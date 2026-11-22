"""Regression coverage for recent Clash of Clans home and overlay screens."""
from pathlib import Path
import unittest

import cv2
import numpy as np

from 模块.检测.页面识别器 import 页面识别器
from 模块.检测.模板匹配器 import 模板匹配引擎


class 新版主世界页面识别测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.根目录 = Path(__file__).resolve().parents[1]
        cls.识别器 = 页面识别器(
            模板匹配引擎(图片库路径=cls.根目录 / "img")
        )
        图像路径 = cls.根目录 / "tests" / "fixtures" / "coc_home_18_647_5.png"
        cls.画面 = cv2.imdecode(
            np.fromfile(图像路径, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        断线图像路径 = (
            cls.根目录 / "tests" / "fixtures" / "coc_idle_disconnect_18_647_5.png"
        )
        cls.断线画面 = cv2.imdecode(
            np.fromfile(断线图像路径, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        军队配置路径 = (
            cls.根目录 / "tests" / "fixtures" / "coc_army_config_live_ui.png"
        )
        cls.军队配置画面 = cv2.imdecode(
            np.fromfile(军队配置路径, dtype=np.uint8), cv2.IMREAD_COLOR
        )

    def test_新版主世界战斗卡片与资源栏可确认主世界主页(self):
        self.assertIsNotNone(self.画面)
        世界 = self.识别器.世界识别.识别(self.画面)
        self.assertEqual(世界.当前世界, "主世界", 世界.摘要())
        self.assertGreaterEqual(世界.主世界分数, 0.70, 世界.摘要())

        页面 = self.识别器.识别(self.画面)
        self.assertEqual(页面.页面, "主世界主页", 页面.摘要())
        self.assertEqual(页面.世界, "主世界", 页面.摘要())

    def test_新版闲置断线弹窗能被明确识别(self):
        self.assertIsNotNone(self.断线画面)
        页面 = self.识别器.识别(self.断线画面)
        self.assertEqual(页面.页面, "断线弹窗", 页面.摘要())

    def test_新版军队配置页不能误判为战斗中(self):
        self.assertIsNotNone(self.军队配置画面)
        页面 = self.识别器.识别(self.军队配置画面)
        self.assertEqual(页面.页面, "军队配置页", 页面.摘要())

    def test_新版联赛概况弹窗不能误判为战斗并可定位安全关闭点(self):
        """红色联赛背景和顶部标题会同时撞上旧战斗几何规则。"""
        画面 = np.full((600, 800, 3), (52, 46, 41), dtype=np.uint8)
        cv2.rectangle(画面, (12, 125), (788, 599), (35, 24, 132), -1)
        cv2.rectangle(画面, (150, 190), (700, 222), (28, 22, 155), -1)
        for 左 in (95, 300, 505):
            cv2.rectangle(画面, (左, 70), (左 + 190, 128), (185, 175, 164), -1)
        cv2.rectangle(画面, (760, 42), (788, 79), (20, 20, 225), -1)
        cv2.line(画面, (767, 49), (781, 71), (255, 255, 255), 3)
        cv2.line(画面, (781, 49), (767, 71), (255, 255, 255), 3)
        cv2.putText(
            画面, "LEAGUE", (325, 107), cv2.FONT_HERSHEY_SIMPLEX,
            0.8, (255, 255, 255), 2, cv2.LINE_AA,
        )

        for 战斗中 in (False, True):
            with self.subTest(战斗中=战斗中):
                页面 = self.识别器.识别(画面, 战斗中=战斗中)
                self.assertEqual(页面.页面, "联赛概况弹窗", 页面.摘要())

        关闭点 = self.识别器.定位联赛概况关闭按钮(画面)
        self.assertEqual(关闭点, (774, 61))


if __name__ == "__main__":
    unittest.main()
