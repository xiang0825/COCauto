import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 任务流程.兵种或法术升级 import 兵种或法术升级任务
from 任务流程.战宠升级 import 战宠升级任务
from 任务流程.基础任务框架 import 任务上下文


class 任务计划冷却退避测试(unittest.TestCase):
    @staticmethod
    def _状态数据库(状态类型, 原因):
        return SimpleNamespace(
            获取最新完整状态=Mock(return_value=SimpleNamespace(
                状态数据={状态类型: {"时间": time.time(), "原因": 原因}}
            ))
        )

    def test_研究冷却请求任务计划等待(self):
        请求等待 = Mock()
        上下文 = SimpleNamespace(
            设置=SimpleNamespace(研究升级检查间隔=1.0),
            数据库=self._状态数据库("研究升级失败记录", "实验室不可用"),
            机器人标志="测试",
            置脚本状态=Mock(),
            请求任务计划等待=请求等待,
        )
        任务 = 兵种或法术升级任务.__new__(兵种或法术升级任务)
        任务.上下文 = 上下文
        任务.数据库 = 上下文.数据库
        任务.机器人标志 = 上下文.机器人标志

        self.assertFalse(任务._检查冷却时间())
        请求等待.assert_called_once()
        self.assertGreaterEqual(请求等待.call_args.args[0], 3590)
        self.assertEqual(请求等待.call_args.args[1], "研究升级冷却")

    def test_战宠冷却请求任务计划等待(self):
        请求等待 = Mock()
        上下文 = SimpleNamespace(
            设置=SimpleNamespace(欲升级的战宠="独角兽", 战宠升级检查间隔=1.0),
            数据库=self._状态数据库("战宠升级失败记录", "资源不足"),
            机器人标志="测试",
            置脚本状态=Mock(),
            请求任务计划等待=请求等待,
        )
        任务 = 战宠升级任务.__new__(战宠升级任务)
        任务.上下文 = 上下文
        任务.数据库 = 上下文.数据库
        任务.机器人标志 = 上下文.机器人标志

        # 战宠任务冷却属于正常跳过，不应阻断后续任务。
        self.assertTrue(任务.执行())
        请求等待.assert_called_once()
        self.assertGreaterEqual(请求等待.call_args.args[0], 3590)
        self.assertEqual(请求等待.call_args.args[1], "战宠升级冷却")

    def test_任务上下文等待取最大值并限制为一小时(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.任务计划等待秒 = 5

        上下文.请求任务计划等待(90, "研究升级冷却")
        上下文.请求任务计划等待(7200, "错误配置")

        self.assertEqual(上下文.任务计划等待秒, 3600)
        self.assertEqual(上下文._任务计划等待原因, "错误配置")

    def test_长时间任务计划等待降低升级弹窗维护频率(self):
        任务 = 任务上下文.__new__(任务上下文)
        任务._升级完成弹窗检查时间 = time.monotonic()
        任务._任务计划长时间等待 = True

        # 直接验证维护频率判定，不启动 OCR/ADB。
        self.assertEqual(任务._升级完成弹窗检查间隔(), 30.0)
        任务._任务计划长时间等待 = False
        self.assertEqual(任务._升级完成弹窗检查间隔(), 5.0)

    def test_研究间隔为零时失败也请求短退避(self):
        请求等待 = Mock()
        上下文 = SimpleNamespace(
            设置=SimpleNamespace(研究升级检查间隔=0.0),
            数据库=Mock(),
            机器人标志="测试",
            置脚本状态=Mock(),
            请求任务计划等待=请求等待,
        )
        任务 = 兵种或法术升级任务.__new__(兵种或法术升级任务)
        任务.上下文 = 上下文
        任务.数据库 = 上下文.数据库
        任务.机器人标志 = 上下文.机器人标志

        任务._记录失败状态("实验室不可用或已有升级中")

        请求等待.assert_called_once_with(60.0, "研究升级不可用退避")

    def test_旧上下文研究间隔为零时也设置短退避(self):
        上下文 = SimpleNamespace(
            设置=SimpleNamespace(研究升级检查间隔=0.0),
            数据库=Mock(),
            机器人标志="测试",
            置脚本状态=Mock(),
            任务计划等待秒=5.0,
        )
        任务 = 兵种或法术升级任务.__new__(兵种或法术升级任务)
        任务.上下文 = 上下文
        任务.数据库 = 上下文.数据库
        任务.机器人标志 = 上下文.机器人标志

        任务._记录失败状态("实验室不可用或已有升级中")

        self.assertEqual(上下文.任务计划等待秒, 60.0)
        self.assertEqual(上下文._任务计划等待原因, "研究升级不可用退避")


if __name__ == "__main__":
    unittest.main()
