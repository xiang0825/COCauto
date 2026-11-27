"""rc165 11-27 23:2x 夜世界圣水满仓（6,500,000）时收集圣水车卡死回放。

1. 圣水车弹窗（0.97）灰色禁用收集按钮，但面板是防御奖励列表而非
   “暫無新的防禦獎勵”，旧逻辑报“空车结构已命中但文案未确认”并返回失败。
2. 外层随即用通用红 X 关闭后立刻点第 2 个候选点，弹窗尚未收起，被护栏
   拒绝 → 夜世界刷资源终止 → 安全待命；每次回夜世界必现。

现场只有回营后的夜世界主页截图（圣水车上方紫色气泡、圣水 6,500,000），
没有保存弹窗帧；弹窗文案用 OCR 桩模拟。
"""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 模块.检测.页面识别器 import 页面识别器
from 模块.检测.模板匹配器 import 模板匹配引擎
from 任务流程.夜世界.收集圣水车 import 收集圣水车任务

测试目录 = Path(__file__).resolve().parent
满仓主页图 = 测试目录 / "回放样本" / "standby_night_home_cart_full_20261127_233039.png"
灰色按钮 = {"收集": None, "关闭": (650, 40, 690, 80), "空车": True}


def _页(名称):
    return SimpleNamespace(页面=名称)


