"""日常任务共用：资源 JSON 读取、校准开关、按日记录、冷却与危险词判断。

- JSON 查找顺序与识别参数一致：EXE 同级 资源/日常 → _internal/资源/日常 →
  源码根 资源/日常。缺文件/格式错误时返回代码默认值，绝不让任务崩溃。
- 按日记录存数据库状态类型 ``日常任务记录``：``{任务键: {...}}``，
  “今天”按本地日期计算（夜世界星级奖励、都城次数都按日/周重置）。
"""
from __future__ import annotations

import copy
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from 工具包.识别参数 import 资源候选目录

资源子目录 = Path("资源") / "日常"
记录状态类型 = "日常任务记录"

# 任何日常任务都绝不点击含这些字的按钮：花宝石、购买、跳过、重置、加速。
危险词 = (
    "宝石", "寶石", "购买", "購買", "跳过", "跳過", "重置", "加速",
    "立即完成", "商店", "充值", "gem", "buy", "skip", "boost",
)


def 查找日常参数文件(名称: str, 候选目录: Iterable[Path] | None = None) -> Path | None:
    for 目录 in (候选目录 if 候选目录 is not None else 资源候选目录()):
        路径 = Path(目录) / 资源子目录 / f"{名称}.json"
        if 路径.is_file():
            return 路径
    return None


def 加载日常参数(名称: str, 默认值: dict, 路径: str | Path | None = None) -> dict:
    """读取 资源/日常/<名称>.json 并与默认值浅合并（JSON 同名键覆盖）。

    每次调用都重新读文件：日常任务一小时最多跑几次，改了 EXE 同级 JSON
    不用重启就能生效。类型与默认值不符的键忽略。
    """
    结果 = copy.deepcopy(默认值)
    文件 = Path(路径) if 路径 is not None else 查找日常参数文件(名称)
    if 文件 is None or not Path(文件).is_file():
        结果["_来源"] = "代码默认值"
        return 结果
    try:
        with open(文件, encoding="utf-8") as 句柄:
            数据 = json.load(句柄)
    except (OSError, ValueError) as 异常:
        结果["_来源"] = f"读取失败（{异常}），代码默认值"
        return 结果
    if not isinstance(数据, dict):
        结果["_来源"] = "顶层不是对象，代码默认值"
        return 结果
    for 键, 值 in 数据.items():
        if 键.startswith("_") or 键 == "说明":
            continue
        if 键 in 结果 and not _类型兼容(结果[键], 值):
            continue
        结果[键] = 值
    结果["_来源"] = str(文件)
    return 结果


def _类型兼容(默认, 值) -> bool:
    if 默认 is None:
        return True
    if isinstance(默认, bool):
        return isinstance(值, bool)
    if isinstance(默认, (int, float)):
        return isinstance(值, (int, float)) and not isinstance(值, bool)
    if isinstance(默认, (list, tuple)):
        return isinstance(值, list)
    return isinstance(值, type(默认))


def 已校准(参数: dict) -> bool:
    """只有 JSON 明确写 ``"calibrated": true`` 才算实机校准过。"""
    return 参数.get("calibrated") is True


def 含危险词(文本: Any) -> bool:
    规范 = str(文本 or "").replace(" ", "").lower()
    return any(词.lower() in 规范 for 词 in 危险词)


def 今天(现在: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if 现在 is None else 现在).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 记录读写
def 读取任务记录(数据库, 机器人标志: str, 任务键: str) -> dict:
    try:
        完整 = 数据库.获取最新完整状态(机器人标志)
        数据 = getattr(完整, "状态数据", None) or {}
        全部 = 数据.get(记录状态类型) if isinstance(数据, dict) else None
        记录 = 全部.get(任务键) if isinstance(全部, dict) else None
        return dict(记录) if isinstance(记录, dict) else {}
    except Exception:
        return {}


def 写入任务记录(数据库, 机器人标志: str, 任务键: str, 记录: dict) -> None:
    try:
        完整 = 数据库.获取最新完整状态(机器人标志)
        数据 = getattr(完整, "状态数据", None) or {}
        全部 = 数据.get(记录状态类型) if isinstance(数据, dict) else None
        全部 = dict(全部) if isinstance(全部, dict) else {}
    except Exception:
        全部 = {}
    全部[任务键] = dict(记录)
    数据库.更新状态(机器人标志, 记录状态类型, 全部)


def 今日记录(数据库, 机器人标志: str, 任务键: str, 现在: float | None = None) -> dict:
    """返回当天的记录；跨日自动清零（保留 ``下次检查时间``）。"""
    记录 = 读取任务记录(数据库, 机器人标志, 任务键)
    if 记录.get("日期") != 今天(现在):
        记录 = {"日期": 今天(现在), "下次检查时间": 记录.get("下次检查时间", 0)}
    return 记录


def 冷却剩余秒(记录: dict, 现在: float | None = None) -> float:
    现在 = time.time() if 现在 is None else 现在
    try:
        return max(0.0, float(记录.get("下次检查时间", 0) or 0) - 现在)
    except (TypeError, ValueError):
        return 0.0


def 请求等待(上下文, 秒数: float, 原因: str) -> None:
    请求 = getattr(上下文, "请求任务计划等待", None)
    if callable(请求):
        请求(秒数, 原因)
        return
    上下文.任务计划等待秒 = max(float(getattr(上下文, "任务计划等待秒", 0.0) or 0.0), min(3600.0, 秒数))
    上下文._任务计划等待原因 = 原因


def OCR文本列表(识别结果) -> list[tuple[str, tuple[float, float] | None]]:
    """把 RapidOCR 结果规范为 [(去空格文本, 中心点或None)]。"""
    输出 = []
    for 项 in 识别结果 or []:
        if not isinstance(项, (list, tuple)) or len(项) < 2:
            continue
        文本 = str(项[1]).replace(" ", "").replace("\n", "")
        中心 = None
        try:
            点列表 = [(float(点[0]), float(点[1])) for 点 in 项[0]]
            if 点列表:
                中心 = (
                    sum(p[0] for p in 点列表) / len(点列表),
                    sum(p[1] for p in 点列表) / len(点列表),
                )
        except (TypeError, ValueError, IndexError):
            中心 = None
        输出.append((文本, 中心))
    return 输出
