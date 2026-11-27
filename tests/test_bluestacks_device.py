"""BlueStacks（macOS BlueStacks Air）纯 ADB 设备实现与跨平台小工具的单测。"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from 模块 import 平台
from 模块.ADB设备操作类 import ADB设备操作类, ADB错误
from 模块.BlueStacks设备 import (
    BlueStacks设备,
    原始触摸坐标,
    生成双指捏合脚本,
    解析触摸设备列表,
)
from 模块.设备接口 import 创建游戏设备, 游戏设备, 规范化模拟器类型

ADB = sys.executable
在线蓝叠 = b"List of devices attached\n127.0.0.1:5555 device product:BlueStacks model:BlueStacks\n"

GETEVENT输出 = """add device 1: /dev/input/event4
  name:     "BlueStacks Virtual Keyboard"
  events:
    KEY (0001): KEY_ESC KEY_1
  input props:
    <none>
add device 2: /dev/input/event2
  name:     "BlueStacks Touch"
  events:
    KEY (0001): BTN_TOUCH
    ABS (0003): ABS_MT_SLOT           : value 0, min 0, max 9, fuzz 0, flat 0, resolution 0
                ABS_MT_TRACKING_ID    : value 0, min 0, max 65535, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_X     : value 0, min 0, max 32767, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_Y     : value 0, min 0, max 32767, fuzz 0, flat 0, resolution 0
  input props:
    INPUT_PROP_DIRECT
add device 3: /dev/input/event3
  name:     "virtio_input_multi_touch_1"
  events:
    ABS (0003): ABS_MT_POSITION_X     : value 0, min 0, max 1279, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_Y     : value 0, min 0, max 719, fuzz 0, flat 0, resolution 0
  input props:
    <none>
