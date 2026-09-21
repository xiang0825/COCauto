import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from unittest.mock import patch

from 任务流程.更新主世界账号资源状态 import 更新家乡资源状态任务
from 工具包.工具函数 import 单行资源识别


class 资源状态测试(unittest.TestCase):
    def test_单行资源只使用轻量识别模型(self):
        引擎 = Mock(return_value=([("123456", 0.99)], None))
        图像 = np.zeros((24, 120, 3), dtype=np.uint8)

        self.assertEqual(单行资源识别(引擎, 图像), 123456)
        引擎.assert_called_once()
        self.assertEqual(
            引擎.call_args.kwargs,
            {"use_det": False, "use_cls": False},
        )

    def test_圈号数字不会让资源识别抛出转换异常(self):
        引擎 = Mock(return_value=([("①②③", 0.99)], None))
        图像 = np.zeros((24, 120, 3), dtype=np.uint8)

        self.assertEqual(单行资源识别(引擎, 图像), 123)

    def test_OCR连续失败时不覆盖数据库(self):
        任务 = 更新家乡资源状态任务.__new__(更新家乡资源状态任务)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((160, 210, 3), dtype=np.uint8)),
            ),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            数据库=SimpleNamespace(更新状态=Mock()),
            机器人标志="测试机器人",
        )
        任务.上下文 = 上下文
        任务.ocr引擎 = Mock()

        with patch(
            "任务流程.更新主世界账号资源状态.单行资源识别",
            side_effect=RuntimeError("bad allocation"),
        ):
            self.assertFalse(任务.执行())

        上下文.数据库.更新状态.assert_not_called()
        self.assertFalse(上下文._最近资源识别成功)
        self.assertIn("bad allocation", 上下文._最近资源识别结果.get("识别错误", ""))
        状态文本 = [调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list]
        self.assertTrue(any("保留上一份资源状态" in 文本 for 文本 in 状态文本))

    def test_资源OCR截断的小数字不算成功(self):
        任务 = 更新家乡资源状态任务.__new__(更新家乡资源状态任务)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((160, 210, 3), dtype=np.uint8)),
            ),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务.上下文 = 上下文
        任务.ocr引擎 = Mock()

        with patch(
            "任务流程.更新主世界账号资源状态.单行资源识别",
            side_effect=[27, 18, 73],
        ):
            结果 = 任务.识别当前资源(上下文)

        self.assertFalse(结果["识别成功"])
        self.assertIn("疑似截断", 结果["识别错误"])

    def test_资源OCR正常主城读数允许写入(self):
        任务 = 更新家乡资源状态任务.__new__(更新家乡资源状态任务)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((160, 210, 3), dtype=np.uint8)),
            ),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务.上下文 = 上下文
        任务.ocr引擎 = Mock()

        with patch(
            "任务流程.更新主世界账号资源状态.单行资源识别",
            side_effect=[500000, 700000, 120],
        ):
            结果 = 任务.识别当前资源(上下文)

        self.assertTrue(结果["识别成功"])
        self.assertEqual(结果["总资源"], 1200000)


if __name__ == "__main__":
    unittest.main()
