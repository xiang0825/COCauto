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

    def test_稳定清零阈值大于冷却_十分钟后又停仍算失败(self):
        self.assertGreater(自动重启策略.稳定清零秒, 自动重启策略.冷却秒)
        self.assertEqual(自动重启策略.稳定清零秒, 3600.0)
        线程 = [object() for _ in range(5)]
        self.策略.判定("r", 线程[0], "无心跳", False)
        self.时钟.t = 600
        self.assertEqual(self.策略.判定("r", 线程[0], "无心跳", False), "check")
        self.策略.复核结果("r", 已重启=True)
        # 每次重启后跑 10 分钟多一点就停：旧逻辑（清零阈值=冷却 600s）会清零导致无限重启。
        for 次 in range(1, 4):
            self.时钟.t += 601
            动作 = self.策略.判定("r", 线程[次], "无心跳", False)
            self.assertEqual(self.策略.连续失败("r"), 次)
            if 次 < 3:
                self.assertEqual(动作, "check")
                self.策略.复核结果("r", 已重启=True)
            else:
                self.assertEqual(动作, "give_up")

    def test_复核时人工介入不计失败只解除复核中(self):
        线程 = object()
        self.策略.判定("r", 线程, "无心跳", False)
        self.时钟.t = 600
        self.assertEqual(self.策略.判定("r", 线程, "无心跳", False), "check")
        self.策略.复核结果("r", 已重启=False, 人工介入=True)
        self.assertEqual(self.策略.连续失败("r"), 0)
        self.assertFalse(self.策略._状态["r"]["复核中"])

    def test_复核期间状态被人工清空则不重建不计数(self):
        线程 = object()
        self.策略.判定("r", 线程, "无心跳", False)
        self.时钟.t = 600
        self.策略.判定("r", 线程, "无心跳", False)
        self.策略.记录人工操作("r")
        self.策略.复核结果("r", 已重启=False)
        self.assertNotIn("r", self.策略._状态)
        self.assertEqual(self.策略.连续失败("r"), 0)

    def test_多线程并发判定和复核不丢计数(self):
        策略 = 自动重启策略(时钟=lambda: 0.0)
        策略.最大连续失败 = 10**9
        策略._取("r")
        屏障 = threading.Barrier(8)

        def 工作():
            屏障.wait()
            for _ in range(2000):
                策略.复核结果("r", 已重启=False)
                策略.判定("r", "同一停止", "无心跳", False)

        线程们 = [threading.Thread(target=工作) for _ in range(8)]
        for t in 线程们:
            t.start()
        for t in 线程们:
            t.join()
        self.assertEqual(策略.连续失败("r"), 8 * 2000)

    def test_所有公开方法都在锁内(self):
        锁 = mock.MagicMock()
        self.策略._锁 = 锁
        self.策略.判定("r", object(), "无心跳", False)
        self.策略.复核结果("r", 已重启=False)
        self.策略.连续失败("r")
        self.策略.记录人工操作("r")
        self.assertEqual(锁.__enter__.call_count, 4)


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
        中心.自动重启._取("robot_1")
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
        中心.自动重启._取("robot_1")["复核中"] = True
        中心._复核并自动重启("robot_1", 机器人, "无心跳", 机器人.主线程)
        机器人.启动.assert_not_called()
        # 人工介入不算自动重启失败，且复核标记已解除。
        self.assertEqual(中心.自动重启.连续失败("robot_1"), 0)
        self.assertFalse(中心.自动重启._状态["robot_1"]["复核中"])

    def test_关闭时先等机器人主线程退出(self):
        中心 = self._中心()
        放行 = threading.Event()
        已退出 = []

        def 主线程体():
            放行.wait(3)
            已退出.append(True)

        主线程 = threading.Thread(target=主线程体, daemon=True)
        主线程.start()
        机器人 = SimpleNamespace(主线程=主线程, 停止=mock.Mock(side_effect=lambda *_a, **_k: 放行.set()))
        中心.机器人池 = {"robot_1": 机器人}
        中心.关闭()
        机器人.停止.assert_called_once_with("控制台关闭", 等待=False)
        self.assertFalse(主线程.is_alive())
        self.assertEqual(已退出, [True])

    def test_关闭等待有上限(self):
        中心 = self._中心()
        中心.关闭等待主线程秒 = 0.2
        卡住 = threading.Event()
        主线程 = threading.Thread(target=lambda: 卡住.wait(5), daemon=True)
        主线程.start()
        self.addCleanup(卡住.set)
        中心.机器人池 = {"robot_1": SimpleNamespace(主线程=主线程, 停止=mock.Mock())}
        开始 = __import__("time").monotonic()
        中心.关闭()
        self.assertLess(__import__("time").monotonic() - 开始, 2.0)

    def test_设置关闭时不检查(self):
        中心 = self._中心(允许=False)
        机器人 = self._机器人()
        with mock.patch("threading.Thread") as 线程类:
            中心._检查自动重启("robot_1", 机器人)
        线程类.assert_not_called()

    def test_放弃时写日志(self):
        中心 = self._中心()
        机器人 = self._机器人(原因="未处理异常：x")
        中心.自动重启._状态["robot_1"] = {
            "停止线程": id(机器人.主线程), "停止时间": 0.0, "上次重启": None,
            "上次尝试": 0.0, "连续失败": 3, "已放弃": False, "复核中": False,
        }
        with mock.patch("threading.Thread") as 线程类:
            中心._检查自动重启("robot_1", 机器人)
        线程类.assert_not_called()
        self.assertIn("不再自动重启", 机器人.记录日志.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
