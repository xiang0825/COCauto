"""每日完成通知：每天到点（默认 23:30）用桌面弹窗汇总今天的战果。

内容：今天场次、胜率、金/圣水/黑油收益（复用 ``战报服务``），部落竞赛今天
接到的任务、个人积分和是否可领奖。竞赛奖励绝不自动领取，只提示“可领奖”。

每天每个机器人只发一次：发送日期记在 ``系统配置`` 表，重启程序不会重复弹。
任务日志每次启动会导出到 ``上次日志.bak.jsonl`` 后清空，所以统计时把备份里
今天的记录一并算上。所有入口吞掉异常，通知失败绝不影响脚本运行。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from 应用.战报服务 import 战报服务
from 数据库.任务数据库 import 规范化每日通知时间

已发送配置键前缀 = "每日通知已发送:"
备份文件名 = "上次日志.bak.jsonl"
备份最多读取字节 = 20 * 1024 * 1024

_个人积分正则 = re.compile(r"部落竞赛：个人积分\s*(\d+)\s*/\s*(\d+)")
_已接任务正则 = re.compile(r"部落竞赛：已接任务(?:（[^）]*）)?：(?P<类型>[^（\s]+)（(?P<积分>\d+|\?)分）")
_可领奖词 = ("可以领奖", "可以去领奖", "个人积分已满", "已满分", "手动领奖")


def _今日零点(现在: float) -> float:
    日期 = datetime.fromtimestamp(现在)
    return datetime(日期.year, 日期.month, 日期.day).timestamp()


def 读取备份日志(数据库路径, 机器人标志: str, 起始: float, 截止: float) -> list[tuple[float, str]]:
    """从 ``上次日志.bak.jsonl`` 尾部读取指定机器人在时间窗内的日志。"""
    try:
        路径 = Path(数据库路径).with_name(备份文件名)
        if not 路径.is_file():
            return []
        大小 = 路径.stat().st_size
        with open(路径, "rb") as 文件:
            if 大小 > 备份最多读取字节:
                文件.seek(大小 - 备份最多读取字节)
                文件.readline()  # 丢弃被截断的半行
            数据 = 文件.read()
    except OSError:
        return []
    结果 = []
    for 行 in 数据.decode("utf-8", errors="replace").splitlines():
        try:
            记录 = json.loads(行)
            if str(记录.get("机器人")) != str(机器人标志):
                continue
            时间 = float(记录.get("ts") or 0)
            if 起始 <= 时间 < 截止:
                结果.append((时间, str(记录.get("内容") or "")))
        except (ValueError, TypeError, AttributeError):
            continue
    return 结果


class _含备份战报服务(战报服务):
    """把上次会话备份里的日志也算进今日战报（启动时任务日志会被清空）。"""

    def __init__(self, 数据库, 备份行: list[tuple[float, str]]):
        super().__init__(数据库)
        self._备份行 = 备份行

    def _读取原始数据(self, 机器人ID, 起始时间, 截止时间):
        日志行, 状态行, 学习行 = super()._读取原始数据(机器人ID, 起始时间, 截止时间)
        已有 = {(float(时间), str(内容)) for 时间, 内容 in 日志行}
        补充 = [
            (时间, 内容) for 时间, 内容 in self._备份行
            if 起始时间 <= 时间 < 截止时间 and (时间, 内容) not in 已有
        ]
        if 补充:
            日志行 = sorted(list(日志行) + 补充, key=lambda 项: float(项[0]))
        return 日志行, 状态行, 学习行


def 汇总部落竞赛(日志行: Iterable[tuple[float, str]], 状态记录: Optional[dict] = None) -> dict[str, Any]:
    """从今天的日志里提取部落竞赛：已接任务、个人积分（首/末）和是否可领奖。"""
    已接: list[str] = []
    积分序列: list[tuple[int, int]] = []
    可领奖 = False
    for _时间, 内容 in sorted(日志行, key=lambda 项: float(项[0])):
        文本 = str(内容 or "")
        if "部落竞赛" not in 文本:
            continue
        匹配 = _个人积分正则.search(文本)
        if 匹配:
            积分序列.append((int(匹配.group(1)), int(匹配.group(2))))
        匹配 = _已接任务正则.search(文本)
        if 匹配:
            已接.append(f"{匹配.group('类型')}{匹配.group('积分')}分")
        if any(词 in 文本 for 词 in _可领奖词):
            可领奖 = True
    if not 积分序列 and isinstance(状态记录, dict):
        记录积分 = 状态记录.get("个人积分")
        if isinstance(记录积分, (list, tuple)) and len(记录积分) == 2:
            try:
                积分序列.append((int(记录积分[0]), int(记录积分[1])))
            except (TypeError, ValueError):
                pass
    if isinstance(状态记录, dict) and 状态记录.get("结果") == "已满分":
        可领奖 = True
    最新 = 积分序列[-1] if 积分序列 else None
    if 最新 is not None and 最新[1] > 0 and 最新[0] >= 最新[1]:
        可领奖 = True
    return {
        "已接任务": 已接,
        "个人积分": 最新,
        "今日积分增加": (最新[0] - 积分序列[0][0]) if len(积分序列) >= 2 else None,
        "可领奖": 可领奖,
    }


def _格式数量(数值: int) -> str:
    数值 = int(数值 or 0)
    符号 = "+" if 数值 > 0 else ("-" if 数值 < 0 else "")
    绝对 = abs(数值)
    if 绝对 >= 1_000_000:
        return f"{符号}{绝对 / 1_000_000:.1f}M"
    if 绝对 >= 10_000:
        return f"{符号}{绝对 / 1000:.0f}k"
    return f"{符号}{绝对}"


def 生成每日摘要(数据库, 机器人标志: str, 现在: Optional[float] = None) -> tuple[str, str, bool]:
    """返回 (标题, 正文, 今天是否有可汇总的内容)。"""
    现在 = float(time.time() if 现在 is None else 现在)
    零点 = _今日零点(现在)
    明日零点 = (datetime.fromtimestamp(零点) + timedelta(days=1)).timestamp()
    数据库路径 = getattr(数据库, "文件路径", None)
    备份行 = 读取备份日志(数据库路径, 机器人标志, 零点 - 86400, 明日零点) if 数据库路径 else []

    战报 = _含备份战报服务(数据库, 备份行).生成战报(机器人标志, 当前时间=现在)
    今日 = 战报.今日
    if 今日.胜率 is None:
        胜率文本 = "胜率 -"
    else:
        # 战报服务的胜率已是百分数（0~100）。
        胜率文本 = f"胜率 {float(今日.胜率):.0f}%（{今日.胜场}胜{今日.负场}负）"
    行 = [
        f"场次 {今日.总场次}，{胜率文本}",
        f"收益 金{_格式数量(今日.总掠夺金币)} 水{_格式数量(今日.总掠夺圣水)} 油{_格式数量(今日.总掠夺黑油)}",
    ]

    try:
        今日日志 = [
            (float(日志.记录时间), str(日志.日志内容))
            for 日志 in 数据库.查询日志历史(机器人标志, 起始时间=零点, 截止时间=现在, 最大条数=20000)
        ]
    except Exception:
        今日日志 = []
    今日日志 += [(时间, 内容) for 时间, 内容 in 备份行 if 零点 <= 时间 < 明日零点]
    try:
        状态记录 = 数据库.获取最新完整状态(机器人标志).状态数据.get("部落竞赛检查记录")
    except Exception:
        状态记录 = None
    竞赛 = 汇总部落竞赛(今日日志, 状态记录 if isinstance(状态记录, dict) else None)
    竞赛片段 = []
    if 竞赛["已接任务"]:
        竞赛片段.append(f"今日接 {len(竞赛['已接任务'])} 项（{'、'.join(竞赛['已接任务'][:3])}）")
    if 竞赛["个人积分"] is not None:
        积分, 上限 = 竞赛["个人积分"]
        片段 = f"积分 {积分}/{上限}"
        if 竞赛["今日积分增加"]:
            片段 += f"（今日{竞赛['今日积分增加']:+d}）"
        竞赛片段.append(片段)
    if 竞赛片段:
        行.append("部落竞赛：" + "，".join(竞赛片段))
    if 竞赛["可领奖"]:
        行.append("部落竞赛可领奖，请手动领取（脚本不会自动领奖）")
    标题 = f"今日完成汇总 {time.strftime('%m-%d', time.localtime(现在))}"
    有内容 = bool(今日.总场次 or 竞赛片段 or 竞赛["可领奖"])
    return 标题, "\n".join(行), 有内容


def 到点(设置, 现在: float) -> bool:
    if 设置 is None or not bool(getattr(设置, "每日完成通知", True)):
        return False
    时间 = 规范化每日通知时间(getattr(设置, "每日通知时间", "23:30"))
    时, 分 = (int(片) for 片 in 时间.split(":"))
    本地 = datetime.fromtimestamp(现在)
    return (本地.hour, 本地.minute) >= (时, 分)


class 每日通知调度器:
    """由监控线程周期调用 ``检查``；到点且今天没发过才发送。"""

    检查间隔秒 = 30.0
    无内容重查秒 = 600.0

    def __init__(
        self,
        数据库,
        获取机器人列表: Callable[[], Iterable[str]],
        发送: Optional[Callable[..., bool]] = None,
        时钟: Callable[[], float] = time.time,
    ):
        self.数据库 = 数据库
        self._获取机器人列表 = 获取机器人列表
        self._发送 = 发送
        self._时钟 = 时钟
        self._上次检查 = 0.0
        self._暂缓至: dict[str, float] = {}

    def _默认发送(self, 设置, 标志: str, 标题: str, 正文: str) -> bool:
        from 工具包.桌面通知 import 机器人桌面通知

        return 机器人桌面通知(
            设置, 标志, "每日汇总", 标题, 正文,
            级别="信息", 需要恢复通知=False, 节流秒=0,
        )

    def 检查(self, 强制: bool = False) -> list[str]:
        """返回本次已发送通知的机器人列表；绝不抛异常。"""
        已发送 = []
        try:
            现在 = float(self._时钟())
            if not 强制 and 现在 - self._上次检查 < self.检查间隔秒:
                return []
            self._上次检查 = 现在
            今天 = time.strftime("%Y-%m-%d", time.localtime(现在))
            for 标志 in list(self._获取机器人列表() or []):
                try:
                    设置 = self.数据库.获取机器人设置(标志)
                    if not 到点(设置, 现在) or 现在 < self._暂缓至.get(标志, 0.0):
                        continue
                    键 = 已发送配置键前缀 + str(标志)
                    if self.数据库.读取系统配置(键) == 今天:
                        continue
                    标题, 正文, 有内容 = 生成每日摘要(self.数据库, 标志, 现在)
                    if not 有内容:
                        # 今天还没打过也没有竞赛进度：不弹空汇总，10 分钟后再看。
                        self._暂缓至[标志] = 现在 + self.无内容重查秒
                        continue
                    # 先记日期再发送：发送失败也不在同一天反复重试刷屏。
                    self.数据库.保存系统配置(键, 今天)
                    发送 = self._发送 or self._默认发送
                    if 发送(设置, 标志, 标题, 正文):
                        已发送.append(标志)
                except Exception:
                    continue
        except Exception:
            return 已发送
        return 已发送
