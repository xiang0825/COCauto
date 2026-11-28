import tempfile
import unittest
from pathlib import Path

from 数据库.任务数据库 import 任务数据库


class 运行时状态存储测试(unittest.TestCase):
    def setUp(self):
        self._临时目录 = tempfile.TemporaryDirectory(prefix="coc-runtime-state-")
        self.addCleanup(self._临时目录.cleanup)
        self.数据库 = 任务数据库(Path(self._临时目录.name) / "任务系统.db")

    def _状态记录数(self, 机器人标志, 状态类型):
        with self.数据库._获取连接() as conn:
            return conn.execute(
                """SELECT COUNT(*) FROM 运行时状态
                   WHERE 机器人标志 = ? AND 状态类型 = ?""",
                (机器人标志, 状态类型),
            ).fetchone()[0]

    def test_战斗摘要只更新当前快照而保留滚动学习数据(self):
        for 场次 in range(40):
            self.数据库.更新状态(
                "robot_1",
                "战斗学习",
                {"总场次": 场次 + 1, "近期": [{"场次": 场次 + 1}]},
            )
            self.数据库.更新状态(
                "robot_1",
                "战斗胜率",
                {"完成场次": 场次 + 1, "胜场": 场次 // 2},
            )

        self.assertEqual(self._状态记录数("robot_1", "战斗学习"), 1)
        self.assertEqual(self._状态记录数("robot_1", "战斗胜率"), 1)
        状态 = self.数据库.获取最新完整状态("robot_1").状态数据
        self.assertEqual(状态["战斗学习"]["总场次"], 40)
        self.assertEqual(状态["战斗学习"]["近期"], [{"场次": 40}])
        self.assertEqual(状态["战斗胜率"]["完成场次"], 40)

    def test_资源状态仍保留历史且机器人之间相互独立(self):
        self.数据库.更新状态("robot_1", "家乡资源", {"金币": 100})
        self.数据库.更新状态("robot_1", "家乡资源", {"金币": 200})
        self.数据库.更新状态("robot_2", "战斗学习", {"总场次": 1})

        self.assertEqual(self._状态记录数("robot_1", "家乡资源"), 2)
        self.assertEqual(self._状态记录数("robot_2", "战斗学习"), 1)
        self.assertEqual(
            [条目["数据"]["金币"] for 条目 in self.数据库.获取状态历史(
                "robot_1", "家乡资源", 最大条数=10
            )],
            [200, 100],
        )

    def test_已有战斗快照只覆盖最新行并保留旧历史(self):
        with self.数据库._获取连接() as conn:
            conn.executemany(
                """INSERT INTO 运行时状态
                   (机器人标志, 记录时间, 状态类型, 状态值)
                   VALUES (?, ?, ?, ?)""",
                [
                    ("robot_1", 1.0, "战斗学习", '{"总场次": 1}'),
                    ("robot_1", 2.0, "战斗学习", '{"总场次": 2}'),
                ],
            )
            conn.commit()

        self.数据库.更新状态("robot_1", "战斗学习", {"总场次": 3})

        self.assertEqual(self._状态记录数("robot_1", "战斗学习"), 2)
        self.assertEqual(
            [条目["数据"]["总场次"] for 条目 in self.数据库.获取状态历史(
                "robot_1", "战斗学习", 最大条数=10
            )],
            [3, 1],
        )

    def test_状态JSON保留中文避免unicode转义膨胀(self):
        self.数据库.更新状态("robot_1", "家乡资源", {"金币": 12345})
        with self.数据库._获取连接() as conn:
            状态值 = conn.execute(
                """SELECT 状态值 FROM 运行时状态
                   WHERE 机器人标志 = ? AND 状态类型 = ?""",
                ("robot_1", "家乡资源"),
            ).fetchone()[0]

        self.assertIn("金币", 状态值)
        self.assertNotIn("\\u91d1", 状态值)

    def test_攻城缓存与竞赛快照及常见快照状态重复写入仅保留最新一条(self):
        快照类型们 = (
            "最近确认攻城阵容",
            "竞赛原阵容快照",
            "部落竞赛检查记录",
            "日常任务记录",
            "工人状态",
        )
        for 轮次 in range(10):
            for 类型 in 快照类型们:
                self.数据库.更新状态("robot_1", 类型, {"轮次": 轮次 + 1})

        完整 = self.数据库.获取最新完整状态("robot_1").状态数据
        for 类型 in 快照类型们:
            self.assertEqual(self._状态记录数("robot_1", 类型), 1, 类型)
            self.assertEqual(完整[类型]["轮次"], 10, 类型)


if __name__ == "__main__":
    unittest.main()
