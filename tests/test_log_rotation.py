"""启动/退出日志轮转：导出上一份、清空任务日志、只保留一份备份、不碰其他表。"""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from 数据库.任务数据库 import 任务数据库
from 数据库.日志轮转 import 会话日志轮转, 导出并清空任务日志, 压缩数据库一次, 轮转错误日志


class 日志轮转测试(unittest.TestCase):
    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="coc-logrot-"))
        self.路径 = self.目录 / "任务系统.db"
        self.库 = 任务数据库(str(self.路径))
        for 序 in range(3):
            self.库.记录日志("robot_1", f"第{序}条", 0)
        self.库.更新状态("robot_1", "战斗胜率", {"场次": 5})

    def _计数(self, 表):
        连接 = sqlite3.connect(self.路径)
        try:
            return 连接.execute(f"SELECT COUNT(*) FROM {表}").fetchone()[0]
        finally:
            连接.close()

    def test_导出后清空且其他表不动(self):
        设置数 = self._计数("机器人设置")
        状态数 = self._计数("运行时状态")
        self.assertEqual(导出并清空任务日志(self.路径), 3)
        self.assertEqual(self._计数("任务日志"), 0)
        self.assertEqual(self._计数("运行时状态"), 状态数)
        self.assertEqual(self._计数("机器人设置"), 设置数)
        行 = [json.loads(x) for x in (self.目录 / "上次日志.bak.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["内容"] for r in 行], ["第0条", "第1条", "第2条"])
        self.assertEqual(行[0]["机器人"], "robot_1")

    def test_空表时保留上一份备份(self):
        导出并清空任务日志(self.路径)
        备份 = self.目录 / "上次日志.bak.jsonl"
        原文 = 备份.read_text(encoding="utf-8")
        self.assertEqual(导出并清空任务日志(self.路径), 0)
        self.assertEqual(备份.read_text(encoding="utf-8"), 原文)

    def test_新会话覆盖旧备份只留一份(self):
        导出并清空任务日志(self.路径)
        self.库.记录日志("robot_1", "新会话", 0)
        self.assertEqual(导出并清空任务日志(self.路径), 1)
        self.assertEqual(len((self.目录 / "上次日志.bak.jsonl").read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual(sorted(p.name for p in self.目录.glob("上次日志*")), ["上次日志.bak.jsonl"])

    def test_只压缩一次(self):
        导出并清空任务日志(self.路径)
        self.assertTrue(压缩数据库一次(self.路径))
        self.assertFalse(压缩数据库一次(self.路径))

    def test_错误日志轮转为单个bak(self):
        (self.目录 / "robot-error.log").write_text("old", encoding="utf-8")
        (self.目录 / "robot-error.log.bak").write_text("older", encoding="utf-8")
        self.assertTrue(轮转错误日志(self.目录))
        self.assertFalse((self.目录 / "robot-error.log").exists())
        self.assertEqual((self.目录 / "robot-error.log.bak").read_text(encoding="utf-8"), "old")
        self.assertFalse(轮转错误日志(self.目录))

    def test_会话轮转不抛异常且缺库时无操作(self):
        结果 = 会话日志轮转(self.目录 / "不存在.db", 记录=lambda *_: None)
        self.assertEqual(结果["导出条数"], 0)
        结果 = 会话日志轮转(self.路径, 记录=lambda *_: None)
        self.assertEqual(结果["导出条数"], 3)
        self.assertTrue(结果["已压缩"])

    def test_导出失败时不删日志(self):
        备份目录 = self.目录 / "只读"
        备份目录.mkdir()
        坏路径 = 备份目录 / "不存在的子目录" / "x.jsonl"
        with self.assertRaises(OSError):
            导出并清空任务日志(self.路径, 坏路径)
        self.assertEqual(self._计数("任务日志"), 3)


if __name__ == "__main__":
    unittest.main()
