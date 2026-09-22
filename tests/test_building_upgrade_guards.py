import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 任务流程.建筑升级.寻找建筑 import 寻找建筑
from 任务流程.建筑升级.升级普通建筑 import (
    提取建议升级建筑名称,
    提取建议升级建筑,
    升级普通建筑任务,
)
from 任务流程.建筑升级.更新工人状态 import 更新工人状态任务


class 建筑升级边界测试(unittest.TestCase):
    def test_关闭刷资源时建筑入口仍使用主世界坐标(self):
        点击 = Mock()
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(
            设置=SimpleNamespace(是否刷主世界=False),
            点击=点击,
            滑动到建筑栏底部=Mock(),
        )

        任务.打开建筑页面(划到底部=False)

        点击.assert_called_once_with(353, 13, 延时=1000)

    def test_关闭刷资源时寻找建筑滑动仍使用主世界坐标(self):
        鼠标 = SimpleNamespace(
            移动到=Mock(),
            左键按下=Mock(),
            移动相对位置=Mock(),
            左键抬起=Mock(),
        )
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(
            设置=SimpleNamespace(是否刷主世界=False),
            鼠标=鼠标,
            脚本延时=Mock(),
        )

        任务.滑动屏幕(0)

        鼠标.移动到.assert_called_once_with(399, 116)

    def test_建筑升级面板已打开时不会重复点击入口(self):
        点击 = Mock()
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(
            设置=SimpleNamespace(是否刷主世界=False),
            点击=点击,
            置脚本状态=Mock(),
            op=SimpleNamespace(),
        )
        任务.执行OCR识别 = Mock(return_value=[
            ([[10, 10], [60, 10], [60, 30], [10, 30]], "升级中", 0.95),
            ([[10, 40], [60, 40], [60, 60], [10, 60]], "建升级", 0.95),
        ])

        任务.打开建筑页面(划到底部=False)

        点击.assert_not_called()
        任务.上下文.置脚本状态.assert_called_once()

    def test_主世界单独出现升级中不会被当成建筑面板(self):
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(
            设置=SimpleNamespace(是否刷主世界=False),
            点击=Mock(),
            置脚本状态=Mock(),
        )
        任务.执行OCR识别 = Mock(return_value=[
            ([[10, 10], [60, 10], [60, 30], [10, 30]], "升级中", 0.95),
        ])

        self.assertFalse(任务._建筑升级面板已打开())

    def test_OCR只定位底部升级按钮不接受升级中文字(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(op=SimpleNamespace())
        任务.执行OCR识别 = Mock(return_value=[
            ([[10, 10], [60, 10], [60, 30], [10, 30]], "升级中", 0.99),
            ([[520, 492], [546, 492], [546, 511], [520, 511]], "升级", 0.99),
        ])

        self.assertEqual(任务._OCR定位升级按钮(), (533, 502))

    def test_缩放模板只在限定区域且达到新版阈值时返回坐标(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: object()
            ),
            置脚本状态=Mock(),
        )
        任务.模板识别 = SimpleNamespace(
            执行最佳匹配=Mock(return_value=(0.65, (42, 58), "建筑升级界面锤子[1].bmp"))
        )

        self.assertEqual(任务._局部模板定位升级按钮(), (517, 463))

        任务.模板识别.执行最佳匹配.return_value = (0.63, (42, 58), "建筑升级界面锤子[1].bmp")
        self.assertIsNone(任务._局部模板定位升级按钮())

    def test_绿色确认按钮返回底部卡片中心(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace()
        )
        任务.执行OCR识别 = Mock(return_value=[
            ([[550, 490], [590, 490], [590, 515], [550, 515]], "確", 0.99),
        ])

        self.assertEqual(任务._定位升级确认按钮(), (570, 502))

    def test_建筑升级页面关闭时明确授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        任务.关闭建筑升级页面()

        返回.assert_called_once_with(
            "关闭建筑升级页面", 已确认可关闭面板=True
        )

    def test_绿色立即完成区域不会被当成资源确认按钮(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace()
        )
        任务.执行OCR识别 = Mock(return_value=[
            ([[423, 492], [467, 492], [467, 510], [423, 510]], "立即完成", 0.99),
        ])

        self.assertIsNone(任务._定位升级确认按钮())

    def test_确认文字被OCR误识别时使用升级确认标题(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(op=SimpleNamespace())
        任务.执行OCR识别 = Mock(return_value=[
            ([[312, 29], [483, 29], [483, 60], [312, 60]], "将聖水收集器升至17级？", 0.95),
            ([[548, 494], [574, 494], [574, 514], [548, 514]], "雅韧", 0.66),
        ])

        self.assertEqual(任务._定位升级确认按钮(), (560, 522))

    def test_建筑坐标右边界跟随OCR框而不是固定值(self):
        任务 = 寻找建筑.__new__(寻找建筑)

        self.assertEqual(
            任务.解析坐标([[10, 20], [50, 20], [50, 40], [10, 40]]),
            (229, 77, 269, 97),
        )

    def test_空OCR坐标被拒绝(self):
        任务 = 寻找建筑.__new__(寻找建筑)

        with self.assertRaises(ValueError):
            任务.解析坐标([])

    def test_建议升级标题被截断且没有其他升级标题时仍提取建筑(self):
        OCR = [
            ([[50, 20], [100, 20], [100, 40], [50, 40]], "升级中", 0.96),
            ([[50, 60], [100, 60], [100, 80], [50, 80]], "建升级", 0.98),
            ([[50, 90], [150, 90], [150, 110], [50, 110]], "圣水收集器x5", 0.96),
            ([[250, 90], [320, 90], [320, 110], [250, 110]], "8000000", 0.99),
            ([[50, 120], [130, 120], [130, 140], [50, 140]], "可使用", 0.99),
            ([[50, 150], [130, 150], [130, 170], [50, 170]], "野蛮人之王", 0.95),
        ]

        self.assertEqual(
            提取建议升级建筑名称(OCR),
            ["圣水收集器x5", "野蛮人之王"],
        )
        self.assertEqual(
            [项目[1] for 项目 in 提取建议升级建筑(OCR)],
            ["圣水收集器x5", "野蛮人之王"],
        )


class 工人状态容错测试(unittest.TestCase):
    def _创建任务(self, 状态):
        任务 = 更新工人状态任务.__new__(更新工人状态任务)
        任务.机器人标志 = "robot_1"
        任务.数据库 = SimpleNamespace(
            获取最新完整状态=Mock(return_value=SimpleNamespace(状态数据=状态))
        )
        任务.上下文 = SimpleNamespace(置脚本状态=Mock())
        return 任务

    def test_工人状态缺字段时返回False而不是抛异常(self):
        任务 = self._创建任务({"工人状态": {"空闲工人": 1}})

        self.assertFalse(任务.是否有空闲工人())
        日志 = " ".join(调用.args[0] for 调用 in 任务.上下文.置脚本状态.call_args_list)
        self.assertIn("字段缺失或无效", 日志)

    def test_工人状态字段格式错误时返回False(self):
        任务 = self._创建任务({
            "工人状态": {
                "空闲工人": "?",
                "工人总数": 5,
                "更新时间": time.time(),
            }
        })

        self.assertFalse(任务.是否有空闲工人())


if __name__ == "__main__":
    unittest.main()
