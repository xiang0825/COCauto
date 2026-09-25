import unittest

import numpy as np

from 任务流程.天鹰火炮成就.天鹰火炮检测器 import 天鹰火炮检测器


class 天鹰检测器输出解析测试(unittest.TestCase):
    def _检测器(self):
        return 天鹰火炮检测器.__new__(天鹰火炮检测器)

    def test_多类别通道取最高类别分数而不是固定第零类(self):
        输出 = np.zeros((1, 84, 2), dtype=np.float32)
        输出[0, :, 0] = 0
        输出[0, 0:4, 0] = (320, 240, 80, 60)
        输出[0, 4 + 7, 0] = 0.91
        输出[0, 4, 0] = 0.03
        输出[0, 0:4, 1] = (100, 100, 40, 40)
        输出[0, 4 + 2, 1] = 0.20

        结果 = self._检测器().解析输出(输出, 0.25)

        self.assertEqual(len(结果), 1)
        self.assertEqual(结果[0]["类别"], 7)
        self.assertAlmostEqual(结果[0]["置信度"], 0.91, places=5)
        self.assertEqual(
            (结果[0]["x1"], 结果[0]["y1"], 结果[0]["x2"], 结果[0]["y2"]),
            (280.0, 210.0, 360.0, 270.0),
        )

    def test_候选维度在末轴的导出格式也能解析(self):
        输出 = np.zeros((1, 2, 5), dtype=np.float32)
        输出[0, 0] = (320, 240, 80, 60, 0.8)
        输出[0, 1] = (100, 100, -1, 40, 0.9)

        结果 = self._检测器().解析输出(输出, 0.25)

        self.assertEqual(len(结果), 1)
        self.assertAlmostEqual(结果[0]["置信度"], 0.8, places=5)

    def test_非有限候选不会让解析器抛异常(self):
        输出 = np.full((1, 5, 1), np.nan, dtype=np.float32)

        self.assertEqual(self._检测器().解析输出(输出), [])


if __name__ == "__main__":
    unittest.main()
