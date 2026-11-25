"""按自然日累计的战斗与收益统计（界面「今日数据条」的数据来源）。

写入方：战斗结算（场次/胜负/星数）和战后资源净变化（收益）。
读取方：界面。所有函数吞掉数据库异常，统计失败绝不影响刷资源流程。

收益取“战前→战后资源净变化”的累加：它已经扣除训练消耗，包含战后收集；
单场读数不可信（疑似 OCR 误读）时不计入，与阵容学习用同一条判断。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

状态类型 = "今日统计"
保留天数 = 7
资源列表 = ("金币", "圣水", "黑油")
# 与 阵容学习.单场最低可信净变化 保持一致；正向上限防止 OCR 多读一位把当天收益拉爆。
单场最低可信净变化 = -20_000
单场最高可信净变化 = {"金币": 6_000_000, "圣水": 6_000_000, "黑油": 120_000}


def 今天(现在: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(time.time() if 现在 is None else 现在))


def _空日() -> dict:
    return {"场次": 0, "胜": 0, "负": 0, "星数和": 0, "星数场次": 0,
            "收益场次": 0, "金币": 0, "圣水": 0, "黑油": 0}


def 读取全部(数据库, 机器人标志: str) -> dict:
    try:
        with 数据库._获取连接() as conn:
            行 = conn.execute(
                """SELECT 状态值 FROM 运行时状态
                   WHERE 机器人标志 = ? AND 状态类型 = ?
                   ORDER BY 记录ID DESC LIMIT 1""",
                (机器人标志, 状态类型),
            ).fetchone()
        数据 = json.loads(行[0]) if 行 else {}
    except Exception:
        数据 = {}
    按日 = 数据.get("按日") if isinstance(数据, dict) else None
    return {"按日": dict(按日) if isinstance(按日, dict) else {}}


def _修改今天(数据库, 机器人标志: str, 现在: float | None, 修改) -> bool:
    try:
        全部 = 读取全部(数据库, 机器人标志)
        日期 = 今天(现在)
        当天 = {**_空日(), **(全部["按日"].get(日期) or {})}
        修改(当天)
        全部["按日"][日期] = 当天
        for 旧日期 in sorted(全部["按日"])[:-保留天数]:
            del 全部["按日"][旧日期]
        数据库.更新状态(机器人标志, 状态类型, 全部)
        return True
    except Exception:
        return False


def 记录战斗(数据库, 机器人标志: str, 结果: str, 星数: int | None, 现在: float | None = None) -> bool:
    def 修改(当天):
        当天["场次"] += 1
        if 结果 == "胜利":
            当天["胜"] += 1
        elif 结果 == "失败":
            当天["负"] += 1
        if 星数 is not None:
            当天["星数和"] += int(星数)
            当天["星数场次"] += 1
    return _修改今天(数据库, 机器人标志, 现在, 修改)


def 收益可信(净变化: dict) -> bool:
    try:
        for 资源 in 资源列表:
            值 = int(净变化.get(资源, 0) or 0)
            if not 单场最低可信净变化 <= 值 <= 单场最高可信净变化[资源]:
                return False
    except (TypeError, ValueError, AttributeError):
        return False
    return True


def 记录收益(数据库, 机器人标志: str, 净变化: dict, 现在: float | None = None) -> bool:
    if not isinstance(净变化, dict) or not 收益可信(净变化):
        return False

    def 修改(当天):
        当天["收益场次"] += 1
        for 资源 in 资源列表:
            当天[资源] += int(净变化.get(资源, 0) or 0)
    return _修改今天(数据库, 机器人标志, 现在, 修改)


@dataclass(frozen=True)
class 今日数据:
    场次: int = 0
    胜: int = 0
    负: int = 0
    平均星数: float | None = None
    金币: int = 0
    圣水: int = 0
    黑油: int = 0
    收益场次: int = 0

    @property
    def 胜率(self) -> float | None:
        已识别 = self.胜 + self.负
        return round(self.胜 / 已识别 * 100) if 已识别 else None


def 读取今日(数据库, 机器人标志: str, 现在: float | None = None) -> 今日数据:
    当天 = {**_空日(), **(读取全部(数据库, 机器人标志)["按日"].get(今天(现在)) or {})}
    星数场次 = int(当天["星数场次"])
    return 今日数据(
        场次=int(当天["场次"]), 胜=int(当天["胜"]), 负=int(当天["负"]),
        平均星数=round(当天["星数和"] / 星数场次, 1) if 星数场次 else None,
        金币=int(当天["金币"]), 圣水=int(当天["圣水"]), 黑油=int(当天["黑油"]),
        收益场次=int(当天["收益场次"]),
    )


def 读取部落竞赛(数据库, 机器人标志: str) -> dict:
    """部落竞赛任务写下的检查记录（个人积分、当前任务、下次检查时间）。"""
    try:
        with 数据库._获取连接() as conn:
            行 = conn.execute(
                """SELECT 状态值 FROM 运行时状态
                   WHERE 机器人标志 = ? AND 状态类型 = '部落竞赛检查记录'
                   ORDER BY 记录ID DESC LIMIT 1""",
                (机器人标志,),
            ).fetchone()
        数据 = json.loads(行[0]) if 行 else {}
        return 数据 if isinstance(数据, dict) else {}
    except Exception:
        return {}


def 格式化数量(数值: int) -> str:
    """4_200_000 → +4.2M；21_000 → +21k；负数保留符号。"""
    符号 = "+" if 数值 > 0 else ("-" if 数值 < 0 else "")
    绝对 = abs(int(数值))
    if 绝对 >= 1_000_000:
        文本 = f"{绝对 / 1_000_000:.1f}M"
    elif 绝对 >= 10_000:
        文本 = f"{绝对 / 1000:.0f}k"
    elif 绝对 >= 1000:
        文本 = f"{绝对 / 1000:.1f}k"
    else:
        文本 = str(绝对)
    return 符号 + 文本
