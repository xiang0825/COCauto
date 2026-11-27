"""F1/F2 全局热键（Windows RegisterHotKey），与界面框架无关。

热键在独立线程中监听，按下时调用 ``回调(按键名)``——回调运行在热键
线程里，界面层需要自己切回主线程（Qt 用信号即可）。注册失败的按键
通过 ``注册失败回调(按键名)`` 通知界面退回窗口内快捷键。
"""
from __future__ import annotations

import ctypes
import sys
import threading
from typing import Callable


class 全局快捷键:
    按键表 = {1: ("F1", 0x70), 2: ("F2", 0x71)}
    _热键消息 = 0x0312  # WM_HOTKEY
    _退出消息 = 0x0012  # WM_QUIT
    _禁止重复 = 0x4000  # MOD_NOREPEAT

    def __init__(
        self,
        回调: Callable[[str], None],
        注册失败回调: Callable[[str], None] | None = None,
    ):
        self._回调 = 回调
        self._注册失败 = 注册失败回调 or (lambda _名称: None)
        self._停止 = threading.Event()
        self._线程ID: int | None = None
        self._线程: threading.Thread | None = None

    def 启动(self) -> None:
        if sys.platform != "win32":
            for 名称, _ in self.按键表.values():
                self._注册失败(名称)
            return
        self._线程 = threading.Thread(target=self._监听, name="运行快捷键", daemon=True)
        self._线程.start()

    def _监听(self) -> None:
        try:
            # 仅 Windows 线程内导入：Python 3.11 在 macOS 上 import wintypes 会抛 ValueError。
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
            user32.RegisterHotKey.restype = wintypes.BOOL
            user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
            user32.UnregisterHotKey.restype = wintypes.BOOL
            user32.GetMessageW.argtypes = (
                ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
            )
            user32.GetMessageW.restype = ctypes.c_int
            self._线程ID = kernel32.GetCurrentThreadId()
            已注册 = set()
            for 标识, (名称, 虚拟键) in self.按键表.items():
                if user32.RegisterHotKey(None, 标识, self._禁止重复, 虚拟键):
                    已注册.add(标识)
                else:
                    self._注册失败(名称)
            try:
                消息 = wintypes.MSG()
                while not self._停止.is_set():
                    if user32.GetMessageW(ctypes.byref(消息), None, 0, 0) <= 0:
                        break
                    if 消息.message == self._热键消息 and 消息.wParam in 已注册:
                        try:
                            self._回调(self.按键表[消息.wParam][0])
                        except Exception:
                            pass
            finally:
                for 标识 in 已注册:
                    user32.UnregisterHotKey(None, 标识)
        except Exception:
            for 名称, _ in self.按键表.values():
                self._注册失败(名称)

    def 关闭(self) -> None:
        if self._停止.is_set():
            return
        self._停止.set()
        if self._线程ID and sys.platform == "win32":
            try:
                ctypes.WinDLL("user32").PostThreadMessageW(self._线程ID, self._退出消息, 0, 0)
            except Exception:
                pass
