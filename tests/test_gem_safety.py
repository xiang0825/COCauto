import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call

import cv2
import numpy as np

from 任务流程.基础任务框架 import 任务上下文
from 核心.鼠标操作 import 鼠标控制器


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
    上下文._宝石保护确认主页面 = Mock(return_value=False)
    上下文._战斗中 = False
    return 上下文


class 宝石安全保护测试(unittest.TestCase):
    def test_中部宝石图标触发ESC并标记停止(self):
        模板 = 读取模板("宝石.bmp")
        模板1 = 读取模板("宝石1.bmp")
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[230:230 + 模板.shape[0], 390:390 + 模板.shape[1]] = 模板
        屏幕[230:230 + 模板1.shape[0], 414:414 + 模板1.shape[1]] = 模板1
        上下文 = 创建上下文(屏幕)
        上下文._宝石保护确认主页面.return_value = True

        self.assertTrue(上下文.检查宝石商店危险页面(强制=True))
        self.assertEqual(
            [调用.args[0] for 调用 in 上下文.键盘.按字符按压.call_args_list],
            ["esc"],
        )
        上下文.停止事件.set.assert_not_called()
        self.assertFalse(上下文.页面恢复失败)

    def test_缩放后的中部宝石图标仍然触发拦截(self):
        模板 = 读取模板("宝石.bmp")
        模板1 = 读取模板("宝石1.bmp")
        缩放模板 = cv2.resize(模板, None, fx=0.8, fy=0.8, interpolation=cv2.INTER_AREA)
        缩放模板1 = cv2.resize(模板1, None, fx=0.8, fy=0.8, interpolation=cv2.INTER_AREA)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[230:230 + 缩放模板.shape[0], 390:390 + 缩放模板.shape[1]] = 缩放模板
        屏幕[230:230 + 缩放模板1.shape[0], 414:414 + 缩放模板1.shape[1]] = 缩放模板1
        上下文 = 创建上下文(屏幕)
        上下文._宝石保护确认主页面.return_value = True

        self.assertTrue(上下文.检查宝石商店危险页面(强制=True))
        上下文.键盘.按字符按压.assert_called()

    def test_单张局部宝石图案不会阻断正常战斗点击(self):
        模板 = 读取模板("宝石2.bmp")
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[230:230 + 模板.shape[0], 390:390 + 模板.shape[1]] = 模板
        上下文 = 创建上下文(屏幕)

        self.assertFalse(上下文.检查宝石商店危险页面(强制=True))
        上下文.键盘.按字符按压.assert_not_called()

    def test_主世界右上角常驻宝石图标不会误触发(self):
        模板 = 读取模板("宝石.bmp")
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[20:20 + 模板.shape[0], 760:760 + 模板.shape[1]] = 模板
        上下文 = 创建上下文(屏幕)

        self.assertFalse(上下文.检查宝石商店危险页面(强制=True))
        上下文.键盘.按字符按压.assert_not_called()

    def test_点击检测到危险页面后不会发送鼠标点击(self):
        模板 = 读取模板("宝石.bmp")
        模板1 = 读取模板("宝石1.bmp")
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[230:230 + 模板.shape[0], 390:390 + 模板.shape[1]] = 模板
        屏幕[230:230 + 模板1.shape[0], 414:414 + 模板1.shape[1]] = 模板1
        上下文 = 创建上下文(屏幕)
        上下文._宝石保护确认主页面.return_value = True

        self.assertFalse(上下文.点击(400, 300, 延时=1, 是否精确点击=True))
        上下文.鼠标.移动到.assert_not_called()
        上下文.鼠标.左键点击.assert_not_called()

    def test_战斗中即使误命中危险模板也绝不发送返回键(self):
        模板 = 读取模板("宝石.bmp")
        模板1 = 读取模板("宝石1.bmp")
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[230:230 + 模板.shape[0], 390:390 + 模板.shape[1]] = 模板
        屏幕[230:230 + 模板1.shape[0], 414:414 + 模板1.shape[1]] = 模板1
        上下文 = 创建上下文(屏幕)
        上下文._战斗中 = True

        self.assertFalse(上下文.检查宝石商店危险页面(强制=True))
        上下文.键盘.按字符按压.assert_not_called()

    def test_点击完成后强制再次检查危险页面(self):
        上下文 = 创建上下文(np.zeros((600, 800, 3), dtype=np.uint8))
        上下文.检查宝石商店危险页面 = Mock(side_effect=[False, True])

        self.assertFalse(上下文.点击(400, 300, 延时=1, 是否精确点击=True))
        self.assertEqual(
            上下文.检查宝石商店危险页面.call_args_list,
            [call(), call(强制=True)],
        )

    def test_战斗点击后不强制全屏检查(self):
        上下文 = 创建上下文(np.zeros((600, 800, 3), dtype=np.uint8))
        上下文._战斗中 = True
        上下文.检查宝石商店危险页面 = Mock(return_value=False)

        self.assertTrue(上下文.点击(400, 300, 延时=1, 是否精确点击=True))
        self.assertEqual(
            上下文.检查宝石商店危险页面.call_args_list,
            [call(), call(强制=False)],
        )

    def test_已确认安全按钮绕过重复保护但恢复原回调(self):
        上下文 = 创建上下文(np.zeros((600, 800, 3), dtype=np.uint8))
        原回调 = Mock(return_value=True)
        上下文.鼠标._安全点击检查回调 = 原回调
        上下文.鼠标.左键点击.return_value = True

        self.assertTrue(上下文.点击已确认安全按钮(262, 378, 延时=1))
        上下文.鼠标.移动到.assert_called_once_with(262, 378)
        上下文.鼠标.左键点击.assert_called_once_with()
        self.assertIs(上下文.鼠标._安全点击检查回调, 原回调)

    def test_底层鼠标路径也会阻断危险点击(self):
        鼠标 = 鼠标控制器.__new__(鼠标控制器)
        鼠标._安全点击检查回调 = Mock(return_value=True)
        鼠标._左键点击内部 = Mock(return_value=True)

        self.assertFalse(鼠标.左键点击())
        鼠标._左键点击内部.assert_not_called()


if __name__ == "__main__":
    unittest.main()
