import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 任务流程.建筑升级.寻找建筑 import 寻找建筑
from 任务流程.建筑升级.更新工人状态 import 更新工人状态任务


class 建筑升级边界测试(unittest.TestCase):
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
