"""按设置自动编辑军队（新版“战斗 → 编辑军队”页）：普通兵种、法术、攻城器械。

新版 CoC 部队不再需要训练时间，编辑军队页里的配置就是下一场的军队。
配置来源：设置里的「阵容预设」（主流三星/刷资源阵容），或自定义勾选的兵种/法术/攻城器械。

流程（坐标均为 800×600 参考画布，来自 MuMu 实机截图）：

1. 主世界主页 → 点“战斗” → OCR 确认左下“编辑军队”后点击 → OCR 确认“我的军队”页；
2. 对普通兵种、法术、攻城器械三个分区依次：
   a. 先打开该分区列表（满员时卡片是灰色也能识别）确认要配的单位都在，缺关键单位就不动这个分区；
   b. 读该分区容量，用垃圾桶清空（OCR 确认“移除部队”弹窗后只放行这一次“确定”）；
   c. 点“点击以编辑”打开列表，按卡片模板找到单位并添加；普通兵种批量连点，
      法术/攻城器械逐个点击并复核容量；
   d. 返回键收起列表，复核容量；
3. 关闭编辑页回到主世界主页。英雄不改动。

安全边界：只点击编辑页自己的控件（战斗菜单入口、编辑军队、垃圾桶/确认、卡片、关闭）。
不会点击“强化军队/强化英雄”、卡片的 i 详情（里面有升级按钮）、超级兵种激活或任何宝石按钮；
每一步都先确认页面，确认不了就按返回键退出，不再继续点击。
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

import cv2
import numpy as np

from 任务流程.基础任务框架 import 基础任务, 任务上下文
from 任务流程.世界跳转.新版界面坐标 import 主世界战斗菜单, 锚定
from 任务流程.军队配置 import 兵种资料
from 任务流程.军队配置 import 阵容预设 as 预设

状态类型 = "自动配兵"

编辑军队按钮 = (62, 565)
编辑军队按钮OCR区域 = (10, 545, 120, 588)
编辑页标题OCR区域 = (100, 40, 270, 82)
# OCR 常把“軍隊”的“隊”读成“隧”，只用前两个字符判断。
编辑页标题关键字 = ("我的軍", "我的军")
关闭按钮 = (772, 55)
兵种列表区域 = (0, 340, 800, 590)
列表滑动Y = 450
卡片匹配阈值 = 0.85
最多尝试次数 = 2
满员比例 = 0.95

# ---- 竞赛临时换兵：编辑页主页面“当前阵容”快照 ----
# 状态库里保存换兵前的实际阵容；任务完成/变化/失败时按它逐个数量精确恢复。
快照状态类型 = "竞赛原阵容快照"
最近确认攻城状态类型 = "最近确认攻城阵容"
最近确认攻城有效秒 = 24 * 3600
# 编辑页主页面（列表收起）上已配单位卡片的左上角与可容纳卡片数（800×600 实机截图
# tests/fixtures/coc_army_config_live_ui.png 标定）：卡宽约 58、间距 64，卡片靠左排列。
阵容卡片槽 = {
    "兵种": (350, 163, 7),
    "法术": (350, 312, 4),
    "攻城": (637, 312, 2),
}
阵容卡片间距 = 64
# 主页面卡片比列表卡片小：列表模板缩放到这些宽度后再在卡片区域内匹配。
# 竞赛原阵容页的攻城卡片宽度约 34px；旧尺度会让攻城气球/飞艇分差停在 0.05 左右。
阵容模板宽度 = (34, 36, 38, 40, 42, 44, 46)
阵容识别最低分 = 0.60
# 最佳与第二名的最小差距。攻城器械模板来自另一种卡面，实机夹具里差距只有 0.047；
# 攻城人口都是 1，合计复核核不了种类，因此不放宽。认不准时须先找到可恢复来源。
阵容识别最小差距 = {"兵种": 0.08, "法术": 0.08, "攻城": 0.08}
空卡片灰度标准差 = 20.0

_主页卡片模板缓存: dict[tuple[str, int], list[np.ndarray]] = {}


def _主页卡片模板(名称: str, 宽: int) -> list[np.ndarray]:
    键 = (名称, 宽)
    if 键 not in _主页卡片模板缓存:
        根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        模板 = []
        for 文件名 in (f"{名称}.png", f"{名称}_彩.png"):
            路径 = os.path.join(根, "img", "军队卡片", 文件名)
            if not os.path.isfile(路径):
                continue
            图 = cv2.imdecode(np.fromfile(路径, dtype=np.uint8), cv2.IMREAD_COLOR)
            if 图 is None:
                continue
            比例 = 宽 / 图.shape[1]
            模板.append(cv2.resize(图, None, fx=比例, fy=比例, interpolation=cv2.INTER_AREA))
        _主页卡片模板缓存[键] = 模板
    return _主页卡片模板缓存[键]


def 阵容卡片区域(区: str, 序号: int) -> tuple[int, int, int, int]:
    x0, y0, _ = 阵容卡片槽[区]
    x = x0 + 序号 * 阵容卡片间距
    return x - 6, y0 - 4, x + 64, y0 + 84


def 阵容数量区域(区: str, 序号: int) -> tuple[int, int, int, int]:
    x0, y0, _ = 阵容卡片槽[区]
    x = x0 + 序号 * 阵容卡片间距
    return x - 2, y0 - 2, x + 42, y0 + 24


def 识别阵容卡片(图像, 区: str, 序号: int) -> tuple[str | None, str]:
    """返回 (单位名, 说明)；疑似空槽返回 ("", 说明)，无法可靠识别返回 (None, 原因)。

    说明里带最佳分/第二名/灰度标准差，写进日志方便实机标定。疑似空槽还要由调用方
    再确认数量区没有 “x数字” 才算真的空。
    """
    x1, y1, x2, y2 = 阵容卡片区域(区, 序号)
    if 图像 is None or 图像.shape[0] < y2 or 图像.shape[1] < x2:
        return None, "截图尺寸不足"
    卡 = 图像[y1:y2, x1:x2]
    标准差 = float(cv2.cvtColor(卡, cv2.COLOR_BGR2GRAY).std())
    if 标准差 < 空卡片灰度标准差:
        return "", f"第{序号 + 1}格疑似空(std={标准差:.1f})"
    分数表: dict[str, float] = {}
    for 名 in 分区单位(区):
        for 宽 in 阵容模板宽度:
            for 模板 in _主页卡片模板(名, 宽):
                if 模板.shape[0] > 卡.shape[0] or 模板.shape[1] > 卡.shape[1]:
                    continue
                分数 = float(cv2.minMaxLoc(cv2.matchTemplate(卡, 模板, cv2.TM_CCOEFF_NORMED))[1])
                if 分数 > 分数表.get(名, -1.0):
                    分数表[名] = 分数
    排名 = sorted(分数表.items(), key=lambda 项: -项[1])
    if not 排名:
        return None, f"第{序号 + 1}张卡片没有可用模板(std={标准差:.1f})"
    次名, 次分 = 排名[1] if len(排名) > 1 else ("无", 0.0)
    明细 = f"{排名[0][0]}={排名[0][1]:.3f}/{次名}={次分:.3f}/std={标准差:.1f}"
    if 排名[0][1] < 阵容识别最低分:
        return None, f"第{序号 + 1}张卡片匹配分数过低({明细})"
    if 排名[0][1] - 次分 < 阵容识别最小差距.get(区, 0.08):
        return None, f"第{序号 + 1}张卡片无法区分({明细})"
    return 排名[0][0], 明细


def 解析卡片数量(文本: str) -> int | None:
    文本 = (
        str(文本 or "").replace(" ", "").replace("X", "x").replace("×", "x")
        .replace("O", "0").replace("o", "0").replace("I", "1").replace("l", "1")
    )
    匹配 = re.search(r"x(\d{1,3})", 文本) or re.fullmatch(r"(\d{1,3})", 文本)
    if not 匹配:
        return None
    数 = int(匹配.group(1))
    return 数 if 数 > 0 else None


def 阵容占用(单位: dict[str, int]) -> int | None:
    总 = 0
    for 名, 数 in 单位.items():
        人口 = 兵种资料.人口(名)
        if 人口 <= 0:
            return None
        总 += 人口 * int(数)
    return 总


def 有待恢复竞赛快照(上下文) -> bool:
    快照 = 读取竞赛快照(上下文)
    return bool(快照.get("分区"))


def 读取竞赛快照(上下文) -> dict:
    """内存优先；首次读取时从状态库加载（重启后也能恢复）。"""
    快照 = getattr(上下文, "_竞赛原阵容快照", None)
    if isinstance(快照, dict):
        return 快照
    快照 = {}
    try:
        状态 = 上下文.数据库.获取最新完整状态(上下文.机器人标志)
        数据 = getattr(状态, "状态数据", None)
        记录 = 数据.get(快照状态类型) if isinstance(数据, dict) else None
        if isinstance(记录, dict) and isinstance(记录.get("分区"), dict):
            快照 = 记录
    except Exception:
        # 读库异常不缓存：下一轮再读，避免本次运行再也看不到已落盘的快照。
        return {}
    try:
        上下文._竞赛原阵容快照 = 快照
    except Exception:
        pass
    return 快照


def 保存竞赛快照(上下文, 快照: dict) -> bool:
    """写内存与状态库；写库失败返回 False（调用方在动军队前据此放弃换兵）。"""
    上下文._竞赛原阵容快照 = dict(快照 or {})
    try:
        上下文.数据库.更新状态(上下文.机器人标志, 快照状态类型, dict(快照 or {}))
    except Exception:
        return False
    return True


@dataclass(frozen=True)
class 分区:
    名称: str
    人口OCR区域: tuple[int, int, int, int]
    垃圾桶: tuple[int, int]
    编辑区: tuple[int, int]       # 主页面上点击打开该分区的卡片列表
    批量点击: bool                # 普通兵种数量多用批量连点；法术/攻城逐个点击复核


# 编辑页主页面（列表收起时）的位置；打开法术/攻城列表时整个面板会上移，
# 所以每个分区都从主页面开始操作，结束时用返回键收起列表。
分区表 = {
    "兵种": 分区("兵种", (360, 126, 470, 154), (772, 140), (565, 200), True),
    "法术": 分区("法术", (362, 276, 432, 302), (612, 288), (480, 352), False),
    "攻城": 分区("攻城", (646, 276, 712, 302), (772, 288), (745, 360), False),
}


def 配置签名(配置) -> str:
    """配置可以是兵种列表（旧用法）或 {分区: {单位: 数量/权重}}。"""
    if isinstance(配置, dict):
        return "|".join(
            f"{区}:" + "+".join(f"{名}{配置[区][名]}" for 名 in sorted(配置[区]))
            for 区 in sorted(配置) if 配置[区]
        )
    return "+".join(sorted(map(str, 配置 or [])))


def 解析人口(文本: str) -> tuple[int, int] | None:
    匹配 = re.search(r"(\d{1,3})\s*[/／]\s*(\d{1,3})", str(文本 or "").replace(" ", ""))
    if not 匹配:
        return None
    当前, 上限 = int(匹配.group(1)), int(匹配.group(2))
    return (当前, 上限) if 0 <= 当前 <= 上限 <= 999 and 上限 > 0 else None


_模板缓存: dict[str, list[np.ndarray]] = {}


def 读取卡片模板(名称: str) -> list[np.ndarray] | None:
    """返回该单位的灰度模板列表（灰色卡、彩色卡各一张，至少一张）；没有则 None。"""
    if 名称 not in _模板缓存:
        根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        模板 = []
        for 文件名 in (f"{名称}.png", f"{名称}_彩.png"):
            路径 = os.path.join(根, "img", "军队卡片", 文件名)
            if os.path.isfile(路径):
                图 = cv2.imdecode(np.fromfile(路径, dtype=np.uint8), cv2.IMREAD_COLOR)
                if 图 is not None:
                    模板.append(cv2.cvtColor(图, cv2.COLOR_BGR2GRAY))
        _模板缓存[名称] = 模板
    return _模板缓存[名称] or None


def 查找兵种卡片(图像, 名称: str) -> tuple[tuple[int, int], float] | None:
    """在列表区域里找该单位完整可见的卡片，返回 (点击点=头像中心, 分数)。"""
    模板列表 = 读取卡片模板(名称)
    if not 模板列表:
        return None
    x1, y1, x2, y2 = 兵种列表区域
    灰 = cv2.cvtColor(图像[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    最佳 = None
    for 模板 in 模板列表:
        高, 宽 = 模板.shape
        if 高 > 灰.shape[0] or 宽 > 灰.shape[1]:
            continue
        结果 = cv2.matchTemplate(灰, 模板, cv2.TM_CCOEFF_NORMED)
        # 只接受整张卡在画面内的位置：左右各留出卡片边框宽度。
        结果[:, :8] = -1
        结果[:, max(0, 结果.shape[1] - 24):] = -1
        _, 分数, _, (x, y) = cv2.minMaxLoc(结果)
        if 分数 >= 卡片匹配阈值 and (最佳 is None or 分数 > 最佳[1]):
            最佳 = ((x + x1 + 宽 // 2, y + y1 + 高 // 2), float(分数))
    return 最佳


def 分区单位(区: str) -> tuple[str, ...]:
    if 区 == "兵种":
        return 兵种资料.可选兵种名称
    if 区 == "法术":
        return 兵种资料.可选法术名称
    return 兵种资料.攻城列表


def 列表已打开(图像, 区: str = "兵种") -> bool:
    """底部列表里至少认出一张该分区的已知卡片，才算列表已打开。"""
    return any(查找兵种卡片(图像, 名) for 名 in 分区单位(区) if 读取卡片模板(名))


# 已有卡片模板的兵种及其人口（测试与旧接口使用）
兵种人口 = {资料.名称: 资料.人口 for 资料 in 兵种资料.兵种列表 if 读取卡片模板(资料.名称)}


def 期望配置(设置, 配置覆盖: dict | None = None) -> dict | None:
    """把设置换算成 {分区: {单位: 权重或个数}}；未开启或没有内容返回 None。

    兵种给权重（按军营人口换算个数），法术给个数，攻城器械给 1 个。
    """
    if isinstance(配置覆盖, dict):
        覆盖 = {}
        for 区, 单位 in 配置覆盖.items():
            if not isinstance(单位, dict):
                continue
            清理 = {}
            for 名, 数 in 单位.items():
                try:
                    数 = float(数)
                except (TypeError, ValueError):
                    continue
                if 数 > 0:
                    清理[str(名)] = 数
            if 清理:
                覆盖[str(区)] = 清理
        return 覆盖 or None
    if not getattr(设置, "是否自动配置军队", False):
        return None
    预设名 = getattr(设置, "阵容预设", 预设.自定义) or 预设.自定义
    if 预设名 in 预设.预设映射:
        方案 = 预设.预设映射[预设名]
        配置 = {"兵种": dict(方案.兵种权重), "法术": dict(方案.法术个数)}
        if 方案.攻城:
            配置["攻城"] = {方案.攻城: 1}
        return 配置
    兵种 = list(getattr(设置, "配兵兵种", []) or [])
    法术 = list(getattr(设置, "配兵法术", []) or [])
    攻城 = str(getattr(设置, "配兵攻城", "") or "")
    配置 = {}
    if 兵种:
        配置["兵种"] = {名: 兵种资料.兵种映射[名].权重 for 名 in 兵种 if 名 in 兵种资料.兵种映射}
    if 法术:
        # 自定义法术不指定个数：按勾选顺序轮流各放一个，直到放满法术容量。
        配置["法术"] = {名: 99 for 名 in 法术}
    if 攻城:
        配置["攻城"] = {攻城: 1}
    return {区: 单位 for 区, 单位 in 配置.items() if 单位} or None


def 关键单位(设置) -> tuple[str, ...]:
    方案 = 预设.预设映射.get(getattr(设置, "阵容预设", ""))
    return 方案.关键兵种 if 方案 else ()


class 编辑军队任务(基础任务):
    """按设置编辑军队。失败时只退出编辑页，不影响后续刷资源。"""

    def __init__(self, 上下文: 任务上下文):
        super().__init__(上下文)

    def _期望配置(self) -> dict | None:
        return 期望配置(
            getattr(self.上下文, "设置", None),
            getattr(self.上下文, "_部落竞赛配兵配置覆盖", None),
        )

    # ------------------------------------------------------------ 对外入口
    def 需要配置(self) -> bool:
        配置 = self._期望配置()
        if not 配置:
            return False
        签名 = 配置签名(配置)
        if getattr(self.上下文, "_本次运行已配兵签名", None) == 签名:
            return False
        # 上次成功配好的就是这套（记录在数据库，重启也保留），游戏会自动补满同样的军队，
        # 不再清空重配；只有改了预设/勾选（签名变化）才重新进编辑页。
        if self._已记录签名() == 签名:
            self.上下文._本次运行已配兵签名 = 签名
            置状态 = getattr(self.上下文, "置脚本状态", None)
            if callable(置状态):
                置状态("自动配兵：游戏里已是上次配好的这套军队，跳过重配")
            return False
        # 同一配置本次运行最多尝试 2 次，失败后不再每轮重进编辑页。
        尝试 = getattr(self.上下文, "_本次运行配兵尝试", {}) or {}
        return 尝试.get(签名, 0) < 最多尝试次数

    def _已记录签名(self) -> str | None:
        try:
            状态 = self.上下文.数据库.获取最新完整状态(self.上下文.机器人标志)
            记录 = (getattr(状态, "状态数据", {}) or {}).get(状态类型) or {}
            return 记录.get("签名")
        except Exception:
            return None

    def 执行(self) -> bool:
        上下文 = self.上下文
        if isinstance(getattr(上下文, "_部落竞赛配兵配置覆盖", None), dict):
            return self._竞赛快照换兵()
        快照 = 读取竞赛快照(上下文)
        if 快照.get("分区"):
            # 竞赛任务已完成/变化/关闭：不管是否开启自动配兵，都按换兵前快照精确恢复。
            return self._按快照恢复(快照, "竞赛任务已完成或已变化")
        if not self.需要配置():
            配置 = self._期望配置()
            上下文._最近自动配兵执行结果 = {
                "签名": 配置签名(配置), "成功": True, "已恢复": False,
            }
            return True
        设置 = 上下文.设置
        配置 = self._期望配置()
        签名 = 配置签名(配置)
        关键 = 关键单位(设置)
        无模板 = [名 for 单位 in 配置.values() for 名 in 单位 if 读取卡片模板(名) is None]
        if 无模板:
            上下文.置脚本状态(
                f"自动配兵：{'、'.join(兵种资料.显示名(名) for 名 in 无模板)} 暂无卡片模板，配兵时跳过"
            )
        配置 = {区: {名: 值 for 名, 值 in 单位.items() if 名 not in 无模板} for 区, 单位 in 配置.items()}
        配置 = {区: 单位 for 区, 单位 in 配置.items() if 单位}
        缺关键 = [名 for 名 in 关键 if 名 in 无模板]
        if not 配置 or 缺关键:
            上下文._本次运行已配兵签名 = 签名
            上下文.置脚本状态(
                "自动配兵："
                + (f"预设缺少关键兵种 {'、'.join(缺关键)} 的模板，" if 缺关键 else "勾选的单位都没有卡片模板，")
                + "保持游戏里现有军队"
            )
            上下文._最近自动配兵执行结果 = {"签名": 签名, "成功": False, "已恢复": False}
            return True

        尝试 = dict(getattr(上下文, "_本次运行配兵尝试", {}) or {})
        尝试[签名] = 尝试.get(签名, 0) + 1
        上下文._本次运行配兵尝试 = 尝试
        预设名 = getattr(设置, "阵容预设", 预设.自定义)
        上下文.置脚本状态(
            f"自动配兵：开始配置【{预设名}】"
            + "；".join(f"{区}：{'、'.join(兵种资料.显示名(名) for 名 in 单位)}" for 区, 单位 in 配置.items())
        )
        try:
            结果 = self._配置流程(配置, 关键)
        except Exception as 异常:  # 任何异常都退出编辑页，交给刷资源继续
            上下文.置脚本状态(f"[警告] 自动配兵异常，保持当前军队：{异常}", 60)
            结果 = None
        finally:
            try:
                self._退出到主世界()
            finally:
                self._结束编辑状态()
        if 结果 is None:
            上下文._最近自动配兵执行结果 = {"签名": 签名, "成功": False, "已恢复": False}
            return not getattr(上下文, "页面恢复失败", False)
        人口 = 结果.get("人口")
        if "兵种" in 配置 and (not 人口 or 人口[0] < 人口[1] * 满员比例):
            上下文.置脚本状态(
                f"[警告] 自动配兵未填满军营（{人口[0] if 人口 else '?'}/{人口[1] if 人口 else '?'}），"
                f"本次运行还会再试 {最多尝试次数 - 尝试[签名]} 次"
            )
            上下文._最近自动配兵执行结果 = {"签名": 签名, "成功": False, "已恢复": False}
            return True
        上下文._本次运行已配兵签名 = 签名
        try:
            上下文.数据库.更新状态(上下文.机器人标志, 状态类型, {
                "预设": 预设名, "签名": 签名, "配置": 结果["配置"], "人口": 结果["人口"],
                "分区容量": 结果.get("分区容量"), "时间": int(time.time()),
            })
        except Exception:
            pass
        上下文._最近自动配兵执行结果 = {"签名": 签名, "成功": True, "已恢复": False}
        return True

    # ------------------------------------------------------------ 竞赛快照换兵
    def _竞赛放弃换兵(self, 任务键: str, 原因: str) -> None:
        """不换兵、保持原阵容：本任务不再重试，进攻也不再要求临时关键单位。"""
        上下文 = self.上下文
        上下文.置脚本状态(f"部落竞赛临时换兵取消：{原因}；保持游戏里原阵容不动")
        上下文._部落竞赛配兵配置覆盖 = None
        上下文._竞赛配兵关键单位 = {}
        上下文._部落竞赛配兵任务类型 = ""
        上下文._竞赛配兵任务键 = ""
        上下文._竞赛配兵失败任务键 = 任务键
        上下文._最近自动配兵执行结果 = {"签名": f"竞赛:{任务键}", "成功": False, "已恢复": False}

    def _读取分区阵容(self, 区: str) -> tuple[dict | None, str]:
        """只读：识别编辑页主页面某分区的当前单位与数量，并用容量合计复核。

        返回 ({"单位": {名: 数}, "容量": [当前, 上限]}, "")；任一卡片或数量识别失败、
        或数量×人口合计与容量文字不一致时返回 (None, 原因)。
        """
        容量 = self._读取人口(区)
        if not 容量:
            return None, f"读不到{区}容量"
        图 = self._截图()
        单位: dict[str, int] = {}
        明细: list[str] = []
        _, _, 槽数 = 阵容卡片槽[区]
        for 序号 in range(槽数):
            名, 说明 = 识别阵容卡片(图, 区, 序号)
            数文本 = self._OCR文本(图, 阵容数量区域(区, 序号))
            if 名 == "":
                # 空槽要同时满足：灰度平坦 且 数量区没有 “x数字”。
                if 解析卡片数量(数文本) is not None:
                    return None, f"{区}{说明}，但数量区读到“{数文本}”，不当空槽"
                明细.append(说明)
                break
            if 名 is None:
                return None, f"{区}{说明}"
            数 = 解析卡片数量(数文本)
            if 数 is None:
                return None, f"{区}第{序号 + 1}张卡片（{兵种资料.显示名(名)}）数量读不到"
            if 名 in 单位:
                return None, f"{区}出现两张{兵种资料.显示名(名)}卡片，无法确认"
            单位[名] = 数
            明细.append(f"{说明}×{数}")
        self.上下文.置脚本状态(f"阵容识别明细（{区}）：" + ("；".join(明细) or "无卡片"))
        占用 = 阵容占用(单位)
        if 占用 is None or 占用 != 容量[0]:
            return None, (
                f"{区}识别合计 {占用 if 占用 is not None else '?'} 与容量 {容量[0]}/{容量[1]} 不一致"
                "（可能有卡片在可视范围外或识别错误）"
            )
        快照 = {"单位": 单位, "容量": list(容量)}
        if 区 == "攻城":
            self._缓存最近确认攻城阵容(快照)
        return 快照, ""

    def _缓存最近确认攻城阵容(self, 快照: dict) -> None:
        """按账号保存最近一次由编辑页高置信识别并经容量复核的攻城阵容。"""
        上下文 = self.上下文
        try:
            # 已有待恢复快照时当前攻城器械可能是临时任务配置，不能覆盖长期基准。
            if 读取竞赛快照(上下文).get("分区"):
                return
            上下文.数据库.更新状态(
                上下文.机器人标志,
                最近确认攻城状态类型,
                {
                    "单位": dict(快照.get("单位") or {}),
                    "容量": list(快照.get("容量") or [0, 3]),
                    "来源": "编辑页高置信识别",
                    "时间": int(time.time()),
                },
            )
        except Exception:
            # 缓存只是恢复来源之一；写库失败时，后续不确定识别仍按 fail-closed 处理。
            return

    def _竞赛攻城恢复快照(self) -> tuple[dict | None, str]:
        """依次从账号设置和最近一次高置信识别读取可确认的攻城恢复基准。"""
        def 清理(单位数据, 容量数据=None):
            if not isinstance(单位数据, dict):
                return None
            单位 = {}
            try:
                for 名, 数 in 单位数据.items():
                    名, 数 = str(名), int(数)
                    if 名 not in 兵种资料.攻城列表 or not 0 <= 数 <= 3:
                        return None
                    if 数:
                        单位[名] = 数
            except (TypeError, ValueError, OverflowError):
                return None
            try:
                容量 = [int(容量数据[0]), int(容量数据[1])]
            except (TypeError, ValueError, IndexError, OverflowError):
                容量 = [sum(单位.values()), 3]
            if 容量[1] <= 0 or not 0 <= 容量[0] <= 容量[1] or sum(单位.values()) != 容量[0]:
                return None
            return {"单位": 单位, "容量": 容量}

        设置配置 = 期望配置(getattr(self.上下文, "设置", None)) or {}
        设置快照 = 清理(设置配置.get("攻城"), [sum((设置配置.get("攻城") or {}).values()), 3])
        if 设置快照 is not None:
            return 设置快照, "设置"
        try:
            状态 = self.上下文.数据库.获取最新完整状态(self.上下文.机器人标志)
            记录 = (getattr(状态, "状态数据", {}) or {}).get(最近确认攻城状态类型)
            if isinstance(记录, dict):
                缓存快照 = 清理(记录.get("单位"), 记录.get("容量"))
                if 缓存快照 is not None:
                    try:
                        记录时间 = float(记录.get("时间"))
                    except (TypeError, ValueError):
                        记录时间 = None
                    现在 = time.time()
                    if (
                        记录时间 is not None
                        and 记录时间 > 0
                        and -60 <= 现在 - 记录时间 <= 最近确认攻城有效秒
                    ):
                        return 缓存快照, "最近高置信识别"
                    # 缓存缺失时间戳或已超过 24 小时 TTL：不能确认为当前攻城配置，
                    # 写入“不确定”标记，交由下游防线拒绝换兵/回滚。
                    return {**缓存快照, "不确定": True, "来源": "过期缓存"}, "过期缓存"
        except Exception:
            pass
        return None, ""

    @staticmethod
    def _阵容描述(单位: dict) -> str:
        return "、".join(f"{兵种资料.显示名(名)}×{数}" for 名, 数 in 单位.items()) or "空"

    def _进入编辑页(self) -> bool:
        if not self._确认主世界主页():
            self.上下文.置脚本状态("部落竞赛换兵：未确认主世界主页，不进入编辑军队")
            return False
        return self._打开编辑页()

    def _离开编辑页(self) -> bool:
        """关闭编辑页并确认回到主世界主页。"""
        try:
            self._退出到主世界()
        finally:
            self._结束编辑状态()
        try:
            return bool(self._确认主世界主页())
        except Exception:
            return False

    def _竞赛快照换兵(self) -> bool:
        """竞赛临时换兵：先读实际阵容快照（完整才换），失败按快照精确恢复。"""
        上下文 = self.上下文
        任务键 = str(getattr(上下文, "_竞赛配兵任务键", "") or "")
        类型 = str(getattr(上下文, "_部落竞赛配兵任务类型", "") or "")
        关键 = {
            区: list(dict.fromkeys(名单))
            for 区, 名单 in (getattr(上下文, "_竞赛配兵关键单位", {}) or {}).items() if 名单
        }
        if getattr(上下文, "_竞赛配兵失败任务键", "") == 任务键 and 任务键:
            self._竞赛放弃换兵(任务键, "本任务换兵之前已失败")
            return True
        快照 = 读取竞赛快照(上下文)
        if 任务键 and (
            getattr(上下文, "_竞赛临时阵容已应用键", "") == 任务键
            or (快照.get("已应用") and 快照.get("任务键") == 任务键)
        ):
            上下文._竞赛临时阵容已应用键 = 任务键
            上下文._最近自动配兵执行结果 = {"签名": f"竞赛:{任务键}", "成功": True, "已恢复": False}
            return True
        if 快照.get("分区"):
            # 换了任务：先回到换兵前的阵容，再按新任务重新拍快照。
            if not self._按快照恢复(快照, "竞赛任务已变化"):
                return False
            if not (getattr(上下文, "_最近自动配兵执行结果", {}) or {}).get("已恢复"):
                self._竞赛放弃换兵(任务键, "上一个任务的原阵容没能恢复")
                return True
        if not 关键 or 类型 not in {"拆墙", "指定兵种"}:
            self._竞赛放弃换兵(任务键, "没有需要临时加入的单位")
            return True
        目标区 = [区 for 区 in ("兵种", "法术", "攻城") if 区 in 关键]

        from 任务流程.活动.竞赛配兵策略 import 按快照构建临时阵容

        恢复失败 = False
        try:
            if not self._进入编辑页():
                上下文.置脚本状态("部落竞赛换兵：没确认到编辑军队页，不换兵")
                已回主页 = self._离开编辑页()
                self._竞赛放弃换兵(任务键, "编辑军队页未确认")
                if not 已回主页:
                    上下文.页面恢复失败 = True
                    return False
                return True
            分区快照 = {}
            for 区 in list(目标区):
                读到, 原因 = self._读取分区阵容(区)
                if 读到 is None and 区 == "攻城":
                    # 主人 2026-11-27 群聊原话：“竞赛可以跟着任务自由调整配兵，前提是能完成任务、不影响其他”。
                    # 所以只在已有明确恢复来源时临时替换攻城器械，结束后必须恢复；没有来源就 fail-closed。
                    if 类型 == "指定兵种" and 关键.get("攻城"):
                        恢复来源快照, 来源 = self._竞赛攻城恢复快照()
                        if 恢复来源快照 is not None and not 恢复来源快照.get("不确定"):
                            分区快照[区] = 恢复来源快照
                            上下文.置脚本状态(
                                f"部落竞赛换兵：攻城区原阵容识别不确定（{原因}）；"
                                f"按恢复来源={来源}保存恢复值：{self._阵容描述(恢复来源快照['单位'])}"
                            )
                            continue
                        if 恢复来源快照 is not None:
                            上下文.置脚本状态(
                                f"部落竞赛换兵：攻城区原阵容识别不确定（{原因}）；"
                                f"恢复来源={来源}已标记为不确定，无法作为安全恢复基准，只放弃攻城区换兵"
                            )
                        else:
                            上下文.置脚本状态(
                                f"部落竞赛换兵：攻城区原阵容识别不确定（{原因}），"
                                "没有可确认的攻城恢复来源；只放弃攻城区换兵"
                            )
                    else:
                        上下文.置脚本状态(f"部落竞赛换兵：攻城区识别不确定（{原因}），只放弃攻城区换兵")
                    目标区.remove(区)
                    关键.pop(区, None)
                    continue
                if 读到 is None:
                    已回主页 = self._离开编辑页()
                    self._竞赛放弃换兵(任务键, f"原阵容快照不完整（{原因}）")
                    if not 已回主页:
                        上下文.页面恢复失败 = True
                        return False
                    return True
                分区快照[区] = 读到
            if not 目标区:
                已回主页 = self._离开编辑页()
                self._竞赛放弃换兵(任务键, "要求单位所在分区识别不确定")
                if not 已回主页:
                    上下文.页面恢复失败 = True
                    return False
                return True
            上下文.置脚本状态(
                "部落竞赛换兵：已读取原阵容快照 "
                + "；".join(f"{区} {self._阵容描述(值['单位'])}（{值['容量'][0]}/{值['容量'][1]}）"
                           for 区, 值 in 分区快照.items())
            )
            文本 = str(getattr(上下文, "_竞赛配兵任务文本", "") or "")
            临时, 原因 = 按快照构建临时阵容(类型, 文本, 关键, 分区快照)
            if 临时 is None:
                已回主页 = self._离开编辑页()
                if 原因.startswith("已满足"):
                    上下文.置脚本状态(f"部落竞赛换兵：{原因}，不需要改动军队")
                    上下文._竞赛临时阵容已应用键 = 任务键
                    上下文._最近自动配兵执行结果 = {
                        "签名": f"竞赛:{任务键}", "成功": True, "已恢复": False,
                    }
                else:
                    self._竞赛放弃换兵(任务键, 原因)
                if not 已回主页:
                    上下文.页面恢复失败 = True
                    return False
                return True
            # 先落盘快照再动军队：中途断电/重启也能按快照恢复。
            快照 = {"任务键": 任务键, "类型": 类型, "分区": 分区快照, "已应用": False,
                    "时间": int(time.time())}
            if not 保存竞赛快照(上下文, 快照):
                上下文._竞赛原阵容快照 = {}
                已回主页 = self._离开编辑页()
                self._竞赛放弃换兵(任务键, "原阵容快照写入状态库失败，断电后无法恢复")
                if not 已回主页:
                    上下文.页面恢复失败 = True
                    return False
                return True
            for 区 in 目标区:
                if 区 not in 临时:
                    continue
                上下文.置脚本状态(f"部落竞赛换兵（{区}）：{self._阵容描述(临时[区])}")
                结果 = self._配置分区(区, 临时[区], tuple(关键[区]), tuple(关键[区]), 精确=True)
                if 结果 is None:
                    上下文.置脚本状态(f"[警告] 部落竞赛换兵：{区}未确认，按快照恢复原阵容")
                    原阵容不确定 = any(
                        bool(值.get("不确定")) for 值 in 分区快照.values() if isinstance(值, dict)
                    )
                    if 原阵容不确定:
                        恢复失败 = True
                        上下文.置脚本状态("攻城区原阵容不确定，换兵失败后不能安全回滚；停止进攻并保留快照")
                    else:
                        恢复失败 = not self._在编辑页按快照恢复(分区快照)
                    容量 = self._读取人口("兵种") if 恢复失败 else None
                    已回主页 = self._离开编辑页()
                    if 恢复失败 or not 已回主页:
                        self._竞赛放弃换兵(任务键, "临时换兵未确认")
                        return self._处理恢复失败(
                            快照, "临时换兵失败后" + ("恢复未确认" if 恢复失败 else "未确认回到主页"),
                            已回主页, 容量,
                        )
                    保存竞赛快照(上下文, {})
                    self._竞赛放弃换兵(任务键, "临时换兵未确认，已按快照恢复原阵容")
                    上下文._最近自动配兵执行结果 = {
                        "签名": f"竞赛:{任务键}", "成功": False, "已恢复": True,
                    }
                    return True
            if not self._离开编辑页():
                上下文.页面恢复失败 = True
                上下文.置脚本状态("[严重] 部落竞赛换兵后未确认回到主世界主页，停止后续点击")
                return False
        except Exception as 异常:
            上下文.置脚本状态(f"[警告] 部落竞赛换兵异常：{异常}")
            快照 = 读取竞赛快照(上下文)
            self._竞赛放弃换兵(任务键, f"换兵异常（{异常}）")
            if 快照.get("分区"):
                if any(
                    bool(值.get("不确定")) for 值 in 快照["分区"].values() if isinstance(值, dict)
                ):
                    已回主页 = self._离开编辑页()
                    return self._处理恢复失败(快照, "换兵异常且攻城原阵容不确定", 已回主页, None)
                self._离开编辑页()
                return self._按快照恢复(快照, "临时换兵异常")
            self._离开编辑页()
            return not getattr(上下文, "页面恢复失败", False)
        快照["已应用"] = True
        保存竞赛快照(上下文, 快照)
        上下文._竞赛临时阵容已应用键 = 任务键
        上下文._最近自动配兵执行结果 = {"签名": f"竞赛:{任务键}", "成功": True, "已恢复": False}
        上下文.置脚本状态("部落竞赛临时阵容已确认；任务完成或变化后按快照恢复原阵容")
        return True

    def _在编辑页按快照恢复(self, 分区快照: dict) -> bool:
        """已在编辑页：逐区比对，与快照一致的分区不动，不一致的按快照精确重配。"""
        上下文 = self.上下文
        for 区 in ("兵种", "法术", "攻城"):
            if 区 not in 分区快照:
                continue
            当前区快照 = 分区快照.get(区) or {}
            if isinstance(当前区快照, dict) and 当前区快照.get("不确定"):
                上下文.置脚本状态(
                    "[严重] 部落竞赛恢复：旧快照中的攻城区原阵容不确定，无法安全恢复；保留快照并停止进攻"
                )
                return False
            目标 = {str(名): int(数) for 名, 数 in (当前区快照.get("单位") or {}).items()}
            当前, _ = self._读取分区阵容(区)
            if 当前 is not None and 当前["单位"] == 目标:
                continue
            if self._已请求停止():
                return False
            上下文.置脚本状态(f"部落竞赛恢复（{区}）：{self._阵容描述(目标)}")
            if not 目标:
                if not self._清空分区(区):
                    return False
                continue
            if self._配置分区(区, 目标, (), (), 精确=True, 缺失替补=True) is None:
                return False
        return True

    def _按快照恢复(self, 快照: dict, 原因: str) -> bool:
        上下文 = self.上下文
        分区快照 = 快照.get("分区") or {}
        上下文.置脚本状态(f"{原因}，按换兵前快照恢复原阵容")
        try:
            if not self._进入编辑页():
                已回主页 = self._离开编辑页()
                return self._处理恢复失败(快照, "没确认到编辑军队页", 已回主页, None)
            成功 = self._在编辑页按快照恢复(分区快照)
        except Exception as 异常:
            上下文.置脚本状态(f"[警告] 原阵容恢复异常：{异常}")
            成功 = False
        容量 = None
        if not 成功:
            try:
                容量 = self._读取人口("兵种")  # 只读：决定连续失败后能否带当前军队继续
            except Exception:
                容量 = None
        已回主页 = self._离开编辑页()
        if not 成功 or not 已回主页:
            return self._处理恢复失败(
                快照, "恢复未通过数量复核" if not 成功 else "恢复后未确认回到主页", 已回主页, 容量,
            )
        保存竞赛快照(上下文, {})
        上下文._竞赛临时阵容已应用键 = ""
        上下文._最近自动配兵执行结果 = {"签名": "竞赛恢复", "成功": True, "已恢复": True}
        上下文.置脚本状态("已按快照精确恢复原阵容（数量已逐项复核），继续打鱼")
        return True

    def _处理恢复失败(self, 快照: dict, 原因: str, 已回主页: bool, 兵种容量) -> bool:
        """第 1 次失败：保留快照并停机；连续第 2 次：清除快照，绝不无限停机。

        清除后军营是满的且已回主页就带当前军队继续；空/半空或页面不明就停在主页。
        """
        上下文 = self.上下文
        次数 = int((快照 or {}).get("恢复失败次数", 0) or 0) + 1
        if 次数 < 2:
            新快照 = dict(快照 or {})
            新快照["恢复失败次数"] = 次数
            保存竞赛快照(上下文, 新快照)
            return self._恢复失败停止(f"{原因}；第{次数}次")
        保存竞赛快照(上下文, {})
        上下文._竞赛临时阵容已应用键 = ""
        满营 = bool(兵种容量 and 兵种容量[1] > 0 and 兵种容量[0] >= 兵种容量[1] * 满员比例)
        if 已回主页 and 满营:
            上下文._最近自动配兵执行结果 = {"签名": "竞赛恢复", "成功": False, "已恢复": False}
            上下文.置脚本状态(
                f"[严重] 部落竞赛原阵容连续{次数}次恢复失败（{原因}）；已清除快照，"
                f"军营已满（{兵种容量[0]}/{兵种容量[1]}），保持当前军队继续打鱼，请有空时在游戏里检查军队", 60,
            )
            return True
        上下文.页面恢复失败 = True
        上下文._最近自动配兵执行结果 = {"签名": "竞赛恢复", "成功": False, "已恢复": False}
        上下文.置脚本状态(
            f"[严重] 部落竞赛原阵容连续{次数}次恢复失败（{原因}）；已清除快照，"
            f"军营未满或未确认（{兵种容量[0] if 兵种容量 else '?'}/{兵种容量[1] if 兵种容量 else '?'}），"
            "停在主页不进攻，请在游戏里配好军队后重新启动", 60,
        )
        return False

    def _恢复失败停止(self, 原因: str) -> bool:
        """恢复失败绝不带残缺军队进攻：退出编辑页、保留快照，交给引擎安全停在主页。"""
        上下文 = self.上下文
        上下文.页面恢复失败 = True
        上下文._最近自动配兵执行结果 = {"签名": "竞赛恢复", "成功": False, "已恢复": False}
        上下文.置脚本状态(
            f"[严重] 部落竞赛原阵容恢复失败（{原因}）；已停止进攻，快照保留，"
            "请在游戏里检查军队后重新启动", 60,
        )
        return False

    # ------------------------------------------------------------ 流程
    def _配置流程(self, 配置: dict, 关键: tuple[str, ...] = ()) -> dict | None:
        上下文 = self.上下文
        if not self._确认主世界主页():
            上下文.置脚本状态("自动配兵：未确认主世界主页，跳过本次配兵")
            return None
        if not self._打开编辑页():
            return None
        总计划, 分区容量, 兵种容量 = {}, {}, None
        for 区 in ("兵种", "法术", "攻城"):
            if 区 not in 配置:
                continue
            竞赛分区 = tuple(
                (getattr(上下文, "_竞赛配兵关键单位", {}) or {}).get(区, ()) or ()
            )
            关键分区 = tuple(dict.fromkeys(tuple(关键 if 区 == "兵种" else ()) + 竞赛分区))
            结果 = self._配置分区(区, 配置[区], 关键分区, 竞赛分区)
            if 结果 is None:
                if 区 == "兵种" or 关键分区:
                    return None
                continue
            计划, 容量 = 结果
            总计划.update(计划)
            分区容量[区] = list(容量) if 容量 else None
            if 区 == "兵种":
                兵种容量 = 容量
        if "兵种" not in 配置:
            兵种容量 = self._读取人口("兵种")
        return {"配置": 总计划, "人口": list(兵种容量) if 兵种容量 else None, "分区容量": 分区容量}

    def _配置分区(
        self, 区: str, 单位: dict, 关键: tuple[str, ...], 确认关键: tuple[str, ...] = (),
        精确: bool = False, 缺失替补: bool = False,
    ) -> tuple[dict, tuple] | None:
        """一个分区：确认可用 → 清空 → 添加 → 复核。返回 (计划, 容量)；不动该分区时返回 None。

        确认关键：竞赛临时配兵要求的本分区单位，清空前必须已在计划中，添加时逐个单击并以容量变化确认；
        预设关键兵只做可用性检查，仍走原批量添加路径。
        精确：``单位`` 是确切个数（竞赛快照换兵/恢复），任一单位不可用就不清空；添加时不做
        多点补偿，最后按主页面卡片逐项复核数量，只补缺口，多了或对不上即失败。
        缺失替补（只用于按快照恢复）：快照里的单位当前不可用（超级兵种到期等）时，
        按可用单位恢复，缺的人口用快照里其它可用兵补；一个都不可用就保持当前军队不动。
        """
        上下文 = self.上下文
        容量 = self._读取人口(区)
        if 容量 is None:
            上下文.置脚本状态(f"自动配兵：读不到{区}容量，跳过{区}")
            return None
        _, 上限 = 容量
        # a. 清空前先确认单位都在列表里，避免清空后才发现配不了
        if not self._打开列表(区):
            上下文.置脚本状态(f"自动配兵：{区}列表没有打开，跳过{区}")
            return None
        可用 = self._扫描可用(区, list(单位))
        self._收起列表()
        缺少 = [名 for 名 in 单位 if 名 not in 可用]
        if 缺少:
            上下文.置脚本状态(
                f"自动配兵：{区}列表里没找到 {'、'.join(兵种资料.显示名(名) for 名 in 缺少)}"
                "（未解锁或超级兵种未激活），跳过这些单位"
            )
        缺关键 = [名 for 名 in 关键 if 名 in 缺少]
        if 精确 and 缺少 and 缺失替补:
            单位 = self._替补不可用单位(区, 单位, 可用, 上限)
            if not 单位:
                上下文.置脚本状态(
                    f"[警告] 部落竞赛恢复：快照里{区}单位当前都不可用，{区}保持当前军队不动"
                )
                return {}, tuple(容量)
            可用 = [名 for 名 in 单位 if 名 in 可用]
        elif 精确 and 缺少:
            上下文.置脚本状态(f"自动配兵：{区}精确配置缺少单位，{区}保持不动")
            return None
        if 缺关键 or not 可用:
            上下文.置脚本状态(
                f"自动配兵：缺少{'关键单位 ' + '、'.join(缺关键) if 缺关键 else '可用单位'}，{区}保持不动"
            )
            return None
        人口表 = {名: 兵种资料.人口(名) for 名 in 可用}
        if 精确:
            计划 = {名: int(单位[名]) for 名 in 可用 if int(单位[名]) > 0}
            占用 = 阵容占用(计划)
            if 占用 is None or 占用 > 上限:
                上下文.置脚本状态(f"自动配兵：{区}精确配置占用 {占用} 超过容量 {上限}，{区}保持不动")
                return None
            目标 = dict(计划)
        elif 区 == "兵种":
            计划 = 兵种资料.按权重分配({名: 单位[名] for 名 in 可用}, 上限, 人口表)
        else:
            计划 = self._按个数分配({名: 单位[名] for 名 in 可用}, 上限, 人口表)
        if not 计划:
            上下文.置脚本状态(f"自动配兵：{区}容量 {上限} 放不下所选单位，{区}保持不动")
            return None
        不在计划 = [名 for 名 in dict.fromkeys(确认关键) if 计划.get(名, 0) <= 0]
        if 不在计划:
            上下文.置脚本状态(
                f"自动配兵：关键单位{'、'.join(不在计划)}不在{区}计划中，{区}保持不动"
            )
            return None
        上下文.置脚本状态(
            f"自动配兵计划（{区}）：" + "、".join(f"{兵种资料.显示名(名)}×{数}" for 名, 数 in 计划.items())
            + f"（容量 {上限}）"
        )
        # b. 清空
        if not self._清空分区(区):
            上下文.置脚本状态(f"自动配兵：未能确认{区}已清空，停止{区}配置避免叠加")
            return None
        # c. 添加
        if not self._打开列表(区):
            上下文.置脚本状态(f"[警告] 自动配兵：{区}已清空，但列表没有打开，请在游戏里检查")
            return None
        for 名 in dict.fromkeys(确认关键):
            if not self._添加并确认关键单位(区, 名):
                上下文.置脚本状态(f"自动配兵：关键单位{名}添加后未确认数量，停止{区}配置")
                return None
            计划[名] -= 1
            if 计划[名] <= 0:
                del 计划[名]
        if 分区表[区].批量点击:
            if 精确:
                # 实机（rc126）：每批连续点击的第一下会被吞。精确模式不补偿以免多加，
                # 批量只加到离目标还差 3 个左右，尾数交给 _精确复核 逐下单击并用容量确认。
                批量 = self._精确批量部分(计划)
                if 批量:
                    self._添加兵种(批量, {名: 0 for 名 in 批量}, 补偿=False)
            elif 计划:
                self._添加兵种(计划, {名: 0 for 名 in 计划})
        else:
            if 计划:
                self._逐个添加(区, 计划)
        self._收起列表()
        if 精确:
            return self._精确复核(区, 目标)
        容量 = self._读取人口(区)
        # 连续点击偶尔会丢几下：按剩余空位用计划内兵种补满（权重高的优先），最多补 3 轮。
        for _ in range(3 if 区 == "兵种" else 0):
            if not 容量 or 容量[0] >= 容量[1]:
                break
            补充 = self._补满计划(容量[1] - 容量[0], 计划, 人口表)
            if not 补充:
                break
            上下文.置脚本状态(
                f"自动配兵补满：剩余 {容量[1] - 容量[0]} 人口，补充 "
                + "、".join(f"{兵种资料.显示名(名)}×{数}" for 名, 数 in 补充.items())
            )
            if not self._打开列表(区):
                break
            self._添加兵种(补充, {名: 0 for 名 in 补充})
            self._收起列表()
            for 名, 数 in 补充.items():
                计划[名] = 计划.get(名, 0) + 数
            容量 = self._读取人口(区)
        if 容量:
            上下文.置脚本状态(f"自动配兵完成（{区}）：{容量[0]}/{容量[1]}")
        return 计划, 容量

    @staticmethod
    def _精确批量部分(缺口: dict[str, int]) -> dict[str, int]:
        """缺口大于 5 的单位先小批连点到只差 3 个；其余全部逐下确认。"""
        return {名: 数 - 3 for 名, 数 in 缺口.items() if 数 > 5}

    def _替补不可用单位(self, 区: str, 单位: dict, 可用: list[str], 上限: int) -> dict[str, int]:
        """快照里不可用的单位去掉，空出的人口用快照里其它可用单位（个数多的优先）补上。"""
        上下文 = self.上下文
        缺 = {名: int(数) for 名, 数 in 单位.items() if 名 not in 可用}
        保留 = {名: int(数) for 名, 数 in 单位.items() if 名 in 可用 and int(数) > 0}
        if not 保留:
            return {}
        空出 = 上限 - (阵容占用(保留) or 0)
        for 名 in sorted(保留, key=lambda 名: (-保留[名] * 兵种资料.人口(名), 兵种资料.人口(名))):
            人口 = 兵种资料.人口(名)
            if 人口 > 0 and 空出 >= 人口:
                加 = 空出 // 人口
                保留[名] += 加
                空出 -= 加 * 人口
        上下文.置脚本状态(
            f"[警告] 部落竞赛恢复：快照里 {self._阵容描述(缺)} 当前不可用（超级兵种到期/未解锁等），"
            f"{区}改按可用单位恢复：{self._阵容描述(保留)}"
        )
        return 保留

    def _逐下确认添加(self, 区: str, 名称: str, 个数: int) -> int:
        """逐下单击一个单位，每下都用列表打开时的容量 OCR 确认入账；返回确认加入的个数。

        单击被吞（容量没变）就再点，连续 3 下没入账即放弃；按容量增量折算个数，
        多入账由 _精确复核 判失败，不会静默多加。
        """
        上下文 = self.上下文
        人口 = max(1, 兵种资料.人口(名称))
        已加 = 0
        for _, 图 in self._逐页():
            if self._已请求停止():
                return 已加
            找到 = 查找兵种卡片(图, 名称)
            if not 找到:
                continue
            连续失败 = 0
            while 找到 and 已加 < 个数 and 连续失败 < 3:
                if self._已请求停止():
                    return 已加
                前 = self._读取当前列表容量(区)
                if not 前 or 前[0] + 人口 > 前[1]:
                    return 已加
                (x, y), _ = 找到
                if 上下文.点击(x, y, 延时=500, 是否精确点击=True) is False:
                    return 已加
                上下文.脚本延时(300)
                后 = self._读取当前列表容量(区)
                if 后 and 后[0] > 前[0]:
                    已加 += max(1, (后[0] - 前[0]) // 人口)
                    连续失败 = 0
                else:
                    连续失败 += 1
                找到 = 查找兵种卡片(self._截图(), 名称)
            return 已加
        return 已加

    def _精确复核(self, 区: str, 目标: dict[str, int]) -> tuple[dict, tuple] | None:
        """按主页面卡片逐项比对数量；只补缺口，多了或识别不到即失败。

        缺口 >5 先小批连点（不补偿）缩小，≤5 的尾数逐下单击并用容量确认入账，
        所以每批第一下被吞也能收敛。
        """
        上下文 = self.上下文
        最多轮数 = 8
        for 轮 in range(最多轮数 + 1):
            当前, 原因 = self._读取分区阵容(区)
            if 当前 is None:
                上下文.置脚本状态(f"自动配兵：{区}数量复核失败（{原因}）")
                return None
            if 当前["单位"] == 目标:
                上下文.置脚本状态(
                    f"自动配兵完成（{区}）：{self._阵容描述(目标)}，{当前['容量'][0]}/{当前['容量'][1]}"
                )
                return dict(目标), tuple(当前["容量"])
            多出 = {名: 数 for 名, 数 in 当前["单位"].items() if 数 > 目标.get(名, 0)}
            if 多出 or 轮 == 最多轮数 or self._已请求停止():
                上下文.置脚本状态(
                    f"自动配兵：{区}数量与目标不一致（当前 {self._阵容描述(当前['单位'])}，"
                    f"目标 {self._阵容描述(目标)}）"
                )
                return None
            缺口 = {名: 数 - 当前["单位"].get(名, 0) for 名, 数 in 目标.items()
                    if 数 > 当前["单位"].get(名, 0)}
            上下文.置脚本状态(f"自动配兵补缺（{区}）：{self._阵容描述(缺口)}")
            if not self._打开列表(区):
                return None
            if 分区表[区].批量点击:
                批量 = self._精确批量部分(缺口)
                if 批量:
                    self._添加兵种(批量, {名: 0 for 名 in 批量}, 补偿=False)
                else:
                    for 名, 数 in 缺口.items():
                        if self._已请求停止():
                            break
                        self._逐下确认添加(区, 名, 数)
            else:
                self._逐个添加(区, 缺口)
            self._收起列表()
        return None

    @staticmethod
    def _按个数分配(个数: dict[str, int], 容量: int, 人口表: dict[str, int]) -> dict[str, int]:
        """法术/攻城：预设给固定个数时按顺序放；自定义（99）时轮流各放一个直到放满。"""
        if all(数 < 99 for 数 in 个数.values()):
            return 预设.分配法术(个数, 容量, 人口表)
        结果, 剩余, 放入 = {名: 0 for 名 in 个数}, 容量, True
        while 放入:
            放入 = False
            for 名 in 个数:
                if 人口表.get(名, 0) and 剩余 >= 人口表[名] and 结果[名] < 个数[名]:
                    结果[名] += 1
                    剩余 -= 人口表[名]
                    放入 = True
        return {名: 数 for 名, 数 in 结果.items() if 数 > 0}

    # ------------------------------------------------------------ 页面
    def _截图(self):
        return self.上下文.op.获取屏幕图像cv(0, 0, 800, 600, 强制刷新=True)

    def _OCR文本(self, 图像, 区域) -> str:
        x1, y1, x2, y2 = 区域
        try:
            结果, _ = self.上下文.获取OCR引擎()(图像[y1:y2, x1:x2])
        except Exception:
            return ""
        return "".join(str(项[1]) for 项 in (结果 or []))

    def _确认主世界主页(self) -> bool:
        from 任务流程.主世界打鱼.打开进攻页面 import 打开进攻页面任务
        return 打开进攻页面任务._确认主世界主页(self.上下文)

    def _等待文字(self, 区域, 关键字: tuple[str, ...], 超时秒=5.0) -> bool:
        截止 = time.time() + 超时秒
        while time.time() < 截止:
            文本 = self._OCR文本(self._截图(), 区域)
            if any(字 in 文本 for 字 in 关键字):
                return True
            self.上下文.脚本延时(400)
        return False

    def _打开编辑页(self) -> bool:
        上下文 = self.上下文
        if not self._确认主世界主页():
            上下文.置脚本状态("自动配兵：未确认主世界主页，不点击战斗菜单")
            return False
        if 上下文.点击(*锚定(主世界战斗菜单), 延时=900, 是否精确点击=True) is False:
            return False
        if not self._等待文字(编辑军队按钮OCR区域, ("編輯", "编辑", "軍隊", "军队")):
            上下文.置脚本状态("自动配兵：战斗菜单里没确认到“编辑军队”按钮")
            return False
        if 上下文.点击(*编辑军队按钮, 延时=900, 是否精确点击=True) is False:
            return False
        if not self._等待文字(编辑页标题OCR区域, 编辑页标题关键字):
            上下文.置脚本状态("自动配兵：没确认到“我的军队”编辑页")
            return False
        # 已用 OCR 确认在编辑页：页面识别会把它误判成“战斗结算”而锁住输入，
        # 这里告诉点击护栏当前在编辑军队（宝石/商店检查照常进行）。
        上下文._军队编辑中 = True
        return True

    def _读取人口(self, 区: str = "兵种") -> tuple[int, int] | None:
        for _ in range(3):
            人口 = 解析人口(self._OCR文本(self._截图(), 分区表[区].人口OCR区域))
            if 人口:
                return 人口
            self.上下文.脚本延时(300)
        return None

    def _清空分区(self, 区: str) -> bool:
        """点分区垃圾桶；若弹出“移除部队”确认框则点 OCR 确认到的“确定”。"""
        上下文 = self.上下文
        人口 = self._读取人口(区)
        if 人口 and 人口[0] == 0:
            return True
        if 上下文.点击(*分区表[区].垃圾桶, 延时=700, 是否精确点击=True) is False:
            return False
        人口 = self._读取人口(区)
        if 人口 and 人口[0] == 0:
            return True
        按钮 = self._查找确认按钮()
        if 按钮 is not None:
            # 点击护栏默认阻断所有“多按钮弹窗”；这里已 OCR 确认是“移除部队”
            # 确认框且画面无宝石字样，只放行这一次点击。
            上下文._移除部队确认中 = True
            try:
                上下文.点击(*按钮, 延时=700, 是否精确点击=True)
            finally:
                上下文._移除部队确认中 = False
            人口 = self._读取人口(区)
        return bool(人口 and 人口[0] == 0)

    def _清空普通兵种(self, 上限: int = 0) -> bool:  # 兼容旧调用
        return self._清空分区("兵种")

    def _查找确认按钮(self) -> tuple[int, int] | None:
        """确认是“移除部队？”弹窗后，返回“确定”按钮中心；画面有宝石字样则放弃。"""
        try:
            结果, _ = self.上下文.获取OCR引擎()(self._截图())
        except Exception:
            return None
        全部文字 = "".join(str(项[1]) for 项 in 结果 or [])
        if not any(字 in 全部文字 for 字 in ("移除部隊", "移除部队", "移除這些", "移除这些")):
            return None
        if any(字 in 全部文字 for 字 in ("寶石", "宝石", "購買", "购买")):
            return None
        for 框, 文本, *_ in 结果 or []:
            文本 = str(文本)
            if any(字 in 文本 for 字 in ("寶石", "宝石", "購買", "购买")):
                continue
            if 文本.strip() in ("確定", "确定", "確認", "确认", "是", "清除", "移除"):
                xs = [点[0] for 点 in 框]
                ys = [点[1] for 点 in 框]
                return int(sum(xs) / len(xs)), int(sum(ys) / len(ys))
        return None

    # ------------------------------------------------------------ 列表
    def _已请求停止(self) -> bool:
        事件 = getattr(self.上下文, "停止事件", None)
        检查 = getattr(事件, "is_set", None)
        return bool(callable(检查) and 检查())

    def _读取当前列表容量(self, 区: str) -> tuple[int, int] | None:
        """关键单位必须在仍打开列表时确认本分区容量确实增加。"""
        return self._读取人口(区) if 区 == "兵种" else self._列表中容量(区)

    def _添加并确认关键单位(self, 区: str, 名称: str) -> bool:
        """逐次点击一个关键单位，以分区容量变化确认卡片输入被游戏接受。"""
        上下文 = self.上下文
        for _, 图 in self._逐页():
            if self._已请求停止():
                return False
            找到 = 查找兵种卡片(图, 名称)
            if not 找到:
                continue
            起始容量 = self._读取当前列表容量(区)
            if not 起始容量 or 起始容量[0] >= 起始容量[1]:
                return False
            for _ in range(3):
                if self._已请求停止():
                    return False
                (x, y), _ = 找到
                if 上下文.点击(x, y, 延时=500, 是否精确点击=True) is False:
                    return False
                上下文.脚本延时(300)
                当前容量 = self._读取当前列表容量(区)
                if 当前容量 and 当前容量[0] > 起始容量[0]:
                    上下文.置脚本状态(
                        f"自动配兵：已确认关键单位{兵种资料.显示名(名称)}至少加入1个"
                    )
                    return True
                图 = self._截图()
                找到 = 查找兵种卡片(图, 名称)
                if not 找到:
                    break
            return False
        return False

    def _滑动列表(self, 起x: int, 终x: int, 时长毫秒=450) -> bool:
        if self._已请求停止():
            return False
        设备 = self.上下文.设备
        a = 设备.参考坐标转设备坐标(起x, 列表滑动Y)
        b = 设备.参考坐标转设备坐标(终x, 列表滑动Y)
        if self._已请求停止():
            return False
        设备.执行(
            ["shell", "input", *设备._输入显示参数(), "swipe",
             str(a[0]), str(a[1]), str(b[0]), str(b[1]), str(时长毫秒)],
            timeout=10,
        )
        self.上下文.脚本延时(900)
        return not self._已请求停止()

    def _打开列表(self, 区: str = "兵种") -> bool:
        """在编辑页主页面点分区（满员时点卡片区，空时点“点击以编辑”）打开底部列表。"""
        上下文 = self.上下文
        for _ in range(2):
            if 列表已打开(self._截图(), 区):
                return True
            if 上下文.点击(*分区表[区].编辑区, 延时=900, 是否精确点击=True) is False:
                return False
        return 列表已打开(self._截图(), 区)

    def 检查可用单位(self, 目标单位: dict[str, list[str] | tuple[str, ...]]) -> dict[str, set[str]]:
        """只读扫描编辑页里的已解锁卡片，不清空、不添加或修改任何单位。"""
        上下文 = self.上下文
        可用 = {}
        try:
            if not self._确认主世界主页():
                上下文.置脚本状态("部落竞赛配兵预检：未确认主世界主页，不进入军队页")
                return 可用
            if not self._打开编辑页():
                上下文.置脚本状态("部落竞赛配兵预检：编辑军队页未确认，本轮动态任务关闭")
                return 可用
            for 区 in ("兵种", "法术", "攻城"):
                名称列表 = list(dict.fromkeys(map(str, (目标单位 or {}).get(区, ()))))
                if not 名称列表:
                    continue
                if not self._打开列表(区):
                    上下文.置脚本状态(f"部落竞赛配兵预检：{区}列表未确认")
                    可用[区] = set()
                    continue
                可用[区] = set(self._扫描可用(区, 名称列表))
                self._收起列表()
            return 可用
        except Exception as 异常:
            上下文.置脚本状态(f"部落竞赛配兵预检异常，相关任务不接：{异常}")
            return {}
        finally:
            try:
                self._退出到主世界()
                if not self._确认主世界主页():
                    可用.clear()
                    上下文.置脚本状态("部落竞赛配兵预检后未确认回到主世界，禁用动态配兵")
            except Exception as 异常:
                可用.clear()
                上下文.置脚本状态(f"部落竞赛配兵预检退出失败：{异常}")
            finally:
                self._结束编辑状态()

    def _打开兵种列表(self) -> bool:  # 兼容旧调用
        return self._打开列表("兵种")

    def _收起列表(self):
        """返回键收起底部列表，回到编辑页主页面（实机：返回键只收列表，不关编辑页）。"""
        if self._已请求停止():
            return
        try:
            self.上下文.键盘.按键按压("esc")
        except Exception:
            return
        self.上下文.脚本延时(900)

    def _逐页(self, 最多页数=8):
        """先滑到最左，再逐页右滑；每页产出 (页序号, 截图)。列表不再变化时停止。"""
        for _ in range(4):
            if self._已请求停止() or not self._滑动列表(150, 750, 250):
                return
        上一张 = None
        for 页 in range(最多页数):
            if self._已请求停止():
                return
            图 = self._截图()
            yield 页, 图
            if self._已请求停止():
                return
            if 上一张 is not None:
                x1, y1, x2, y2 = 兵种列表区域
                差异 = np.abs(图[y1:y2, x1:x2].astype(np.int16) - 上一张[y1:y2, x1:x2].astype(np.int16)).mean()
                if 差异 < 2:
                    return
            上一张 = 图
            if not self._滑动列表(600, 300):
                return

    def _扫描可用(self, 区: str, 名称列表: list[str]) -> list[str]:
        可用 = set()
        for _, 图 in self._逐页():
            可用 |= {名 for 名 in 名称列表 if 名 not in 可用 and 查找兵种卡片(图, 名)}
            if len(可用) == len(名称列表):
                break
        return [名 for 名 in 名称列表 if 名 in 可用]

    def _扫描兵种卡片(self, 勾选: list[str]) -> tuple[dict, dict]:  # 兼容旧调用
        可用 = self._扫描可用("兵种", 勾选)
        return {名: 0 for 名 in 可用}, {名: 兵种资料.人口(名) for 名 in 可用}

    def _添加兵种(self, 计划: dict[str, int], 位置: dict[str, int], 补偿: bool = True):
        """逐页找到卡片后小批连续点击；每批至多3个 + 1下补偿并检查停止事件。

        补偿=False（精确配置）时每批只点计划个数，丢的几下由数量复核补缺口，绝不多加。
        """
        上下文 = self.上下文
        剩余 = dict(计划)
        for _, 图 in self._逐页():
            if self._已请求停止():
                return
            for 兵种 in [名 for 名, 数 in 剩余.items() if 数 > 0]:
                找到 = 查找兵种卡片(图, 兵种)
                while 找到 and 剩余[兵种] > 0:
                    if self._已请求停止():
                        return
                    (x, y), _ = 找到
                    本批 = min(3, 剩余[兵种])
                    # 实机：每批连续点击的第一下不会被编辑页接收（3 批就少 3 个），
                    # 所以每批至多多点一下；小批之间可立即响应停止事件。
                    点击数 = 本批 + 1 if 补偿 else 本批
                    if 上下文.鼠标.连续点击(x, y, 点击数, 间隔毫秒=90) is False:
                        上下文.置脚本状态(f"自动配兵：添加{兵种资料.显示名(兵种)}被输入层拒绝，停止添加")
                        return
                    剩余[兵种] -= 本批
                    上下文.脚本延时(300)
                    if self._已请求停止():
                        return
                    # 添加后卡片可能变灰或列表重排，重新截图定位再继续。
                    图 = self._截图()
                    找到 = 查找兵种卡片(图, 兵种)
            if not any(数 > 0 for 数 in 剩余.values()):
                return
        未加完 = {名: 数 for 名, 数 in 剩余.items() if 数 > 0}
        if 未加完:
            上下文.置脚本状态(
                "自动配兵：以下兵种未能全部添加："
                + "、".join(f"{兵种资料.显示名(名)}×{数}" for 名, 数 in 未加完.items())
            )

    def _逐个添加(self, 区: str, 计划: dict[str, int]):
        """法术/攻城器械个数少：逐个点击，每下之后用容量 OCR 确认增加，避免多加。

        打开法术/攻城列表时面板上移，容量文字不在主页面位置，所以用卡片计数
        的方式复核：点击前后都在列表打开的状态下读同一分区上移后的容量区。
        """
        上下文 = self.上下文
        剩余 = dict(计划)
        截止 = time.time() + 150  # 实机 rc128：容量已满后仍逐页重试了 6 分钟以上
        for _, 图 in self._逐页():
            for 名 in [名 for 名, 数 in 剩余.items() if 数 > 0]:
                找到 = 查找兵种卡片(图, 名)
                失败 = 0
                while 找到 and 剩余[名] > 0 and 失败 < 3:
                    前 = self._列表中容量(区)
                    if 前 and 前[0] >= 前[1]:
                        上下文.置脚本状态(f"自动配兵：{区}容量已满 {前[0]}/{前[1]}，停止添加")
                        return
                    if time.time() > 截止:
                        上下文.置脚本状态(f"自动配兵：{区}添加超过 150 秒，停止添加")
                        return
                    (x, y), _ = 找到
                    if 上下文.点击(x, y, 延时=500, 是否精确点击=True) is False:
                        return
                    后 = self._列表中容量(区)
                    if 前 and 后 and 后[0] > 前[0]:
                        剩余[名] -= 1
                        失败 = 0
                    elif 前 is None or 后 is None:
                        # 读不到容量时按点击一次算一次，最终由收起列表后的复核兜底。
                        剩余[名] -= 1
                    else:
                        失败 += 1
                    找到 = 查找兵种卡片(self._截图(), 名)
            if not any(数 > 0 for 数 in 剩余.values()):
                return
        未加完 = {名: 数 for 名, 数 in 剩余.items() if 数 > 0}
        if 未加完:
            上下文.置脚本状态(
                f"自动配兵：{区}未能全部添加："
                + "、".join(f"{兵种资料.显示名(名)}×{数}" for 名, 数 in 未加完.items())
            )

    def _列表中容量(self, 区: str) -> tuple[int, int] | None:
        """法术/攻城列表打开时面板上移约 100px，容量文字随之上移。"""
        x1, y1, x2, y2 = 分区表[区].人口OCR区域
        return 解析人口(self._OCR文本(self._截图(), (x1, y1 - 102, x2, y2 - 102)))

    @staticmethod
    def _补满计划(空位: int, 计划: dict[str, int], 人口表: dict[str, int]) -> dict[str, int]:
        """用已在计划里的兵种填剩余空位：按权重从高到低，放得下就尽量多放。"""
        补充 = {}
        for 名 in sorted(计划, key=lambda 名: -getattr(兵种资料.兵种映射.get(名), "权重", 0)):
            占用 = 人口表.get(名, 0)
            if 占用 and 空位 >= 占用:
                数量 = 空位 // 占用
                补充[名] = 数量
                空位 -= 数量 * 占用
        return 补充

    def _结束编辑状态(self):
        """清除编辑期标志和编辑页被误判成结算页留下的状态，避免拦住后续正常点击。"""
        上下文 = self.上下文
        上下文._军队编辑中 = False
        上下文._移除部队确认中 = False
        for 名称, 值 in (
            ("_最近点击页面结果", None), ("_最近结算视觉时间", 0.0),
            ("_非战斗结算输入已拦截", False), ("_结算输入已锁定日志", False),
            ("_结算视觉跨帧阻断日志", False),
        ):
            if hasattr(上下文, 名称):
                setattr(上下文, 名称, 值)

    def _退出到主世界(self):
        """关编辑页；再用返回键收起弹窗/战斗菜单，直到确认主世界主页（最多 5 次）。

        实机：列表打开时返回键先收列表；编辑页 X → 回到战斗菜单；返回键 → 主世界主页。
        确认框还开着时 X 会被点击护栏拦下，此时返回键先关确认框（等同“取消”）。
        """
        上下文 = self.上下文
        if self._已请求停止():
            return
        文本 = self._OCR文本(self._截图(), 编辑页标题OCR区域)
        if any(字 in 文本 for 字 in 编辑页标题关键字):
            if self._已请求停止():
                return
            上下文.点击(*关闭按钮, 延时=900, 是否精确点击=True)
        for _ in range(5):
            if self._已请求停止():
                return
            识别 = getattr(上下文, "识别点击画面", None)
            try:
                结果 = 识别(强制=True) if callable(识别) else None
            except Exception:
                结果 = None
            if getattr(结果, "页面", "") == "主世界主页":
                return
            if self._已请求停止():
                return
            try:
                上下文.键盘.按键按压("esc")
            except Exception:
                return
            上下文.脚本延时(900)
