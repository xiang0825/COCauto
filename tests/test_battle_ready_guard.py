import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from 任务流程.主世界打鱼.进攻 import 进攻任务


class 战斗就绪护栏测试(unittest.TestCase):
    def test_目标或兵栏为空时停止而不进入回营流程(self):
        上下文 = SimpleNamespace(
            _战斗中=False,
            _已确认进入战斗=False,
            停止事件=threading.Event(),
            页面恢复失败=False,
            置脚本状态=Mock(),
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))
            ),
        )
        任务 = 进攻任务.__new__(进攻任务)
        任务.上下文 = 上下文
        任务.检测器 = SimpleNamespace(检测=Mock(return_value=[]))
        任务.检查当前配兵 = Mock(return_value=[])
        任务.筛选有效目标 = Mock(return_value=[])
        任务.选择集中进攻目标 = Mock(return_value=[])

        self.assertFalse(任务.执行())
        self.assertTrue(上下文.停止事件.is_set())
        self.assertTrue(上下文.页面恢复失败)
        self.assertFalse(上下文._战斗中)
        self.assertFalse(上下文._已确认进入战斗)
        self.assertTrue(any("不等待回营" in c.args[0] for c in 上下文.置脚本状态.call_args_list))


if __name__ == "__main__":
    unittest.main()
