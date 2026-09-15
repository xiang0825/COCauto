import unittest

from 任务流程.主世界打鱼.进攻 import 进攻任务
from 任务流程.主世界打鱼.进攻坐标逻辑计算 import 坐标


class _设置:
    欲进攻资源建筑靠近地图边缘最小比例 = 0.5


class _数据库:
    def 获取机器人设置(self, _机器人标志):
        return _设置()


class _上下文:
    数据库 = _数据库()
    机器人标志 = "测试机器人"

    def __init__(self):
        self.状态 = []

    def 置脚本状态(self, 文本, *参数, **关键字参数):
        self.状态.append(文本)


class 进攻目标选择测试(unittest.TestCase):
    def setUp(self):
        self.任务 = 进攻任务.__new__(进攻任务)
        self.上下文 = _上下文()

    def test_边缘比例开启时仍保留内圈储存建筑(self):
        结果 = self.任务.筛选有效目标(
            self.上下文,
            [
                {"类别名称": "金库", "置信度": 0.8, "裁剪坐标": [385, 285, 415, 315]},
                {"类别名称": "未知建筑", "置信度": 0.9, "裁剪坐标": [100, 100, 130, 130]},
            ],
        )

        self.assertEqual([目标["类别名称"] for 目标 in 结果], ["金库"])
        self.assertIn("储存建筑 1", self.上下文.状态[-1])

    def test_同一进攻方向优先选择储存建筑(self):
        目标列表 = [
            {"类别名称": "金矿", "置信度": 1.0, "中心坐标": 坐标(100, 250), "靠近边缘": True},
            {"类别名称": "金库", "置信度": 0.8, "中心坐标": 坐标(150, 260), "靠近边缘": False},
        ]

        结果 = self.任务.选择集中进攻目标(self.上下文, 目标列表)

        self.assertEqual(结果[0]["类别名称"], "金库")
        self.assertLessEqual(len(结果), self.任务.最多集中目标数)


if __name__ == "__main__":
    unittest.main()
