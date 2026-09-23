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

    def test_资源行预处理保留行底部数字(self):
        引擎 = Mock(return_value=([("31 000 000", 0.99)], None))
        图像 = np.zeros((53, 120, 3), dtype=np.uint8)

        self.assertEqual(单行资源识别(引擎, 图像), 31000000)
        送入OCR = 引擎.call_args.args[0]
        # 53px 行按 5%~95% 保留 47px，再放大 3 倍；避免未来重新
        # 使用过窄的上半行裁剪，导致圣水/黑油被识别成 0。
        self.assertEqual(送入OCR.shape[0], 141)

    def test_完整资源识别可修复轻量OCR截断(self):
        引擎 = Mock(side_effect=[
            ([("279379", 0.70)], None),
            ([([[0, 0], [1, 0], [1, 1], [0, 1]], "27 937 922", 0.98)], None),
        ])
        图像 = np.zeros((53, 120, 3), dtype=np.uint8)

        结果 = 单行资源识别(引擎, 图像, 允许完整识别=True)

        self.assertEqual(结果, 27937922)
        self.assertEqual(引擎.call_count, 2)

    def test_完整资源识别会用备用图修复七位截断(self):
        引擎 = Mock(side_effect=[
            ([("1455202", 0.70)], None),
            ([([[0, 0], [1, 0], [1, 1], [0, 1]], "14 552 022", 0.98)], None),
        ])
        图像 = np.zeros((53, 120, 3), dtype=np.uint8)

        结果 = 单行资源识别(引擎, 图像, 允许完整识别=True)

        self.assertEqual(结果, 14552022)
        self.assertEqual(引擎.call_count, 2)

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
            side_effect=[27, 18, 73, 27, 18],
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
            side_effect=[500000, 700000, 120, 500000, 700000],
        ):
            结果 = 任务.识别当前资源(上下文)

        self.assertTrue(结果["识别成功"])
        self.assertEqual(结果["总资源"], 1200000)

    def test_主资源轻量OCR漏首位时使用完整OCR(self):
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

        # 真实 MuMu 画面复现：轻量路径漏掉主资源首位和黑油首位，
        # 完整 OCR 返回正确数字。
        with patch(
            "任务流程.更新主世界账号资源状态.单行资源识别",
            side_effect=[151700, 241756, 9249, 1511700, 2417561, 409724],
        ):
            结果 = 任务.识别当前资源(上下文)

        self.assertTrue(结果["识别成功"])
        self.assertEqual(结果["金币"], 1511700)
        self.assertEqual(结果["圣水"], 2417561)
        self.assertEqual(结果["黑油"], 409724)

    def test_七位主资源轻量OCR漏首位时使用完整OCR(self):
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

        # 当前 MuMu 实机复现：14,552,022 偶发被轻量路径读成 1,455,202；
        # 低于新的 2,000,000 复核阈值后，完整 OCR 应恢复真实八位读数。
        with patch(
            "任务流程.更新主世界账号资源状态.单行资源识别",
            side_effect=[13_396_779, 1_455_202, 316_548, 13_395_079, 14_552_022],
        ):
            结果 = 任务.识别当前资源(上下文)

        self.assertTrue(结果["识别成功"])
        self.assertEqual(结果["金币"], 13_395_079)
        self.assertEqual(结果["圣水"], 14_552_022)
        self.assertEqual(结果["黑油"], 316_548)

    def test_黑油轻量读数明显过短时使用完整OCR(self):
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
            side_effect=[28_241_336, 31_000_000, 558, 469_558],
        ):
            结果 = 任务.识别当前资源(上下文)

        self.assertTrue(结果["识别成功"])
        self.assertEqual(结果["黑油"], 469_558)


if __name__ == "__main__":
    unittest.main()
