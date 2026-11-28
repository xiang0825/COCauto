import sys
import subprocess
import tempfile
import time
import unittest
import importlib
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
        self.调用参数 = []

    def __call__(self, 命令, **参数):
        self.命令.append(命令)
        self.调用参数.append(参数)
        if self.响应:
            return self.响应.pop(0)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


def 结果(输出=b"", code=0, 错误=b""):
    return SimpleNamespace(returncode=code, stdout=输出, stderr=错误)


在线模拟器 = b"List of devices attached\nemulator-5554 device product:LDPlayer model:LDPlayer\n"


class ADB设备测试(unittest.TestCase):
    def setUp(self):
        # ADB 服务冷却与 BlueStacks 探测缓存是进程级保护；测试之间必须清理，
        # 避免前一个测试的状态影响后续测试的命令序列断言。
        ADB设备操作类._全局最近ADB服务重置时间 = 0.0
        ADB设备操作类.清除BlueStacks探测缓存()

    def _创建假ADB文件(self, *相对路径段: str) -> str:
        临时目录 = tempfile.TemporaryDirectory()
        self.addCleanup(临时目录.cleanup)
        假adb = Path(临时目录.name).joinpath(*相对路径段)
        假adb.parent.mkdir(parents=True, exist_ok=True)
        假adb.write_text("#!/bin/sh\n", encoding="utf-8")
        return str(假adb)

    def _创建假MuMuADB(self) -> str:
        return self._创建假ADB文件("Netease", "MuMuPlayer", "nx_main", "adb.exe")

    def test_单文件模式数据库放在EXE旁而非临时解包目录(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            exe路径 = str(Path(临时目录) / "app.exe")
            with patch.object(sys, "platform", "win32"), \
                    patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "executable", exe路径):
                数据库路径 = 任务数据库.默认数据库路径()
            self.assertEqual(Path(数据库路径), Path(临时目录) / "数据库" / "任务系统.db")

    def test_打包版不误用EXE上级的开发数据库(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            根目录 = Path(临时目录)
            exe路径 = 根目录 / "coc_robot" / "部落冲突.exe"
            共享路径 = 根目录 / "数据库" / "任务系统.db"
            共享路径.parent.mkdir(parents=True)
            共享路径.touch()
            with patch.object(sys, "platform", "win32"), \
                    patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "executable", str(exe路径)), \
                    patch.dict("os.environ", {"COCAUTO_DB_PATH": ""}, clear=False):
                数据库路径 = 任务数据库.默认数据库路径()
            self.assertEqual(Path(数据库路径), exe路径.parent / "数据库" / "任务系统.db")

    def test_打包版显式共享数据库路径仍优先(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            共享路径 = Path(临时目录) / "共享" / "任务系统.db"
            exe路径 = str(Path(临时目录) / "发布" / "部落冲突.exe")
            with patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "executable", exe路径), \
                    patch.dict("os.environ", {"COCAUTO_DB_PATH": str(共享路径)}, clear=False):
                数据库路径 = 任务数据库.默认数据库路径()
            self.assertEqual(Path(数据库路径), 共享路径.resolve())

    def test_源码模式优先复用项目上级的共享数据库(self):
        数据库模块 = importlib.import_module("数据库.任务数据库")
        with tempfile.TemporaryDirectory() as 临时目录:
            根目录 = Path(临时目录)
            假文件 = 根目录 / "coc_robot" / "数据库" / "任务数据库.py"
            共享路径 = 根目录 / "数据库" / "任务系统.db"
            假文件.parent.mkdir(parents=True)
            共享路径.parent.mkdir(parents=True)
            共享路径.touch()
            with patch.object(数据库模块, "__file__", str(假文件)), \
                    patch.object(sys, "frozen", False, create=True), \
                    patch.dict("os.environ", {"COCAUTO_DB_PATH": ""}, clear=False):
                数据库路径 = 任务数据库.默认数据库路径()
            self.assertEqual(Path(数据库路径), 共享路径)

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

    def test_所有ADB调用都使用独立服务端口(self):
        self.assertEqual(ADB设备操作类.ADB服务器端口, 5038)

        设备命令Runner = 假Runner(结果(b"ok"))
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=设备命令Runner)
        设备.执行(["shell", "echo", "ok"])

        服务命令Runner = 假Runner()
        服务设备 = ADB设备操作类(ADB, "emulator-5554", runner=服务命令Runner)
        服务设备._重置ADB服务()

        恢复Runner = 假Runner()
        恢复设备 = ADB设备操作类(ADB, "127.0.0.1:16416", runner=恢复Runner)
        with patch.object(恢复设备, "_是MuMu连接", return_value=True), patch(
            "模块.ADB设备操作类.time.sleep"
        ):
            恢复设备._连接已保存网络设备()
            恢复设备._尝试恢复ADB连接()

        扫描Runner = 假Runner(结果(在线模拟器))
        ADB设备操作类.扫描设备(ADB, runner=扫描Runner)

        连接Runner = 假Runner(结果(b"connected to 127.0.0.1:5555"))
        ADB设备操作类.连接网络设备(ADB, "127.0.0.1:5555", runner=连接Runner)

        for runner in (
            设备命令Runner,
            服务命令Runner,
            恢复Runner,
            扫描Runner,
            连接Runner,
        ):
            self.assertTrue(runner.调用参数)
            for 参数 in runner.调用参数:
                self.assertEqual(
                    参数.get("env", {}).get("ANDROID_ADB_SERVER_PORT"),
                    str(ADB设备操作类.ADB服务器端口),
                )

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
                    return 结果(
                        b"FocusedWindows:\n"
                        b"  displayId=4, name='87ab31 com.supercell.clashofclans/com.supercell.titan.GameApp'\n"
                    )
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
                        b"FocusedWindows:\n"
                        b"  displayId=4, name='87ab31 com.supercell.clashofclans/com.supercell.titan.GameApp'\n"
                    )
                return 结果(
                    b"topResumedActivity=ActivityRecord{1 u0 app.lawnchair/.Launcher t2}\n"
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
                if 命令[-2:] == ["getprop", "ro.serialno"]:
                    return 结果(b"mumu-test-instance\n")
                if 命令[1:4] == ["-s", "127.0.0.1:16416", "shell"]:
                    return 结果(
                        b"FocusedWindows:\n"
                        b"  displayId=4, name='87ab31 com.supercell.clashofclans/com.supercell.titan.GameApp'\n"
                    )
                return 结果(
                    b"topResumedActivity=ActivityRecord{1 u0 com.supercell.clashofclans/.GameApp t14}\n"
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

    def test_MuMu显示服务识别emulator别名并启用多显示截图(self):
        runner = 假Runner(结果(
            b"DisplayDeviceInfo{mumuscreen001: uniqueId=local:4619827767814508545}"
        ))
        设备 = ADB设备操作类(self._创建假ADB文件("adb", "adb.exe"), "emulator-5556", runner=runner)
        self.assertTrue(设备._是MuMu连接())
        self.assertEqual(
            runner.命令[0][1:],
            ["-s", "emulator-5556", "shell", "dumpsys", "display"],
        )

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
            self._创建假MuMuADB(),
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
            self._创建假MuMuADB(),
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
            self._创建假MuMuADB(),
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
            self._创建假MuMuADB(),
            "127.0.0.1:16416",
        )
        设备.设置目标包名("com.supercell.clashofclans")
        设备._最近有效输入显示ID = "6"
        设备._最近有效输入显示ID时间 = time.monotonic()
        设备._runner = 假Runner(结果(b""))
        self.assertEqual(设备._获取MuMu输入显示ID(), "6")

    def test_MuMu显示层短暂丢失复用最近物理映射但不回退display0(self):
        设备 = ADB设备操作类(
            self._创建假MuMuADB(),
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

    def test_MuMu输入焦点绑定游戏显示层而不遍历活动栈(self):
        活动输出 = b"""
FocusedWindows:
  displayId=4, name='87ab31 com.supercell.clashofclans/com.supercell.titan.GameApp'
"""
        runner = 假Runner(结果(活动输出))
        设备 = ADB设备操作类(
            self._创建假MuMuADB(),
            "127.0.0.1:16416", runner=runner, 自动检测路径=False,
        )
        设备.设置目标包名("com.supercell.clashofclans")
        self.assertEqual(设备._获取MuMu输入显示ID(), "4")
        self.assertEqual(设备._解析MuMu焦点包名(活动输出.decode(), 设备._目标包名), 设备._目标包名)
        self.assertEqual(runner.命令[0][-2:], ["dumpsys", "input"])
        self.assertFalse(any("activities" in 命令 for 命令 in runner.命令))

    def test_MuMu后台游戏任务不能授权输入显示层(self):
        活动输出 = """
Display #4 (activities from top to bottom):
    * Task{1 A=10017:com.supercell.clashofclans visible=false}
Display #0 (activities from top to bottom):
    topResumedActivity=ActivityRecord{2 u0 app.lawnchair/.LawnchairLauncher t2}
"""
        self.assertIsNone(ADB设备操作类._解析MuMu逻辑显示ID(活动输出, "com.supercell.clashofclans"))
        self.assertEqual(ADB设备操作类._解析MuMu焦点包名(活动输出, "com.supercell.clashofclans"), "app.lawnchair")

    def test_MuMu输入服务焦点可安全识别当前包名和逻辑显示层(self):
        输入输出 = """
FocusedApplications:
  displayId=0, name='ActivityRecord{launcher app.lawnchair/.LawnchairLauncher t2}', dispatchingTimeout=25000ms
FocusedWindows:
  displayId=4, name='87ab31 com.supercell.clashofclans/com.supercell.titan.GameApp'
FocusRequests:
  displayId=4, name='87ab31 com.supercell.clashofclans/com.supercell.titan.GameApp' result='OK'
"""
        self.assertEqual(
            ADB设备操作类._解析MuMu焦点包名(输入输出, "com.supercell.clashofclans"),
            "com.supercell.clashofclans",
        )
        self.assertEqual(
            ADB设备操作类._解析MuMu逻辑显示ID(
                输入输出, "com.supercell.clashofclans"
            ),
            "4",
        )

    def test_MuMu启动器焦点不会错误授权后台CoC显示层(self):
        输入输出 = """
FocusedWindows:
  displayId=0, name='d35c333 app.lawnchair/app.lawnchair.LawnchairLauncher'
"""
        self.assertEqual(
            ADB设备操作类._解析MuMu焦点包名(输入输出, "com.supercell.clashofclans"),
            "app.lawnchair",
        )
        self.assertIsNone(
            ADB设备操作类._解析MuMu逻辑显示ID(
                输入输出, "com.supercell.clashofclans"
            )
        )

    def test_MuMu前台与输入显示查询只读取dumpsys_input(self):
        输入输出 = b"""
FocusedWindows:
  displayId=4, name='87ab31 com.supercell.clashofclans/com.supercell.titan.GameApp'
"""
        runner = 假Runner(结果(输入输出))
        设备 = ADB设备操作类(
            self._创建假MuMuADB(),
            "127.0.0.1:16416", runner=runner, 自动检测路径=False,
        )
        设备.设置目标包名("com.supercell.clashofclans")
        self.assertEqual(设备.获取当前前台包名(), "com.supercell.clashofclans")
        self.assertEqual(设备._获取MuMu输入显示ID(), "4")
        self.assertEqual(len(runner.命令), 1)
        self.assertEqual(runner.命令[0][-2:], ["dumpsys", "input"])
        self.assertFalse(any("activities" in 命令 for 命令 in runner.命令))

    def test_MuMu已在前台的游戏不会查询完整活动栈(self):
        runner = 假Runner(结果(
            b"FocusedWindows:\n"
            b"  displayId=4, name='87ab31 com.supercell.clashofclans/com.supercell.titan.GameApp'\n"
        ))
        设备 = ADB设备操作类(
            self._创建假MuMuADB(),
            "127.0.0.1:16416", runner=runner, 自动检测路径=False,
        )
        with patch.object(设备, "_验证目标"):
            设备.打开应用("com.supercell.clashofclans")
        self.assertEqual(len(runner.命令), 1)
        self.assertEqual(runner.命令[0][-2:], ["dumpsys", "input"])

    def test_轻量top_resumed查询可解析前台包名(self):
        输出 = """
ACTIVITY MANAGER TOP-RESUMED (dumpsys activity top-resumed)
packageName=com.supercell.clashofclans processName=com.supercell.clashofclans
"""
        self.assertEqual(
            ADB设备操作类._解析前台包名列表(输出),
            ["com.supercell.clashofclans"],
        )

    def test_MuMu屏幕尺寸来自显示视口而非窗口转储(self):
        活动输出 = b"Display #4 (activities from top to bottom):\n    topResumedActivity=ActivityRecord{1 u0 com.supercell.clashofclans/.GameApp t32}\n"
        显示输出 = b"mViewports=[DisplayViewport{displayId=4, uniqueId='local:123', logicalFrame=Rect(0, 0 - 1280, 720)}]"
        runner = 假Runner(结果(活动输出), 结果(显示输出))
        设备 = ADB设备操作类(
            self._创建假MuMuADB(),
            "127.0.0.1:16416", runner=runner, 自动检测路径=False,
        )
        设备.设置目标包名("com.supercell.clashofclans")
        self.assertEqual(设备.查询屏幕尺寸(), (1280, 720))
        self.assertFalse(any("window" in 命令 for 命令 in runner.命令))

    def test_MuMu触控命令明确发送到游戏display(self):
        runner = 假Runner()
        设备 = ADB设备操作类(
            self._创建假MuMuADB(),
            "127.0.0.1:16416",
            runner=runner,
            自动检测路径=False,
        )
        设备.设置目标包名("com.supercell.clashofclans")
        with patch.object(设备, "_验证目标"), \
                patch.object(设备, "_验证输入前台"), \
                patch.object(设备, "_输入显示参数", return_value=["-d", "7"]), \
                patch.object(设备, "参考坐标转设备坐标", return_value=(19, 41)):
            self.assertTrue(设备.触控(12, 34))
        self.assertEqual(
            runner.命令[-1][1:],
            ["-s", "127.0.0.1:16416", "shell", "input", "-d", "7", "tap", "19", "41"],
        )

    def test_MuMu地图滑动使用input_display而不是旋转事件轴(self):
        """organized display 的单指拖动必须沿用截图方向，不能误点 HUD。"""
        runner = 假Runner()
        设备 = ADB设备操作类(
            self._创建假MuMuADB(),
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
        runner = 假Runner(
            结果(b"List of devices attached\n127.0.0.1:16416 device product:a55x model:SM_A5560\n"),
            结果(b"FocusedWindows:\n  displayId=7, name='87ab31 com.supercell.clashofclans/com.supercell.titan.GameApp'\n"),
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
            结果(b"DisplayViewport{displayId=7, uniqueId='local:test', logicalFrame=Rect(0, 0 - 1280, 720)}"),
            结果(),
        )
        设备 = ADB设备操作类(
            self._创建假MuMuADB(),
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

    @staticmethod
    def _测试PNG字节(宽: int = 800, 高: int = 600) -> bytes:
        图像 = np.zeros((高, 宽, 3), dtype=np.uint8)
        编码成功, 编码 = cv2.imencode(".png", 图像)
        assert 编码成功
        return 编码.tobytes()

    def test_触控命令固定绑定选中序列号(self):
        runner = 假Runner(结果(在线模拟器), 结果(self._测试PNG字节(800, 600)), 结果())
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with self._内存充足():
            self.assertTrue(设备.触控(12, 34))
        self.assertEqual(runner.命令[-1][1:], ["-s", "emulator-5554", "shell", "input", "tap", "12", "34"])

    def test_ADB传输断线会重连后重试(self):
        runner = 假Runner(
            结果(在线模拟器),
            结果(self._测试PNG字节(800, 600)),
            结果(code=1, 错误=b"error: protocol fault (couldn't read status): connection reset"),
            结果(),
            结果(在线模拟器),
            结果(),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with self._内存充足():
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
            结果(self._测试PNG字节(1280, 720)),
            结果(),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with self._内存充足():
            self.assertTrue(设备.触控(12, 34))
        self.assertEqual(
            runner.命令[-1][1:],
            ["-s", "emulator-5554", "shell", "input", "tap", "19", "41"],
        )

    def test_ADB连续触控复用一次shell会话(self):
        runner = 假Runner(结果(在线模拟器), 结果(self._测试PNG字节(800, 600)), 结果())
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with self._内存充足():
            self.assertTrue(设备.连续触控([(12, 34), (12, 34)], 间隔毫秒=8))
        self.assertEqual(
            runner.命令[-1][1:],
             ["-s", "emulator-5554", "shell", "sh", "-c",
              "input tap 12 34; sleep 0.040; input tap 12 34"],
        )

    def test_ADB长按使用同点swipe(self):
        runner = 假Runner(结果(在线模拟器), 结果(self._测试PNG字节(800, 600)), 结果())
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with self._内存充足():
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
        # 默认请求原始像素；设备仍返回 PNG 时也能直接解码。
        self.assertEqual(runner.命令[1][1:], ["-s", "emulator-5554", "exec-out", "screencap"])

    def _原始截图字节(self, 图像BGR, 头长=16, 前缀=b""):
        高, 宽 = 图像BGR.shape[:2]
        RGBA = cv2.cvtColor(图像BGR, cv2.COLOR_BGR2RGBA)
        头 = np.array([宽, 高, 1] + ([0] if 头长 == 16 else []), dtype="<u4").tobytes()
        return 前缀 + 头 + RGBA.tobytes()

    def _内存充足(self):
        return patch.object(ADB设备操作类, "_获取主机内存状态", return_value={
            "内存负载": 50,
            "可用物理内存": 8 * 1024 * 1024 * 1024,
            "可用提交额度": 8 * 1024 * 1024 * 1024,
        })

    def test_screencap原始像素按新旧头长和前置警告都能解析(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        图像[50:100, 40:90] = (20, 100, 200)
        警告 = b"[Warning] Multiple displays were found, but no display id was specified!\n"
        for 头长, 前缀 in ((16, b""), (12, b""), (16, 警告)):
            with self.subTest(头长=头长, 有警告=bool(前缀)):
                runner = 假Runner(结果(在线模拟器), 结果(self._原始截图字节(图像, 头长, 前缀)))
                设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
                with self._内存充足():
                    结果图 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
                self.assertTrue(np.array_equal(结果图, 图像))
                self.assertFalse(设备._截图使用PNG)

    def test_原始截图无法解析时改用PNG重试且之后保持PNG(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        编码成功, 编码 = cv2.imencode(".png", 图像)
        self.assertTrue(编码成功)
        runner = 假Runner(
            结果(在线模拟器),
            结果(b"\x00" * 1000),
            结果(),
            结果(在线模拟器),
            结果(编码.tobytes()),
        )
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with self._内存充足():
            结果图 = 设备.获取屏幕图像cv()
        self.assertEqual(结果图.shape, (600, 800, 3))
        self.assertTrue(设备._截图使用PNG)
        self.assertEqual(runner.命令[-1][1:], ["-s", "emulator-5554", "exec-out", "screencap", "-p"])

    def test_MuMu未确认游戏显示层时拒绝退回启动器截图(self):
        设备 = ADB设备操作类(
            self._创建假MuMuADB(),
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
            self._创建假MuMuADB(),
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

    def test_公开内存预算查询识别低提交额度且不调用ADB(self):
        runner = 假Runner()
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        状态读取 = patch.object(
            设备,
            "_获取主机内存状态",
            return_value={
                "内存负载": 79,
                "可用物理内存": 6420 * 1024 * 1024,
                "可用提交额度": 828 * 1024 * 1024,
            },
        )
        with 状态读取 as 读取:
            健康, 诊断 = 设备.检查主机内存预算()

        self.assertFalse(健康)
        self.assertIn("主机内存保护", 诊断)
        读取.assert_called_once_with()
        self.assertEqual(runner.命令, [])

    def test_公开内存预算查询接受高于现有保护线且不调用ADB(self):
        runner = 假Runner()
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        状态读取 = patch.object(
            设备,
            "_获取主机内存状态",
            return_value={
                "内存负载": 70,
                "可用物理内存": 2048 * 1024 * 1024,
                "可用提交额度": 4096 * 1024 * 1024,
            },
        )
        with 状态读取 as 读取:
            健康, 诊断 = 设备.检查主机内存预算()

        self.assertTrue(健康)
        self.assertIn("可用提交额度", 诊断)
        读取.assert_called_once_with()
        self.assertEqual(runner.命令, [])

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

    def test_MuMu前台查询优先按窗口焦点而不是隐藏的CoC历史任务(self):
        runner = 假Runner(
            结果(
                b"""
FocusedWindows:
  displayId=0, name='d35c333 app.lawnchair/app.lawnchair.LawnchairLauncher'
"""
            ),
        )
        设备 = ADB设备操作类(
            ADB, "127.0.0.1:16416", runner=runner, 自动检测路径=False
        )
        设备.设置目标包名("com.supercell.clashofclans")
        self.assertEqual(设备.获取当前前台包名(), "app.lawnchair")

    def test_MuMu打开应用会切回窗口焦点不是CoC的显示层(self):
        runner = 假Runner(
            结果(
                b"List of devices attached\n"
                b"127.0.0.1:16416 device product:a55x model:SM_A5560\n"
            ),
            结果(
                b"""
FocusedWindows:
  displayId=0, name='d35c333 app.lawnchair/app.lawnchair.LawnchairLauncher'
"""
            ),
            结果(b"priority=0\ncom.supercell.clashofclans/.SplashActivity\n"),
            结果(),
        )
        设备 = ADB设备操作类(
            ADB, "127.0.0.1:16416", runner=runner, 自动检测路径=False
        )
        设备.设置目标包名("com.supercell.clashofclans")
        设备.打开应用("com.supercell.clashofclans")
        self.assertTrue(any("am" in 命令 and "start" in 命令 for 命令 in runner.命令))

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

    def test_建筑升级确认缺少标签或费用时不会误报成功(self):
        任务 = object.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: np.zeros((52, 140, 3), dtype=np.uint8)
            ),
            置脚本状态=lambda *_参数, **_关键字参数: None,
        )
        任务.执行OCR识别 = lambda _区域: []
        self.assertFalse(任务._升级确认按钮可用())

        任务.执行OCR识别 = lambda _区域: [
            ([[550, 490], [590, 490], [590, 515], [550, 515]], "確認", 0.99),
        ]
        self.assertFalse(任务._升级确认按钮可用())

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

    def test_wm_size竖屏但截图横屏时点击按截图尺寸映射(self):
        """BlueStacks Air 原生竖屏 wm size=1080x1920，但截图为横屏 1920x1080。"""
        class 竖屏WMRunner:
            def __init__(自身, png字节):
                自身.png字节 = png字节
                自身.命令 = []

            def __call__(自身, 命令, **_参数):
                自身.命令.append(命令)
                if 命令[1:] == ["devices", "-l"]:
                    return 结果(在线模拟器)
                if "screencap" in 命令:
                    return 结果(自身.png字节)
                if 命令[-2:] == ["wm", "size"]:
                    return 结果(b"Physical size: 1080x1920\n")
                return 结果()

        runner = 竖屏WMRunner(self._测试PNG字节(1920, 1080))
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        with self._内存充足():
            设备.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertEqual(设备.取屏幕尺寸(), (1920, 1080))
            self.assertTrue(设备.触控(400, 300))
        self.assertEqual(
            runner.命令[-1][1:],
            ["-s", "emulator-5554", "shell", "input", "tap", "960", "540"],
        )
        self.assertFalse(any(命令[-2:] == ["wm", "size"] for 命令 in runner.命令))

    def test_标记目标未验证后缓存命中与点击仍复用最近截图尺寸(self):
        class 缓存点击Runner:
            def __init__(自身, png字节):
                自身.png字节 = png字节
                自身.命令 = []

            def __call__(自身, 命令, **_参数):
                自身.命令.append(命令)
                if 命令[1:] == ["devices", "-l"]:
                    return 结果(在线模拟器)
                if "screencap" in 命令:
                    return 结果(自身.png字节)
                if 命令[-2:] == ["wm", "size"]:
                    return 结果(b"Physical size: 1080x1920\n")
                return 结果()

        runner = 缓存点击Runner(self._测试PNG字节(1920, 1080))
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner)
        屏幕 = ADB屏幕(设备)
        with self._内存充足():
            屏幕.获取屏幕图像cv(0, 0, 800, 600)
            # 模拟断连重连/确认在线清空 _屏幕尺寸，但 _最近截图尺寸 仍保留。
            设备._标记目标未验证()
            self.assertIsNone(设备._屏幕尺寸)
            self.assertEqual(设备._最近截图尺寸, (1920, 1080))
            # 命中 ADB屏幕 截图缓存，不会重新调用设备 screencap，同时应同步尺寸。
            屏幕.获取屏幕图像cv(0, 0, 800, 600)
            self.assertEqual(设备._屏幕尺寸, (1920, 1080))
            # 再次标记未验证后直接点击，不经过截图缓存也应优先用 _最近截图尺寸。
            设备._标记目标未验证()
            self.assertTrue(设备.触控(400, 300))
        self.assertEqual(
            runner.命令[-1][1:],
            ["-s", "emulator-5554", "shell", "input", "tap", "960", "540"],
        )
        self.assertFalse(any(命令[-2:] == ["wm", "size"] for 命令 in runner.命令))

    def test_非MuMu查询屏幕尺寸解析logicalFrame及旋转交换宽高(self):
        # 1) dumpsys display logicalFrame=Rect(...)
        runner1 = 假Runner(
            结果(b"DisplayViewport{type=INTERNAL, displayId=0, logicalFrame=Rect(0, 0 - 1920, 1080)}"),
        )
        设备1 = ADB设备操作类(ADB, "emulator-5554", runner=runner1)
        self.assertEqual(设备1.查询屏幕尺寸(), (1920, 1080))

        # 2) dumpsys input logicalFrame=[...]
        runner2 = 假Runner(
            结果(b"no viewport here"),
            结果(b"Viewport INTERNAL: displayId=0, orientation=1, logicalFrame=[0, 0, 1920, 1080]"),
        )
        设备2 = ADB设备操作类(ADB, "emulator-5554", runner=runner2)
        self.assertEqual(设备2.查询屏幕尺寸(), (1920, 1080))

        # 3) wm size=1080x1920 + dumpsys window rotation=1/3 交换宽高；rotation=0 保持原值
        for 旋转文本, 期望尺寸 in (
            (b"mCurrentRotation=ROTATION_90\n", (1920, 1080)),
            (b"mCurrentRotation=3\n", (1920, 1080)),
            (b"mCurrentRotation=ROTATION_0\n", (1080, 1920)),
        ):
            with self.subTest(旋转文本=旋转文本):
                runner3 = 假Runner(
                    结果(b""),
                    结果(b""),
                    结果(b"Physical size: 1080x1920\n"),
                    结果(旋转文本),
                )
                设备3 = ADB设备操作类(ADB, "emulator-5554", runner=runner3)
                self.assertEqual(设备3.查询屏幕尺寸(), 期望尺寸)

    def test_尺寸未知时点击和滑动前保守先截一帧拿到真实尺寸(self):
        png = self._测试PNG字节(1920, 1080)
        # 点击场景
        runner_tap = 假Runner(结果(在线模拟器), 结果(png), 结果())
        设备1 = ADB设备操作类(ADB, "emulator-5554", runner=runner_tap)
        self.assertIsNone(设备1._屏幕尺寸)
        self.assertIsNone(设备1._最近截图尺寸)
        with self._内存充足():
            self.assertTrue(设备1.触控(400, 300))
        self.assertEqual(runner_tap.命令[1][1:], ["-s", "emulator-5554", "exec-out", "screencap"])
        self.assertEqual(runner_tap.命令[2][1:], ["-s", "emulator-5554", "shell", "input", "tap", "960", "540"])

        # 滑动场景
        runner_swipe = 假Runner(结果(在线模拟器), 结果(png), 结果())
        设备2 = ADB设备操作类(ADB, "emulator-5554", runner=runner_swipe)
        with self._内存充足():
            self.assertTrue(设备2.滑动((200, 300), (600, 300), 300))
        self.assertEqual(runner_swipe.命令[1][1:], ["-s", "emulator-5554", "exec-out", "screencap"])
        self.assertEqual(
            runner_swipe.命令[2][1:],
            ["-s", "emulator-5554", "shell", "input", "swipe", "480", "540", "1440", "540", "300"],
        )

    def test_BlueStacks本机端口伪装三星通过特征白名单放行(self):
        # 方式1：getprop 含 ro.bluestacks.*
        bs列表 = b"List of devices attached\n127.0.0.1:5555 device product:dm3q model:SM_S908E device:dm3q\n"
        runner1 = 假Runner(
            结果(bs列表),
            结果(b"[ro.product.brand]: [samsung]\n[ro.bluestacks.version]: [5.21.100]\n"),
        )
        设备1 = ADB设备操作类(ADB, "127.0.0.1:5555", runner=runner1)
        在线1 = 设备1.确认在线()
        self.assertEqual(在线1.序列号, "127.0.0.1:5555")
        self.assertFalse(在线1.疑似实体设备)

        # 方式2：/data/.bluestacks.prop 存在
        bs列表2 = b"List of devices attached\nlocalhost:5555 device product:dm3q model:SM_S908E device:dm3q\n"
        runner2 = 假Runner(
            结果(bs列表2),
            结果(b"[ro.product.brand]: [samsung]\n"),
            结果(b"/data/.bluestacks.prop\n"),
        )
        设备2 = ADB设备操作类(ADB, "localhost:5555", runner=runner2)
        在线2 = 设备2.确认在线()
        self.assertEqual(在线2.序列号, "localhost:5555")
        self.assertFalse(在线2.疑似实体设备)

    def test_三星真机USB与无BlueStacks特征端口均仍被拦截(self):
        # USB 真机：不执行 getprop 探测，直接拦截
        runner_usb = 假Runner(
            结果(b"List of devices attached\nR58M9999999 device product:dm3q model:SM_S908E\n")
        )
        设备_usb = ADB设备操作类(ADB, "R58M9999999", runner=runner_usb)
        with self.assertRaisesRegex(ADB错误, "实体 Android 设备"):
            设备_usb.确认在线()
        self.assertEqual(len(runner_usb.命令), 1)

        # 局域网真机：不在 127.0.0.1/localhost，直接拦截
        runner_lan = 假Runner(
            结果(b"List of devices attached\n192.168.1.88:5555 device product:dm3q model:SM_S908E\n")
        )
        设备_lan = ADB设备操作类(ADB, "192.168.1.88:5555", runner=runner_lan)
        with self.assertRaisesRegex(ADB错误, "实体 Android 设备"):
            设备_lan.确认在线()
        self.assertEqual(len(runner_lan.命令), 1)

        # 本机 5555 端口转发但无 BlueStacks 特征的真机：探测失败后仍被拦截
        runner_fwd = 假Runner(
            结果(b"List of devices attached\n127.0.0.1:5555 device product:dm3q model:SM_S908E\n"),
            结果(b"[ro.product.brand]: [samsung]\n[ro.product.model]: [SM-S908E]\n"),
            结果(code=1, 错误=b"ls: /data/.bluestacks.prop: No such file or directory\n"),
        )
        设备_fwd = ADB设备操作类(ADB, "127.0.0.1:5555", runner=runner_fwd)
        with self.assertRaisesRegex(ADB错误, "实体 Android 设备"):
            设备_fwd.确认在线()

    def test_BlueStacks扫描探测按序列号缓存_不再重复调用getprop且支持失效(self):
        bs列表 = b"List of devices attached\n127.0.0.1:5555 device product:dm3q model:SM_S908E device:dm3q\n"
        # 第一次扫描触发 getprop，第二次扫描命中缓存，不再调用 getprop。
        runner = 假Runner(
            结果(bs列表),
            结果(b"[ro.product.brand]: [samsung]\n[ro.bluestacks.version]: [5.21.100]\n"),
            结果(bs列表),
        )
        首次 = ADB设备操作类.扫描设备(ADB, runner=runner)
        次次 = ADB设备操作类.扫描设备(ADB, runner=runner)
        self.assertFalse(首次[0].疑似实体设备)
        self.assertFalse(次次[0].疑似实体设备)
        getprop命令 = [命令 for 命令 in runner.命令 if 命令[-2:] == ["shell", "getprop"]]
        self.assertEqual(len(getprop命令), 1)
        self.assertEqual([命令[1:] for 命令 in runner.命令], [
            ["devices", "-l"],
            ["-s", "127.0.0.1:5555", "shell", "getprop"],
            ["devices", "-l"],
        ])

        # 显式清除缓存后，再次扫描应重新探测。
        ADB设备操作类.清除BlueStacks探测缓存("127.0.0.1:5555")
        runner_cleared = 假Runner(
            结果(bs列表),
            结果(b"[ro.product.brand]: [samsung]\n[ro.bluestacks.version]: [5.21.100]\n"),
        )
        清后 = ADB设备操作类.扫描设备(ADB, runner=runner_cleared)
        self.assertFalse(清后[0].疑似实体设备)
        self.assertEqual(
            len([命令 for 命令 in runner_cleared.命令 if 命令[-2:] == ["shell", "getprop"]]),
            1,
        )

        # 设备从扫描列表消失后缓存失效：随后同端口接入无 BlueStacks 特征的三星真机仍被拦截。
        runner_swap = 假Runner(
            结果(b"List of devices attached\n"),
            结果(bs列表),
            结果(b"[ro.product.brand]: [samsung]\n[ro.product.model]: [SM-S908E]\n"),
            结果(code=1, 错误=b"ls: /data/.bluestacks.prop: No such file or directory\n"),
        )
        self.assertEqual(ADB设备操作类.扫描设备(ADB, runner=runner_swap), [])
        设备_真机 = ADB设备操作类(ADB, "127.0.0.1:5555", runner=runner_swap)
        with self.assertRaisesRegex(ADB错误, "实体 Android 设备"):
            设备_真机.确认在线()

    def test_BlueStacks探测超时不缓存_恢复后下次扫描可重新探测放行(self):
        bs列表 = b"List of devices attached\n127.0.0.1:5555 device product:dm3q model:SM_S908E device:dm3q\n"
        调用次数 = {"getprop": 0}

        def 超时后恢复Runner(命令, **_参数):
            if 命令[1:] == ["devices", "-l"]:
                return 结果(bs列表)
            if 命令[-2:] == ["shell", "getprop"]:
                调用次数["getprop"] += 1
                if 调用次数["getprop"] == 1:
                    raise subprocess.TimeoutExpired(命令, 5)
                return 结果(b"[ro.product.brand]: [samsung]\n[ro.bluestacks.version]: [5.21.100]\n")
            return 结果()

        首次 = ADB设备操作类.扫描设备(ADB, runner=超时后恢复Runner)
        self.assertTrue(首次[0].疑似实体设备)
        次次 = ADB设备操作类.扫描设备(ADB, runner=超时后恢复Runner)
        self.assertFalse(次次[0].疑似实体设备)
        self.assertEqual(调用次数["getprop"], 2)

    def test_macOS候选ADB路径包含BlueStacksAir和MuMuMac版(self):
        with patch("模块.ADB设备操作类.sys.platform", "darwin"), \
                patch("模块.ADB设备操作类.shutil.which", return_value="/custom/bin/adb"):
            候选 = ADB设备操作类._候选ADB路径()
        路径列表 = [str(项) for 项 in 候选]
        路径集合 = set(路径列表)
        bs路径 = "/Applications/BlueStacks.app/Contents/MacOS/hd-adb"
        sdk路径 = str(Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb")
        path路径 = "/custom/bin/adb"
        mumu路径 = "/Applications/MuMuPlayer.app/Contents/MacOS/tools/adb"
        mumupro路径 = "/Applications/MuMuPlayerPro.app/Contents/MacOS/tools/adb"
        self.assertIn(bs路径, 路径集合)
        self.assertIn(sdk路径, 路径集合)
        self.assertIn(path路径, 路径集合)
        self.assertIn(mumu路径, 路径集合)
        self.assertIn(mumupro路径, 路径集合)
        # 严格校验优先级：BlueStacks > Android SDK > PATH > 其他 macOS 候选
        self.assertLess(路径列表.index(bs路径), 路径列表.index(sdk路径))
        self.assertLess(路径列表.index(sdk路径), 路径列表.index(path路径))
        self.assertLess(路径列表.index(path路径), 路径列表.index(mumu路径))

    def test_macOS查找ADB路径按优先级回退(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            根 = Path(临时目录)
            假BS = 根 / "BlueStacks" / "hd-adb"
            假SDK = 根 / "sdk" / "adb"
            假PATH = 根 / "path" / "adb"
            假MuMu = 根 / "mumu" / "adb"
            for 文件 in (假BS, 假SDK, 假PATH, 假MuMu):
                文件.parent.mkdir(parents=True, exist_ok=True)
                文件.write_text("#!/bin/sh\n", encoding="utf-8")

            with patch("模块.ADB设备操作类.sys.platform", "darwin"), \
                    patch.dict("os.environ", {"ANDROID_ADB": ""}, clear=False), \
                    patch("模块.ADB设备操作类.shutil.which", return_value=str(假PATH)), \
                    patch.object(
                        ADB设备操作类,
                        "_候选ADB路径",
                        return_value=[假BS, 假SDK, 假PATH, 假MuMu],
                    ):
                结果路径 = ADB设备操作类.查找ADB路径("", 自动检测=True)
            self.assertEqual(
                结果路径,
                [str(假BS.resolve()), str(假SDK.resolve()), str(假PATH.resolve()), str(假MuMu.resolve())],
            )

            # BlueStacks 不存在时回退到 SDK；SDK 也不存在时回退到 PATH
            假BS.unlink()
            with patch("模块.ADB设备操作类.sys.platform", "darwin"), \
                    patch.dict("os.environ", {"ANDROID_ADB": ""}, clear=False), \
                    patch("模块.ADB设备操作类.shutil.which", return_value=str(假PATH)), \
                    patch.object(
                        ADB设备操作类,
                        "_候选ADB路径",
                        return_value=[假BS, 假SDK, 假PATH, 假MuMu],
                    ):
                self.assertEqual(ADB设备操作类.解析ADB路径("", 自动检测=True), str(假SDK.resolve()))

            假SDK.unlink()
            with patch("模块.ADB设备操作类.sys.platform", "darwin"), \
                    patch.dict("os.environ", {"ANDROID_ADB": ""}, clear=False), \
                    patch("模块.ADB设备操作类.shutil.which", return_value=str(假PATH)), \
                    patch.object(
                        ADB设备操作类,
                        "_候选ADB路径",
                        return_value=[假BS, 假SDK, 假PATH, 假MuMu],
                    ):
                self.assertEqual(ADB设备操作类.解析ADB路径("", 自动检测=True), str(假PATH.resolve()))

    def test_POSIX无exe后缀adb路径下emulator别名可识别为MuMu(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            假adb = Path(临时目录) / "adb"
            假adb.write_text("#!/bin/sh\n", encoding="utf-8")
            runner = 假Runner(结果(
                b"DisplayDeviceInfo{mumuscreen001: uniqueId=local:4619827767814508545}"
            ))
            设备 = ADB设备操作类(str(假adb), "emulator-5556", runner=runner, 自动检测路径=False)
            self.assertTrue(设备._是MuMu连接())
            self.assertEqual(
                runner.命令[0][1:],
                ["-s", "emulator-5556", "shell", "dumpsys", "display"],
            )

    def test_BlueStacks本机端口断线后支持重连且局域网地址不自动重连(self):
        runner_bs = 假Runner(结果(b"connected to 127.0.0.1:5555"))
        设备_bs = ADB设备操作类(ADB, "127.0.0.1:5555", runner=runner_bs)
        设备_bs._连接已保存网络设备()
        self.assertEqual(len(runner_bs.命令), 1)
        self.assertEqual(runner_bs.命令[0][1:], ["connect", "127.0.0.1:5555"])

        runner_lan = 假Runner()
        设备_lan = ADB设备操作类(ADB, "192.168.1.5:5555", runner=runner_lan)
        设备_lan._连接已保存网络设备()
        self.assertEqual(runner_lan.命令, [])

    def test_解析逻辑视口优先跳过valid为false的旧视口(self):
        输出 = (
            "DisplayViewport{type=INTERNAL, valid=false, displayId=0, logicalFrame=Rect(0, 0 - 1080, 1920)}\n"
            "DisplayViewport{type=INTERNAL, valid=true, displayId=0, logicalFrame=Rect(0, 0 - 1920, 1080)}\n"
        )
        self.assertEqual(ADB设备操作类._解析逻辑视口尺寸(输出), (1920, 1080))


if __name__ == "__main__":
    unittest.main()
