import importlib
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

自动启动模块 = importlib.import_module("界面.自动启动界面")


class 自动启动界面测试(unittest.TestCase):
    def test_机器人加载后刷新清除旧空提示(self):
        try:
            根 = tk.Tk()
        except tk.TclError as 异常:
            self.skipTest(f"当前环境没有桌面显示：{异常}")
        根.withdraw()
        监控中心 = SimpleNamespace(机器人池={})
        try:
            with patch.object(自动启动模块, "自动启动管理器") as 管理器类:
                管理器类.return_value.获取所有自动启动配置.return_value = {}
                面板 = 自动启动模块.自动启动界面(根, 监控中心)
                self.assertEqual(面板.机器人配置项, {})
                监控中心.机器人池["robot_1"] = object()
                面板._刷新机器人列表()
                self.assertEqual(set(面板.机器人配置项), {"robot_1"})
                self.assertEqual(len(面板.机器人列表框架.winfo_children()), 1)
                self.assertEqual(面板._滚动条.winfo_manager(), "")
        finally:
            根.destroy()


if __name__ == "__main__":
    unittest.main()
