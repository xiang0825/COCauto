import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from 任务流程.基础任务框架 import 任务上下文
from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务
from 任务流程.主世界打鱼.搜索页面识别 import 搜索页面识别器


def 搜索画面():
    画面 = np.zeros((600, 800, 3), dtype=np.uint8)
    cv2.rectangle(画面, (665, 390), (792, 464), (0, 180, 245), -1)
    return 画面


class 搜索按钮护栏测试(unittest.TestCase):
    def test_偏左低分绿色地图只可暂作入口候选不可点击(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.fillPoly(画面, [np.array([
            (585, 380), (693, 380), (693, 390),
            (615, 390), (615, 431), (585, 431),
        ])], (40, 190, 40))
        命中, 坐标, 依据, 分数 = 搜索页面识别器.查找下一个按钮(画面)
        self.assertTrue(命中)
        self.assertLess(坐标[0], 搜索页面识别器.点击安全最左x)
        self.assertFalse(搜索页面识别器.按钮证据可信(依据, 分数))

    def test_实机中等分橙色及文字模板可通过两帧复核(self):
        for 依据, 分数 in (("橙黄色按钮", 0.80), ("模板下一个.bmp", 0.64)):
            with self.subTest(依据=依据):
                画面 = 搜索画面()
                上下文 = SimpleNamespace(
                    op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=画面)),
                    _获取点击页面识别器=lambda: SimpleNamespace(
                        识别=lambda *_参数, **_关键字: SimpleNamespace(页面="战斗结算")
                    ),
                    获取模板识别器=lambda: None,
                    点击已确认安全按钮=Mock(return_value=True),
                    脚本延时=Mock(),
                    置脚本状态=Mock(),
                )
                with patch.object(
                    搜索页面识别器, "查找下一个按钮",
                    return_value=(True, (728, 428), 依据, 分数),
                ):
                    self.assertTrue(任务上下文.点击已确认搜索按钮(上下文, 728, 428))
                上下文.点击已确认安全按钮.assert_called_once()

    def test_入场弱候选后重试到可靠按钮(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.模板识别 = None
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=搜索画面())),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            点击已确认搜索按钮=Mock(return_value=True),
        )
        with patch.object(
            搜索页面识别器, "查找下一个按钮",
            side_effect=[
                (True, (639, 406), "绿色按钮", 0.33),
                (True, (728, 428), "橙黄色按钮", 0.80),
            ],
        ):
            self.assertTrue(任务.点击下一个按钮(上下文))
        上下文.点击已确认搜索按钮.assert_called_once_with(728, 428)
        上下文.脚本延时.assert_called_once_with(600)

    def test_弱绿色候选持续存在也不盲点(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.模板识别 = None
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=搜索画面())),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            点击已确认搜索按钮=Mock(return_value=True),
        )
        with patch.object(
            搜索页面识别器, "查找下一个按钮",
            return_value=(True, (639, 406), "绿色按钮", 0.33),
        ):
            self.assertFalse(任务.点击下一个按钮(上下文))
        上下文.点击已确认搜索按钮.assert_not_called()
        self.assertEqual(上下文.op.获取屏幕图像cv.call_count, 8)

    def test_弱绿色候选不遮蔽可靠文字模板(self):
        with patch.object(
            搜索页面识别器, "_按颜色查找",
            return_value=(True, (639, 406), "绿色按钮", 0.33),
        ), patch.object(
            搜索页面识别器, "_按模板查找",
            return_value=(True, (731, 414), "模板下一个.bmp", 0.64),
        ):
            self.assertEqual(
                搜索页面识别器.查找下一个按钮(搜索画面()),
                (True, (731, 414), "模板下一个.bmp", 0.64),
            )

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
