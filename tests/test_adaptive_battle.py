import unittest
import os
from pathlib import Path
import tempfile
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from 任务流程.主世界打鱼.进攻 import 进攻任务
from 任务流程.主世界打鱼.进攻坐标逻辑计算 import 坐标, 取进攻方向
from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务
from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务


class 自适应战斗测试(unittest.TestCase):
    def test_连续搜索每十个候选继续降低资源门槛(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        上下文 = SimpleNamespace(置脚本状态=Mock())

        第十次 = 任务.调整搜索目标(上下文, 3_000_000, 10)
        第二十次 = 任务.调整搜索目标(上下文, 3_000_000, 20)

        self.assertEqual(第十次, 2_700_000)
        self.assertEqual(第二十次, 2_400_000)

    def test_连续搜索资源门槛最低降到十万(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        上下文 = SimpleNamespace(置脚本状态=Mock())

        结果 = 任务.调整搜索目标(上下文, 3_000_000, 100)

        self.assertEqual(结果, 100_000)

    def test_进攻界面截图使用中文数据集目录仍能写入(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.数据集目录 = Path("数据集")
        任务.目录文件数 = 0
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(
                    return_value=np.zeros((24, 32, 3), dtype=np.uint8)
                )
            ),
            置脚本状态=Mock(),
        )
        原目录 = os.getcwd()
        with tempfile.TemporaryDirectory() as 临时目录:
            try:
                os.chdir(临时目录)
                任务.数据集目录 = Path("数据集")
                任务.数据集目录.mkdir()
                self.assertIsNone(任务.采集当前画面())
            finally:
                os.chdir(原目录)
            文件 = list(Path(临时目录).glob("数据集/*.png"))
            self.assertEqual(len(文件), 1)
            self.assertGreater(文件[0].stat().st_size, 0)

    def test_敌方资源OCR返回None时按空结果处理(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.ocr引擎 = Mock(return_value=(None, None))
        日志 = []
        设置 = SimpleNamespace(战利品优先级="金币")
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((79, 137, 3), dtype=np.uint8)),
            ),
            数据库=SimpleNamespace(获取机器人设置=Mock(return_value=设置)),
            机器人标志="robot_1",
            置脚本状态=日志.append,
            是否内存异常=lambda _异常: False,
            触发内存保护=Mock(),
        )

        结果 = 任务.识别当前资源(上下文)

        self.assertEqual(结果["金币"], 0)
        self.assertEqual(结果["圣水"], 0)
        self.assertEqual(结果["黑油"], 0)
        self.assertFalse(any("NoneType" in 文本 for 文本 in 日志))

    def test_敌方资源OCR兼容轻量格式并按坐标排序(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        完整OCR结果 = [
            ([[0, 70], [20, 70], [20, 80], [0, 80]], "333333", 0.9),
            ([[0, 40], [20, 40], [20, 50], [0, 50]], "222222", 0.9),
            ([[0, 10], [20, 10], [20, 20], [0, 20]], "111111", 0.9),
        ]
        self.assertEqual(
            任务._提取资源行文本(完整OCR结果),
            ["111111", "222222", "333333"],
        )

    def test_资源行缺失时仍按屏幕行映射不把黑油补到圣水(self):
        OCR结果 = [
            ([[0, 16], [20, 16], [20, 24], [0, 24]], "97690", 0.99),
            ([[0, 78], [20, 78], [20, 86], [0, 86]], "5326", 0.99),
        ]

        self.assertEqual(
            搜索目标敌人任务._提取资源行文本(OCR结果),
            ["97690", "0", "5326"],
        )

    def test_敌方资源截图覆盖金币圣水黑油三行(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        OCR行 = ((18, "97690"), (51, "367510"), (83, "5326"))

        def 按可见区域OCR(区域):
            结果 = []
            for 中心Y, 文本 in OCR行:
                if 中心Y >= 区域.shape[0]:
                    continue
                框 = [
                    [0, 中心Y - 4], [40, 中心Y - 4],
                    [40, 中心Y + 4], [0, 中心Y + 4],
                ]
                结果.append((框, 文本, 0.99))
            return 结果, None

        任务.ocr引擎 = Mock(side_effect=按可见区域OCR)
        设置 = SimpleNamespace(战利品优先级="均衡")
        上下文 = SimpleNamespace(
            数据库=SimpleNamespace(获取机器人设置=Mock(return_value=设置)),
            机器人标志="测试机器人",
            置脚本状态=Mock(),
            是否内存异常=Mock(return_value=False),
            触发内存保护=Mock(),
        )
        任务.上下文 = 上下文

        资源 = 任务.识别当前资源(
            上下文, np.zeros((600, 800, 3), dtype=np.uint8)
        )

        self.assertEqual(
            (资源["金币"], 资源["圣水"], 资源["黑油"]),
            (97690, 367510, 5326),
        )
        self.assertEqual(
            任务._提取资源行文本([
                ["111111", 0.9], ["222222", 0.9], ["333333", 0.9]
            ]),
            ["111111", "222222", "333333"],
        )

    def test_接管时没有搜索页不误报搜索OCR故障(self):
        诊断 = 等待战斗结束并回营任务.生成战斗诊断(
            "胜利", 3, 100,
            {"金币": None, "圣水": None, "黑油": None, "资源评分状态": "不可用"},
        )
        self.assertIn("未经过敌方搜索页", 诊断)
        self.assertNotIn("检查搜索页OCR故障", 诊断)

    def test_搜索页已确认但战利品为空仍提示检查OCR(self):
        诊断 = 等待战斗结束并回营任务.生成战斗诊断(
            "胜利", 3, 100,
            {"金币": None, "圣水": None, "黑油": None, "资源评分状态": "已完成"},
        )
        self.assertIn("检查搜索页资源 OCR", 诊断)

    def test_奖励页过渡最终结算时交给回营流程(self):
        任务 = 进攻任务.__new__(进攻任务)
        class 可控停止事件:
            def is_set(self):
                return False
            def wait(self, timeout=None):
                return False
        上下文 = SimpleNamespace(
            停止事件=可控停止事件(),
            识别点击画面=Mock(side_effect=[
                SimpleNamespace(页面="战斗奖励选择"),
                SimpleNamespace(页面="战斗奖励选择"),
                SimpleNamespace(页面="战斗结算"),
            ]),
            置脚本状态=Mock(),
            _战斗奖励弹窗已确认=True,
        )
        self.assertTrue(任务.等待奖励页结算过渡(上下文, 超时秒=3))
        self.assertFalse(上下文._战斗奖励弹窗已确认)
        self.assertTrue(上下文._战斗结束已确认)
        self.assertTrue(any("交给回营流程" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_奖励页过渡回到战斗时不重新下兵(self):
        任务 = 进攻任务.__new__(进攻任务)
        class 可控停止事件:
            def is_set(self):
                return False
            def wait(self, timeout=None):
                return False
        上下文 = SimpleNamespace(
            停止事件=可控停止事件(),
            识别点击画面=Mock(return_value=SimpleNamespace(页面="战斗中")),
            置脚本状态=Mock(),
            _战斗奖励弹窗已确认=True,
        )
        self.assertTrue(任务.等待奖励页结算过渡(上下文, 超时秒=3))
        self.assertFalse(上下文._战斗奖励弹窗已确认)
        self.assertTrue(any("交给回营流程" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_单目标也会生成多个不同落点(self):
        任务 = 进攻任务.__new__(进攻任务)
        落点 = 任务.生成分散下兵点([
            {"中心坐标": 坐标(100, 100), "类别名称": "金矿", "置信度": 0.9}
        ])
        self.assertGreaterEqual(len(set(落点)), 3)

    def test_胜利打断连续低表现序列(self):
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
        self.assertEqual(任务.读取自适应进攻策略(上下文), "集中资源")

    def test_胜利后按已保存建议保留有效进攻策略(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 32},
                            {"结果": "胜利", "星数": 2, "摧毁率": 62},
                        ],
                        "下一场建议": "分散探索",
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 进攻任务.__new__(进攻任务)
        self.assertEqual(任务.读取自适应进攻策略(上下文), "分散探索")

    def test_结构化分散建议不被诊断文字覆盖(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 36},
                            {"结果": "失败", "星数": 0, "摧毁率": 44},
                        ],
                        "下一场建议": "分散探索",
                        "最近原因": (
                            "高评分且高可达资源目标仍低摧毁：可达评分已足够，"
                            "下一场集中主力方向、减少分兵并观察突破效果"
                        ),
                        "建议依据": "低表现后分散覆盖尚未完成，继续探索入口",
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 进攻任务.__new__(进攻任务)
        self.assertEqual(任务.读取自适应进攻策略(上下文), "分散探索")

    def test_结构化提高可达评分建议被实际读取(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 40},
                            {"结果": "胜利", "星数": 1, "摧毁率": 50},
                        ],
                        "下一场建议": "提高目标可达评分",
                        "最近原因": (
                            "已获胜但星数偏低：下一场提高目标可达评分，"
                            "并在有可靠目标时分散入口"
                        ),
                        "建议依据": "低表现后分散覆盖尚未完成，继续探索入口",
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 进攻任务.__new__(进攻任务)
        self.assertEqual(
            任务.读取自适应进攻策略(上下文),
            "提高目标可达评分",
        )

    def test_结构化集中资源建议优先于冲突诊断文字并落实集中主力(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 33},
                            {"结果": "失败", "星数": 0, "摧毁率": 34},
                        ],
                        "下一场建议": "集中资源",
                        "最近原因": (
                            "已确认多方向实际投放但摧毁率低；"
                            "下一场优先筛选可达评分更高的阵营"
                        ),
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 进攻任务.__new__(进攻任务)

        self.assertEqual(任务.读取自适应进攻策略(上下文), "集中主力")

    def test_单方向零星失败覆盖过期的集中建议(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {
                                "结果": "失败",
                                "星数": 0,
                                "摧毁率": 19,
                                "进攻方向数量": 1,
                                "实际投放方向": ["左上"],
                                "策略": "资源聚焦/集中主力",
                            }
                        ],
                        "下一场建议": "集中资源",
                        "最近原因": "实际下兵仅覆盖1个方向；入口覆盖不足",
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 进攻任务.__new__(进攻任务)

        self.assertEqual(任务.读取自适应进攻策略(上下文), "分散探索")

    def test_提高目标可达评分后稳健三星在可靠入口分散至两个方向(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 36},
                            {"结果": "失败", "星数": 0, "摧毁率": 41},
                        ],
                        "下一场建议": "提高目标可达评分",
                    }
                })

        日志 = []
        上下文 = SimpleNamespace(
            数据库=数据库(),
            机器人标志="测试",
            设置=SimpleNamespace(
                是否自动配兵=True,
                自动配兵玩法="稳健三星",
                战利品优先级="均衡",
            ),
            置脚本状态=日志.append,
        )
        目标列表 = [
            {"类别名称": "圣水瓶", "中心坐标": 坐标(155, 205), "靠近边缘": True, "置信度": 0.95},
            {"类别名称": "金矿", "中心坐标": 坐标(190, 230), "靠近边缘": True, "置信度": 0.95},
            {"类别名称": "圣水瓶", "中心坐标": 坐标(625, 345), "靠近边缘": True, "置信度": 0.95},
            {"类别名称": "金矿", "中心坐标": 坐标(660, 375), "靠近边缘": True, "置信度": 0.95},
        ]
        任务 = 进攻任务.__new__(进攻任务)

        选择结果 = 任务.选择集中进攻目标(上下文, 目标列表)

        选择方向 = {
            取进攻方向(目标["中心坐标"])
            for 目标 in 选择结果
        }
        self.assertEqual(len(选择方向), 2)
        self.assertIn("提高目标可达评分", 上下文.本场进攻策略)
        self.assertTrue(any("提高目标可达评分" in 文本 and "双方向探索" in 文本 for 文本 in 日志))

    def test_资源优先分散探索会先跨方向选目标再受兵力上限截断(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 25},
                            {"结果": "失败", "星数": 0, "摧毁率": 25},
                        ],
                        "下一场建议": "分散探索",
                    }
                })

        上下文 = SimpleNamespace(
            数据库=数据库(),
            机器人标志="测试",
            设置=SimpleNamespace(
                是否自动配兵=False,
                自动配兵玩法="资源优先",
                战利品优先级="均衡",
            ),
            当前兵栏清单=[{"类别": "雷龙", "数量": 34}],
            置脚本状态=Mock(),
        )
        任务 = 进攻任务.__new__(进攻任务)
        目标列表 = [
            {"类别名称": "金库", "中心坐标": 坐标(160, 340), "靠近边缘": True, "置信度": 0.99},
            {"类别名称": "圣水瓶", "中心坐标": 坐标(180, 360), "靠近边缘": True, "置信度": 0.99},
            {"类别名称": "金库", "中心坐标": 坐标(200, 350), "靠近边缘": True, "置信度": 0.99},
            {"类别名称": "圣水瓶", "中心坐标": 坐标(220, 370), "靠近边缘": True, "置信度": 0.99},
            {"类别名称": "金矿", "中心坐标": 坐标(625, 345), "靠近边缘": True, "置信度": 0.99},
            {"类别名称": "圣水采集器", "中心坐标": 坐标(660, 365), "靠近边缘": True, "置信度": 0.99},
        ]

        选择结果 = 任务.选择集中进攻目标(上下文, 目标列表)
        选择方向 = {
            取进攻方向(目标["中心坐标"])
            for 目标 in 选择结果
        }

        self.assertEqual(len(选择结果), 4)
        self.assertEqual(len(选择方向), 2)
        self.assertEqual(set(上下文.本场进攻方向), 选择方向)
        self.assertIn("分散探索", 上下文.本场进攻策略)

    def test_一星胜利不当作低表现(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "胜利", "星数": 1, "摧毁率": 73},
                            {"结果": "胜利", "星数": 1, "摧毁率": 54},
                        ]
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 进攻任务.__new__(进攻任务)
        self.assertEqual(任务.读取自适应进攻策略(上下文), "集中资源")

    def test_连续低表现时前二十个候选临时提高评分与可达门槛(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "摧毁率": 21},
                            {"结果": "失败", "摧毁率": 35},
                        ],
                        "下一场建议": "提高目标可达评分",
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        评分, 可达比例, 说明 = 任务.获取自适应资源筛选门槛(上下文, 1)
        self.assertEqual(评分, 6.0)
        self.assertEqual(可达比例, 0.50)
        self.assertIn("前15个候选", 说明)

    def test_黑水优先候选资源门槛分阶段放宽且最终取消(self):
        获取门槛 = 搜索目标敌人任务.获取黑水优先最低候选黑油

        self.assertEqual(获取门槛("黑水", 1), 11000)
        self.assertEqual(获取门槛("黑水", 25), 11000)
        self.assertEqual(获取门槛("黑水", 26), 6500)
        self.assertEqual(获取门槛("黑水", 55), 6500)
        self.assertEqual(获取门槛("黑水", 56), 0)
        self.assertEqual(获取门槛("金币", 1), 0)

    def test_未有效投兵的失败不会加严资源搜索门槛(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {
                                "结果": "胜利", "星数": 1, "摧毁率": 44,
                                "可部署单位数量": 34, "实际投放数量": 26,
                                "策略样本有效": True,
                            },
                            {
                                "结果": "失败", "星数": 0, "摧毁率": 0,
                                "可部署单位数量": 34, "实际投放数量": 0,
                                "策略样本有效": False,
                            },
                            {
                                "结果": "失败", "星数": 0, "摧毁率": 37,
                                "可部署单位数量": 34, "实际投放数量": 34,
                                "策略样本有效": True,
                            },
                        ],
                        "下一场建议": "集中资源",
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)

        评分, 可达比例, 说明 = 任务.获取自适应资源筛选门槛(上下文, 1)

        self.assertEqual(评分, 5.0)
        self.assertIsNone(可达比例)
        self.assertEqual(说明, "")

    def test_未有效投兵的失败不会触发分散进攻策略(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {
                                "结果": "失败", "星数": 0, "摧毁率": 37,
                                "可部署单位数量": 34, "实际投放数量": 34,
                                "策略样本有效": True,
                            },
                            {
                                "结果": "失败", "星数": 0, "摧毁率": 0,
                                "可部署单位数量": 34, "实际投放数量": 0,
                                "实际投放方向": ["右下"],
                                "策略样本有效": False,
                            },
                        ],
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 进攻任务.__new__(进攻任务)

        self.assertEqual(任务.读取自适应进攻策略(上下文), "集中资源")

    def test_单个储存建筑低可达率仍会触发自适应跳过(self):
        """只有一个储存建筑时，也不能让低可达率高价值目标漏过学习筛选。"""
        日志 = []
        设置 = SimpleNamespace(是否采集进攻界面图像=False)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            设置=设置,
            数据库=SimpleNamespace(获取机器人设置=Mock(return_value=SimpleNamespace(
                战利品优先级="金币",
                欲进攻资源建筑靠近地图边缘最小比例=0.25,
            ))),
            机器人标志="测试",
            置脚本状态=日志.append,
        )
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.上下文 = 上下文
        任务.等待下一个按钮出现 = Mock(return_value=True)
        任务.识别当前资源 = Mock(return_value={"战利品评分": 999})
        任务.检测器 = SimpleNamespace(检测=Mock(return_value=[]))
        任务.计算资源易窃取评分 = Mock(return_value=(6.7, {
            "储存建筑数": 1,
            "高价值资源可达折算": 9.9,
        }))
        任务.打印状态信息 = Mock()
        任务.获取自适应资源筛选门槛 = Mock(return_value=(5.0, 0.70, "连续低表现"))
        任务.点击下一个按钮 = Mock(return_value=True)

        with patch.object(
            搜索目标敌人任务,
            "是否有足够资源建筑靠近边缘",
            return_value=True,
        ), patch.object(
            搜索目标敌人任务,
            "已出现图片",
            return_value=(False, (None, None)),
        ):
            结果 = 任务.执行单次搜索(上下文, 搜索次数=1, 最小资源=1)

        self.assertFalse(结果)
        任务.点击下一个按钮.assert_called_once_with(上下文)
        self.assertTrue(any("高价值资源可达折算[10%]低于70%" in 文本 for 文本 in 日志))

    def test_候选预算内低黑水目标在YOLO前跳过(self):
        日志 = []
        设置 = SimpleNamespace(是否采集进攻界面图像=False)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            设置=设置,
            数据库=SimpleNamespace(获取机器人设置=Mock(return_value=SimpleNamespace(
                战利品优先级="黑水",
                欲进攻资源建筑靠近地图边缘最小比例=0.25,
            ))),
            机器人标志="测试",
            置脚本状态=日志.append,
        )
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.上下文 = 上下文
        任务.等待下一个按钮出现 = Mock(return_value=True)
        任务.识别当前资源 = Mock(return_value={
            "战利品评分": 999,
            "黑油": 9072,
        })
        任务.检测器 = SimpleNamespace(检测=Mock(return_value=[]))
        任务.计算资源易窃取评分 = Mock(return_value=(6.7, {}))
        任务.打印状态信息 = Mock()
        任务.获取自适应资源筛选门槛 = Mock(return_value=(5.0, None, ""))
        任务.点击下一个按钮 = Mock(return_value=True)

        结果 = 任务.执行单次搜索(上下文, 搜索次数=15, 最小资源=1)

        self.assertFalse(结果)
        任务.检测器.检测.assert_not_called()
        任务.点击下一个按钮.assert_called_once_with(上下文)
        self.assertTrue(any("最低目标黑油[11,000]" in 文本 for 文本 in 日志))

    def test_胜利后不沿用之前的低表现目标筛选门槛(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 21},
                            {"结果": "失败", "星数": 0, "摧毁率": 35},
                            {"结果": "胜利", "星数": 2, "摧毁率": 62},
                        ],
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        评分, 可达比例, 说明 = 任务.获取自适应资源筛选门槛(上下文, 1)
        self.assertEqual(评分, 5.0)
        self.assertIsNone(可达比例)
        self.assertEqual(说明, "")

    def test_第九个候选仍保持提高目标可达评分门槛(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "摧毁率": 21},
                            {"结果": "失败", "摧毁率": 35},
                        ],
                        "下一场建议": "提高目标可达评分",
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        评分, 可达比例, 说明 = 任务.获取自适应资源筛选门槛(上下文, 9)
        self.assertEqual(评分, 6.0)
        self.assertEqual(可达比例, 0.50)
        self.assertIn("前15个候选", 说明)

    def test_低表现期间更换下兵策略仍保留目标可达门槛(self):
        for 建议 in ("集中资源", "分散探索"):
            with self.subTest(下一场建议=建议):
                class 数据库:
                    def 获取最新完整状态(self, _标志):
                        return SimpleNamespace(状态数据={
                            "战斗学习": {
                                "近期": [
                                    {"结果": "失败", "星数": 0, "摧毁率": 49},
                                    {"结果": "失败", "星数": 0, "摧毁率": 12},
                                    {"结果": "失败", "星数": 0, "摧毁率": 24},
                                ],
                                "下一场建议": 建议,
                            }
                        })

                上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
                任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
                评分, 可达比例, 说明 = 任务.获取自适应资源筛选门槛(上下文, 1)
                self.assertEqual(评分, 6.0)
                self.assertEqual(可达比例, 0.50)
                self.assertIn("前15个候选", 说明)

    def test_超出自适应候选上限后同时放宽总分与可达门槛(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "摧毁率": 21},
                            {"结果": "失败", "摧毁率": 35},
                        ],
                        "下一场建议": "提高目标可达评分",
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        评分, 可达比例, 说明 = 任务.获取自适应资源筛选门槛(上下文, 16)
        self.assertEqual(评分, 5.0)
        self.assertIsNone(可达比例)
        self.assertIn("放宽回基础门槛", 说明)

    def test_自适应门槛不会低于基础评分门槛(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "下一场建议": "提高目标可达评分",
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        with patch.object(搜索目标敌人任务, "资源易窃取最低评分", 7.0):
            评分, 可达比例, _ = 任务.获取自适应资源筛选门槛(上下文, 1)
        self.assertEqual(评分, 7.0)
        self.assertEqual(可达比例, 0.50)

    def test_没有学习反馈时仍保持用户设定的五分门槛(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={})

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        self.assertEqual(
            任务.获取自适应资源筛选门槛(上下文),
            (5.0, None, ""),
        )

    def test_进攻策略会读取提高可达评分建议(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "摧毁率": 21},
                            {"结果": "失败", "摧毁率": 35},
                        ],
                        "下一场建议": "提高目标可达评分",
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 进攻任务.__new__(进攻任务)
        self.assertEqual(任务.读取自适应进攻策略(上下文), "提高目标可达评分")

    def test_进攻策略将集中资源建议落实为集中主力(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 49},
                            {"结果": "失败", "星数": 0, "摧毁率": 33},
                        ],
                        "下一场建议": "集中资源",
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 进攻任务.__new__(进攻任务)
        self.assertEqual(任务.读取自适应进攻策略(上下文), "集中主力")

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

    def test_储存资源仅约一半可达时不得被外围采集器抬过门槛(self):
        """回归实机 28% 战斗：外围采集器多不代表内圈战利品易取。"""
        目标列表 = []
        for x, y in ((308, 343), (439, 227), (296, 265), (517, 330)):
            目标列表.append({
                "类别名称": "圣水瓶",
                "裁剪坐标": [x - 15, y - 15, x + 15, y + 15],
                "置信度": 0.9,
            })
        for 索引, (x, y) in enumerate((
            (257, 388), (490, 138), (289, 161), (543, 386),
            (129, 345), (496, 77), (297, 74), (536, 473),
            (245, 443), (575, 138), (323, 54), (200, 406), (601, 160),
        )):
            目标列表.append({
                "类别名称": "金矿" if 索引 % 2 else "圣水采集器",
                "裁剪坐标": [x - 12, y - 12, x + 12, y + 12],
                "置信度": 0.9,
            })

        评分, 依据 = 搜索目标敌人任务.计算资源易窃取评分(目标列表)

        self.assertLessEqual(评分, 5.0)
        self.assertLess(依据["高价值资源可达折算"], 依据["高价值资源可达比例"])
        self.assertFalse(搜索目标敌人任务.是否达到资源易窃取门槛(评分))

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

    def test_下兵点不会落入兵栏或放弃按钮(self):
        任务 = 进攻任务.__new__(进攻任务)
        上下文 = SimpleNamespace(
            _部署区域已初始化=True,
            _部署红色掩码=None,
            本场可下兵区域={
                "边界顶点": [(394, 20), (745, 293), (405, 549), (68, 278)],
                "边界带宽": 58.0,
            },
        )
        self.assertFalse(任务.下兵点是否位于可下兵区域(上下文, (300, 498)))
        self.assertFalse(任务.下兵点是否位于可下兵区域(上下文, (60, 440)))

    def test_底部边缘外侧落点保留在兵栏上方(self):
        """回归实机底部资源目标：y482-489 是战场边缘，不应被 y480 误删。"""
        任务 = 进攻任务.__new__(进攻任务)
        上下文 = SimpleNamespace(
            _部署区域已初始化=True,
            _部署红色掩码=None,
            本场可下兵区域={
                "边界顶点": [(394, 20), (745, 293), (405, 549), (68, 278)],
                "边界带宽": 58.0,
            },
        )
        self.assertTrue(任务.下兵点是否位于可下兵区域(上下文, (524, 482)))
        self.assertTrue(任务.下兵点是否位于可下兵区域(上下文, (302, 489)))
        self.assertFalse(任务.下兵点是否位于可下兵区域(上下文, (300, 498)))

    def test_底部目标跳过游戏拒绝的贴边点并优先最近安全落点(self):
        任务 = 进攻任务.__new__(进攻任务)
        上下文 = SimpleNamespace(
            _部署区域已初始化=True,
            _部署红色掩码=None,
            本场可下兵区域={
                "边界顶点": [(394, 20), (745, 293), (405, 549), (68, 278)],
                "边界带宽": 58.0,
            },
        )

        目标 = 坐标(433, 438)
        被实机拒绝的点 = [(474, 488), (500, 490), (495, 481)]
        候选点 = 任务.生成可下兵候选点(上下文, 目标)

        for 点 in 被实机拒绝的点:
            self.assertFalse(任务.下兵点是否位于可下兵区域(上下文, 点))
            self.assertNotIn(点, 候选点)
        self.assertEqual(候选点[0], (524, 482))

    def test_兵栏变化才视为下兵成功(self):
        任务 = 进攻任务.__new__(进攻任务)
        前图 = np.zeros((36, 31, 3), dtype=np.uint8)
        后图 = 前图.copy()
        self.assertFalse(任务.判断下兵反馈(前图, 后图, {"类别": "兵种"}))
        后图[10:25, 5:25] = 255
        self.assertTrue(任务.判断下兵反馈(前图, 后图, {"类别": "兵种"}))

    def test_未知非灰色x0槽位启用一次安全探测(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务.兵栏槽位 = [("第2格", (0, 0, 10, 10))]
        任务.取本次兵种模板列表 = lambda _上下文: []
        任务._识别槽位文本 = lambda _图像: "|"
        任务._识别槽位数量 = lambda _图像, _文本: None
        任务._槽位最佳模板 = lambda *_参数: ("", 0.0)
        任务.是否为灰色图片 = lambda *_参数, **_关键字: False
        状态 = []
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: np.zeros((10, 10, 3), dtype=np.uint8),
            ),
            置脚本状态=状态.append,
        )

        结果 = 任务.检查当前配兵(上下文)

        self.assertEqual(结果[0]["数量"], 1)
        self.assertFalse(结果[0]["数量已确认"])
        self.assertEqual(结果[0]["名称"], "未匹配模板(待探测)")
        self.assertTrue(any("启用一次安全探测" in 文本 for 文本 in 状态))

    def test_彩色攻城飞艇被OCR误读为零时仍安全探测一次(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务.兵栏槽位 = [("第4格", (0, 0, 10, 10))]
        任务.取本次兵种模板列表 = lambda _上下文: ["兵种_攻城气球.bmp"]
        任务._识别槽位文本 = lambda _图像: "x0|5"
        任务._识别槽位数量 = lambda _图像, _文本: 0
        任务._槽位最佳模板 = Mock(side_effect=[
            ("兵种_攻城气球", 0.9), ("", 0.0), ("", 0.0),
        ])
        任务.是否为灰色图片 = lambda *_参数, **_关键字: False
        日志 = []
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=lambda *_区域: np.zeros((10, 10, 3), dtype=np.uint8)),
            置脚本状态=日志.append,
        )
        结果 = 任务.检查当前配兵(上下文)
        self.assertEqual(结果[0]["类别"], "攻城器械")
        self.assertEqual(结果[0]["数量"], 1)
        self.assertFalse(结果[0]["数量已确认"])
        self.assertTrue(any("一次部署尝试" in 文本 for 文本 in 日志))

    def test_单架飞艇被OCR误读为六架时不得重复投放(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务.兵栏槽位 = [("第4格", (0, 0, 10, 10))]
        任务.取本次兵种模板列表 = lambda _上下文: ["兵种_攻城气球.bmp"]
        任务._识别槽位文本 = lambda _图像: "x6|5"
        任务._识别槽位数量 = lambda _图像, _文本: 6
        任务._槽位最佳模板 = Mock(side_effect=[
            ("兵种_攻城气球", 0.9), ("", 0.0), ("", 0.0),
        ])
        任务.是否为灰色图片 = lambda *_参数, **_关键字: False
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=lambda *_区域: np.zeros((10, 10, 3), dtype=np.uint8)),
            置脚本状态=Mock(),
        )
        结果 = 任务.检查当前配兵(上下文)
        self.assertEqual(结果[0]["类别"], "攻城器械")
        self.assertEqual(结果[0]["数量"], 1)
        self.assertFalse(结果[0]["数量已确认"])

    def test_前五格大数量未匹配卡牌按普通兵种启用高速下兵(self):
        """模板缺失但 x40 这类大数量卡牌不能被误当成慢速攻城器械。"""
        任务 = 进攻任务.__new__(进攻任务)
        任务.兵栏槽位 = [("第1格", (0, 0, 10, 10))]
        任务.取本次兵种模板列表 = lambda _上下文: []
        任务._识别槽位文本 = lambda _图像: ("x40", "")
        任务._识别槽位数量 = lambda _图像, _文本: 40
        任务._槽位最佳模板 = lambda *_参数: ("", 0.0)
        任务.是否为灰色图片 = lambda *_参数, **_关键字: False
        状态 = []
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: np.zeros((10, 10, 3), dtype=np.uint8),
            ),
            置脚本状态=状态.append,
        )

        结果 = 任务.检查当前配兵(上下文)

        self.assertEqual(结果[0]["数量"], 40)
        self.assertEqual(结果[0]["类别"], "兵种")
        self.assertTrue(any("启用高速下兵" in 文本 for 文本 in 状态))

    def test_低分未匹配攻城候选且x20回退为普通兵种(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务.兵栏槽位 = [("第1格", (0, 0, 10, 10))]
        任务.取本次兵种模板列表 = lambda _上下文: ["兵种_攻城气球.bmp"]
        任务._识别槽位文本 = lambda _图像: ("x20", "")
        任务._识别槽位数量 = lambda _图像, _文本: 20
        任务._槽位最佳模板 = Mock(side_effect=[
            ("未匹配攻城器械模板", 0.55), ("", 0.0), ("", 0.0),
        ])
        任务.是否为灰色图片 = lambda *_参数, **_关键字: False
        状态 = []
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: np.zeros((10, 10, 3), dtype=np.uint8),
            ),
            置脚本状态=状态.append,
        )

        结果 = 任务.检查当前配兵(上下文)

        self.assertEqual(结果[0]["类别"], "兵种")
        self.assertEqual(结果[0]["数量"], 20)
        self.assertTrue(结果[0]["数量已确认"])

    def test_九条雷龙模板失配时不能判成攻城器械(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务.兵栏槽位 = [("第1格", (0, 0, 10, 10))]
        任务.取本次兵种模板列表 = lambda _上下文: []
        任务._识别槽位文本 = lambda _图像: "x9|9"
        任务._识别槽位数量 = lambda _图像, _文本: 9
        任务._槽位最佳模板 = lambda *_参数: ("", 0.0)
        任务.是否为灰色图片 = lambda *_参数, **_关键字: False
        状态 = []
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: np.zeros((10, 10, 3), dtype=np.uint8),
            ),
            置脚本状态=状态.append,
        )

        结果 = 任务.检查当前配兵(上下文)

        self.assertEqual(结果[0]["类别"], "兵种")
        self.assertEqual(结果[0]["数量"], 9)

    def test_没有英雄时闪电法术前的单个飞艇仍是攻城器械(self):
        任务 = 进攻任务.__new__(进攻任务)
        结果 = 任务._按英雄布局修正槽位类别([
            {"槽位": 1, "类别": "兵种", "名称": "未匹配兵种模板", "数量": 9},
            {"槽位": 2, "类别": "兵种", "名称": "兵种_气球兵", "数量": 16},
            {"槽位": 3, "类别": "兵种", "名称": "兵种_弓箭手", "数量": 2},
            {"槽位": 4, "类别": "未知", "名称": "未匹配模板", "数量": 1},
            {"槽位": 5, "类别": "药水", "名称": "法术_闪电法术", "数量": 11},
            {"槽位": 6, "类别": "未知", "名称": "未匹配模板", "数量": 1},
        ], 0)
        self.assertEqual([项["类别"] for 项 in 结果],
                         ["兵种", "兵种", "兵种", "攻城器械", "药水", "药水"])

    def test_闪电法术模板失配时按已确认槽位下兵并复核数量(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.读取槽位显示兵量 = Mock(side_effect=[3, 2, 1, 0])
        任务.读取兵栏槽位图像 = Mock(return_value=None)
        点击 = Mock(return_value=True)
        日志 = []
        上下文 = SimpleNamespace(
            当前兵栏清单=[{
                "名称": "法术_闪电法术", "类别": "药水", "数量已确认": True,
                "数量": 3, "区域": (320, 493, 376, 594),
            }],
            本场进攻方向=["左上"],
            点击=点击,
            置脚本状态=日志.append,
        )

        self.assertTrue(任务.执行已识别闪电法术(上下文))

        self.assertEqual(点击.call_count, 4)
        self.assertEqual(点击.call_args_list[0].args, (348, 543))
        self.assertEqual(任务.读取槽位显示兵量.call_count, 4)
        self.assertTrue(any("3/3个" in 文本 for 文本 in 日志))

    def test_战中OCR暂不可读但数字确实变化可继续投放(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.读取槽位显示兵量 = Mock(return_value=None)
        任务.读取兵栏槽位图像 = Mock(side_effect=[
            np.zeros((90, 60, 3), dtype=np.uint8),
            np.pad(np.ones((10, 10, 3), dtype=np.uint8) * 255,
                   ((4, 76), (30, 20), (0, 0))),
            np.zeros((90, 60, 3), dtype=np.uint8),
        ])
        点击 = Mock(return_value=True)
        日志 = []
        上下文 = SimpleNamespace(
            当前兵栏清单=[{
                "名称": "法术_闪电法术", "类别": "药水", "数量已确认": True,
                "数量": 2, "区域": (320, 493, 376, 594),
            }],
            本场进攻方向=["左上"], 点击=点击, 置脚本状态=日志.append,
        )
        self.assertTrue(任务.执行已识别闪电法术(上下文))
        self.assertEqual(点击.call_count, 3)
        self.assertTrue(any("2/2个" in 文本 for 文本 in 日志))

    def test_点击后数字刷新慢时等一下复读再继续(self):
        # rc131 实机：OCR 提速后点完立刻读到旧数字，两场都停在 8/11。
        任务 = 进攻任务.__new__(进攻任务)
        任务.战斗是否仍在进行 = Mock(return_value=True)
        # 开战读 3；第 1 次点后读到旧的 3，等待后复读到 2；之后正常下降
        任务.读取槽位显示兵量 = Mock(side_effect=[3, 3, 2, 1, 0])
        任务.读取兵栏槽位图像 = Mock(return_value=None)
        点击 = Mock(return_value=True)
        延时 = Mock()
        日志 = []
        上下文 = SimpleNamespace(
            当前兵栏清单=[{
                "名称": "法术_闪电法术", "类别": "药水", "数量已确认": True,
                "数量": 3, "区域": (320, 493, 376, 594),
            }],
            本场进攻方向=["左上"], 点击=点击, 置脚本状态=日志.append, 脚本延时=延时,
        )
        self.assertTrue(任务.执行已识别闪电法术(上下文))
        延时.assert_called_once_with(500)
        self.assertTrue(any("3/3个" in 文本 for 文本 in 日志))

    def test_数字迟迟不降时最多复读三次后停止(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.读取槽位显示兵量 = Mock(side_effect=[3, 3, 3, 3, 3])
        任务.读取兵栏槽位图像 = Mock(return_value=None)
        点击 = Mock(return_value=True)
        延时 = Mock()
        日志 = []
        上下文 = SimpleNamespace(
            当前兵栏清单=[{
                "名称": "法术_闪电法术", "类别": "药水", "数量已确认": True,
                "数量": 3, "区域": (320, 493, 376, 594),
            }],
            本场进攻方向=["左上"], 点击=点击, 置脚本状态=日志.append, 脚本延时=延时,
        )
        self.assertTrue(任务.执行已识别闪电法术(上下文))
        self.assertEqual(延时.call_count, 3)
        self.assertEqual(点击.call_count, 2)  # 选卡 + 1 次落点
        self.assertTrue(any("未确认下降" in 文本 for 文本 in 日志))

    def test_闪电法术未确认数量时不盲点槽位(self):
        任务 = 进攻任务.__new__(进攻任务)
        点击 = Mock(return_value=True)
        上下文 = SimpleNamespace(
            当前兵栏清单=[{
                "名称": "法术_闪电法术", "类别": "药水", "数量已确认": False,
                "数量": 11, "区域": (320, 493, 376, 594),
            }],
            点击=点击,
        )

        self.assertFalse(任务.执行已识别闪电法术(上下文))
        点击.assert_not_called()

    def test_战前已投放闪电时战后法术流程不得重复投放(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务.乱生效类法术列表 = ["法术_闪电法术.bmp"]
        任务.执行已识别闪电法术 = Mock()
        上下文 = SimpleNamespace(_闪电已提前处理=True)
        任务.执行其他法术流程(上下文)
        任务.执行已识别闪电法术.assert_not_called()

    def test_英雄技能无专用模板时按英雄槽位识别高亮(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务.模板识别 = Mock()
        任务.模板识别._安全加载模板.return_value = None
        战前图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        战后图像 = 战前图像.copy()
        # 模拟第4格英雄技能区域出现紫色高亮；颜色使用 BGR。
        战后图像[530:570, 245:290] = (200, 0, 255)
        上下文 = SimpleNamespace(
            当前兵栏清单=[{
                "槽位": 4,
                "名称": "英雄_野蛮人之王",
                "类别": "英雄",
                "区域": (234, 510, 304, 594),
            }],
            _战斗开始兵栏画面=战前图像,
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=战后图像),
            ),
            置脚本状态=Mock(),
        )
        状态 = 任务.识别英雄技能状态(上下文)
        self.assertEqual(状态["第4格/英雄_野蛮人之王"], "可用")

    def test_夜世界结果页只有摧毁率和熄灭星时记录零星(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        self.assertEqual(
            任务.识别星数(画面, "摧毁率：43%"),
            0,
        )

    def test_英雄技能灰色主体优先于残留高亮(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务.模板识别 = Mock()
        任务.模板识别._安全加载模板.return_value = None
        战前图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        战后图像 = 战前图像.copy()
        区域 = (234, 510, 304, 594)
        战后图像[510:594, 234:304] = (139, 139, 139)
        # 模拟使用后灰色卡牌边缘残留约5%的紫色高亮。
        战后图像[540:550, 250:280] = (200, 0, 255)
        上下文 = SimpleNamespace(
            当前兵栏清单=[{
                "槽位": 4,
                "类别": "英雄",
                "名称": "英雄_野蛮人之王",
                "区域": 区域,
            }],
            _战斗开始兵栏画面=战前图像,
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=战后图像)),
            置脚本状态=Mock(),
        )
        状态 = 任务.识别英雄技能状态(上下文)
        self.assertEqual(状态["第4格/英雄_野蛮人之王"], "已使用/不可用")

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
        任务.战斗是否仍在进行 = Mock(return_value=True)
        候选点 = 任务.生成可下兵候选点(上下文, 坐标(400, 285))
        with patch.object(任务, "读取兵栏槽位图像", side_effect=[object()] * 5), \
             patch.object(任务, "判断下兵反馈", side_effect=[False, False, False, True]):
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

    def test_局部候选全部失败时使用本场已验证全局落点(self):
        任务 = 进攻任务.__new__(进攻任务)
        点击记录 = []
        日志 = []
        全局落点 = (500, 100)
        上下文 = SimpleNamespace(
            _部署区域已初始化=True,
            _部署红色掩码=None,
            本场可下兵区域={
                "边界顶点": [(394, 20), (745, 293), (405, 549), (68, 278)],
                "边界带宽": 58.0,
            },
            _本场全局已确认下兵点={"1:兵种": 全局落点},
            点击=lambda x, y, **_参数: 点击记录.append((x, y)),
            脚本延时=lambda _毫秒: None,
            置脚本状态=日志.append,
        )
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.下兵点是否位于可下兵区域 = Mock(return_value=True)
        任务.读取兵栏槽位图像 = lambda *_参数: object()
        with patch.object(
            任务,
            "判断下兵反馈",
            side_effect=[False] * 4 + [True],
        ):
            成功, 使用坐标 = 任务.尝试下兵至可用位置(
                上下文,
                {"槽位": 1, "名称": "测试兵", "类别": "兵种", "区域": (0, 0, 1, 1)},
                坐标(430, 360),
                [(100, 100), (110, 110)],
                5,
            )
        self.assertTrue(成功)
        self.assertEqual(使用坐标, 全局落点)
        self.assertEqual(点击记录, [(100, 100), (110, 110), 全局落点])
        self.assertTrue(any("使用本场已验证落点" in 文本 for 文本 in 日志))

    def test_同方向不同目标不共享同一个缓存落点(self):
        任务 = 进攻任务.__new__(进攻任务)
        兵栏项 = {"槽位": 1}
        self.assertNotEqual(
            任务._下兵方向缓存键(坐标(620, 400), 兵栏项),
            任务._下兵方向缓存键(坐标(670, 400), 兵栏项),
        )
        # 实机相邻资源建筑可能只相差约30px；旧的48px分桶会让它们
        # 共享缓存落点，日志中表现为连续两次点击同一坐标。
        self.assertNotEqual(
            任务._下兵方向缓存键(坐标(326, 96), 兵栏项),
            任务._下兵方向缓存键(坐标(294, 114), 兵栏项),
        )

    def test_同一坐标被拒绝后本场不重复点击(self):
        任务 = 进攻任务.__new__(进攻任务)
        点击记录 = []
        上下文 = SimpleNamespace(
            _部署区域已初始化=True,
            _部署红色掩码=None,
            本场可下兵区域={
                "边界顶点": [(394, 20), (745, 293), (405, 549), (68, 278)],
                "边界带宽": 58.0,
            },
            点击=lambda x, y, **_参数: 点击记录.append((x, y)),
            脚本延时=lambda _毫秒: None,
            置脚本状态=lambda *_参数: None,
        )
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.下兵点是否位于可下兵区域 = Mock(return_value=True)
        任务.读取兵栏槽位图像 = lambda *_参数: object()
        任务.判断下兵反馈 = Mock(return_value=False)
        兵栏项 = {"槽位": 1, "名称": "测试兵", "类别": "兵种", "区域": (0, 0, 1, 1)}
        目标 = 坐标(400, 285)
        候选点 = [(394, 20)]
        任务.尝试下兵至可用位置(上下文, 兵栏项, 目标, 候选点, 5)
        任务.尝试下兵至可用位置(上下文, 兵栏项, 目标, 候选点, 5)
        self.assertEqual(点击记录, [候选点[0]])

    def test_不同兵种槽位共享已拒绝下兵点(self):
        """同一地形被游戏拒绝后，切换兵种不应重新探测该点。"""
        任务 = 进攻任务.__new__(进攻任务)
        点击记录 = []
        上下文 = SimpleNamespace(
            _部署区域已初始化=True,
            _部署红色掩码=None,
            本场可下兵区域={
                "边界顶点": [(394, 20), (745, 293), (405, 549), (68, 278)],
                "边界带宽": 58.0,
            },
            _本场全局被拒绝下兵点=set(),
            点击=lambda x, y, **_参数: 点击记录.append((x, y)),
            脚本延时=lambda _毫秒: None,
            置脚本状态=lambda *_参数: None,
        )
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.下兵点是否位于可下兵区域 = Mock(return_value=True)
        任务.读取兵栏槽位图像 = lambda *_参数: object()
        任务.判断下兵反馈 = Mock(return_value=False)
        目标 = 坐标(400, 285)
        候选点 = [(394, 20)]

        任务.尝试下兵至可用位置(
            上下文,
            {"槽位": 1, "名称": "兵种A", "类别": "兵种", "区域": (0, 0, 1, 1)},
            目标,
            候选点,
            5,
        )
        任务.尝试下兵至可用位置(
            上下文,
            {"槽位": 2, "名称": "兵种B", "类别": "兵种", "区域": (0, 0, 1, 1)},
            目标,
            候选点,
            5,
        )

        self.assertEqual(点击记录, [候选点[0]])
        self.assertIn(候选点[0], 上下文._本场全局被拒绝下兵点)

    def test_同一局部连续拒绝后跳过剩余点(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务.实际下兵位置尝试上限 = 6
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
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.下兵点是否位于可下兵区域 = Mock(return_value=True)
        任务.读取兵栏槽位图像 = lambda *_参数: object()
        任务.判断下兵反馈 = Mock(return_value=False)
        兵栏项 = {"槽位": 1, "名称": "测试兵", "类别": "法术", "区域": (0, 0, 1, 1)}
        候选点 = [
            (100, 100), (110, 105), (120, 110), (130, 115),
            (300, 300),
        ]

        结果 = 任务.尝试下兵至可用位置(
            上下文, 兵栏项, 坐标(400, 285), 候选点, 5
        )

        self.assertEqual(结果, (False, None))
        self.assertEqual(点击记录, [(100, 100), (110, 105), (120, 110), (300, 300)])
        self.assertTrue(any("局部下兵区域连续" in 文本 for 文本 in 日志))

    def test_结算页出现后候选点循环立即停止(self):
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
        任务.读取兵栏槽位图像 = lambda *_参数: object()
        任务.战斗是否仍在进行 = Mock(return_value=False)
        成功, 坐标结果 = 任务.尝试下兵至可用位置(
            上下文,
            {"名称": "测试兵", "区域": (0, 0, 1, 1), "类别": "兵种"},
            坐标(400, 285),
            [(400, 20), (410, 25)],
            5,
        )
        self.assertFalse(成功)
        self.assertIsNone(坐标结果)
        self.assertEqual(点击记录, [])
        self.assertTrue(any("停止目标" in 文本 for 文本 in 日志))

    def test_兵量足够的普通兵种才启用高速批次(self):
        任务 = 进攻任务.__new__(进攻任务)
        设置 = SimpleNamespace(是否启用高速下兵=True)
        上下文 = SimpleNamespace(设置=设置)
        self.assertEqual(任务.取高速下兵批次(上下文, {"类别": "兵种", "数量": 7}, 7), 1)
        self.assertEqual(任务.取高速下兵批次(上下文, {"类别": "兵种", "数量": 16}, 10), 10)
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
        # 高速批次允许批量点击，实机通过兵栏
        # 数量复核是否真的被游戏逐个消费。
        self.assertEqual(
            任务.执行高速下兵批次(
                上下文, (100, 200), 5, "快速连点", 间隔毫秒=45
            ),
            5,
        )
        self.assertEqual(
            任务.执行高速下兵批次(
                上下文, (100, 200), 2, "快速连点", 间隔毫秒=25
            ),
            2,
        )
        self.assertEqual(任务.执行高速下兵批次(上下文, (100, 200), 2, "短按压"), 2)
        self.assertEqual([项[0] for 项 in 鼠标对象.调用], ["连点", "连点", "短按"])
        self.assertEqual(鼠标对象.调用[0][2]["间隔毫秒"], 45)
        self.assertEqual(鼠标对象.调用[1][2]["间隔毫秒"], 40)

    def test_高速分散批次把后续单位发送到不同目标(self):
        class 鼠标:
            def __init__(self):
                self.调用 = []

            def 连续点击多点(self, 点位, **关键字):
                self.调用.append((list(点位), 关键字))
                return True

        鼠标对象 = 鼠标()
        上下文 = SimpleNamespace(
            鼠标=鼠标对象,
            置脚本状态=lambda *_参数, **_关键字: None,
        )
        任务 = 进攻任务.__new__(进攻任务)
        数量 = 任务.执行高速下兵批次(
            上下文,
            (100, 200),
            2,
            "快速连点",
            分散下兵点列表=[(120, 200), (140, 200)],
        )
        self.assertEqual(数量, 2)
        self.assertEqual(鼠标对象.调用[0][0], [(120, 200), (140, 200)])
        self.assertTrue(getattr(上下文, "_最近高速批次使用分散"))

    def test_边界不可见时高速批次只复用本场已确认落点(self):
        任务 = 进攻任务.__new__(进攻任务)
        上下文 = SimpleNamespace(
            本场可下兵区域={"颜色边界可见": False},
        )
        点位 = 任务.生成高速分散下兵点(
            上下文,
            {"槽位": 1},
            0,
            4,
            2,
            [[(30, 40), (31, 41)], [(50, 50)]],
            (10, 20),
        )
        self.assertEqual(点位, [(10, 20)] * 4)

    def test_已确认点批次不标记为多目标分散(self):
        class 鼠标:
            def __init__(self):
                self.调用 = []

            def 连续点击多点(self, 点位, **关键字):
                self.调用.append((list(点位), 关键字))
                return True

        上下文 = SimpleNamespace(
            鼠标=鼠标(),
            置脚本状态=lambda *_参数, **_关键字: None,
        )
        任务 = 进攻任务.__new__(进攻任务)
        self.assertEqual(
            任务.执行高速下兵批次(
                上下文,
                (120, 200),
                3,
                "快速连点",
                分散下兵点列表=[(120, 200)] * 3,
            ),
            3,
        )
        self.assertEqual(上下文.鼠标.调用[0][0], [(120, 200)] * 3)
        self.assertFalse(getattr(上下文, "_最近高速批次使用分散"))

    def test_高速下兵默认间隔设为八十毫秒(self):
        self.assertEqual(进攻任务.高速连点间隔毫秒, 80)

    def test_高速分散点按目标顺序循环并跳过拒绝点(self):
        任务 = 进攻任务.__new__(进攻任务)
        上下文 = SimpleNamespace(
            _本场被拒绝下兵点={(1, 30, 40)},
        )
        点位 = 任务.生成高速分散下兵点(
            上下文,
            {"槽位": 1},
            0,
            3,
            3,
            [
                [(10, 10)],
                [(30, 40), (31, 41)],
                [(50, 50)],
            ],
            (8, 8),
        )
        self.assertEqual(点位, [(31, 41), (50, 50), (10, 10)])

    def test_高速分散点不会用当前点回填被拒绝目标(self):
        任务 = 进攻任务.__new__(进攻任务)
        上下文 = SimpleNamespace(
            _本场被拒绝下兵点={(1, 30, 40), (1, 31, 41)},
            _本槽位无效目标索引={1},
        )
        点位 = 任务.生成高速分散下兵点(
            上下文,
            {"槽位": 1},
            0,
            2,
            3,
            [
                [(10, 10)],
                [(30, 40), (31, 41)],
                [(50, 50)],
            ],
            (10, 10),
        )
        self.assertEqual(点位, [(50, 50)])
        self.assertNotIn((10, 10), 点位)

    def test_高速分散点会在首轮后继续填充同目标备用落点(self):
        任务 = 进攻任务.__new__(进攻任务)
        上下文 = SimpleNamespace()
        点位 = 任务.生成高速分散下兵点(
            上下文,
            {"槽位": 1},
            0,
            5,
            3,
            [
                [(10, 10), (11, 11)],
                [(30, 30), (31, 31)],
                [(50, 50), (51, 51)],
            ],
            (8, 8),
        )
        self.assertEqual(
            点位,
            [(30, 30), (50, 50), (10, 10), (31, 31), (51, 51)],
        )

    def test_没有备用安全落点时高速批次不回退同点连点(self):
        class 鼠标:
            def __init__(self):
                self.调用 = []

            def 连续点击(self, *参数, **关键字):
                self.调用.append((参数, 关键字))
                return True

        日志 = []
        上下文 = SimpleNamespace(
            鼠标=鼠标(),
            置脚本状态=日志.append,
        )
        任务 = 进攻任务.__new__(进攻任务)
        数量 = 任务.执行高速下兵批次(
            上下文,
            (100, 200),
            5,
            "快速连点",
            分散下兵点列表=[],
        )
        self.assertEqual(数量, 0)
        self.assertEqual(上下文.鼠标.调用, [])
        self.assertTrue(any("跳过同点连点" in 文本 for 文本 in 日志))

    def test_高速批次完成后不会按单位数跳过资源目标(self):
        """一个批次共下多个单位，但这些单位共用一个目标落点。"""
        任务 = 进攻任务.__new__(进攻任务)
        目标数 = 20
        目标索引 = 0
        访问顺序 = []
        for _ in range(目标数):
            访问顺序.append(目标索引)
            # 与执行下兵流程的批次推进逻辑保持一致：每批只前进一个目标。
            目标索引 = 任务.推进资源目标索引(目标索引, 目标数)
        self.assertEqual(访问顺序, list(range(目标数)))
        self.assertEqual(任务.推进资源目标索引(0, 0), 0)
        self.assertEqual(任务.推进资源目标索引(0, 20, 7), 7)

    def test_新版九格兵栏按64像素间距覆盖第七第八英雄槽(self):
        """实机新版兵栏从第五格起不能继续按66px累积偏移。"""
        self.assertEqual(
            [区域[0] for _, 区域 in 进攻任务.可见兵栏格子],
            [56, 120, 184, 248, 312, 376, 440, 504, 568],
        )
        第八格区域 = 进攻任务.可见兵栏格子[7][1]
        self.assertEqual(
            进攻任务._英雄技能点击点列表(第八格区域),
            [(508, 503), (513, 503), (508, 508)],
        )

    def test_英雄后第一个未匹配槽位保留为攻城器械(self):
        任务 = 进攻任务.__new__(进攻任务)
        结果 = 任务._按英雄布局修正槽位类别([
            {"槽位": 4, "类别": "英雄", "名称": "英雄_野蛮人之王", "数量": 1},
            {"槽位": 5, "类别": "攻城器械", "名称": "未匹配攻城器械模板", "数量": 2},
            {"槽位": 6, "类别": "未知", "名称": "法术_生日大爆炸法术", "数量": 2},
            {"槽位": 7, "类别": "未知", "名称": "未匹配模板", "数量": 0},
        ], 4)
        self.assertEqual(结果[1]["类别"], "攻城器械")
        self.assertEqual(结果[2]["类别"], "药水")
        self.assertEqual(结果[3]["类别"], "药水")

    def test_新版九格兵栏中英雄后未匹配卡牌按证据识别为英雄(self):
        任务 = 进攻任务.__new__(进攻任务)
        兵栏 = [
            {"槽位": 5, "类别": "英雄", "名称": "英雄_野蛮人之王", "数量": 1},
            {"槽位": 6, "类别": "未知", "名称": "未匹配模板", "数量": 1,
             "OCR": "|99", "顶部数量已识别": False, "卡牌为灰色": False},
            {"槽位": 7, "类别": "药水", "名称": "未匹配模板", "数量": 1,
             "OCR": "|71", "顶部数量已识别": False, "卡牌为灰色": False},
            {"槽位": 8, "类别": "未知", "名称": "未匹配模板", "数量": 1,
             "OCR": "|25", "顶部数量已识别": False, "卡牌为灰色": False},
            {"槽位": 9, "类别": "药水", "名称": "法术_闪电法术", "数量": 11,
             "OCR": "x11|13", "顶部数量已识别": True, "卡牌为灰色": False},
        ]

        结果 = 任务._按英雄布局修正槽位类别(兵栏, 5)

        self.assertEqual([项["类别"] for 项 in 结果], ["英雄", "英雄", "英雄", "英雄", "药水"])
        self.assertTrue(all(项["名称"].startswith("英雄_") for 项 in 结果[1:4]))

    def test_新版九格兵栏中不可信x0不应把英雄错分为兵种或法术(self):
        任务 = 进攻任务.__new__(进攻任务)
        兵栏 = [
            {"槽位": 5, "类别": "英雄", "名称": "英雄_野蛮人之王", "数量": 1},
            {"槽位": 6, "类别": "攻城器械", "名称": "未匹配模板(待探测)", "数量": 1,
             "数量已确认": False, "OCR": "x0|99", "顶部数量已识别": True, "卡牌为灰色": False},
            {"槽位": 7, "类别": "药水", "名称": "未匹配模板(待探测)", "数量": 1,
             "数量已确认": False, "OCR": "x0|71", "顶部数量已识别": True, "卡牌为灰色": False},
            {"槽位": 8, "类别": "未知", "名称": "未匹配模板(待探测)", "数量": 1,
             "数量已确认": False, "OCR": "x0|25", "顶部数量已识别": True, "卡牌为灰色": False},
            {"槽位": 9, "类别": "药水", "名称": "法术_闪电法术", "数量": 11,
             "数量已确认": True, "OCR": "x11|13", "顶部数量已识别": True, "卡牌为灰色": False},
        ]

        结果 = 任务._按英雄布局修正槽位类别(兵栏, 5)

        self.assertEqual([项["类别"] for 项 in 结果], ["英雄", "英雄", "英雄", "英雄", "药水"])
        self.assertTrue(all(项["数量"] == 1 for 项 in 结果[1:4]))

    def test_新版九格兵栏第九格法术未命中模板时仍识别后续英雄(self):
        任务 = 进攻任务.__new__(进攻任务)
        兵栏 = [
            {"槽位": 5, "类别": "英雄", "名称": "英雄_野蛮人之王", "数量": 1},
            {"槽位": 6, "类别": "攻城器械", "名称": "未匹配模板(待探测)", "数量": 1,
             "数量已确认": False, "OCR": "x0|99", "顶部数量已识别": True, "卡牌为灰色": False},
            {"槽位": 7, "类别": "药水", "名称": "未匹配模板(待探测)", "数量": 1,
             "数量已确认": False, "OCR": "x0|71", "顶部数量已识别": True, "卡牌为灰色": False},
            {"槽位": 8, "类别": "药水", "名称": "未匹配模板(待探测)", "数量": 1,
             "数量已确认": False, "OCR": "x0|25", "顶部数量已识别": True, "卡牌为灰色": False},
            {"槽位": 9, "类别": "药水", "名称": "未匹配模板", "数量": 11,
             "数量已确认": True, "OCR": "x11|13", "顶部数量已识别": True, "卡牌为灰色": False},
        ]

        结果 = 任务._按英雄布局修正槽位类别(兵栏, 5)

        self.assertEqual([项["类别"] for 项 in 结果], ["英雄", "英雄", "英雄", "英雄", "药水"])
        self.assertEqual([项["数量"] for 项 in 结果[1:4]], [1, 1, 1])

    def test_英雄名称优先修正被回退为普通兵种的类别(self):
        任务 = 进攻任务.__new__(进攻任务)
        结果 = 任务._按英雄布局修正槽位类别([
            {"槽位": 5, "类别": "兵种", "名称": "英雄_飞龙公爵", "数量": 20},
        ], 0)
        self.assertEqual(结果[0]["类别"], "英雄")
        self.assertEqual(结果[0]["数量"], 1)

    def test_英雄技能点击集中在卡片左上角徽标(self):
        区域 = (316, 493, 372, 594)
        点位 = 进攻任务._英雄技能点击点列表(区域)
        self.assertEqual(点位, [(320, 503), (325, 503), (320, 508)])
        self.assertTrue(all(316 <= x < 332 and 499 <= y < 516 for x, y in 点位))

    def test_英雄落地后只尝试一次可用技能(self):
        任务 = 进攻任务.__new__(进攻任务)
        日志 = []
        点击 = Mock(return_value=True)
        上下文 = SimpleNamespace(
            _本场已部署槽位={4},
            _本场已释放英雄技能=set(),
            英雄技能状态={"第4格/英雄_野蛮人之王": "可用"},
            停止事件=SimpleNamespace(is_set=lambda: False),
            点击=点击,
            脚本延时=lambda _毫秒: None,
            置脚本状态=日志.append,
        )
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.识别英雄技能状态 = Mock(
            return_value={"第4格/英雄_野蛮人之王": "已使用/不可用"}
        )
        兵栏项 = {
            "槽位": 4,
            "名称": "英雄_野蛮人之王",
            "区域": (254, 493, 310, 594),
        }
        self.assertTrue(任务.尝试释放英雄技能(上下文, 兵栏项))
        self.assertEqual(点击.call_args_list[0].args[:2], (258, 503))
        self.assertIn(4, 上下文._本场已释放英雄技能)
        self.assertTrue(any("技能已点击" in 文本 for 文本 in 日志))

    def test_英雄技能首次点击未生效时只复核一次(self):
        任务 = 进攻任务.__new__(进攻任务)
        日志 = []
        点击 = Mock(return_value=True)
        上下文 = SimpleNamespace(
            _本场已部署槽位={5},
            _本场已释放英雄技能=set(),
            _本场技能复核重试槽位=set(),
            英雄技能状态={"第5格/英雄_飞盾战神": "可用"},
            停止事件=SimpleNamespace(is_set=lambda: False),
            点击=点击,
            脚本延时=lambda _毫秒: None,
            置脚本状态=日志.append,
        )
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.识别英雄技能状态 = Mock(side_effect=[
            {"第5格/英雄_飞盾战神": "可用"},
            {"第5格/英雄_飞盾战神": "已使用/不可用"},
        ])
        兵栏项 = {
            "槽位": 5,
            "名称": "英雄_飞盾战神",
            "区域": (316, 493, 372, 594),
        }
        self.assertTrue(任务.尝试释放英雄技能(上下文, 兵栏项))
        self.assertEqual(点击.call_count, 2)
        self.assertIn(5, 上下文._本场技能复核重试槽位)
        self.assertTrue(any("复核点击后状态" in 文本 for 文本 in 日志))

    def test_英雄技能备用点击仍限制在当前卡牌内(self):
        任务 = 进攻任务.__new__(进攻任务)
        点击记录 = []
        日志 = []
        上下文 = SimpleNamespace(
            _本场已部署槽位={5},
            _本场已释放英雄技能=set(),
            _本场技能复核重试槽位=set(),
            英雄技能状态={"第5格/英雄_飞盾战神": "可用"},
            停止事件=SimpleNamespace(is_set=lambda: False),
            点击=lambda x, y, **_参数: 点击记录.append((x, y)) or True,
            脚本延时=lambda _毫秒: None,
            置脚本状态=日志.append,
        )
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.识别英雄技能状态 = Mock(
            side_effect=[
                {"第5格/英雄_飞盾战神": "可用"},
                {"第5格/英雄_飞盾战神": "可用"},
                {"第5格/英雄_飞盾战神": "可用"},
            ]
        )
        区域 = (316, 493, 372, 594)
        self.assertTrue(
            任务.尝试释放英雄技能(
                上下文,
                {"槽位": 5, "名称": "英雄_飞盾战神", "区域": 区域},
            )
        )
        self.assertEqual(len(点击记录), 3)
        左, 上, 右, 下 = 区域
        self.assertTrue(all(左 <= x < 右 and 上 <= y < 下 for x, y in 点击记录))
        self.assertTrue(any("备用点击后仍显示可用" in 文本 for 文本 in 日志))

    def test_英雄落地后初判不可用会重新识别并释放技能(self):
        任务 = 进攻任务.__new__(进攻任务)
        日志 = []
        点击 = Mock(return_value=True)
        上下文 = SimpleNamespace(
            _本场已部署槽位={4},
            _本场已释放英雄技能=set(),
            英雄技能状态={"第4格/英雄_野蛮人之王": "已使用/不可用"},
            停止事件=SimpleNamespace(is_set=lambda: False),
            点击=点击,
            脚本延时=lambda _毫秒: None,
            置脚本状态=日志.append,
        )
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.识别英雄技能状态 = Mock(
            return_value={"第4格/英雄_野蛮人之王": "可用"}
        )
        兵栏项 = {
            "槽位": 4,
            "名称": "英雄_野蛮人之王",
            "区域": (254, 493, 310, 594),
        }

        self.assertTrue(任务.尝试释放英雄技能(上下文, 兵栏项))
        self.assertGreaterEqual(任务.识别英雄技能状态.call_count, 2)
        self.assertEqual(点击.call_args_list[0].args[:2], (258, 503))
        self.assertIn(4, 上下文._本场已释放英雄技能)
        self.assertTrue(any("准备复核" in 文本 for 文本 in 日志))

    def test_同一兵栏槽位连续下兵不会重复点击反选(self):
        任务 = 进攻任务.__new__(进攻任务)
        点击记录 = []
        设置 = SimpleNamespace(是否启用高速下兵=False, 下兵间隔毫秒=5)
        上下文 = SimpleNamespace(
            设置=设置,
            当前兵栏清单=[
                {"槽位": 1, "类别": "兵种", "数量": 2,
                 "区域": (20, 20, 50, 50), "名称": "测试兵"}
            ],
            点击=lambda x, y, **_参数: 点击记录.append((x, y)),
            置脚本状态=lambda *_参数, **_关键字: None,
            脚本延时=lambda _毫秒: None,
            op=SimpleNamespace(获取屏幕图像cv=lambda *_区域: np.full((30, 30, 3), (0, 80, 200), dtype=np.uint8)),
        )
        任务.准备可下兵区域 = lambda *_参数, **_关键字: None
        任务.生成可下兵候选点 = lambda *_参数: [(100, 100)]
        任务.记录可下兵点标记 = lambda *_参数: None
        任务.刷新选中兵种后的下兵边界 = lambda *_参数: None
        任务.战斗是否仍在进行 = lambda *_参数: True
        任务.是否为灰色图片 = lambda *_参数: False
        with patch.object(任务, "尝试下兵至可用位置", side_effect=[(True, (100, 100)), (True, (700, 500))]):
            任务.执行下兵流程(上下文, [{"中心坐标": 坐标(100, 100)}])
        self.assertEqual(点击记录, [(35, 35)])
        self.assertEqual(上下文._本场已确认投放数量, 2)
        self.assertEqual(
            上下文._本场已确认投放方向集合,
            {
                取进攻方向(坐标(100, 100)),
                取进攻方向(坐标(700, 500)),
            },
        )

    def test_高速批次只按兵栏确认的消费数记录额外落点(self):
        任务 = 进攻任务.__new__(进攻任务)
        设置 = SimpleNamespace(是否启用高速下兵=False, 下兵间隔毫秒=5)
        上下文 = SimpleNamespace(
            设置=设置,
            当前兵栏清单=[
                {"槽位": 1, "类别": "兵种", "数量": 3,
                 "区域": (20, 20, 50, 50), "名称": "测试兵"}
            ],
            点击=lambda *_参数, **_关键字: True,
            置脚本状态=lambda *_参数, **_关键字: None,
            脚本延时=lambda _毫秒: None,
            鼠标=SimpleNamespace(连续点击多点=lambda *_参数: None),
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: np.full(
                    (30, 30, 3), (0, 80, 200), dtype=np.uint8
                )
            ),
        )
        任务.准备可下兵区域 = lambda *_参数, **_关键字: None
        任务.生成可下兵候选点 = lambda *_参数: [(100, 100)]
        任务.记录可下兵点标记 = lambda *_参数: None
        任务.刷新选中兵种后的下兵边界 = lambda *_参数: setattr(
            上下文, "_部署边界已刷新", True
        )
        任务.战斗是否仍在进行 = lambda *_参数: True
        任务.是否为灰色图片 = lambda *_参数: False
        任务.尝试下兵至可用位置 = lambda *_参数: (True, (100, 100))
        任务.取高速下兵批次 = lambda *_参数: 3
        批量落点 = [(700, 100), (700, 500)]
        任务.生成高速分散下兵点 = lambda *_参数: 批量落点
        def 执行批次(上下文, *_参数, **_关键字):
            上下文._最近高速批次使用分散 = True
            return 2
        任务.执行高速下兵批次 = 执行批次
        任务.读取槽位显示兵量 = lambda *_参数, **_关键字: 0

        任务.执行下兵流程(上下文, [{"中心坐标": 坐标(100, 100)}])

        self.assertEqual(上下文._本场已确认投放数量, 3)
        self.assertEqual(
            上下文._本场已确认投放方向集合,
            {取进攻方向(坐标(x, y)) for x, y in [(100, 100), *批量落点]},
        )

    def test_实际下兵顺序把英雄前置避免战斗末段才释放技能(self):
        任务 = 进攻任务.__new__(进攻任务)
        尝试顺序 = []
        技能顺序 = []
        设置 = SimpleNamespace(是否自动配兵=False, 下兵间隔毫秒=5)
        上下文 = SimpleNamespace(
            设置=设置,
            当前兵栏清单=[
                {"槽位": 1, "类别": "兵种", "数量": 1,
                 "区域": (20, 20, 50, 50), "名称": "兵种_超级哥布林"},
                {"槽位": 5, "类别": "英雄", "数量": 1,
                 "区域": (284, 493, 340, 594), "名称": "英雄_飞龙公爵"},
            ],
            点击=lambda *_参数, **_关键字: True,
            置脚本状态=lambda *_参数, **_关键字: None,
            脚本延时=lambda _毫秒: None,
            op=SimpleNamespace(获取屏幕图像cv=lambda *_区域: np.full((30, 30, 3), (0, 80, 200), dtype=np.uint8)),
        )
        任务.准备可下兵区域 = lambda *_参数, **_关键字: None
        任务.生成可下兵候选点 = lambda *_参数: [(100, 100)]
        任务.记录可下兵点标记 = lambda *_参数: None
        任务.刷新选中兵种后的下兵边界 = lambda *_参数: None
        任务.战斗是否仍在进行 = lambda _上下文: True
        任务.是否为灰色图片 = lambda _图像: False
        任务.取高速下兵批次 = lambda *_参数: 1

        def 记录下兵(_上下文, 项, *_参数):
            尝试顺序.append(项["槽位"])
            return True, (100, 100)

        任务.尝试下兵至可用位置 = 记录下兵
        任务.尝试释放英雄技能 = lambda _上下文, 项: 技能顺序.append(项["槽位"]) or True

        任务.执行下兵流程(上下文, [{"中心坐标": 坐标(100, 100)}])

        self.assertEqual(尝试顺序, [5, 1])
        self.assertEqual(技能顺序, [5])

    def test_补下读取统一兵栏区域的x0并跳过彩色空卡(self):
        任务 = 进攻任务.__new__(进攻任务)
        日志 = []
        读取区域 = []
        设置 = SimpleNamespace(漏下兵种检测格数=1)
        上下文 = SimpleNamespace(
            机器人标志="测试",
            数据库=SimpleNamespace(获取机器人设置=lambda _标志: 设置),
            当前兵栏清单=[{
                "槽位": 1,
                "类别": "兵种",
                "数量": 117,
                "区域": (56, 493, 112, 594),
                "名称": "兵种_超级哥布林",
            }],
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: np.zeros((36, 56, 3), dtype=np.uint8),
            ),
            置脚本状态=日志.append,
            点击=lambda *_参数, **_关键字: self.fail("x0空卡不应再次点击"),
            脚本延时=lambda _毫秒: None,
        )
        任务.准备可下兵区域 = lambda *_参数, **_关键字: None
        任务.战斗是否仍在进行 = lambda _上下文: True
        任务.是否为灰色图片 = lambda _图像: False

        def 读取当前数量(_上下文, 区域):
            读取区域.append(tuple(区域))
            return 0

        任务.读取槽位显示兵量 = 读取当前数量
        任务.执行漏下兵种下兵流程(
            上下文,
            [{"中心坐标": 坐标(100, 100)}],
        )

        self.assertEqual(读取区域, [(56, 493, 112, 594)])
        self.assertTrue(any("当前数量已确认0" in 文本 for 文本 in 日志))

    def test_补兵复核按普通兵种筛前三种而不扫英雄和法术(self):
        任务 = 进攻任务.__new__(进攻任务)
        读取区域 = []
        区域 = {
            1: (10, 500, 40, 540),
            2: (50, 500, 80, 540),
            3: (90, 500, 120, 540),
            4: (130, 500, 160, 540),
            5: (170, 500, 200, 540),
        }
        任务.可见兵栏格子 = [
            (f"第{槽位}格", 区域[槽位]) for 槽位 in range(1, 6)
        ]
        设置 = SimpleNamespace(漏下兵种检测格数=3)
        清单 = [
            {"槽位": 1, "类别": "兵种", "数量": 2, "区域": 区域[1], "名称": "雷龙"},
            {"槽位": 2, "类别": "英雄", "数量": 1, "区域": 区域[2], "名称": "飞龙公爵"},
            {"槽位": 3, "类别": "兵种", "数量": 22, "区域": 区域[3], "名称": "气球兵"},
            {"槽位": 4, "类别": "药水", "数量": 4, "区域": 区域[4], "名称": "闪电法术"},
            {"槽位": 5, "类别": "兵种", "数量": 2, "区域": 区域[5], "名称": "弓箭手"},
        ]
        上下文 = SimpleNamespace(
            机器人标志="测试",
            数据库=SimpleNamespace(获取机器人设置=lambda _标志: 设置),
            当前兵栏清单=清单,
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: np.zeros((40, 30, 3), dtype=np.uint8),
            ),
            置脚本状态=lambda *_参数, **_关键字: None,
            点击=lambda *_参数, **_关键字: self.fail("数量为0时不应点击"),
            脚本延时=lambda _毫秒: None,
        )
        任务.准备可下兵区域 = lambda *_参数, **_关键字: None
        任务.战斗是否仍在进行 = lambda _上下文: True
        任务.是否为灰色图片 = lambda _图像: False
        任务.读取槽位显示兵量 = lambda _上下文, 格子区域: 读取区域.append(tuple(格子区域)) or 0

        任务.执行漏下兵种下兵流程(
            上下文,
            [{"中心坐标": 坐标(100, 100)}],
        )

        self.assertEqual(读取区域, [区域[1], 区域[3], 区域[5]])

    def test_战斗过渡开始漏兵检测时不读取兵栏也不点击(self):
        任务 = 进攻任务.__new__(进攻任务)
        日志 = []
        上下文 = SimpleNamespace(
            置脚本状态=日志.append,
            点击=lambda *_参数, **_关键字: self.fail("战斗过渡页不应点击"),
        )
        任务.战斗是否仍在进行 = Mock(return_value=False)
        任务.准备可下兵区域 = Mock(side_effect=AssertionError("不应初始化下兵区域"))

        任务.执行漏下兵种下兵流程(
            上下文,
            [{"中心坐标": 坐标(100, 100)}],
        )

        任务.战斗是否仍在进行.assert_called_once_with(上下文)
        任务.准备可下兵区域.assert_not_called()
        self.assertTrue(any("停止补下兵" in 文本 for 文本 in 日志))

    def test_页面护栏误报战斗过渡后复核到战斗不能结束(self):
        任务 = 进攻任务.__new__(进攻任务)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        复核次数 = iter(("战斗过渡", "战斗中"))
        识别器 = SimpleNamespace(
            识别=lambda *_参数, **_关键字: SimpleNamespace(页面=next(复核次数)),
            _战斗倒计时分数=lambda _图像: 0.0,
            _红色放弃按钮分数=lambda _图像: 0.0,
        )
        上下文 = SimpleNamespace(
            停止事件=SimpleNamespace(is_set=lambda: False),
            op=SimpleNamespace(获取屏幕图像cv=lambda *_区域: 屏幕),
            _获取点击页面识别器=lambda: 识别器,
        )

        with patch("任务流程.主世界打鱼.进攻.time.sleep"):
            self.assertTrue(任务.战斗是否仍在进行(上下文))
        self.assertFalse(getattr(上下文, "_战斗结束已确认", False))

    def test_战斗特效持续超过旧版四帧后恢复不会停止(self):
        任务 = 进攻任务.__new__(进攻任务)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        页面序列 = iter(["战斗过渡"] * 7 + ["战斗中"])
        识别器 = SimpleNamespace(
            识别=lambda *_参数, **_关键字: SimpleNamespace(页面=next(页面序列)),
            _战斗倒计时分数=lambda _图像: 0.0,
            _红色放弃按钮分数=lambda _图像: 0.0,
        )
        停止事件 = Event()
        上下文 = SimpleNamespace(
            停止事件=停止事件,
            op=SimpleNamespace(获取屏幕图像cv=lambda *_区域: 屏幕),
            _获取点击页面识别器=lambda: 识别器,
            置脚本状态=Mock(),
        )
        with patch("任务流程.主世界打鱼.进攻.time.sleep"):
            self.assertTrue(任务.战斗是否仍在进行(上下文))
        self.assertFalse(停止事件.is_set())
        self.assertFalse(getattr(上下文, "页面恢复失败", False))

    def test_奖励页持续出现时交给既有结算等待而不立即停机(self):
        任务 = 进攻任务.__new__(进攻任务)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        识别器 = SimpleNamespace(
            识别=Mock(return_value=SimpleNamespace(页面="战斗奖励选择")),
            _战斗倒计时分数=lambda _图像: 0.0,
            _红色放弃按钮分数=lambda _图像: 0.0,
        )
        停止事件 = Event()
        日志 = []
        上下文 = SimpleNamespace(
            停止事件=停止事件,
            op=SimpleNamespace(获取屏幕图像cv=lambda *_区域: 屏幕),
            _获取点击页面识别器=lambda: 识别器,
            置脚本状态=日志.append,
        )
        with patch("任务流程.主世界打鱼.进攻.time.sleep"):
            self.assertFalse(任务.战斗是否仍在进行(上下文))
        self.assertFalse(停止事件.is_set())
        self.assertTrue(上下文._战斗奖励弹窗已确认)
        self.assertTrue(any("等待结算" in 文字 for 文字 in 日志))

    def test_战斗倒计时仍在时奖励遮罩不得放行下兵(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        识别器 = SimpleNamespace(
            _战斗倒计时分数=lambda _图像: 0.96,
            _红色放弃按钮分数=lambda _图像: 0.93,
            _奖励选择横幅分数=lambda _图像: 0.96,
        )
        self.assertFalse(进攻任务._画面有强战斗证据(识别器, 屏幕))
        识别器._奖励选择横幅分数 = lambda _图像: 0.0
        self.assertTrue(进攻任务._画面有强战斗证据(识别器, 屏幕))

    def test_长期未知画面仍安全停机并记录页面序列(self):
        任务 = 进攻任务.__new__(进攻任务)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        识别器 = SimpleNamespace(
            识别=Mock(return_value=SimpleNamespace(页面="战斗过渡")),
            _战斗倒计时分数=lambda _图像: 0.0,
            _红色放弃按钮分数=lambda _图像: 0.0,
        )
        停止事件 = Event()
        日志 = []
        上下文 = SimpleNamespace(
            停止事件=停止事件,
            op=SimpleNamespace(获取屏幕图像cv=lambda *_区域: 屏幕),
            _获取点击页面识别器=lambda: 识别器,
            置脚本状态=日志.append,
        )
        with patch("任务流程.主世界打鱼.进攻.time.sleep"):
            self.assertFalse(任务.战斗是否仍在进行(上下文))
        self.assertTrue(停止事件.is_set())
        self.assertTrue(上下文.页面恢复失败)
        self.assertTrue(any("最近=战斗过渡" in 文字 for 文字 in 日志))

    def test_识别失败不再记录为已确认战斗结束(self):
        日志 = []
        停止事件 = Event()
        上下文 = SimpleNamespace(
            停止事件=停止事件,
            页面恢复失败=True,
            置脚本状态=日志.append,
        )
        进攻任务._记录已确认战斗结束(上下文, "检测到战斗结束")
        self.assertEqual(日志, [])
        上下文.页面恢复失败 = False
        进攻任务._记录已确认战斗结束(上下文, "检测到战斗结束")
        self.assertEqual(日志, ["检测到战斗结束"])

    def test_奖励页误报后新画面确认战斗会清除残留标记(self):
        任务 = 进攻任务.__new__(进攻任务)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        识别器 = SimpleNamespace(
            识别=Mock(return_value=SimpleNamespace(页面="战斗中")),
            _战斗倒计时分数=lambda _图像: 0.0,
            _红色放弃按钮分数=lambda _图像: 0.0,
        )
        截图 = Mock(return_value=屏幕)
        日志 = []
        上下文 = SimpleNamespace(
            停止事件=Event(),
            op=SimpleNamespace(获取屏幕图像cv=截图),
            _获取点击页面识别器=lambda: 识别器,
            _战斗奖励弹窗已确认=True,
            _战斗状态缓存时间=float("inf"),
            _战斗状态缓存结果=True,
            置脚本状态=日志.append,
        )
        self.assertTrue(任务.战斗是否仍在进行(上下文))
        截图.assert_called_once()
        self.assertFalse(上下文._战斗奖励弹窗已确认)
        self.assertTrue(any("清除过渡标记" in 文字 for 文字 in 日志))

    def test_结算误报与倒计时红按钮共存时保持战斗(self):
        任务 = 进攻任务.__new__(进攻任务)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        识别器 = SimpleNamespace(
            识别=Mock(return_value=SimpleNamespace(页面="战斗结算")),
            _战斗倒计时分数=lambda _图像: 0.96,
            _红色放弃按钮分数=lambda _图像: 0.93,
        )
        上下文 = SimpleNamespace(
            停止事件=SimpleNamespace(is_set=lambda: False),
            op=SimpleNamespace(获取屏幕图像cv=lambda *_区域: 屏幕),
            _获取点击页面识别器=lambda: 识别器,
        )
        self.assertTrue(任务.战斗是否仍在进行(上下文))
        识别器.识别.assert_not_called()
        self.assertFalse(getattr(上下文, "_战斗结束已确认", False))

    def test_连续两帧真正结算才确认战斗结束(self):
        任务 = 进攻任务.__new__(进攻任务)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        识别器 = SimpleNamespace(
            识别=Mock(return_value=SimpleNamespace(页面="战斗结算")),
            _战斗倒计时分数=lambda _图像: 0.0,
            _红色放弃按钮分数=lambda _图像: 0.0,
        )
        上下文 = SimpleNamespace(
            停止事件=SimpleNamespace(is_set=lambda: False),
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕)),
            _获取点击页面识别器=lambda: 识别器,
        )
        with patch("任务流程.主世界打鱼.进攻.time.sleep"):
            self.assertFalse(任务.战斗是否仍在进行(上下文))
        self.assertTrue(上下文._战斗结束已确认)
        self.assertEqual(识别器.识别.call_count, 2)

    def test_读取槽位显示兵量能把OCR的XO识别为零(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务._识别槽位文本 = lambda _图像: "XO|12"
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: np.zeros((101, 56, 3), dtype=np.uint8),
            ),
        )
        self.assertEqual(
            任务.读取槽位显示兵量(上下文, (56, 493, 112, 594)),
            0,
        )

    def test_战斗动画粘连的超大兵量会被拒绝(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务._识别槽位文本 = lambda _图像: "X1101|9"
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: np.zeros((101, 56, 3), dtype=np.uint8),
            ),
        )
        self.assertIsNone(
            任务.读取槽位显示兵量(
                上下文,
                (56, 493, 112, 594),
                最大数量=117,
            )
        )

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

    def test_页面识别器确认零点八五分结算页(self):
        class 匹配器:
            def 执行匹配(self, _图像, _模板路径, **_参数):
                return False, (0, 0), None

        class 页面识别器:
            def 识别(self, _图像, **_参数):
                return SimpleNamespace(页面="战斗结算", 可信度=0.85)

        任务 = 进攻任务.__new__(进攻任务)
        任务.模板识别 = 匹配器()
        任务.ocr引擎 = lambda *_参数, **_关键字: ([], None)
        任务.上下文 = SimpleNamespace(
            _获取点击页面识别器=lambda: 页面识别器()
        )

        self.assertTrue(
            任务._结束画面有结果标记(np.zeros((600, 800, 3), dtype=np.uint8))
        )

    def test_下兵前会等待战斗过渡完成(self):
        任务 = 进攻任务.__new__(进攻任务)
        日志 = []
        上下文 = SimpleNamespace(
            停止事件=SimpleNamespace(
                is_set=lambda: False,
                wait=lambda timeout: None,
            ),
            识别点击画面=Mock(side_effect=[
                SimpleNamespace(页面="战斗过渡"),
                SimpleNamespace(页面="战斗中"),
            ]),
            置脚本状态=日志.append,
        )

        self.assertEqual(任务.等待战斗画面确认(上下文, 超时秒=2), "战斗中")
        self.assertTrue(any("开始下兵" in 文本 for 文本 in 日志))

    def test_侦察倒计时超过十五秒仍继续等战斗画面(self):
        任务 = 进攻任务.__new__(进攻任务)
        上下文 = SimpleNamespace(
            停止事件=SimpleNamespace(is_set=lambda: False, wait=lambda timeout: None),
            识别点击画面=Mock(side_effect=[
                SimpleNamespace(页面="选择卡片弹窗"),
                SimpleNamespace(页面="战斗过渡"),
                SimpleNamespace(页面="战斗中"),
            ]),
            置脚本状态=Mock(),
        )
        with patch(
            "任务流程.主世界打鱼.进攻.time.monotonic",
            side_effect=[0, 0, 0, 25, 25, 30],
        ):
            self.assertEqual(任务.等待战斗画面确认(上下文), "战斗中")

    def test_等待超时边界强制新帧发现结算后交给回营(self):
        任务 = 进攻任务.__new__(进攻任务)
        上下文 = SimpleNamespace(
            停止事件=SimpleNamespace(is_set=lambda: False, wait=lambda timeout: None),
            识别点击画面=Mock(side_effect=[
                SimpleNamespace(页面="战斗结算"),
            ]),
            置脚本状态=Mock(),
            _战斗结束已确认=False,
        )

        with patch(
            "任务流程.主世界打鱼.进攻.time.monotonic",
            side_effect=[0.0, 2.0],
        ):
            结果 = 任务.等待战斗画面确认(上下文, 超时秒=1)

        self.assertEqual(结果, "战斗结算")
        self.assertTrue(上下文._战斗结束已确认)
        上下文.识别点击画面.assert_called_once_with(强制=True)


if __name__ == "__main__":
    unittest.main()
