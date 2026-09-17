import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 任务流程.世界跳转.进入世界基类 import 进入世界任务基类


class 世界跳转测试(unittest.TestCase):
    def test_世界未知时不发送任何输入(self):
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
        任务.是否在目标世界 = Mock(return_value=False)
        任务.识别当前世界 = Mock(return_value=SimpleNamespace(当前世界="未知"))

        原时间函数 = 模块.time.time
        模块.time.time = lambda: 时钟.当前时间
        try:
            self.assertFalse(任务.执行())
        finally:
            模块.time.time = 原时间函数

        键盘.按字符按压.assert_not_called()
        任务.滑动屏幕.assert_not_called()
        self.assertTrue(
            any("禁止点击、滑动、ESC或返回键" in 调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
