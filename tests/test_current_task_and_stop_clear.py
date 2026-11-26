"""界面当前任务显示以任务边界日志为准；脚本停止后导出备份并清空日志。"""
import json
import os
import queue
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from 应用.日志模型 import 解析任务边界, 日志聚合器
from 数据库.日志轮转 import 停止后导出并清空, 读取最近日志, 备份文件名


def 聚合器加日志(聚合, 行列表, 机器人="r"):
    队列 = 聚合._队列
    for 时间, 内容 in 行列表:
        队列.put({"内容": 内容, "机器人ID": 机器人, "记录时间": 时间})
    聚合.消费实时队列(上限=10000)


def 新聚合器():
    return 日志聚合器(queue.Queue(), 读取历史=lambda *_: [], 获取机器人列表=lambda: ["r"])


class 任务边界解析测试(unittest.TestCase):
    def test_开始任务映射任务键(self):
        self.assertEqual(解析任务边界("开始任务：主世界刷资源"), ("main_resource", "主世界刷资源"))
        self.assertEqual(解析任务边界("[12:00:00] 开始任务：部落竞赛接任务"), ("event", "部落竞赛接任务"))
        self.assertEqual(解析任务边界("开始任务：启动游戏"), (None, "启动游戏"))

    def test_结束类日志(self):
        for 文本 in ("完成任务：主世界刷资源", "[警告] 任务未完成：主世界刷资源", "收到停止事件",
                   "[警告] 收到外部停止请求：界面停止按钮", "安全待命结束，停止后续任务和所有点击",
                   "开始运行任务计划"):
            with self.subTest(文本=文本):
                self.assertEqual(解析任务边界(文本), (None, None))

    def test_普通日志不是边界(self):
        self.assertIsNone(解析任务边界("世界识别：当前=夜世界，主世界=0.29"))
        self.assertIsNone(解析任务边界("部落竞赛：本次结果：非主世界"))


class 当前任务显示测试(unittest.TestCase):
    def test_2026_11_26实机日志主世界刷资源期间不被夜世界和竞赛日志带偏(self):
        聚合 = 新聚合器()
        t = time.time() - 100
        聚合器加日志(聚合, [
            (t + 0, "开始任务：部落竞赛接任务"),
            (t + 1, "部落竞赛：当前不在主世界主页，本轮不操作"),
            (t + 2, "完成任务：部落竞赛接任务"),
            (t + 3, "开始任务：主世界刷资源"),
            (t + 4, "世界识别：当前=夜世界，主世界=0.29，夜世界=0.74"),
        ])
        self.assertEqual(聚合.当前任务键("r"), "main_resource")
        self.assertEqual(聚合.当前任务名称("r"), "主世界刷资源")
        聚合器加日志(聚合, [(t + 5, "部落竞赛：本轮跳过：冷却中，还剩约20分钟")])
        self.assertEqual(聚合.当前任务键("r"), "main_resource")

    def test_任务完成后立即清空(self):
        聚合 = 新聚合器()
        t = time.time() - 10
        聚合器加日志(聚合, [(t, "开始任务：部落竞赛接任务"), (t + 1, "完成任务：部落竞赛接任务"),
                       (t + 2, "部落竞赛：本次结果：已接任务")])
        self.assertIsNone(聚合.当前任务键("r"))
        self.assertIsNone(聚合.当前任务名称("r"))

    def test_任务未完成和停止都清空(self):
        for 结束 in ("[警告] 任务未完成：主世界刷资源", "收到停止事件"):
            with self.subTest(结束=结束):
                聚合 = 新聚合器()
                t = time.time() - 10
                聚合器加日志(聚合, [(t, "开始任务：主世界刷资源"), (t + 1, 结束)])
                self.assertIsNone(聚合.当前任务键("r"))

    def test_长时间打鱼超过日志保留条数仍显示正确(self):
        聚合 = 新聚合器()
        t = time.time() - 5000
        行 = [(t, "开始任务：主世界刷资源")]
        行 += [(t + 1 + i, "夜世界资源栏" if i % 2 else "下兵") for i in range(3000)]
        聚合器加日志(聚合, 行)
        self.assertEqual(聚合.当前任务键("r"), "main_resource")

    def test_历史同步也记录边界(self):
        t = time.time() - 10
        记录 = [SimpleNamespace(记录时间=t + 1, 日志内容="开始任务：夜世界刷资源"),
              SimpleNamespace(记录时间=t, 日志内容="完成任务：启动游戏")]
        聚合 = 日志聚合器(None, 读取历史=lambda 标志, 起始: 记录 if 起始 < t else [],
                     获取机器人列表=lambda: ["r"])
        聚合.同步历史()
        self.assertEqual(聚合.当前任务键("r"), "night_resource")

    def test_没有边界日志时退回关键词推断(self):
        聚合 = 新聚合器()
        聚合器加日志(聚合, [(time.time() - 1, "按任务计划执行：wall")])
        self.assertEqual(聚合.当前任务键("r"), "wall")

    def test_清空会话只清截止前的日志和边界(self):
        聚合 = 新聚合器()
        t = time.time() - 10
        聚合器加日志(聚合, [(t, "开始任务：主世界刷资源"), (t + 1, "收到停止事件")])
        截止 = t + 2
        聚合器加日志(聚合, [(t + 3, "开始运行任务计划"), (t + 4, "开始任务：启动游戏")])
        聚合.清空会话(截止)
        内容 = [项.内容 for 项 in 聚合.全部条目()]
        self.assertEqual(内容, ["开始运行任务计划", "开始任务：启动游戏"])
        self.assertEqual(聚合.当前任务名称("r"), "启动游戏")

    def test_清空会话不带截止时全部清掉(self):
        聚合 = 新聚合器()
        聚合器加日志(聚合, [(time.time() - 5, "开始任务：主世界刷资源")])
        聚合.记录操作("停止")
        聚合.清空会话()
        self.assertEqual(聚合.全部条目(), [])
        self.assertIsNone(聚合.当前任务名称("r"))


