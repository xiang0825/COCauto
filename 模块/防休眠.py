"""Windows 防系统自动休眠控制器（跨平台与单测安全）。"""

from __future__ import annotations

import ctypes
import sys
import threading
from typing import Any, Callable

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def _获取Windows执行状态API(平台名称: str | None = None) -> Callable[[int], Any] | None:
    当前平台 = sys.platform if 平台名称 is None else str(平台名称)
    if 当前平台 != "win32":
        return None
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None
    kernel32 = getattr(windll, "kernel32", None)
    if kernel32 is None:
        return None
    函数 = getattr(kernel32, "SetThreadExecutionState", None)
    return 函数 if callable(函数) else None


class 防休眠控制器:
    """封装 ``SetThreadExecutionState``，保证运行期间防系统休眠、暂停或退出时恢复。"""

    def __init__(
        self,
        执行状态函数: Callable[[int], Any] | None = None,
        *,
        平台名称: str | None = None,
        日志回调: Callable[[str], Any] | None = None,
    ) -> None:
        self._自定义执行函数 = 执行状态函数
        self._平台名称 = sys.platform if 平台名称 is None else str(平台名称)
        self._日志回调 = 日志回调
        self._锁 = threading.RLock()
        self._当前已阻止休眠 = False
        self._活跃线程集合: set[int] = set()
        self._调用记录: list[int] = []

    @property
    def 当前已阻止休眠(self) -> bool:
        with self._锁:
            return self._当前已阻止休眠

    @property
    def 平台支持(self) -> bool:
        return self._解析后端() is not None

    def _解析后端(self) -> Callable[[int], Any] | None:
        if self._自定义执行函数 is not None:
            return self._自定义执行函数
        return _获取Windows执行状态API(self._平台名称)

    def _记录日志(self, 消息: str) -> None:
        回调 = self._日志回调
        if callable(回调):
            try:
                回调(消息)
            except Exception:
                pass

    def _安全调用(self, 标志位: int) -> bool:
        后端 = self._解析后端()
        if 后端 is None:
            return False
        try:
            结果 = 后端(int(标志位))
            self._调用记录.append(int(标志位))
            # Windows SetThreadExecutionState 返回 0 (NULL) 表示失败；
            # 测试注入的模拟函数可能返回 True / None / 非零整数。
            if 结果 == 0 and 结果 is not False:
                return False
            if 结果 is False:
                return False
            return True
        except Exception as 异常:
            self._记录日志(f"设置系统防休眠状态失败（忽略并继续运行）：{异常}")
            return False

    def 保持唤醒(self) -> bool:
        """阻止系统自动进入休眠（允许显示器按电源计划自行息屏）。"""
        当前线程 = threading.get_ident()
        with self._锁:
            if self._当前已阻止休眠 and 当前线程 in self._活跃线程集合:
                return True
            成功 = self._安全调用(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            if 成功:
                self._当前已阻止休眠 = True
                self._活跃线程集合.add(当前线程)
            return 成功

    def 允许休眠(self) -> bool:
        """恢复系统默认休眠策略。"""
        当前线程 = threading.get_ident()
        with self._锁:
            if not self._当前已阻止休眠 and 当前线程 not in self._活跃线程集合:
                return True
            成功 = self._安全调用(ES_CONTINUOUS)
            self._当前已阻止休眠 = False
            self._活跃线程集合.discard(当前线程)
            return 成功

    def 同步运行状态(self, 运行中: bool) -> bool:
        """按运行/暂停状态同步防休眠状态，并确保当前工作线程状态一致。"""
        if 运行中:
            return self.保持唤醒()
        return self.允许休眠()

    def __enter__(self) -> "防休眠控制器":
        self.保持唤醒()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.允许休眠()
        return False
