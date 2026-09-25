import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 主入口 import 机器人监控中心


class 机器人设备唯一性测试(unittest.TestCase):
    def _中心(self, 当前停止=False):
        中心 = 机器人监控中心.__new__(机器人监控中心)
        中心.机器人池 = {
            "robot_1": SimpleNamespace(
                停止事件=threading.Event(),
                启动=Mock(),
            ),
            "robot_2": SimpleNamespace(
                停止事件=threading.Event(),
                启动=Mock(),
            ),
        }
        if 当前停止:
            中心.机器人池["robot_1"].停止事件.set()
        设置 = {
            "robot_1": SimpleNamespace(ADB设备序列号="127.0.0.1:16416"),
            "robot_2": SimpleNamespace(ADB设备序列号="127.0.0.1:16416"),
        }
        中心.数据库 = SimpleNamespace(
            获取机器人设置=lambda 标志: 设置[标志]
        )
        return 中心

    def test_同一ADB设备被运行中机器人占用时拒绝启动(self):
        中心 = self._中心()

        with self.assertRaisesRegex(RuntimeError, "已被机器人\[robot_1\]占用"):
            中心.启动机器人("robot_2")

        中心.机器人池["robot_2"].启动.assert_not_called()

    def test_原机器人已停止后允许另一个机器人接管(self):
        中心 = self._中心(当前停止=True)

        中心.启动机器人("robot_2")

        中心.机器人池["robot_2"].启动.assert_called_once_with()

    def test_没有设备序列号时不阻断机器人创建(self):
        中心 = self._中心()
        中心.数据库.获取机器人设置 = lambda _标志: SimpleNamespace(
            ADB设备序列号=""
        )

        中心.启动机器人("robot_2")

        中心.机器人池["robot_2"].启动.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
