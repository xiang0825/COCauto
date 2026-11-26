"""A. 夜世界打满星星奖励（night_star_bonus）：计数、上限、跨日、页面护栏与回放。"""
import pathlib
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.日常 import 日常公共
from 任务流程.日常.夜世界星星 import 夜世界星星任务, 奖励日, 距下次重置秒, 默认参数, 读取参数
from 数据库.任务数据库 import 任务计划定义映射, 机器人设置

根目录 = pathlib.Path(__file__).resolve().parents[1]


class 假数据库:
    def __init__(self):
        self.状态 = {}

    def 获取最新完整状态(self, 标志):
        return SimpleNamespace(状态数据=dict(self.状态))

    def 更新状态(self, 标志, 类型, 数据):
        self.状态[类型] = 数据


def 构造(页面序列=("夜世界主页",), 每场奖励=(0,), 战斗成功=True, 参数=None, **设置项):
    页面 = list(页面序列)
    上下文 = SimpleNamespace(
        机器人标志="t", 数据库=假数据库(), 设置=机器人设置(**设置项),
        置脚本状态=Mock(), 脚本延时=Mock(), 请求任务计划等待=Mock(),
        _夜世界星级奖励确认次数=0, 处理战斗星级奖励弹窗=Mock(),
    )

    def 识别(强制=False):
        当前 = 页面.pop(0) if len(页面) > 1 else 页面[0]
        return SimpleNamespace(页面=当前)

    上下文.识别点击画面 = 识别
    奖励 = list(每场奖励)
    场次 = {"n": 0}

    class 假打鱼:
        def __init__(self, 上下文_):
            pass

        def 执行(self):
            增量 = 奖励[min(场次["n"], len(奖励) - 1)]
            场次["n"] += 1
            上下文._夜世界星级奖励确认次数 += 增量
            return 战斗成功

    任务 = 夜世界星星任务.__new__(夜世界星星任务)
    任务.上下文, 任务.数据库, 任务.机器人标志 = 上下文, 上下文.数据库, "t"
    任务.参数 = dict(参数 or 默认参数)
    任务.重置小时 = int(任务.参数.get("每日重置本地小时", 0))
    任务.夜世界打鱼任务类 = 假打鱼
    return 任务, 上下文, 场次


class 计数测试(unittest.TestCase):
    def test_确认到星级奖励后完成(self):
        任务, 上下文, 场次 = 构造(每场奖励=(0, 0, 1))
        结果 = [任务.打一场() for _ in range(3)]
        self.assertEqual(结果, ["继续", "继续", "完成"])
        self.assertTrue(任务.读取今日记录()["已领满"])
        self.assertTrue(任务.今日已完成())
        self.assertEqual(任务.打一场(), "完成")
        self.assertEqual(场次["n"], 3)

    def test_每日奖励次数可配置(self):
        任务, _, _ = 构造(每场奖励=(1,), 夜世界每日星级奖励次数=2)
        self.assertEqual(任务.打一场(), "继续")
        self.assertEqual(任务.打一场(), "完成")

    def test_达到每日最多场次即停(self):
        任务, _, 场次 = 构造(每场奖励=(0,), 夜世界星星每日最多场次=2)
        self.assertEqual([任务.打一场(), 任务.打一场(), 任务.打一场()], ["继续", "完成", "完成"])
        self.assertEqual(场次["n"], 2)
        self.assertTrue(任务.今日已完成())

    def test_战斗未完成返回失败但仍记场次(self):
        任务, _, _ = 构造(战斗成功=False)
        self.assertEqual(任务.打一场(), "失败")
        self.assertEqual(任务.读取今日记录()["场次"], 1)

    def test_跨日重置(self):
        任务, 上下文, _ = 构造()
        日常公共.写入任务记录(上下文.数据库, "t", "night_star_bonus",
                       {"日期": "2000-01-01", "场次": 9, "星级奖励": 1, "已领满": True})
        self.assertFalse(任务.今日已完成())
        self.assertEqual(任务.读取今日记录()["场次"], 0)


