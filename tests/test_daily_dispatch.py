"""日常任务在调度器里的分段与失败语义。"""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 线程.自动化机器人 import 自动化机器人


def 机器人():
    实例 = 自动化机器人.__new__(自动化机器人)
    实例.停止事件 = threading.Event()
    实例._进入并确认主世界 = Mock(return_value=True)
    实例._断线时恢复游戏连接 = Mock(return_value=True)
    return 实例


def 上下文():
    return SimpleNamespace(置脚本状态=Mock(), 页面恢复失败=False, 请求任务计划等待=Mock())


class 保持不闲调度测试(unittest.TestCase):
    def _假任务(self, 冷却=False, 研究=True, 工人=True):
        任务 = SimpleNamespace(
            冷却中=Mock(return_value=冷却), 执行研究段=Mock(return_value=研究),
            执行工人段=Mock(return_value=工人), 记录完成=Mock(),
        )
        return 任务

    def test_两段之间重新确认主世界(self):
        实例, 任务 = 机器人(), self._假任务()
        with patch("任务流程.日常.保持不闲.保持不闲任务", return_value=任务):
            self.assertTrue(实例._执行保持不闲计划(上下文(), object()))
        self.assertEqual(实例._进入并确认主世界.call_count, 2)
        任务.记录完成.assert_called_once()

    def test_冷却中不确认页面不点击(self):
        实例, 任务 = 机器人(), self._假任务(冷却=True)
        with patch("任务流程.日常.保持不闲.保持不闲任务", return_value=任务):
            self.assertTrue(实例._执行保持不闲计划(上下文(), object()))
        实例._进入并确认主世界.assert_not_called()
        任务.执行研究段.assert_not_called()

    def test_研究段页面不可信时不进工人段(self):
        实例, 任务 = 机器人(), self._假任务(研究=False)
        with patch("任务流程.日常.保持不闲.保持不闲任务", return_value=任务):
            self.assertFalse(实例._执行保持不闲计划(上下文(), object()))
        任务.执行工人段.assert_not_called()
        任务.记录完成.assert_not_called()

    def test_主世界未确认时标记页面恢复失败(self):
        实例, 任务 = 机器人(), self._假任务()
        实例._进入并确认主世界.return_value = False
        ctx = 上下文()
        with patch("任务流程.日常.保持不闲.保持不闲任务", return_value=任务):
            self.assertFalse(实例._执行保持不闲计划(ctx, object()))
        self.assertTrue(ctx.页面恢复失败)
        任务.执行研究段.assert_not_called()


class 夜世界星星调度测试(unittest.TestCase):
    def test_今日已完成不进夜世界(self):
        实例 = 机器人()
        任务 = SimpleNamespace(今日已完成=Mock(return_value=True), 打一场=Mock())
        进入 = Mock()
        with patch("任务流程.日常.夜世界星星.夜世界星星任务", return_value=任务), \
                patch("线程.自动化机器人.到夜世界任务", 进入):
            self.assertTrue(实例._执行夜世界星星计划(上下文(), object()))
        进入.assert_not_called()
        任务.打一场.assert_not_called()

    def test_逐场打到完成(self):
        实例 = 机器人()
        任务 = SimpleNamespace(
            今日已完成=Mock(return_value=False),
            打一场=Mock(side_effect=["继续", "继续", "完成"]),
        )
        with patch("任务流程.日常.夜世界星星.夜世界星星任务", return_value=任务), \
                patch("线程.自动化机器人.到夜世界任务", return_value=SimpleNamespace(执行=lambda: True)):
            self.assertTrue(实例._执行夜世界星星计划(上下文(), object()))
        self.assertEqual(任务.打一场.call_count, 3)

    def test_一场失败标记页面恢复失败(self):
        实例, ctx = 机器人(), 上下文()
        任务 = SimpleNamespace(今日已完成=Mock(return_value=False), 打一场=Mock(return_value="失败"))
        with patch("任务流程.日常.夜世界星星.夜世界星星任务", return_value=任务), \
                patch("线程.自动化机器人.到夜世界任务", return_value=SimpleNamespace(执行=lambda: True)):
            self.assertFalse(实例._执行夜世界星星计划(ctx, object()))
        self.assertTrue(ctx.页面恢复失败)

    def test_夜世界入口暂不可用时安全跳过(self):
        实例, ctx = 机器人(), 上下文()
        ctx._夜世界入口暂不可用 = True
        任务 = SimpleNamespace(今日已完成=Mock(return_value=False), 打一场=Mock())
        with patch("任务流程.日常.夜世界星星.夜世界星星任务", return_value=任务), \
                patch("线程.自动化机器人.到夜世界任务", return_value=SimpleNamespace(执行=lambda: False)):
            self.assertTrue(实例._执行夜世界星星计划(ctx, object()))
        self.assertFalse(ctx.页面恢复失败)
        任务.打一场.assert_not_called()


if __name__ == "__main__":
    unittest.main()
