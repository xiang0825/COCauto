import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 应用.设备服务 import 设备服务, 连接表单
from 模块.ADB设备操作类 import ADB错误


class 设备服务测试(unittest.TestCase):
    def test_扫描前只重连已保存的本机ADB设备(self):
        with patch(
            "应用.设备服务.ADB设备操作类.解析ADB路径",
            return_value="C:/MuMu/adb.exe",
        ), patch(
            "应用.设备服务.ADB设备操作类.连接网络设备",
            return_value="connected",
        ) as 连接, patch(
            "应用.设备服务.ADB设备操作类.扫描设备",
            return_value=[],
        ) as 扫描:
            结果 = 设备服务.扫描("adb.exe", False, "127.0.0.1:16416")

        连接.assert_called_once_with("C:/MuMu/adb.exe", "127.0.0.1:16416", 自动检测路径=False)
        扫描.assert_called_once_with("C:/MuMu/adb.exe", 自动检测路径=False)
        self.assertEqual((结果.adb路径, 结果.设备), ("C:/MuMu/adb.exe", ()))

    def test_非本机地址不会被自动重连(self):
        with patch("应用.设备服务.ADB设备操作类.解析ADB路径", return_value="adb"), patch(
            "应用.设备服务.ADB设备操作类.连接网络设备",
        ) as 连接, patch("应用.设备服务.ADB设备操作类.扫描设备", return_value=[]):
            设备服务.扫描("adb", False, "emulator-5554")
        连接.assert_not_called()

    def _表单(self, 已确认=True, 序列号="127.0.0.1:16416"):
        return 连接表单("adb.exe", True, 序列号, 已确认)

    def test_连接截图使用机器人配置的CoC包名解析MuMu显示层(self):
        数据库 = SimpleNamespace(获取机器人设置=Mock(return_value=SimpleNamespace(
            部落冲突包名="com.supercell.clashofclans.custom"
        )))
        设备 = Mock()
        with patch("应用.设备服务.ADB设备操作类", return_value=设备):
            设备服务(数据库).测试截图("robot_1", self._表单())
        设备.设置目标包名.assert_called_once_with("com.supercell.clashofclans.custom")
        设备.确认在线.assert_called_once_with()
        设备.获取屏幕图像cv.assert_called_once()

    def test_无机器人配置时使用国际服CoC包名(self):
        设备 = Mock()
        with patch("应用.设备服务.ADB设备操作类", return_value=设备):
            设备服务(Mock()).测试截图(None, self._表单())
        设备.设置目标包名.assert_called_once_with("com.supercell.clashofclans")

    def test_未确认模拟器时拒绝截图(self):
        with patch("应用.设备服务.ADB设备操作类") as 设备类:
            with self.assertRaises(ADB错误):
                设备服务(Mock()).测试截图(None, self._表单(已确认=False))
            with self.assertRaises(ADB错误):
                设备服务(Mock()).测试截图(None, self._表单(序列号=""))
        设备类.assert_not_called()

    def test_保存时只有选了设备才记为已确认(self):
        设置 = SimpleNamespace(ADB路径="", ADB自动检测路径=True, ADB设备序列号="", ADB已确认模拟器=False)
        数据库 = SimpleNamespace(获取机器人设置=Mock(return_value=设置), 保存机器人设置=Mock())
        设备服务(数据库).保存("robot_1", 连接表单("adb.exe", False, "", False))
        self.assertFalse(设置.ADB已确认模拟器)
        with patch("应用.设备服务.ADB设备操作类.解析ADB路径", return_value="C:/adb.exe"):
            路径 = 设备服务(数据库).保存("robot_1", 连接表单("adb.exe", False, "emulator-5554", True))
        self.assertEqual(路径, "C:/adb.exe")
        self.assertTrue(设置.ADB已确认模拟器)
        self.assertEqual(设置.ADB设备序列号, "emulator-5554")


if __name__ == "__main__":
    unittest.main()
