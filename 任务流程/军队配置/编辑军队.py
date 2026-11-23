"""按设置里勾选的兵种自动编辑军队（新版“战斗 → 编辑军队”页）。

新版 CoC 部队不再需要训练时间，编辑军队页里的配置就是下一场的军队。
流程（坐标均为 800×600 参考画布，来自 MuMu 实机截图）：

1. 主世界主页 → 点“战斗”打开战斗菜单 → OCR 确认左下“编辑军队”后点击；
2. OCR 确认“我的军队”页并读取人口“当前/上限”；
3. 用普通兵种区右侧的垃圾桶清空普通兵种（不动法术、攻城器械和英雄）；
4. 点“点击以编辑”打开底部兵种列表，按卡片头像模板找到勾选的兵种，
   按推荐比例算出个数后逐个点击卡片添加；列表可横向滚动，逐页查找；
5. 复核人口，关闭编辑页并回到主世界主页。

安全边界：只点击编辑页自己的控件（战斗菜单入口、编辑军队、垃圾桶/确认、
兵种卡片、关闭）。不会点击“强化军队/强化英雄”、超级兵种激活或任何宝石按钮；
每一步都先确认页面，确认不了就按返回键退出，不再继续点击。
"""
from __future__ import annotations

import os
import re
import time

import cv2
import numpy as np

from 任务流程.基础任务框架 import 基础任务, 任务上下文
from 任务流程.世界跳转.新版界面坐标 import 主世界战斗菜单
from 任务流程.军队配置 import 兵种资料

状态类型 = "自动配兵"

编辑军队按钮 = (62, 565)
编辑军队按钮OCR区域 = (10, 545, 120, 588)
编辑页标题OCR区域 = (100, 40, 270, 82)
# OCR 常把“軍隊”的“隊”读成“隧”，只用前两个字符判断。
编辑页标题关键字 = ("我的軍", "我的军")
人口OCR区域 = (360, 126, 470, 154)
普通兵种垃圾桶 = (772, 140)
关闭按钮 = (772, 55)
普通兵种编辑区 = (565, 200)  # 清空后这里显示“点击以编辑”，点击打开底部兵种列表
兵种列表区域 = (0, 340, 800, 590)
列表滑动Y = 450

# 卡片头像模板：img/军队卡片/<兵种>.png（军营满员时的灰色卡）与 <兵种>_彩.png
# （有空位时的彩色卡）。头像取卡片内 [16:62, 6:58]，去掉右上 i 图标和底部人口数字。
# 在整个列表区域里直接搜索头像，不依赖逐张定位卡片（彩色卡的蓝底会干扰 i 图标识别）。
头像宽 = 52
头像高 = 46
头像到卡片中心 = (30, 32)
卡片匹配阈值 = 0.85
最多尝试次数 = 2
满员比例 = 0.95

# 每个兵种占用人口（2025 年后新版数值，逐一对照实机卡片底部数字核对）。
# 卡片上的数字很小，OCR 常把 5 读成 S、30 读成 1，所以不在运行时读。
兵种人口 = {
    "超级哥布林": 3, "哥布林": 1, "野蛮人": 1, "弓箭手": 1, "巨人": 5, "炸弹人": 2,
    "气球兵": 5, "法师": 4, "天使": 14, "飞龙": 20, "飞龙宝宝": 10, "雷龙": 30,
    "龙骑士": 25, "根蔓骑士": 20, "苍蝇": 2, "瓦基丽武神": 8, "女巫": 12, "皮卡超人": 25,
    "矿工": 6, "大雪怪": 18, "野猪骑士": 5, "石头人": 30, "天狗": 30, "戈仑冰人": 15,
}


def 配置签名(兵种列表) -> str:
    return "+".join(sorted(map(str, 兵种列表 or [])))


def 解析人口(文本: str) -> tuple[int, int] | None:
    匹配 = re.search(r"(\d{1,3})\s*[/／]\s*(\d{2,3})", str(文本 or "").replace(" ", ""))
    if not 匹配:
        return None
    当前, 上限 = int(匹配.group(1)), int(匹配.group(2))
    return (当前, 上限) if 0 <= 当前 <= 上限 <= 999 else None


_模板缓存: dict[str, list[np.ndarray]] = {}


def 读取卡片模板(兵种: str) -> list[np.ndarray] | None:
    """返回该兵种的灰度模板列表（灰色卡、彩色卡各一张，至少一张）；没有则 None。"""
    if 兵种 not in _模板缓存:
        根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        模板 = []
        for 文件名 in (f"{兵种}.png", f"{兵种}_彩.png"):
            路径 = os.path.join(根, "img", "军队卡片", 文件名)
            if os.path.isfile(路径):
                图 = cv2.imdecode(np.fromfile(路径, dtype=np.uint8), cv2.IMREAD_COLOR)
                if 图 is not None:
                    模板.append(cv2.cvtColor(图, cv2.COLOR_BGR2GRAY))
        _模板缓存[兵种] = 模板
    return _模板缓存[兵种] or None


