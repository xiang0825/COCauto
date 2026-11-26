"""脚本停止/启动清空任务日志后，今日战报和今日数据不能清零；跨日重置。"""
import sqlite3
from contextlib import closing
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from 应用.战报服务 import 战报服务
from 数据库 import 今日统计
from 数据库.任务数据库 import 任务数据库
from 数据库.日志统计归档 import 合并归档, 是统计相关, 状态类型
from 数据库.日志轮转 import 停止后导出并清空, 导出并清空任务日志


def 今天时刻(小时: int, 分: int = 0) -> float:
    今天 = datetime.now().replace(hour=小时, minute=分, second=0, microsecond=0)
    return 今天.timestamp()


class 日志统计归档测试(unittest.TestCase):
    def setUp(self):
        self._目录 = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.路径 = Path(self._目录.name) / "任务系统.db"
        self.数据库 = 任务数据库(str(self.路径))
        self.基准 = 今天时刻(12)

    def tearDown(self):
        self._目录.cleanup()

    def _写(self, 时间戳, 内容, 标志="robot_1"):
        with closing(sqlite3.connect(str(self.路径))) as 连接, 连接:
            连接.execute(
                "INSERT INTO 任务日志 (机器人标志, 日志内容, 记录时间, 下次超时) VALUES (?, ?, ?, 0)",
                (标志, 内容, 时间戳),
            )

    def _一场(self, t, 结果="胜利", 金币=500000):
        self._写(t - 30, "搜索次数[1] 金币[100000]")
        self._写(t - 20, "搜索次数[4] 金币[800000]")
        self._写(t - 10, "成功找到敌人")
        self._写(t - 5, "下兵中")  # 与统计无关，不归档
        self._写(t, f"战斗结果：{结果}；星数：2；摧毁率：72%；当前胜率：100.0%")
        self._写(t + 5, f"本场资源净变化：金币 +{金币}，圣水 +400000，黑油 +4500")

    def _战报(self, 现在=None):
        return 战报服务(str(self.路径)).生成战报("robot_1", 当前时间=现在 or self.基准)

    def _日志条数(self):
        with closing(sqlite3.connect(str(self.路径))) as 连接, 连接:
            return 连接.execute("SELECT COUNT(*) FROM 任务日志").fetchone()[0]

    def test_停止清空后今日战报不变(self):
        self._一场(今天时刻(9))
        self._一场(今天时刻(10), 结果="失败", 金币=120000)
        之前 = self._战报().今日.to_dict()
        self.assertEqual(之前["总场次"], 2)
        self.assertGreater(停止后导出并清空(self.路径), 0)
        self.assertEqual(self._日志条数(), 0)
        self.assertEqual(self._战报().今日.to_dict(), 之前)

    def test_一天多次停止累计而不是只留最后一份备份(self):
        self._一场(今天时刻(8))
        停止后导出并清空(self.路径)
        self._一场(今天时刻(9))
        停止后导出并清空(self.路径)
        self._一场(今天时刻(10))  # 本次会话还在表里
        今日 = self._战报().今日
        self.assertEqual(今日.总场次, 3)
        self.assertEqual(今日.总掠夺金币, 1_500_000)
        self.assertEqual(今日.搜敌样本数, 3)

    def test_归档与表内或备份重叠不重复计数(self):
        self._一场(今天时刻(9))
        with closing(sqlite3.connect(str(self.路径))) as 连接, 连接:
            from 数据库.日志统计归档 import 归档待清空日志
            归档待清空日志(连接, 10**9)  # 只归档不清空：同一行同时在表和归档里
        self.assertEqual(self._战报().今日.总场次, 1)

    def test_只归档统计相关行(self):
        self.assertTrue(是统计相关("战斗结果：胜利；星数：3"))
        self.assertTrue(是统计相关("部落竞赛：个人积分 6200/10000"))
        self.assertTrue(是统计相关("部落竞赛：已接任务：拆毁建筑（150分）"))
        self.assertFalse(是统计相关("部落竞赛：点击活动按钮 (196, 556)"))
        self.assertFalse(是统计相关("下兵中"))

    def test_跨日重置_昨天进昨日今天从零开始(self):
        昨天 = self.基准 - 86400
        self._一场(昨天)
        停止后导出并清空(self.路径)
        战报 = self._战报()
        self.assertEqual(战报.今日.总场次, 0)
        self.assertEqual(战报.昨日.总场次, 1)
        # 再过两天：更早的日期从归档里丢掉，不会无限增长
        归档 = 合并归档({"2000-01-01": [[1.0, "战斗结果：胜利"]]}, [], 现在=self.基准)
        self.assertNotIn("2000-01-01", 归档)
        # 两天后：旧归档行不在今日/昨日范围内，读取时自然不计入。
        两天后 = self.基准 + 2 * 86400
        self.assertEqual(self._战报(两天后).今日.总场次, 0)
        self.assertEqual(self._战报(两天后).昨日.总场次, 0)

    def test_顶栏今日数据不受清空影响(self):
        今日统计.记录战斗(self.数据库, "robot_1", "胜利", 3, 现在=self.基准)
        今日统计.记录收益(self.数据库, "robot_1", {"金币": 1000, "圣水": 2000, "黑油": 30}, 现在=self.基准)
        self._一场(今天时刻(9))
        停止后导出并清空(self.路径)
        今日 = 今日统计.读取今日(self.数据库, "robot_1", 现在=self.基准)
        self.assertEqual((今日.场次, 今日.胜, 今日.金币), (1, 1, 1000))
        # 跨日：今日统计按日期键，第二天从零开始
        明天 = 今日统计.读取今日(self.数据库, "robot_1", 现在=self.基准 + 86400)
        self.assertEqual(明天.场次, 0)

    def test_归档失败时不清空日志(self):
        self._一场(今天时刻(9))
        with patch("数据库.日志统计归档.归档待清空日志", side_effect=RuntimeError("坏了")):
            with self.assertRaises(RuntimeError):
                导出并清空任务日志(self.路径)
        self.assertEqual(self._日志条数(), 6)
        self.assertEqual(self._战报().今日.总场次, 1)

    def test_归档只保留最新一行快照(self):
        self._一场(今天时刻(8))
        停止后导出并清空(self.路径)
        self._一场(今天时刻(9))
        停止后导出并清空(self.路径)
        with closing(sqlite3.connect(str(self.路径))) as 连接, 连接:
            行数 = 连接.execute(
                "SELECT COUNT(*) FROM 运行时状态 WHERE 状态类型 = ?", (状态类型,)
            ).fetchone()[0]
        self.assertEqual(行数, 1)


if __name__ == "__main__":
    unittest.main()
