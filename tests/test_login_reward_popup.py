"""断线重登后的胜利之星奖励确认框：登录检测要按文字+按钮确认后点击，不能停机。

实机 2026-11-23 20:18：重登 → 点“跳过宝箱动画” → 弹出“仍要跳过”确认（多按钮弹窗）
→ 旧逻辑“登录时出现多按钮弹窗…停止输入并保留画面”，整夜刷资源中断。
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from 任务流程.检测游戏登录状态 import 检测游戏登录状态任务


def _框(x, y):
    return [[x - 20, y - 8], [x + 20, y - 8], [x + 20, y + 8], [x - 20, y + 8]]


class 战后奖励确认测试(unittest.TestCase):
    def _上下文(self, *文字):
        结果 = [(_框(400, 300 + 序号 * 20), 文, 0.9) for 序号, 文 in enumerate(文字)]
        return SimpleNamespace(获取OCR引擎=Mock(return_value=Mock(return_value=(结果, None))))

    def test_仍要跳过确认框交给奖励识别器(self):
        上下文 = self._上下文("跳过宝箱动画？", "奖励仍会发放，仍要跳过吗", "取消", "确定")
        识别 = SimpleNamespace(识别战后奖励按钮=Mock(return_value=("确认跳过", (486, 389))))
        图 = np.zeros((600, 800, 3), np.uint8)
        self.assertEqual(
            检测游戏登录状态任务._定位战后奖励确认按钮(上下文, 识别, 图), ("确认跳过", (486, 389))
        )
        _, 参数 = 识别.识别战后奖励按钮.call_args
        self.assertFalse(参数["奖励动画处理中"])  # 只接受文字确认的操作

    def test_画面有宝石字样不点(self):
        上下文 = self._上下文("跳过宝箱动画", "仍要跳过", "宝石")
        识别 = SimpleNamespace(识别战后奖励按钮=Mock(return_value=("确认跳过", (486, 389))))
        self.assertIsNone(检测游戏登录状态任务._定位战后奖励确认按钮(上下文, 识别, np.zeros((600, 800, 3), np.uint8)))
        识别.识别战后奖励按钮.assert_not_called()

    def test_非奖励操作或识别失败都不点(self):
        上下文 = self._上下文("升级", "确定")
        for 返回 in (None, ("跳过动画", (700, 560))):
            识别 = SimpleNamespace(识别战后奖励按钮=Mock(return_value=返回))
            self.assertIsNone(检测游戏登录状态任务._定位战后奖励确认按钮(上下文, 识别, np.zeros((600, 800, 3), np.uint8)))

    def test_真实识别器要求文字和绿色按钮同时成立(self):
        from 模块.检测.页面识别器 import 页面识别器
        from 模块.检测.模板匹配器 import 模板匹配引擎
        识别 = 页面识别器(模板匹配引擎())
        黑图 = np.zeros((600, 800, 3), np.uint8)
        OCR = [(_框(400, 250), "跳过宝箱动画？", 0.9), (_框(400, 300), "仍要跳过吗", 0.9)]
        # 没有绿色确认按钮 → 不返回点击点
        self.assertIsNone(识别.识别战后奖励按钮(黑图, OCR, 奖励动画处理中=False))
        # 只有按钮没有文字 → 也不返回
        self.assertIsNone(识别.识别战后奖励按钮(黑图, [(_框(486, 389), "确定", 0.9)], 奖励动画处理中=False))


if __name__ == "__main__":
    unittest.main()
