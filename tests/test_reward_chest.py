"""胜利之星奖励宝箱：敲到锤子计数 3 → 再敲 3 次 → 等 3 秒 → 敲 1 次 → 确认回到主世界。"""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from 任务流程.主世界打鱼 import 奖励宝箱 as 宝箱


def _框():
    return [[0, 0], [10, 0], [10, 10], [0, 10]]


class 假上下文:
    def __init__(self, 计数序列, 全屏文字="", 回主世界=True):
        self.点击记录, self.延时记录, self.日志 = [], [], []
        self._计数 = list(计数序列)
        self._全屏文字 = 全屏文字
        self._回主世界 = 回主世界
        self.op = SimpleNamespace(获取屏幕图像cv=lambda *_a, **_k: np.zeros((600, 800, 3), np.uint8))

    def 获取OCR引擎(self):
        def 识别(图像, **_k):
            if 图像.shape[:2] == (600, 800):  # 全屏：只用于宝石字样检查
                return ([(_框(), self._全屏文字, 0.9)] if self._全屏文字 else [], None)
            值 = self._计数.pop(0) if self._计数 else None
            return ([(_框(), str(值), 0.9)] if 值 is not None else [], None)
        return 识别

    def 点击已确认安全按钮(self, x, y, 延时=100):
        self.点击记录.append((x, y))
        return True

    def 脚本延时(self, 毫秒):
        self.延时记录.append(毫秒)

    def 置脚本状态(self, 文本, *_a, **_k):
        self.日志.append(文本)

    def 识别点击画面(self, 强制=False):
        return SimpleNamespace(页面="主世界主页" if self._回主世界 else "未知")


class 奖励宝箱测试(unittest.TestCase):
    def setUp(self):
        self._旧目录 = os.getcwd()
        os.chdir(tempfile.mkdtemp())  # 截图写到临时目录

    def tearDown(self):
        os.chdir(self._旧目录)

    def test_计数降到3后再敲3次_等3秒_敲1次_回到主世界(self):
        上下文 = 假上下文(["5", "4", "x3"])
        self.assertTrue(宝箱.开启奖励宝箱(上下文))
        # 3 次敲到计数 3 + 补敲 3 次 + 收尾 1 次
        self.assertEqual(len(上下文.点击记录), 7)
        self.assertTrue(all(点 == 宝箱.宝箱点击点 for 点 in 上下文.点击记录))
        self.assertIn(3000, 上下文.延时记录)
        self.assertIn("已敲开宝箱并确认回到主世界", 上下文.日志[-1])
        self.assertTrue(any(f.endswith("等待后.png") for f in os.listdir(os.path.join("数据集", "奖励宝箱"))))

    def test_第一下就读到3(self):
        上下文 = 假上下文(["3"])
        self.assertTrue(宝箱.开启奖励宝箱(上下文))
        self.assertEqual(len(上下文.点击记录), 5)

    def test_画面有宝石字样不敲(self):
        上下文 = 假上下文(["3"], 全屏文字="使用宝石立即开启")
        self.assertFalse(宝箱.开启奖励宝箱(上下文))
        self.assertEqual(上下文.点击记录, [])

    def test_计数一直不下降时放弃改走跳过(self):
        上下文 = 假上下文(["7"] * 20)
        self.assertFalse(宝箱.开启奖励宝箱(上下文))
        self.assertEqual(len(上下文.点击记录), 宝箱.最多敲击次数)
        self.assertIn("改走跳过动画", 上下文.日志[-1])

    def test_敲完没回主世界返回失败(self):
        上下文 = 假上下文(["3"], 回主世界=False)
        with patch.object(宝箱, "回主世界等待秒", 0.01):
            self.assertFalse(宝箱.开启奖励宝箱(上下文))

    def test_读取锤子计数(self):
        self.assertEqual(宝箱.读取锤子计数([(_框(), "×3", 0.9)]), 3)
        self.assertEqual(宝箱.读取锤子计数([(_框(), "12", 0.9), (_框(), "4", 0.9)]), 4)
        self.assertIsNone(宝箱.读取锤子计数([(_框(), "领取", 0.9)]))


if __name__ == "__main__":
    unittest.main()
