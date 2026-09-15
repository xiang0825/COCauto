import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 任务流程.世界跳转.进入世界基类 import 进入世界任务基类


class 世界跳转测试(unittest.TestCase):
    def test_切换世界超时会先发送ESC关闭误触页面(self):
        模块 = importlib.import_module("任务流程.世界跳转.进入世界基类")
        时钟 = SimpleNamespace(当前时间=0.0)
        键盘 = Mock()

        def 脚本延时(毫秒数):
            时钟.当前时间 += 毫秒数 / 1000

        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            键盘=键盘,
            脚本延时=脚本延时,
            置脚本状态=Mock(),
        )
        任务 = object.__new__(进入世界任务基类)
        任务.上下文 = 上下文
        任务.状态文本 = "主世界"
        任务.船模板路径 = "船.bmp"
        任务.滑动配置 = SimpleNamespace(起点=(1, 1), 终点=(2, 2))
        任务.模板识别 = Mock()
        任务.模板识别.执行匹配.return_value = (False, (0, 0), None)
        任务.滑动屏幕 = Mock()
        任务.是否在目标世界 = Mock(side_effect=[False, False, False, False, False, True])

        原时间函数 = 模块.time.time
        模块.time.time = lambda: 时钟.当前时间
        try:
            self.assertTrue(任务.执行())
        finally:
            模块.time.time = 原时间函数

        按键列表 = [调用.args[0] for 调用 in 键盘.按字符按压.call_args_list]
        self.assertEqual(按键列表[:2], ["esc", "esc"])
        self.assertIn("f5", 按键列表)
        self.assertTrue(
            any("ESC关闭误触页面" in 调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
