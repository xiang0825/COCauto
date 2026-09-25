import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 任务流程.夜世界.夜世界打鱼 import 夜世界打鱼任务


class 夜世界后台技能清理测试(unittest.TestCase):
    def test_夜世界任务异常退出时停止后台英雄技能线程(self):
        技能标志 = threading.Event()
        上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            _战斗中=True,
            英雄技能标志=技能标志,
        )
        任务 = 夜世界打鱼任务.__new__(夜世界打鱼任务)
        任务.上下文 = 上下文
        假任务 = Mock()
        假任务.执行.return_value = False

        with patch(
            "任务流程.夜世界.夜世界打鱼.打开进攻页面",
            return_value=假任务,
        ), patch(
            "任务流程.夜世界.夜世界打鱼.等待进入战斗",
            return_value=假任务,
        ), patch(
            "任务流程.夜世界.夜世界打鱼.下兵",
            return_value=假任务,
        ), patch(
            "任务流程.夜世界.夜世界打鱼.等待回营或第二次战斗",
            return_value=假任务,
        ):
            self.assertFalse(任务.执行())

        self.assertTrue(技能标志.is_set())
        self.assertFalse(hasattr(上下文, "英雄技能标志"))
        self.assertFalse(上下文._战斗中)


if __name__ == "__main__":
    unittest.main()
