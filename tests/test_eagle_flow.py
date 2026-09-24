import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 任务流程.天鹰火炮成就.天鹰火炮进攻任务 import 天鹰火炮进攻任务
from 任务流程.天鹰火炮成就.等待战斗结束并回营 import 等待战斗结束并回营任务


class 天鹰战斗页衔接测试(unittest.TestCase):
    def _任务(self, 已进入战斗=True):
        任务 = 天鹰火炮进攻任务.__new__(天鹰火炮进攻任务)
        任务.上下文 = SimpleNamespace(
            _入口已进入战斗=已进入战斗,
            _战斗中=False,
            置脚本状态=Mock(),
        )
        任务.天鹰检测器 = object()
        任务.等待下一个按钮出现 = Mock(return_value=True)
        任务.点击下一个按钮 = Mock()
        任务.检测天鹰火炮位置 = Mock(return_value=(320, 260))
        任务.使用雷电法术攻击 = Mock()
        return 任务

    def test_已进入战斗页直接检测并攻击不搜索(self):
        任务 = self._任务()

        self.assertTrue(任务.执行())
        任务.检测天鹰火炮位置.assert_called_once_with()
        任务.使用雷电法术攻击.assert_called_once_with((320, 260))
        任务.等待下一个按钮出现.assert_not_called()
        任务.点击下一个按钮.assert_not_called()

    def test_战斗页漏检目标仍交给回营不点击搜索(self):
        任务 = self._任务()
        任务.检测天鹰火炮位置.return_value = None

        self.assertTrue(任务.执行())
        任务.使用雷电法术攻击.assert_not_called()
        任务.等待下一个按钮出现.assert_not_called()
        任务.点击下一个按钮.assert_not_called()
        日志 = " ".join(
            调用.args[0] for 调用 in 任务.上下文.置脚本状态.call_args_list
        )
        self.assertIn("安全回营", 日志)

    def test_搜索等待期间进入战斗直接检测目标不等待下一个(self):
        任务 = 天鹰火炮进攻任务.__new__(天鹰火炮进攻任务)
        任务.上下文 = SimpleNamespace(
            _入口已进入战斗=False,
            _战斗中=False,
            识别点击画面=Mock(return_value=SimpleNamespace(页面="战斗中")),
            置脚本状态=Mock(),
        )
        任务.天鹰检测器 = object()
        任务.检测天鹰火炮位置 = Mock(return_value=(320, 260))
        任务.使用雷电法术攻击 = Mock(return_value=True)
        任务.等待下一个按钮出现 = Mock()
        任务.点击下一个按钮 = Mock()

        self.assertTrue(任务.执行())
        任务.检测天鹰火炮位置.assert_called_once_with()
        任务.使用雷电法术攻击.assert_called_once_with((320, 260))
        任务.等待下一个按钮出现.assert_not_called()
        任务.点击下一个按钮.assert_not_called()
        self.assertTrue(任务.上下文._战斗中)

    def test_雷电落点被拒绝时停止攻击(self):
        任务 = 天鹰火炮进攻任务.__new__(天鹰火炮进攻任务)
        任务.上下文 = SimpleNamespace(
            点击=Mock(return_value=False),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            页面恢复失败=False,
        )
        任务.选中雷电法术 = Mock(return_value=True)

        self.assertFalse(任务.使用雷电法术攻击((320, 260)))
        任务.上下文.点击.assert_called_once()
        self.assertTrue(任务.上下文.页面恢复失败)

    def test_雷电法术不可用时交给回营步骤(self):
        任务 = self._任务()
        任务.使用雷电法术攻击 = Mock(
            side_effect=lambda 坐标: (
                setattr(任务, "_雷电法术不可用", True) or False
            )
        )

        self.assertTrue(任务._执行攻击或安全回营((320, 260)))

        日志 = " ".join(
            调用.args[0] for 调用 in 任务.上下文.置脚本状态.call_args_list
        )
        self.assertIn("安全回营", 日志)

    def test_下一个按钮被拒绝时返回失败(self):
        任务 = 天鹰火炮进攻任务.__new__(天鹰火炮进攻任务)
        任务.上下文 = SimpleNamespace(
            点击=Mock(return_value=False),
            页面恢复失败=False,
        )

        self.assertFalse(任务.点击下一个按钮())
        self.assertTrue(任务.上下文.页面恢复失败)

    def test_放弃战斗按钮被拒绝时不继续确认(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            点击=Mock(return_value=False),
            脚本延时=Mock(),
            页面恢复失败=False,
        )
        任务.模板识别 = Mock()
        任务.模板识别.执行匹配.return_value = (True, (320, 260), 0.99)

        self.assertFalse(任务.点击放弃战斗按钮())
        self.assertTrue(任务.上下文.页面恢复失败)

    def test_天鹰回营复用主世界几何护栏(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.上下文 = SimpleNamespace(置脚本状态=Mock())
        with patch(
            "任务流程.天鹰火炮成就.等待战斗结束并回营.主世界回营任务"
        ) as 通用回营:
            通用回营.return_value.点击放弃战斗按钮.return_value = True
            通用回营.return_value.点击确定.return_value = True
            通用回营.return_value.等待回营地按钮出现.return_value = True

            self.assertTrue(任务.执行())

        通用回营.return_value.点击放弃战斗按钮.assert_called_once_with(
            任务.上下文
        )
        通用回营.return_value.点击确定.assert_called_once_with(任务.上下文)
        通用回营.return_value.等待回营地按钮出现.assert_called_once_with(
            任务.上下文
        )

    def test_测试服放弃后直接主世界也安全结束天鹰回营(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.上下文 = SimpleNamespace(置脚本状态=Mock())
        with patch(
            "任务流程.天鹰火炮成就.等待战斗结束并回营.主世界回营任务"
        ) as 通用回营:
            通用回营.return_value.点击放弃战斗按钮.return_value = True
            通用回营.return_value.点击确定.return_value = False
            通用回营.return_value.等待主界面就绪.return_value = True

            self.assertTrue(任务.执行())

        通用回营.return_value.等待回营地按钮出现.assert_not_called()
        日志 = " ".join(
            调用.args[0] for 调用 in 任务.上下文.置脚本状态.call_args_list
        )
        self.assertIn("直接回到主世界", 日志)


if __name__ == "__main__":
    unittest.main()
