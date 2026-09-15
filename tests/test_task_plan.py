import unittest

from 数据库.任务数据库 import 机器人设置
from 界面.任务计划面板 import 生成任务计划
from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务


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
        设置 = 机器人设置(战利品优先级="未知", 自动配兵玩法="未知")

        self.assertEqual(设置.战利品优先级, "均衡")
        self.assertEqual(设置.自动配兵玩法, "资源优先")

    def test_战利品评分会随优先级改变(self):
        金币优先 = 搜索目标敌人任务.计算战利品评分(800000, 100000, 1000, "金币")
        黑水优先 = 搜索目标敌人任务.计算战利品评分(100000, 100000, 8000, "黑水")

        self.assertGreater(金币优先, 700000)
        self.assertGreater(黑水优先, 700000)


if __name__ == "__main__":
    unittest.main()
