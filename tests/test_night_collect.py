import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.夜世界.收集圣水车 import 收集圣水车任务


class 夜世界圣水车测试(unittest.TestCase):
    def _任务(self, 屏幕):
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕)),
            置脚本状态=Mock(),
        )
        任务 = object.__new__(收集圣水车任务)
        任务.上下文 = 上下文
        return 任务

    def test_动态紫色气泡优先于旧船偏移(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 构造和实机一致的紫色收集气泡，位于地图区域内。
        cv2.circle(屏幕, (484, 224), 18, (180, 60, 220), -1)
        任务 = self._任务(屏幕)

        候选 = 任务._生成圣水车候选点(692, 7)

        self.assertEqual(候选[0][2], "船模板兼容偏移1")
        self.assertIn((484, 224, "动态紫色资源气泡"), 候选)

    def test_所有候选点都在参考画布内且固定偏移不会越界(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        任务 = self._任务(屏幕)

        候选 = 任务._生成圣水车候选点(10, 0)

        self.assertTrue(候选)
        self.assertTrue(all(12 <= x <= 788 and 12 <= y <= 588 for x, y, _ in 候选))

    def test_船模板覆盖全部变体(self):
        for 编号 in range(1, 13):
            self.assertIn(f"夜世界的船{编号}.bmp", 收集圣水车任务.船模板路径)

    def test_只识别右上角明确红色关闭按钮(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        # OpenCV 使用 BGR；用红色方块模拟游戏内详情面板的关闭按钮。
        cv2.rectangle(屏幕, (660, 12), (716, 68), (0, 0, 220), -1)

        关闭点 = 收集圣水车任务._检测详情面板关闭点(屏幕)

        self.assertIsNotNone(关闭点)
        self.assertTrue(650 <= 关闭点[0] <= 730)
        self.assertTrue(10 <= 关闭点[1] <= 80)

    def test_主页没有红色关闭按钮时不发送关闭输入(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)

        self.assertIsNone(收集圣水车任务._检测详情面板关闭点(屏幕))

    def test_简繁体圣水车标题都可确认(self):
        self.assertTrue(收集圣水车任务._是否圣水车标题([([], "聖水車", 0.99)]))
        self.assertTrue(收集圣水车任务._是否圣水车标题([([], "圣水车", 0.99)]))
        self.assertFalse(收集圣水车任务._是否圣水车标题([([], "雙管加農炮", 0.99)]))


if __name__ == "__main__":
    unittest.main()