def 查找兵种卡片(图像, 兵种: str) -> tuple[tuple[int, int], float] | None:
    """在兵种列表区域里找该兵种完整可见的卡片，返回 (卡片中心, 分数)。"""
    模板列表 = 读取卡片模板(兵种)
    if not 模板列表:
        return None
    x1, y1, x2, y2 = 兵种列表区域
    灰 = cv2.cvtColor(图像[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    最佳 = None
    for 模板 in 模板列表:
        结果 = cv2.matchTemplate(灰, 模板, cv2.TM_CCOEFF_NORMED)
        # 只接受整张卡在画面内的位置：左右各留出卡片边框宽度。
        结果[:, :8] = -1
        结果[:, max(0, 结果.shape[1] - 24):] = -1
        _, 分数, _, (x, y) = cv2.minMaxLoc(结果)
        if 分数 >= 卡片匹配阈值 and (最佳 is None or 分数 > 最佳[1]):
            中心 = (x + x1 + 头像到卡片中心[0], y + y1 + 头像到卡片中心[1])
            最佳 = (中心, float(分数))
    return 最佳


def 列表已打开(图像) -> bool:
    """底部列表里至少认出一张已知兵种卡，才算兵种列表已打开。"""
    return any(查找兵种卡片(图像, 兵种) for 兵种 in 兵种人口 if 读取卡片模板(兵种))


class 编辑军队任务(基础任务):
    """勾选兵种 → 编辑军队。失败时只退出编辑页，不影响后续刷资源。"""

    def __init__(self, 上下文: 任务上下文):
        super().__init__(上下文)

    # ------------------------------------------------------------ 对外入口
    def 需要配置(self) -> bool:
        设置 = getattr(self.上下文, "设置", None)
        if not getattr(设置, "是否自动配置军队", False):
            return False
        勾选 = list(getattr(设置, "配兵兵种", []) or [])
        if not 勾选:
            return False
        签名 = 配置签名(勾选)
        # 每次启动至少核对一次（玩家可能在游戏里手动改过军队），之后只在勾选变化时重配。
        if getattr(self.上下文, "_本次运行已配兵签名", None) == 签名:
            return False
        # 同一勾选本次运行最多尝试 2 次，失败后不再每轮重进编辑页。
        尝试 = getattr(self.上下文, "_本次运行配兵尝试", {}) or {}
        return 尝试.get(签名, 0) < 最多尝试次数

    def 执行(self) -> bool:
        上下文 = self.上下文
        if not self.需要配置():
            return True
        勾选 = list(上下文.设置.配兵兵种)
        无模板 = [名 for 名 in 勾选 if 读取卡片模板(名) is None]
        可配 = [名 for 名 in 勾选 if 名 not in 无模板]
        if 无模板:
            上下文.置脚本状态(
                f"自动配兵：{'、'.join(兵种资料.显示名(名) for 名 in 无模板)} 暂无卡片模板，配兵时跳过"
            )
        if not 可配:
            上下文._本次运行已配兵签名 = 配置签名(勾选)
            上下文.置脚本状态("自动配兵：勾选的兵种都没有卡片模板，保持游戏里现有军队")
            return True

        签名 = 配置签名(勾选)
        尝试 = dict(getattr(上下文, "_本次运行配兵尝试", {}) or {})
        尝试[签名] = 尝试.get(签名, 0) + 1
        上下文._本次运行配兵尝试 = 尝试
        上下文.置脚本状态(f"自动配兵：开始配置 {'、'.join(兵种资料.显示名(名) for 名 in 可配)}")
        try:
            结果 = self._配置流程(可配)
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
        if not 人口 or 人口[0] < 人口[1] * 满员比例:
            上下文.置脚本状态(
                f"[警告] 自动配兵未填满军营（{人口[0] if 人口 else '?'}/{人口[1] if 人口 else '?'}），"
                f"本次运行还会再试 {最多尝试次数 - 尝试[签名]} 次"
            )
            return True
        上下文._本次运行已配兵签名 = 配置签名(勾选)
        try:
            上下文.数据库.更新状态(上下文.机器人标志, 状态类型, {
                "勾选": 勾选, "配置": 结果["配置"], "人口": 结果["人口"], "时间": int(time.time()),
            })
        except Exception:
            pass
        return True

    # ------------------------------------------------------------ 流程
    def _配置流程(self, 勾选: list[str]) -> dict | None:
        上下文 = self.上下文
        if not self._确认主世界主页():
            上下文.置脚本状态("自动配兵：未确认主世界主页，跳过本次配兵")
            return None
        if not self._打开编辑页():
            return None
        人口 = self._读取人口()
        if 人口 is None:
            上下文.置脚本状态("自动配兵：读不到军营人口，跳过")
            return None
        _, 上限 = 人口
        if not self._清空普通兵种(上限):
            上下文.置脚本状态("自动配兵：未能确认普通兵种已清空，停止配兵避免叠加")
            return None
        if not self._打开兵种列表():
            上下文.置脚本状态("[警告] 自动配兵：普通兵种已清空，但兵种列表没有打开，请在游戏里检查军队")
            return None

        位置, 人口表 = self._扫描兵种卡片(勾选)
        未找到 = [名 for 名 in 勾选 if 名 not in 位置]
        if 未找到:
            上下文.置脚本状态(
                f"自动配兵：列表里没找到 {'、'.join(兵种资料.显示名(名) for 名 in 未找到)}"
                "（未解锁或超级兵种未激活），跳过"
            )
        计划 = 兵种资料.分配兵量([名 for 名 in 勾选 if 名 in 位置], 上限, 人口表)
        if not 计划:
            上下文.置脚本状态("[警告] 自动配兵：普通兵种已清空但没有可添加的兵种，请在游戏里检查军队")
            return None
        上下文.置脚本状态(
            "自动配兵计划：" + "、".join(f"{兵种资料.显示名(名)}×{数}" for 名, 数 in 计划.items())
            + f"（人口上限 {上限}）"
        )
        self._添加兵种(计划, 位置)
        人口 = self._读取人口()
        # 连续点击偶尔会丢几下：按剩余空位用勾选兵种补满（权重高的优先），最多补 3 轮。
        for _ in range(3):
            if not 人口 or 人口[0] >= 人口[1]:
                break
            补充 = self._补满计划(人口[1] - 人口[0], 计划, 人口表)
            if not 补充:
                break
            上下文.置脚本状态(
                f"自动配兵补满：剩余 {人口[1] - 人口[0]} 人口，补充 "
                + "、".join(f"{兵种资料.显示名(名)}×{数}" for 名, 数 in 补充.items())
            )
            self._添加兵种(补充, 位置)
            for 名, 数 in 补充.items():
                计划[名] = 计划.get(名, 0) + 数
            人口 = self._读取人口()
        if 人口:
            上下文.置脚本状态(f"自动配兵完成：军营人口 {人口[0]}/{人口[1]}")
        return {"配置": 计划, "人口": list(人口) if 人口 else None}

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
        if 上下文.点击(*主世界战斗菜单, 延时=900, 是否精确点击=True) is False:
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

    def _读取人口(self) -> tuple[int, int] | None:
        for _ in range(3):
            人口 = 解析人口(self._OCR文本(self._截图(), 人口OCR区域))
            if 人口:
                return 人口
            self.上下文.脚本延时(300)
        return None

    def _清空普通兵种(self, 上限: int) -> bool:
        """点普通兵种区的垃圾桶；若弹出确认框则点 OCR 确认到的“确定”。"""
        上下文 = self.上下文
        人口 = self._读取人口()
        if 人口 and 人口[0] == 0:
            return True
        if 上下文.点击(*普通兵种垃圾桶, 延时=700, 是否精确点击=True) is False:
            return False
        人口 = self._读取人口()
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
            人口 = self._读取人口()
        return bool(人口 and 人口[0] == 0)

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

    # ------------------------------------------------------------ 兵种列表
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

    def _打开兵种列表(self) -> bool:
        """清空后普通兵种区显示“点击以编辑”；点它打开底部兵种列表并确认有卡片。"""
        上下文 = self.上下文
        for _ in range(2):
            if 列表已打开(self._截图()):
                return True
            if 上下文.点击(*普通兵种编辑区, 延时=900, 是否精确点击=True) is False:
                return False
        return 列表已打开(self._截图())

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

    def _扫描兵种卡片(self, 勾选: list[str]) -> tuple[dict, dict]:
        """逐页找出列表里有哪些勾选兵种，返回 ({兵种: 页序号}, {兵种: 人口})。"""
        位置, 人口表 = {}, {}
        for 页, 图 in self._逐页():
            for 兵种 in 勾选:
                if 兵种 not in 位置 and 查找兵种卡片(图, 兵种):
                    位置[兵种] = 页
                    人口表[兵种] = 兵种人口.get(兵种, 0)
            if len(位置) == len(勾选):
                break
        return 位置, 人口表

    def _添加兵种(self, 计划: dict[str, int], 位置: dict[str, int]):
        """逐页找到卡片后连续点击添加；每批 31 个 + 1 下补偿（输入层上限 32），每批后复核卡片位置。"""
        上下文 = self.上下文
        剩余 = dict(计划)
        for 页, 图 in self._逐页():
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

    @staticmethod
    def _补满计划(空位: int, 计划: dict[str, int], 人口表: dict[str, int]) -> dict[str, int]:
        """用已在计划里的兵种填剩余空位：按权重从高到低，放得下就尽量多放。"""
        补充 = {}
        for 名 in sorted(计划, key=lambda 名: -兵种资料.兵种映射[名].权重):
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

        实机：编辑页 X → 回到战斗菜单；返回键 → 主世界主页。确认框还开着时
        X 会被点击护栏拦下，此时返回键先关确认框（等同“取消”，不移除部队）。
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
