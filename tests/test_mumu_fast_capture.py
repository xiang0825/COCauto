import ctypes
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from 模块.ADB设备操作类 import ADB设备操作类
from 模块.MuMu高速截图 import MuMu高速截图, 解析MuMu实例号

ADB = sys.executable
在线模拟器 = b"List of devices attached\nemulator-5554 device product:LDPlayer model:LDPlayer\n"


class 假Runner:
    def __init__(self, *响应):
        self.响应 = list(响应)
        self.命令 = []

    def __call__(self, 命令, **参数):
        self.命令.append(命令)
        if self.响应:
            return self.响应.pop(0)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


def 结果(输出=b""):
    return SimpleNamespace(returncode=0, stdout=输出, stderr=b"")


class 假IPC库:
    """模拟 external_renderer_ipc.dll：画面按渲染器的自下而上 RGBA 存放。"""

    def __init__(self, 画面BGR, 显示ID=2, 连接句柄=7):
        self.画面 = 画面BGR
        self.显示ID = 显示ID
        self.连接句柄 = 连接句柄
        self.连接参数 = []
        self.查询包名 = []
        self.断开次数 = 0
        self.截图失败 = False

    def nemu_connect(self, 根目录, 实例号):
        self.连接参数.append((根目录, 实例号))
        return self.连接句柄

    def nemu_disconnect(self, 句柄):
        self.断开次数 += 1

    def nemu_get_display_id(self, 句柄, 包名, 序号):
        self.查询包名.append(包名)
        return self.显示ID

    def nemu_capture_display(self, 句柄, 显示ID, 大小, 宽引用, 高引用, 缓冲引用):
        if self.截图失败:
            return -1
        高, 宽 = self.画面.shape[:2]
        宽引用._obj.value, 高引用._obj.value = 宽, 高
        if 大小:
            数据 = cv2.cvtColor(self.画面, cv2.COLOR_BGR2RGBA)[::-1].tobytes()
            ctypes.memmove(缓冲引用._obj, 数据, len(数据))
        return 0


def 测试画面():
    画面 = np.zeros((72, 128, 3), dtype=np.uint8)
    画面[:10, :, :] = (10, 20, 200)  # 顶部一条红色，用来确认没有上下颠倒
    画面[:, 100:, 0] = 250
    return 画面


def 建截图器(库, 包名="com.supercell.clashofclans"):
    截图器 = MuMu高速截图(r"C:\MuMu", r"C:\MuMu\x.dll", 1, 包名)
    截图器._库 = 库
    return 截图器


class MuMu实例号测试(unittest.TestCase):
    def test_按MuMu端口约定换算实例号(self):
        self.assertEqual(解析MuMu实例号("127.0.0.1:16384"), 0)
        self.assertEqual(解析MuMu实例号("127.0.0.1:16416"), 1)
        self.assertEqual(解析MuMu实例号("emulator-5554"), 0)
        self.assertEqual(解析MuMu实例号("emulator-5556"), 1)

    def test_不符合约定的序列号不使用高速截图(self):
        for 序列号 in ("127.0.0.1:16385", "127.0.0.1:5555", "emulator-5555", "R58N123", ""):
            with self.subTest(序列号=序列号):
                self.assertIsNone(解析MuMu实例号(序列号))


class MuMu高速截图测试(unittest.TestCase):
    def test_返回方向和颜色正确的BGR画面并复用连接(self):
        库 = 假IPC库(测试画面())
        截图器 = 建截图器(库)
        for _ in range(2):
            图像 = 截图器.截图()
            self.assertTrue(np.array_equal(图像, 测试画面()))
        self.assertEqual(库.连接参数, [(r"C:\MuMu", 1)])
        self.assertEqual(库.查询包名, [b"com.supercell.clashofclans"] * 2)

    def test_CoC不在任何显示层时返回None且不算失败(self):
        库 = 假IPC库(测试画面(), 显示ID=-1)
        截图器 = 建截图器(库)
        for _ in range(5):
            self.assertIsNone(截图器.截图())
        self.assertFalse(截图器.已停用)

    def test_连续失败三次后停用(self):
        库 = 假IPC库(测试画面())
        库.截图失败 = True
        截图器 = 建截图器(库)
        for _ in range(3):
            self.assertIsNone(截图器.截图())
        self.assertTrue(截图器.已停用)
        self.assertEqual(len(库.连接参数), 3)  # 每次失败都断开重连

    def test_连接失败返回None(self):
        库 = 假IPC库(测试画面(), 连接句柄=0)
        self.assertIsNone(建截图器(库).截图())

    def test_没有目标包名时不截图(self):
        库 = 假IPC库(测试画面())
        self.assertIsNone(建截图器(库, 包名="").截图())
        self.assertEqual(库.连接参数, [])


class 设备高速截图接入测试(unittest.TestCase):
    def setUp(self):
        ADB设备操作类._全局最近ADB服务重置时间 = 0.0

    def _内存充足(self):
        return patch.object(ADB设备操作类, "_获取主机内存状态", return_value={
            "内存负载": 50,
            "可用物理内存": 8 * 1024 * 1024 * 1024,
            "可用提交额度": 8 * 1024 * 1024 * 1024,
        })

    def _PNG(self, 画面):
        return cv2.imencode(".png", 画面)[1].tobytes()

    def test_假runner永远不启用高速截图(self):
        设备 = ADB设备操作类(ADB, "emulator-5556", runner=假Runner())
        设备._目标包名 = "com.supercell.clashofclans"
        self.assertIsNone(设备._获取高速截图器())

    def test_核对通过前走adb_核对后直接用高速截图(self):
        画面 = 测试画面()
        截图器 = 建截图器(假IPC库(画面))
        runner = 假Runner(结果(在线模拟器), 结果(self._PNG(画面)))
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with self._内存充足(), patch.object(设备, "_获取高速截图器", return_value=截图器):
            第一张 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertTrue(设备._高速截图已核对)
            adb命令数 = len(runner.命令)
            第二张 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
        self.assertTrue(np.array_equal(第一张, 画面))
        self.assertTrue(np.array_equal(第二张, 画面))
        self.assertFalse(any("screencap" in 命令 for 命令 in runner.命令[adb命令数:]))

    def test_画面对不上时不启用_连续三次后停用(self):
        截图器 = 建截图器(假IPC库(np.full((72, 128, 3), 255, dtype=np.uint8)))
        adb画面 = 测试画面()
        响应 = [结果(在线模拟器)] + [结果(self._PNG(adb画面)) for _ in range(3)]
        runner = 假Runner(*响应)
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with self._内存充足(), patch.object(设备, "_获取高速截图器", return_value=截图器):
            for _ in range(3):
                图像 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
                self.assertTrue(np.array_equal(图像, adb画面))
        self.assertFalse(设备._高速截图已核对)
        self.assertTrue(截图器.已停用)

    def test_高速截图拿不到画面时照常走adb(self):
        画面 = 测试画面()
        库 = 假IPC库(画面)
        截图器 = 建截图器(库)
        runner = 假Runner(结果(在线模拟器), 结果(self._PNG(画面)))
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        设备._高速截图已核对 = True
        库.显示ID = -1  # CoC 不在任何显示层
        with self._内存充足(), patch.object(设备, "_获取高速截图器", return_value=截图器):
            图像 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
        self.assertTrue(np.array_equal(图像, 画面))
        self.assertTrue(any("screencap" in 命令 for 命令 in runner.命令))


if __name__ == "__main__":
    unittest.main()
