"""F1/F2 运行控制：Windows 全局热键，注册失败时退回窗口内按键。"""
import ctypes
from ctypes import wintypes
import queue
import sys
import threading
import tkinter as tk


class 运行快捷键:
    _按键 = {1: ("F1", 0x70), 2: ("F2", 0x71)}
    _热键消息 = 0x0312  # WM_HOTKEY
    _退出消息 = 0x0012  # WM_QUIT
    _禁止重复 = 0x4000  # MOD_NOREPEAT

    def __init__(self, 窗口: tk.Misc, 处理按键):
        self.窗口 = 窗口
        self.处理按键 = 处理按键
        self._消息 = queue.Queue()
        self._停止 = threading.Event()
        self._线程ID = None
        self._已绑定窗口按键 = set()
        if sys.platform == "win32":
            self._线程 = threading.Thread(
                target=self._监听全局按键, name="运行快捷键", daemon=True
            )
            self._线程.start()
        else:
            for 按键, _ in self._按键.values():
                self._绑定窗口按键(按键)
        self.窗口.after(100, self._处理消息)

    def _绑定窗口按键(self, 按键):
        if 按键 in self._已绑定窗口按键:
            return
        self._已绑定窗口按键.add(按键)
        self.窗口.bind_all(
            f"<{按键}>",
            lambda _事件, 名称=按键: self.处理按键(名称),
            add="+",
        )

    def _监听全局按键(self):
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            user32.RegisterHotKey.argtypes = (
                wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
            )
            user32.RegisterHotKey.restype = wintypes.BOOL
            user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
            user32.UnregisterHotKey.restype = wintypes.BOOL
            user32.GetMessageW.argtypes = (
                ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                wintypes.UINT, wintypes.UINT,
            )
            user32.GetMessageW.restype = ctypes.c_int
            self._线程ID = kernel32.GetCurrentThreadId()
            已注册 = set()
            for 标识, (名称, 虚拟键) in self._按键.items():
                if user32.RegisterHotKey(None, 标识, self._禁止重复, 虚拟键):
                    已注册.add(标识)
                else:
                    self._消息.put(("退回窗口", 名称))
            try:
                消息 = wintypes.MSG()
                while not self._停止.is_set():
                    结果 = user32.GetMessageW(ctypes.byref(消息), None, 0, 0)
                    if 结果 <= 0:
                        break
                    if 消息.message == self._热键消息 and 消息.wParam in 已注册:
                        self._消息.put(("按键", self._按键[消息.wParam][0]))
            finally:
                for 标识 in 已注册:
                    user32.UnregisterHotKey(None, 标识)
        except Exception:
            for 名称, _ in self._按键.values():
                self._消息.put(("退回窗口", 名称))

    def _处理消息(self):
        if self._停止.is_set():
            return
        try:
            while True:
                类型, 名称 = self._消息.get_nowait()
                if 类型 == "按键":
                    self.处理按键(名称)
                elif 类型 == "退回窗口":
                    self._绑定窗口按键(名称)
        except queue.Empty:
            pass
        try:
            self.窗口.after(100, self._处理消息)
        except tk.TclError:
            pass

    def 关闭(self):
        if self._停止.is_set():
            return
        self._停止.set()
        if self._线程ID and sys.platform == "win32":
            try:
                ctypes.WinDLL("user32").PostThreadMessageW(
                    self._线程ID, self._退出消息, 0, 0
                )
            except Exception:
                pass
        for 名称 in self._已绑定窗口按键:
            try:
                self.窗口.unbind_all(f"<{名称}>")
            except tk.TclError:
                pass
