"""C2. 都城突袭周末自动出击（任务键 capital_raid）—— 骨架，必须实机校准后才运行。

只用免费出击次数，简化下兵：

1. 只在突袭周末窗口内运行（默认 UTC 周五 07:00 ～ 周一 07:00，JSON 可改）。
2. 主世界主页 → 进入都城（复用 C1 的 都城导航）→ 打开突袭页并 OCR 确认。
3. OCR 读「剩余出击次数」：读不出来或为 0 → 不出击；本周末记为已用完。
4. 「进攻」按钮区域过宝石图标 + 危险词护栏（付费/宝石入口一律不点）→ 点击。
5. OCR 确认已进入战斗页 → 按 JSON 的兵种栏格子逐个选中（每格过护栏），
   在 JSON 的下兵点上轮流点下（每点也过宝石护栏）→ 不点「结束战斗/放弃」，
   只轮询等待结算出现「回营/返回」→ 过护栏后点击。
6. 回到突袭页（或都城页时重新打开突袭页）继续下一次，直到达到每轮上限或次数用完。
7. 退出突袭页（安全关闭：先确认仍在突袭页）→ 返回主世界。

护栏：
- 资源/日常/都城突袭.json calibrated 不是 true，或兵种栏/下兵点为空 → 拒绝运行。
- 任何要点的区域出现宝石图标或「宝石/购买/跳过/重置/加速」字样一律不点；
  OCR 不可用时护栏拒绝点击。
- 停止事件置位后不再发任何点击；任何一步页面未确认（已进入都城后）→ 页面不可信。
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

from 任务流程.日常 import 日常公共
from 任务流程.日常.都城捐金币 import 都城导航

任务键 = "capital_raid"

默认参数 = {
    "calibrated": False,
    "点击后等待毫秒": 1500,
    # 突袭周末窗口（UTC）：周几用 Python 约定（周一=0 … 周五=4）。
    "周末开始周几": 4,
    "周末开始UTC小时": 7,
    "周末结束周几": 0,
    "周末结束UTC小时": 7,
    # 与 资源/日常/都城.json 同名键含义相同（校准值可直接抄过来）。
    "都城入口": [0, 0],
    "都城页确认区域": [200, 0, 600, 80],
    "都城页关键词": ["都城", "部落都城"],
    "返回按钮区域": [0, 500, 200, 600],
    "返回按钮关键词": ["返回", "回家"],
    # 都城页上的突袭入口按钮。
    "突袭入口区域": [600, 480, 800, 600],
    "突袭入口关键词": ["突袭"],
    "突袭页确认区域": [200, 0, 600, 90],
    "突袭页关键词": ["突袭周末", "突袭"],
    # 剩余出击次数文字，例如「剩余出击 5/6」；取第一个数字为剩余次数。
    "剩余次数区域": [500, 470, 800, 540],
    "剩余次数正则": "(\\d+)\\s*/\\s*\\d+",
    "进攻按钮区域": [550, 520, 800, 600],
    "进攻按钮关键词": ["进攻", "攻击"],
    # 突袭页关闭点（点前会重新确认仍在突袭页）；[0, 0] 表示未配置。
    "退出突袭页点": [0, 0],
    # 战斗页确认：屏幕上出现这些字（只用于确认，绝不点击）。
    "战斗确认区域": [0, 480, 250, 600],
    "战斗确认关键词": ["结束战斗", "放弃"],
    # 兵种栏格子中心与下兵点（800x600）；为空时拒绝运行。
    "兵种栏格子": [],
    "下兵点": [],
    "每格下兵次数": 8,
    "下兵间隔毫秒": 150,
    "格子护栏半宽": 30,
    "格子护栏半高": 30,
    "下兵点护栏半径": 20,
    # 剩余次数本周末连续读不出达到此数即放弃本周末（与读到 0 一样记为用完）。
    "读不出次数上限": 3,
    "战斗最长秒": 240,
    "结算轮询毫秒": 3000,
    "结算区域": [200, 430, 600, 600],
    "结算关键词": ["回营", "返回"],
}


def 读取参数() -> dict:
    return 日常公共.加载日常参数("都城突袭", 默认参数)


# ---------------------------------------------------------------- 时间窗口
def _周内小时(时刻: datetime) -> float:
    return 时刻.weekday() * 24 + 时刻.hour + 时刻.minute / 60 + 时刻.second / 3600


def 是否突袭周末(时刻: datetime | None = None, 参数: dict | None = None) -> bool:
    参数 = 参数 or 默认参数
    时刻 = 时刻 or datetime.now(timezone.utc)
    时刻 = 时刻.astimezone(timezone.utc)
    开始 = int(参数["周末开始周几"]) * 24 + int(参数["周末开始UTC小时"])
    结束 = int(参数["周末结束周几"]) * 24 + int(参数["周末结束UTC小时"])
    当前 = _周内小时(时刻)
    if 开始 <= 结束:
        return 开始 <= 当前 < 结束
    return 当前 >= 开始 or 当前 < 结束  # 跨周（周五→周一）


def 本周末标识(时刻: datetime | None = None, 参数: dict | None = None) -> str:
    """当前（或最近一次）突袭周末开始那天的 UTC 日期，用于按周末记次数。"""
    参数 = 参数 or 默认参数
    时刻 = (时刻 or datetime.now(timezone.utc)).astimezone(timezone.utc)
    开始周几 = int(参数["周末开始周几"])
    开始小时 = int(参数["周末开始UTC小时"])
    相差天 = (时刻.weekday() - 开始周几) % 7
    开始 = (时刻 - timedelta(days=相差天)).replace(hour=开始小时, minute=0, second=0, microsecond=0)
    if 开始 > 时刻:
        开始 -= timedelta(days=7)
    return 开始.strftime("%Y-%m-%d")


def 距突袭周末开始秒(时刻: datetime | None = None, 参数: dict | None = None) -> float:
    参数 = 参数 or 默认参数
    时刻 = (时刻 or datetime.now(timezone.utc)).astimezone(timezone.utc)
    开始 = int(参数["周末开始周几"]) * 24 + int(参数["周末开始UTC小时"])
    差 = (开始 - _周内小时(时刻)) % (7 * 24)
    return 差 * 3600


def 解析剩余次数(文本: str, 正则: str) -> int | None:
    匹配 = re.search(正则, str(文本 or "").replace(" ", ""))
    if not 匹配:
        return None
    try:
        return int(匹配.group(1))
    except (IndexError, ValueError):
        return None


class 都城突袭任务(都城导航):
    日志前缀 = "都城突袭"

    def __init__(self, 上下文, 参数: dict | None = None, 现在: datetime | None = None):
        self.上下文 = 上下文
        self.数据库 = 上下文.数据库
        self.机器人标志 = 上下文.机器人标志
        self.参数 = 参数 if 参数 is not None else 读取参数()
        self.现在 = 现在  # 测试注入；None 表示真实时间
        self.已进入都城 = False
        self.本轮出击 = 0
        self.次数用完 = False
        # 本轮是否真正读到过有效次数，以及“最后一次读到之后”连续读不出的次数。
        # 记录里的读不出计数只在真正读到有效数字时清零，读失败绝不写成 0。
        self.本轮读到过次数 = False
        self.读到后连续读不出 = 0

    # ------------------------------------------------------------ 记录
    def _周末(self) -> str:
        return 本周末标识(self.现在, self.参数)

    def 读取记录(self) -> dict:
        记录 = 日常公共.读取任务记录(self.数据库, self.机器人标志, 任务键)
        if 记录.get("周末") != self._周末():
            记录 = {"周末": self._周末(), "出击次数": 0, "次数用完": False, "读不出次数": 0,
                  "下次检查时间": 记录.get("下次检查时间", 0)}
        return 记录

    # ------------------------------------------------------------ 前置
    def 可以运行(self) -> bool:
        if not 日常公共.已校准(self.参数):
            self.日志(
                "资源/日常/都城突袭.json 尚未实机校准（calibrated=false），拒绝运行；"
                "请先截都城页/突袭页/战斗页校准坐标后再开启"
            )
            日常公共.请求等待(self.上下文, 3600, "都城突袭未校准")
            return False
        if not self.参数.get("兵种栏格子") or not self.参数.get("下兵点"):
            self.日志("兵种栏格子或下兵点未配置，拒绝运行")
            日常公共.请求等待(self.上下文, 3600, "都城突袭下兵点未配置")
            return False
        if not 是否突袭周末(self.现在, self.参数):
            剩余 = 距突袭周末开始秒(self.现在, self.参数)
            self.日志(f"不在突袭周末，{int(剩余 // 3600)} 小时后开始")
            日常公共.请求等待(self.上下文, 剩余, "等待突袭周末")
            return False
        记录 = self.读取记录()
        if 记录.get("次数用完"):
            self.日志("本周末免费出击次数已用完")
            日常公共.请求等待(self.上下文, 3600, "都城突袭次数用完")
            return False
        剩余 = 日常公共.冷却剩余秒(记录)
        if 剩余 > 0:
            日常公共.请求等待(self.上下文, 剩余, "都城突袭检查间隔")
            return False
        return True

    # ------------------------------------------------------------ 主流程
    def 执行(self) -> bool:
        if not self.可以运行():
            return True
        try:
            结果 = self._流程()
        except Exception as 异常:
            self.日志(f"异常：{异常}")
            结果 = False
        if self.已停止():
            # 停止后不再发任何点击，也不标记失败；已出击次数照常记下。
            self._保存(完成=False)
            return True
        if not 结果:
            self._保存(完成=False)
            self.上下文.页面恢复失败 = True
            return False
        self._保存(完成=True)
        return True

    def _流程(self) -> bool:
        进入 = self.进入都城()
        if 进入 != "已进入":
            return 进入 == "跳过"
        上限 = int(getattr(self.上下文.设置, "都城突袭每轮最多出击", 6) or 6)
        while self.本轮出击 < 上限 and not self.已停止():
            if not self._打开突袭页():
                return False
            结果 = self._出击一次()
            if 结果 == "失败":
                return False
            if 结果 == "无次数":
                break
        if self.已停止():
            return True
        if not self._退出突袭页():
            return False
        return self._返回()

    # ------------------------------------------------------------ 突袭页
    def _突袭页在(self, 图) -> bool:
        return self.区域有关键词(图, self.参数["突袭页确认区域"], self.参数["突袭页关键词"]) is not None

    def _打开突袭页(self) -> bool:
        图 = self.截图()
        if self._突袭页在(图):
            return True
        if not self.都城页在(图):
            self.日志("既不在突袭页也不在都城页，停止并保留画面")
            return False
        按钮 = self.区域有关键词(图, self.参数["突袭入口区域"], self.参数["突袭入口关键词"])
        if 按钮 is None or 按钮[1] is None:
            self.日志("都城页上没找到突袭入口")
            return False
        if not self.点击前护栏(图, 日常公共.扩展区域(按钮[1], 50, 24), "突袭入口"):
            return False
        if not self.点击(*按钮[1], "打开突袭页"):
            return False
        if not self._突袭页在(self.截图()):
            self.日志("点了突袭入口但未确认突袭页，停止并保留画面")
            return False
        return True

    def _读剩余次数(self, 图) -> int | None:
        for 文本, _ in self.OCR或空(图, self.参数["剩余次数区域"]):
            次数 = 解析剩余次数(文本, str(self.参数["剩余次数正则"]))
            if 次数 is not None:
                return 次数
        return None

    def _出击一次(self) -> str:
        """返回 "完成" / "无次数"（含读不出次数、护栏拒绝等不出击情形）/ "失败"。"""
        图 = self.截图()
        剩余 = self._读剩余次数(图)
        if 剩余 is None:
            self.日志("剩余出击次数读不出来，不出击")
            self.读到后连续读不出 += 1
            return "无次数"
        self.本轮读到过次数 = True
        self.读到后连续读不出 = 0
        if 剩余 <= 0:
            self.日志("免费出击次数已用完")
            self.次数用完 = True
            return "无次数"
        按钮 = self.区域有关键词(图, self.参数["进攻按钮区域"], self.参数["进攻按钮关键词"])
        if 按钮 is None or 按钮[1] is None:
            self.日志("突袭页没找到进攻按钮，不出击")
            return "无次数"
        if 日常公共.含危险词(按钮[0]) or not self.点击前护栏(
            图, tuple(self.参数["进攻按钮区域"]), "进攻按钮"
        ):
            return "无次数"
        if not self.点击(*按钮[1], f"开始出击（剩余 {剩余} 次）"):
            return "无次数" if not self.已停止() else "完成"
        if not self._战斗页在(self.截图()):
            self.日志("点了进攻但未确认进入战斗，停止并保留画面")
            return "失败"
        self.本轮出击 += 1
        self._下兵()
        if self.已停止():
            return "完成"
        return "完成" if self._等待结算并回营() else "失败"

    # ------------------------------------------------------------ 战斗
    def _战斗页在(self, 图) -> bool:
        return self.区域有关键词(图, self.参数["战斗确认区域"], self.参数["战斗确认关键词"]) is not None

    def _战斗中安全点击(self, 点, 半宽: int, 半高: int, 说明: str, 等待毫秒: int) -> str:
        """每次点击前取新帧：停止→确认仍在战斗页→宝石图标+危险词护栏→点击。

        返回 "已点" / "跳过"（护栏拒绝这一点）/ "停止"（停止、战斗页消失或点击被拒）。
        """
        if self.已停止():
            return "停止"
        图 = self.截图()
        if not self._战斗页在(图):
            self.日志(f"{说明}前未确认仍在战斗页，停止下兵")
            return "停止"
        if not self.点击前护栏(图, 日常公共.扩展区域(点, 半宽, 半高), 说明):
            return "跳过"
        return "已点" if self.点击(点[0], 点[1], 说明, 等待毫秒=等待毫秒) else "停止"

    def _下兵(self) -> None:
        下兵点 = [tuple(点) for 点 in self.参数["下兵点"]]
        次数 = max(1, int(self.参数["每格下兵次数"]))
        间隔 = int(self.参数["下兵间隔毫秒"])
        半宽, 半高 = int(self.参数["格子护栏半宽"]), int(self.参数["格子护栏半高"])
        半径 = int(self.参数["下兵点护栏半径"])
        序号 = 0
        for 格 in self.参数["兵种栏格子"]:
            结果 = self._战斗中安全点击(tuple(格), 半宽, 半高, "选中兵种", None)
            if 结果 == "停止":
                return
            if 结果 == "跳过":
                continue
            for _ in range(次数):
                点 = 下兵点[序号 % len(下兵点)]
                序号 += 1
                if self._战斗中安全点击(点, 半径, 半径, "下兵", 间隔) == "停止":
                    return

    def _等待结算并回营(self) -> bool:
        截止 = time.monotonic() + float(self.参数["战斗最长秒"])
        轮询 = int(self.参数["结算轮询毫秒"])
        while time.monotonic() < 截止:
            if self.已停止():
                return True
            图 = self.截图()
            按钮 = self.区域有关键词(图, self.参数["结算区域"], self.参数["结算关键词"])
            if 按钮 is not None and 按钮[1] is not None and not self._战斗页在(图):
                if not self.点击前护栏(图, 日常公共.扩展区域(按钮[1], 60, 24), "回营按钮"):
                    return False
                return self.点击(*按钮[1], "结算回营")
            延时 = getattr(self.上下文, "脚本延时", None)
            if callable(延时):
                延时(轮询)
            else:
                time.sleep(轮询 / 1000)
        self.日志(f"等待结算超过 {self.参数['战斗最长秒']} 秒，保留画面")
        return False

    # ------------------------------------------------------------ 退出
    def _退出突袭页(self) -> bool:
        图 = self.截图()
        if not self._突袭页在(图):
            return self.都城页在(图) or self._记("退出时既不在突袭页也不在都城页")
        点 = self.参数.get("退出突袭页点", [0, 0])
        if tuple(点) == (0, 0):
            return self._记("未配置退出突袭页点，保留画面")
        if not self.安全关闭(点, self.参数["突袭页确认区域"], self.参数["突袭页关键词"], "退出突袭页"):
            return False
        return self.都城页在(self.截图()) or self._记("退出突袭页后未确认都城页")

    def _记(self, 文本: str) -> bool:
        self.日志(文本)
        return False

    def _保存(self, 完成: bool) -> None:
        记录 = self.读取记录()
        记录["出击次数"] = int(记录.get("出击次数", 0)) + self.本轮出击
        if self.本轮读到过次数:
            # 只有真正读到过才清零，再加上读到之后又连续读不出的次数。
            记录["读不出次数"] = self.读到后连续读不出
        else:
            记录["读不出次数"] = int(记录.get("读不出次数", 0)) + self.读到后连续读不出
        if self.读到后连续读不出 > 0:
            上限 = max(1, int(self.参数.get("读不出次数上限", 3)))
            if 记录["读不出次数"] >= 上限:
                self.日志(f"本周末剩余出击次数连续 {记录['读不出次数']} 次读不出，放弃本周末突袭")
                self.次数用完 = True
        if self.次数用完:
            记录["次数用完"] = True
        if 完成:
            间隔 = max(15, int(getattr(self.上下文.设置, "都城突袭检查间隔分钟", 60) or 60)) * 60
            记录["下次检查时间"] = time.time() + 间隔
            日常公共.请求等待(self.上下文, 间隔, "都城突袭检查间隔")
        日常公共.写入任务记录(self.数据库, self.机器人标志, 任务键, 记录)
        self.日志(f"本轮出击 {self.本轮出击} 次，本周末累计 {记录['出击次数']} 次")
