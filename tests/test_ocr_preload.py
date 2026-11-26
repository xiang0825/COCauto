"""启动阶段后台预热 OCR：不阻塞、只建一套引擎、失败只记日志。"""
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

from 任务流程.基础任务框架 import 任务上下文


def 假上下文():
    上下文 = 任务上下文.__new__(任务上下文)
    上下文._日志 = []
    上下文.置脚本状态 = lambda 文本, *a: 上下文._日志.append(文本)
    上下文.标记模型使用 = lambda *a: 0.0
    return 上下文


class 慢引擎:
    创建次数 = 0
    放行 = threading.Event()

    def __init__(self):
        慢引擎.创建次数 += 1
        慢引擎.放行.wait(5)
        self.调用 = 0

    def __call__(self, 图像):
        self.调用 += 1
        return [], None


def 假OCR模块(引擎类):
    模块 = types.ModuleType("模块.检测.OCR识别器")
    模块.安全OCR引擎 = 引擎类
    return patch.dict(sys.modules, {"模块.检测.OCR识别器": 模块})


class OCR预热测试(unittest.TestCase):
    def setUp(self):
        慢引擎.创建次数 = 0
        慢引擎.放行 = threading.Event()

    def test_后台预热不阻塞且与首次识别共用同一引擎(self):
        上下文 = 假上下文()
        with 假OCR模块(慢引擎):
            开始 = time.monotonic()
            线程 = 上下文.后台预热OCR()
            self.assertLess(time.monotonic() - 开始, 0.5)  # 立即返回
            self.assertTrue(线程.is_alive())
            结果 = {}
            取引擎 = threading.Thread(target=lambda: 结果.setdefault("引擎", 上下文.获取OCR引擎()))
            取引擎.start()
            time.sleep(0.05)
            慢引擎.放行.set()
            线程.join(5)
            取引擎.join(5)
        self.assertEqual(慢引擎.创建次数, 1)
        self.assertIs(结果["引擎"], 上下文._共享OCR引擎)
        self.assertEqual(上下文._共享OCR引擎.调用, 1)  # 空跑一次
        self.assertTrue(any("预热完成" in 行 for 行 in 上下文._日志))

    def test_已加载或正在预热时不重复(self):
        上下文 = 假上下文()
        with 假OCR模块(慢引擎):
            线程 = 上下文.后台预热OCR()
            self.assertIs(上下文.后台预热OCR(), 线程)
            慢引擎.放行.set()
            线程.join(5)
            self.assertIsNone(上下文.后台预热OCR())

    def test_内存保护触发后不预热(self):
        上下文 = 假上下文()
        上下文._内存保护已触发 = True
        self.assertIsNone(上下文.后台预热OCR())

    def test_预热失败只记日志(self):
        class 坏引擎:
            def __init__(self):
                raise RuntimeError("模型文件缺失")

        上下文 = 假上下文()
        with 假OCR模块(坏引擎):
            上下文.后台预热OCR().join(5)
        self.assertTrue(any("OCR 后台预热失败" in 行 and "模型文件缺失" in 行 for 行 in 上下文._日志))
        self.assertIsNone(getattr(上下文, "_共享OCR引擎", None))


if __name__ == "__main__":
    unittest.main()
