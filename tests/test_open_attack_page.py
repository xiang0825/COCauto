import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from 任务流程.主世界打鱼.打开进攻页面 import 打开进攻页面任务
from 任务流程.主世界打鱼.搜索页面识别 import 搜索页面识别器
from 任务流程.主世界打鱼.进攻 import 进攻任务
from 任务流程.夜世界.夜世界打鱼.打开进攻页面任务 import 打开进攻页面


class 打开进攻页面测试(unittest.TestCase):
    @staticmethod
    def 军队配置画面():
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 与当前 CoC 绿色“攻击!”按钮相同的高饱和黄绿色区域。
        cv2.rectangle(画面, (630, 515), (780, 555), (73, 227, 154), -1)
        return 画面

    def test_攻击按钮使用动态识别而不是固定坐标(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        结果 = 任务._检测攻击按钮(self.军队配置画面())
        self.assertIsNotNone(结果)
        self.assertAlmostEqual(结果[0], 705, delta=3)
        self.assertAlmostEqual(结果[1], 535, delta=3)

    def test_点击后必须确认进入搜索页面(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=self.军队配置画面())
            ),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        with patch.object(
            任务, "_是否出现下一个", side_effect=[False, True, True]
        ):
            self.assertTrue(任务._等待并点击攻击按钮(上下文))

        上下文.点击.assert_called_once_with(
            705, 535, 延时=700, 是否精确点击=True
        )

    def test_启动时已经在战斗页不再点击主世界入口(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            识别点击画面=Mock(
                return_value=SimpleNamespace(页面="战斗中")
            ),
            点击=Mock(),
            停止事件=threading.Event(),
        )

        任务.上下文 = 上下文
        self.assertTrue(任务.执行())
        self.assertTrue(上下文._入口已进入战斗)
        上下文.点击.assert_not_called()

    def test_攻击按钮点击后直接进入战斗会交给下兵流程(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        页面状态 = iter((
            SimpleNamespace(页面="未知"),
            SimpleNamespace(页面="战斗中"),
        ))
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=self.军队配置画面())
            ),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            识别点击画面=Mock(side_effect=lambda **_: next(页面状态)),
        )

        self.assertTrue(任务._等待并点击攻击按钮(上下文))
        self.assertTrue(上下文._入口已进入战斗)
        上下文.点击.assert_called_once_with(
            705, 535, 延时=700, 是否精确点击=True
        )

    def test_繁体下一個按钮通过颜色和位置识别(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 模拟实机搜索页的橙黄色“下一個”按钮；文字繁简不影响识别。
        cv2.rectangle(画面, (664, 389), (793, 466), (80, 190, 245), -1)
        命中, 中心, 依据, 分数 = 搜索页面识别器.查找下一个按钮(画面)
        self.assertTrue(命中)
        self.assertAlmostEqual(中心[0], 729, delta=5)
        self.assertAlmostEqual(中心[1], 428, delta=5)
        self.assertIn("按钮", 依据)
        self.assertGreaterEqual(分数, 0.30)

    def test_军队页底部攻击按钮不被当成下一個按钮(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(画面, (630, 515), (780, 555), (73, 227, 154), -1)
        命中, _, _, _ = 搜索页面识别器.查找下一个按钮(画面)
        self.assertFalse(命中)

    def test_兵栏第一格避开结束战斗按钮并覆盖当前实机卡牌(self):
        第一格 = 进攻任务.兵栏槽位[0][1]
        第二格 = 进攻任务.兵栏槽位[1][1]
        self.assertGreaterEqual(第一格[0], 50)
        self.assertLessEqual(第一格[1], 500)
        self.assertGreater(第二格[0], 第一格[0])
        self.assertEqual(len(进攻任务.兵栏槽位), 8)

    def test_兵栏空槽OCR的XO不会把等级读成兵量(self):
        任务 = 进攻任务.__new__(进攻任务)
        self.assertEqual(任务._识别槽位数量(np.zeros((20, 20, 3), dtype=np.uint8), "XO|12"), 0)

    def test_夜世界开始进攻兼容简体和繁体OCR(self):
        self.assertTrue(打开进攻页面._OCR包含文本(
            [[[[0, 0], [100, 0], [100, 30], [0, 30]], "開始進攻", 0.93]],
            ("开始进攻", "開始進攻"),
        ))
        self.assertTrue(打开进攻页面._OCR包含文本(
            [[[[0, 0], [100, 0], [100, 30], [0, 30]], "开始进攻", 0.93]],
            ("开始进攻", "開始進攻"),
        ))

    def test_夜世界立即寻找按钮补回OCR裁剪偏移(self):
        任务 = 打开进攻页面.__new__(打开进攻页面)
        任务.执行OCR识别 = Mock(return_value=[
            [[[150, 60], [230, 60], [230, 92], [150, 92]], "立即尋找！", 0.91]
        ])
        self.assertEqual(任务._查找立即寻找按钮中心(), (620, 396))

    def test_夜世界立即寻找OCR不命中时使用参考坐标(self):
        任务 = 打开进攻页面.__new__(打开进攻页面)
        任务.执行OCR识别 = Mock(return_value=[])
        self.assertIsNone(任务._查找立即寻找按钮中心())


if __name__ == "__main__":
    unittest.main()
