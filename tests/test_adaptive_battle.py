import unittest
from types import SimpleNamespace

from 任务流程.主世界打鱼.进攻 import 进攻任务
from 任务流程.主世界打鱼.进攻坐标逻辑计算 import 坐标
from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务


class 自适应战斗测试(unittest.TestCase):
    def test_单目标也会生成多个不同落点(self):
        任务 = 进攻任务.__new__(进攻任务)
        落点 = 任务.生成分散下兵点([
            {"中心坐标": 坐标(100, 100), "类别名称": "金矿", "置信度": 0.9}
        ])
        self.assertGreaterEqual(len(set(落点)), 3)

    def test_连续低表现切换探索策略(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "摧毁率": 32},
                            {"结果": "胜利", "摧毁率": 41},
                        ]
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 进攻任务.__new__(进攻任务)
        self.assertEqual(任务.读取自适应进攻策略(上下文), "分散探索")

    def test_拆分OCR框仍能读取百分比(self):
        结果 = [
            ([[600, 450], [650, 450], [650, 470], [600, 470]], "摧毁率", 0.99),
            ([[700, 450], [720, 450], [720, 470], [700, 470]], "67", 0.99),
        ]
        self.assertEqual(
            等待战斗结束并回营任务.从OCR结果提取摧毁率(结果, "摧毁率67"),
            67,
        )


if __name__ == "__main__":
    unittest.main()
