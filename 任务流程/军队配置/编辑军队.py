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


def 期望配置(设置) -> dict | None:
    """把设置换算成 {分区: {单位: 权重或个数}}；未开启或没有内容返回 None。

    兵种给权重（按军营人口换算个数），法术给个数，攻城器械给 1 个。
    """
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

    # ------------------------------------------------------------ 对外入口
    def 需要配置(self) -> bool:
        配置 = 期望配置(getattr(self.上下文, "设置", None))
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
        if not self.需要配置():
            return True
        设置 = 上下文.设置
        配置 = 期望配置(设置)
        签名 = 配置签名(配置)
        无模板 = [名 for 单位 in 配置.values() for 名 in 单位 if 读取卡片模板(名) is None]
        if 无模板:
            上下文.置脚本状态(
                f"自动配兵：{'、'.join(兵种资料.显示名(名) for 名 in 无模板)} 暂无卡片模板，配兵时跳过"
            )
        配置 = {区: {名: 值 for 名, 值 in 单位.items() if 名 not in 无模板} for 区, 单位 in 配置.items()}
        配置 = {区: 单位 for 区, 单位 in 配置.items() if 单位}
        缺关键 = [名 for 名 in 关键单位(设置) if 名 in 无模板]
        if not 配置 or 缺关键:
            上下文._本次运行已配兵签名 = 签名
            上下文.置脚本状态(
                "自动配兵："
                + (f"预设缺少关键兵种 {'、'.join(缺关键)} 的模板，" if 缺关键 else "勾选的单位都没有卡片模板，")
                + "保持游戏里现有军队"
            )
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
            结果 = self._配置流程(配置, 关键单位(设置))
        except Exception as 异常:  # 任何异常都退出编辑页，交给刷资源继续
            上下文.置脚本状态(f"[警告] 自动配兵异常，保持当前军队：{异常}", 60)
            结果 = None
        finally:
            try:
                self._退出到主世界()
            finally:
                self._结束编辑状态()
        if 结果 is None:
            return not getattr(上下文, "页面恢复失败", False)
        人口 = 结果.get("人口")
        if "兵种" in 配置 and (not 人口 or 人口[0] < 人口[1] * 满员比例):
            上下文.置脚本状态(
                f"[警告] 自动配兵未填满军营（{人口[0] if 人口 else '?'}/{人口[1] if 人口 else '?'}），"
                f"本次运行还会再试 {最多尝试次数 - 尝试[签名]} 次"
            )
            return True
        上下文._本次运行已配兵签名 = 签名
        try:
            上下文.数据库.更新状态(上下文.机器人标志, 状态类型, {
                "预设": 预设名, "签名": 签名, "配置": 结果["配置"], "人口": 结果["人口"],
                "分区容量": 结果.get("分区容量"), "时间": int(time.time()),
            })
        except Exception:
            pass
        return True

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
            结果 = self._配置分区(区, 配置[区], 关键 if 区 == "兵种" else ())
            if 结果 is None:
                if 区 == "兵种":
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

    def _配置分区(self, 区: str, 单位: dict, 关键: tuple[str, ...]) -> tuple[dict, tuple] | None:
        """一个分区：确认可用 → 清空 → 添加 → 复核。返回 (计划, 容量)；不动该分区时返回 None。"""
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
        if 缺关键 or not 可用:
            上下文.置脚本状态(
                f"自动配兵：缺少{'关键单位 ' + '、'.join(缺关键) if 缺关键 else '可用单位'}，{区}保持不动"
            )
            return None
        人口表 = {名: 兵种资料.人口(名) for 名 in 可用}
        if 区 == "兵种":
            计划 = 兵种资料.按权重分配({名: 单位[名] for 名 in 可用}, 上限, 人口表)
        else:
            计划 = self._按个数分配({名: 单位[名] for 名 in 可用}, 上限, 人口表)
        if not 计划:
            上下文.置脚本状态(f"自动配兵：{区}容量 {上限} 放不下所选单位，{区}保持不动")
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
        if 分区表[区].批量点击:
            self._添加兵种(计划, {名: 0 for 名 in 计划})
        else:
            self._逐个添加(区, 计划)
        self._收起列表()
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
    def _滑动列表(self, 起x: int, 终x: int, 时长毫秒=450):
        设备 = self.上下文.设备
        a = 设备.参考坐标转设备坐标(起x, 列表滑动Y)
        b = 设备.参考坐标转设备坐标(终x, 列表滑动Y)
        设备.执行(
            ["shell", "input", *设备._输入显示参数(), "swipe",
             str(a[0]), str(a[1]), str(b[0]), str(b[1]), str(时长毫秒)],
            timeout=10,
        )
        self.上下文.脚本延时(900)

    def _打开列表(self, 区: str = "兵种") -> bool:
        """在编辑页主页面点分区（满员时点卡片区，空时点“点击以编辑”）打开底部列表。"""
        上下文 = self.上下文
        for _ in range(2):
            if 列表已打开(self._截图(), 区):
                return True
            if 上下文.点击(*分区表[区].编辑区, 延时=900, 是否精确点击=True) is False:
                return False
        return 列表已打开(self._截图(), 区)

    def _打开兵种列表(self) -> bool:  # 兼容旧调用
        return self._打开列表("兵种")

    def _收起列表(self):
        """返回键收起底部列表，回到编辑页主页面（实机：返回键只收列表，不关编辑页）。"""
        try:
            self.上下文.键盘.按键按压("esc")
        except Exception:
            return
        self.上下文.脚本延时(900)

    def _逐页(self, 最多页数=8):
        """先滑到最左，再逐页右滑；每页产出 (页序号, 截图)。列表不再变化时停止。"""
        for _ in range(4):
            self._滑动列表(150, 750, 250)
        上一张 = None
        for 页 in range(最多页数):
            图 = self._截图()
            yield 页, 图
            if 上一张 is not None:
                x1, y1, x2, y2 = 兵种列表区域
                差异 = np.abs(图[y1:y2, x1:x2].astype(np.int16) - 上一张[y1:y2, x1:x2].astype(np.int16)).mean()
                if 差异 < 2:
                    return
            上一张 = 图
            self._滑动列表(600, 300)

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

    def _添加兵种(self, 计划: dict[str, int], 位置: dict[str, int]):
        """逐页找到卡片后连续点击添加；每批 31 个 + 1 下补偿（输入层上限 32），每批后复核卡片位置。"""
        上下文 = self.上下文
        剩余 = dict(计划)
        for _, 图 in self._逐页():
            for 兵种 in [名 for 名, 数 in 剩余.items() if 数 > 0]:
                找到 = 查找兵种卡片(图, 兵种)
                while 找到 and 剩余[兵种] > 0:
                    (x, y), _ = 找到
                    本批 = min(31, 剩余[兵种])
                    # 实机：每批连续点击的第一下不会被编辑页接收（3 批就少 3 个），
                    # 所以每批多点一下。军营满员后游戏不会再加兵，多点不会超员。
                    if 上下文.鼠标.连续点击(x, y, 本批 + 1, 间隔毫秒=90) is False:
                        上下文.置脚本状态(f"自动配兵：添加{兵种资料.显示名(兵种)}被输入层拒绝，停止添加")
                        return
                    剩余[兵种] -= 本批
                    上下文.脚本延时(300)
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
        文本 = self._OCR文本(self._截图(), 编辑页标题OCR区域)
        if any(字 in 文本 for 字 in 编辑页标题关键字):
            上下文.点击(*关闭按钮, 延时=900, 是否精确点击=True)
        for _ in range(5):
            识别 = getattr(上下文, "识别点击画面", None)
            try:
                结果 = 识别(强制=True) if callable(识别) else None
            except Exception:
                结果 = None
            if getattr(结果, "页面", "") == "主世界主页":
                return
            try:
                上下文.键盘.按键按压("esc")
            except Exception:
                return
            上下文.脚本延时(900)
