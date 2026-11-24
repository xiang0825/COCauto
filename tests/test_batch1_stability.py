"""第一批稳定性止血修复（P0-1/P0-2/P1-1/P0-3/P1-8）单元测试与集成测试。"""
from __future__ import annotations

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
from unittest.mock import Mock, patch

import numpy as np

from 主入口 import 停止所有活跃机器人
from 核心.异常 import 主机内存保护暂停请求, 机器人停止请求
from 核心.核心异常们 import 图像获取失败
from 数据库.任务数据库 import 任务数据库, 机器人设置
from 模块.ADB设备操作类 import ADB设备操作类, ADB错误
from 任务流程.基础任务框架 import 任务上下文
from 任务流程.建筑升级 import 建筑升级任务
from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务
from 线程.自动化机器人 import 自动化机器人


class 内存保护可恢复与阈值配置测试(unittest.TestCase):
    def test_主机内存保护暂停请求不被Exception和SystemExit吞掉(self):
        self.assertTrue(issubclass(主机内存保护暂停请求, BaseException))
        self.assertFalse(issubclass(主机内存保护暂停请求, Exception))
        self.assertFalse(issubclass(主机内存保护暂停请求, SystemExit))

        with self.assertRaises(主机内存保护暂停请求):
            try:
                raise 主机内存保护暂停请求("内存不足")
            except Exception:
                self.fail("不应被 except Exception 吞掉")
            except SystemExit:
                self.fail("不应被 except SystemExit 误当作退出请求")

    def test_可恢复内存保护不置停止事件且停止事件优先于内存保护(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.机器人标志 = "robot_1"
        上下文.停止事件 = threading.Event()
        上下文.继续事件 = threading.Event()
        上下文.继续事件.set()
        上下文.内存保护标志 = threading.Event()
        上下文.置脚本状态 = Mock()
        上下文.释放识别模型 = Mock()
        上下文.op = SimpleNamespace(检查主机内存预算=Mock(return_value=(False, "提交额度不足")))

        上下文.触发内存保护("截图", ADB错误("主机内存保护已触发：可用提交额度900MB"))

        self.assertTrue(上下文._内存保护已触发)
        self.assertTrue(上下文._主机内存保护可恢复)
        self.assertTrue(上下文.内存保护标志.is_set())
        self.assertFalse(上下文.停止事件.is_set())

        with self.assertRaises(主机内存保护暂停请求):
            上下文.脚本延时(50)

        # 人工停止优先级高于内存保护
        上下文.停止事件.set()
        with self.assertRaises(机器人停止请求):
            上下文.脚本延时(50)

    def test_内存保护提交额度阈值可配置且兼容旧配置(self):
        默认设置 = 机器人设置()
        self.assertEqual(默认设置.内存保护提交额度阈值MB, 1536)

        with tempfile.TemporaryDirectory() as 临时目录:
            数据库路径 = str(Path(临时目录) / "任务系统.db")
            数据库 = 任务数据库(数据库路径)
            数据库.保存机器人设置("robot_legacy", 机器人设置())
            连接 = sqlite3.connect(数据库路径)
            try:
                旧数据 = json.loads(
                    连接.execute(
                        "SELECT 设置JSON FROM 机器人设置 WHERE 机器人标志=?",
                        ("robot_legacy",),
                    ).fetchone()[0]
                )
                for 新字段 in (
                    "内存保护提交额度阈值MB",
                    "最大搜索次数",
                    "最长搜索分钟",
                    "YOLO连续失败熔断次数",
                    "未知页面待命通知秒数",
                ):
                    旧数据.pop(新字段, None)
                连接.execute(
                    "UPDATE 机器人设置 SET 设置JSON=? WHERE 机器人标志=?",
                    (json.dumps(旧数据), "robot_legacy"),
                )
                连接.commit()
            finally:
                连接.close()

            加载旧设置 = 数据库.获取机器人设置("robot_legacy")
            self.assertEqual(加载旧设置.内存保护提交额度阈值MB, 1536)
            self.assertEqual(加载旧设置.最大搜索次数, 150)
            self.assertEqual(加载旧设置.最长搜索分钟, 15)
            self.assertEqual(加载旧设置.YOLO连续失败熔断次数, 10)
            self.assertEqual(加载旧设置.未知页面待命通知秒数, 180)

        with patch.object(ADB设备操作类, "解析ADB路径", return_value="adb.exe"):
            设备 = ADB设备操作类(
                "adb.exe",
                "emulator-5554",
                自动检测路径=False,
                内存保护提交额度阈值MB=2048,
            )
        with patch.object(
            设备,
            "_获取主机内存状态",
            return_value={
                "内存负载": 60,
                "可用物理内存": 4096 * 1024 * 1024,
                "可用提交额度": 1800 * 1024 * 1024,
            },
        ):
            健康, 诊断 = 设备.检查主机内存预算(强制刷新=True)

        self.assertFalse(健康)
        self.assertIn("主机内存保护已触发", 诊断)

    def test_任务流程触发内存保护后待命恢复并继续执行下一轮(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "robot_mem"
        机器人.停止事件 = threading.Event()
        机器人.继续事件 = threading.Event()
        机器人.继续事件.set()
        机器人.停止原因 = ""
        机器人.记录日志 = Mock()
        设置 = 机器人设置(任务计划顺序=["main_resource"], 是否刷主世界=True)
        机器人.数据库 = SimpleNamespace(获取机器人设置=Mock(return_value=设置))

        主页 = SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.85)
        预算状态 = iter([
            (False, "主机内存保护已触发：可用提交额度900MB"),
            (True, "健康1"),
            (True, "健康2"),
            (True, "健康3"),
        ])

        上下文 = 任务上下文.__new__(任务上下文)
        上下文.机器人标志 = "robot_mem"
        上下文.数据库 = 机器人.数据库
        上下文.消息队列 = queue.Queue()
        上下文.停止事件 = 机器人.停止事件
        上下文.继续事件 = 机器人.继续事件
        上下文.内存保护标志 = threading.Event()
        上下文.置脚本状态 = Mock()
        上下文.释放识别模型 = Mock()
        上下文.页面恢复失败 = False
        上下文.企业微信通知器 = None
        上下文.上报间隔秒 = 0
        上下文.发送企业微信通知 = Mock()
        上下文.发送死亡通知 = Mock()
        上下文.op = SimpleNamespace(
            检查主机内存预算=Mock(side_effect=lambda 强制刷新=True: next(预算状态)),
            安全清理=Mock(),
            获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8)),
        )
        上下文.识别点击画面 = Mock(side_effect=[主页, 主页])

        机器人._初始化任务上下文 = Mock(return_value=(设置, 上下文, None))
        机器人._任务计划顺序 = Mock(return_value=["main_resource"])
        机器人._同步官方账号数据 = Mock()
        机器人._接管启动时战斗 = Mock(return_value=True)

        执行次数 = 0

        def 模拟执行任务项(任务键, 当前上下文, _检测登录):
            nonlocal 执行次数
            执行次数 += 1
            if 执行次数 == 1:
                当前上下文.触发内存保护(
                    "资源OCR",
                    ADB错误("主机内存保护已触发：可用提交额度900MB"),
                )
                当前上下文.脚本延时(100)
                self.fail("触发可恢复内存保护后应由脚本延时抛出暂停请求")
            机器人.停止("完成恢复验证", 等待=False)
            return True, False

        机器人._执行任务计划项 = Mock(side_effect=模拟执行任务项)

        原始等待 = 机器人.停止事件.wait

        def 快速等待(timeout=None):
            return 原始等待(timeout=0.01)

        with patch.object(机器人.停止事件, "wait", side_effect=快速等待), \
                patch("线程.自动化机器人.检测游戏登录状态任务") as 检测登录, \
                patch("线程.自动化机器人.启动模拟器任务") as 启动模拟器, \
                patch("线程.自动化机器人.检查图像任务") as 检查图像:
            检测登录.return_value.执行.return_value = True
            启动模拟器.return_value.执行.return_value = True
            检查图像.return_value.执行.return_value = True
            机器人._任务流程()

        self.assertEqual(执行次数, 2)
        self.assertEqual(上下文.op.检查主机内存预算.call_count, 4)
        self.assertFalse(上下文._内存保护已触发)
        self.assertFalse(上下文.内存保护标志.is_set())
        self.assertEqual(机器人.停止原因, "完成恢复验证")
        上下文.发送死亡通知.assert_not_called()

    def test_内存保护待命期间人工停止可在两秒内立即退出线程(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "robot_stop"
        机器人.停止事件 = threading.Event()
        机器人.继续事件 = threading.Event()
        机器人.继续事件.set()
        机器人.停止原因 = ""
        机器人.记录日志 = Mock()
        设置 = 机器人设置(任务计划顺序=["main_resource"], 是否刷主世界=True)
        机器人.数据库 = SimpleNamespace(获取机器人设置=Mock(return_value=设置))

        已进入待命 = threading.Event()

        def 模拟检查预算(强制刷新=True):
            已进入待命.set()
            return False, "主机内存保护已触发：可用提交额度800MB"

        上下文 = 任务上下文.__new__(任务上下文)
        上下文.机器人标志 = "robot_stop"
        上下文.数据库 = 机器人.数据库
        上下文.消息队列 = queue.Queue()
        上下文.停止事件 = 机器人.停止事件
        上下文.继续事件 = 机器人.继续事件
        上下文.内存保护标志 = threading.Event()
        上下文.置脚本状态 = Mock()
        上下文.释放识别模型 = Mock()
        上下文.页面恢复失败 = False
        上下文.企业微信通知器 = None
        上下文.上报间隔秒 = 0
        上下文.发送企业微信通知 = Mock()
        上下文.发送死亡通知 = Mock()
        上下文.op = SimpleNamespace(
            检查主机内存预算=Mock(side_effect=模拟检查预算),
            安全清理=Mock(),
        )
        上下文.识别点击画面 = Mock()

        机器人._初始化任务上下文 = Mock(return_value=(设置, 上下文, None))
        机器人._任务计划顺序 = Mock(return_value=["main_resource"])
        机器人._同步官方账号数据 = Mock()
        机器人._接管启动时战斗 = Mock(return_value=True)

        def 模拟截图触发保护(*_参数):
            raise 图像获取失败("ADB 截图失败：主机内存保护已触发：可用提交额度800MB")

        机器人._执行任务计划项 = Mock(side_effect=模拟截图触发保护)

        with patch("线程.自动化机器人.检测游戏登录状态任务") as 检测登录, \
                patch("线程.自动化机器人.启动模拟器任务") as 启动模拟器, \
                patch("线程.自动化机器人.检查图像任务") as 检查图像:
            检测登录.return_value.执行.return_value = True
            启动模拟器.return_value.执行.return_value = True
            检查图像.return_value.执行.return_value = True

            机器人.主线程 = threading.Thread(target=机器人._任务流程, daemon=True)
            机器人.主线程.start()
            self.assertTrue(已进入待命.wait(timeout=2.0), "任务线程未进入内存保护待命")

            开始停止 = time.monotonic()
            机器人.停止("人工停止测试", 等待=True, 超时=2.0)
            耗时 = time.monotonic() - 开始停止

        self.assertFalse(机器人.主线程.is_alive())
        self.assertLess(耗时, 2.0)
        self.assertEqual(机器人.停止原因, "人工停止测试")
        self.assertTrue(机器人.停止事件.is_set())
        上下文.识别点击画面.assert_not_called()


class 搜索敌人上限与熔断测试(unittest.TestCase):
    def _创建搜索任务(self, *, 最大搜索次数=150, 最长搜索分钟=15, 熔断次数=10):
        设置 = SimpleNamespace(
            欲进攻的最小资源=500_000,
            欲进攻资源建筑靠近地图边缘最小比例=0.5,
            是否采集进攻界面图像=False,
            战利品优先级="均衡",
            最大搜索次数=最大搜索次数,
            最长搜索分钟=最长搜索分钟,
            YOLO连续失败熔断次数=熔断次数,
        )
        上下文 = SimpleNamespace(
            机器人标志="robot_search",
            设置=设置,
            停止事件=threading.Event(),
            页面恢复失败=False,
            数据库=SimpleNamespace(获取机器人设置=Mock(return_value=设置)),
            置脚本状态=Mock(),
            脚本延时=Mock(),
            发送企业微信通知=Mock(),
        )
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.上下文 = 上下文
        任务.数据库 = 上下文.数据库
        任务.机器人标志 = "robot_search"
        任务.模板识别 = Mock()
        return 任务, 上下文

    def test_搜索达到最大次数上限后安全退出并通知待命(self):
        任务, 上下文 = self._创建搜索任务(最大搜索次数=3, 最长搜索分钟=15, 熔断次数=10)
        任务.执行单次搜索 = Mock(return_value=False)

        结果 = 任务.执行()

        self.assertFalse(结果)
        self.assertEqual(任务.执行单次搜索.call_count, 3)
        self.assertTrue(上下文.页面恢复失败)
        上下文.发送企业微信通知.assert_called_once()
        self.assertTrue(any(
            "最大搜索次数上限（3次）" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_搜索达到最长时间上限后安全退出并通知待命(self):
        任务, 上下文 = self._创建搜索任务(最大搜索次数=150, 最长搜索分钟=2, 熔断次数=10)
        任务.执行单次搜索 = Mock(return_value=False)
        时钟 = iter([0.0, 10.0, 121.0])

        with patch("任务流程.主世界打鱼.搜索敌人.time.monotonic", side_effect=lambda: next(时钟)):
            结果 = 任务.执行()

        self.assertFalse(结果)
        self.assertEqual(任务.执行单次搜索.call_count, 1)
        self.assertTrue(上下文.页面恢复失败)
        上下文.发送企业微信通知.assert_called_once()
        self.assertTrue(any(
            "最长搜索时间上限（2分钟）" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_YOLO连续异常或零建筑识别触发熔断且中途成功会清零计数(self):
        任务, 上下文 = self._创建搜索任务(最大搜索次数=150, 最长搜索分钟=15, 熔断次数=3)
        上下文.op = SimpleNamespace(
            获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))
        )
        任务.等待下一个按钮出现 = Mock(return_value=True)
        任务.识别当前资源 = Mock(return_value={
            "金币": 100_000, "圣水": 100_000, "黑油": 1_000, "战利品评分": 200_000
        })
        任务.获取自适应资源筛选门槛 = Mock(return_value=(5.0, None, ""))
        任务.打印状态信息 = Mock()
        任务.点击下一个按钮 = Mock(return_value=True)

        # 第1次异常、第2次0建筑、第3次识别到建筑(清零)、第4次0建筑、第5次异常、第6次0建筑 -> 第6次熔断
        有效目标 = [{"类别名称": "金矿", "置信度": 0.9, "裁剪坐标": [10, 10, 40, 40]}]
        任务.检测器 = SimpleNamespace(
            检测=Mock(side_effect=[
                RuntimeError("onnx fail"),
                [],
                有效目标,
                [],
                RuntimeError("onnx fail"),
                [],
            ])
        )

        结果 = 任务.执行()

        self.assertFalse(结果)
        self.assertEqual(任务.检测器.检测.call_count, 6)
        # 第6次触发熔断时不得再点击“下一个”
        self.assertEqual(任务.点击下一个按钮.call_count, 5)
        self.assertTrue(上下文.页面恢复失败)
        上下文.发送企业微信通知.assert_called_once()
        self.assertTrue(any(
            "熔断" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))


class 未知页面待命通知与现场截图测试(unittest.TestCase):
    def test_待命超过三分钟触发一次通知和回调兜底(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "robot_standby"
        机器人.停止事件 = threading.Event()
        机器人.继续事件 = threading.Event()
        机器人.继续事件.set()
        机器人.停止原因 = ""
        机器人.记录日志 = Mock()
        机器人.停止事件.wait = Mock(return_value=False)

        回调记录 = []
        消息队列 = queue.Queue()
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        主页 = SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.80)
        未知页 = SimpleNamespace(页面="未知", 世界=None, 可信度=0.0)

        上下文 = 任务上下文.__new__(任务上下文)
        上下文.机器人标志 = "robot_standby"
        上下文.数据库 = SimpleNamespace(
            获取机器人设置=Mock(return_value=机器人设置(未知页面待命通知秒数=180))
        )
        上下文.消息队列 = 消息队列
        上下文.企业微信通知器 = None
        上下文.待命通知回调 = lambda **kwargs: 回调记录.append(kwargs)
        上下文._点击识别截图 = 图像
        上下文.置脚本状态 = Mock()
        上下文.识别点击画面 = Mock(side_effect=[未知页, 未知页, 未知页, 主页, 主页])

        时钟 = iter([0.0, 100.0, 181.0, 220.0, 230.0, 240.0])

        with tempfile.TemporaryDirectory() as 临时目录:
            原始保存 = 任务上下文.保存待命现场截图并通知

            def 写入临时目录(self_ctx, 原因, 屏幕图像=None, **_kwargs):
                return 原始保存(self_ctx, 原因, 屏幕图像=屏幕图像, 截图目录=临时目录, 最大留图数=50)

            with patch.object(任务上下文, "保存待命现场截图并通知", 写入临时目录), \
                    patch("线程.自动化机器人.time.monotonic", side_effect=lambda: next(时钟)):
                self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))

            保存的文件 = list(Path(临时目录).glob("*.png"))
            self.assertEqual(len(保存的文件), 1)
            self.assertEqual(len(回调记录), 1)
            self.assertEqual(消息队列.qsize(), 1)
            self.assertEqual(消息队列.get_nowait()["类型"], "待命超时通知")

    def test_待命现场截图超过上限时自动裁剪旧图且支持企微发送(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            目录 = Path(临时目录)
            for 序号 in range(52):
                文件 = 目录 / f"old_{序号:03d}.png"
                文件.write_bytes(b"png")
                os.utime(文件, (1000 + 序号, 1000 + 序号))

            通知器 = SimpleNamespace(发送状态消息=Mock(return_value=True))
            上下文 = 任务上下文.__new__(任务上下文)
            上下文.机器人标志 = "robot_cap"
            上下文.企业微信通知器 = 通知器
            上下文.消息队列 = queue.Queue()
            上下文.待命通知回调 = None
            上下文.置脚本状态 = Mock()
            上下文.记录警告 = Mock()

            图像 = np.full((60, 80, 3), 120, dtype=np.uint8)
            保存路径 = 上下文.保存待命现场截图并通知(
                "未知页面待命超3分钟",
                屏幕图像=图像,
                截图目录=目录,
                最大留图数=50,
            )

            self.assertIsNotNone(保存路径)
            self.assertTrue(保存路径.is_file())
            剩余 = sorted(p.name for p in 目录.glob("*.png"))
            self.assertEqual(len(剩余), 50)
            self.assertNotIn("old_000.png", 剩余)
            self.assertNotIn("old_001.png", 剩余)
            self.assertNotIn("old_002.png", 剩余)
            self.assertIn(保存路径.name, 剩余)
            通知器.发送状态消息.assert_called_once()


class 建筑升级收尾复核测试(unittest.TestCase):
    def test_升级提交后确认主世界_连续两帧成功返回True(self):
        上下文 = SimpleNamespace(
            关闭升级详情弹窗=Mock(return_value=True),
            页面恢复失败=False,
            识别点击画面=Mock(side_effect=[
                SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.82),
                SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.85),
            ]),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务 = 建筑升级任务.__new__(建筑升级任务)
        任务.上下文 = 上下文

        self.assertTrue(任务._升级提交后确认主世界())
        上下文.关闭升级详情弹窗.assert_called_once_with()
        self.assertEqual(上下文.识别点击画面.call_count, 2)
        上下文.脚本延时.assert_called_once_with(250)

    def test_升级提交后确认主世界_未连续确认返回False(self):
        上下文 = SimpleNamespace(
            关闭升级详情弹窗=Mock(return_value=False),
            页面恢复失败=False,
            识别点击画面=Mock(side_effect=[
                SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.82),
                SimpleNamespace(页面="升级详情弹窗", 世界="未知", 可信度=0.90),
            ]),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务 = 建筑升级任务.__new__(建筑升级任务)
        任务.上下文 = 上下文

        self.assertFalse(任务._升级提交后确认主世界())
        self.assertEqual(上下文.识别点击画面.call_count, 2)

    def test_建筑升级任务集成执行调用真实收尾函数(self):
        for 主页确认结果, 预期返回 in ((True, True), (False, False)):
            with self.subTest(主页确认结果=主页确认结果):
                页面序列 = (
                    [
                        SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.88),
                        SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.88),
                    ]
                    if 主页确认结果
                    else [
                        SimpleNamespace(页面="未知", 世界=None, 可信度=0.0),
                        SimpleNamespace(页面="未知", 世界=None, 可信度=0.0),
                    ]
                )
                上下文 = SimpleNamespace(
                    设置=机器人设置(
                        欲升级的英雄或建筑=["兵营"],
                        是否升级建议升级的建筑=False,
                        建筑升级检查间隔=0,
                    ),
                    关闭升级详情弹窗=Mock(return_value=False),
                    页面恢复失败=False,
                    识别点击画面=Mock(side_effect=页面序列),
                    脚本延时=Mock(),
                    置脚本状态=Mock(),
                    请求任务计划等待=Mock(),
                    机器人标志="robot_build",
                )
                数据库 = Mock(
                    获取最新完整状态=Mock(return_value=SimpleNamespace(状态数据={})),
                    更新状态=Mock(),
                )
                任务 = 建筑升级任务.__new__(建筑升级任务)
                任务.上下文 = 上下文
                任务.数据库 = 数据库
                任务.机器人标志 = "robot_build"
                任务._清理残留研究目标页 = Mock(return_value=True)

                with patch("任务流程.建筑升级.更新工人状态任务") as 工人状态, \
                     patch("任务流程.建筑升级.寻找建筑") as 寻找, \
                     patch("任务流程.建筑升级.升级普通建筑任务") as 升级建筑:
                    工人状态.return_value.执行.return_value = True
                    工人状态.return_value.是否有空闲工人.return_value = True
                    寻找.return_value.执行.return_value = True
                    寻找.return_value.当前建筑 = "兵营"
                    升级建筑.return_value.执行.return_value = True

                    self.assertEqual(任务.执行(), 预期返回)


