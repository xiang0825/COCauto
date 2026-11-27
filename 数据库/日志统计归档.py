"""清空任务日志前把“统计要用的日志行”按日期归档到 运行时状态。

背景：任务日志在启动/退出/脚本停止后都会导出备份再清空，而战报（今日 vs 昨日、
分小时效率）是从任务日志里解析战斗结果、资源净变化、搜敌次数、
部落竞赛积分的。备份只留上一份，一天停几次就会丢掉前几次会话的统计。

这里在清空前把相关原始行（不改写内容）存进 ``运行时状态`` 的
``日志统计归档``（只保留最新一行快照）：``{"按日": {"YYYY-MM-DD": [[时间戳, 内容], ...]}}``，
只保留今天和昨天（跨日自动丢掉更早的日期）。读取方把归档行与表里现存的行按
(时间戳, 内容) 去重合并，所以与备份文件、未清掉的行重叠也不会重复计数。

顶栏“今日数据条”用的是 ``今日统计``（运行时状态，按日期累计），本来就不依赖任务日志。
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Iterable

状态类型 = "日志统计归档"
保留天数 = 2
每日上限行数 = 50_000

# 战报服务解析用到的日志特征；只归档命中的行。
统计相关片段 = (
    "战斗结果：",
    "本场资源净变化",
    "搜索次数[",
    "黑水优先筛选：候选[",
    "成功找到敌人",
    "对方17本，大本营比较高",
    "搜索按钮消失后已连续确认自然回营",
)
竞赛相关片段 = ("个人积分", "已接任务", "领奖")


def 是统计相关(内容: str) -> bool:
    文本 = str(内容 or "")
    if any(片段 in 文本 for 片段 in 统计相关片段):
        return True
    return "部落竞赛" in 文本 and any(片段 in 文本 for 片段 in 竞赛相关片段)


def _日期(时间戳: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(float(时间戳)))


def 保留日期(现在: float | None = None) -> list[str]:
    今天 = datetime.fromtimestamp(time.time() if 现在 is None else float(现在)).date()
    return [(今天 - timedelta(days=偏移)).strftime("%Y-%m-%d") for 偏移 in range(保留天数)]


def _读取(连接: sqlite3.Connection, 机器人标志: str) -> tuple[int | None, dict]:
    行 = 连接.execute(
        "SELECT 记录ID, 状态值 FROM 运行时状态 WHERE 机器人标志 = ? AND 状态类型 = ? "
        "ORDER BY 记录ID DESC LIMIT 1",
        (机器人标志, 状态类型),
    ).fetchone()
    if not 行:
        return None, {}
    try:
        数据 = json.loads(行[1])
    except (TypeError, ValueError):
        数据 = {}
    按日 = 数据.get("按日") if isinstance(数据, dict) else None
    return 行[0], (dict(按日) if isinstance(按日, dict) else {})


def 合并归档(已有: dict, 新行: Iterable[tuple[float, str]], 现在: float | None = None) -> dict:
    """把新行并入按日归档：去重、按时间排序、只留保留日期、每天限量（丢最旧的）。"""
    保留 = set(保留日期(现在))
    结果: dict[str, list] = {}
    for 日期, 行列表 in (已有 or {}).items():
        if 日期 in 保留 and isinstance(行列表, list):
            结果[日期] = [list(项) for 项 in 行列表 if isinstance(项, (list, tuple)) and len(项) == 2]
    for 时间戳, 内容 in 新行:
        日期 = _日期(时间戳)
        if 日期 in 保留:
            结果.setdefault(日期, []).append([float(时间戳), str(内容)])
    for 日期, 行列表 in 结果.items():
        去重 = {(float(时间), str(内容)) for 时间, 内容 in 行列表}
        结果[日期] = [list(项) for 项 in sorted(去重)[-每日上限行数:]]
    return 结果


def 归档待清空日志(连接: sqlite3.Connection, 最大ID, 现在: float | None = None) -> int:
    """清空前调用（同一连接、未提交前）：归档 记录ID <= 最大ID 中今天/昨天的统计相关行。

    返回归档的新行数；出错直接抛出，调用方据此放弃本次清空。
    """
    现在 = time.time() if 现在 is None else float(现在)
    起点 = datetime.strptime(保留日期(现在)[-1], "%Y-%m-%d").timestamp()
    按机器人: dict[str, list[tuple[float, str]]] = {}
    for 标志, 时间戳, 内容 in 连接.execute(
        "SELECT 机器人标志, 记录时间, 日志内容 FROM 任务日志 WHERE 记录ID <= ? AND 记录时间 >= ? "
        "ORDER BY 记录ID",
        (最大ID, 起点),
    ):
        if 是统计相关(内容):
            按机器人.setdefault(str(标志), []).append((float(时间戳 or 0), str(内容)))
    总数 = 0
    for 标志, 行列表 in 按机器人.items():
        记录ID, 已有 = _读取(连接, 标志)
        新归档 = 合并归档(已有, 行列表, 现在)
        值 = json.dumps({"按日": 新归档}, ensure_ascii=False, separators=(",", ":"))
        if 记录ID is None:
            连接.execute(
                "INSERT INTO 运行时状态 (机器人标志, 记录时间, 状态类型, 状态值) VALUES (?, ?, ?, ?)",
                (标志, 现在, 状态类型, 值),
            )
        else:
            连接.execute(
                "UPDATE 运行时状态 SET 记录时间 = ?, 状态值 = ? WHERE 记录ID = ?",
                (现在, 值, 记录ID),
            )
        总数 += len(行列表)
    return 总数


def 读取归档行(连接: sqlite3.Connection, 机器人标志: str, 起始时间: float, 截止时间: float) -> list[tuple[float, str]]:
    """只读：归档里 [起始, 截止) 内的行；表或记录不存在时返回空列表。"""
    try:
        _, 按日 = _读取(连接, 机器人标志)
    except sqlite3.Error:
        return []
    结果 = []
    for 行列表 in 按日.values():
        for 项 in 行列表 if isinstance(行列表, list) else []:
            try:
                时间戳, 内容 = float(项[0]), str(项[1])
            except (TypeError, ValueError, IndexError):
                continue
            if 起始时间 <= 时间戳 < 截止时间:
                结果.append((时间戳, 内容))
    return sorted(结果)
