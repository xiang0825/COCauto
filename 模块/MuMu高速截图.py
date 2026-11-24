"""MuMu 模拟器自带的 external_renderer_ipc 高速截图。

MuMu 安装目录里带有 ``external_renderer_ipc.dll``（MAA 的“MuMu 截图增强
模式”用的也是它），可以直接从模拟器渲染器读取指定显示层的画面，不经过
adb，也不创建子进程。1280×720 实测每张约 7ms，对比 adb 原始截图约 270ms。

本模块只负责“读画面”，从不发送输入。任何一步不确定（找不到 DLL、实例
对不上、CoC 不在任何显示层、调用失败）都返回 None，由调用方退回 adb 截图，
因此最坏情况只是回到原来的速度。
"""
from __future__ import annotations

import ctypes
import os
import re
import threading
from pathlib import Path

import numpy as np

# MuMu 的 adb 端口约定：127.0.0.1:(16384 + 32×实例号)，或 emulator-(5554 + 2×实例号)。
_MuMu基础端口 = 16384
_MuMu端口步长 = 32
_模拟器基础端口 = 5554


def 解析MuMu实例号(设备序列号: str) -> int | None:
    """按 MuMu 的端口约定把 adb 序列号换算成实例号；不符合约定返回 None。"""
    序列号 = str(设备序列号 or "").strip().lower()
    匹配 = re.fullmatch(r"(?:127\.0\.0\.1|localhost):(\d+)", 序列号)
    if 匹配:
        偏移 = int(匹配.group(1)) - _MuMu基础端口
        if 0 <= 偏移 < 32 * _MuMu端口步长 and 偏移 % _MuMu端口步长 == 0:
            return 偏移 // _MuMu端口步长
        return None
    匹配 = re.fullmatch(r"emulator-(\d+)", 序列号)
    if 匹配:
        偏移 = int(匹配.group(1)) - _模拟器基础端口
        if 0 <= 偏移 < 64 and 偏移 % 2 == 0:
            return 偏移 // 2
    return None


def 查找MuMu截图库(adb路径: str = "") -> tuple[Path, Path] | None:
    """返回 (MuMu 安装根目录, external_renderer_ipc.dll)，找不到返回 None。"""
    候选根目录: list[Path] = []
    if adb路径:
        adb所在目录 = Path(adb路径).resolve().parent
        # MuMu 5.x：<根>/nx_main/adb.exe；MuMu 12：<根>/shell/adb.exe
        if adb所在目录.name.lower() in {"nx_main", "shell"}:
            候选根目录.append(adb所在目录.parent)
    for 环境变量, 默认值 in (("ProgramFiles", r"C:\Program Files"),
                         ("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        基础 = Path(os.environ.get(环境变量, 默认值)) / "Netease"
        候选根目录 += [基础 / "MuMuPlayer", 基础 / "MuMuPlayer-12.0"]
    for 根目录 in 候选根目录:
        for 相对路径 in (("nx_main", "sdk"), ("shell", "sdk")):
            库 = 根目录.joinpath(*相对路径, "external_renderer_ipc.dll")
            if 库.is_file():
                return 根目录, 库
    return None


class MuMu高速截图:
    """线程安全地持有一个 MuMu IPC 连接，并复用截图缓冲区。"""

    最大连续失败次数 = 3

    def __init__(self, 根目录: Path, 库路径: Path, 实例号: int, 目标包名: str):
        self.根目录 = Path(根目录)
        self.库路径 = Path(库路径)
        self.实例号 = int(实例号)
        self.目标包名 = str(目标包名 or "")
        self._锁 = threading.Lock()
        self._库 = None
        self._句柄 = 0
        self._缓冲区 = None
        self._连续失败次数 = 0
        self.已停用 = False

    def _加载库(self):
        if self._库 is not None:
            return self._库
        库 = ctypes.CDLL(str(self.库路径))
        库.nemu_connect.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
        库.nemu_connect.restype = ctypes.c_int
        库.nemu_disconnect.argtypes = [ctypes.c_int]
        库.nemu_disconnect.restype = None
        库.nemu_get_display_id.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        库.nemu_get_display_id.restype = ctypes.c_int
        库.nemu_capture_display.argtypes = [
            ctypes.c_int, ctypes.c_uint, ctypes.c_int,
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.c_void_p,
        ]
        库.nemu_capture_display.restype = ctypes.c_int
        self._库 = 库
        return 库

    def _断开(self) -> None:
        if self._句柄 and self._库 is not None:
            try:
                self._库.nemu_disconnect(self._句柄)
            except OSError:
                pass
        self._句柄 = 0

    def _记录失败(self) -> None:
        self._断开()
        self._连续失败次数 += 1
        if self._连续失败次数 >= self.最大连续失败次数:
            self.已停用 = True

    def 截图(self):
        """返回 CoC 所在显示层的 BGR 画面；任何不确定情况返回 None。"""
        if self.已停用 or not self.目标包名:
            return None
        with self._锁:
            try:
                库 = self._加载库()
                if not self._句柄:
                    self._句柄 = 库.nemu_connect(str(self.根目录), self.实例号)
                    if not self._句柄:
                        self._记录失败()
                        return None
                # 每次都按包名重新确认 CoC 所在显示层：CoC 不在前台或
                # 正在重启时返回负数，此时交给 adb 流程按原规则 fail-closed。
                显示ID = 库.nemu_get_display_id(self._句柄, self.目标包名.encode("utf-8"), 0)
                if 显示ID < 0:
                    return None
                宽, 高 = ctypes.c_int(), ctypes.c_int()
                if 库.nemu_capture_display(self._句柄, 显示ID, 0, ctypes.byref(宽), ctypes.byref(高), None) != 0:
                    self._记录失败()
                    return None
                if not (1 <= 宽.value <= 8192 and 1 <= 高.value <= 8192):
                    self._记录失败()
                    return None
                字节数 = 宽.value * 高.value * 4
                if self._缓冲区 is None or len(self._缓冲区) != 字节数:
                    self._缓冲区 = (ctypes.c_ubyte * 字节数)()
                if 库.nemu_capture_display(
                    self._句柄, 显示ID, 字节数, ctypes.byref(宽), ctypes.byref(高),
                    ctypes.byref(self._缓冲区),
                ) != 0:
                    self._记录失败()
                    return None
                import cv2
                像素 = np.frombuffer(self._缓冲区, dtype=np.uint8).reshape(高.value, 宽.value, 4)
                # 渲染器缓冲区是自下而上存放的，需要上下翻转。
                图像 = cv2.cvtColor(像素[::-1], cv2.COLOR_RGBA2BGR)
                self._连续失败次数 = 0
                return 图像
            except (OSError, AttributeError, ValueError):
                self._记录失败()
                return None

    def 关闭(self) -> None:
        with self._锁:
            self._断开()
            self.已停用 = True
