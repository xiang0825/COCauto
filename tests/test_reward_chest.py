"""胜利之星奖励宝箱：按实机截图校准的识别与敲开流程。"""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from 任务流程.主世界打鱼 import 奖励宝箱 as 宝箱

素材 = Path(__file__).parent / "fixtures" / "奖励宝箱"


def _读(名称):
    return cv2.imdecode(np.fromfile(str(素材 / 名称), np.uint8), cv2.IMREAD_COLOR)


def _框(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


class 宝箱页识别测试(unittest.TestCase):
    def test_实机截图的黄色擀面杖根数(self):
        self.assertEqual(宝箱.识别宝箱页(_读("宝箱页_4根.png")), 4)
        self.assertEqual(宝箱.识别宝箱页(_读("宝箱页_3根.png")), 3)
        self.assertEqual(宝箱.识别宝箱页(_读("宝箱页_1根.png")), 1)

    def test_奖励页和其他画面不是宝箱页(self):
        self.assertIsNone(宝箱.识别宝箱页(_读("奖励页_繼續.png")))
        self.assertIsNone(宝箱.识别宝箱页(np.zeros((600, 800, 3), np.uint8)))
        self.assertIsNone(宝箱.识别宝箱页(np.full((600, 800, 3), 200, np.uint8)))

    def test_定位继续按钮(self):
        结果 = [(_框(300, 440, 480, 470), "物品已運送到臨時倉庫。", 0.9),
              (_框(360, 500, 420, 525), "繼續", 0.95)]
        self.assertEqual(宝箱.定位继续按钮(结果), (390, 512))
        self.assertIsNone(宝箱.定位继续按钮([(_框(0, 0, 9, 9), "繼續", 0.9),
                                        (_框(0, 0, 9, 9), "使用寶石", 0.9)]))
        self.assertIsNone(宝箱.定位继续按钮([(_框(0, 0, 9, 9), "4倍戰鬥糕點", 0.9)]))


class 假上下文:
    """按点击推进画面：4 根 → 3 根 → 1 根（再敲不变）→ 开箱后奖励页。"""

    def __init__(self, 画面序列, 奖励页OCR=None, 回主世界=True):
        self.点击记录, self.延时记录, self.日志 = [], [], []
        self._画面 = list(画面序列)
        self._奖励页OCR = 奖励页OCR if 奖励页OCR is not None else [
            (_框(360, 500, 420, 525), "繼續", 0.95)]
        self._回主世界 = 回主世界
        self.op = SimpleNamespace(获取屏幕图像cv=self._截图)

    def _截图(self, *_a, **_k):
        return self._画面[0]

    def 获取OCR引擎(self):
        return lambda *_a, **_k: (self._奖励页OCR, None)

    def 点击已确认安全按钮(self, x, y, 延时=100):
        self.点击记录.append((x, y))
        if len(self._画面) > 1:
            self._画面.pop(0)
        return True

    def 脚本延时(self, 毫秒):
        self.延时记录.append(毫秒)

    def 置脚本状态(self, 文本, *_a, **_k):
        self.日志.append(文本)

    def 识别点击画面(self, 强制=False):
        return SimpleNamespace(页面="主世界主页" if self._回主世界 else "未知")


class 敲宝箱流程测试(unittest.TestCase):
    def setUp(self):
        self._旧目录 = os.getcwd()
        os.chdir(tempfile.mkdtemp())

    def tearDown(self):
        os.chdir(self._旧目录)

    def test_敲到3根_再敲3次_等3秒_点繼續_回主世界(self):
        四, 三, 一, 奖励 = (_读(n) for n in ("宝箱页_4根.png", "宝箱页_3根.png", "宝箱页_1根.png", "奖励页_繼續.png"))
        上下文 = 假上下文([四, 三, 一, 一, 奖励])
        self.assertTrue(宝箱.开启奖励宝箱(上下文))
        敲宝箱 = [点 for 点 in 上下文.点击记录 if 点 == 宝箱.宝箱点击点]
        self.assertEqual(len(敲宝箱), 1 + 3)           # 敲到 3 根 1 次 + 补敲 3 次
        self.assertEqual(上下文.点击记录[-1], (390, 512))  # 最后点“繼續”
        self.assertIn(3000, 上下文.延时记录)
        self.assertIn("回到主世界", 上下文.日志[-1])

    def test_领取后等宝箱页出现再敲(self):
        黑 = np.zeros((600, 800, 3), np.uint8)
        三, 一, 奖励 = (_读(n) for n in ("宝箱页_3根.png", "宝箱页_1根.png", "奖励页_繼續.png"))
        上下文 = 假上下文([黑, 三, 一, 奖励])
        原截图 = 上下文._截图
        次数 = [0]

        def 截图(*a, **k):  # 头两帧还是过场黑屏，之后出现宝箱页
            次数[0] += 1
            if 次数[0] == 2 and len(上下文._画面) > 1 and 上下文._画面[0] is 黑:
                上下文._画面.pop(0)
            return 原截图()
        上下文.op.获取屏幕图像cv = 截图
        self.assertTrue(宝箱.开启奖励宝箱(上下文, 等待出现秒=5.0))
        self.assertIn(500, 上下文.延时记录)

    def test_不是宝箱页什么都不点(self):
        上下文 = 假上下文([np.zeros((600, 800, 3), np.uint8)])
        self.assertFalse(宝箱.开启奖励宝箱(上下文))
        self.assertEqual(上下文.点击记录, [])

    def test_敲了不变化时有上限(self):
        四 = _读("宝箱页_4根.png")
        上下文 = 假上下文([四])
        self.assertFalse(宝箱.开启奖励宝箱(上下文))
        self.assertEqual(len(上下文.点击记录), 宝箱.最多敲击次数)

    def test_找不到繼續按钮不乱点(self):
        三, 奖励 = _读("宝箱页_3根.png"), _读("奖励页_繼續.png")
        上下文 = 假上下文([三, 奖励], 奖励页OCR=[])
        with patch.object(宝箱, "继续按钮等待秒", 0.01):
            self.assertFalse(宝箱.开启奖励宝箱(上下文))
        self.assertEqual(len(上下文.点击记录), 3)  # 只有补敲 3 次

    def test_奖励页有宝石字样不点(self):
        三, 奖励 = _读("宝箱页_3根.png"), _读("奖励页_繼續.png")
        上下文 = 假上下文([三, 奖励], 奖励页OCR=[(_框(0, 0, 9, 9), "繼續", 0.9),
                                            (_框(0, 0, 9, 9), "購買", 0.9)])
        with patch.object(宝箱, "继续按钮等待秒", 0.01):
            self.assertFalse(宝箱.开启奖励宝箱(上下文))


if __name__ == "__main__":
    unittest.main()
