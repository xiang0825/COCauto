import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.基础任务框架 import 任务上下文


def 读取模板(名称: str) -> np.ndarray:
    数据 = np.fromfile(f"img/{名称}", dtype=np.uint8)
    图像 = cv2.imdecode(数据, cv2.IMREAD_COLOR)
    if 图像 is None:
        raise AssertionError(f"无法读取测试模板：{名称}")
    return 图像


def 创建上下文(屏幕图像: np.ndarray):
    上下文 = 任务上下文.__new__(任务上下文)
    上下文.op = SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕图像))
    上下文.键盘 = SimpleNamespace(按字符按压=Mock())
    上下文.鼠标 = SimpleNamespace(移动到=Mock(), 左键点击=Mock())
    上下文.脚本延时 = Mock()
    上下文.置脚本状态 = Mock()
    上下文.停止事件 = Mock()
    上下文.停止事件.set = Mock()
    return 上下文


class 宝石安全保护测试(unittest.TestCase):
    def test_中部宝石图标触发ESC并标记停止(self):
        模板 = 读取模板("宝石.bmp")
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[230:230 + 模板.shape[0], 390:390 + 模板.shape[1]] = 模板
        上下文 = 创建上下文(屏幕)

        self.assertTrue(上下文.检查宝石商店危险页面(强制=True))
        self.assertEqual(
            [调用.args[0] for 调用 in 上下文.键盘.按字符按压.call_args_list],
            ["esc", "esc", "esc"],
        )
        上下文.停止事件.set.assert_called_once_with()
        self.assertTrue(上下文.页面恢复失败)

    def test_主世界右上角常驻宝石图标不会误触发(self):
        模板 = 读取模板("宝石.bmp")
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[20:20 + 模板.shape[0], 760:760 + 模板.shape[1]] = 模板
        上下文 = 创建上下文(屏幕)

        self.assertFalse(上下文.检查宝石商店危险页面(强制=True))
        上下文.键盘.按字符按压.assert_not_called()

    def test_点击检测到危险页面后不会发送鼠标点击(self):
        模板 = 读取模板("宝石.bmp")
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[230:230 + 模板.shape[0], 390:390 + 模板.shape[1]] = 模板
        上下文 = 创建上下文(屏幕)

        with self.assertRaises(SystemExit):
            上下文.点击(400, 300, 延时=1, 是否精确点击=True)
        上下文.鼠标.移动到.assert_not_called()
        上下文.鼠标.左键点击.assert_not_called()


if __name__ == "__main__":
    unittest.main()
