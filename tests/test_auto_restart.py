"""非人工停止后的自动重启：人工优先、冷却 10 分钟、连续 3 次失败放弃。"""
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from 主入口 import 机器人监控中心, 自动重启策略


class _时钟:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class 策略测试(unittest.TestCase):
    def setUp(self):
        self.时钟 = _时钟()
        self.策略 = 自动重启策略(时钟=self.时钟)

    def test_人工停止和自然完成和内存保护不重启(self):
        for 原因 in ("界面停止按钮", "控制台关闭", "手动终止", "任务自然完成", "未启动", "宿主机内存保护退出：x"):
            self.时钟.t += 1000
            self.assertEqual(self.策略.判定("r", object(), 原因, False), "ignore", 原因)

    def test_暂停中不重启(self):
        线程 = object()
        self.策略.判定("r", 线程, "无心跳", True)
        self.时钟.t = 700
        self.assertEqual(self.策略.判定("r", 线程, "无心跳", True), "ignore")

    def test_冷却十分钟后才复核且复核期间不重复(self):
        线程 = object()
        self.assertEqual(self.策略.判定("r", 线程, "无心跳", False), "wait")
        self.时钟.t = 599
        self.assertEqual(self.策略.判定("r", 线程, "无心跳", False), "wait")
        self.时钟.t = 600
        self.assertEqual(self.策略.判定("r", 线程, "无心跳", False), "check")
        self.assertEqual(self.策略.判定("r", 线程, "无心跳", False), "ignore")

    def test_未确认主页三次后放弃且只提醒一次(self):
        线程 = object()
        self.assertEqual(self.策略.判定("r", 线程, "未处理异常：x", False), "wait")
        for 次 in range(3):
            self.时钟.t += 600
            self.assertEqual(self.策略.判定("r", 线程, "未处理异常：x", False), "check")
            self.策略.复核结果("r", 已重启=False)
        self.时钟.t += 600
        self.assertEqual(self.策略.判定("r", 线程, "未处理异常：x", False), "give_up")
        self.时钟.t += 600
        self.assertEqual(self.策略.判定("r", 线程, "未处理异常：x", False), "ignore")

    def test_重启后很快又停算失败_稳定运行后清零(self):
        线程1, 线程2, 线程3 = object(), object(), object()
        self.策略.判定("r", 线程1, "无心跳", False)
        self.时钟.t = 600
        self.策略.判定("r", 线程1, "无心跳", False)
        self.策略.复核结果("r", 已重启=True)
        self.时钟.t = 700  # 重启 100 秒后又停
        self.策略.判定("r", 线程2, "无心跳", False)
        self.assertEqual(self.策略.连续失败("r"), 1)
        self.时钟.t = 1300
        self.assertEqual(self.策略.判定("r", 线程2, "无心跳", False), "check")
        self.策略.复核结果("r", 已重启=True)
        self.时钟.t = 1300 + 3600  # 稳定跑了一小时再停
        self.策略.判定("r", 线程3, "无心跳", False)
        self.assertEqual(self.策略.连续失败("r"), 0)

    def test_人工操作清零计数(self):
        线程 = object()
        self.策略.判定("r", 线程, "无心跳", False)
        self.策略.复核结果("r", 已重启=False)
        self.策略.记录人工操作("r")
        self.assertEqual(self.策略.连续失败("r"), 0)


class 监控中心接线测试(unittest.TestCase):
    def _中心(self, 允许=True):
        中心 = 机器人监控中心.__new__(机器人监控中心)
        中心.自动重启 = 自动重启策略(时钟=lambda: 10_000.0)
        中心.运行标志 = True
        中心.机器人池 = {}
        中心.数据库 = SimpleNamespace(获取机器人设置=lambda _标志: SimpleNamespace(非人工停止后自动重启=允许))
        return 中心

    def _机器人(self, 原因="无心跳", 确认=(True, "页面=主世界主页")):
        已结束 = threading.Thread(target=lambda: None)
        已结束.start()
        已结束.join()
        机器人 = SimpleNamespace(
            停止事件=threading.Event(), 继续事件=threading.Event(), 主线程=已结束, 停止原因=原因,
            只读确认主世界主页=mock.Mock(return_value=确认), 启动=mock.Mock(), 记录日志=mock.Mock(),
        )
        机器人.停止事件.set()
        机器人.继续事件.set()
        return 机器人

    def test_确认主页后自动启动(self):
        中心 = self._中心()
        中心._检查设备是否已被其它机器人占用 = lambda _标志: None
        机器人 = self._机器人()
        中心.自动重启._取("robot_1")  # 停止时间=0，已过冷却
        中心.自动重启._状态["robot_1"].update(停止线程=id(机器人.主线程), 停止时间=0.0)
        with mock.patch("threading.Thread") as 线程类:
            中心._检查自动重启("robot_1", 机器人)
        参数 = 线程类.call_args.kwargs["args"]
        中心._复核并自动重启(*参数)
        机器人.启动.assert_called_once()

    def test_未确认主页不启动(self):
        中心 = self._中心()
        机器人 = self._机器人(确认=(False, "页面=战斗中"))
        中心._复核并自动重启("robot_1", 机器人, "无心跳", 机器人.主线程)
        机器人.启动.assert_not_called()
        self.assertEqual(中心.自动重启.连续失败("robot_1"), 1)

    def test_复核期间人工暂停则放弃这次重启(self):
        中心 = self._中心()
        机器人 = self._机器人()

        def 复核():
            机器人.继续事件.clear()  # 用户按了 F2
            return True, "主页"

        机器人.只读确认主世界主页 = 复核
        中心._复核并自动重启("robot_1", 机器人, "无心跳", 机器人.主线程)
        机器人.启动.assert_not_called()

    def test_设置关闭时不检查(self):
        中心 = self._中心(允许=False)
        机器人 = self._机器人()
        with mock.patch("threading.Thread") as 线程类:
            中心._检查自动重启("robot_1", 机器人)
        线程类.assert_not_called()

    def test_放弃时弹桌面通知(self):
        中心 = self._中心()
        机器人 = self._机器人(原因="未处理异常：x")
        中心.自动重启._状态["robot_1"] = {
            "停止线程": id(机器人.主线程), "停止时间": 0.0, "上次重启": None,
            "上次尝试": 0.0, "连续失败": 3, "已放弃": False, "复核中": False,
        }
        with mock.patch("工具包.桌面通知.机器人桌面通知") as 通知:
            中心._检查自动重启("robot_1", 机器人)
        self.assertEqual(通知.call_args[0][3], "自动重启已放弃")


if __name__ == "__main__":
    unittest.main()
