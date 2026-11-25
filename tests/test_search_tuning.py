"""搜敌与兵力调优（可配置门槛、有界自适应放宽与旧库兼容）专项单元测试。"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 应用 import 任务计划 as 计划
from 数据库.任务数据库 import 任务数据库, 机器人设置
from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务
from 任务流程.主世界打鱼.进攻 import 进攻任务
from 任务流程.主世界打鱼.进攻坐标逻辑计算 import 坐标


class 搜索调优配置兼容与校验测试(unittest.TestCase):
    新增字段 = (
        "资源易窃取最低评分",
        "资源边缘距离阈值",
        "自适应评分候选数上限",
        "自适应最低资源评分",
        "自适应最低高价值可达折算",
        "黑水优先最低黑油",
        "黑水优先前期候选数上限",
        "黑水优先放宽后最低黑油",
        "黑水优先放宽候选数上限",
        "搜索目标递减间隔次数",
        "搜索目标每次降幅比例",
        "搜索目标最低下限",
        "集中主力目标上限",
    )

    def test_调优默认值与范围钳制(self):
        默认 = 机器人设置()
        self.assertEqual(默认.资源易窃取最低评分, 5.0)
        self.assertEqual(默认.资源边缘距离阈值, 80.0)
        self.assertEqual(默认.自适应评分候选数上限, 15)
        self.assertEqual(默认.自适应最低资源评分, 6.0)
        self.assertEqual(默认.自适应最低高价值可达折算, 0.50)
        self.assertEqual(默认.黑水优先最低黑油, 11000)
        self.assertEqual(默认.黑水优先前期候选数上限, 25)
        self.assertEqual(默认.黑水优先放宽后最低黑油, 6500)
        self.assertEqual(默认.黑水优先放宽候选数上限, 55)
        self.assertEqual(默认.搜索目标递减间隔次数, 10)
        self.assertEqual(默认.搜索目标每次降幅比例, 0.10)
        self.assertEqual(默认.搜索目标最低下限, 100000)
        self.assertEqual(默认.集中主力目标上限, 2)

        越界 = 机器人设置(
            资源易窃取最低评分=99.0,
            资源边缘距离阈值=-5.0,
            自适应评分候选数上限=0,
            自适应最低资源评分=float("nan"),
            自适应最低高价值可达折算=1.5,
            黑水优先最低黑油=99999,
            黑水优先前期候选数上限=999,
            黑水优先放宽后最低黑油=-10,
            黑水优先放宽候选数上限=0,
            搜索目标递减间隔次数=0,
            搜索目标每次降幅比例=float("inf"),
            搜索目标最低下限=-100,
            集中主力目标上限=99,
        )
        self.assertEqual(越界.资源易窃取最低评分, 9.5)
        self.assertEqual(越界.资源边缘距离阈值, 20.0)
        self.assertEqual(越界.自适应评分候选数上限, 1)
        self.assertEqual(越界.自适应最低资源评分, 6.0)
        self.assertEqual(越界.自适应最低高价值可达折算, 0.95)
        self.assertEqual(越界.黑水优先最低黑油, 30000)
        self.assertEqual(越界.黑水优先前期候选数上限, 150)
        self.assertEqual(越界.黑水优先放宽后最低黑油, 0)
        self.assertEqual(越界.黑水优先放宽候选数上限, 1)
        self.assertEqual(越界.搜索目标递减间隔次数, 1)
        self.assertEqual(越界.搜索目标每次降幅比例, 0.10)
        self.assertEqual(越界.搜索目标最低下限, 0)
        self.assertEqual(越界.集中主力目标上限, 6)

    def test_旧数据库缺少新增调优字段时可平滑迁移并回写(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            数据库路径 = str(Path(临时目录) / "任务系统.db")
            数据库 = 任务数据库(数据库路径)
            数据库.保存机器人设置("robot_legacy", 机器人设置(欲进攻的最小资源=1400000))
            连接 = sqlite3.connect(数据库路径)
            try:
                旧数据 = json.loads(
                    连接.execute(
                        "SELECT 设置JSON FROM 机器人设置 WHERE 机器人标志=?",
                        ("robot_legacy",),
                    ).fetchone()[0]
                )
                for 字段名 in self.新增字段:
                    旧数据.pop(字段名, None)
                连接.execute(
                    "UPDATE 机器人设置 SET 设置JSON=? WHERE 机器人标志=?",
                    (json.dumps(旧数据), "robot_legacy"),
                )
                连接.commit()
            finally:
                连接.close()

            加载旧设置 = 数据库.获取机器人设置("robot_legacy")
            self.assertEqual(加载旧设置.欲进攻的最小资源, 1400000)
            self.assertEqual(加载旧设置.自适应最低高价值可达折算, 0.50)
            self.assertEqual(加载旧设置.黑水优先最低黑油, 11000)
            self.assertEqual(加载旧设置.集中主力目标上限, 2)

            加载旧设置.自适应评分候选数上限 = 12
            加载旧设置.黑水优先最低黑油 = 10500
            数据库.保存机器人设置("robot_legacy", 加载旧设置)
            再加载 = 数据库.获取机器人设置("robot_legacy")
            self.assertEqual(再加载.自适应评分候选数上限, 12)
            self.assertEqual(再加载.黑水优先最低黑油, 10500)

    def test_任务计划表单校验新搜敌与集中参数(self):
        已知字段 = set(机器人设置.__dataclass_fields__)
        for 字段 in 计划.所有参数字段():
            self.assertIn(字段.字段, 已知字段)

        设置 = 机器人设置()
        计划.应用参数(
            设置,
            "main_resource",
            {
                "资源易窃取最低评分": "5.5",
                "自适应评分候选数上限": "18",
                "自适应最低高价值可达折算": "0.45",
                "黑水优先最低黑油": "12000",
                "搜索目标递减间隔次数": "8",
                "搜索目标每次降幅比例": "0.15",
            },
        )
        self.assertEqual(设置.资源易窃取最低评分, 5.5)
        self.assertEqual(设置.自适应评分候选数上限, 18)
        self.assertEqual(设置.自适应最低高价值可达折算, 0.45)
        self.assertEqual(设置.黑水优先最低黑油, 12000)
        self.assertEqual(设置.搜索目标递减间隔次数, 8)
        self.assertEqual(设置.搜索目标每次降幅比例, 0.15)

        计划.应用参数(设置, "combat_options", {"集中主力目标上限": "3"})
        self.assertEqual(设置.集中主力目标上限, 3)

        for 非法提交 in (
            {"自适应最低高价值可达折算": "nan"},
            {"自适应最低高价值可达折算": "1.2"},
            {"黑水优先最低黑油": "40000"},
            {"搜索目标每次降幅比例": "0.8"},
        ):
            with self.assertRaises(ValueError):
                计划.应用参数(设置, "main_resource", 非法提交)


class 搜索调优策略逻辑测试(unittest.TestCase):
    @staticmethod
    def _低表现数据库(设置=None):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(
                    状态数据={
                        "战斗学习": {
                            "近期": [
                                {"结果": "失败", "星数": 0, "摧毁率": 24},
                                {"结果": "失败", "星数": 0, "摧毁率": 33},
                            ],
                            "下一场建议": "提高目标可达评分",
                        }
                    }
                )

            def 获取机器人设置(self, _标志):
                return 设置

        return 数据库()

    def test_自适应门槛超候选上限后同时放宽评分和可达率(self):
        设置 = 机器人设置()
        上下文 = SimpleNamespace(
            数据库=self._低表现数据库(设置),
            设置=设置,
            机器人标志="robot_1",
        )
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)

        评分1, 可达1, 说明1 = 任务.获取自适应资源筛选门槛(上下文, 1)
        评分15, 可达15, _ = 任务.获取自适应资源筛选门槛(上下文, 15)
        评分16, 可达16, 说明16 = 任务.获取自适应资源筛选门槛(上下文, 16)

        self.assertEqual((评分1, 可达1), (6.0, 0.50))
        self.assertEqual((评分15, 可达15), (6.0, 0.50))
        self.assertIn("前15个候选", 说明1)
        self.assertEqual(评分16, 5.0)
        self.assertIsNone(可达16)
        self.assertIn("放宽回基础门槛", 说明16)

    def test_自适应可达门槛可自定义或设为零禁用(self):
        自定义 = 机器人设置(
            资源易窃取最低评分=5.5,
            自适应评分候选数上限=5,
            自适应最低资源评分=7.2,
            自适应最低高价值可达折算=0.0,
        )
        上下文 = SimpleNamespace(
            数据库=self._低表现数据库(自定义),
            设置=自定义,
            机器人标志="robot_1",
        )
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)

        评分5, 可达5, _ = 任务.获取自适应资源筛选门槛(上下文, 5)
        评分6, 可达6, _ = 任务.获取自适应资源筛选门槛(上下文, 6)

        self.assertEqual(评分5, 7.2)
        self.assertIsNone(可达5)
        self.assertEqual(评分6, 5.5)
        self.assertIsNone(可达6)

    def test_黑水优先三阶段门槛支持配置化(self):
        默认获取 = 搜索目标敌人任务.获取黑水优先最低候选黑油
        self.assertEqual(默认获取("黑水", 1), 11000)
        self.assertEqual(默认获取("黑水", 25), 11000)
        self.assertEqual(默认获取("黑水", 26), 6500)
        self.assertEqual(默认获取("黑水", 55), 6500)
        self.assertEqual(默认获取("黑水", 56), 0)

        自定义设置 = 机器人设置(
            黑水优先最低黑油=13000,
            黑水优先前期候选数上限=12,
            黑水优先放宽后最低黑油=7500,
            黑水优先放宽候选数上限=30,
        )
        self.assertEqual(默认获取("黑水", 12, 设置=自定义设置), 13000)
        self.assertEqual(默认获取("黑水", 13, 设置=自定义设置), 7500)
        self.assertEqual(默认获取("黑水", 30, 设置=自定义设置), 7500)
        self.assertEqual(默认获取("黑水", 31, 设置=自定义设置), 0)

    def test_搜索目标递减参数可配置且不抬高更低的原始目标(self):
        日志 = []
        设置 = 机器人设置(
            欲进攻的最小资源=1_000_000,
            搜索目标递减间隔次数=8,
            搜索目标每次降幅比例=0.15,
            搜索目标最低下限=250_000,
        )
        上下文 = SimpleNamespace(
            设置=设置,
            数据库=SimpleNamespace(获取机器人设置=Mock(return_value=设置)),
            机器人标志="robot_1",
            置脚本状态=lambda 文本, **_kw: 日志.append(文本),
        )
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)

        self.assertEqual(任务.调整搜索目标(上下文, 1_000_000, 8), 850_000)
        self.assertEqual(任务.调整搜索目标(上下文, 1_000_000, 16), 700_000)
        self.assertEqual(任务.调整搜索目标(上下文, 1_000_000, 80), 250_000)
        # 原始目标低于配置的最低下限时，不能反向抬高目标
        self.assertEqual(任务.调整搜索目标(上下文, 50_000, 80), 50_000)

    def test_自定义易窃取评分与边缘距离门槛在单次搜索生效(self):
        设置 = 机器人设置(
            欲进攻的最小资源=500_000,
            战利品优先级="均衡",
            欲进攻资源建筑靠近地图边缘最小比例=0.5,
            资源易窃取最低评分=6.0,
            资源边缘距离阈值=110.0,
        )
        日志 = []
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            设置=设置,
            数据库=SimpleNamespace(获取机器人设置=Mock(return_value=设置)),
            机器人标志="robot_1",
            置脚本状态=lambda 文本, **_kw: 日志.append(文本),
        )
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.上下文 = 上下文
        任务.等待下一个按钮出现 = Mock(return_value=True)
        任务.识别当前资源 = Mock(return_value={
            "金币": 800_000,
            "圣水": 800_000,
            "黑油": 5_000,
            "战利品评分": 1_700_000,
        })
        任务.检测器 = SimpleNamespace(检测=Mock(return_value=[]))
        任务.计算资源易窃取评分 = Mock(return_value=(5.8, {"资源建筑数": 4}))
        任务.打印状态信息 = Mock()
        任务.获取自适应资源筛选门槛 = Mock(return_value=(6.0, None, ""))
        任务.点击下一个按钮 = Mock(return_value=True)

        结果 = 任务.执行单次搜索(上下文, 搜索次数=1, 最小资源=500_000)
        self.assertFalse(结果)
        任务.计算资源易窃取评分.assert_called_once_with(
            [],
            边缘距离阈值=110.0,
            最低评分=6.0,
        )
        任务.点击下一个按钮.assert_called_once_with(上下文)
        self.assertTrue(any("未超过6.0分" in 项 for 项 in 日志))

    def test_安全护栏在调优后依然严格拦截异常与上限(self):
        设置 = 机器人设置(
            最大搜索次数=2,
            最长搜索分钟=15,
            YOLO连续失败熔断次数=2,
            搜索目标递减间隔次数=1,
            搜索目标每次降幅比例=0.20,
            搜索目标最低下限=100_000,
        )
        日志 = []
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            设置=设置,
            数据库=SimpleNamespace(获取机器人设置=Mock(return_value=设置)),
            机器人标志="robot_guard",
            停止事件=threading.Event(),
            页面恢复失败=False,
            置脚本状态=lambda 文本, **_kw: 日志.append(文本),
            脚本延时=Mock(),
            发送企业微信通知=Mock(),
            发送桌面通知=Mock(),
        )
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.上下文 = 上下文
        任务._连续YOLO失败次数 = 0
        任务._搜索熔断原因 = ""
        任务.等待下一个按钮出现 = Mock(return_value=True)
        任务.识别当前资源 = Mock(return_value={"资源识别异常": True})
        任务.点击下一个按钮 = Mock(return_value=True)

        成功 = 任务.执行()
        self.assertFalse(成功)
        self.assertTrue(上下文.页面恢复失败)
        self.assertEqual(任务.点击下一个按钮.call_count, 2)
        self.assertTrue(any("已达最大搜索次数上限（2次）" in 项 for 项 in 日志))

    def test_集中主力目标上限可按配置调整(self):
        目标列表 = [
            {"类别名称": "金库", "置信度": 0.95, "中心坐标": 坐标(155, 205), "靠近边缘": True},
            {"类别名称": "圣水瓶", "置信度": 0.95, "中心坐标": 坐标(190, 230), "靠近边缘": True},
            {"类别名称": "金矿", "置信度": 0.95, "中心坐标": 坐标(170, 215), "靠近边缘": True},
            {"类别名称": "圣水采集器", "置信度": 0.95, "中心坐标": 坐标(625, 375), "靠近边缘": True},
        ]
        for 自动配兵, 玩法 in ((False, "资源优先"), (True, "稳健三星")):
            with self.subTest(自动配兵=自动配兵, 玩法=玩法):
                设置 = 机器人设置(
                    是否自动配兵=自动配兵,
                    自动配兵玩法=玩法,
                    战利品优先级="均衡",
                    集中主力目标上限=3,
                )
                上下文 = SimpleNamespace(
                    设置=设置,
                    数据库=SimpleNamespace(获取机器人设置=Mock(return_value=设置)),
                    机器人标志="robot_1",
                    置脚本状态=Mock(),
                )
                任务 = 进攻任务.__new__(进攻任务)
                任务.读取自适应进攻策略 = lambda _上下文: "集中主力"

                结果 = 任务.选择集中进攻目标(上下文, 目标列表)
                self.assertEqual(len(结果), 3)
                self.assertIn("集中主力", 上下文.本场进攻策略)


if __name__ == "__main__":
    unittest.main()