"""


class 假Runner:
    def __init__(self, *响应):
        self.响应 = list(响应)
        self.命令 = []

    def __call__(self, 命令, **参数):
        self.命令.append(命令)
        if self.响应:
            return self.响应.pop(0)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


def 结果(输出=b"", code=0, 错误=b""):
    return SimpleNamespace(returncode=code, stdout=输出, stderr=错误)


def 内存充足():
    return patch.object(ADB设备操作类, "_获取主机内存状态", return_value={
        "内存负载": 50,
        "可用物理内存": 8 * 1024 ** 3,
        "可用提交额度": 8 * 1024 ** 3,
    })


class 触摸解析测试(unittest.TestCase):
    def test_优先选择支持slot的直接触摸设备(self):
        列表 = 解析触摸设备列表(GETEVENT输出)
        self.assertEqual([项.路径 for 项 in 列表], ["/dev/input/event2", "/dev/input/event3"])
        首选 = 列表[0]
        self.assertEqual((首选.最大x, 首选.最大y), (32767, 32767))
        self.assertTrue(首选.支持多点槽位)
        self.assertTrue(首选.直接触摸)
        self.assertFalse(列表[1].支持多点槽位)

    def test_空输出与无触摸设备(self):
        self.assertEqual(解析触摸设备列表(""), [])
        self.assertEqual(解析触摸设备列表("add device 1: /dev/input/event1\n  name: \"kbd\"\n"), [])

    def test_坐标换算含旋转(self):
        self.assertEqual(原始触摸坐标(0, 0, 1280, 720, 32767, 32767), (0, 0))
        self.assertEqual(原始触摸坐标(1280, 720, 1280, 720, 32767, 32767), (32767, 32767))
        self.assertEqual(原始触摸坐标(640, 360, 1280, 720, 1279, 719), (640, 360))
        # 旋转 90：屏幕左下角 → 原始 (max, max)
        self.assertEqual(原始触摸坐标(0, 720, 1280, 720, 100, 100, 90), (100, 100))
        self.assertEqual(原始触摸坐标(0, 0, 1280, 720, 100, 100, 270), (100, 0))

    def test_捏合脚本是双指向内且成对抬起(self):
        脚本 = 生成双指捏合脚本("/dev/input/event2", 32767, 32767, 1280, 720, 次数=2)
        self.assertIn("sendevent /dev/input/event2 3 47 0", 脚本)
        self.assertIn("sendevent /dev/input/event2 3 47 1", 脚本)
        self.assertIn("sendevent /dev/input/event2 3 57 200", 脚本)
        self.assertIn("sendevent /dev/input/event2 3 57 203", 脚本)
        self.assertEqual(脚本.count("sendevent /dev/input/event2 1 330 1"), 2)
        self.assertEqual(脚本.count("sendevent /dev/input/event2 1 330 0"), 2)
        self.assertEqual(脚本.count("3 57 -1"), 4)
        # 第一根手指 X 从 0.35 宽向 0.445 宽靠近中心
        起 = round(0.35 * 32767)
        self.assertIn(f"sendevent /dev/input/event2 3 53 {起}", 脚本)
        self.assertNotIn("keyevent", 脚本)

    def test_非法设备路径拒绝生成(self):
        with self.assertRaises(ValueError):
            生成双指捏合脚本("/dev/input/event2; reboot", 100, 100, 1280, 720)


class BlueStacks设备测试(unittest.TestCase):
    def setUp(self):
        ADB设备操作类._全局最近ADB服务重置时间 = 0.0

    def test_永远不当作MuMu也不加载MuMu高速截图(self):
        设备 = BlueStacks设备(ADB, "127.0.0.1:16384", runner=假Runner())
        self.assertFalse(设备._是MuMu连接())
        self.assertIsNone(设备._获取高速截图器())
        self.assertEqual(设备._runner.命令, [])

    def test_截图走ADB原始像素且不探测mumuscreen(self):
        图像 = np.zeros((720, 1280, 3), dtype=np.uint8)
        图像[100:200, 300:400] = (10, 120, 230)
        RGBA = cv2.cvtColor(图像, cv2.COLOR_BGR2RGBA)
        原始 = np.array([1280, 720, 1, 0], dtype="<u4").tobytes() + RGBA.tobytes()
        runner = 假Runner(结果(在线蓝叠), 结果(原始))
        设备 = BlueStacks设备(ADB, "127.0.0.1:5555", runner=runner)
        with 内存充足():
            画面 = 设备.获取屏幕图像cv()
        self.assertEqual(画面.shape, (720, 1280, 3))
        self.assertEqual(tuple(int(v) for v in 画面[150, 350]), (10, 120, 230))
        self.assertEqual(runner.命令[1][1:], ["-s", "127.0.0.1:5555", "exec-out", "screencap"])
        self.assertFalse(any("dumpsys" in 命令 for 命令 in runner.命令))

    def test_点击与滑动走通用input命令(self):
        runner = 假Runner()
        设备 = BlueStacks设备(ADB, "127.0.0.1:5555", runner=runner)
        设备._目标已验证 = True
        设备._屏幕尺寸 = (1600, 1200)
        设备.触控(400, 300)
        设备.滑动((100, 100), (200, 100), 300)
        self.assertEqual(runner.命令[0][1:], ["-s", "127.0.0.1:5555", "shell", "input", "tap", "800", "600"])
        self.assertEqual(
            runner.命令[1][1:],
            ["-s", "127.0.0.1:5555", "shell", "input", "swipe", "200", "200", "400", "200", "300"],
        )

    def _缩放设备(self, *响应):
        runner = 假Runner(*响应)
        设备 = BlueStacks设备(ADB, "127.0.0.1:5555", runner=runner, 触摸旋转=0)
        设备._目标已验证 = True
        设备._屏幕尺寸 = (1280, 720)
        return 设备, runner

    def test_拉远视距先探测再注入双指捏合(self):
        设备, runner = self._缩放设备(
            结果(GETEVENT输出.encode()), 结果(b"COC_SENDEVENT_OK\n"), 结果(b""),
        )
        self.assertTrue(设备.游戏内拉远视距(1))
        self.assertEqual(runner.命令[0][3:], ["shell", "getevent", "-lp"])
        self.assertIn("sendevent /dev/input/event2 0 0 0 && echo COC_SENDEVENT_OK", runner.命令[1][-1])
        self.assertIn("sendevent /dev/input/event2 3 57 200", runner.命令[2][-1])
        # 第二次复用缓存的触摸设备和写权限，只发手势。
        设备.游戏内拉远视距(1)
        self.assertEqual(len(runner.命令), 4)
        self.assertIn("3 57 200", runner.命令[3][-1])

    def test_没有多点触摸设备时拒绝发送任何输入(self):
        仅单点 = "add device 1: /dev/input/event3\n  name: \"x\"\n" \
                 "    ABS (0003): ABS_MT_POSITION_X : value 0, min 0, max 10\n" \
                 "                ABS_MT_POSITION_Y : value 0, min 0, max 10\n"
        设备, runner = self._缩放设备(结果(仅单点.encode()))
        with self.assertRaises(ADB错误):
            设备.游戏内拉远视距(1)
        self.assertFalse(any("sendevent" in " ".join(命令) for 命令 in runner.命令))

    def test_sendevent无权限时报错且不发手势(self):
        设备, runner = self._缩放设备(
            结果(GETEVENT输出.encode()), 结果(b"could not open /dev/input/event2, Permission denied\n"),
        )
        with self.assertRaisesRegex(ADB错误, "不可写"):
            设备.游戏内拉远视距(1)
        self.assertEqual(len(runner.命令), 2)


class 设备工厂测试(unittest.TestCase):
    def test_类型规范化(self):
        self.assertEqual(规范化模拟器类型(""), "auto")
        self.assertEqual(规范化模拟器类型("BlueStacks Air"), "bluestacks")
        self.assertEqual(规范化模拟器类型("蓝叠"), "bluestacks")
        self.assertEqual(规范化模拟器类型("MuMu"), "mumu")
        with self.assertRaises(ValueError):
            规范化模拟器类型("夜神")

    def test_按类型创建实现(self):
        蓝叠 = 创建游戏设备("bluestacks", ADB, "127.0.0.1:5555", runner=假Runner())
        默认 = 创建游戏设备("auto", ADB, "127.0.0.1:16384", runner=假Runner())
        self.assertIsInstance(蓝叠, BlueStacks设备)
        self.assertIs(type(默认), ADB设备操作类)
        self.assertIsInstance(蓝叠, 游戏设备)
        self.assertIsInstance(默认, 游戏设备)


class 伪装型号与类型选择测试(unittest.TestCase):
    def test_本机回环的伪装型号被标注为蓝叠_局域网和USB不放宽(self):
        from 模块.ADB设备操作类 import ADB设备信息
        from 模块.BlueStacks设备 import 标注本机蓝叠
        回环 = ADB设备信息("127.0.0.1:5555", "device", "product:SM-S908E model:SM_S908E")
        模拟 = ADB设备信息("emulator-5554", "device", "model:SM_S908E")
        局域网 = ADB设备信息("192.168.1.20:5555", "device", "model:SM_S908E")
        USB = ADB设备信息("R58M1234567", "device", "model:SM_S908E")
        self.assertTrue(回环.疑似实体设备)
        self.assertFalse(标注本机蓝叠(回环).疑似实体设备)
        self.assertIs(标注本机蓝叠(模拟), 模拟)
        self.assertTrue(标注本机蓝叠(局域网).疑似实体设备)
        self.assertTrue(标注本机蓝叠(USB).疑似实体设备)

    def test_BlueStacks设备确认在线接受伪装型号的本机端口(self):
        runner = 假Runner(结果(b"List of devices attached\n127.0.0.1:5555 device product:SM-S908E model:SM_S908E\n"))
        设备 = BlueStacks设备(ADB, "127.0.0.1:5555", runner=runner)
        self.assertEqual(设备.确认在线().序列号, "127.0.0.1:5555")
        普通 = ADB设备操作类(ADB, "127.0.0.1:5555", runner=假Runner(
            结果(b"List of devices attached\n127.0.0.1:5555 device product:SM-S908E model:SM_S908E\n")))
        with self.assertRaisesRegex(ADB错误, "实体"):
            普通.确认在线()

    def test_选择设备类按平台和设置(self):
        from 模块.设备接口 import 选择设备类, 解析生效模拟器类型
        with patch.dict("os.environ", {"COC_EMULATOR_TYPE": ""}):
            self.assertIs(选择设备类("auto", ADB设备操作类, "win32"), ADB设备操作类)
            self.assertIs(选择设备类("", ADB设备操作类, "win32"), ADB设备操作类)
            self.assertIs(选择设备类("mumu", ADB设备操作类, "darwin"), ADB设备操作类)
            self.assertIs(选择设备类("auto", ADB设备操作类, "darwin"), BlueStacks设备)
            self.assertIs(选择设备类("bluestacks", ADB设备操作类, "win32"), BlueStacks设备)
            self.assertEqual(解析生效模拟器类型("乱写", "win32"), "mumu")
        with patch.dict("os.environ", {"COC_EMULATOR_TYPE": "bluestacks"}):
            self.assertIs(选择设备类("auto", ADB设备操作类, "win32"), BlueStacks设备)

    def test_设置默认auto(self):
        from 数据库.任务数据库 import 机器人设置
        self.assertEqual(机器人设置().模拟器类型, "auto")


class 平台工具测试(unittest.TestCase):
    def test_平台识别与adb名(self):
        self.assertEqual(平台.当前平台("win32"), "windows")
        self.assertEqual(平台.当前平台("darwin"), "macos")
        self.assertEqual(平台.当前平台("linux"), "linux")
        self.assertEqual(平台.adb可执行名("win32"), "adb.exe")
        self.assertEqual(平台.adb可执行名("darwin"), "adb")

    def test_macOS候选包含蓝叠Air和Homebrew(self):
        候选 = [p.as_posix() for p in 平台.macOS候选ADB路径(Path("/Users/u"), 环境={"ANDROID_HOME": "/sdk"})]
        self.assertIn("/Applications/BlueStacks.app/Contents/MacOS/hd-adb", 候选)
        self.assertIn("/opt/homebrew/bin/adb", 候选)
        self.assertIn("/Users/u/Library/Android/sdk/platform-tools/adb", 候选)
        self.assertIn("/sdk/platform-tools/adb", 候选)

    def test_用户数据目录(self):
        家 = Path("/Users/u")
        self.assertEqual(
            平台.用户数据目录("COCauto", "darwin", 家, {}).as_posix(),
            "/Users/u/Library/Application Support/COCauto",
        )
        self.assertEqual(
            平台.用户数据目录("COCauto", "win32", 家, {"LOCALAPPDATA": "C:/L"}).as_posix(),
            "C:/L/COCauto",
        )

    def test_mac上ADB候选走macOS列表_Windows列表不变(self):
        with patch.object(sys, "platform", "darwin"):
            mac候选 = [p.as_posix() for p in ADB设备操作类._候选ADB路径()]
        self.assertIn("/opt/homebrew/bin/adb", mac候选)
        self.assertFalse(any(p.endswith(".exe") for p in mac候选))
        if sys.platform == "win32":
            win候选 = [str(p) for p in ADB设备操作类._候选ADB路径()]
            self.assertTrue(any(p.endswith("HD-Adb.exe") for p in win候选))
            self.assertFalse(any("homebrew" in p for p in win候选))

    def test_mac上读取蓝叠配置端口(self):
        from 模块 import 模拟器探测
        import tempfile
        with tempfile.TemporaryDirectory() as 目录:
            配置 = Path(目录) / "bluestacks.conf"
            配置.write_text('bst.instance.Pie64.status.adb_port="5555"\n', encoding="utf-8")
            with patch.object(sys, "platform", "darwin"), \
                    patch("模块.平台.macOS蓝叠配置路径", return_value=(配置,)):
                候选 = 模拟器探测.蓝叠候选地址()
        self.assertEqual([项.地址 for 项 in 候选], ["127.0.0.1:5555"])


if __name__ == "__main__":
    unittest.main()