class 页面护栏测试(unittest.TestCase):
    def test_不在夜世界主页时不点进攻(self):
        任务, 上下文, 场次 = 构造(页面序列=("主世界主页",))
        self.assertEqual(任务.打一场(), "失败")
        self.assertEqual(场次["n"], 0)

    def test_星级奖励弹窗先处理再进攻(self):
        任务, 上下文, 场次 = 构造(页面序列=("战斗星级奖励", "夜世界主页"))
        self.assertEqual(任务.打一场(), "继续")
        上下文.处理战斗星级奖励弹窗.assert_called()
        self.assertEqual(场次["n"], 1)

    def test_未校准不做主页OCR(self):
        任务, _, _ = 构造()
        任务.执行OCR识别 = Mock(side_effect=AssertionError("未校准不应 OCR"))
        self.assertFalse(任务.主页显示已领满())

    def test_校准后主页OCR命中关键词即完成(self):
        参数 = dict(默认参数, calibrated=True)
        任务, _, 场次 = 构造(参数=参数)
        任务.执行OCR识别 = Mock(return_value=[([[0, 0], [9, 0], [9, 9], [0, 9]], "明天再来", 0.9)])
        self.assertEqual(任务.打一场(), "完成")
        self.assertEqual(场次["n"], 0)


class 时间测试(unittest.TestCase):
    def test_重置小时前算前一天(self):
        早上 = datetime(2026, 11, 26, 7, 30).timestamp()
        self.assertEqual(奖励日(早上, 8), "2026-11-25")
        self.assertEqual(奖励日(早上, 0), "2026-11-26")

    def test_距下次重置(self):
        时刻 = datetime(2026, 11, 26, 23, 0).timestamp()
        self.assertAlmostEqual(距下次重置秒(时刻, 0), 3600, delta=1)
        self.assertAlmostEqual(距下次重置秒(时刻, 23), 86400, delta=1)


class 注册测试(unittest.TestCase):
    def test_默认关闭已注册且资源JSON未校准(self):
        self.assertFalse(机器人设置().是否夜世界星星奖励)
        self.assertIn("night_star_bonus", 任务计划定义映射)
        参数 = 读取参数()
        self.assertFalse(日常公共.已校准(参数))
        self.assertEqual(len(参数["主页星级OCR区域"]), 4)

    def test_设置夹取(self):
        设置 = 机器人设置(夜世界每日星级奖励次数=99, 夜世界星星每日最多场次=0)
        self.assertEqual(设置.夜世界每日星级奖励次数, 5)
        self.assertEqual(设置.夜世界星星每日最多场次, 1)


class 回放测试(unittest.TestCase):
    """用真实主世界主页截图回放：页面识别不是夜世界主页 → 绝不点进攻。"""

    def test_主世界主页截图不会被当成夜世界主页(self):
        from 模块.检测.模板匹配器 import 模板匹配引擎
        from 模块.检测.页面识别器 import 页面识别器

        图 = cv2.imdecode(np.fromfile(str(根目录 / "tests/fixtures/coc_home_18_647_5.png"), dtype=np.uint8), cv2.IMREAD_COLOR)
        识别器 = 页面识别器(模板匹配引擎(图片库路径=根目录 / "img"))
        任务, 上下文, 场次 = 构造()
        上下文.识别点击画面 = lambda 强制=False: 识别器.识别(图)
        self.assertEqual(任务.打一场(), "失败")
        self.assertEqual(场次["n"], 0)


class 星级奖励计数钩子测试(unittest.TestCase):
    def test_确认弹窗后计数加一(self):
        from 任务流程.基础任务框架 import 任务上下文

        上下文 = 任务上下文.__new__(任务上下文)
        上下文._内存保护已触发 = False
        上下文._最近战后奖励按钮候选 = None
        上下文._战斗中 = False
        识别器 = SimpleNamespace(
            识别=lambda 图, 战斗中=False: SimpleNamespace(页面="战斗星级奖励"),
            定位战斗星级奖励确定按钮=lambda 图: (400, 510),
        )
        上下文._获取点击页面识别器 = lambda: 识别器
        上下文._获取点击识别截图 = lambda 强制=False: object()
        上下文.点击已确认安全按钮 = Mock(return_value=True)
        上下文.清除战斗结算保护状态 = Mock()
        上下文.置脚本状态 = Mock()
        self.assertTrue(上下文.处理战斗星级奖励弹窗())
        self.assertTrue(上下文.处理战斗星级奖励弹窗())
        self.assertEqual(上下文._夜世界星级奖励确认次数, 2)


if __name__ == "__main__":
    unittest.main()
