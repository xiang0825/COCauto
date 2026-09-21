import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 任务流程.启动模拟器 import 启动模拟器任务


class 启动模拟器状态测试(unittest.TestCase):
    def _上下文(self, 设备):
        日志 = []
        设置 = SimpleNamespace(部落冲突包名="com.supercell.clashofclans")
        上下文 = SimpleNamespace(
            机器人标志="robot_test",
            数据库=SimpleNamespace(获取机器人设置=Mock(return_value=设置)),
            雷电模拟器=设备,
            置脚本状态=lambda 文本, *_参数, **_关键字: 日志.append(文本),
            脚本延时=Mock(),
        )
        return 上下文, 日志

    def test_已在前台运行时复用现有游戏实例(self):
        设备 = Mock()
        设备.是否已启动.return_value = True
        设备.获取当前前台包名.return_value = "com.supercell.clashofclans"
        上下文, 日志 = self._上下文(设备)

        self.assertTrue(启动模拟器任务(上下文).执行())
        设备.打开应用.assert_called_once_with("com.supercell.clashofclans")
        self.assertTrue(any("复用当前游戏实例" in 文本 for 文本 in 日志))
        上下文.脚本延时.assert_not_called()

    def test_启动后等待前台确认而不是立即误判未开启(self):
        设备 = Mock()
        设备.是否已启动.return_value = True
        设备.获取当前前台包名.side_effect = ["app.lawnchair", "app.lawnchair", "com.supercell.clashofclans"]
        上下文, 日志 = self._上下文(设备)

        self.assertTrue(启动模拟器任务(上下文).执行())
        self.assertGreaterEqual(上下文.脚本延时.call_count, 2)
        self.assertTrue(any("进入前台" in 文本 for 文本 in 日志))


if __name__ == "__main__":
    unittest.main()
