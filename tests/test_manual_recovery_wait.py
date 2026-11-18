import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 模块.ADB设备操作类 import ADB错误
from 任务流程.基础任务框架 import 任务上下文
from 线程.自动化机器人 import 自动化机器人


class 人工安全恢复等待测试(unittest.TestCase):
    def _创建机器人(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.停止事件 = threading.Event()
        机器人.停止事件.wait = Mock(return_value=False)
        机器人.继续事件 = threading.Event()
        机器人.继续事件.set()
        机器人.停止原因 = ""
        机器人.记录日志 = Mock()
        return 机器人

    @staticmethod
    def _创建内存恢复上下文(预算结果):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.op = SimpleNamespace(
            检查主机内存预算=Mock(side_effect=预算结果),
        )
        上下文._内存保护已触发 = True
        上下文._主机内存保护可恢复 = True
        上下文._主机内存恢复连续正常次数 = 0
        上下文.页面恢复失败 = True
        上下文.停止事件 = threading.Event()
        上下文.置脚本状态 = Mock()
        上下文.释放识别模型 = Mock()
        return 上下文

    @staticmethod
    def _页面(名称, 世界=None, 可信度=0.0):
        return SimpleNamespace(页面=名称, 世界=世界, 可信度=可信度)

    def test_要求连续两帧主世界确认且不处理中间未知页(self):
        机器人 = self._创建机器人()
        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=[
                self._页面("未知"),
                self._页面("主世界主页", "主世界", 0.78),
                self._页面("未知"),
                self._页面("主世界主页", "主世界", 0.78),
                self._页面("主世界主页", "主世界", 0.78),
            ]),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))

        self.assertEqual(上下文.识别点击画面.call_count, 5)
        self.assertTrue(all(
            调用.kwargs == {"强制": True}
            for 调用 in 上下文.识别点击画面.call_args_list
        ))
        self.assertTrue(any(
            "连续2帧确认主世界主页" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_连续确认新版主世界战斗模式页后交回任务流程(self):
        机器人 = self._创建机器人()
        模式页 = self._页面("主世界战斗模式选择", "主世界", 0.96)
        调用次数 = 0

        def 读取页面(**_参数):
            nonlocal 调用次数
            调用次数 += 1
            if 调用次数 > 2:
                机器人.停止事件.set()
            return 模式页

        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=读取页面),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))

        self.assertEqual(上下文.识别点击画面.call_count, 2)
        self.assertTrue(上下文._主世界战斗模式选择页)
        self.assertTrue(any(
            "连续2帧确认主世界战斗模式选择页" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_低置信度战斗模式页不解除安全待命(self):
        机器人 = self._创建机器人()
        模式页 = self._页面("主世界战斗模式选择", "主世界", 0.89)
        调用次数 = 0

        def 读取页面(**_参数):
            nonlocal 调用次数
            调用次数 += 1
            if 调用次数 > 2:
                机器人.停止事件.set()
            return 模式页

        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=读取页面),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertFalse(机器人._等待人工恢复主世界(上下文, Mock()))

        self.assertFalse(getattr(上下文, "_主世界战斗模式选择页", False))

    def test_明确断线页走既有登录恢复后仍需确认主页(self):
        机器人 = self._创建机器人()
        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=[
                self._页面("断线弹窗"),
                self._页面("主世界主页", "主世界", 0.78),
                self._页面("主世界主页", "主世界", 0.78),
            ]),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        检测登录 = Mock()
        检测登录.执行.return_value = True

        self.assertTrue(机器人._等待人工恢复主世界(上下文, 检测登录))

        检测登录.执行.assert_called_once_with(首次登录=False)
        self.assertTrue(any(
            "断线" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_停止事件会结束安全待命(self):
        机器人 = self._创建机器人()

        def 读取后停止(**_参数):
            机器人.停止原因 = "用户停止"
            机器人.停止事件.set()
            return self._页面("未知")

        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=读取后停止),
            置脚本状态=Mock(),
            脚本延时=Mock(side_effect=lambda _毫秒: 机器人.停止事件.set()),
        )

        self.assertFalse(机器人._等待人工恢复主世界(上下文, Mock()))
        self.assertEqual(上下文.识别点击画面.call_count, 1)

    def test_可恢复页面保护事件不会阻止人工恢复等待(self):
        机器人 = self._创建机器人()
        机器人.停止事件.set()
        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=[
                self._页面("主世界主页", "主世界", 0.78),
                self._页面("主世界主页", "主世界", 0.78),
            ]),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))

        self.assertEqual(上下文.识别点击画面.call_count, 2)
        self.assertFalse(机器人.停止事件.is_set())

    def test_保护事件期间收到明确停止请求仍会终止恢复等待(self):
        机器人 = self._创建机器人()
        机器人.停止事件.set()

        机器人.停止("用户停止", 等待=False)

        self.assertEqual(机器人.停止原因, "用户停止")
        self.assertTrue(机器人.停止事件.is_set())

        上下文 = SimpleNamespace(
            识别点击画面=Mock(),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        self.assertFalse(机器人._等待人工恢复主世界(上下文, Mock()))
        上下文.识别点击画面.assert_not_called()

    def test_低内存待命期间不截图并等待用户停止(self):
        机器人 = self._创建机器人()
        机器人.停止事件.set()
        内存上下文 = self._创建内存恢复上下文([
            (False, "主机内存保护已触发：可用提交额度828MB"),
        ])
        内存上下文.识别点击画面 = Mock()
        内存上下文.置脚本状态 = Mock()
        内存上下文.op.检查主机内存预算.return_value = (
            False, "主机内存保护已触发：可用提交额度828MB"
        )

        def 用户停止(timeout=None):
            机器人.停止原因 = "用户停止"
            机器人.停止事件.set()
            return True

        机器人.停止事件.wait = Mock(side_effect=用户停止)

        self.assertFalse(机器人._等待人工恢复主世界(内存上下文, Mock()))

        内存上下文.识别点击画面.assert_not_called()
        内存上下文.op.检查主机内存预算.assert_called_once_with(强制刷新=True)
        self.assertEqual(机器人.停止原因, "用户停止")
        self.assertTrue(机器人.停止事件.is_set())
        self.assertEqual(
            机器人.停止事件.wait.call_args.kwargs.get("timeout"), 10.0
        )

    def test_连续三次内存预算健康后仍需连续两帧主世界确认(self):
        机器人 = self._创建机器人()
        机器人.停止事件.set()
        内存上下文 = self._创建内存恢复上下文([
            (True, "健康样本1"),
            (True, "健康样本2"),
            (True, "健康样本3"),
        ])
        内存上下文.识别点击画面 = Mock(side_effect=[
            self._页面("主世界主页", "主世界", 0.78),
            self._页面("主世界主页", "主世界", 0.78),
        ])
        机器人.停止事件.wait = Mock(return_value=False)

        self.assertTrue(机器人._等待人工恢复主世界(内存上下文, Mock()))

        self.assertEqual(内存上下文.op.检查主机内存预算.call_count, 3)
        self.assertEqual(内存上下文.识别点击画面.call_count, 2)
        self.assertEqual(
            [调用.kwargs.get("timeout") for 调用 in 机器人.停止事件.wait.call_args_list[:2]],
            [10.0, 10.0],
        )
        self.assertFalse(内存上下文._内存保护已触发)
        self.assertFalse(内存上下文._主机内存保护可恢复)

    def test_待命截图时触发宿主机内存保护后转入预算恢复等待(self):
        机器人 = self._创建机器人()
        内存上下文 = self._创建内存恢复上下文([
            (False, "提交额度828MB"),
            (True, "健康样本1"),
            (True, "健康样本2"),
            (True, "健康样本3"),
        ])
        内存上下文._内存保护已触发 = False
        内存上下文._主机内存保护可恢复 = False
        内存上下文.停止事件 = 机器人.停止事件
        内存上下文.op.检查主机内存预算.reset_mock()
        主页 = self._页面("主世界主页", "主世界", 0.78)
        调用次数 = 0

        def 读取页面(**_参数):
            nonlocal 调用次数
            调用次数 += 1
            if 调用次数 == 1:
                内存上下文.触发内存保护(
                    "点击护栏",
                    ADB错误("主机内存保护已触发：可用提交额度828MB"),
                )
                return None
            return 主页

        内存上下文.识别点击画面 = Mock(side_effect=读取页面)
        内存上下文.置脚本状态 = Mock()

        self.assertTrue(机器人._等待人工恢复主世界(内存上下文, Mock()))

        self.assertEqual(内存上下文.op.检查主机内存预算.call_count, 4)
        self.assertEqual(内存上下文.识别点击画面.call_count, 3)
        self.assertEqual(
            [调用.kwargs.get("timeout") for 调用 in 机器人.停止事件.wait.call_args_list],
            [10.0, 10.0, 10.0, 5.0],
        )
        self.assertFalse(机器人.停止事件.is_set())
        self.assertFalse(内存上下文._内存保护已触发)
        self.assertFalse(内存上下文._主机内存保护可恢复)

    def test_任一低内存样本会清零连续健康计数(self):
        内存上下文 = self._创建内存恢复上下文([
            (True, "健康"),
            (True, "健康"),
            (False, "提交额度不足"),
            (True, "健康"),
            (True, "健康"),
            (True, "健康"),
        ])
        检查恢复 = getattr(内存上下文, "检查主机内存预算恢复", None)
        self.assertTrue(callable(检查恢复), "任务上下文必须提供内存恢复检查")
        if not callable(检查恢复):
            return

        恢复状态 = [
            检查恢复()[0]
            for _ in range(6)
        ]

        self.assertEqual(恢复状态, [False, False, False, False, False, True])
        self.assertEqual(内存上下文.op.检查主机内存预算.call_count, 6)

    def test_只有明确的主机预算保护会标记为可自动恢复(self):
        主机预算上下文 = self._创建内存恢复上下文([])
        主机预算上下文._内存保护已触发 = False
        主机预算上下文.触发内存保护(
            "截图", ADB错误("主机内存保护已触发：可用提交额度828MB")
        )

        一般内存上下文 = self._创建内存恢复上下文([])
        一般内存上下文._内存保护已触发 = False
        一般内存上下文.触发内存保护("OCR", MemoryError("bad allocation"))
        是否可恢复 = getattr(
            主机预算上下文, "是否可自动恢复主机内存保护", None
        )
        self.assertTrue(callable(是否可恢复), "任务上下文必须标明内存保护类型")
        if not callable(是否可恢复):
            return
        是否可恢复一般 = getattr(
            一般内存上下文, "是否可自动恢复主机内存保护", None
        )
        self.assertTrue(callable(是否可恢复一般))
        if not callable(是否可恢复一般):
            return

        self.assertTrue(是否可恢复())
        self.assertFalse(是否可恢复一般())

    def test_一般MemoryError保持停止且不进入截图恢复(self):
        机器人 = self._创建机器人()
        机器人.停止事件.set()
        内存上下文 = self._创建内存恢复上下文([])
        内存上下文._主机内存保护可恢复 = False
        内存上下文.识别点击画面 = Mock(side_effect=lambda **_参数: (
            机器人.停止事件.set() or self._页面("未知")
        ))
        内存上下文.置脚本状态 = Mock()

        self.assertFalse(机器人._等待人工恢复主世界(内存上下文, Mock()))

        内存上下文.识别点击画面.assert_not_called()
        self.assertTrue(机器人.停止事件.is_set())


if __name__ == "__main__":
    unittest.main()
