"""每日战报与每小时效率统计服务（纯只读，与界面无关）。

从 ``任务数据库`` 的 ``运行时状态`` 与 ``任务日志`` 聚合统计：
- 今日 vs 昨日汇总（总场次、胜场、胜率、平均摧毁率、总掠夺金/水/黑油、
  每小时场次、每小时金/水/黑油收益、平均搜敌次数）；
- 今日 0~23 时分小时效率曲线（每小时场次与金/水/黑油收益列表）。

只执行只读查询，兼容空数据库与字段缺失的历史记录。
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from 应用.控制器 import 默认实例ID, 选择主实例ID
from 数据库.任务数据库 import 任务数据库

_战斗结果正则 = re.compile(
    r"战斗结果：(?P<结果>[^；;\s]+)"
    r"(?:[；;]星数：(?P<星数>\d+|待识别))?"
    r"(?:[；;]摧毁率：(?P<摧毁率>\d+(?:\.\d+)?|待识别)%?)?"
)
_净变化正则 = re.compile(
    r"本场资源净变化[:：]\s*"
    r"金币\s*(?P<金币>[+-]?\d+)\s*[，,]\s*"
    r"圣水\s*(?P<圣水>[+-]?\d+)\s*[，,]\s*"
    r"黑油\s*(?P<黑油>[+-]?\d+)"
)
_搜敌次数正则 = re.compile(r"(?:搜索次数|黑水优先筛选：候选)\[(\d+)\]")
_搜敌完成标记 = (
    "成功找到敌人",
    "对方17本，大本营比较高",
    "搜索按钮消失后已连续确认自然回营",
)


def _安全整数(值: Any) -> int | None:
    if 值 is None or isinstance(值, bool):
        return None
    if isinstance(值, int):
        return 值
    if isinstance(值, float):
        return int(值) if math.isfinite(值) else None
    文本 = str(值).strip().replace(",", "")
    if not 文本 or 文本 == "待识别":
        return None
    try:
        return int(float(文本))
    except (TypeError, ValueError, OverflowError):
        return None


def _安全浮点(值: Any) -> float | None:
    if 值 is None or isinstance(值, bool):
        return None
    if isinstance(值, (int, float)):
        f = float(值)
        return f if math.isfinite(f) else None
    文本 = str(值).strip().rstrip("%")
    if not 文本 or 文本 == "待识别":
        return None
    try:
        f = float(文本)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _安全非负整数(值: Any) -> int:
    解析 = _安全整数(值)
    return max(0, 解析) if 解析 is not None else 0


def _解析JSON字典(文本: Any) -> dict[str, Any]:
    if isinstance(文本, dict):
        return 文本
    if not isinstance(文本, str) or not 文本.strip():
        return {}
    try:
        数据 = json.loads(文本)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return 数据 if isinstance(数据, dict) else {}


def _规范化结果(值: Any) -> str:
    文本 = str(值 or "").strip()
    if 文本 in {"胜利", "失败", "未知"}:
        return 文本
    return "未知"


@dataclass
class _战斗事件:
    时间戳: float
    结果: str = "未知"
    星数: int | None = None
    摧毁率: float | None = None


@dataclass
class _收益事件:
    时间戳: float
    金币: int = 0
    圣水: int = 0
    黑油: int = 0
    结果: str | None = None
    星数: int | None = None
    摧毁率: float | None = None


@dataclass(frozen=True)
class 小时效率项:
    小时: int
    场次: int = 0
    胜场: int = 0
    金币: int = 0
    圣水: int = 0
    黑油: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "小时": self.小时,
            "场次": self.场次,
            "胜场": self.胜场,
            "金币": self.金币,
            "圣水": self.圣水,
            "黑油": self.黑油,
        }


@dataclass(frozen=True)
class 每日汇总:
    日期: str
    总场次: int = 0
    胜场: int = 0
    负场: int = 0
    未知结果场次: int = 0
    胜率: float | None = None
    平均摧毁率: float | None = None
    总掠夺金币: int = 0
    总掠夺圣水: int = 0
    总掠夺黑油: int = 0
    活跃小时数: int = 0
    每小时场次: float = 0.0
    每小时金币: float = 0.0
    每小时圣水: float = 0.0
    每小时黑油: float = 0.0
    平均搜敌次数: float | None = None
    搜敌样本数: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "日期": self.日期,
            "总场次": self.总场次,
            "胜场": self.胜场,
            "负场": self.负场,
            "未知结果场次": self.未知结果场次,
            "胜率": self.胜率,
            "平均摧毁率": self.平均摧毁率,
            "总掠夺金币": self.总掠夺金币,
            "总掠夺圣水": self.总掠夺圣水,
            "总掠夺黑油": self.总掠夺黑油,
            "活跃小时数": self.活跃小时数,
            "每小时场次": self.每小时场次,
            "每小时金币": self.每小时金币,
            "每小时圣水": self.每小时圣水,
            "每小时黑油": self.每小时黑油,
            "平均搜敌次数": self.平均搜敌次数,
            "搜敌样本数": self.搜敌样本数,
        }


@dataclass(frozen=True)
class 每日战报结果:
    机器人ID: str
    生成时间: float
    今日: 每日汇总
    昨日: 每日汇总
    今日分小时: tuple[小时效率项, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "机器人ID": self.机器人ID,
            "生成时间": self.生成时间,
            "今日": self.今日.to_dict(),
            "昨日": self.昨日.to_dict(),
            "今日分小时": [项.to_dict() for 项 in self.今日分小时],
        }


class 战报服务:
    """只读聚合今日/昨日战报与 0~23 时分小时效率曲线。"""

    def __init__(self, 数据库: 任务数据库 | str | Path | None = None):
        self._数据库 = 数据库

    def _只读连接(self):
        """以只读语义打开连接；路径不存在时不创建新数据库文件。"""
        目标 = self._数据库
        if 目标 is None:
            目标 = 任务数据库.默认数据库路径()
        if isinstance(目标, (str, Path)):
            路径 = Path(目标)
            if not 路径.is_file():
                return None
            return sqlite3.connect(
                f"file:{路径.resolve()}?mode=ro",
                uri=True,
                check_same_thread=False,
                timeout=10,
            )
        获取连接 = getattr(目标, "_获取连接", None)
        if callable(获取连接):
            return 获取连接()
        return None

    def _解析机器人ID(self, 机器人ID: str | None) -> str:
        if 机器人ID is not None and str(机器人ID).strip():
            return str(机器人ID).strip()
        if isinstance(self._数据库, 任务数据库):
            try:
                return 选择主实例ID(self._数据库)
            except Exception:
                return 默认实例ID
        if isinstance(self._数据库, (str, Path)) and Path(self._数据库).is_file():
            try:
                return 选择主实例ID(任务数据库(str(self._数据库)))
            except Exception:
                return 默认实例ID
        return 默认实例ID

    def _读取原始数据(
        self,
        机器人ID: str,
        起始时间: float,
        截止时间: float,
    ) -> tuple[list[tuple[float, str]], list[tuple[float, str, str]], list[tuple[float, str]]]:
        """返回 (任务日志行, 战斗状态行, 战斗学习行)，全部只读 SELECT。"""
        conn_or_cm = self._只读连接()
        if conn_or_cm is None:
            return [], [], []

        def _执行查询(conn: sqlite3.Connection):
            日志行: list[tuple[float, str]] = []
            状态行: list[tuple[float, str, str]] = []
            学习行: list[tuple[float, str]] = []
            try:
                日志行 = conn.execute(
                    """SELECT 记录时间, 日志内容
                       FROM 任务日志
                       WHERE 机器人标志 = ? AND 记录时间 >= ? AND 记录时间 < ?
                       ORDER BY 记录时间 ASC, 记录ID ASC""",
                    (机器人ID, 起始时间, 截止时间),
                ).fetchall()
            except sqlite3.Error:
                日志行 = []
            try:
                状态行 = conn.execute(
                    """SELECT 记录时间, 状态类型, 状态值
                       FROM 运行时状态
                       WHERE 机器人标志 = ?
                         AND 状态类型 IN ('战斗资源分析', '战斗记录', '战斗结果')
                         AND 记录时间 >= ? AND 记录时间 < ?
                       ORDER BY 记录时间 ASC, 记录ID ASC""",
                    (机器人ID, 起始时间 - 60.0, 截止时间),
                ).fetchall()
            except sqlite3.Error:
                状态行 = []
            try:
                学习行 = conn.execute(
                    """SELECT 记录时间, 状态值
                       FROM 运行时状态
                       WHERE 机器人标志 = ? AND 状态类型 = '战斗学习'
                       ORDER BY 记录ID DESC
                       LIMIT 5""",
                    (机器人ID,),
                ).fetchall()
            except sqlite3.Error:
                学习行 = []
            return 日志行, 状态行, 学习行

        if hasattr(conn_or_cm, "__enter__"):
            with conn_or_cm as conn:
                return _执行查询(conn)
        try:
            return _执行查询(conn_or_cm)
        finally:
            conn_or_cm.close()

    @staticmethod
    def _解析日志(
        日志行: Iterable[tuple[Any, Any]],
    ) -> tuple[list[_战斗事件], list[_收益事件], list[tuple[float, int]]]:
        战斗列表: list[_战斗事件] = []
        收益列表: list[_收益事件] = []
        搜敌轮次: list[tuple[float, int]] = []

        当前轮最大搜敌 = 0
        当前轮最后时间 = 0.0

        for 原始时间, 原始内容 in 日志行:
            时间戳 = _安全浮点(原始时间)
            if 时间戳 is None:
                continue
            文本 = str(原始内容 or "")

            搜敌匹配 = _搜敌次数正则.search(文本)
            if 搜敌匹配:
                次数 = int(搜敌匹配.group(1))
                if 当前轮最大搜敌 > 0 and 次数 < 当前轮最大搜敌:
                    搜敌轮次.append((当前轮最后时间, 当前轮最大搜敌))
                    当前轮最大搜敌 = 0
                if 次数 > 当前轮最大搜敌:
                    当前轮最大搜敌 = 次数
                    当前轮最后时间 = 时间戳

            if any(标记 in 文本 for 标记 in _搜敌完成标记) and 当前轮最大搜敌 > 0:
                搜敌轮次.append((时间戳, 当前轮最大搜敌))
                当前轮最大搜敌 = 0

            结果匹配 = _战斗结果正则.search(文本)
            if 结果匹配:
                if 当前轮最大搜敌 > 0:
                    搜敌轮次.append((时间戳, 当前轮最大搜敌))
                    当前轮最大搜敌 = 0
                战斗列表.append(
                    _战斗事件(
                        时间戳=时间戳,
                        结果=_规范化结果(结果匹配.group("结果")),
                        星数=_安全整数(结果匹配.group("星数")),
                        摧毁率=_安全浮点(结果匹配.group("摧毁率")),
                    )
                )

            净变化匹配 = _净变化正则.search(文本)
            if 净变化匹配:
                收益列表.append(
                    _收益事件(
                        时间戳=时间戳,
                        金币=_安全非负整数(净变化匹配.group("金币")),
                        圣水=_安全非负整数(净变化匹配.group("圣水")),
                        黑油=_安全非负整数(净变化匹配.group("黑油")),
                    )
                )

        if 当前轮最大搜敌 > 0:
            搜敌轮次.append((当前轮最后时间, 当前轮最大搜敌))

        return 战斗列表, 收益列表, 搜敌轮次

    @staticmethod
    def _解析状态(
        状态行: Iterable[tuple[Any, Any, Any]],
        学习行: Iterable[tuple[Any, Any]],
        起始时间: float,
        截止时间: float,
    ) -> tuple[list[_战斗事件], list[_收益事件]]:
        状态战斗: list[_战斗事件] = []
        状态收益: list[_收益事件] = []

        for 原始时间, 状态类型, 原始值 in 状态行:
            行时间 = _安全浮点(原始时间)
            数据 = _解析JSON字典(原始值)
            if not 数据:
                continue
            时间 = _安全浮点(数据.get("时间")) or 行时间
            if 时间 is None or not (起始时间 <= 时间 < 截止时间):
                continue

            if 状态类型 == "战斗资源分析":
                净变化 = 数据.get("本场净变化")
                if not isinstance(净变化, dict):
                    净变化 = {}
                状态收益.append(
                    _收益事件(
                        时间戳=时间,
                        金币=_安全非负整数(净变化.get("金币")),
                        圣水=_安全非负整数(净变化.get("圣水")),
                        黑油=_安全非负整数(净变化.get("黑油")),
                        结果=(_规范化结果(数据["结果"]) if "结果" in 数据 else None),
                        星数=_安全整数(数据.get("星数")),
                        摧毁率=_安全浮点(数据.get("摧毁率")),
                    )
                )
            elif 状态类型 in {"战斗记录", "战斗结果"}:
                状态战斗.append(
                    _战斗事件(
                        时间戳=时间,
                        结果=_规范化结果(数据.get("结果")),
                        星数=_安全整数(数据.get("星数")),
                        摧毁率=_安全浮点(数据.get("摧毁率")),
                    )
                )

        已见学习键: set[tuple[int, str, int | None, float | None]] = set()
        for _行时间, 原始值 in 学习行:
            数据 = _解析JSON字典(原始值)
            近期 = 数据.get("近期")
            if not isinstance(近期, list):
                continue
            for 项 in 近期:
                if not isinstance(项, dict):
                    continue
                时间 = _安全浮点(项.get("时间"))
                if 时间 is None or not (起始时间 <= 时间 < 截止时间):
                    continue
                结果 = _规范化结果(项.get("结果"))
                星数 = _安全整数(项.get("星数"))
                摧毁率 = _安全浮点(项.get("摧毁率"))
                键 = (int(时间), 结果, 星数, 摧毁率)
                if 键 in 已见学习键:
                    continue
                已见学习键.add(键)
                状态战斗.append(_战斗事件(时间, 结果, 星数, 摧毁率))

        状态战斗.sort(key=lambda 项: 项.时间戳)
        状态收益.sort(key=lambda 项: 项.时间戳)
        return 状态战斗, 状态收益

    @staticmethod
    def _合并战斗与收益(
        日志战斗: list[_战斗事件],
        日志收益: list[_收益事件],
        状态战斗: list[_战斗事件],
        状态收益: list[_收益事件],
    ) -> tuple[list[_战斗事件], list[_收益事件]]:
        # 1. 合并战斗结果（优先保留日志记录，并用学习/状态补充或补全缺失项）
        战斗列表: list[_战斗事件] = [
            _战斗事件(项.时间戳, 项.结果, 项.星数, 项.摧毁率) for 项 in 日志战斗
        ]
        for 候选 in 状态战斗:
            匹配 = None
            for 已有 in 战斗列表:
                if abs(已有.时间戳 - 候选.时间戳) <= 30.0 and (
                    已有.结果 == 候选.结果
                    or 已有.结果 == "未知"
                    or 候选.结果 == "未知"
                ):
                    匹配 = 已有
                    break
            if 匹配 is not None:
                if 匹配.结果 == "未知" and 候选.结果 != "未知":
                    匹配.结果 = 候选.结果
                if 匹配.星数 is None and 候选.星数 is not None:
                    匹配.星数 = 候选.星数
                if 匹配.摧毁率 is None and 候选.摧毁率 is not None:
                    匹配.摧毁率 = 候选.摧毁率
            else:
                战斗列表.append(
                    _战斗事件(候选.时间戳, 候选.结果, 候选.星数, 候选.摧毁率)
                )

        # 2. 合并收益记录（同一场 30 秒内已有日志净变化时不重复计算）
        收益列表: list[_收益事件] = [
            _收益事件(项.时间戳, 项.金币, 项.圣水, 项.黑油) for 项 in 日志收益
        ]
        for 候选 in 状态收益:
            if any(abs(已有.时间戳 - 候选.时间戳) <= 30.0 for 已有 in 日志收益):
                continue
            收益列表.append(候选)
            # 若仅有战斗资源分析（无日志与战斗学习），仍应计入对应场次
            if not any(
                -120.0 <= (候选.时间戳 - 已有.时间戳) <= 30.0
                for 已有 in 战斗列表
            ):
                战斗列表.append(
                    _战斗事件(
                        时间戳=候选.时间戳,
                        结果=_规范化结果(候选.结果),
                        星数=候选.星数,
                        摧毁率=候选.摧毁率,
                    )
                )

        战斗列表.sort(key=lambda 项: 项.时间戳)
        收益列表.sort(key=lambda 项: 项.时间戳)
        return 战斗列表, 收益列表

    @staticmethod
    def _汇总单日(
        日期: str,
        起始时间: float,
        截止时间: float,
        战斗列表: list[_战斗事件],
        收益列表: list[_收益事件],
        搜敌轮次: list[tuple[float, int]],
    ) -> tuple[每日汇总, tuple[小时效率项, ...]]:
        当日战斗 = [项 for 项 in 战斗列表 if 起始时间 <= 项.时间戳 < 截止时间]
        当日收益 = [项 for 项 in 收益列表 if 起始时间 <= 项.时间戳 < 截止时间]
        当日搜敌 = [次数 for ts, 次数 in 搜敌轮次 if 起始时间 <= ts < 截止时间]

        小时场次 = [0] * 24
        小时胜场 = [0] * 24
        小时金币 = [0] * 24
        小时圣水 = [0] * 24
        小时黑油 = [0] * 24
        活跃小时集合: set[int] = set()

        胜场 = 0
        负场 = 0
        未知场次 = 0
        有效摧毁率: list[float] = []

        for 项 in 当日战斗:
            小时 = time.localtime(项.时间戳).tm_hour
            小时场次[小时] += 1
            活跃小时集合.add(小时)
            if 项.结果 == "胜利":
                胜场 += 1
                小时胜场[小时] += 1
            elif 项.结果 == "失败":
                负场 += 1
            else:
                未知场次 += 1
            if 项.摧毁率 is not None:
                有效摧毁率.append(项.摧毁率)

        总金币 = 0
        总圣水 = 0
        总黑油 = 0
        for 项 in 当日收益:
            小时 = time.localtime(项.时间戳).tm_hour
            活跃小时集合.add(小时)
            小时金币[小时] += 项.金币
            小时圣水[小时] += 项.圣水
            小时黑油[小时] += 项.黑油
            总金币 += 项.金币
            总圣水 += 项.圣水
            总黑油 += 项.黑油

        总场次 = len(当日战斗)
        已识别胜负 = 胜场 + 负场
        胜率 = round(胜场 / 已识别胜负 * 100, 1) if 已识别胜负 > 0 else None
        平均摧毁率 = (
            round(sum(有效摧毁率) / len(有效摧毁率), 1)
            if 有效摧毁率
            else None
        )

        活跃小时数 = len(活跃小时集合)
        if 活跃小时数 > 0:
            每小时场次 = round(总场次 / 活跃小时数, 2)
            每小时金币 = round(总金币 / 活跃小时数, 1)
            每小时圣水 = round(总圣水 / 活跃小时数, 1)
            每小时黑油 = round(总黑油 / 活跃小时数, 1)
        else:
            每小时场次 = 0.0
            每小时金币 = 0.0
            每小时圣水 = 0.0
            每小时黑油 = 0.0

        # 仅取不超过场次或已完成的搜敌轮次样本；若搜敌结束但未开战，也保留作参考
        搜敌样本数 = len(当日搜敌)
        平均搜敌次数 = (
            round(sum(当日搜敌) / 搜敌样本数, 1) if 搜敌样本数 > 0 else None
        )

        汇总 = 每日汇总(
            日期=日期,
            总场次=总场次,
            胜场=胜场,
            负场=负场,
            未知结果场次=未知场次,
            胜率=胜率,
            平均摧毁率=平均摧毁率,
            总掠夺金币=总金币,
            总掠夺圣水=总圣水,
            总掠夺黑油=总黑油,
            活跃小时数=活跃小时数,
            每小时场次=每小时场次,
            每小时金币=每小时金币,
            每小时圣水=每小时圣水,
            每小时黑油=每小时黑油,
            平均搜敌次数=平均搜敌次数,
            搜敌样本数=搜敌样本数,
        )
        分小时 = tuple(
            小时效率项(
                小时=小时,
                场次=小时场次[小时],
                胜场=小时胜场[小时],
                金币=小时金币[小时],
                圣水=小时圣水[小时],
                黑油=小时黑油[小时],
            )
            for 小时 in range(24)
        )
        return 汇总, 分小时

    def 生成战报(
        self,
        机器人ID: str | None = None,
        *,
        当前时间: float | None = None,
    ) -> 每日战报结果:
        现在 = float(当前时间 if 当前时间 is not None else time.time())
        目标机器人 = self._解析机器人ID(机器人ID)

        当前日期对象 = datetime.fromtimestamp(现在)
        今日零点对象 = datetime(当前日期对象.year, 当前日期对象.month, 当前日期对象.day)
        昨日零点对象 = 今日零点对象 - timedelta(days=1)
        明日零点对象 = 今日零点对象 + timedelta(days=1)

        昨日零点 = 昨日零点对象.timestamp()
        今日零点 = 今日零点对象.timestamp()
        明日零点 = 明日零点对象.timestamp()

        日志行, 状态行, 学习行 = self._读取原始数据(目标机器人, 昨日零点, 明日零点)
        日志战斗, 日志收益, 搜敌轮次 = self._解析日志(日志行)
        状态战斗, 状态收益 = self._解析状态(状态行, 学习行, 昨日零点, 明日零点)
        全部战斗, 全部收益 = self._合并战斗与收益(
            日志战斗, 日志收益, 状态战斗, 状态收益
        )

        今日汇总, 今日分小时 = self._汇总单日(
            今日零点对象.strftime("%Y-%m-%d"),
            今日零点,
            明日零点,
            全部战斗,
            全部收益,
            搜敌轮次,
        )
        昨日汇总, _ = self._汇总单日(
            昨日零点对象.strftime("%Y-%m-%d"),
            昨日零点,
            今日零点,
            全部战斗,
            全部收益,
            搜敌轮次,
        )

        return 每日战报结果(
            机器人ID=目标机器人,
            生成时间=现在,
            今日=今日汇总,
            昨日=昨日汇总,
            今日分小时=今日分小时,
        )

    def 导出字典(
        self,
        机器人ID: str | None = None,
        *,
        当前时间: float | None = None,
    ) -> dict[str, Any]:
        return self.生成战报(机器人ID, 当前时间=当前时间).to_dict()


def 生成每日战报(
    数据库: 任务数据库 | str | Path | None,
    机器人ID: str | None = None,
    *,
    当前时间: float | None = None,
) -> 每日战报结果:
    return 战报服务(数据库).生成战报(机器人ID, 当前时间=当前时间)
