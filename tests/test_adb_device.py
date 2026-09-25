import sys
import subprocess
import tempfile
import time
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
    def setUp(self):
        # ADB 服务冷却是进程级保护；测试之间必须清理时间戳，避免前一个
        # 测试的模拟重置影响后续测试的命令序列断言。
        ADB设备操作类._全局最近ADB服务重置时间 = 0.0

    def test_单文件模式数据库放在EXE旁而非临时解包目录(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            exe路径 = str(Path(临时目录) / "app.exe")
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", exe路径):
                数据库路径 = 任务数据库.默认数据库路径()
            self.assertEqual(Path(数据库路径), Path(临时目录) / "数据库" / "任务系统.db")

    def test_源码模式也遵守共享数据库环境变量(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            目标 = Path(临时目录) / "共享" / "任务系统.db"
            with patch.dict("os.environ", {"COCAUTO_DB_PATH": str(目标)}, clear=False), \
                    patch.object(sys, "frozen", False, create=True):
                数据库路径 = 任务数据库.默认数据库路径()
            self.assertEqual(Path(数据库路径), 目标.resolve())

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

    def test_自动选择当前前台CoC模拟器(self):
        class 自动选择Runner:
            def __init__(自身):
                自身.命令 = []

            def __call__(自身, 命令, **_参数):
                自身.命令.append(命令)
                if 命令[1:] == ["devices", "-l"]:
                    return 结果(
                        b"List of devices attached\n"
                        b"127.0.0.1:16416 device model:SM_A5560\n"
                        b"emulator-5556 device model:MuMu\n"
                    )
                if 命令[1:4] == ["-s", "127.0.0.1:16416", "shell"]:
                    if 命令[-3:] == ["list", "packages", "com.supercell.clashofclans"]:
                        return 结果(b"package:com.supercell.clashofclans\n")
                    return 结果(b"mResumedActivity: com.supercell.clashofclans/.GameApp\n")
                if 命令[1:4] == ["-s", "emulator-5556", "shell"]:
                    if 命令[-3:] == ["list", "packages", "com.supercell.clashofclans"]:
                        return 结果(b"package:com.supercell.clashofclans\n")
                    return 结果(b"mResumedActivity: app.lawnchair/.LawnchairLauncher\n")
                return 结果()

        runner = 自动选择Runner()
        with patch.object(ADB设备操作类, "解析ADB路径", return_value=ADB):
            设备 = ADB设备操作类.自动选择游戏设备(
                ADB,
                runner=runner,
                自动检测路径=False,
            )
        self.assertEqual(设备.序列号, "127.0.0.1:16416")

    def test_自动选择设备并列时拒绝猜测(self):
        class 并列Runner:
            def __call__(自身, 命令, **_参数):
                if 命令[1:] == ["devices", "-l"]:
                    return 结果(
                        b"List of devices attached\n"
                        b"127.0.0.1:16416 device model:MuMu\n"
                        b"emulator-5556 device model:MuMu\n"
                    )
                return 结果(b"package:com.supercell.clashofclans\n")

        with patch.object(ADB设备操作类, "解析ADB路径", return_value=ADB):
            with self.assertRaisesRegex(ADB错误, "多个可能的 CoC 模拟器"):
                ADB设备操作类.自动选择游戏设备(
                    ADB,
                    runner=并列Runner(),
                    自动检测路径=False,
                )

    def test_自动选择只看当前焦点而不看后台任务历史(self):
        class 焦点Runner:
            def __init__(自身):
                自身.命令 = []

            def __call__(自身, 命令, **_参数):
                自身.命令.append(命令)
                if 命令[1:] == ["devices", "-l"]:
                    return 结果(
                        b"List of devices attached\n"
                        b"127.0.0.1:16416 device model:MuMu\n"
                        b"emulator-5556 device model:MuMu\n"
                    )
                serial = 命令[2] if len(命令) > 2 and 命令[1] == "-s" else ""
                if 命令[-3:] == ["list", "packages", "com.supercell.clashofclans"]:
                    return 结果(b"package:com.supercell.clashofclans\n")
                if serial == "127.0.0.1:16416":
                    return 结果(
                        b"mCurrentFocus=Window{u0 com.supercell.clashofclans/.GameApp}\n"
                        b"RecentTask: com.supercell.clashofclans/.GameApp\n"
                    )
                return 结果(
                    b"mCurrentFocus=Window{u0 app.lawnchair/.Launcher}\n"
                    b"RecentTask: com.supercell.clashofclans/.GameApp\n"
                )

        runner = 焦点Runner()
        with patch.object(ADB设备操作类, "解析ADB路径", return_value=ADB):
            设备 = ADB设备操作类.自动选择游戏设备(
                ADB,
                runner=runner,
                自动检测路径=False,
            )
        self.assertEqual(设备.序列号, "127.0.0.1:16416")

    def test_自动选择合并同一MuMu的网络与emulator别名(self):
        class 同一实例Runner:
            def __call__(自身, 命令, **_参数):
                if 命令[1:] == ["devices", "-l"]:
                    return 结果(
                        b"List of devices attached\n"
                        b"127.0.0.1:16416 device model:MuMu\n"
                        b"emulator-5556 device model:MuMu\n"
                    )
                if 命令[-3:] == ["list", "packages", "com.supercell.clashofclans"]:
                    return 结果(b"package:com.supercell.clashofclans\n")
                if 命令[-3:] == ["getprop", "ro.serialno"]:
                    return 结果(b"mumu-test-instance\n")
                return 结果(
                    b"mCurrentFocus=Window{u0 com.supercell.clashofclans/.GameApp}\n"
                )

        with patch.object(ADB设备操作类, "解析ADB路径", return_value=ADB):
            设备 = ADB设备操作类.自动选择游戏设备(
                ADB,
                runner=同一实例Runner(),
                自动检测路径=False,
            )
        self.assertEqual(设备.序列号, "127.0.0.1:16416")

    def test_实体Samsung设备即使确认也会被阻止(self):
        runner = 假Runner(结果(b"List of devices attached\nR58M1234567 device model:SM_A5560 product:a55xchn\n"))
        设备 = ADB设备操作类(ADB, "R58M1234567", runner=runner)
        with self.assertRaisesRegex(ADB错误, "实体 Android 设备"):
            设备.获取屏幕图像cv()
        self.assertEqual(len(runner.命令), 1)
        self.assertEqual(runner.命令[0][1:], ["devices", "-l"])

    def test_emulator序列号即使手机样式描述也视为模拟器(self):
        设备 = ADB设备信息("emulator-5556", "device", "product:a55x model:SM_A5560 device:a55x")
        self.assertFalse(设备.疑似实体设备)

    def test_保存序列号失效时自动切换唯一CoC模拟器(self):
        class 失效序列号Runner:
            def __init__(自身):
                自身.命令 = []

            def __call__(自身, 命令, **_参数):
                自身.命令.append(命令)
                if 命令[1:] == ["devices", "-l"]:
                    return 结果(
                        b"List of devices attached\n"
                        b"emulator-5556 device product:a55x model:SM_A5560 device:a55x\n"
                    )
                if 命令[1:4] == ["-s", "emulator-5556", "shell"]:
                    if 命令[-3:] == ["list", "packages", "com.supercell.clashofclans"]:
                        return 结果(b"package:com.supercell.clashofclans\n")
                    return 结果(b"mResumedActivity: app.lawnchair/.LawnchairLauncher\n")
                return 结果()

        runner = 失效序列号Runner()
        设备 = ADB设备操作类(ADB, "127.0.0.1:16416", runner=runner)
        设备.设置目标包名("com.supercell.clashofclans")
        self.assertEqual(设备.确认在线().序列号, "emulator-5556")
        self.assertEqual(设备.设备序列号, "emulator-5556")

    def test_MuMuAndroid15手机样式描述按本机端口识别为模拟器(self):
        runner = 假Runner(
            结果(b"List of devices attached\n127.0.0.1:16416 device model:SM_A5560 product:a55xchn\n"),
            结果(b"Physical size: 720x1280"),
            结果(),
        )
        设备 = ADB设备操作类(ADB, "127.0.0.1:16416", runner=runner)
        self.assertEqual(设备.确认在线().序列号, "127.0.0.1:16416")

    def test_MuMu截图使用当前虚拟显示(self):
        设备 = ADB设备操作类(
            r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
            "127.0.0.1:16416",
        )
        设备.设置目标包名("com.supercell.clashofclans")
        窗口输出 = b"""\n  Display: mDisplayId=5\n    mCurrentFocus=Window{u0 com.supercell.clashofclans/com.supercell.titan.GameApp}\n"""
        显示输出 = b"""\n  mDisplayId=5\n    mPrimaryDisplayDevice=mumuscreen004(local:4619826948029188612)\n"""
        runner = 假Runner(
            结果(窗口输出),
            结果(显示输出),
        )
        设备._runner = runner
        self.assertEqual(设备._获取MuMu截图显示ID(), "4619826948029188612")

    def test_MuMu多显示优先选择游戏所在显示而不是启动器(self):
        设备 = ADB设备操作类(
            r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
            "127.0.0.1:16416",
        )
        设备.设置目标包名("com.supercell.clashofclans")
        窗口输出 = b"""
  Display: mDisplayId=0
    mCurrentFocus=Window{u0 app.lawnchair/app.lawnchair.LawnchairLauncher}
    mFocusedApp=ActivityRecord{launcher app.lawnchair/.LawnchairLauncher}
  Display: mDisplayId=6
    mCurrentFocus=null
    mFocusedApp=ActivityRecord{game com.supercell.clashofclans/com.supercell.titan.GameApp}
"""
        显示输出 = b"""
mViewports=[DisplayViewport{type=INTERNAL, valid=true, displayId=0, uniqueId='local:4619827820427265280'}, DisplayViewport{type=EXTERNAL, valid=true, displayId=6, uniqueId='local:4619827203584079877'}]
"""
        设备._runner = 假Runner(结果(窗口输出), 结果(显示输出))
        self.assertEqual(设备._获取MuMu截图显示ID(), "4619827203584079877")

    def test_MuMu显示查询短暂空响应会有界重试(self):
        设备 = ADB设备操作类(
            r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
            "127.0.0.1:16416",
        )
        设备.设置目标包名("com.supercell.clashofclans")
        窗口输出 = b"""
  Display: mDisplayId=6
    mCurrentFocus=null
    mFocusedApp=ActivityRecord{game com.supercell.clashofclans/com.supercell.titan.GameApp}
"""
        显示输出 = b"""
mViewports=[DisplayViewport{type=EXTERNAL, valid=true, displayId=6, uniqueId='local:4619827203584079877'}]
"""
        设备._runner = 假Runner(结果(b""), 结果(窗口输出), 结果(显示输出))
        self.assertEqual(设备._获取MuMu截图显示ID(), "4619827203584079877")

    def test_MuMu窗口焦点短暂丢失复用最近逻辑显示层(self):
        设备 = ADB设备操作类(
            r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
            "127.0.0.1:16416",
        )
        设备.设置目标包名("com.supercell.clashofclans")
        设备._最近有效输入显示ID = "6"
        设备._最近有效输入显示ID时间 = time.monotonic()
        设备._runner = 假Runner(结果(b""))
        self.assertEqual(设备._获取MuMu输入显示ID(), "6")

    def test_MuMu显示层短暂丢失复用最近物理映射但不回退display0(self):
        设备 = ADB设备操作类(
            r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
            "127.0.0.1:16416",
        )
        设备.设置目标包名("com.supercell.clashofclans")
        设备._最近有效输入显示ID = "6"
        设备._最近有效输入显示ID时间 = time.monotonic()
        设备._最近有效截图显示ID = "4619827203584079877"
        设备._最近有效截图显示ID时间 = time.monotonic()
        设备._runner = 假Runner(结果(b""))
        self.assertEqual(设备._获取MuMu截图显示ID(), "4619827203584079877")

    def test_MuMu输入显示层使用游戏逻辑display而不是启动器display(self):
        窗口输出 = b"""
  Display: mDisplayId=0
    mCurrentFocus=Window{u0 app.lawnchair/app.lawnchair.LawnchairLauncher}
    mFocusedApp=ActivityRecord{launcher app.lawnchair/.LawnchairLauncher}
  Display: mDisplayId=7
    mCurrentFocus=Window{u0 com.supercell.clashofclans/com.supercell.titan.GameApp}
    mFocusedApp=ActivityRecord{game com.supercell.clashofclans/com.supercell.titan.GameApp}
"""
        self.assertEqual(
            ADB设备操作类._解析MuMu逻辑显示ID(
                窗口输出.decode("utf-8"), "com.supercell.clashofclans"
            ),
            "7",
        )

    def test_MuMu触控命令明确发送到游戏display(self):
        窗口输出 = b"""
  Display: mDisplayId=0
    mCurrentFocus=Window{u0 app.lawnchair/app.lawnchair.LawnchairLauncher}
    mFocusedApp=ActivityRecord{launcher app.lawnchair/.LawnchairLauncher}
  Display: mDisplayId=7
    mCurrentFocus=Window{u0 com.supercell.clashofclans/com.supercell.titan.GameApp}
    mFocusedApp=ActivityRecord{game com.supercell.clashofclans/com.supercell.titan.GameApp}
"""
        runner = 假Runner(
            结果(b"List of devices attached\n127.0.0.1:16416 device product:a55x model:SM_A5560\n"),
            结果(b"topResumedActivity=ActivityRecord{1 u0 com.supercell.clashofclans/com.supercell.titan.GameApp t15}\n"),
            结果(窗口输出),
            结果(b"""Event Hub State:
    27: Xiaomi Touchscreen
      Path: /dev/input/event16
Input Reader State:
  Device 28: Xiaomi Touchscreen
    EventHub Devices: [ 27 ]
      Viewport INTERNAL: displayId=7, uniqueId=local:test
"""),
            结果(b"""ABS_MT_POSITION_X : value 0, min 0, max 720
ABS_MT_POSITION_Y : value 0, min 0, max 1280
"""),
            结果(b"""Display: mDisplayId=7 (organized)
  cur=1280x720 app=1280x720 rng=720x720-1280x1280
"""),
            结果(b"Physical size: 1280x720"),
            结果(),
        )
        设备 = ADB设备操作类(
            r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
            "127.0.0.1:16416",
            runner=runner,
            自动检测路径=False,
        )
        设备.设置目标包名("com.supercell.clashofclans")
        self.assertTrue(设备.触控(12, 34))
        self.assertEqual(runner.命令[-1][1:4], ["-s", "127.0.0.1:16416", "shell"])
        self.assertEqual(runner.命令[-1][4:6], ["sh", "-c"])
        self.assertIn("sendevent /dev/input/event16", runner.命令[-1][-1])
        self.assertIn("sendevent /dev/input/event16 3 53 679", runner.命令[-1][-1])
        self.assertIn("sendevent /dev/input/event16 3 54 19", runner.命令[-1][-1])

    def test_MuMu地图滑动使用input_display而不是旋转事件轴(self):
        """organized display 的单指拖动必须沿用截图方向，不能误点 HUD。"""
        runner = 假Runner()
        设备 = ADB设备操作类(
            r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
            "127.0.0.1:16416",
            runner=runner,
            自动检测路径=False,
        )
        设备.设置目标包名("com.supercell.clashofclans")
        with patch.object(设备, "_验证目标"), \
                patch.object(设备, "_验证输入前台"), \
                patch.object(设备, "_输入显示参数", return_value=["-d", "7"]), \
                patch.object(
                    设备,
                    "参考坐标转设备坐标",
                    side_effect=[(952, 218), (216, 580)],
                ):
            self.assertTrue(设备.滑动((595, 182), (135, 483), 350))

        self.assertEqual(
            runner.命令[-1][1:],
            [
                "-s", "127.0.0.1:16416", "shell", "input", "-d", "7",
                "swipe", "952", "218", "216", "580", "350",
            ],
        )

    def test_MuMu拉伸手势明确发送到游戏display(self):
        窗口输出 = b"""
  Display: mDisplayId=0
    mCurrentFocus=Window{u0 app.lawnchair/app.lawnchair.LawnchairLauncher}
    mFocusedApp=ActivityRecord{launcher app.lawnchair/.LawnchairLauncher}
  Display: mDisplayId=7
    mCurrentFocus=Window{u0 com.supercell.clashofclans/com.supercell.titan.GameApp}
    mFocusedApp=ActivityRecord{game com.supercell.clashofclans/com.supercell.titan.GameApp}
"""
        runner = 假Runner(
            结果(b"List of devices attached\n127.0.0.1:16416 device product:a55x model:SM_A5560\n"),
            结果(b"topResumedActivity=ActivityRecord{1 u0 com.supercell.clashofclans/com.supercell.titan.GameApp t15}\n"),
            结果(窗口输出),
            结果(b"""Event Hub State:
    27: Xiaomi Touchscreen
      Path: /dev/input/event16
Input Reader State:
  Device 28: Xiaomi Touchscreen
    EventHub Devices: [ 27 ]
      Viewport INTERNAL: displayId=7, uniqueId=local:test
"""),
            结果(b"""  ABS_MT_POSITION_X : value 0, min 0, max 720
  ABS_MT_POSITION_Y : value 0, min 0, max 1280
"""),
            结果(),
        )
        设备 = ADB设备操作类(
            r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
            "127.0.0.1:16416",
            runner=runner,
            自动检测路径=False,
        )
        设备.设置目标包名("com.supercell.clashofclans")
        self.assertTrue(设备.游戏内拉远视距(次数=1))
        self.assertEqual(runner.命令[-1][1:4], ["-s", "127.0.0.1:16416", "shell"])
        self.assertEqual(runner.命令[-1][4:6], ["sh", "-c"])
        self.assertIn("sendevent /dev/input/event16", runner.命令[-1][-1])

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
            结果(在线模拟器),
            结果(),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        self.assertTrue(设备.触控(12, 34))
        self.assertTrue(any(命令[1:] == ["reconnect", "offline"] for 命令 in runner.命令))
        self.assertEqual(
            runner.命令[-1][1:],
            ["-s", "emulator-5554", "shell", "input", "tap", "12", "34"],
        )

    def test_设备从列表消失时重启ADB服务但不重启模拟器(self):
        runner = 假Runner(
            结果(b"List of devices attached\n"),
            结果(),
            结果(),
            结果(在线模拟器),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        self.assertEqual(设备.确认在线().序列号, "emulator-5554")
        self.assertEqual(runner.命令[0][1:], ["devices", "-l"])
        self.assertEqual(runner.命令[1][1:], ["kill-server"])
        self.assertEqual(runner.命令[2][1:], ["start-server"])
        self.assertEqual(runner.命令[3][1:], ["devices", "-l"])
        self.assertFalse(any("force-stop" in 命令 or "reboot" in 命令 for 命令 in runner.命令))

    def test_不同适配器不会并发重复重置ADB服务(self):
        第一个 = 假Runner()
        第二个 = 假Runner()
        设备一 = ADB设备操作类(ADB, "emulator-5554", runner=第一个)
        设备二 = ADB设备操作类(ADB, "127.0.0.1:16416", runner=第二个)

        设备一._重置ADB服务()
        设备二._重置ADB服务()

        self.assertEqual([命令[1:] for 命令 in 第一个.命令], [["kill-server"], ["start-server"]])
        self.assertEqual(第二个.命令, [])

    def test_运行期设备消失时重置ADB服务后重试(self):
        runner = 假Runner(
            结果(code=1, 错误=b"error: device not found"),
            结果(),
            结果(),
            结果(),
            结果(),
            结果(在线模拟器),
            结果(b"ok"),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        self.assertTrue(设备.执行(["shell", "input", "tap", "12", "34"]))
        self.assertEqual(runner.命令[1][1:], ["reconnect", "offline"])
        self.assertEqual(runner.命令[3][1:], ["kill-server"])
        self.assertEqual(runner.命令[4][1:], ["start-server"])
        self.assertEqual(
            runner.命令[-1][1:],
            ["-s", "emulator-5554", "shell", "input", "tap", "12", "34"],
        )

    def test_运行期旧设备消失时不会把输入重试到其他设备(self):
        其他设备 = b"List of devices attached\nemulator-5556 device model:MuMu\n"
        runner = 假Runner(
            结果(code=1, 错误=b"error: device not found"),
            结果(),
            结果(其他设备),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with self.assertRaisesRegex(ADB错误, "未出现在当前 ADB 设备列表|不会把操作发送到其他设备"):
            设备.执行(["shell", "input", "tap", "12", "34"])
        输入命令 = [命令 for 命令 in runner.命令 if 命令[-4:] == ["input", "tap", "12", "34"]]
        self.assertEqual(len(输入命令), 1, "失效设备不应向其他 serial 重复发送输入")

    def test_ADB连续截图超时会熔断而不是无限创建进程(self):
        class 超时Runner:
            def __init__(self):
                self.命令 = []

            def __call__(self, 命令, **_参数):
                self.命令.append(命令)
                if 命令[1:] == ["devices", "-l"]:
                    return 结果(在线模拟器)
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
        with patch.object(ADB设备操作类, "_获取主机内存状态", return_value={
            "内存负载": 50,
            "可用物理内存": 8 * 1024 * 1024 * 1024,
            "可用提交额度": 8 * 1024 * 1024 * 1024,
        }):
            裁剪 = 设备.获取屏幕图像cv(40, 50, 90, 100)
        self.assertEqual(裁剪.shape, (50, 50, 3))
        self.assertEqual(runner.命令[1][1:], ["-s", "emulator-5554", "exec-out", "screencap", "-p"])

    def test_MuMu未确认游戏显示层时拒绝退回启动器截图(self):
        设备 = ADB设备操作类(
            r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
            "127.0.0.1:16416",
            runner=假Runner(),
            自动检测路径=False,
        )
        设备._截图重试上限 = 1
        with patch.object(ADB设备操作类, "_验证目标"), \
                patch.object(设备, "_获取MuMu截图显示ID", return_value=None), \
                patch.object(设备, "_检查主机内存预算"):
            with self.assertRaisesRegex(ADB错误, "未确认 CoC 所在的 MuMu 游戏显示层"):
                设备.获取屏幕图像cv()

    def test_MuMu显示服务缺失时不复用旧显示ID或创建截图进程(self):
        设备 = ADB设备操作类(
            r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
            "127.0.0.1:16416",
            runner=假Runner(
                结果(错误=b"Can't find service: window\n"),
            ),
            自动检测路径=False,
        )
        设备._最近有效输入显示ID = "7"
        设备._最近有效输入显示ID时间 = time.monotonic()
        设备._最近有效截图显示ID = "4619827203584079877"
        设备._最近有效截图显示ID时间 = time.monotonic()
        with patch.object(设备, "_验证目标"), patch.object(设备, "_检查主机内存预算"):
            with self.assertRaisesRegex(ADB错误, "未确认 CoC 所在的 MuMu 游戏显示层"):
                设备.获取屏幕图像cv()
        self.assertIsNone(设备._最近有效输入显示ID)
        self.assertIsNone(设备._最近有效截图显示ID)
        self.assertFalse(any("screencap" in 命令 for 命令 in 设备._runner.命令))

    def test_ADB成功码携带系统服务缺失诊断时抛出明确错误(self):
        设备 = ADB设备操作类(
            ADB,
            "emulator-5554",
            runner=假Runner(结果(错误=b"Can't find service: package\n")),
        )
        with self.assertRaisesRegex(ADB错误, "Can't find service: package"):
            设备.执行(["shell", "cmd", "package", "resolve-activity"])

    def test_screencap完整截图哨兵不会裁剪超宽设备(self):
        图像 = np.zeros((1200, 2200, 3), dtype=np.uint8)
        编码成功, 编码 = cv2.imencode(".png", 图像)
        self.assertTrue(编码成功)
        runner = 假Runner(结果(在线模拟器), 结果(编码.tobytes()))
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with patch.object(ADB设备操作类, "_获取主机内存状态", return_value={
            "内存负载": 50,
            "可用物理内存": 8 * 1024 * 1024 * 1024,
            "可用提交额度": 8 * 1024 * 1024 * 1024,
        }):
            完整图像 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
        self.assertEqual(完整图像.shape, (1200, 2200, 3))

    def test_screencap解码失败后有限重连并重试原命令(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        编码成功, 编码 = cv2.imencode(".png", 图像)
        self.assertTrue(编码成功)
        runner = 假Runner(
            结果(在线模拟器),
            结果(b"not-a-png"),
            结果(),
            结果(在线模拟器),
            结果(编码.tobytes()),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with patch.object(ADB设备操作类, "_获取主机内存状态", return_value={
            "内存负载": 50,
            "可用物理内存": 8 * 1024 * 1024 * 1024,
            "可用提交额度": 8 * 1024 * 1024 * 1024,
        }):
            结果图 = 设备.获取屏幕图像cv()
        self.assertEqual(结果图.shape, (600, 800, 3))
        self.assertTrue(any(命令[1:] == ["reconnect", "offline"] for 命令 in runner.命令))
        self.assertEqual(runner.命令[-1][1:], ["-s", "emulator-5554", "exec-out", "screencap", "-p"])

    def test_MuMu截图前的多屏警告不会破坏PNG解码(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        编码成功, 编码 = cv2.imencode(".png", 图像)
        self.assertTrue(编码成功)
        警告 = b"[Warning] Multiple displays were found, but no display id was specified!\n"
        runner = 假Runner(结果(在线模拟器), 结果(警告 + 编码.tobytes()))
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with patch.object(ADB设备操作类, "_获取主机内存状态", return_value={
            "内存负载": 50,
            "可用物理内存": 8 * 1024 * 1024 * 1024,
            "可用提交额度": 8 * 1024 * 1024 * 1024,
        }):
            结果图 = 设备.获取屏幕图像cv()
        self.assertEqual(结果图.shape, (600, 800, 3))

    def test_低内存时不创建截图ADB进程(self):
        runner = 假Runner(结果(在线模拟器))
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with patch.object(
            ADB设备操作类,
            "_获取主机内存状态",
            return_value={"内存负载": 95, "可用物理内存": 512 * 1024 * 1024,
                         "可用提交额度": 512 * 1024 * 1024},
        ):
            with self.assertRaisesRegex(ADB错误, "主机内存保护"):
                设备.获取屏幕图像cv()
        # 目标验证仍会查询设备列表；真正的截图进程不能被创建。
        self.assertEqual(len(runner.命令), 1)
        self.assertEqual(runner.命令[0][1:], ["devices", "-l"])

    def test_ADB屏幕把任意实际分辨率归一化到逻辑画布(self):
        图像 = np.zeros((720, 1280, 3), dtype=np.uint8)
        编码成功, 编码 = cv2.imencode(".png", 图像)
        self.assertTrue(编码成功)
        runner = 假Runner(
            结果(在线模拟器),
            结果(编码.tobytes()),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        屏幕 = ADB屏幕(设备)
        with patch.object(ADB设备操作类, "_获取主机内存状态", return_value={
            "内存负载": 50,
            "可用物理内存": 8 * 1024 * 1024 * 1024,
            "可用提交额度": 8 * 1024 * 1024 * 1024,
        }):
            结果图 = 屏幕.获取屏幕图像cv(0, 0, 800, 600)
        self.assertEqual(结果图.shape, (600, 800, 3))

    def test_ADB屏幕短窗口复用同一截图(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        编码成功, 编码 = cv2.imencode(".png", 图像)
        self.assertTrue(编码成功)
        runner = 假Runner(结果(在线模拟器), 结果(编码.tobytes()))
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        屏幕 = ADB屏幕(设备)
        with patch.object(ADB设备操作类, "_获取主机内存状态", return_value={
            "内存负载": 50,
            "可用物理内存": 8 * 1024 * 1024 * 1024,
            "可用提交额度": 8 * 1024 * 1024 * 1024,
        }):
            屏幕.获取屏幕图像cv(0, 0, 800, 600)
            屏幕.获取屏幕图像cv(20, 20, 100, 100)
        self.assertEqual(len(runner.命令), 2)

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

    def test_MuMu多显示任一层有游戏都不会重复启动(self):
        runner = 假Runner(
            结果(在线模拟器),
            结果(
                b"topResumedActivity=ActivityRecord{1 u0 app.lawnchair/.LawnchairLauncher t2}\n"
                b"topResumedActivity=ActivityRecord{2 u0 com.supercell.clashofclans/com.supercell.titan.GameApp t14}\n"
            ),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        设备.打开应用("com.supercell.clashofclans")
        self.assertEqual(len(runner.命令), 2)
        self.assertFalse(any("am" in 命令 and "start" in 命令 for 命令 in runner.命令))

    def test_MuMu多显示前台查询优先返回已绑定目标包(self):
        runner = 假Runner(
            结果(
                b"topResumedActivity=ActivityRecord{1 u0 app.lawnchair/.LawnchairLauncher t2}\n"
                b"topResumedActivity=ActivityRecord{2 u0 com.supercell.clashofclans/com.supercell.titan.GameApp t14}\n"
            ),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        设备.设置目标包名("com.supercell.clashofclans")
        self.assertEqual(设备.获取当前前台包名(), "com.supercell.clashofclans")

    def test_游戏内拉远视距只向已确认的CoC发送F5(self):
        runner = 假Runner(
            结果(在线模拟器),
            结果(b"topResumedActivity=ActivityRecord{1 u0 com.supercell.clashofclans/com.supercell.titan.GameApp t14}\n"),
            结果(),
            结果(b"topResumedActivity=ActivityRecord{1 u0 com.supercell.clashofclans/com.supercell.titan.GameApp t14}\n"),
            结果(),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        设备.设置目标包名("com.supercell.clashofclans")
        self.assertTrue(设备.游戏内拉远视距(次数=2, 间隔毫秒=80))
        按键命令 = [命令 for 命令 in runner.命令 if "keyevent" in 命令]
        self.assertEqual(len(按键命令), 2)
        self.assertTrue(all(命令[-1] == "135" for 命令 in 按键命令))

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
        任务.执行OCR识别 = lambda _区域: []
        self.assertFalse(任务._升级确认按钮可用())

        绿色按钮 = np.zeros((52, 140, 3), dtype=np.uint8)
        绿色按钮[15:40, 20:120] = (40, 200, 40)
        任务.上下文.op.获取屏幕图像cv = lambda *_区域: 绿色按钮
        任务.执行OCR识别 = lambda _区域: [
            ([[550, 490], [590, 490], [590, 515], [550, 515]], "確認", 0.99),
        ]
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
