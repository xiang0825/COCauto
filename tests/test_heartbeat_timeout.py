import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 线程.自动化机器人 import 自动化机器人
from 任务流程.基础任务框架 import 任务上下文
from 任务流程.检测游戏登录状态 import 检测游戏登录状态任务


class 心跳超时测试(unittest.TestCase):
    def _创建机器人(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "robot_1"
        机器人.停止事件 = threading.Event()
        机器人.继续事件 = threading.Event()
        机器人.继续事件.set()
        机器人.数据库 = SimpleNamespace(
            读取最后日志=Mock(
                return_value=SimpleNamespace(
                    日志内容="仍在等待游戏主页识别",
                    记录时间=70.0,
                    下次超时=100.0,
                )
            )
        )
        return 机器人

    def test_心跳截止瞬间不会因提交竞态误重启(self):
        机器人 = self._创建机器人()

        with patch("线程.自动化机器人.time.time", return_value=101.0):
            self.assertEqual(机器人.检查超时(), (False, ""))

    def test_超过宽限后才判定无心跳(self):
        机器人 = self._创建机器人()

        with patch("线程.自动化机器人.time.time", return_value=106.0):
            超时, 原因 = 机器人.检查超时()

        self.assertTrue(超时)
        self.assertIn("含5秒宽限", 原因)

    def test_战后主页确认容忍慢截图(self):
        机器人 = self._创建机器人()
        当前时间 = [0.0]
        主页 = SimpleNamespace(
            页面="主世界主页",
            世界="主世界",
            可信度=0.70,
            依据=("主世界资源栏0.94", "新版战斗入口0.99"),
        )

        def 识别页面(**_参数):
            if 上下文.识别点击画面.call_count == 1:
                # 模拟 ADB 首帧在回营后卡顿 11 秒，仍应给第二帧确认机会。
                当前时间[0] += 11.0
            return 主页

        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=识别页面),
            置脚本状态=Mock(),
            脚本延时=Mock(
                side_effect=lambda 毫秒: 当前时间.__setitem__(
                    0, 当前时间[0] + 毫秒 / 1000
                )
            ),
        )
        with patch(
            "线程.自动化机器人.time.monotonic",
            side_effect=lambda: 当前时间[0],
        ):
            self.assertTrue(机器人._战后连续确认主世界主页(上下文))

        self.assertEqual(上下文.识别点击画面.call_count, 2)

    def test_用户暂停期间不以旧日志判定无心跳(self):
        机器人 = self._创建机器人()
        机器人.继续事件.clear()
        with patch("线程.自动化机器人.time.time", return_value=10000.0):
            self.assertEqual(机器人.检查超时()[0], False)

    def test_暂停恢复先更新心跳再接受监控(self):
        机器人 = self._创建机器人()
        机器人.继续事件.clear()
        机器人.记录日志 = Mock()
        机器人.继续()
        机器人.记录日志.assert_called_once_with(
            "机器人已从暂停状态继续，等待下一条任务心跳", 120
        )
        self.assertTrue(机器人.继续事件.is_set())

    def test_外部停止唤醒暂停线程但不写恢复心跳(self):
        机器人 = self._创建机器人()
        机器人.继续事件.clear()
        机器人.记录日志 = Mock()
        机器人.停止("测试停止", 等待=False)
        self.assertTrue(机器人.停止事件.is_set())
        self.assertTrue(机器人.继续事件.is_set())
        self.assertEqual(机器人.记录日志.call_count, 1)

    def test_重复关闭保留第一次停止原因并且不重复写日志(self):
        机器人 = self._创建机器人()
        机器人.记录日志 = Mock()
        机器人.停止("界面停止按钮", 等待=False)
        机器人.停止("控制台关闭", 等待=False)
        self.assertEqual(机器人.停止原因, "界面停止按钮")
        机器人.记录日志.assert_called_once()

    def test_战斗异常不会把游戏切到前台或重启(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.机器人标志 = "robot_1"
        上下文.置脚本状态 = Mock()
        上下文.发送企业微信通知 = Mock()
        上下文.发送死亡通知 = Mock()
        上下文.雷电模拟器 = Mock()
        上下文._战斗中 = True

        上下文.处理异常("进攻任务", RuntimeError("战斗页面操作超时"))

        上下文.雷电模拟器.打开应用.assert_not_called()
        上下文.发送死亡通知.assert_called_once()
        self.assertTrue(
            any("异常恢复安全锁" in 调用.args[0]
                for 调用 in 上下文.置脚本状态.call_args_list)
        )

    def test_登录识别超时不发送ESC并安全停止(self):
        任务 = object.__new__(检测游戏登录状态任务)
        上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            脚本延时=Mock(),
            键盘=SimpleNamespace(按字符按压=Mock()),
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=object()),
                设备=SimpleNamespace(获取当前前台包名=Mock(return_value="com.ldmnq.launcher3")),
            ),
            停止事件=threading.Event(),
        )
        任务.上下文 = 上下文
        任务.第一次检测游戏登录 = False

        现在 = iter((0.0, 201.0))
        with patch("任务流程.检测游戏登录状态.time.monotonic", side_effect=lambda: next(现在)):
            self.assertFalse(任务.执行())

        上下文.键盘.按字符按压.assert_not_called()
        self.assertTrue(上下文.停止事件.is_set())
        self.assertTrue(
            any("禁止发送ESC" in 调用.args[0]
                for 调用 in 上下文.置脚本状态.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
