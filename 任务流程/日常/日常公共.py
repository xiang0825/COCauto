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


# ---------------------------------------------------------------- 图像与护栏
def 规范文本(文本: Any) -> str:
    """去空白、繁转简、转小写（复用部落竞赛的繁简表）。"""
    from 任务流程.活动.部落竞赛 import 规范文本 as _规范

    return _规范(文本)


def 查找资源图片(相对路径: str) -> Path | None:
    """相对 资源/ 查找图片：EXE 同级优先。"""
    for 目录 in 资源候选目录():
        路径 = Path(目录) / "资源" / 相对路径
        if 路径.is_file():
            return 路径
    return None


_图片缓存: dict[str, Any] = {}


def 读取图片(相对路径: str):
    if 相对路径 in _图片缓存:
        return _图片缓存[相对路径]
    import cv2
    import numpy as np

    路径 = 查找资源图片(相对路径)
    图 = None
    if 路径 is not None:
        图 = cv2.imdecode(np.fromfile(str(路径), dtype=np.uint8), cv2.IMREAD_COLOR)
    _图片缓存[相对路径] = 图
    return 图


def 匹配模板(图像, 模板, 区域=None, 阈值: float = 0.85, 缩放=(1.0,)):
    """返回 (中心x, 中心y, 分数)（800x600 坐标）；未命中返回 None。"""
    import cv2

    if 图像 is None or 模板 is None or not hasattr(图像, "shape"):
        return None
    高, 宽 = 图像.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in (区域 or (0, 0, 宽, 高))]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(宽, x2), min(高, y2)
    子图 = 图像[y1:y2, x1:x2]
    最佳 = None
    for 比例 in 缩放:
        当前 = 模板 if 比例 == 1.0 else cv2.resize(模板, None, fx=比例, fy=比例)
        th, tw = 当前.shape[:2]
        if th < 4 or tw < 4 or 子图.shape[0] < th or 子图.shape[1] < tw:
            continue
        结果 = cv2.matchTemplate(子图, 当前, cv2.TM_CCOEFF_NORMED)
        _, 分数, _, 位置 = cv2.minMaxLoc(结果)
        if 分数 >= 阈值 and (最佳 is None or 分数 > 最佳[2]):
            最佳 = (x1 + 位置[0] + tw // 2, y1 + 位置[1] + th // 2, float(分数))
    return 最佳


宝石图标路径 = "活动/部落竞赛/宝石图标.png"


def 区域含宝石图标(图像, 区域, 阈值: float = 0.80) -> bool:
    """多尺度匹配宝石图标；模板缺失时按“有宝石”处理（宁可不点）。"""
    模板 = 读取图片(宝石图标路径)
    if 模板 is None:
        return True
    return 匹配模板(图像, 模板, 区域, 阈值, 缩放=(0.6, 0.8, 1.0, 1.2, 1.5)) is not None


def 扩展区域(中心, 半宽: int, 半高: int) -> tuple[int, int, int, int]:
    x, y = int(中心[0]), int(中心[1])
    return (max(0, x - 半宽), max(0, y - 半高), min(800, x + 半宽), min(600, y + 半高))


def 解析数量(文本: Any) -> int | None:
    """从 "x5" / "×12" / "12" 等 OCR 文本取数量。"""
    import re

    匹配 = re.search(r"(\d+)", str(文本 or "").replace(",", "").replace(" ", ""))
    return int(匹配.group(1)) if 匹配 else None


class OCR不可用(Exception):
    """OCR 引擎缺失或识别异常：不能据此判定“没有危险文字”。"""


class 日常面板任务基类:
    """C1/C2 共用的截图、OCR、点击前护栏。子类需有 上下文 / 参数。"""

    上下文: Any
    参数: dict

    def 截图(self):
        op = self.上下文.op
        try:
            return op.获取屏幕图像cv(0, 0, 800, 600, 强制刷新=True)
        except TypeError:
            return op.获取屏幕图像cv(0, 0, 800, 600)

    def OCR(self, 图像, 区域) -> list[tuple[str, tuple[float, float] | None]]:
        """OCR 图像的一个区域，返回 [(规范文本, 800x600 中心)]。

        引擎缺失或识别异常时抛 ``OCR不可用``：调用方不能把它当成“没有文字”。
        """
        x1, y1, x2, y2 = [int(v) for v in 区域]
        获取 = getattr(self.上下文, "获取OCR引擎", None)
        try:
            引擎 = 获取() if callable(获取) else None
        except Exception as 异常:
            raise OCR不可用(f"获取 OCR 引擎失败：{异常}") from 异常
        if 引擎 is None:
            raise OCR不可用("没有 OCR 引擎")
        try:
            结果 = 引擎(图像[y1:y2, x1:x2])
            if isinstance(结果, tuple):
                结果 = 结果[0]
        except Exception as 异常:
            raise OCR不可用(f"OCR 识别异常：{异常}") from 异常
        输出 = []
        for 文本, 中心 in OCR文本列表(结果):
            if 中心 is not None:
                中心 = (中心[0] + x1, 中心[1] + y1)
            输出.append((规范文本(文本), 中心))
        return 输出

    def OCR或空(self, 图像, 区域) -> list[tuple[str, tuple[float, float] | None]]:
        """用于“找按钮/确认页面/读数量”：OCR 不可用时返回空 → 找不到 → 不点。

        绝不能用于“没有危险文字才点”的判定，那里用 ``点击前护栏``。
        """
        try:
            return self.OCR(图像, 区域)
        except OCR不可用 as 异常:
            self.日志(f"{异常}，按未识别处理")
            return []

    def 区域有关键词(self, 图像, 区域, 关键词) -> tuple[str, tuple[float, float] | None] | None:
        词表 = [规范文本(词) for 词 in 关键词 if str(词).strip()]
        for 文本, 中心 in self.OCR或空(图像, 区域):
            if any(词 in 文本 for 词 in 词表):
                return 文本, 中心
        return None

    def 点击前护栏(self, 图像, 按钮区域, 说明: str) -> bool:
        """按钮区域出现宝石图标或宝石/购买/跳过/重置/加速等文字一律拒绝。"""
        if 区域含宝石图标(图像, 按钮区域):
            self.日志(f"{说明}：按钮区域有宝石图标，拒绝点击")
            return False
        try:
            文字 = self.OCR(图像, 按钮区域)
        except OCR不可用 as 异常:
            self.日志(f"{说明}：{异常}，无法确认没有危险文字，拒绝点击")
            return False
        for 文本, _ in 文字:
            if 含危险词(文本):
                self.日志(f"{说明}：按钮文字「{文本}」含危险词，拒绝点击")
                return False
        return True

    def 已停止(self) -> bool:
        停止 = getattr(self.上下文, "停止事件", None)
        return bool(停止 is not None and 停止.is_set())

    def 安全关闭(self, 关闭点, 面板区域, 面板关键词, 说明: str, 已关闭判定=None) -> bool:
        """关闭本任务打开的面板：停止时不点；先重新截图确认面板仍在、关闭点过护栏。

        ``已关闭判定(图)`` 为真表示面板已被游戏自己关掉（例如捐满后弹窗自动
        收起），此时不点击、返回 True。确认不了当前页面返回 False（页面不可信）。
        """
        if self.已停止():
            self.日志(f"{说明}：已收到停止信号，不再点击")
            return True
        图 = self.截图()
        if not self.区域有关键词(图, 面板区域, 面板关键词):
            if callable(已关闭判定) and 已关闭判定(图):
                return True
            self.日志(f"{说明}：重新截图未确认面板仍在，不点击关闭点")
            return False
        x, y = 关闭点
        if not self.点击前护栏(图, 扩展区域((x, y), 25, 25), 说明):
            return False
        return self.点击(x, y, 说明)

    def 点击(self, x, y, 说明: str, 等待毫秒: int | None = None) -> bool:
        if self.已停止():
            self.日志(f"{说明}：已收到停止信号，不再点击")
            return False
        if self.上下文.点击(int(x), int(y), 是否精确点击=True) is False:
            self.日志(f"{说明}：点击被安全输入层拒绝")
            return False
        延时 = getattr(self.上下文, "脚本延时", None)
        等待 = int(self.参数.get("点击后等待毫秒", 700)) if 等待毫秒 is None else int(等待毫秒)
        if callable(延时) and 等待 > 0:
            延时(等待)
        return True

    def 日志(self, 文本: str) -> None:
        self.上下文.置脚本状态(f"{getattr(self, '日志前缀', '日常')}：{文本}")
