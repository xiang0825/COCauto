"""单实例：命名互斥体保证只有一个控制台，本地套接字用来唤醒已有窗口。

Windows 上 QLocalServer 允许同名重复监听，不能单独作为锁；互斥体由
系统在进程退出（包括崩溃）时自动释放，不会留下永久的“孤立锁”。
"""
from __future__ import annotations

import ctypes
import sys
import time

from PySide6.QtNetwork import QLocalServer, QLocalSocket

名称 = "COCAUTO_DESKTOP_CONSOLE"
_互斥体 = None


def _获取互斥体() -> bool:
    """返回 True 表示本进程是唯一实例。"""
    global _互斥体
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _互斥体 = kernel32.CreateMutexW(None, False, f"Local\\{名称}")
    if not _互斥体:
        return True
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def 唤醒已有实例(等待秒: float = 10.0) -> bool:
    """通知已有实例显示窗口。已有实例可能还在启动，最多等待几秒。"""
    截止 = time.monotonic() + 等待秒
    while time.monotonic() < 截止:
        套接字 = QLocalSocket()
        套接字.connectToServer(名称)
        if 套接字.waitForConnected(300):
            套接字.write(b"show")
            套接字.flush()
            套接字.waitForBytesWritten(300)
            套接字.disconnectFromServer()
            return True
        time.sleep(0.2)
    return False


class 单实例服务:
    def __init__(self, 唤醒回调):
        self._回调 = 唤醒回调
        self._服务 = QLocalServer()
        QLocalServer.removeServer(名称)
        self._服务.listen(名称)
        self._服务.newConnection.connect(self._新连接)

    def _新连接(self):
        while self._服务.hasPendingConnections():
            连接 = self._服务.nextPendingConnection()
            连接.readyRead.connect(连接.readAll)
            连接.disconnected.connect(连接.deleteLater)
            self._回调()

    def 关闭(self):
        self._服务.close()


def 抢占单实例() -> bool:
    """本进程获得单实例锁返回 True；否则尝试唤醒已有窗口并返回 False。"""
    if _获取互斥体():
        return True
    唤醒已有实例()
    return False
