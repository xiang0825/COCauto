"""方案 A 附加逻辑（不需要窗口）：当前任务推断、日志胶囊分类、现场图就近匹配。"""
import time
import unittest
from types import SimpleNamespace

from 应用.日志模型 import 推断任务键, 日志聚合器


class 当前任务推断测试(unittest.TestCase):
    def test_引擎任务键优先(self):
        self.assertEqual(推断任务键("按任务计划执行：hero"), "hero")
        self.assertEqual(推断任务键("[实时] 按任务计划执行：wall"), "wall")
        self.assertIsNone(推断任务键("按任务计划执行："))

    def test_特征词(self):
        self.assertEqual(推断任务键("部落竞赛：接取任务"), "event")
        self.assertEqual(推断任务键("夜世界：开始搜索"), "night_resource")
        self.assertEqual(推断任务键("搜索第 3 个村庄，开始进攻"), "main_resource")
        self.assertIsNone(推断任务键("收集资源完成"))

    def test_聚合器取最近且未过期的任务(self):
        import queue

        队列 = queue.Queue()
        聚合 = 日志聚合器(队列, 读取历史=lambda *_: [], 获取机器人列表=lambda: ["r"])
        现在 = time.time()
        队列.put({"内容": "按任务计划执行：wall", "机器人ID": "r", "记录时间": 现在 - 5})
        队列.put({"内容": "收集资源完成", "机器人ID": "r", "记录时间": 现在 - 1})
        聚合.消费实时队列()
        self.assertEqual(聚合.当前任务键("r"), "wall")
        self.assertIsNone(聚合.当前任务键("r", 最长秒=0.5))
        self.assertIsNone(聚合.当前任务键("其他"))


class 日志胶囊分类测试(unittest.TestCase):
    def test_分类(self):
        from 界面.日志视图 import 日志类别

        self.assertEqual(日志类别("资源不足", "警告"), "异常")
        self.assertEqual(日志类别("部落竞赛：接取任务", "正常"), "竞赛")
        self.assertEqual(日志类别("搜索第 12 个村庄", "正常"), "搜敌")
        self.assertEqual(日志类别("战斗结束：胜利", "成功"), "进攻")
        self.assertEqual(日志类别("护盾中，进入待命", "正常"), "保护")
        self.assertEqual(日志类别("收集资源完成", "正常"), "系统")


class 现场图索引测试(unittest.TestCase):
    def test_窗口内就近匹配(self):
        from 界面.方案A部件 import 现场图索引

        条目 = [SimpleNamespace(时间戳=t, 文件路径=f"{t}.png") for t in (100.0, 200.0, 400.0)]
        服务 = SimpleNamespace(扫描全部=lambda: 条目)
        索引 = 现场图索引(服务, 窗口秒=60)
        self.assertIsNone(索引.查找(150))
        索引.刷新(同步=True)
        self.assertEqual(索引.查找(150).时间戳, 100.0)
        self.assertEqual(索引.查找(185).时间戳, 200.0)
        self.assertIsNone(索引.查找(300))
        self.assertEqual(索引.查找(455).时间戳, 400.0)


if __name__ == "__main__":
    unittest.main()
