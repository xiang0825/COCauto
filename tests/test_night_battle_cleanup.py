import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 任务流程.夜世界.夜世界打鱼 import 夜世界打鱼任务
from 任务流程.夜世界.夜世界打鱼.等待回营或第二场战斗 import 等待回营或第二次战斗


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

    def test_英雄技能线程未退出时不清除安全点击回调或点击回营(self):
        class 未退出线程:
            def __init__(self):
                self.等待秒数 = None

            def is_alive(self):
                return True

            def join(self, timeout=None):
                self.等待秒数 = timeout

        线程 = 未退出线程()
        回调 = Mock(return_value=True)
        安全点击 = Mock(return_value=True)
        识别器 = Mock()
        识别器.识别.return_value = SimpleNamespace(页面="战斗结算")
        识别器.定位结算回营按钮.return_value = (400, 508)
        技能标志 = threading.Event()
        上下文 = SimpleNamespace(
            _战斗中=True,
            英雄技能标志=技能标志,
            英雄技能线程=线程,
            鼠标=SimpleNamespace(_安全点击检查回调=回调),
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            _获取点击页面识别器=Mock(return_value=识别器),
            点击已确认安全按钮=安全点击,
            置脚本状态=Mock(),
            清除战斗结算保护状态=Mock(),
        )
        任务 = 等待回营或第二次战斗.__new__(等待回营或第二次战斗)
        任务.上下文 = 上下文

        self.assertFalse(任务.尝试点击回营按钮())

        self.assertTrue(技能标志.is_set())
        self.assertIs(上下文.英雄技能线程, 线程)
        self.assertEqual(线程.等待秒数, 5.0)
        self.assertTrue(上下文._战斗中)
        self.assertIs(上下文.鼠标._安全点击检查回调, 回调)
        安全点击.assert_not_called()
        上下文.清除战斗结算保护状态.assert_not_called()

    def test_夜世界回营超时安全返回不触发异常处理(self):
        上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            脚本延时=Mock(),
            _战斗中=True,
        )
        任务 = 等待回营或第二次战斗.__new__(等待回营或第二次战斗)
        任务.上下文 = 上下文
        任务._读取页面状态 = Mock(return_value=(None, False))
        任务.是否出现换兵种箭头 = Mock(return_value=False)
        任务.尝试点击回营按钮 = Mock(return_value=False)
        任务.异常处理 = Mock()

        with patch(
            "任务流程.夜世界.夜世界打鱼.等待回营或第二场战斗.time.time",
            side_effect=(0, 0, 301),
        ):
            self.assertFalse(任务.执行())

        self.assertTrue(any(
            "夜世界回营等待超时" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))
        任务.异常处理.assert_not_called()


if __name__ == "__main__":
    unittest.main()
