import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from 任务流程.主世界打鱼.进攻 import 进攻任务
from 任务流程.主世界打鱼.进攻坐标逻辑计算 import 坐标
from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务
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

    def test_资源阵营评分范围和严格门槛(self):
        易攻目标 = [
            {"类别名称": "金库", "裁剪坐标": [55, 245, 85, 275], "置信度": 0.95},
            {"类别名称": "圣水瓶", "裁剪坐标": [715, 270, 745, 300], "置信度": 0.95},
            {"类别名称": "金矿", "裁剪坐标": [85, 220, 115, 250], "置信度": 0.90},
            {"类别名称": "圣水采集器", "裁剪坐标": [680, 300, 710, 330], "置信度": 0.90},
        ]
        难攻目标 = [
            {"类别名称": "金库", "裁剪坐标": [380, 280, 410, 310], "置信度": 0.95},
            {"类别名称": "圣水瓶", "裁剪坐标": [420, 290, 450, 320], "置信度": 0.95},
        ]
        易攻评分, 依据 = 搜索目标敌人任务.计算资源易窃取评分(易攻目标)
        难攻评分, _ = 搜索目标敌人任务.计算资源易窃取评分(难攻目标)
        self.assertGreater(易攻评分, 5.0)
        self.assertLessEqual(难攻评分, 5.0)
        self.assertGreaterEqual(易攻评分, 0.0)
        self.assertLessEqual(易攻评分, 10.0)
        self.assertIn("高价值资源可达比例", 依据)
        self.assertFalse(搜索目标敌人任务.是否达到资源易窃取门槛(5.0))
        self.assertTrue(搜索目标敌人任务.是否达到资源易窃取门槛(5.01))

    def test_下兵点只允许边界带并能生成邻近候选(self):
        任务 = 进攻任务.__new__(进攻任务)
        上下文 = SimpleNamespace(
            _部署区域已初始化=True,
            _部署红色掩码=None,
            本场可下兵区域={
                "边界顶点": [(394, 20), (745, 293), (405, 549), (68, 278)],
                "边界带宽": 58.0,
            },
        )
        候选点 = 任务.生成可下兵候选点(上下文, 坐标(400, 285))
        self.assertEqual(len(候选点), 8)
        self.assertTrue(all(任务.下兵点是否位于可下兵区域(上下文, 点) for 点 in 候选点))
        self.assertFalse(任务.下兵点是否位于可下兵区域(上下文, (400, 285)))

    def test_兵栏变化才视为下兵成功(self):
        任务 = 进攻任务.__new__(进攻任务)
        前图 = np.zeros((36, 31, 3), dtype=np.uint8)
        后图 = 前图.copy()
        self.assertFalse(任务.判断下兵反馈(前图, 后图, {"类别": "兵种"}))
        后图[10:25, 5:25] = 255
        self.assertTrue(任务.判断下兵反馈(前图, 后图, {"类别": "兵种"}))

    def test_被拒绝的候选点会换点而不是重复点击(self):
        任务 = 进攻任务.__new__(进攻任务)
        点击记录 = []
        日志 = []
        上下文 = SimpleNamespace(
            _部署区域已初始化=True,
            _部署红色掩码=None,
            本场可下兵区域={
                "边界顶点": [(394, 20), (745, 293), (405, 549), (68, 278)],
                "边界带宽": 58.0,
            },
            点击=lambda x, y, **_参数: 点击记录.append((x, y)),
            脚本延时=lambda _毫秒: None,
            置脚本状态=日志.append,
        )
        候选点 = 任务.生成可下兵候选点(上下文, 坐标(400, 285))
        with patch.object(任务, "读取兵栏槽位图像", side_effect=[object(), object(), object()]), \
             patch.object(任务, "判断下兵反馈", side_effect=[False, True]):
            成功, 使用坐标 = 任务.尝试下兵至可用位置(
                上下文,
                {"名称": "测试兵", "区域": (0, 0, 1, 1), "类别": "兵种"},
                坐标(400, 285),
                候选点[:2],
                5,
            )
        self.assertTrue(成功)
        self.assertEqual(使用坐标, 候选点[1])
        self.assertEqual(点击记录, 候选点[:2])
        self.assertTrue(any("换下一个候选点" in 文本 for 文本 in 日志))

    def test_兵量足够的普通兵种才启用高速批次(self):
        任务 = 进攻任务.__new__(进攻任务)
        设置 = SimpleNamespace(是否启用高速下兵=True)
        上下文 = SimpleNamespace(设置=设置)
        self.assertEqual(任务.取高速下兵批次(上下文, {"类别": "兵种", "数量": 7}, 7), 1)
        self.assertEqual(任务.取高速下兵批次(上下文, {"类别": "兵种", "数量": 8}, 10), 6)
        self.assertEqual(任务.取高速下兵批次(上下文, {"类别": "英雄", "数量": 20}, 10), 1)

    def test_高速模式分别调用连点和短按压(self):
        class 鼠标:
            def __init__(self):
                self.调用 = []

            def 连续点击(self, *参数, **关键字):
                self.调用.append(("连点", 参数, 关键字))
                return True

            def 长按(self, *参数, **关键字):
                self.调用.append(("短按", 参数, 关键字))
                return True

        鼠标对象 = 鼠标()
        日志 = []
        上下文 = SimpleNamespace(鼠标=鼠标对象, 置脚本状态=日志.append)
        任务 = 进攻任务.__new__(进攻任务)
        self.assertEqual(任务.执行高速下兵批次(上下文, (100, 200), 5, "快速连点"), 5)
        self.assertEqual(任务.执行高速下兵批次(上下文, (100, 200), 2, "短按压"), 2)
        self.assertEqual([项[0] for 项 in 鼠标对象.调用], ["连点", "短按"])

    def test_回营模板没有结果页标记时仍视为战斗中(self):
        class 匹配器:
            def 执行匹配(self, _图像, 模板路径, **_参数):
                if "领取奖励" in 模板路径:
                    return False, (0, 0), None
                return True, (400, 550), None

        任务 = 进攻任务.__new__(进攻任务)
        任务.模板识别 = 匹配器()
        任务.ocr引擎 = lambda *_参数, **_关键字: ([], None)
        self.assertFalse(任务._结束画面有结果标记(np.zeros((600, 800, 3), dtype=np.uint8)))

    def test_结果页有失败文字才允许确认结束(self):
        class 匹配器:
            def 执行匹配(self, _图像, 模板路径, **_参数):
                if "领取奖励" in 模板路径:
                    return False, (0, 0), None
                return True, (400, 550), None

        任务 = 进攻任务.__new__(进攻任务)
        任务.模板识别 = 匹配器()
        任务.ocr引擎 = lambda *_参数, **_关键字: (
            [([[0, 0], [1, 0], [1, 1], [0, 1]], "战斗失败", 0.99)],
            None,
        )
        self.assertTrue(任务._结束画面有结果标记(np.zeros((600, 800, 3), dtype=np.uint8)))


if __name__ == "__main__":
    unittest.main()
