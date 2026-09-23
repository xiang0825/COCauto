import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 任务流程.兵种或法术升级.打开研究面板 import 打开研究面板任务


class 研究面板OCR护栏测试(unittest.TestCase):
    def test_遍历OCR结果提取合法研究槽位(self):
        结果 = 打开研究面板任务.解析实验室计数([
            ([[0, 0], [10, 0], [10, 10], [0, 10]], "1", 0.99),
            ([[0, 0], [30, 0], [30, 12], [0, 12]], "1/2", 0.88),
        ])
        self.assertEqual(结果, (1, 2))

    def test_单个数字不会再触发解包异常(self):
        with self.assertRaises(ValueError):
            打开研究面板任务.解析实验室计数([
                ([[0, 0], [10, 0], [10, 10], [0, 10]], "1", 0.99),
            ])

    def test_窄区域只有单数字时使用顶部宽区域回退(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务.执行OCR识别 = Mock(side_effect=[
            [([[0, 0], [10, 0], [10, 10], [0, 10]], "1", 0.99)],
            [([[20, 10], [55, 10], [55, 32], [20, 32]], "2/2", 0.90)],
        ])
        任务.上下文 = SimpleNamespace(置脚本状态=Mock())

        self.assertTrue(任务._检查实验室是否空闲())
        self.assertEqual(
            任务.执行OCR识别.call_args_list[1].args[0],
            (240, 0, 380, 80),
        )
        self.assertTrue(any(
            "顶部宽区域回退" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))


if __name__ == "__main__":
    unittest.main()
