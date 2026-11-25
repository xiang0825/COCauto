"""游戏控制服务：界面和快捷键共用的启停入口。

控制台只控制一个游戏（一个模拟器里的一个 CoC），类似 MAA 的单实例
模式：一份连接设置、一份任务计划、一组开始/暂停/停止按钮。

引擎内部仍用一个“机器人标志”区分数据库里的设置和日志。旧版本可能
存了多份机器人配置，这里按“最近一次有运行日志的那份”自动选用，其余
配置原样保留在数据库里，不会被删除。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from 数据库.任务数据库 import 任务数据库, 机器人设置
from 应用.任务计划 import 已启用任务名称

状态运行中 = "运行中"
状态暂停中 = "暂停中"
状态已停止 = "已停止"

默认实例ID = "robot_1"


def 选择主实例ID(数据库) -> str:
    """从已有配置中选出要控制的那一份；没有配置时返回默认 ID。

    规则固定、与界面无关，命令行入口和自动启动脚本也用同一规则：
    1. 有运行日志的配置里，选最后一条日志最新的；
    2. 否则优先 ``robot_1``；
    3. 否则按名称排序取第一份。
    """
    try:
        所有配置 = list(数据库.查询所有机器人设置())
    except Exception:
        所有配置 = []
    if not 所有配置:
        return 默认实例ID
    最新: tuple[float, str] | None = None
    for 标志 in 所有配置:
        try:
            日志 = 数据库.读取最后日志(标志)
        except Exception:
            日志 = None
        if 日志 is not None:
            时间 = float(getattr(日志, "记录时间", 0) or 0)
            if 最新 is None or 时间 > 最新[0]:
                最新 = (时间, 标志)
    if 最新 is not None:
        return 最新[1]
    if 默认实例ID in 所有配置:
        return 默认实例ID
    return sorted(所有配置)[0]


@dataclass(frozen=True)
class 运行快照:
    """界面一次刷新所需的只读状态，避免界面直接访问线程对象。"""

    状态: str
    停止原因: str
    设备序列号: str
    设备已确认: bool
    已选任务: tuple[str, ...]
    最近日志: str
    最近日志时间: float | None = None

    @property
    def 设备描述(self) -> str:
        if self.设备序列号 and self.设备已确认:
            return f"已确认 · {self.设备序列号}"
        if self.设备序列号:
            return f"未确认 · {self.设备序列号}"
        return "未配置"


class 应用控制器:
    """包装 ``机器人监控中心``，只暴露一个游戏实例。所有方法可在界面线程调用。"""

    def __init__(self, 监控中心, 数据库: 任务数据库 | None = None):
        self.监控中心 = 监控中心
        self.数据库 = 数据库 or getattr(监控中心, "数据库", None) or 任务数据库()
        self.实例ID = 默认实例ID
        self._设置缓存: tuple[float, 机器人设置] | None = None

    # ---------------------------------------------------------- 初始化
    def 准备(self) -> str:
        """选定要控制的配置并创建引擎实例，返回实例 ID。"""
        self.实例ID = 选择主实例ID(self.数据库)
        if not self.数据库.查询所有机器人设置():
            self.数据库.保存机器人设置(self.实例ID, 机器人设置())
        if self.实例ID not in self.监控中心.机器人池:
            self.监控中心.创建机器人(
                机器人标志=self.实例ID,
                初始设置=self.数据库.获取机器人设置(self.实例ID),
            )
        return self.实例ID

    @property
    def _实例(self):
        return self.监控中心.机器人池.get(self.实例ID)

    # ---------------------------------------------------------- 设置
    def 获取设置(self) -> 机器人设置:
        return self.数据库.获取机器人设置(self.实例ID)

    def 保存设置(self, 设置: 机器人设置) -> None:
        post = getattr(设置, "__post_init__", None)
        if callable(post):
            post()
        self.数据库.保存机器人设置(self.实例ID, 设置)
        self._设置缓存 = None

    def 设置已变更(self) -> None:
        """其它服务直接写了数据库（例如连接页保存设备）后调用，刷新快照。"""
        self._设置缓存 = None

    def _缓存设置(self, 最长秒: float = 3.0) -> 机器人设置:
        现在 = time.monotonic()
        if self._设置缓存 and 现在 - self._设置缓存[0] < 最长秒:
            return self._设置缓存[1]
        设置 = self.数据库.获取机器人设置(self.实例ID)
        self._设置缓存 = (现在, 设置)
        return 设置

    # ---------------------------------------------------------- 运行控制
    @property
    def 状态(self) -> str:
        实例 = self._实例
        return str(getattr(实例, "当前状态", 状态已停止)) if 实例 else 状态已停止

    def 启动(self) -> None:
        if self._实例 is None:
            raise RuntimeError("控制台尚未初始化完成")
        self.监控中心.启动机器人(self.实例ID)

    def 暂停(self) -> None:
        if self._实例 is not None:
            self._实例.暂停()

    def 继续(self) -> None:
        实例 = self._实例
        if 实例 is None:
            return
        if self.状态 == 状态已停止:
            # 已退出的线程不能“继续”，必须重新走启动护栏。
            self.启动()
            return
        实例.继续()

    def 停止(self, 原因: str = "界面停止按钮") -> threading.Thread | None:
        """在后台线程中停止并等待任务线程退出，界面不会卡住。"""
        实例 = self._实例
        if 实例 is None:
            return None
        线程 = threading.Thread(
            target=实例.停止, args=(原因,), name="停止任务", daemon=True,
        )
        线程.start()
        return 线程

    def 开始或继续(self) -> bool:
        """F1：只启动已停止的任务，或恢复已暂停的任务。"""
        if self._实例 is None:
            return False
        if self.状态 == 状态暂停中:
            self.继续()
            return True
        if self.状态 == 状态已停止:
            self.启动()
            return True
        return False

    def 仅暂停(self) -> bool:
        """F2：只暂停正在运行的任务，不会误启动。"""
        if self.状态 != 状态运行中:
            return False
        self.暂停()
        return True

    # ---------------------------------------------------------- 快照
    def 快照(self) -> 运行快照:
        实例 = self._实例
        try:
            设置 = self._缓存设置()
        except Exception:
            设置 = 机器人设置()
        try:
            日志 = self.数据库.读取最后日志(self.实例ID)
        except Exception:
            日志 = None
        return 运行快照(
            状态=self.状态,
            停止原因=str(getattr(实例, "停止原因", "") or ""),
            设备序列号=str(getattr(设置, "ADB设备序列号", "") or "").strip(),
            设备已确认=bool(getattr(设置, "ADB已确认模拟器", False)),
            已选任务=tuple(已启用任务名称(设置)),
            最近日志=(str(日志.日志内容)[:200] if 日志 else ""),
            最近日志时间=(float(日志.记录时间) if 日志 else None),
        )

    def 关闭(self) -> None:
        try:
            self.监控中心.关闭()
        except Exception:
            self.监控中心.运行标志 = False
