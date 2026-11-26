"""今日统计：按自然日累计战斗与收益，界面数据条的数据来源。"""
import os
import tempfile
import time
import unittest

from 数据库 import 今日统计
from 数据库.任务数据库 import 任务数据库


def _时间(日期: str, 时分: str = "12:00") -> float:
    return time.mktime(time.strptime(f"{日期} {时分}", "%Y-%m-%d %H:%M"))


class 今日统计测试(unittest.TestCase):
    def setUp(self):
        self.库 = 任务数据库(os.path.join(tempfile.mkdtemp(), "t.db"))

    def test_按日累计场次胜率星数(self):
        现在 = _时间("2026-11-25")
        for 结果, 星数 in (("胜利", 2), ("胜利", 3), ("失败", 0), ("未识别", None)):
            self.assertTrue(今日统计.记录战斗(self.库, "robot_1", 结果, 星数, 现在))
        今日 = 今日统计.读取今日(self.库, "robot_1", 现在)
        self.assertEqual((今日.场次, 今日.胜, 今日.负), (4, 2, 1))
        self.assertEqual(今日.胜率, 67)
        self.assertEqual(今日.平均星数, 1.7)

    def test_跨天从零开始且只保留七天(self):
        for 天 in range(1, 10):
            今日统计.记录战斗(self.库, "robot_1", "胜利", 1, _时间(f"2026-11-{天:02d}"))
        self.assertEqual(今日统计.读取今日(self.库, "robot_1", _时间("2026-11-10")).场次, 0)
        self.assertEqual(今日统计.读取今日(self.库, "robot_1", _时间("2026-11-09")).场次, 1)
        self.assertEqual(len(今日统计.读取全部(self.库, "robot_1")["按日"]), 今日统计.保留天数)

    def test_收益累加且可疑读数不计入(self):
        现在 = _时间("2026-11-25")
        self.assertTrue(今日统计.记录收益(self.库, "robot_1", {"金币": 500_000, "圣水": 400_000, "黑油": 2000}, 现在))
        self.assertTrue(今日统计.记录收益(self.库, "robot_1", {"金币": -5000, "圣水": 300_000, "黑油": 0}, 现在))
        # 黑油 70,303 被读成 157 → 大幅负值；金币多读一位 → 超过单场上限。两者都不计入。
        self.assertFalse(今日统计.记录收益(self.库, "robot_1", {"金币": 1, "圣水": 1, "黑油": -70_146}, 现在))
        self.assertFalse(今日统计.记录收益(self.库, "robot_1", {"金币": 30_000_000, "圣水": 0, "黑油": 0}, 现在))
        今日 = 今日统计.读取今日(self.库, "robot_1", 现在)
        self.assertEqual((今日.金币, 今日.圣水, 今日.黑油, 今日.收益场次), (495_000, 700_000, 2000, 2))

    def test_只保留最新快照不堆积历史行(self):
        现在 = _时间("2026-11-25")
        for _ in range(20):
            今日统计.记录战斗(self.库, "robot_1", "胜利", 1, 现在)
        with self.库._获取连接() as conn:
            行数 = conn.execute(
                "SELECT COUNT(*) FROM 运行时状态 WHERE 状态类型 = ?", (今日统计.状态类型,),
            ).fetchone()[0]
        self.assertEqual(行数, 1)

    def test_数据库异常不影响调用方(self):
        class 坏库:
            def _获取连接(self):
                raise OSError("磁盘满")

            def 更新状态(self, *参数):
                raise OSError("磁盘满")

        self.assertFalse(今日统计.记录战斗(坏库(), "robot_1", "胜利", 1))
        self.assertEqual(今日统计.读取今日(坏库(), "robot_1").场次, 0)
        self.assertEqual(今日统计.读取部落竞赛(坏库(), "robot_1"), {})

    def test_数量格式(self):
        self.assertEqual(今日统计.格式化数量(4_200_000), "+4.2M")
        self.assertEqual(今日统计.格式化数量(21_000), "+21k")
        self.assertEqual(今日统计.格式化数量(3000), "+3.0k")
        self.assertEqual(今日统计.格式化数量(-5000), "-5.0k")
        self.assertEqual(今日统计.格式化数量(0), "0")


class 主界面参数分层测试(unittest.TestCase):
    def test_每个参数都在主界面或高级设置里(self):
        from 应用 import 任务计划 as 计划
        主 = {字段.字段 for 页 in 计划.主界面参数表.values() for 字段 in 页.字段}
        高 = {字段.字段 for 页 in 计划.高级参数表.values() for 字段 in 页.字段}
        全部 = {字段.字段 for 字段 in 计划.所有参数字段()}
        self.assertEqual(全部 - 主 - 高, set())
        self.assertEqual(set(计划.主界面参数表), {行.键 for 行 in 计划.任务行列表(计划.机器人设置())})

    def test_数据库里可调的设置都有界面入口(self):
        """机器人设置新增可见字段时必须放进主界面或高级设置（rc149 起漏过几次）。"""
        from dataclasses import fields

        from 应用 import 任务计划 as 计划
        from 数据库.任务数据库 import 机器人设置

        已覆盖 = {字段.字段 for 表 in (计划.主界面参数表, 计划.高级参数表) for 页 in 表.values() for 字段 in 页.字段}
        # 服务器在常规页单独的下拉框；任务开关在任务列表；战斗结果统计强制启用。
        另有入口 = {"服务器", "开启刷墙", "是否刷主世界", "是否刷夜世界", "是否升级建议升级的建筑",
                  "是否部落竞赛接任务", "是否试战统计胜率"}
        缺少 = {
            字段.name for 字段 in fields(机器人设置)
            if 字段.metadata.get("UI类型") != "hidden" and 字段.name not in 已覆盖 | 另有入口
        }
        self.assertEqual(缺少, set())
        self.assertIn("内存保护提交额度阈值MB", {字段.字段 for 字段 in 计划.高级参数表["adv_general"].字段})

    def test_主界面每个任务最多六个常用参数(self):
        from 应用 import 任务计划 as 计划
        for 键, 页 in 计划.主界面参数表.items():
            self.assertLessEqual(len(页.字段), 6, 键)
            if 键 != "event":  # 白名单是部落竞赛唯一的核心参数，其余宽控件都在高级设置
                self.assertNotIn("multi", {字段.类型 for 字段 in 页.字段}, 键)


if __name__ == "__main__":
    unittest.main()