class 界面文本测试(unittest.TestCase):
    def test_竞赛已接任务与正在执行分开(self):
        from 界面.主窗口 import 竞赛已接任务文本, 运行状态文本

        self.assertEqual(竞赛已接任务文本({}), "")
        self.assertEqual(竞赛已接任务文本({"当前任务": "掠夺黑油（300分）"}), "竞赛已接：掠夺黑油（300分）")
        self.assertEqual(
            竞赛已接任务文本({"当前任务": "进行中的任务", "当前任务进度": [2, 5]}),
            "竞赛已接：进行中的任务 · 进度 2/5",
        )
        self.assertEqual(运行状态文本("主世界刷资源", "下兵"), "正在执行：主世界刷资源 · 下兵")
        self.assertEqual(运行状态文本(None, "下兵"), "下兵")
        self.assertIn("等待", 运行状态文本(None, None))


def 建库(路径: Path, 行列表):
    连接 = sqlite3.connect(str(路径))
    连接.execute("CREATE TABLE 任务日志 (记录ID INTEGER PRIMARY KEY AUTOINCREMENT, 机器人标志 TEXT, "
               "日志内容 TEXT, 记录时间 REAL, 下次超时 REAL)")
    连接.execute("CREATE TABLE 运行时状态 (记录ID INTEGER PRIMARY KEY, 机器人标志 TEXT, 状态类型 TEXT, 状态值 TEXT)")
    连接.execute("INSERT INTO 运行时状态 VALUES (1, 'r', '部落竞赛检查记录', '{}')")
    for 标志, 内容, 时间 in 行列表:
        连接.execute("INSERT INTO 任务日志 (机器人标志, 日志内容, 记录时间, 下次超时) VALUES (?,?,?,0)",
                   (标志, 内容, 时间))
    连接.commit()
    连接.close()


