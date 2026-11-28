"""MAA 式模拟器一键检测测试（全部使用假数据，不连接真实模拟器）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from 模块 import 模拟器探测 as 探测
from 模块.ADB设备操作类 import ADB设备操作类, ADB错误

ADB = sys.executable
包名 = "com.supercell.clashofclans"


def 结果(输出=b"", code=0, 错误=b""):
    return SimpleNamespace(returncode=code, stdout=输出, stderr=错误)


class 假ADB:
    """按命令返回预设结果，并记录 adb connect 的地址。"""

    def __init__(self, 设备列表: bytes, 前台: set[str], 已安装: set[str]):
        self.设备列表 = 设备列表
        self.前台 = 前台
        self.已安装 = 已安装
        self.连接 = []

    def __call__(self, 命令, **_参数):
        if 命令[1:2] == ["connect"]:
            self.连接.append(命令[2])
            return 结果(f"connected to {命令[2]}".encode())
        if 命令[1:] == ["devices", "-l"]:
            return 结果(self.设备列表)
        序列号 = 命令[2] if len(命令) > 2 and 命令[1] == "-s" else ""
        if 命令[-3:] == ["list", "packages", 包名]:
            return 结果(f"package:{包名}\n".encode() if 序列号 in self.已安装 else b"")
        if 命令[-2:] == ["getprop", "ro.serialno"]:
            return 结果(f"id-{序列号}\n".encode())
        if 序列号 in self.前台:
            return 结果((
                f"FocusedWindows:\n  displayId=4, name='87ab31 {包名}/com.supercell.titan.GameApp'\n"
                f"topResumedActivity=ActivityRecord{{1 u0 {包名}/.GameApp t1}}\n"
            ).encode())
        return 结果(b"topResumedActivity=ActivityRecord{1 u0 app.launcher/.Main t1}\n")


class 发现测试(unittest.TestCase):
    def _MuMu目录(self, 根: Path, 端口: int = 16416) -> Path:
        目录 = 根 / "MuMuPlayer"
        (目录 / "nx_main").mkdir(parents=True)
        (目录 / "nx_main" / "adb.exe").write_bytes(b"")
        配置 = 目录 / "vms" / "MuMuPlayerGlobal-15.0-1" / "configs"
        配置.mkdir(parents=True)
        (配置 / "vm_config.json").write_text(json.dumps(
            {"vm": {"nat": {"port_forward": {"adb": {"host_port": str(端口)}}}}}
        ), encoding="utf-8")
        return 目录

    def test_注册表和运行进程合并并找到自带adb(self):
        with tempfile.TemporaryDirectory() as 临时:
            目录 = self._MuMu目录(Path(临时))
            结果列表 = 探测.发现模拟器(
                注册表来源=lambda: [("MuMu", 目录)],
                进程来源=lambda: [目录 / "nx_device" / "15.0" / "shell" / "MuMuNxDevice.exe"],
            )
        self.assertEqual(len(结果列表), 1)
        self.assertTrue(结果列表[0].运行中)
        self.assertTrue(结果列表[0].adb路径.endswith("adb.exe"))

    def test_MuMu从实例配置读取真实端口且排在默认端口前(self):
        with tempfile.TemporaryDirectory() as 临时:
            目录 = self._MuMu目录(Path(临时), 16448)
            安装 = 探测.模拟器安装("MuMu", 目录, str(目录 / "nx_main" / "adb.exe"), True)
            候选 = 探测.收集候选地址([安装], runner=lambda *_a, **_k: 结果(b""))
        self.assertEqual(候选[0].地址, "127.0.0.1:16448")
        self.assertIn("127.0.0.1:16384", [项.地址 for 项 in 候选])
        self.assertNotIn("127.0.0.1:5555", [项.地址 for 项 in 候选])

    def test_MuMuManager运行中实例端口(self):
        with tempfile.TemporaryDirectory() as 临时:
            目录 = Path(临时)
            (目录 / "nx_main").mkdir()
            (目录 / "nx_main" / "MuMuManager.exe").write_bytes(b"")
            输出 = json.dumps({"0": {"index": "0", "name": "主号", "is_android_started": True,
                                    "adb_host_ip": "10.0.2.15", "adb_port": 16384}}).encode()
            候选 = 探测.MuMu候选地址(目录, runner=lambda *_a, **_k: 结果(输出))
        self.assertEqual(候选[0].地址, "127.0.0.1:16384")
        self.assertTrue(候选[0].运行中)
        self.assertIn("主号", 候选[0].说明)

    def test_蓝叠配置端口(self):
        with tempfile.TemporaryDirectory() as 临时:
            配置 = Path(临时) / "bluestacks.conf"
            配置.write_text('bst.instance.Pie64.status.adb_port="5565"\n', encoding="utf-8")
            候选 = 探测.蓝叠候选地址([配置])
        self.assertEqual([项.地址 for 项 in 候选], ["127.0.0.1:5565"])

    def test_macOS默认查找BlueStacks共享目录配置(self):
        with tempfile.TemporaryDirectory() as 临时:
            假家目录 = Path(临时)
            用户配置 = 假家目录 / "Library" / "Application Support" / "BlueStacks" / "bluestacks.conf"
            用户配置.parent.mkdir(parents=True)
            用户配置.write_text('bst.instance.Tiramisu64.status.adb_port="5555"\n', encoding="utf-8")
            with patch("模块.模拟器探测.sys.platform", "darwin"), \
                    patch("模块.模拟器探测.Path.home", return_value=假家目录):
                候选 = 探测.蓝叠候选地址()
        self.assertIn("127.0.0.1:5555", [项.地址 for 项 in 候选])

    def test_没发现模拟器时尝试全部常见端口(self):
        地址 = [项.地址 for 项 in 探测.收集候选地址([])]
        for 端口 in (16384, 5555, 62001, 21503):
            self.assertIn(f"127.0.0.1:{端口}", 地址)


class 检测流程测试(unittest.TestCase):
    def _检测(self, adb: 假ADB, 监听: set[str]):
        with patch.object(ADB设备操作类, "解析ADB路径", return_value=ADB):
            return 探测.检测(
                包名, ADB,
                发现=lambda: [],
                端口探测=lambda 地址: 地址 in 监听,
                runner=adb,
            )

    def test_只连接正在监听的端口并推荐游戏在前台的实例(self):
        adb = 假ADB(
            b"List of devices attached\n127.0.0.1:16384 device model:MuMu\n127.0.0.1:16416 device model:MuMu\n",
            前台={"127.0.0.1:16416"}, 已安装={"127.0.0.1:16384", "127.0.0.1:16416"},
        )
        结果对象 = self._检测(adb, {"127.0.0.1:16384", "127.0.0.1:16416"})
        self.assertEqual(sorted(adb.连接), ["127.0.0.1:16384", "127.0.0.1:16416"])
        self.assertEqual(结果对象.推荐.序列号, "127.0.0.1:16416")
        self.assertEqual(结果对象.推荐.类型, "MuMu")
        self.assertEqual(sum(1 for 项 in 结果对象.条目 if 项.推荐), 1)

    def test_并列时不推荐(self):
        adb = 假ADB(
            b"List of devices attached\n127.0.0.1:16384 device\n127.0.0.1:16416 device\n",
            前台=set(), 已安装={"127.0.0.1:16384", "127.0.0.1:16416"},
        )
        结果对象 = self._检测(adb, set())
        self.assertIsNone(结果对象.推荐)
        self.assertEqual(len(结果对象.条目), 2)
        with patch.object(ADB设备操作类, "解析ADB路径", return_value=ADB), self.assertRaises(ADB错误):
            探测.检测并选择(包名, ADB, 发现=lambda: [], 端口探测=lambda _地址: False, runner=adb)

    def test_未安装游戏不推荐(self):
        adb = 假ADB(b"List of devices attached\nemulator-5554 device\n", 前台=set(), 已安装=set())
        结果对象 = self._检测(adb, set())
        self.assertIsNone(结果对象.推荐)
        self.assertEqual(结果对象.条目[0].类型, "模拟器")

    def test_实体手机被排除(self):
        adb = 假ADB(
            b"List of devices attached\nR58M1234567 device model:SM_A5560 product:a55xchn\n",
            前台={"R58M1234567"}, 已安装={"R58M1234567"},
        )
        结果对象 = self._检测(adb, set())
        self.assertEqual(结果对象.条目, [])
        self.assertTrue(any("实体手机" in 行 for 行 in 结果对象.日志))

    def test_选择adb优先运行中的模拟器(self):
        已发现 = [
            探测.模拟器安装("雷电", Path("ld"), "ld/adb.exe", False),
            探测.模拟器安装("MuMu", Path("mumu"), "mumu/adb.exe", True),
        ]
        self.assertEqual(探测.选择adb路径(已发现), "mumu/adb.exe")


if __name__ == "__main__":
    unittest.main()
