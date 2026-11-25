"""第二批稳定性与识别准确度优化（fix/stability-batch2）专项单测。"""

from __future__ import annotations

import inspect
import logging
import os
import sys
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from 核心.ADB屏幕 import ADB屏幕, 检查分辨率比例告警
from 核心.鼠标操作 import 鼠标控制器
from 数据库.任务数据库 import 任务数据库
from 任务流程.基础任务框架 import 任务上下文
from 任务流程.检查图像 import 检查图像任务
from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务
from 任务流程.主世界打鱼.搜索页面识别 import 搜索页面识别器
from 任务流程.夜世界.夜世界打鱼 import 夜世界打鱼任务
from 任务流程.夜世界.夜世界打鱼.下兵 import 下兵
from 任务流程.夜世界.夜世界打鱼.打开进攻页面任务 import 打开进攻页面
from 模块.检测.YOLO检测器.yolo import 线程安全YOLO检测器
from 应用.日志模型 import 是否重点, 推断级别
from 线程.自动化机器人 import 自动化机器人


def _构造搜索画面(资源像素值: int = 0) -> np.ndarray:
    画面 = np.zeros((600, 800, 3), dtype=np.uint8)
    # 敌方资源栏裁剪区 [67:190, 14:151]
    画面[67:190, 14:151] = 资源像素值
    # 右侧橙色“下一个”按钮区域
    画面[390:464, 665:792] = (0, 180, 245)
    return 画面