class 圣水满仓圣水车测试(unittest.TestCase):
    def _任务(self, 页面序列, 面板文字):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        识别器 = SimpleNamespace(
            定位圣水车弹窗按钮=Mock(return_value=灰色按钮),
            识别=Mock(side_effect=list(页面序列)),
        )
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕)),
            置脚本状态=Mock(),
            脚本延时=Mock(),
            点击=Mock(return_value=True),
            点击已确认安全按钮=Mock(return_value=True),
            _获取点击页面识别器=lambda: 识别器,
        )
        任务 = object.__new__(收集圣水车任务)
        任务.上下文 = 上下文
        任务.执行OCR识别 = Mock(side_effect=lambda 区域: (
            [([], "聖水車", .99)] if 区域[1] < 150 else 面板文字
        ))
        return 任务, 识别器

    def _执行两候选(self, 任务):
        任务._夜世界仍在前台 = Mock(return_value=True)
        任务._查找圣水车模板 = Mock(return_value=(False, (0, 0), 0.0))
        任务._查找海岸船锚点 = Mock(return_value=(True, (692, 7), 0.94))
        任务.是否在危险区域内 = Mock(return_value=False)
        任务._生成圣水车候选点 = Mock(return_value=[
            (575, 278, "船模板兼容偏移1"), (589, 290, "船模板兼容偏移2"),
        ])
        return 任务.执行()

    def _状态(self, 任务):
        return [c.args[0] for c in 任务.上下文.置脚本状态.call_args_list]

    def test_满仓文案灰色按钮只关X并按完成返回(self):
        任务, _ = self._任务(
            [_页("圣水车弹窗"), _页("夜世界主页")],
            [([], "聖水儲存已滿", .95)],
        )
        self.assertTrue(self._执行两候选(任务))

        self.assertTrue(任务._本轮圣水车满仓)
        self.assertFalse(任务._本轮未发现可收集圣水车)
        任务.上下文.点击.assert_called_once_with(575, 278)
        任务.上下文.点击已确认安全按钮.assert_called_once_with(670, 60, 延时=180)
        self.assertTrue(any("储存已满" in 项 for 项 in self._状态(任务)))

    def test_文案未确认的灰色按钮只关X跳过且不点第二候选(self):
        # 现场：满仓时面板是防御奖励列表，没有“暫無新的防”也没有满仓字样。
        任务, _ = self._任务(
            [_页("圣水车弹窗"), _页("夜世界主页")],
            [([], "Valerossi46", .9), ([], "184000", .9), ([], "重播", .9)],
        )
        self.assertFalse(self._执行两候选(任务))

        # 外层据此跳过收集继续夜世界流程，而不是终止整个任务。
        self.assertTrue(任务._本轮未发现可收集圣水车)
        self.assertFalse(任务._输入已拒绝)
        任务.上下文.点击.assert_called_once_with(575, 278)
        任务.上下文.点击已确认安全按钮.assert_called_once_with(670, 60, 延时=180)
        self.assertFalse(any("停止点击收集或其它按钮" in 项 for 项 in self._状态(任务)))

    def test_未找到X或非可关面板时不点击且不点下一个候选(self):
        # 复审 689903f P1-1/2：关 X 返回假（没找到 X）也必须页级确认主页；
        # 未知/升级详情/商店等非圣水车面板一律不点。
        for 页面 in ("未知", "升级详情弹窗", "商店弹窗", "宝石购买页"):
            with self.subTest(页面=页面):
                任务, 识别器 = self._任务([_页(页面)] * 3, [])
                任务.执行OCR识别 = Mock(return_value=[([], "加農炮", .99)])
                任务._检测详情面板关闭点 = Mock(return_value=None)

                self.assertFalse(self._执行两候选(任务))

                self.assertTrue(任务._输入已拒绝)
                self.assertFalse(任务._本轮未发现可收集圣水车)
                任务.上下文.点击.assert_called_once_with(575, 278)
                任务.上下文.点击已确认安全按钮.assert_not_called()
                self.assertEqual(识别器.识别.call_count, 3)
                self.assertTrue(any("交由安全待命" in 项 for 项 in self._状态(任务)))

    def test_候选误开圣水车弹窗经护栏关X确认主页后才点下一个候选(self):
        任务, _ = self._任务(
            [_页("圣水车弹窗"), _页("夜世界主页"), _页("夜世界主页")], []
        )
        任务.执行OCR识别 = Mock(return_value=[([], "加農炮", .99)])

        self.assertFalse(self._执行两候选(任务))

        self.assertEqual(
            [c.args for c in 任务.上下文.点击.call_args_list],
            [(575, 278), (670, 60), (589, 290)],
        )
        # 关闭 X 走公共护栏点击，不用绕过护栏的已确认安全按钮。
        任务.上下文.点击已确认安全按钮.assert_not_called()
        self.assertTrue(任务._本轮未发现可收集圣水车)
        self.assertFalse(任务._输入已拒绝)

    def test_文案未确认但关X后未回主页不标记跳过(self):
        任务, _ = self._任务(
            [_页("圣水车弹窗"), _页("未知"), _页("未知")],
            [([], "Valerossi46", .9)],
        )
        self.assertFalse(self._执行两候选(任务))

        # 外层据此置页面恢复失败交给安全待命，而不是跳过继续资源收集。
        self.assertFalse(任务._本轮未发现可收集圣水车)
        self.assertTrue(任务._输入已拒绝)
        任务.上下文.点击.assert_called_once_with(575, 278)

    def test_满仓关键字不误判空车与正常列表(self):
        self.assertTrue(收集圣水车任务._是否圣水储存已满([([], "圣水已满", .9)]))
        self.assertTrue(收集圣水车任务._是否圣水储存已满([([], "儲存已滿", .9)]))
        self.assertFalse(收集圣水车任务._是否圣水储存已满(
            [([], "暫無新的防禦獎勵", .9)]
        ))
        self.assertFalse(收集圣水车任务._是否圣水储存已满(
            [([], "堪稱完美！", .9), ([], "260000", .9)]
        ))

    def test_满仓现场主页截图识别为夜世界主页(self):
        图 = cv2.imdecode(np.fromfile(str(满仓主页图), dtype=np.uint8), cv2.IMREAD_COLOR)
        识别器 = 页面识别器(模板匹配引擎(图片库路径=测试目录.parent / "img"))
        结果 = 识别器.识别(图, 战斗中=False)
        self.assertEqual(结果.页面, "夜世界主页", 结果.依据)
        self.assertEqual(结果.世界, "夜世界")


if __name__ == "__main__":
    unittest.main()
