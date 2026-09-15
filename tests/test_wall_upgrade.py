import unittest
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.升级城墙 import 城墙升级任务


class 刷墙识别测试(unittest.TestCase):
    def setUp(self):
        self.任务 = 城墙升级任务.__new__(城墙升级任务)

    def test_OCR坐标使用真实包围框而不是固定右边界(self):
        坐标 = self.任务.解析OCR坐标(
            [[20, 30], [84, 30], [84, 58], [20, 58]]
        )
        self.assertEqual(坐标, (20, 30, 84, 58))

    def test_墙体关键词兼容中英文(self):
        for 文本 in ("城墙", "城牆", "围墙", "围牆", "Wall", "WALLS"):
            with self.subTest(文本=文本):
                self.assertTrue(self.任务.文本是否城墙(文本))
        self.assertFalse(self.任务.文本是否城墙("防御塔"))

    def test_候选墙段点位限制在地图搜索区域(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        图像[:] = (50, 155, 45)
        # 模拟一条等距视角下的金色墙线和相邻灰色墙线。
        cv2.line(图像, (110, 180), (390, 360), (0, 190, 255), 8)
        cv2.line(图像, (420, 360), (650, 220), (80, 80, 95), 8)

        候选点 = self.任务.生成城墙候选点(图像)

        self.assertTrue(候选点)
        左, 上, 右, 下 = self.任务.墙体搜索区域
        self.assertTrue(all(左 <= x < 右 and 上 <= y < 下 for x, y in 候选点))

    def test_点击候选点后必须先确认城墙才执行升级(self):
        self.任务.执行升级 = Mock(return_value=True)
        上下文 = SimpleNamespace(置脚本状态=Mock())
        OCR结果 = [([[180, 450], [230, 450], [230, 470], [180, 470]], "城墙", 0.98)]

        self.assertTrue(self.任务.处理已选中的城墙(上下文, OCR结果, (205, 460)))
        参数 = self.任务.执行升级.call_args
        self.assertEqual(参数.args[:5], (上下文, 195, 450, 215, 470))
        self.assertEqual(参数.kwargs, {"已选中": True, "OCR结果": OCR结果})

    def test_非城墙候选不会误触发升级(self):
        self.任务.执行升级 = Mock(return_value=True)
        上下文 = SimpleNamespace(置脚本状态=Mock())
        OCR结果 = [([[180, 450], [230, 450], [230, 470], [180, 470]], "加农炮", 0.98)]

        self.assertFalse(self.任务.处理已选中的城墙(上下文, OCR结果, (205, 460)))
        self.任务.执行升级.assert_not_called()

    def test_刷墙任务读取上下文停止事件(self):
        上下文 = SimpleNamespace(
            停止事件=threading.Event(),
            置脚本状态=Mock(),
        )
        上下文.停止事件.set()
        self.任务.上下文 = 上下文
        self.任务.检查功能开启 = Mock(return_value=True)
        self.任务.刷一次墙 = Mock()

        self.assertTrue(self.任务.执行())
        self.任务.刷一次墙.assert_not_called()

    def test_能从墙体面板读取两种资源费用(self):
        OCR结果 = [
            ([[411, 450], [471, 450], [471, 464], [411, 464]], "So00000", 0.80),
            ([[500, 450], [559, 450], [559, 464], [500, 464]], "5000000", 0.80),
        ]
        self.assertEqual(self.任务.解析城墙升级费用(OCR结果), (5000000, 5000000))
        变形OCR结果 = [
            ([[411, 450], [471, 450], [471, 464], [411, 464]], "000000S", 0.80),
        ]
        self.assertEqual(self.任务.解析城墙升级费用(变形OCR结果), (5000000, None))

    def test_刷墙升级始终使用主世界资源模板(self):
        金币模板, 圣水模板 = self.任务.获取城墙升级资源模板()

        self.assertIn("升级建筑的金币小图标1.bmp", 金币模板)
        self.assertIn("升级建筑的圣水小图标1.bmp", 圣水模板)
        self.assertNotIn("夜.bmp", 金币模板)
        self.assertNotIn("夜.bmp", 圣水模板)

    def test_资源不足只返回主世界且不点击宝石或商店(self):
        键盘 = Mock()
        上下文 = SimpleNamespace(
            键盘=键盘,
            点击=Mock(),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )

        self.任务._标记资源不足并返回主世界(上下文, "金币不足")

        self.assertTrue(上下文.刷墙需要资源)
        键盘.按字符按压.assert_called_once_with("esc")
        上下文.点击.assert_not_called()
        日志 = " ".join(调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list)
        self.assertIn("禁止使用宝石", 日志)
        self.assertIn("禁止进入商店", 日志)

    def test_资源不足时没有安全可点击资源(self):
        self.assertIsNone(
            self.任务.选择可安全使用的升级资源(
                1_000_000,
                2_000_000,
                5_000_000,
                5_000_000,
                True,
                True,
            )
        )
        self.assertEqual(
            self.任务.选择可安全使用的升级资源(
                6_000_000,
                2_000_000,
                5_000_000,
                5_000_000,
                True,
                True,
            ),
            "金币",
        )

    def test_缺少家乡资源状态时返回未知而不是零(self):
        状态 = SimpleNamespace(状态数据={})
        上下文 = SimpleNamespace(
            机器人标志="robot_1",
            数据库=SimpleNamespace(获取最新完整状态=Mock(return_value=状态)),
        )

        self.assertEqual(self.任务.获取当前墙体资源(上下文), (None, None))

    def test_资源未知时执行升级不点击任何入口(self):
        状态 = SimpleNamespace(状态数据={})
        上下文 = SimpleNamespace(
            机器人标志="robot_1",
            数据库=SimpleNamespace(获取最新完整状态=Mock(return_value=状态)),
            点击=Mock(),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )

        self.assertFalse(
            self.任务.执行升级(
                上下文,
                0,
                0,
                10,
                10,
                已选中=True,
                OCR结果=[],
            )
        )
        上下文.点击.assert_not_called()
        状态文本 = " ".join(调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list)
        self.assertIn("禁止点击城墙升级入口", 状态文本)

    def test_执行升级资源不足不会点击资源入口(self):
        状态 = SimpleNamespace(
            状态数据={"家乡资源": {"金币": 1_000_000, "圣水": 2_000_000}}
        )
        上下文 = SimpleNamespace(
            机器人标志="robot_1",
            数据库=SimpleNamespace(获取最新完整状态=Mock(return_value=状态)),
            键盘=Mock(),
            点击=Mock(),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        self.任务.识别城墙升级资源按钮 = Mock(return_value={
            "金币": True,
            "金币点击点": (447, 484),
            "圣水": True,
            "圣水点击点": (534, 484),
        })
        self.任务.确认城墙升级提交 = Mock()
        OCR结果 = [
            ([[411, 450], [471, 450], [471, 464], [411, 464]], "5000000", 0.80),
            ([[500, 450], [559, 450], [559, 464], [500, 464]], "5000000", 0.80),
        ]

        self.assertFalse(
            self.任务.执行升级(
                上下文,
                0,
                0,
                10,
                10,
                已选中=True,
                OCR结果=OCR结果,
            )
        )
        self.assertTrue(上下文.刷墙需要资源)
        上下文.点击.assert_not_called()
        self.任务.确认城墙升级提交.assert_not_called()

    def test_能读取墙体等级并识别资源不足(self):
        OCR结果 = [
            ([[250, 416], [390, 416], [390, 443], [250, 443]], "城墙（16级-）", 0.95),
            ([[411, 450], [471, 450], [471, 464], [411, 464]], "5000000", 0.80),
            ([[500, 450], [559, 450], [559, 464], [500, 464]], "5000000", 0.80),
            ([[420, 498], [470, 498], [470, 515], [420, 515]], "升级", 0.95),
        ]

        self.assertEqual(self.任务.解析城墙等级(OCR结果), 16)
        状态 = self.任务.解析城墙状态(OCR结果, 当前金币=3_000_000, 当前圣水=4_000_000)
        self.assertEqual(状态["状态"], "资源不足")

    def test_满级墙体不会进入升级候选(self):
        OCR结果 = [
            ([[250, 416], [390, 416], [390, 443], [250, 443]], "城墙（16级-）", 0.95),
            ([[420, 498], [470, 498], [470, 515], [420, 515]], "已满级", 0.95),
        ]
        状态 = self.任务.解析城墙状态(OCR结果, 当前金币=99_000_000, 当前圣水=99_000_000)
        self.assertEqual(状态["状态"], "已满级")

    def test_最低等级墙优先且资源不足不能跳到高等级(self):
        墙体记录 = [
            {"坐标": [500, 300], "等级": 16, "状态": "可升级"},
            {"坐标": [300, 300], "等级": 14, "状态": "资源不足"},
            {"坐标": [200, 300], "等级": 13, "状态": "已满级"},
        ]
        候选 = self.任务.选择最低等级墙段(墙体记录)
        self.assertEqual([记录["等级"] for 记录 in 候选], [14, 16])

    def test_能从升级确认框定位确认按钮(self):
        OCR结果 = [
            ([[328, 68], [468, 68], [468, 90], [328, 90]], "将城墙升至17级？", 0.95),
            ([[570, 465], [598, 465], [598, 483], [570, 483]], "确认", 0.95),
        ]
        self.assertEqual(self.任务.定位城墙升级确认按钮(OCR结果), (584, 474))

    def test_确认框消失后才报告升级提交成功(self):
        确认OCR = [
            ([[328, 68], [468, 68], [468, 90], [328, 90]], "将城墙升至17级？", 0.95),
            ([[570, 465], [598, 465], [598, 483], [570, 483]], "确认", 0.95),
        ]
        上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(),
            脚本延时=Mock(),
        )
        self.任务.执行OCR识别 = Mock(side_effect=[确认OCR, []])
        self.assertTrue(self.任务.确认城墙升级提交(上下文))
        上下文.点击.assert_called_once_with(584, 474, 延时=650, 是否精确点击=True)


if __name__ == "__main__":
    unittest.main()
