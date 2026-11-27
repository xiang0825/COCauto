import unittest
import time
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from 任务流程.基础任务框架 import 任务上下文


def ocr项(文字, x1, y1, x2, y2):
    return ([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], 文字, 0.98)


def 创建上下文(结果):
    上下文 = 任务上下文.__new__(任务上下文)
    上下文.机器人标志 = "test"
    上下文.数据库 = SimpleNamespace(
        获取机器人设置=Mock(
            return_value=SimpleNamespace(是否自动确认升级完成=True)
        )
    )
    上下文.op = SimpleNamespace(
        获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))
    )
    上下文._共享OCR引擎 = Mock(return_value=(结果, None))
    上下文.检查宝石商店危险页面 = Mock(return_value=False)
    上下文.点击已确认安全按钮 = Mock(return_value=True)
    上下文.置脚本状态 = Mock()
    上下文._战斗中 = False
    上下文._点击识别截图 = None
    上下文._点击识别截图时间 = 0.0
    return 上下文


class 升级完成弹窗测试(unittest.TestCase):
    def test_明确升级完成和底部确认按钮才形成候选(self):
        上下文 = 创建上下文(
            [
                ocr项("建筑升级完成", 190, 110, 420, 140),
                ocr项("确认", 460, 400, 560, 435),
            ]
        )
        候选 = 上下文._识别升级完成弹窗(
            np.zeros((600, 800, 3), dtype=np.uint8)
        )
        self.assertIsNotNone(候选)
        self.assertEqual(候选["确认点"], (590, 462))

    def test_只有普通确认文字不会点击(self):
        上下文 = 创建上下文([ocr项("确认", 460, 400, 560, 435)])
        self.assertIsNone(
            上下文._识别升级完成弹窗(np.zeros((600, 800, 3), dtype=np.uint8))
        )

    def test_宝石商店和立即完成优先拒绝(self):
        for 文字 in ("升级完成 使用宝石", "建筑升级完成 立即完成", "商店 研究完成"):
            上下文 = 创建上下文(
                [
                    ocr项(文字, 190, 110, 420, 140),
                    ocr项("确认", 460, 400, 560, 435),
                ]
            )
            self.assertIsNone(
                上下文._识别升级完成弹窗(
                    np.zeros((600, 800, 3), dtype=np.uint8)
                ),
                文字,
            )

    def test_同一弹窗连续两次确认后只点击一次(self):
        上下文 = 创建上下文(
            [
                ocr项("研究完成", 190, 110, 420, 140),
                ocr项("确认", 460, 400, 560, 435),
            ]
        )
        上下文._升级完成弹窗检查时间 = -10.0
        self.assertFalse(上下文.自动确认升级完成弹窗())
        上下文._升级完成弹窗检查时间 = -10.0
        self.assertTrue(上下文.自动确认升级完成弹窗())
        上下文.点击已确认安全按钮.assert_called_once_with(590, 462, 延时=180)

    def test_战斗中不识别不点击(self):
        上下文 = 创建上下文(
            [ocr项("升级完成", 190, 110, 420, 140), ocr项("确认", 460, 400, 560, 435)]
        )
        上下文._战斗中 = True
        self.assertFalse(上下文.自动确认升级完成弹窗())
        上下文.检查宝石商店危险页面.assert_not_called()
        上下文.点击已确认安全按钮.assert_not_called()

    def test_弹窗检查间隔内不重复读取机器人设置(self):
        上下文 = 创建上下文([])
        上下文._升级完成弹窗检查时间 = time.monotonic()
        上下文._任务计划长时间等待 = True

        self.assertFalse(上下文.自动确认升级完成弹窗())

        上下文.数据库.获取机器人设置.assert_not_called()
        上下文.检查宝石商店危险页面.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class 部落竞赛期间不做升级弹窗OCR测试(unittest.TestCase):
    """2026-11-26 19:44 实机：活动列表上升级完成弹窗整屏 OCR 同步跑约 3 分钟无日志。"""

    def _上下文(self):
        上下文 = 创建上下文(
            [ocr项("研究完成", 190, 110, 420, 140), ocr项("确认", 460, 400, 560, 435)]
        )
        上下文._升级完成弹窗检查时间 = -10.0
        return 上下文

    def test_部落竞赛流程中不OCR不点击(self):
        for 标记 in ("_部落竞赛流程中", "_部落竞赛面板已确认"):
            上下文 = self._上下文()
            setattr(上下文, 标记, True)
            self.assertFalse(上下文.自动确认升级完成弹窗())
            上下文._共享OCR引擎.assert_not_called()
            上下文.检查宝石商店危险页面.assert_not_called()
            上下文.点击已确认安全按钮.assert_not_called()

    def test_已识别为活动列表或竞赛面板时不做整屏OCR(self):
        for 页面 in ("活动弹窗", "部落竞赛面板", "部落竞赛任务详情"):
            上下文 = self._上下文()
            上下文._最近点击页面结果 = SimpleNamespace(页面=页面)
            self.assertFalse(上下文.自动确认升级完成弹窗())
            上下文._共享OCR引擎.assert_not_called()

    def test_流程结束后恢复正常检查(self):
        上下文 = self._上下文()
        上下文._部落竞赛流程中 = False
        self.assertFalse(上下文.自动确认升级完成弹窗())
        上下文._共享OCR引擎.assert_called_once()
