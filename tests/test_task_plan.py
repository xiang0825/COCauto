import unittest
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 数据库.任务数据库 import 机器人设置
from 界面.日志面板 import 日志面板
from 界面.任务计划面板 import 生成任务计划
from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务
from 线程.自动化机器人 import 自动化机器人


class 任务计划测试(unittest.TestCase):
    def test_计划状态来自机器人配置(self):
        设置 = 机器人设置(
            是否刷主世界=True,
            是否刷夜世界=False,
            开启刷墙=True,
            欲升级的战宠="莱希",
            欲升级的兵种或法术="雷电法术",
        )

        计划 = {项["名称"]: 项 for 项 in 生成任务计划(设置)}

        self.assertEqual(计划["主世界刷资源"]["状态"], "已启用")
        self.assertEqual(计划["夜世界刷资源"]["状态"], "未启用")
        self.assertEqual(计划["刷墙"]["状态"], "已启用")
        self.assertIn("莱希", 计划["战宠升级"]["说明"])
        self.assertIn("雷电法术", 计划["兵种或法术研究"]["说明"])

    def test_空配置不生成任务(self):
        self.assertEqual(生成任务计划(None), [])

    def test_资源打满动作和任务顺序有默认值并可规范化(self):
        设置 = 机器人设置(资源打满后动作="未知值", 任务计划顺序=["night_resource", "night_resource", "unknown"])

        self.assertEqual(设置.资源打满后动作, "退出")
        self.assertEqual(设置.任务计划顺序[0], "night_resource")
        self.assertEqual(设置.任务计划顺序.count("night_resource"), 1)
        self.assertIn("main_resource", 设置.任务计划顺序)

    def test_战利品优先级和自动配兵配置有安全默认值(self):
        设置 = 机器人设置(
            战利品优先级="未知",
            自动配兵玩法="未知",
            高速下兵方式="未知",
        )

        self.assertEqual(设置.战利品优先级, "均衡")
        self.assertEqual(设置.自动配兵玩法, "资源优先")
        self.assertTrue(设置.是否启用高速下兵)
        self.assertEqual(设置.高速下兵方式, "快速连点")

    def test_战利品评分会随优先级改变(self):
        金币优先 = 搜索目标敌人任务.计算战利品评分(800000, 100000, 1000, "金币")
        黑水优先 = 搜索目标敌人任务.计算战利品评分(100000, 100000, 8000, "黑水")

        self.assertGreater(金币优先, 700000)
        self.assertGreater(黑水优先, 700000)

    def test_日志面板会去掉实时消息时间前缀(self):
        self.assertEqual(
            日志面板._去掉实时前缀("[14:33:41] 下兵成功"),
            "下兵成功",
        )
        self.assertEqual(日志面板._去掉实时前缀("普通历史日志"), "普通历史日志")

    def test_刷墙资源不足会自动刷资源后重试一次(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.停止事件 = threading.Event()
        上下文 = SimpleNamespace(
            刷墙需要资源=False,
            置脚本状态=Mock(),
        )
        调用次数 = {"wall": 0}

        def 模拟升级(任务键, 当前上下文, _检测登录):
            调用次数[任务键] += 1
            当前上下文.刷墙需要资源 = 调用次数[任务键] == 1

        机器人._执行升级计划 = Mock(side_effect=模拟升级)
        机器人._执行主世界刷资源计划 = Mock(return_value=True)

        with patch("线程.自动化机器人.到主世界任务") as 回主世界:
            机器人._执行刷墙计划(上下文, object())

        self.assertEqual(调用次数["wall"], 2)
        机器人._执行主世界刷资源计划.assert_called_once()
        # 进入主世界已经由被测的主世界刷资源流程统一负责，避免重复点击。
        回主世界.assert_not_called()
        self.assertFalse(机器人.停止事件.is_set())

    def test_非主页时最多单次ESC并确认主世界主页(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        键盘 = Mock()
        上下文 = SimpleNamespace(
            键盘=键盘,
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        with patch("线程.自动化机器人.模板匹配引擎") as 引擎工厂:
            引擎工厂.return_value.执行匹配.side_effect = [
                (False, (0, 0), None),
                (False, (0, 0), None),
                (True, (0, 0), None),
                (True, (0, 0), None),
            ]
            self.assertTrue(机器人._确保主世界主页面(上下文))

        self.assertEqual(键盘.按字符按压.call_count, 1)
        self.assertFalse(上下文.页面恢复失败)

    def test_已经是主世界主页时不发送ESC(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        键盘 = Mock()
        上下文 = SimpleNamespace(
            键盘=键盘,
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        with patch("线程.自动化机器人.模板匹配引擎") as 引擎工厂:
            引擎工厂.return_value.执行匹配.return_value = (True, (0, 0), None)
            self.assertTrue(机器人._确保主世界主页面(上下文))

        键盘.按字符按压.assert_not_called()
        self.assertFalse(上下文.页面恢复失败)

    def test_主世界主页确认失败时禁止继续(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        键盘 = Mock()
        上下文 = SimpleNamespace(
            键盘=键盘,
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        with patch("线程.自动化机器人.模板匹配引擎") as 引擎工厂:
            引擎工厂.return_value.执行匹配.return_value = (False, (0, 0), None)
            self.assertFalse(机器人._确保主世界主页面(上下文, 2, 3))

        self.assertEqual(键盘.按字符按压.call_count, 3)
        self.assertTrue(上下文.页面恢复失败)


if __name__ == "__main__":
    unittest.main()
