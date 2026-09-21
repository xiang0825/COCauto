import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from 任务流程.主世界打鱼.打开进攻页面 import 打开进攻页面任务


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
            任务, "_是否出现下一个", side_effect=[False, True]
        ):
            self.assertTrue(任务._等待并点击攻击按钮(上下文))

        上下文.点击.assert_called_once_with(
            705, 535, 延时=700, 是否精确点击=True
        )


if __name__ == "__main__":
    unittest.main()
