import queue
import tkinter as tk
import unittest

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


if __name__ == "__main__":
    unittest.main()
