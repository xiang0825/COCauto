import ctypes
import os
import sys
import threading
import time

import cv2
import numpy as np
import win32com.client
import win32gui
from PIL import ImageGrab

from 核心.核心异常们 import 图像获取失败


打包环境 = getattr(sys, "frozen", False)
if 打包环境:
    当前文件所在目录 = sys._MEIPASS
else:
    当前文件所在目录 = os.path.dirname(__file__)

项目目录 = os.path.dirname(当前文件所在目录)
op目录 = os.path.join(当前文件所在目录 if 打包环境 else 项目目录, "op_runtime")
原始op目录 = os.path.join(当前文件所在目录, "op-0.4.5_with_model")

# COM 组件内部仍使用窄字符路径，中文目录会导致 LoadLibraryA 失败。
# 建立一个 ASCII 路径别名，让 DLL 和 OCR 模型都从该别名加载。
if not 打包环境 and not os.path.isdir(op目录) and os.path.isdir(原始op目录):
    try:
        os.symlink(原始op目录, op目录, target_is_directory=True)
    except OSError:
        pass

if not os.path.isdir(op目录):
    raise RuntimeError(f"找不到 OP 运行目录：{原始op目录}")

_op_dll路径 = os.path.join(op目录, "op_x64.dll")
_免注册dll路径 = os.path.join(op目录, "tools.dll")
if not os.path.isfile(_op_dll路径) or not os.path.isfile(_免注册dll路径):
    raise RuntimeError(f"OP 运行文件不完整：{op目录}")

_免注册dll = ctypes.WinDLL(_免注册dll路径)
_免注册dll.setupW.argtypes = [ctypes.c_wchar_p]
_免注册dll.setupW.restype = ctypes.c_int
_免注册状态 = _免注册dll.setupW(_op_dll路径)
if _免注册状态 != 1:
    raise RuntimeError(f"OP 组件初始化失败，错误码：{_免注册状态}")


class COM对象管理器:
    """确保每个使用 OP 的工作线程都初始化了 COM。"""

    线程数据 = threading.local()

    @classmethod
    def 初始化COM(cls):
        if not getattr(cls.线程数据, "已初始化", False):
            import pythoncom

            pythoncom.CoInitialize()
            cls.线程数据.已初始化 = True

    @classmethod
    def 释放COM(cls):
        if getattr(cls.线程数据, "已初始化", False):
            import pythoncom

            pythoncom.CoUninitialize()
            cls.线程数据.已初始化 = False


class op类:
    def __init__(self, 窗口句柄=None, 图像获取模式="opengl"):
        COM对象管理器.初始化COM()
        self.是否已绑定 = False
        self.窗口句柄 = None
        self._绑定参数 = None
        self.op_COM对象 = win32com.client.Dispatch("op.opsoft")
        self.op_COM对象.SetShowErrorMsg(3)

        if 窗口句柄:
            self.绑定(窗口句柄, 图像获取模式)

    def 绑定(
        self,
        窗口句柄,
        图像获取模式="opengl",
        鼠标模式="normal",
        键盘模式="normal",
        模式=0,
    ):
        if not win32gui.IsWindow(窗口句柄):
            raise RuntimeError(f"无效的模拟器窗口句柄：{窗口句柄}")

        参数 = (窗口句柄, 图像获取模式, 鼠标模式, 键盘模式, 模式)
        绑定结果 = self.op_COM对象.BindWindow(*参数)
        if 绑定结果 != 1:
            raise RuntimeError(
                f"窗口绑定失败，错误码：{绑定结果}；请确认雷电实例已启动且分辨率为 800×600。"
            )

        self.窗口句柄 = 窗口句柄
        self._绑定参数 = 参数
        self.是否已绑定 = True
        print("窗口绑定成功")
        return 绑定结果

    def _解绑(self):
        if self.是否已绑定:
            解绑结果 = self.op_COM对象.UnBindWindow()
            if 解绑结果 != 1:
                raise RuntimeError(f"解绑失败，错误码：{解绑结果}")
            self.是否已绑定 = False

    def 安全清理(self):
        self._解绑()
        if getattr(self, "op_COM对象", None) is not None:
            self.op_COM对象 = None
            import gc

            gc.collect()
        COM对象管理器.释放COM()

    def __del__(self):
        try:
            self.安全清理()
        except Exception:
            pass

    def 获取屏幕图像cv(self, 左边=0, 顶边=0, 右边=2000, 底边=2000):
        """截取模拟器可见客户区，返回 OpenCV BGR 图像。"""
        for 尝试次数 in range(1, 4):
            try:
                if self.是否已绑定 and self.窗口句柄:
                    if not win32gui.IsWindow(self.窗口句柄):
                        raise RuntimeError(f"模拟器窗口句柄已失效：{self.窗口句柄}")
                    if win32gui.IsIconic(self.窗口句柄):
                        raise RuntimeError("雷电模拟器已最小化，请先还原模拟器窗口。")

                    _, _, 客户区右边, 客户区底边 = win32gui.GetClientRect(self.窗口句柄)
                    左边 = max(0, 左边)
                    顶边 = max(0, 顶边)
                    右边 = min(右边, 客户区右边)
                    底边 = min(底边, 客户区底边)
                    if 右边 <= 左边 or 底边 <= 顶边:
                        raise ValueError(
                            f"截图区域超出模拟器客户区：{左边},{顶边},{右边},{底边}"
                        )
                    屏幕原点 = win32gui.ClientToScreen(self.窗口句柄, (0, 0))
                    屏幕左边 = 屏幕原点[0] + 左边
                    屏幕顶边 = 屏幕原点[1] + 顶边
                else:
                    屏幕左边, 屏幕顶边 = 左边, 顶边

                图像 = ImageGrab.grab(
                    bbox=(屏幕左边, 屏幕顶边, 屏幕左边 + 右边 - 左边, 屏幕顶边 + 底边 - 顶边),
                    all_screens=True,
                )
                cv图像 = cv2.cvtColor(np.asarray(图像), cv2.COLOR_RGB2BGR)
                if cv2.mean(cv2.cvtColor(cv图像, cv2.COLOR_BGR2GRAY))[0] > 5:
                    return cv图像
            except Exception as 异常:
                if 尝试次数 == 3:
                    raise 图像获取失败(f"截图失败：{异常}") from 异常

            if 尝试次数 < 3:
                time.sleep(0.05)

        raise 图像获取失败("连续 3 次获取到黑屏图像")

    def __getattr__(self, 属性名):
        引擎 = self.__dict__.get("op_COM对象")
        if 引擎 is None:
            raise AttributeError(属性名)
        return getattr(引擎, 属性名)
