import queue
import unittest
from unittest import mock

from 主入口 import 机器人监控中心


class 异常停止策略测试(unittest.TestCase):
    def test_未分类异常不会删除实例或自动重启(self):
        监控中心 = 机器人监控中心.__new__(机器人监控中心)
        监控中心.全局消息队列 = queue.Queue()
        旧机器人 = object()
        监控中心.机器人池 = {"robot_1": 旧机器人}
        监控中心.创建并启动机器人 = mock.Mock()

        监控中心.处理死亡通知("robot_1", "未处理异常：OCR 引擎状态未知")

        self.assertIs(监控中心.机器人池["robot_1"], 旧机器人)
        监控中心.创建并启动机器人.assert_not_called()
        消息 = []
        while not 监控中心.全局消息队列.empty():
            消息.append(监控中心.全局消息队列.get_nowait())
        self.assertTrue(any("禁止自动重启" in 项 for 项 in 消息))


if __name__ == "__main__":
    unittest.main()
