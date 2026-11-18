import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 界面.设备连接面板 import 设备连接面板


class 设备连接面板测试(unittest.TestCase):
    def test_连接截图使用机器人配置的CoC包名解析MuMu显示层(self):
        面板 = 设备连接面板.__new__(设备连接面板)
        面板.设备序列号 = SimpleNamespace(get=Mock(return_value="127.0.0.1:16416"))
        面板.设备已确认 = SimpleNamespace(get=Mock(return_value=True))
        面板.adb路径 = SimpleNamespace(get=Mock(return_value="adb.exe"))
        面板.自动检测路径 = SimpleNamespace(get=Mock(return_value=True))
        面板.当前机器人ID = "robot_1"
        面板.数据库 = SimpleNamespace(
            获取机器人设置=Mock(return_value=SimpleNamespace(
                部落冲突包名="com.supercell.clashofclans"
            ))
        )
        设备 = Mock()

        with patch("界面.设备连接面板.ADB设备操作类", return_value=设备):
            self.assertIs(面板._取已确认设备(), 设备)

        设备.设置目标包名.assert_called_once_with("com.supercell.clashofclans")
        设备.确认在线.assert_called_once_with()

    def test_无机器人配置时使用国际服CoC包名(self):
        面板 = 设备连接面板.__new__(设备连接面板)
        面板.设备序列号 = SimpleNamespace(get=Mock(return_value="127.0.0.1:16416"))
        面板.设备已确认 = SimpleNamespace(get=Mock(return_value=True))
        面板.adb路径 = SimpleNamespace(get=Mock(return_value="adb.exe"))
        面板.自动检测路径 = SimpleNamespace(get=Mock(return_value=True))
        面板.当前机器人ID = None
        设备 = Mock()

        with patch("界面.设备连接面板.ADB设备操作类", return_value=设备):
            self.assertIs(面板._取已确认设备(), 设备)

        设备.设置目标包名.assert_not_called()
        设备.确认在线.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
