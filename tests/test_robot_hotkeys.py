import queue
import unittest
from unittest import mock
from types import SimpleNamespace

from 应用.控制器 import 应用控制器
from 线程.自动化机器人 import 自动化机器人


class _机器人:
    def __init__(self):
        self.机器人标志 = "robot_1"
        self.当前状态 = "已停止"
        self.停止 = mock.Mock()

    def 暂停(self):
        self.当前状态 = "暂停中"

    def 继续(self):
        self.当前状态 = "运行中"


class 机器人快捷键测试(unittest.TestCase):
    def _控制器(self, 机器人):
        启动次数 = []

        def 启动机器人(_标志):
            启动次数.append(1)
            机器人.当前状态 = "运行中"

        监控中心 = SimpleNamespace(
            机器人池={"robot_1": 机器人}, 启动机器人=启动机器人, 数据库=mock.Mock(),
        )
        控制器 = 应用控制器(监控中心)
        控制器.实例ID = "robot_1"
        return 控制器, 启动次数

    def test_界面停止按钮传递明确停止原因(self):
        机器人 = _机器人()
        控制器, _ = self._控制器(机器人)
        with mock.patch("应用.控制器.threading.Thread") as 线程:
            控制器.停止()
        self.assertEqual(线程.call_args.kwargs["args"], ("界面停止按钮",))
        线程.return_value.start.assert_called_once()

    def test_启动立即进入运行态且马上暂停不会被启动覆盖(self):
        设置 = SimpleNamespace(
            ADB自动检测路径=False, ADB路径="adb",
            ADB已确认模拟器=True, ADB设备序列号="127.0.0.1:16416",
            是否刷主世界=True,
        )
        数据库 = mock.Mock()
        数据库.获取机器人设置.return_value = 设置
        机器人 = 自动化机器人("robot_1", queue.Queue(), 数据库, queue.Queue())
        with mock.patch(
            "线程.自动化机器人.ADB设备操作类.解析ADB路径",
            return_value="adb",
        ), mock.patch("线程.自动化机器人.threading.Thread"):
            机器人.启动()
        self.assertEqual(机器人.当前状态, "运行中")
        机器人.暂停()
        self.assertEqual(机器人.当前状态, "暂停中")

    def test_F1只启动或继续_F2只暂停(self):
        机器人 = _机器人()
        控制器, 启动次数 = self._控制器(机器人)
        self.assertFalse(控制器.仅暂停())
        self.assertTrue(控制器.开始或继续())
        self.assertEqual(len(启动次数), 1)
        self.assertFalse(控制器.开始或继续())
        self.assertTrue(控制器.仅暂停())
        self.assertEqual(机器人.当前状态, "暂停中")
        self.assertFalse(控制器.仅暂停())
        self.assertTrue(控制器.开始或继续())
        self.assertEqual(机器人.当前状态, "运行中")
        self.assertEqual(len(启动次数), 1)

    def test_未初始化时热键不做任何事(self):
        控制器, 启动次数 = self._控制器(_机器人())
        控制器.实例ID = "不存在"
        self.assertFalse(控制器.开始或继续())
        self.assertFalse(控制器.仅暂停())
        self.assertEqual(启动次数, [])

    def test_安全停机后继续按钮走重新启动而不是已退出线程(self):
        机器人 = _机器人()
        机器人.继续 = mock.Mock(side_effect=AssertionError("已停止线程不能继续"))
        控制器, 启动次数 = self._控制器(机器人)
        控制器.继续()
        self.assertEqual(len(启动次数), 1)
        机器人.继续.assert_not_called()


if __name__ == "__main__":
    unittest.main()
