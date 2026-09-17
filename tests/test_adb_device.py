import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from 模块.ADB设备操作类 import (
    ADB设备信息,
    ADB设备操作类,
    ADB错误,
    解析ADB设备列表,
)
from 核心.鼠标操作 import 鼠标控制器
from 核心.键盘操作 import 键盘控制器
from 核心.ADB屏幕 import ADB屏幕
from 数据库.任务数据库 import 任务数据库
from 任务流程.建筑升级.升级普通建筑 import 升级普通建筑任务


ADB = sys.executable


class 假Runner:
    def __init__(self, *响应):
        self.响应 = list(响应)
        self.命令 = []

    def __call__(self, 命令, **_参数):
        self.命令.append(命令)
        if self.响应:
            return self.响应.pop(0)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


def 结果(输出=b"", code=0, 错误=b""):
    return SimpleNamespace(returncode=code, stdout=输出, stderr=错误)


在线模拟器 = b"List of devices attached\nemulator-5554 device product:LDPlayer model:LDPlayer\n"


class ADB设备测试(unittest.TestCase):
    def test_单文件模式数据库放在EXE旁而非临时解包目录(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            exe路径 = str(Path(临时目录) / "app.exe")
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", exe路径):
                数据库路径 = 任务数据库.默认数据库路径()
            self.assertEqual(Path(数据库路径), Path(临时目录) / "数据库" / "任务系统.db")

    def test_解析列表并保留状态与描述(self):
        设备 = 解析ADB设备列表(
            "List of devices attached\n127.0.0.1:16384 device product:MuMu model:MuMuPlayer\n"
            "emulator-5556 unauthorized usb:1-2\n"
        )
        self.assertEqual([项.序列号 for 项 in 设备], ["127.0.0.1:16384", "emulator-5556"])
        self.assertEqual(设备[1].状态, "unauthorized")
        self.assertIn("MuMu", 设备[0].描述)

    def test_空序列号不能构造设备命令(self):
        with self.assertRaises(ADB错误):
            ADB设备操作类.构造设备命令(ADB, "", ["shell", "input", "tap", "1", "2"])

    def test_屏幕尺寸解析优先使用覆盖尺寸(self):
        self.assertEqual(ADB设备操作类.解析屏幕尺寸("Physical size: 1280x720\nOverride size: 800x600"), (800, 600))
        self.assertIsNone(ADB设备操作类.解析屏幕尺寸("unknown"))

    def test_自动检测ADB路径并支持关闭自动检测(self):
        with patch.object(ADB设备操作类, "_候选ADB路径", return_value=[Path(sys.executable)]), \
                patch("模块.ADB设备操作类.shutil.which", return_value=None):
            self.assertEqual(
                ADB设备操作类.解析ADB路径("", 自动检测=True),
                str(Path(sys.executable).resolve()),
            )
        with self.assertRaisesRegex(ADB错误, "未启用 ADB 自动检测"):
            ADB设备操作类.解析ADB路径("", 自动检测=False)

    def test_实体Samsung设备即使确认也会被阻止(self):
        runner = 假Runner(结果(b"List of devices attached\n127.0.0.1:16416 device model:SM_A5560 product:a55xchn\n"))
        设备 = ADB设备操作类(ADB, "127.0.0.1:16416", runner=runner)
        with self.assertRaisesRegex(ADB错误, "实体 Android 设备"):
            设备.获取屏幕图像cv()
        self.assertEqual(len(runner.命令), 1)
        self.assertEqual(runner.命令[0][1:], ["devices", "-l"])

    def test_设备授权状态异常时不发送输入(self):
        runner = 假Runner(结果(b"List of devices attached\nemulator-5554 unauthorized model:LDPlayer\n"))
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with self.assertRaisesRegex(ADB错误, "unauthorized"):
            设备.触控(22, 33)
        self.assertEqual(len(runner.命令), 1)

    def test_触控命令固定绑定选中序列号(self):
        runner = 假Runner(结果(在线模拟器), 结果(b"Physical size: 800x600"), 结果())
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        self.assertTrue(设备.触控(12, 34))
        self.assertEqual(runner.命令[-1][1:], ["-s", "emulator-5554", "shell", "input", "tap", "12", "34"])

    def test_ADB传输断线会重连后重试(self):
        runner = 假Runner(
            结果(在线模拟器),
            结果(b"Physical size: 800x600"),
            结果(code=1, 错误=b"error: protocol fault (couldn't read status): connection reset"),
            结果(),
            结果(),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        self.assertTrue(设备.触控(12, 34))
        self.assertEqual(runner.命令[-2][1:], ["reconnect", "offline"])
        self.assertEqual(
            runner.命令[-1][1:],
            ["-s", "emulator-5554", "shell", "input", "tap", "12", "34"],
        )

    def test_ADB连续截图超时会熔断而不是无限创建进程(self):
        class 超时Runner:
            def __init__(self):
                self.命令 = []

            def __call__(self, 命令, **_参数):
                self.命令.append(命令)
                if 命令[1:] == ["reconnect", "offline"]:
                    return 结果()
                raise subprocess.TimeoutExpired(命令, 1)

        runner = 超时Runner()
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with self.assertRaisesRegex(ADB错误, "命令超时"):
            设备.执行(["exec-out", "screencap", "-p"], timeout=1, binary=True)

        已调用次数 = len(runner.命令)
        with self.assertRaisesRegex(ADB错误, "安全冷却"):
            设备.执行(["exec-out", "screencap", "-p"], timeout=1, binary=True)
        self.assertEqual(len(runner.命令), 已调用次数)

    def test_实际分辨率自动映射参考坐标(self):
        runner = 假Runner(
            结果(在线模拟器),
            结果(b"Physical size: 1280x720"),
            结果(),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        self.assertTrue(设备.触控(12, 34))
        self.assertEqual(
            runner.命令[-1][1:],
            ["-s", "emulator-5554", "shell", "input", "tap", "19", "41"],
        )

    def test_ADB连续触控复用一次shell会话(self):
        runner = 假Runner(结果(在线模拟器), 结果(b"Physical size: 800x600"), 结果())
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        self.assertTrue(设备.连续触控([(12, 34), (12, 34)], 间隔毫秒=8))
        self.assertEqual(
            runner.命令[-1][1:],
             ["-s", "emulator-5554", "shell", "sh", "-c",
              "input tap 12 34; sleep 0.040; input tap 12 34"],
        )

    def test_ADB长按使用同点swipe(self):
        runner = 假Runner(结果(在线模拟器), 结果(b"Physical size: 800x600"), 结果())
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        self.assertTrue(设备.长按触控(12, 34, 220))
        self.assertEqual(
            runner.命令[-1][1:],
            ["-s", "emulator-5554", "shell", "input", "swipe",
             "12", "34", "12", "34", "220"],
        )

    def test_screencap从ADB二进制解码并裁剪(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        图像[50:100, 40:90] = (20, 100, 200)
        编码成功, 编码 = cv2.imencode(".png", 图像)
        self.assertTrue(编码成功)
        runner = 假Runner(结果(在线模拟器), 结果(编码.tobytes()))
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        裁剪 = 设备.获取屏幕图像cv(40, 50, 90, 100)
        self.assertEqual(裁剪.shape, (50, 50, 3))
        self.assertEqual(runner.命令[1][1:], ["-s", "emulator-5554", "exec-out", "screencap", "-p"])

    def test_ADB屏幕把任意实际分辨率归一化到逻辑画布(self):
        图像 = np.zeros((720, 1280, 3), dtype=np.uint8)
        编码成功, 编码 = cv2.imencode(".png", 图像)
        self.assertTrue(编码成功)
        runner = 假Runner(
            结果(在线模拟器),
            结果(b"Physical size: 1280x720"),
            结果(编码.tobytes()),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        屏幕 = ADB屏幕(设备)
        结果图 = 屏幕.获取屏幕图像cv(0, 0, 800, 600)
        self.assertEqual(结果图.shape, (600, 800, 3))

    def test_打开已在前台的游戏不会重启或force_stop(self):
        runner = 假Runner(
            结果(在线模拟器),
            结果(b"mResumedActivity: ActivityRecord{1 com.supercell.clashofclans/.MainActivity}\n"),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        设备.打开应用("com.supercell.clashofclans")
        self.assertEqual(len(runner.命令), 2)
        self.assertFalse(any("force-stop" in 命令 for 命令 in runner.命令))
        self.assertFalse(any("monkey" in 命令 for 命令 in runner.命令))

    def test_雷电没有monkey时使用am_start启动游戏(self):
        runner = 假Runner(
            结果(在线模拟器),
            结果(b"mResumedActivity: ActivityRecord{1 com.android.launcher3/.Launcher}\n"),
            结果(b"priority=0\ncom.supercell.clashofclans/.SplashActivity\n"),
            结果(),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        设备.打开应用("com.supercell.clashofclans")
        self.assertEqual(
            runner.命令[2][1:],
            ["-s", "emulator-5554", "shell", "cmd", "package", "resolve-activity", "--brief",
             "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
             "com.supercell.clashofclans"],
        )
        self.assertEqual(
            runner.命令[3][1:],
            ["-s", "emulator-5554", "shell", "am", "start", "-n",
             "com.supercell.clashofclans/.SplashActivity"],
        )
        self.assertFalse(any("monkey" in 命令 for 命令 in runner.命令))

    def test_解析到其他包的组件时绝不启动其他应用(self):
        runner = 假Runner(
            结果(在线模拟器),
            结果(b"mResumedActivity: ActivityRecord{1 com.android.launcher3/.Launcher}\n"),
            结果(b"priority=0\ncom.android.settings/.Settings\n"),
            结果(),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        设备.打开应用("com.supercell.clashofclans")
        self.assertEqual(
            runner.命令[-1][1:],
            ["-s", "emulator-5554", "shell", "am", "start", "-a",
             "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
             "-p", "com.supercell.clashofclans"],
        )
        self.assertFalse(any("com.android.settings" in 命令 for 命令 in runner.命令))

    def test_能读取前台包名但不执行切换(self):
        runner = 假Runner(
            结果(b"topResumedActivity=ActivityRecord{1 u0 com.ldmnq.launcher3/com.android.launcher3.Launcher t6}\n"),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        self.assertEqual(设备.获取当前前台包名(), "com.ldmnq.launcher3")
        self.assertFalse(any("am" in 命令 and "start" in 命令 for 命令 in runner.命令))

    def test_前台不是目标包时拒绝触控且不操作其他应用(self):
        runner = 假Runner(
            结果(在线模拟器),
            结果(b"topResumedActivity=ActivityRecord{1 u0 com.ldmnq.launcher3/com.android.launcher3.Launcher t6}\n"),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        设备.设置目标包名("com.supercell.clashofclans")
        with self.assertRaisesRegex(ADB错误, "不在前台"):
            设备.触控(100, 100)
        self.assertFalse(any("input" in 命令 for 命令 in runner.命令))

    def test_ADB模式拒绝F5和系统功能键(self):
        runner = 假Runner(结果(在线模拟器))
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        键盘 = 键盘控制器(设备)
        self.assertFalse(键盘.按字符按压("f5"))
        self.assertFalse(键盘.按字符按压("home"))
        self.assertEqual(len(runner.命令), 0)  # 安全拒绝不发送任何 ADB 命令
        self.assertFalse(设备.按键(136))
        self.assertEqual(len(runner.命令), 1)

    def test_ADB安全保护拒绝结束游戏和模拟器(self):
        runner = 假Runner(结果(在线模拟器))
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with self.assertRaisesRegex(ADB错误, "安全保护"):
            设备.执行(["shell", "am", "force-stop", "com.supercell.clashofclans"])
        with self.assertRaisesRegex(ADB错误, "安全保护"):
            设备.关闭模拟器中的应用("com.supercell.clashofclans")
        self.assertEqual(len(runner.命令), 0)

    def test_建筑升级确认区灰色时不会误报成功(self):
        任务 = object.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: np.zeros((52, 140, 3), dtype=np.uint8)
            )
        )
        self.assertFalse(任务._升级确认按钮可用())

        绿色按钮 = np.zeros((52, 140, 3), dtype=np.uint8)
        绿色按钮[15:40, 20:120] = (40, 200, 40)
        任务.上下文.op.获取屏幕图像cv = lambda *_区域: 绿色按钮
        self.assertTrue(任务._升级确认按钮可用())

    def test_ADB网络地址拒绝非法输入(self):
        with self.assertRaisesRegex(ADB错误, "host:port"):
            ADB设备操作类.连接网络设备(ADB, "127.0.0.1;del:5555", runner=假Runner())

    def test_ADB网络连接使用单一明确地址参数(self):
        runner = 假Runner(结果(b"connected to 127.0.0.1:5555"))
        文本 = ADB设备操作类.连接网络设备(ADB, "127.0.0.1:5555", runner=runner)
        self.assertIn("connected", 文本)
        self.assertEqual(runner.命令[0][1:], ["connect", "127.0.0.1:5555"])

    def test_ADB鼠标点击和拖动委托给设备适配器(self):
        class 假设备:
            def __init__(self):
                self.操作 = []

            def 触控(self, x, y):
                self.操作.append(("tap", x, y))
                return True

            def 滑动(self, 起点, 终点, 时长):
                self.操作.append(("swipe", 起点, 终点, 时长))
                return True

        设备 = 假设备()
        鼠标 = 鼠标控制器(设备)
        鼠标.移动到(100, 200)
        鼠标.左键点击()
        鼠标.左键按下()
        鼠标.移动相对位置(20, 30)
        鼠标.左键抬起()
        self.assertEqual(设备.操作[0], ("tap", 100, 200))
        self.assertEqual(设备.操作[1][:3], ("swipe", (100, 200), (120, 230)))

    def test_ADB鼠标支持连续点击和长按(self):
        class 假设备:
            def __init__(self):
                self.操作 = []

            def 触控(self, _x, _y):
                return True

            def 滑动(self, _起点, _终点, _时长):
                return True

            def 连续触控(self, 点位列表, 间隔毫秒=0):
                self.操作.append(("multi", 点位列表, 间隔毫秒))
                return True

            def 长按触控(self, x, y, 时长毫秒=220):
                self.操作.append(("long", x, y, 时长毫秒))
                return True

        设备 = 假设备()
        鼠标 = 鼠标控制器(设备)
        self.assertTrue(鼠标.连续点击(100, 200, 次数=3, 间隔毫秒=8))
        self.assertTrue(鼠标.长按(100, 200, 时长毫秒=220))
        self.assertEqual(设备.操作[0], ("multi", [(100, 200)] * 3, 8))
        self.assertEqual(设备.操作[1], ("long", 100, 200, 220))

    def test_键盘映射对应Android按键码(self):
        self.assertEqual(键盘控制器._转换ADB按键码("esc"), 4)
        self.assertEqual(键盘控制器._转换ADB按键码("f5"), 135)
        self.assertEqual(键盘控制器._转换ADB按键码("a"), 29)


if __name__ == "__main__":
    unittest.main()
