import tkinter as tk
import unittest
from unittest import mock
import queue
from types import SimpleNamespace

from 界面.机器人管理面板 import 机器人管理面板
from 线程.自动化机器人 import 自动化机器人


class _机器人:
    def __init__(self):
        self.机器人标志 = "robot_1"
        self.当前状态 = "已停止"

    def 暂停(self):
        self.当前状态 = "暂停中"

    def 继续(self):
        self.当前状态 = "运行中"


class 机器人快捷键测试(unittest.TestCase):
    def test_界面停止按钮传递明确停止原因(self):
        面板 = 机器人管理面板.__new__(机器人管理面板)
        机器人 = SimpleNamespace(机器人标志="robot_1", 停止=mock.Mock())
        面板.获取当前机器人 = mock.Mock(return_value=机器人)
        with mock.patch("界面.机器人管理面板.threading.Thread") as 线程:
            面板._停止机器人()
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
        try:
            根 = tk.Tk()
        except tk.TclError as 异常:
            self.skipTest(f"当前环境没有桌面显示：{异常}")
        根.withdraw()
        机器人 = _机器人()
        启动次数 = []

        def 启动机器人(_标志):
            启动次数.append(1)
            机器人.当前状态 = "运行中"

        监控中心 = SimpleNamespace(
            机器人池={"robot_1": 机器人}, 启动机器人=启动机器人,
        )
        try:
            面板 = 机器人管理面板(根, 监控中心, lambda _标志: None)
            面板.pack()
            面板.选中机器人("robot_1")
            self.assertEqual(str(面板.继续按钮.cget("state")), "normal")
            self.assertFalse(面板.快捷键暂停())
            self.assertTrue(面板.快捷键开始或继续())
            self.assertEqual(len(启动次数), 1)
            self.assertFalse(面板.快捷键开始或继续())
            self.assertTrue(面板.快捷键暂停())
            self.assertEqual(机器人.当前状态, "暂停中")
            self.assertFalse(面板.快捷键暂停())
            self.assertTrue(面板.快捷键开始或继续())
            self.assertEqual(机器人.当前状态, "运行中")
            self.assertEqual(len(启动次数), 1)
        finally:
            根.destroy()

    def test_安全停机后继续按钮走重新启动而不是已退出线程(self):
        机器人 = _机器人()
        机器人.继续 = mock.Mock(side_effect=AssertionError("已停止线程不能继续"))
        面板 = 机器人管理面板.__new__(机器人管理面板)
        面板.获取当前机器人 = mock.Mock(return_value=机器人)
        面板._启动机器人 = mock.Mock(return_value=True)

        self.assertTrue(面板._继续机器人())
        面板._启动机器人.assert_called_once_with()
        机器人.继续.assert_not_called()


if __name__ == "__main__":
    unittest.main()
