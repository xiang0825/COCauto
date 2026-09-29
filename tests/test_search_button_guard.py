import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.基础任务框架 import 任务上下文
from 任务流程.主世界打鱼.搜索页面识别 import 搜索页面识别器


def 搜索画面():
    画面 = np.zeros((600, 800, 3), dtype=np.uint8)
    cv2.rectangle(画面, (665, 390), (792, 464), (0, 180, 245), -1)
    return 画面


class 搜索按钮护栏测试(unittest.TestCase):
    def test_两帧搜索按钮可覆盖过渡帧结算误报(self):
        画面 = 搜索画面()
        命中, 坐标, _, 分数 = 搜索页面识别器.查找下一个按钮(画面)
        self.assertTrue(命中)
        self.assertGreaterEqual(分数, 0.90)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(side_effect=[画面, 画面])),
            _获取点击页面识别器=lambda: SimpleNamespace(
                识别=lambda *_参数, **_关键字: SimpleNamespace(页面="战斗结算")
            ),
            获取模板识别器=lambda: None,
            点击已确认安全按钮=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            _最近结算视觉时间=123.0,
            _战斗结束已确认=True,
            _最近点击页面结果=SimpleNamespace(页面="战斗结算"),
            _点击识别截图=画面,
        )

        self.assertTrue(任务上下文.点击已确认搜索按钮(上下文, *坐标))
        self.assertEqual(上下文.op.获取屏幕图像cv.call_count, 2)
        上下文.点击已确认安全按钮.assert_called_once_with(
            坐标[0], 坐标[1], 延时=500
        )
        self.assertEqual(上下文._最近结算视觉时间, 0.0)
        self.assertFalse(上下文._战斗结束已确认)

    def test_第二帧为断线弹窗时绝不点击(self):
        画面 = 搜索画面()
        坐标 = 搜索页面识别器.查找下一个按钮(画面)[1]
        页面 = iter(("战斗结算", "断线弹窗"))
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(side_effect=[画面, 画面])),
            _获取点击页面识别器=lambda: SimpleNamespace(
                识别=lambda *_参数, **_关键字: SimpleNamespace(页面=next(页面))
            ),
            获取模板识别器=lambda: None,
            点击已确认安全按钮=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            _最近结算视觉时间=123.0,
        )

        self.assertFalse(任务上下文.点击已确认搜索按钮(上下文, *坐标))
        上下文.点击已确认安全按钮.assert_not_called()
        self.assertEqual(上下文._最近结算视觉时间, 123.0)


if __name__ == "__main__":
    unittest.main()
