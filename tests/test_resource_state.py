import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from unittest.mock import patch

from 任务流程.更新主世界账号资源状态 import 更新家乡资源状态任务
from 工具包.工具函数 import 单行资源识别
from 模块.检测.OCR识别器 import 安全OCR引擎


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

    def test_单行资源空OCR返回不会抛二元组解包异常(self):
        引擎 = Mock(return_value=None)
        图像 = np.zeros((24, 120, 3), dtype=np.uint8)

        self.assertEqual(单行资源识别(引擎, 图像), 0)

    def test_线程安全OCR代理统一空返回格式(self):
        引擎类 = 安全OCR引擎.__wrapped__
        代理 = 引擎类.__new__(引擎类)
        代理._操作锁 = __import__("threading").Lock()
        代理._原始引擎 = Mock(return_value=None)

        self.assertEqual(代理(np.zeros((2, 2, 3), dtype=np.uint8)), ([], None))

        代理._原始引擎.return_value = ([('文字', 0.9)],)
        self.assertEqual(
            代理(np.zeros((2, 2, 3), dtype=np.uint8)),
            ([('文字', 0.9)], None),
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

    def test_黑油上限丢弃二值图八位误读并保留彩色结果(self):
        引擎 = Mock(side_effect=[
            ([("8", 0.32)], None),
            ([([[0, 0], [1, 0], [1, 1], [0, 1]], "349956", 0.99)], None),
            ([([[0, 0], [1, 0], [1, 1], [0, 1]], "34919567", 0.88)], None),
        ])
        图像 = np.zeros((53, 120, 3), dtype=np.uint8)

        结果 = 单行资源识别(
            引擎, 图像, 允许完整识别=True, 最大值=1_000_000
        )

        self.assertEqual(结果, 349956)

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

    def test_普通百万级主资源也必须整栏复核黑油短读数(self):
        """实机回归：8m/4m 主资源时黑油 52059 不能被写成 7/1。"""
        任务 = 更新家乡资源状态任务.__new__(更新家乡资源状态任务)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((160, 210, 3), dtype=np.uint8)),
            ),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务.上下文 = 上下文
        任务.ocr引擎 = Mock(return_value=(
            [
                ([[98, 25], [160, 25], [160, 42], [98, 42]], "8118875", 0.99),
                ([[98, 82], [161, 82], [161, 98], [98, 98]], "4190339", 0.99),
                ([[115, 137], [163, 137], [163, 153], [115, 154]], "52059", 0.99),
            ],
            None,
        ))

        with patch(
            "任务流程.更新主世界账号资源状态.单行资源识别",
            side_effect=[8_118_875, 4_190_339, 7],
        ):
            结果 = 任务.识别当前资源(上下文)

        self.assertTrue(结果["识别成功"])
        self.assertEqual(结果["金币"], 8_118_875)
        self.assertEqual(结果["圣水"], 4_190_339)
        self.assertEqual(结果["黑油"], 52_059)

    def test_资源行使用重叠切分修复黑油漏首位(self):
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

        # 轻量黑油值36,295来自旧切分；重叠切分后完整复核应读回362,905。
        with patch(
            "任务流程.更新主世界账号资源状态.单行资源识别",
            side_effect=[20_004_120, 20_020_360, 36_295, 362_905],
        ):
            结果 = 任务.识别当前资源(上下文)

        self.assertTrue(结果["识别成功"])
        self.assertEqual(结果["黑油"], 362_905)

    def test_主资源很高但下两行偏低时使用整栏坐标复核(self):
        任务 = 更新家乡资源状态任务.__new__(更新家乡资源状态任务)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((160, 210, 3), dtype=np.uint8)),
            ),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务.上下文 = 上下文
        任务.ocr引擎 = Mock(return_value=(
            [
                ([[100, 24], [176, 24], [176, 42], [100, 42]], "20009412", 0.94),
                ([[100, 61], [176, 61], [176, 76], [100, 76]], "20042036", 0.99),
                ([[125, 95], [176, 95], [176, 110], [125, 110]], "362905", 0.99),
            ],
            None,
        ))

        with patch(
            "任务流程.更新主世界账号资源状态.单行资源识别",
            side_effect=[20_009_412, 181_658, 204_858],
        ):
            结果 = 任务.识别当前资源(上下文)

        self.assertTrue(结果["识别成功"])
        self.assertEqual(结果["金币"], 20_009_412)
        self.assertEqual(结果["圣水"], 20_042_036)
        self.assertEqual(结果["黑油"], 362_905)

    def test_整栏OCR按实机动态纵坐标归位(self):
        任务 = 更新家乡资源状态任务.__new__(更新家乡资源状态任务)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((160, 210, 3), dtype=np.uint8)),
            ),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务.上下文 = 上下文
        任务.ocr引擎 = Mock(return_value=(
            [
                ([[82, 24], [160, 24], [160, 43], [82, 43]], "20017009", 0.99),
                ([[81, 81], [162, 81], [162, 99], [81, 99]], "20048658", 0.99),
                ([[107, 137], [165, 137], [165, 153], [107, 153]], "362905", 0.99),
            ],
            None,
        ))

        with patch(
            "任务流程.更新主世界账号资源状态.单行资源识别",
            side_effect=[20_017_009, 0, 0],
        ):
            结果 = 任务.识别当前资源(上下文)

        self.assertTrue(结果["识别成功"])
        self.assertEqual(结果["金币"], 20_017_009)
        self.assertEqual(结果["圣水"], 20_048_658)
        self.assertEqual(结果["黑油"], 362_905)

    def test_实机整栏已读出一百万圣水不再被单行零覆盖(self):
        """复现 31m/1m/231237：整栏正确，旧回退却把圣水写成 0。"""
        任务 = 更新家乡资源状态任务.__new__(更新家乡资源状态任务)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((160, 210, 3), dtype=np.uint8)),
            ),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务.上下文 = 上下文
        任务.ocr引擎 = Mock(return_value=(
            [
                ([[79, 25], [160, 25], [160, 42], [79, 42]], "31000000", 0.998),
                ([[85, 82], [162, 83], [162, 98], [85, 97]], "1000000", 0.997),
                ([[113, 137], [165, 136], [165, 153], [113, 154]], "231237", 0.998),
            ],
            None,
        ))

        with patch(
            "任务流程.更新主世界账号资源状态.单行资源识别",
            side_effect=[31_000_000, 0, 0],
        ) as 单行:
            结果 = 任务.识别当前资源(上下文)

        self.assertEqual(单行.call_count, 3)
        self.assertEqual(结果["金币"], 31_000_000)
        self.assertEqual(结果["圣水"], 1_000_000)
        self.assertEqual(结果["黑油"], 231_237)
        self.assertTrue(结果["识别成功"])

    def test_实机圣水彩色整栏漏前导时使用灰度整栏复核(self):
        """MuMu 实机彩色 OCR 读 819777，灰度路径应恢复 17819777。"""
        任务 = 更新家乡资源状态任务.__new__(更新家乡资源状态任务)
        任务.ocr引擎 = Mock(side_effect=[
            (
                [
                    ([[80, 24], [160, 24], [160, 43], [80, 43]], "20306643", 0.99),
                    ([[111, 82], [163, 82], [163, 99], [111, 99]], "819777", 0.99),
                    ([[107, 137], [163, 137], [163, 153], [107, 153]], "382284", 0.99),
                ],
                None,
            ),
            (
                [
                    ([[80, 24], [160, 24], [160, 43], [80, 43]], "20306643", 0.99),
                    ([[95, 82], [163, 82], [163, 99], [95, 99]], "17819777", 0.99),
                    ([[107, 137], [164, 137], [164, 153], [107, 153]], "382284", 0.99),
                ],
                None,
            ),
        ])

        结果 = 任务._完整资源栏复核(np.zeros((160, 210, 3), dtype=np.uint8))

        self.assertEqual(结果, (20306643, 17819777, 382284))
        self.assertEqual(任务.ocr引擎.call_count, 2)

    def test_一项主资源高而另一项漏读时不算可信(self):
        任务 = 更新家乡资源状态任务.__new__(更新家乡资源状态任务)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((160, 210, 3), dtype=np.uint8)),
            ),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务.上下文 = 上下文
        任务.ocr引擎 = Mock(return_value=([], None))

        with patch(
            "任务流程.更新主世界账号资源状态.单行资源识别",
            side_effect=[20_017_009, 0, 0, 20_017_009, 0, 0],
        ):
            结果 = 任务.识别当前资源(上下文)

        self.assertFalse(结果["识别成功"])
        self.assertIn("漏读", 结果["识别错误"])

    def test_整栏复核后真实四位数主资源允许写入(self):
        """真实低余额不能因低于十万而被误判成 OCR 截断。"""
        任务 = 更新家乡资源状态任务.__new__(更新家乡资源状态任务)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((160, 210, 3), dtype=np.uint8)),
            ),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务.上下文 = 上下文
        任务.ocr引擎 = Mock(return_value=(
            [
                ([[94, 24], [161, 24], [161, 42], [94, 42]], "2339914", 0.99),
                ([[128, 82], [163, 82], [163, 99], [128, 99]], "2318", 0.99),
                ([[128, 137], [164, 137], [164, 154], [128, 154]], "1707", 0.99),
            ],
            None,
        ))

        with patch(
            "任务流程.更新主世界账号资源状态.单行资源识别",
            # 低于 2m 会触发一次完整单行复核，复核仍应保留真实四位数。
            side_effect=[
                2_339_914, 2_318, 1_707,
                2_339_914, 2_318,
            ],
        ):
            结果 = 任务.识别当前资源(上下文)

        self.assertTrue(结果["识别成功"])
        self.assertEqual(结果["金币"], 2_339_914)
        self.assertEqual(结果["圣水"], 2_318)
        self.assertEqual(结果["黑油"], 1_707)


if __name__ == "__main__":
    unittest.main()
