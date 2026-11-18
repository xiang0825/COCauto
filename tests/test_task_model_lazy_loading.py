import unittest
from unittest.mock import Mock

from 任务流程.基础任务框架 import 基础任务, 任务上下文


class _共享模型上下文:
    def __init__(self):
        self.数据库 = object()
        self.机器人标志 = "robot_1"
        self.模板识别器 = object()
        self.ocr创建次数 = 0
        self.yolo创建次数 = 0
        self._ocr引擎 = None
        self._yolo检测器 = None

    def 获取模板识别器(self):
        return self.模板识别器

    def 获取OCR引擎(self):
        if self._ocr引擎 is None:
            self.ocr创建次数 += 1
            self._ocr引擎 = object()
        return self._ocr引擎

    def 获取YOLO检测器(self):
        if self._yolo检测器 is None:
            self.yolo创建次数 += 1
            self._yolo检测器 = object()
        return self._yolo检测器


class _空任务(基础任务):
    def 执行(self):
        return True


class 任务模型延迟加载测试(unittest.TestCase):
    def test_创建未使用识别的任务时不加载模型(self):
        上下文 = _共享模型上下文()

        _空任务(上下文)

        self.assertEqual(上下文.ocr创建次数, 0)
        self.assertEqual(上下文.yolo创建次数, 0)

    def test_首次使用时从上下文加载并复用模型(self):
        上下文 = _共享模型上下文()
        任务一 = _空任务(上下文)
        任务二 = _空任务(上下文)

        OCR = 任务一.ocr引擎
        检测器 = 任务一.检测器

        self.assertIs(任务二.ocr引擎, OCR)
        self.assertIs(任务二.检测器, 检测器)
        self.assertEqual(上下文.ocr创建次数, 1)
        self.assertEqual(上下文.yolo创建次数, 1)

    def test_测试注入的识别器仍然可覆盖上下文模型(self):
        上下文 = _共享模型上下文()
        任务 = _空任务(上下文)
        OCR = Mock()
        检测器 = Mock()

        任务.ocr引擎 = OCR
        任务.检测器 = 检测器

        self.assertIs(任务.ocr引擎, OCR)
        self.assertIs(任务.检测器, 检测器)
        self.assertEqual(上下文.ocr创建次数, 0)
        self.assertEqual(上下文.yolo创建次数, 0)

    def test_内存保护触发后禁止重新加载识别模型(self):
        上下文 = object.__new__(任务上下文)
        上下文._内存保护已触发 = True

        with self.assertRaisesRegex(MemoryError, "内存保护已触发"):
            上下文.获取OCR引擎()
        with self.assertRaisesRegex(MemoryError, "内存保护已触发"):
            上下文.获取YOLO检测器()

        self.assertFalse(hasattr(上下文, "_共享OCR引擎"))
        self.assertFalse(hasattr(上下文, "_共享YOLO检测器"))


if __name__ == "__main__":
    unittest.main()
