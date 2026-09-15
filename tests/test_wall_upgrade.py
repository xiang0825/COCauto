import unittest
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

    def test_能从墙体面板读取两种资源费用(self):
        OCR结果 = [
            ([[411, 450], [471, 450], [471, 464], [411, 464]], "So00000", 0.80),
            ([[500, 450], [559, 450], [559, 464], [500, 464]], "5000000", 0.80),
        ]
        self.assertEqual(self.任务.解析城墙升级费用(OCR结果), (5000000, 5000000))


if __name__ == "__main__":
    unittest.main()