class 线程停止超时测试(unittest.TestCase):
    def test_停止方法调用带超时join且卡死线程不会无限阻塞(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "robot_hang"
        机器人.停止事件 = threading.Event()
        机器人.继续事件 = threading.Event()
        机器人.继续事件.set()
        机器人.停止原因 = ""
        机器人.记录日志 = Mock()

        释放门 = threading.Event()
        try:
            卡死线程 = threading.Thread(target=lambda: 释放门.wait(timeout=5.0), daemon=True)
            卡死线程.start()
            机器人.主线程 = 卡死线程

            开始 = time.monotonic()
            机器人.停止("超时停止测试", 等待=True, 超时=0.1)
            耗时 = time.monotonic() - 开始

            self.assertLess(耗时, 1.0)
            self.assertTrue(卡死线程.is_alive())
            self.assertTrue(any(
                "超时" in 调用.args[0]
                for 调用 in 机器人.记录日志.call_args_list
            ))
        finally:
            释放门.set()

    def test_停止方法默认join超时为10秒(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "robot_default_timeout"
        机器人.停止事件 = threading.Event()
        机器人.继续事件 = threading.Event()
        机器人.继续事件.set()
        机器人.停止原因 = ""
        机器人.记录日志 = Mock()
        机器人.主线程 = SimpleNamespace(
            is_alive=Mock(side_effect=[True, False]),
            join=Mock(),
        )

        机器人.停止("默认超时测试")

        机器人.主线程.join.assert_called_once_with(timeout=10.0)

    def test_主入口停止所有活跃机器人使用超时join(self):
        释放门 = threading.Event()
        try:
            卡死线程 = threading.Thread(target=lambda: 释放门.wait(timeout=5.0), daemon=True)
            卡死线程.start()
            假机器人 = SimpleNamespace(
                主线程=卡死线程,
                停止=Mock(),
            )
            假监控 = SimpleNamespace(
                运行标志=True,
                机器人池={"robot_1": 假机器人},
            )

            开始 = time.monotonic()
            超时列表 = 停止所有活跃机器人(假监控, 超时秒=0.1)
            耗时 = time.monotonic() - 开始

            self.assertFalse(假监控.运行标志)
            self.assertEqual(超时列表, ["robot_1"])
            self.assertLess(耗时, 1.0)
            假机器人.停止.assert_called_once_with("手动终止", 等待=False)
        finally:
            释放门.set()


if __name__ == "__main__":
    unittest.main()