class 停止后清空测试(unittest.TestCase):
    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="stop_clear_"))
        self.库 = self.目录 / "任务系统.db"

    def test_导出备份覆盖旧备份后清空且不碰运行时状态(self):
        (self.目录 / 备份文件名).write_text('{"id": 1, "内容": "旧备份"}\n', encoding="utf-8")
        建库(self.库, [("r", "开始任务：主世界刷资源", 100.0), ("r", "收到停止事件", 101.0)])
        self.assertEqual(停止后导出并清空(self.库), 2)
        备份 = [json.loads(行) for 行 in (self.目录 / 备份文件名).read_text(encoding="utf-8").splitlines()]
        self.assertEqual([项["内容"] for 项 in 备份], ["开始任务：主世界刷资源", "收到停止事件"])
        连接 = sqlite3.connect(str(self.库))
        self.assertEqual(连接.execute("SELECT COUNT(*) FROM 任务日志").fetchone()[0], 0)
        self.assertEqual(连接.execute("SELECT COUNT(*) FROM 运行时状态").fetchone()[0], 1)
        连接.close()

    def test_表已空时不动备份(self):
        (self.目录 / 备份文件名).write_text('{"id": 1, "内容": "上一份"}\n', encoding="utf-8")
        建库(self.库, [])
        self.assertEqual(停止后导出并清空(self.库), 0)
        self.assertIn("上一份", (self.目录 / 备份文件名).read_text(encoding="utf-8"))

    def test_失败不抛异常(self):
        记录 = []
        self.assertEqual(停止后导出并清空(self.目录 / "不存在.db", 记录=记录.append), 0)

    def test_清空后读取最近日志能读到备份(self):
        建库(self.库, [("r", f"旧{i}", 100.0 + i) for i in range(5)] + [("其它", "别的机器人", 103.5)])
        停止后导出并清空(self.库)
        连接 = sqlite3.connect(str(self.库))
        连接.execute("INSERT INTO 任务日志 (机器人标志, 日志内容, 记录时间, 下次超时) VALUES ('r','新',200,0)")
        连接.commit()
        连接.close()
        self.assertEqual(
            [内容 for _, 内容 in 读取最近日志(self.库, "r", 最大条数=3)],
            ["旧3", "旧4", "新"],
        )
        self.assertEqual(len(读取最近日志(self.库, "r", 最大条数=100)), 6)


class 控制器停止清空测试(unittest.TestCase):
    def _控制器(self, 状态序列):
        from 应用.控制器 import 应用控制器

        机器人 = SimpleNamespace(当前状态="运行中", 主线程=None)
        监控 = SimpleNamespace(机器人池={"robot_1": 机器人})
        目录 = Path(tempfile.mkdtemp(prefix="ctl_clear_"))
        库 = 目录 / "任务系统.db"
        建库(库, [("robot_1", "开始任务：主世界刷资源", time.time() - 5)])
        控制器 = 应用控制器(监控, 数据库=SimpleNamespace(文件路径=str(库)))
        return 控制器, 机器人, 库

    def test_只在运行变停止那一次触发(self):
        控制器, 机器人, _ = self._控制器(None)
        self.assertFalse(控制器.检测到停止())  # 初始已停止 → 运行中
        机器人.当前状态 = "已停止"
        self.assertTrue(控制器.检测到停止())
        self.assertFalse(控制器.检测到停止())

    def test_暂停后停止也触发且清理中不重复(self):
        控制器, 机器人, _ = self._控制器(None)
        机器人.当前状态 = "暂停中"
        控制器.检测到停止()
        机器人.当前状态 = "已停止"
        self.assertTrue(控制器.检测到停止())
        机器人.当前状态 = "运行中"
        控制器.检测到停止()
        机器人.当前状态 = "已停止"
        self.assertFalse(控制器.检测到停止())  # 上一次清理还没结束

    def test_停止后清空日志等线程退出后导出并清空(self):
        控制器, 机器人, 库 = self._控制器(None)
        退出 = threading.Event()
        机器人.主线程 = threading.Thread(target=退出.wait, args=(5,), daemon=True)
        机器人.主线程.start()
        机器人.当前状态 = "已停止"
        控制器.检测到停止()
        threading.Timer(0.05, 退出.set).start()
        结果 = 控制器.停止后清空日志(睡眠=lambda 秒: None)
        self.assertFalse(机器人.主线程.is_alive())
        self.assertEqual(结果[0], 1)
        self.assertLessEqual(结果[1], time.time())
        self.assertTrue((库.parent / 备份文件名).is_file())
        self.assertFalse(控制器._日志清理中)

    def test_有机器人重新运行时不清空(self):
        控制器, 机器人, 库 = self._控制器(None)
        机器人.当前状态 = "已停止"
        控制器.检测到停止()
        机器人.当前状态 = "运行中"  # 等待期间被重新启动
        self.assertIsNone(控制器.停止后清空日志(睡眠=lambda 秒: None))
        连接 = sqlite3.connect(str(库))
        self.assertEqual(连接.execute("SELECT COUNT(*) FROM 任务日志").fetchone()[0], 1)
        连接.close()
        self.assertFalse(控制器._日志清理中)


if __name__ == "__main__":
    unittest.main()
