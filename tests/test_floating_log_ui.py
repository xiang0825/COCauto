import queue
import tkinter as tk
import time
import unittest
from types import SimpleNamespace

from 界面.日志面板 import 日志面板


class 悬浮日志测试(unittest.TestCase):
    def test_半透明日志在主日志页隐藏时仍实时更新且可关闭(self):
        try:
            根 = tk.Tk()
        except tk.TclError as 异常:
            self.skipTest(f"当前环境没有桌面显示：{异常}")
        根.withdraw()
        try:
            面板 = 日志面板(根, queue.Queue(), lambda: None, lambda: {})
            面板.pack()
            面板.设置可见(False)
            面板._切换悬浮窗()
            根.update_idletasks()

            self.assertTrue(面板._悬浮窗已打开())
            self.assertAlmostEqual(float(面板._悬浮窗口.attributes("-alpha")), 0.8)
            self.assertTrue(bool(面板._悬浮窗口.attributes("-topmost")))
            面板.记录操作日志("战斗测试事件")
            self.assertIn("战斗测试事件", 面板._悬浮日志文本框.get("1.0", tk.END))

            面板._切换悬浮窗()
            self.assertFalse(面板._悬浮窗已打开())
            self.assertEqual(面板._悬浮按钮.cget("text"), "悬浮半透明")
        finally:
            根.destroy()

    def test_悬浮窗独立显示运行暂停及最近阶段(self):
        try:
            根 = tk.Tk()
        except tk.TclError as 异常:
            self.skipTest(f"当前环境没有桌面显示：{异常}")
        根.withdraw()
        机器人 = SimpleNamespace(机器人标志="robot_1", 当前状态="运行中", 停止原因="")
        队列 = queue.Queue()
        try:
            面板 = 日志面板(根, 队列, lambda: 机器人, lambda: {})
            面板.pack()
            面板.设置可见(False)
            面板._切换悬浮窗()
            队列.put({
                "机器人ID": "robot_1", "内容": "开始执行回营操作",
                "级别": "正常", "记录时间": time.time(),
            })
            面板._定时刷新日志()
            self.assertIn("robot_1", 面板._悬浮机器人标签.cget("text"))
            self.assertIn("运行中", 面板._悬浮状态标签.cget("text"))
            self.assertIn("回营", 面板._悬浮阶段标签.cget("text"))

            机器人.当前状态 = "暂停中"
            面板._更新悬浮状态()
            self.assertIn("暂停中", 面板._悬浮状态标签.cget("text"))
            self.assertIn("游戏计时不会暂停", 面板._悬浮阶段标签.cget("text"))

            机器人.当前状态 = "已停止"
            机器人.停止原因 = "外部停止"
            面板._更新悬浮状态()
            self.assertIn("已停止", 面板._悬浮状态标签.cget("text"))
            self.assertIn("外部停止", 面板._悬浮阶段标签.cget("text"))
        finally:
            根.destroy()


if __name__ == "__main__":
    unittest.main()
