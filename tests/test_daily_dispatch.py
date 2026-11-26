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


class 面板日常调度测试(unittest.TestCase):
    def _假任务(self, 可运行=True, 结果=True):
        return SimpleNamespace(可以运行=Mock(return_value=可运行), 执行=Mock(return_value=结果))

    def test_未校准或冷却时不确认页面不点击(self):
        for 键, 路径 in (("donate_troops", "任务流程.日常.捐兵.捐兵任务"),
                       ("capital_donate", "任务流程.日常.都城捐金币.都城捐金币任务")):
            实例, 任务 = 机器人(), self._假任务(可运行=False)
            with patch(路径, return_value=任务):
                self.assertTrue(实例._执行主世界面板日常计划(键, 上下文(), object()))
            实例._进入并确认主世界.assert_not_called()
            任务.执行.assert_not_called()

    def test_执行前后都确认主世界(self):
        实例, 任务 = 机器人(), self._假任务()
        with patch("任务流程.日常.捐兵.捐兵任务", return_value=任务):
            self.assertTrue(实例._执行主世界面板日常计划("donate_troops", 上下文(), object()))
        self.assertEqual(实例._进入并确认主世界.call_count, 2)
        任务.执行.assert_called_once()

    def test_任务失败不再确认直接返回失败(self):
        实例, 任务 = 机器人(), self._假任务(结果=False)
        with patch("任务流程.日常.都城捐金币.都城捐金币任务", return_value=任务):
            self.assertFalse(实例._执行主世界面板日常计划("capital_donate", 上下文(), object()))
        self.assertEqual(实例._进入并确认主世界.call_count, 1)


if __name__ == "__main__":
    unittest.main()


class 日常任务打包测试(unittest.TestCase):
    def test_日常模块被PyInstaller自动收集(self):
        from PyInstaller.utils.hooks import collect_submodules

        模块 = set(collect_submodules("任务流程"))
        for 名称 in ("保持不闲", "夜世界星星", "捐兵", "都城捐金币", "日常公共"):
            self.assertIn(f"任务流程.日常.{名称}", 模块)

    def test_日常资源JSON在打包资源目录下(self):
        import json
        import pathlib

        根 = pathlib.Path(__file__).resolve().parents[1] / "资源" / "日常"
        for 名称 in ("夜世界星星", "捐兵", "都城"):
            数据 = json.loads((根 / f"{名称}.json").read_text(encoding="utf-8"))
            self.assertIs(数据["calibrated"], False, 名称)

    def test_新界面任务列表能看到新任务且默认关闭(self):
        from 应用 import 任务计划 as 计划
        from 数据库.任务数据库 import 机器人设置

        行 = {r.键: r for r in 计划.任务行列表(机器人设置())}
        for 键 in ("night_star_bonus", "donate_troops", "capital_donate", "keep_busy"):
            self.assertIn(键, 行)
            self.assertFalse(行[键].已启用, 键)
            self.assertIn(键, 计划.任务参数表)
