import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from 数据库.任务数据库 import 任务数据库, 机器人设置


class 机器人设置兼容测试(unittest.TestCase):
    def test_旧版是否刷墙字段可以迁移(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            数据库路径 = str(Path(临时目录) / "任务系统.db")
            数据库 = 任务数据库(数据库路径)
            原始 = 机器人设置(开启刷墙=False).__dict__.copy()
            原始.pop("开启刷墙", None)
            原始["是否刷墙"] = True
            数据库.保存机器人设置("robot_1", 机器人设置())
            连接 = sqlite3.connect(数据库路径)
            try:
                连接.execute(
                    "UPDATE 机器人设置 SET 设置JSON=? WHERE 机器人标志=?",
                    (json.dumps(原始), "robot_1"),
                )
                连接.commit()
            finally:
                连接.close()

            设置 = 数据库.获取机器人设置("robot_1")

            self.assertTrue(设置.开启刷墙)

    def test_保存时丢弃动态临时字段避免下次启动构造失败(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            数据库 = 任务数据库(str(Path(临时目录) / "任务系统.db"))
            设置 = 机器人设置(开启刷墙=False)
            设置.是否刷墙 = True
            设置.维护临时标记 = "test-only"
            数据库.保存机器人设置("robot_1", 设置)

            重新加载 = 数据库.获取机器人设置("robot_1")
            self.assertTrue(重新加载.开启刷墙)
            self.assertFalse(hasattr(重新加载, "维护临时标记"))

            连接 = sqlite3.connect(数据库.文件路径)
            try:
                原始JSON = 连接.execute(
                    "SELECT 设置JSON FROM 机器人设置 WHERE 机器人标志=?",
                    ("robot_1",),
                ).fetchone()[0]
            finally:
                连接.close()
            保存内容 = json.loads(原始JSON)
            self.assertNotIn("是否刷墙", 保存内容)
            self.assertNotIn("维护临时标记", 保存内容)
            self.assertIn("开启刷墙", 保存内容)


if __name__ == "__main__":
    unittest.main()