class 第二批稳定性优化测试(unittest.TestCase):
    # ------------------------------------------------------------------ P1-3
    def test_P1_3_点击下一个后等待资源栏指纹变化(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.模板识别 = None
        任务.下一场等待变化超时秒 = 2.0
        任务.下一场轮询间隔秒 = 0.01

        旧图 = _构造搜索画面(资源像素值=20)
        新图 = _构造搜索画面(资源像素值=220)
        self.assertNotEqual(
            任务._计算稳定区域指纹(旧图),
            任务._计算稳定区域指纹(新图),
        )

        # 第1次查按钮用旧图，等待轮询先返回1次旧图再返回新图
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(side_effect=[旧图, 旧图, 新图])
            ),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            点击已确认搜索按钮=Mock(return_value=True),
            停止事件=threading.Event(),
        )
        with patch.object(
            搜索页面识别器,
            "查找下一个按钮",
            return_value=(True, (728, 428), "橙黄色按钮", 0.90),
        ):
            self.assertTrue(任务.点击下一个按钮(上下文))

        self.assertEqual(上下文.op.获取屏幕图像cv.call_count, 3)
        # P1-3 等待新帧不得调用脚本延时，避免破坏已有单测断言
        上下文.脚本延时.assert_not_called()

    def test_P1_3_画面超时未变时安全记录日志不卡死(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.下一场轮询间隔秒 = 0.01
        静止图 = _构造搜索画面(资源像素值=50)
        指纹 = 任务._计算稳定区域指纹(静止图)
        日志 = []
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=静止图)),
            置脚本状态=日志.append,
            停止事件=threading.Event(),
        )

        变化 = 任务._等待下一场画面变化(上下文, 指纹, 超时秒=0.05)

        self.assertFalse(变化)
        self.assertTrue(any("未变化" in 项 for 项 in 日志))

    # ------------------------------------------------------------------ P1-4
    def test_P1_4_敌方资源OCR超上限时复读取多数合理值(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.资源异常复读延时毫秒 = 1
        # 第1次误读10倍(5,000,000)，后两次正常(500,000)
        任务.ocr引擎 = Mock(
            side_effect=[
                ([[0, 18], [40, 18], [40, 26], [0, 26]], "5000000", 0.99),
            ]
        )

        def 模拟OCR(_图):
            序号 = 模拟OCR.调用次数
            模拟OCR.调用次数 += 1
            金币文本 = "5000000" if 序号 == 0 else "500000"
            return (
                [
                    ([[0, 14], [40, 14], [40, 22], [0, 22]], 金币文本, 0.98),
                    ([[0, 47], [40, 47], [40, 55], [0, 55]], "320000", 0.98),
                    ([[0, 79], [40, 79], [40, 87], [0, 87]], "4500", 0.98),
                ],
                None,
            )

        模拟OCR.调用次数 = 0
        任务.ocr引擎 = Mock(side_effect=模拟OCR)
        设置 = SimpleNamespace(战利品优先级="均衡")
        日志 = []
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(
                    return_value=np.zeros((600, 800, 3), dtype=np.uint8)
                )
            ),
            数据库=SimpleNamespace(获取机器人设置=Mock(return_value=设置)),
            机器人标志="robot_1",
            置脚本状态=日志.append,
            脚本延时=Mock(),
            是否内存异常=lambda _异常: False,
            触发内存保护=Mock(),
        )
        任务.上下文 = 上下文

        结果 = 任务.识别当前资源(
            上下文, np.zeros((600, 800, 3), dtype=np.uint8)
        )

        self.assertEqual(结果["金币"], 500_000)
        self.assertEqual(结果["圣水"], 320_000)
        self.assertEqual(结果["黑油"], 4_500)
        self.assertFalse(结果.get("资源识别异常", False))
        self.assertEqual(任务.ocr引擎.call_count, 3)

    def test_P1_4_敌方资源OCR复读仍异常时安全跳过(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.资源异常复读延时毫秒 = 1
        任务.ocr引擎 = Mock(
            return_value=(
                [
                    ([[0, 14], [40, 14], [40, 22], [0, 22]], "9900000", 0.99),
                    ([[0, 47], [40, 47], [40, 55], [0, 55]], "300000", 0.99),
                    ([[0, 79], [40, 79], [40, 87], [0, 87]], "45000", 0.99),
                ],
                None,
            )
        )
        设置 = SimpleNamespace(战利品优先级="均衡", 欲进攻的最小资源=0)
        日志 = []
        上下文 = SimpleNamespace(
            设置=SimpleNamespace(是否采集进攻界面图像=False),
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(
                    return_value=np.zeros((600, 800, 3), dtype=np.uint8)
                )
            ),
            数据库=SimpleNamespace(获取机器人设置=Mock(return_value=设置)),
            机器人标志="robot_1",
            置脚本状态=日志.append,
            脚本延时=Mock(),
            是否内存异常=lambda _异常: False,
            触发内存保护=Mock(),
        )
        任务.上下文 = 上下文
        任务.等待下一个按钮出现 = Mock(return_value=True)
        任务.点击下一个按钮 = Mock(return_value=True)
        任务.检测器 = SimpleNamespace(检测=Mock())

        self.assertFalse(任务.执行单次搜索(上下文, 搜索次数=1, 最小资源=0))
        任务.点击下一个按钮.assert_called_once_with(上下文)
        任务.检测器.检测.assert_not_called()
        self.assertTrue(any("超过合理上限" in 项 for 项 in 日志))

    # ------------------------------------------------------------------ P1-6
    def test_P1_6_YOLO跨类别高重叠框去重仅保留最高置信度(self):
        重叠检测 = [
            {"类别名称": "金矿", "裁剪坐标": [56, 246, 86, 276], "置信度": 0.62},
            {"类别名称": "金库", "裁剪坐标": [55, 245, 85, 275], "置信度": 0.92},
            {"类别名称": "圣水采集器", "裁剪坐标": [715, 270, 745, 300], "置信度": 0.20},
            {"类别名称": "圣水瓶", "裁剪坐标": [715, 270, 745, 300], "置信度": 0.88},
        ]

        去重后 = 搜索目标敌人任务.过滤与去重资源检测框(重叠检测)
        self.assertEqual(len(去重后), 2)
        self.assertEqual([项["类别名称"] for 项 in 去重后], ["金库", "圣水瓶"])

        _, 依据 = 搜索目标敌人任务.计算资源易窃取评分(重叠检测)
        self.assertEqual(依据["资源建筑数"], 2)
        self.assertEqual(依据["储存建筑数"], 2)

        yolo去重 = 线程安全YOLO检测器.跨类别重叠框去重(重叠检测)
        self.assertEqual(len(yolo去重), 2)
        self.assertEqual([项["类别名称"] for 项 in yolo去重], ["金库", "圣水瓶"])

    # ------------------------------------------------------------------ P1-7
    def test_P1_7_非4比3分辨率输出明确中文警告但不阻断(self):
        self.assertIsNone(检查分辨率比例告警(800, 600))
        self.assertIsNone(检查分辨率比例告警(1600, 1200))

        告警 = 检查分辨率比例告警(1280, 720)
        self.assertIsNotNone(告警)
        self.assertIn("800×600", 告警)
        self.assertIn("4:3", 告警)
        self.assertIn("横向拉伸", 告警)

        日志 = []
        宽屏图 = np.zeros((720, 1280, 3), dtype=np.uint8)
        设备 = SimpleNamespace(
            参考宽度=800,
            参考高度=600,
            获取屏幕图像cv=Mock(return_value=宽屏图),
        )
        屏幕 = ADB屏幕(设备, 日志回调=日志.append)
        返回图 = 屏幕.获取屏幕图像cv(0, 0, 800, 600)
        self.assertEqual(返回图.shape, (600, 800, 3))
        self.assertEqual(len(日志), 1)
        self.assertIn("1280×720", 日志[0])
        # 同一分辨率不重复刷屏
        屏幕.获取屏幕图像cv(0, 0, 800, 600, 强制刷新=True)
        self.assertEqual(len(日志), 1)

        检查日志 = []
        检查上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=宽屏图)),
            置脚本状态=检查日志.append,
        )
        检查任务 = 检查图像任务.__new__(检查图像任务)
        检查任务.上下文 = 检查上下文
        self.assertTrue(检查任务.执行())
        self.assertEqual(len(检查日志), 2)
        self.assertIn("1280×720", 检查日志[0])
        self.assertIn("横向拉伸", 检查日志[1])

    # --------------------------------------------------------- 夜世界 P1 补丁
    def test_夜世界打开进攻页面等待超时与停止事件安全返回失败(self):
        任务 = 打开进攻页面.__new__(打开进攻页面)
        任务.进攻等待超时秒 = 0.05
        任务.进攻等待轮询毫秒 = 1
        上下文 = SimpleNamespace(
            点击=Mock(return_value=True),
            置脚本状态=Mock(),
            脚本延时=Mock(),
            停止事件=threading.Event(),
        )
        任务.上下文 = 上下文
        任务.是否出现开始进攻 = Mock(return_value=True)
        任务.是否出现进攻需要等待 = Mock(return_value=True)

        with patch(
            "任务流程.夜世界.夜世界打鱼.打开进攻页面任务.time.monotonic",
            side_effect=[0.0, 0.06],
        ):
            self.assertFalse(任务.执行())
        self.assertTrue(
            any("超过" in c.args[0] for c in 上下文.置脚本状态.call_args_list)
        )

        # 停止事件触发时立即返回失败
        上下文.停止事件.set()
        with patch(
            "任务流程.夜世界.夜世界打鱼.打开进攻页面任务.time.monotonic",
            return_value=0.0,
        ):
            self.assertFalse(任务.执行())

    def test_鼠标控制器具备RLock且多线程点击坐标不串台(self):
        记录 = []

        class 线程检查设备:
            def 触控(self, x, y):
                记录.append((x, y))
                return 1

            def 滑动(self, 起点, 终点, 时长):
                记录.append((起点, 终点))
                return 1

        控制器 = 鼠标控制器(线程检查设备())
        self.assertIsInstance(控制器._锁, type(threading.RLock()))

        # 持有锁时另一线程的 移动到 不得插队修改坐标
        就绪 = threading.Event()
        线程完成 = threading.Event()

        def 干扰线程():
            就绪.set()
            控制器.移动到(42, 554)
            控制器.左键点击()
            线程完成.set()

        t = threading.Thread(target=干扰线程)
        with 控制器._锁:
            控制器.移动到(300, 400)
            t.start()
            就绪.wait(timeout=1.0)
            time.sleep(0.03)
            控制器.左键点击()
        self.assertTrue(线程完成.wait(timeout=1.0))
        t.join(timeout=1.0)
        self.assertEqual(记录, [(300, 400), (42, 554)])

    def test_夜世界英雄技能后台线程结束前join干净退出(self):
        任务 = 下兵.__new__(下兵)
        任务.上下文 = SimpleNamespace(
            点击=Mock(return_value=True),
            置脚本状态=Mock(),
        )
        任务.启动后台放英雄技能()
        线程 = 任务.上下文.英雄技能线程
        self.assertTrue(线程.is_alive())

        with patch.object(线程, "join", wraps=线程.join) as join_spy:
            已结束 = 下兵.停止并等待英雄技能线程(任务.上下文, 超时秒=2.0)

        self.assertTrue(已结束)
        join_spy.assert_called_once_with(timeout=2.0)
        self.assertFalse(线程.is_alive())
        self.assertFalse(hasattr(任务.上下文, "英雄技能标志"))
        self.assertFalse(hasattr(任务.上下文, "英雄技能线程"))

        # 夜世界打鱼任务退出时最多等待 5 秒确认后台英雄技能线程干净结束。
        外层任务 = 夜世界打鱼任务.__new__(夜世界打鱼任务)
        外层任务.上下文 = SimpleNamespace(
            置脚本状态=Mock(), _战斗中=True, 数据库=Mock()
        )
        假子任务 = Mock()
        假子任务.执行.return_value = False
        with patch("任务流程.夜世界.夜世界打鱼.打开进攻页面", return_value=假子任务), \
             patch("任务流程.夜世界.夜世界打鱼.等待进入战斗", return_value=假子任务), \
             patch("任务流程.夜世界.夜世界打鱼.下兵", return_value=假子任务), \
             patch("任务流程.夜世界.夜世界打鱼.等待回营或第二次战斗", return_value=假子任务), \
             patch(
                 "任务流程.夜世界.夜世界打鱼.停止并等待英雄技能线程",
                 wraps=下兵.停止并等待英雄技能线程,
             ) as cleanup_spy:
            self.assertFalse(外层任务.执行())
        cleanup_spy.assert_called_once_with(外层任务.上下文, 超时秒=5.0)

    # ------------------------------------------------------------------ P1-9
    def test_P1_9_进程资源趋势日志按30分钟节流且异常安全(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "robot_1"
        日志 = []
        上下文 = SimpleNamespace(置脚本状态=日志.append)

        with patch("线程.自动化机器人.time.monotonic", return_value=100.0):
            self.assertTrue(机器人._记录进程资源趋势(上下文))
        self.assertEqual(len(日志), 1)
        self.assertIn("进程资源趋势", 日志[0])
        self.assertIn("线程=", 日志[0])

        # 500 秒内不刷屏
        with patch("线程.自动化机器人.time.monotonic", return_value=600.0):
            self.assertFalse(机器人._记录进程资源趋势(上下文))
        self.assertEqual(len(日志), 1)

        # 超过 1800 秒后记录第二条
        with patch("线程.自动化机器人.time.monotonic", return_value=1950.0):
            self.assertTrue(机器人._记录进程资源趋势(上下文))
        self.assertEqual(len(日志), 2)

        # 采集失败时安全降级不抛异常
        with patch("线程.自动化机器人._采集进程资源指标", side_effect=RuntimeError("boom")):
            self.assertFalse(机器人._记录进程资源趋势(上下文, 强制=True))

    # ------------------------------------------------------------------ P2-1
    def test_P2_1_WAL模式PRAGMA同一路径仅首次执行且零删除日志(self):
        with tempfile.TemporaryDirectory(prefix="coc-wal-once-") as 临时目录:
            db路径 = os.path.join(临时目录, "task.db")
            真实connect = sqlite3.connect
            执行SQL列表 = []

            class 监听连接:
                def __init__(self, conn):
                    self._conn = conn

                def execute(self, sql, *args, **kwargs):
                    执行SQL列表.append(str(sql))
                    return self._conn.execute(sql, *args, **kwargs)

                def __getattr__(self, name):
                    return getattr(self._conn, name)

            with patch(
                "数据库.任务数据库.sqlite3.connect",
                side_effect=lambda *a, **kw: 监听连接(真实connect(*a, **kw)),
            ):
                db1 = 任务数据库(db路径)
                for 索引 in range(5):
                    db1.记录日志("robot_1", f"日志{索引}", time.time() + 60)
                db2 = 任务数据库(db路径)
                db2.读取最后日志("robot_1")

            wal次数 = sum("PRAGMA journal_mode=WAL" in sql for sql in 执行SQL列表)
            self.assertEqual(wal次数, 1)
            self.assertFalse(any("DELETE FROM 任务日志" in sql for sql in 执行SQL列表))
            # 确认历史日志完整保留，未被清理
            conn = 真实connect(db路径)
            try:
                数量 = conn.execute("SELECT COUNT(*) FROM 任务日志").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(数量, 5)

    # -------------------------------------------------------------- P2-2 / P2-3
    def test_P2_2_点击护栏仅在页面状态变化时记录日志(self):
        日志 = []
        结果A = SimpleNamespace(
            页面="战斗中", 世界="主世界", 依据=("兵栏",),
            摘要=lambda: "页面=战斗中，世界=主世界",
        )
        结果B = SimpleNamespace(
            页面="主世界主页", 世界="主世界", 依据=("资源栏",),
            摘要=lambda: "页面=主世界主页，世界=主世界",
        )
        识别器 = SimpleNamespace(识别=Mock(side_effect=[结果A, 结果A, 结果B]))
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.op = SimpleNamespace(
            获取屏幕图像cv=Mock(
                side_effect=lambda *a, **k: np.zeros((600, 800, 3), dtype=np.uint8)
            )
        )
        上下文._获取点击页面识别器 = Mock(return_value=识别器)
        上下文.获取OCR引擎 = Mock(return_value=Mock(return_value=([], [])))
        上下文.获取模板识别器 = Mock(return_value=None)
        上下文.置脚本状态 = 日志.append
        上下文._战斗中 = True
        上下文.是否内存异常 = lambda _e: False
        上下文.触发内存保护 = Mock()
        上下文._点击识别截图 = None
        上下文._点击识别截图时间 = 0.0
        时钟 = [1.0]

        with patch("任务流程.基础任务框架.time.monotonic", side_effect=lambda: 时钟[0]):
            上下文.识别点击画面()
            # 即使过去 9 秒，页面状态未变也不重复写日志
            时钟[0] = 10.0
            上下文.识别点击画面()
            # 状态变化时才记录第二条
            时钟[0] = 11.0
            上下文.识别点击画面()

        self.assertEqual(len(日志), 2)
        self.assertIn("战斗中", 日志[0])
        self.assertIn("主世界主页", 日志[1])

    def test_P2_3_搜索确认与异常终止文案准确且日志级别兼容(self):
        源码 = Path(inspect.getsourcefile(任务上下文)).read_text(encoding="utf-8")
        self.assertNotIn("已清除过渡帧结算误报", 源码)
        self.assertNotIn("线程即将死亡", 源码)

        日志 = []
        队列 = SimpleNamespace(put=Mock())
        假上下文 = SimpleNamespace(
            置脚本状态=日志.append,
            消息队列=队列,
            机器人标志="robot_1",
            停止事件=threading.Event(),
        )
        任务上下文.发送死亡通知(假上下文, "ADB 断线")
        self.assertEqual(len(日志), 1)
        self.assertIn("任务异常终止", 日志[0])
        self.assertNotIn("线程即将死亡", 日志[0])
        self.assertEqual(推断级别(日志[0]), "错误")
        self.assertTrue(是否重点(日志[0]))

    # -------------------------------------------------------------- P2-4 / P2-5
    def test_P2_4与P2_5_无重复内存检查定义且截图缓存返回拷贝(self):
        源码 = Path(inspect.getsourcefile(ADB屏幕)).read_text(encoding="utf-8")
        self.assertEqual(源码.count("def 检查主机内存预算("), 1)

        原始图 = np.full((600, 800, 3), 100, dtype=np.uint8)
        设备 = SimpleNamespace(
            参考宽度=800,
            参考高度=600,
            获取屏幕图像cv=Mock(return_value=原始图),
        )
        屏幕 = ADB屏幕(设备)

        图1 = 屏幕.获取屏幕图像cv(0, 0, 800, 600)
        # 在返回图像上原地涂画，模拟画框操作
        图1[:, :] = 255

        # 短窗口命中缓存时，第二次返回的图不应受图1原地修改污染
        图2 = 屏幕.获取屏幕图像cv(0, 0, 800, 600)
        self.assertEqual(int(图2[0, 0, 0]), 100)
        self.assertEqual(设备.获取屏幕图像cv.call_count, 1)

    # ------------------------------------------------------------------ P2-10
    def test_P2_10_error日志落盘使用数据库目录绝对路径和RotatingHandler(self):
        with tempfile.TemporaryDirectory(prefix="coc-errlog-") as db目录, \
             tempfile.TemporaryDirectory(prefix="coc-cwd-") as 其他目录:
            db路径 = os.path.join(db目录, "任务系统.db")
            机器人 = 自动化机器人.__new__(自动化机器人)
            机器人.数据库 = SimpleNamespace(文件路径=db路径)

            原目录 = os.getcwd()
            try:
                os.chdir(其他目录)
                错误路径 = 机器人._写入未处理异常日志("Traceback: test error\n")
            finally:
                os.chdir(原目录)

            预期路径 = os.path.abspath(os.path.join(db目录, "robot-error.log"))
            self.assertEqual(错误路径, 预期路径)
            self.assertTrue(os.path.isabs(错误路径))
            self.assertTrue(os.path.isfile(预期路径))
            self.assertFalse(os.path.exists(os.path.join(其他目录, "robot-error.log")))
            self.assertIn("Traceback: test error", Path(预期路径).read_text(encoding="utf-8"))

            self.assertEqual(自动化机器人.错误日志最大字节, 5 * 1024 * 1024)

    def test_P2_10_error日志超过上限时改名归档且绝不删除旧日志(self):
        with tempfile.TemporaryDirectory(prefix="coc-errlog-") as db目录:
            机器人 = 自动化机器人.__new__(自动化机器人)
            机器人.数据库 = SimpleNamespace(文件路径=os.path.join(db目录, "任务系统.db"))
            机器人.错误日志最大字节 = 100
            旧归档 = Path(db目录, "robot-error.20200101_000000.log")
            旧归档.write_text("old archive", encoding="utf-8")
            Path(db目录, "robot-error.log").write_text("x" * 200, encoding="utf-8")

            路径 = 机器人._写入未处理异常日志("Traceback: new error\n")

            文件 = sorted(p.name for p in Path(db目录).glob("robot-error*.log"))
            self.assertEqual(len(文件), 3)
            self.assertTrue(旧归档.is_file())
            self.assertIn("Traceback: new error", Path(路径).read_text(encoding="utf-8"))
            self.assertNotIn("xxx", Path(路径).read_text(encoding="utf-8"))
            归档 = [n for n in 文件 if n not in ("robot-error.log", 旧归档.name)]
            self.assertEqual(Path(db目录, 归档[0]).read_text(encoding="utf-8"), "x" * 200)


if __name__ == "__main__":
    unittest.main()


class 第二批审查修正测试(unittest.TestCase):
    def test_YOLO检测器保持原始阈值且不做全局跨类去重(self):
        from 模块.检测.YOLO检测器.yolo import 线程安全YOLO检测器 as 检测器类
        self.assertEqual(检测器类.默认置信度阈值, 0.25)
        源码 = inspect.getsource(检测器类.检测)
        self.assertNotIn("跨类别重叠框去重(", 源码)

    def test_敌方资源上限按线上数据放行真实大鱼并拦截十倍误读(self):
        from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务 as 任务类
        # 线上真实读数：金币 3,450,179 / 圣水 3,357,185 / 黑油 28,000 级
        self.assertFalse(任务类.是否存在资源异常上限(3_450_179, 3_357_185, 28_000))
        # 线上明确误读：圣水 19,291,248；金币 5,228,051；黑油错行 2,087,305
        self.assertTrue(任务类.是否存在资源异常上限(500_000, 19_291_248, 5_000))
        self.assertTrue(任务类.是否存在资源异常上限(5_228_051, 500_000, 5_000))
        self.assertTrue(任务类.是否存在资源异常上限(2_088, 383, 2_087_305))

    def test_下一场画面轮询不超过每秒约两帧(self):
        from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务 as 任务类
        self.assertGreaterEqual(任务类.下一场轮询间隔秒, 0.5)

    def test_每个新连接都设置synchronous为NORMAL(self):
        import sqlite3
        from 数据库.任务数据库 import 任务数据库
        with tempfile.TemporaryDirectory() as 目录:
            库 = 任务数据库(os.path.join(目录, "t.db"))
            for _ in range(2):
                with 库._获取连接() as conn:
                    self.assertEqual(conn.execute("PRAGMA synchronous").fetchone()[0], 1)
                    self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")


class 进程资源指标真实采集测试(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "仅 Windows")
    def test_Windows下真实采集到内存与句柄数(self):
        from 线程.自动化机器人 import _采集进程资源指标
        指标 = _采集进程资源指标()
        self.assertIsNotNone(指标["rss_mb"])
        self.assertGreater(指标["rss_mb"], 0)
        self.assertIsNotNone(指标["private_mb"])
        self.assertGreater(指标["handles"] or 0, 0)
