import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from 应用.任务计划 import 应用参数, 所有参数字段
from 数据库.任务数据库 import 任务数据库, 机器人设置
from 核心.ADB屏幕 import ADB屏幕
from 模块.ADB设备操作类 import ADB设备操作类
from 模块.运行节流与复盘 import (
    低星战局复盘记录器,
    尝试满仓顺手刷墙,
    模型空闲释放协调器,
    检查是否存在可用工人,
    金水是否达到刷墙阈值,
)
from 模块.防休眠 import ES_CONTINUOUS, ES_SYSTEM_REQUIRED, 防休眠控制器
from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务
from 任务流程.升级城墙 import 城墙升级任务
from 任务流程.基础任务框架 import 任务上下文, 基础任务
from 线程.自动化机器人 import 自动化机器人


def _构造测试帧(填充值: int = 120) -> np.ndarray:
    图像 = np.full((600, 800, 3), 填充值, dtype=np.uint8)
    return 图像


class _测试OCR包装:
    def __init__(self):
        self.已释放 = False

    def 释放模型(self):
        self.已释放 = True

    def __call__(self, *args, **kwargs):
        return [], None


class _测试YOLO包装:
    def __init__(self):
        self.已释放 = False

    def 释放模型(self):
        self.已释放 = True


class _空基础任务(基础任务):
    def 执行(self) -> bool:
        return True


class 防系统休眠测试(unittest.TestCase):
    def test_防休眠启停与幂等及异常安全恢复(self):
        调用历史: list[int] = []
        日志列表: list[str] = []
        控制器 = 防休眠控制器(
            执行状态函数=lambda 标志: 调用历史.append(标志) or 1,
            平台名称="win32",
            日志回调=日志列表.append,
        )

        self.assertTrue(控制器.保持唤醒())
        self.assertTrue(控制器.当前已阻止休眠)
        # 同一线程重复调用应幂等，不重复刷 Win32 API
        self.assertTrue(控制器.保持唤醒())
        self.assertEqual(调用历史, [ES_CONTINUOUS | ES_SYSTEM_REQUIRED])

        self.assertTrue(控制器.允许休眠())
        self.assertFalse(控制器.当前已阻止休眠)
        self.assertEqual(
            调用历史,
            [ES_CONTINUOUS | ES_SYSTEM_REQUIRED, ES_CONTINUOUS],
        )

        # 上下文管理器即使发生异常也必须恢复 ES_CONTINUOUS
        with self.assertRaises(RuntimeError):
            with 控制器:
                self.assertTrue(控制器.当前已阻止休眠)
                raise RuntimeError("模拟任务异常")
        self.assertFalse(控制器.当前已阻止休眠)
        self.assertEqual(调用历史[-1], ES_CONTINUOUS)

    def test_非Windows或后端异常静默降级不抛异常(self):
        linux控制器 = 防休眠控制器(平台名称="linux")
        self.assertFalse(linux控制器.平台支持)
        self.assertFalse(linux控制器.保持唤醒())
        self.assertFalse(linux控制器.当前已阻止休眠)
        self.assertTrue(linux控制器.允许休眠())

        日志: list[str] = []

        def _抛错API(_标志):
            raise OSError("API unavailable")

        故障控制器 = 防休眠控制器(
            执行状态函数=_抛错API,
            平台名称="win32",
            日志回调=日志.append,
        )
        self.assertFalse(故障控制器.保持唤醒())
        self.assertFalse(故障控制器.当前已阻止休眠)
        self.assertTrue(any("设置系统防休眠状态失败" in 项 for 项 in 日志))

    def test_自动化机器人暂停继续与异常退出均恢复防休眠(self):
        调用历史: list[int] = []
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "bot_sleep"
        机器人.停止事件 = threading.Event()
        机器人.继续事件 = threading.Event()
        机器人.继续事件.set()
        机器人.记录日志 = Mock()
        机器人.置脚本状态 = Mock()
        机器人._防休眠控制器 = 防休眠控制器(
            执行状态函数=lambda 标志: 调用历史.append(标志) or 1,
            平台名称="win32",
        )

        机器人._防休眠控制器.保持唤醒()
        self.assertTrue(机器人._防休眠控制器.当前已阻止休眠)

        机器人.暂停()
        self.assertFalse(机器人.继续事件.is_set())
        self.assertFalse(机器人._防休眠控制器.当前已阻止休眠)
        self.assertEqual(调用历史[-1], ES_CONTINUOUS)

        机器人.继续()
        self.assertTrue(机器人.继续事件.is_set())
        self.assertTrue(机器人._防休眠控制器.当前已阻止休眠)
        self.assertEqual(调用历史[-1], ES_CONTINUOUS | ES_SYSTEM_REQUIRED)

        # 验证 _任务流程 异常退出时 finally 恢复 ES_CONTINUOUS
        上下文 = SimpleNamespace(
            op=SimpleNamespace(安全清理=Mock(), 获取屏幕图像cv=Mock()),
            释放识别模型=Mock(),
            _内存保护已触发=True,
            发送死亡通知=Mock(),
            置脚本状态=Mock(),
        )
        机器人.停止原因 = ""
        机器人._桌面通知线程停止 = Mock()
        机器人._写入未处理异常日志 = Mock()
        机器人._初始化任务上下文 = Mock(return_value=(机器人设置(), 上下文, None))

        with patch("线程.自动化机器人.检测游戏登录状态任务", side_effect=RuntimeError("boom")):
            机器人._任务流程()

        self.assertFalse(机器人._防休眠控制器.当前已阻止休眠)
        self.assertEqual(调用历史[-1], ES_CONTINUOUS)


class 动态降帧节能测试(unittest.TestCase):
    def test_ADB屏幕按活跃与低频场景动态调节缓存间隔(self):
        当前单调 = [100.0]

        class _假设备(ADB设备操作类):
            def __init__(self):
                self.参考宽度 = 800
                self.参考高度 = 600
                self.截图次数 = 0

            def 获取屏幕图像cv(self, *args, **kwargs):
                self.截图次数 += 1
                return _构造测试帧(self.截图次数 * 20)

        设备 = _假设备()
        屏幕 = ADB屏幕(设备)
        self.assertAlmostEqual(屏幕.获取最短截图间隔秒(), 0.50)

        with patch("time.monotonic", side_effect=lambda: 当前单调[0]):
            # 活跃场景默认 0.50s
            屏幕.获取屏幕图像cv()
            self.assertEqual(设备.截图次数, 1)
            当前单调[0] += 0.30
            屏幕.获取屏幕图像cv()
            self.assertEqual(设备.截图次数, 1)
            当前单调[0] += 0.30
            屏幕.获取屏幕图像cv()
            self.assertEqual(设备.截图次数, 2)

            # 切换低频场景（1.5~2.0s）
            新间隔 = 屏幕.设置截图节流场景("满仓待机")
            self.assertGreaterEqual(新间隔, 1.5)
            self.assertLessEqual(新间隔, 2.0)

            当前单调[0] += 1.00
            屏幕.获取屏幕图像cv()
            self.assertEqual(设备.截图次数, 2)  # 低频复用缓存，减少 screencap

            # 强制刷新（例如确认点击）绝不复用旧帧
            屏幕.获取屏幕图像cv(强制刷新=True)
            self.assertEqual(设备.截图次数, 3)

            当前单调[0] += 1.90
            屏幕.获取屏幕图像cv()
            self.assertEqual(设备.截图次数, 4)

            # 切回活跃场景（搜敌/下兵/确认点击）
            恢复间隔 = 屏幕.设置截图节流场景("搜敌")
            self.assertAlmostEqual(恢复间隔, 0.50)
            self.assertEqual(屏幕.获取当前节流场景(), "活跃")

    def test_任务上下文场景切换同步调节点击识别缓存窗口(self):
        当前单调 = [200.0]
        设备 = SimpleNamespace(
            参考宽度=800,
            参考高度=600,
            获取屏幕图像cv=Mock(side_effect=lambda *a, **k: _构造测试帧()),
        )
        # 使 isinstance 检查或鸭子类型均可正常工作
        屏幕 = ADB屏幕.__new__(ADB屏幕)
        屏幕.设备 = 设备
        屏幕.是否已绑定 = True
        屏幕._原始截图缓存 = None
        屏幕._原始截图缓存时间 = 0.0
        屏幕._日志回调 = None
        屏幕._已告警分辨率 = set()
        屏幕._默认最短截图间隔秒 = 0.50
        屏幕._最短截图间隔秒 = 0.50
        屏幕._当前节流场景 = "活跃"

        上下文 = object.__new__(任务上下文)
        上下文.op = 屏幕
        上下文._战斗中 = False

        with patch("time.monotonic", side_effect=lambda: 当前单调[0]):
            上下文.设置运行节流场景("战斗等待")
            self.assertEqual(上下文._运行节流场景, "低频")
            self.assertGreaterEqual(屏幕.获取最短截图间隔秒(), 1.5)

            上下文._获取点击识别截图()
            self.assertEqual(设备.获取屏幕图像cv.call_count, 1)
            当前单调[0] += 1.00
            上下文._获取点击识别截图()
            self.assertEqual(设备.获取屏幕图像cv.call_count, 1)

            上下文.设置运行节流场景("确认点击")
            self.assertEqual(上下文._运行节流场景, "活跃")
            self.assertAlmostEqual(屏幕.获取最短截图间隔秒(), 0.50)
            上下文._获取点击识别截图(强制=True)
            self.assertEqual(设备.获取屏幕图像cv.call_count, 2)


class 模型空闲懒释放测试(unittest.TestCase):
    def test_连续打鱼短间隔不释放模型且空闲超阈值才释放(self):
        当前单调 = [1000.0]
        上下文 = object.__new__(任务上下文)
        上下文.机器人标志 = "bot_lazy"
        设置 = 机器人设置(模型空闲释放秒数=600)
        上下文.数据库 = SimpleNamespace(获取机器人设置=lambda _: 设置)
        上下文.置脚本状态 = Mock()
        上下文.op = SimpleNamespace(检查主机内存预算=Mock(return_value=(True, "预算充足")))
        OCR = _测试OCR包装()
        YOLO = _测试YOLO包装()
        上下文._共享OCR引擎 = OCR
        上下文._共享YOLO检测器 = YOLO
        上下文._模型释放版本号 = 0

        with patch("time.monotonic", side_effect=lambda: 当前单调[0]):
            上下文.标记模型使用("YOLO")
            任务 = _空基础任务(上下文)
            任务.__dict__["ocr引擎"] = OCR
            任务.__dict__["_ocr引擎关联版本"] = 0

            # 120 秒（正常连续打鱼间隙 < 600s）不释放
            当前单调[0] += 120.0
            已释放, _ = 上下文.检查空闲或内存释放识别模型()
            self.assertFalse(已释放)
            self.assertFalse(OCR.已释放)
            self.assertFalse(YOLO.已释放)

            # 再次使用模型刷新空闲计时（120 + 500 = 620，但中间被刷新过，距离上次仅 500s）
            上下文.标记模型使用("OCR")
            当前单调[0] += 500.0
            已释放, _ = 上下文.检查空闲或内存释放识别模型()
            self.assertFalse(已释放)
            self.assertIsNotNone(上下文._共享OCR引擎)

            # 空闲达到 >= 600s 触发懒释放
            当前单调[0] += 105.0
            已释放, 原因 = 上下文.检查空闲或内存释放识别模型()
            self.assertTrue(已释放)
            self.assertIn("懒释放", 原因)
            self.assertTrue(OCR.已释放)
            self.assertTrue(YOLO.已释放)
            self.assertIsNone(上下文._共享OCR引擎)
            self.assertIsNone(上下文._共享YOLO检测器)
            self.assertEqual(上下文._模型释放版本号, 1)

            # 长寿命任务缓存应在下次读取 ocr引擎 时自动失效并重获新引擎
            新OCR = _测试OCR包装()
            with patch.object(上下文, "获取OCR引擎", return_value=新OCR) as mock_get:
                self.assertIs(任务.ocr引擎, 新OCR)
                mock_get.assert_called_once()

    def test_主机内存预算紧张时即使未达空闲阈值也立即释放(self):
        当前单调 = [500.0]
        上下文 = object.__new__(任务上下文)
        上下文.机器人标志 = "bot_mem"
        设置 = 机器人设置(模型空闲释放秒数=0)  # 即使关闭定时空闲，内存紧张仍应立即释放
        上下文.数据库 = SimpleNamespace(获取机器人设置=lambda _: 设置)
        上下文.置脚本状态 = Mock()
        上下文.op = SimpleNamespace(
            检查主机内存预算=Mock(return_value=(False, "可用提交额度不足 512MB"))
        )
        OCR = _测试OCR包装()
        YOLO = _测试YOLO包装()
        上下文._共享OCR引擎 = OCR
        上下文._共享YOLO检测器 = YOLO

        with patch("time.monotonic", side_effect=lambda: 当前单调[0]):
            上下文.标记模型使用("OCR")
            当前单调[0] += 2.0
            已释放, 原因 = 上下文.检查空闲或内存释放识别模型()

        self.assertTrue(已释放)
        self.assertIn("内存", 原因)
        self.assertTrue(OCR.已释放)
        self.assertTrue(YOLO.已释放)
        self.assertIsNone(上下文._共享OCR引擎)
        self.assertIsNone(上下文._共享YOLO检测器)


class 连续低星自动留档测试(unittest.TestCase):
    def test_连续两场低星触发留档且胜场重置计数并严格不删旧图(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            目录 = Path(临时目录) / "低星复盘"
            日志: list[str] = []
            记录器 = 低星战局复盘记录器(目录, 连续触发次数=2, 摧毁率阈值=30, 最大留档数=2)
            截图 = _构造测试帧(88)

            # 第 1 场 0 星：未达连续 2 场，不留档
            路径1 = 记录器.记录战局(
                屏幕图像=截图, 星数=0, 摧毁率=42, 结果="失败", 日志回调=日志.append
            )
            self.assertIsNone(路径1)
            self.assertEqual(记录器.连续低星次数, 1)

            # 接着赢 1 场（1 星 55%）：重置连续计数
            路径胜利 = 记录器.记录战局(
                屏幕图像=截图, 星数=1, 摧毁率=55, 结果="胜利", 日志回调=日志.append
            )
            self.assertIsNone(路径胜利)
            self.assertEqual(记录器.连续低星次数, 0)

            # 连续两场低表现：先 0 星，再 1 星但摧毁率 < 30%
            self.assertIsNone(
                记录器.记录战局(屏幕图像=截图, 星数=0, 摧毁率=35, 结果="失败")
            )
            归档1 = 记录器.记录战局(
                屏幕图像=截图,
                星数=1,
                摧毁率=24,
                结果="失败",
                日志回调=日志.append,
                时间文本="20261125_120000_001",
            )
            self.assertIsNotNone(归档1)
            self.assertTrue(归档1.exists())
            self.assertIn("20261125_120000_001", 归档1.name)
            self.assertIn("_s1_d24_", 归档1.name)

            # 第 3 场仍低星 -> 写入第 2 张（达到最大留档数 2）
            归档2 = 记录器.记录战局(
                屏幕图像=截图,
                星数=0,
                摧毁率=12,
                结果="失败",
                日志回调=日志.append,
                时间文本="20261125_120100_002",
            )
            self.assertIsNotNone(归档2)
            self.assertTrue(归档2.exists())

            # 再来第 4 场低星：已达上限 2，应停止写入且绝对不删除归档1/归档2
            归档3 = 记录器.记录战局(
                屏幕图像=截图,
                星数=0,
                摧毁率=5,
                结果="失败",
                日志回调=日志.append,
                时间文本="20261125_120200_003",
            )
            self.assertIsNone(归档3)
            现有文件 = sorted(p.name for p in 目录.glob("*.png"))
            self.assertEqual(len(现有文件), 2)
            self.assertTrue(归档1.exists())
            self.assertTrue(归档2.exists())
            self.assertTrue(any("不执行删除" in 项 for 项 in 日志))

    def test_回营记录战斗结果连续两场低星自动写入复盘目录(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            目录 = Path(临时目录) / "低星复盘"
            数据库 = 任务数据库(str(Path(临时目录) / "test.db"))
            任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
            任务.上下文 = SimpleNamespace(
                机器人标志="bot_review",
                数据库=数据库,
                置脚本状态=Mock(),
                本场目标战利品={},
                本场资源易窃取评分=6.0,
                本场资源评估={},
                本场资源评分状态="已知",
                本场资源评分说明="",
                英雄技能状态={},
                _低星复盘记录器=低星战局复盘记录器(目录),
            )
            任务._画面仍在战斗 = Mock(return_value=False)
            任务.识别结算帧 = Mock(
                side_effect=[([], "", "失败", 18), ([], "", "失败", 22)]
            )
            任务.识别星数 = Mock(side_effect=[0, 0])
            任务.合并本场摧毁率 = Mock(side_effect=lambda d, _rt: d)
            任务.校正三星摧毁率 = Mock(side_effect=lambda r, s, d, **kw: d)
            任务.校正星数 = Mock(side_effect=lambda r, s, d: s)
            任务.星数校正说明 = Mock(return_value="")
            任务.生成战斗诊断 = Mock(return_value="低摧毁")
            任务.更新战斗学习 = Mock(return_value=None)

            截图 = _构造测试帧(66)
            self.assertTrue(任务.记录战斗结果(任务.上下文, 截图, True))
            self.assertEqual(list(目录.glob("*.png")), [])

            self.assertTrue(任务.记录战斗结果(任务.上下文, 截图, True))
            文件列表 = list(目录.glob("*.png"))
            self.assertEqual(len(文件列表), 1)
            self.assertIn("_s0_d22_", 文件列表[0].name)


class 满仓顺手刷墙策略测试(unittest.TestCase):
    def test_默认开关关闭与配置参数校验边界(self):
        默认 = 机器人设置()
        self.assertFalse(默认.满仓自动顺手刷墙)
        self.assertEqual(默认.刷墙资源阈值比例, 90)
        self.assertEqual(默认.单次顺手刷墙上限, 2)
        self.assertEqual(默认.模型空闲释放秒数, 600)

        越界 = 机器人设置(
            满仓自动顺手刷墙=1,
            刷墙资源阈值比例=150,
            单次顺手刷墙上限=9,
            模型空闲释放秒数=-5,
        )
        self.assertTrue(越界.满仓自动顺手刷墙)
        self.assertEqual(越界.刷墙资源阈值比例, 100)
        self.assertEqual(越界.单次顺手刷墙上限, 2)
        self.assertEqual(越界.模型空闲释放秒数, 0)

        字段映射 = {项.字段: 项 for 项 in 所有参数字段()}
        self.assertIn("满仓自动顺手刷墙", 字段映射)
        self.assertIn("刷墙资源阈值比例", 字段映射)
        self.assertIn("单次顺手刷墙上限", 字段映射)
        self.assertIn("模型空闲释放秒数", 字段映射)

        设置 = 机器人设置()
        已应用 = 应用参数(
            设置,
            "resource_policy",
            {"满仓自动顺手刷墙": True, "刷墙资源阈值比例": "85", "单次顺手刷墙上限": "1"},
        )
        self.assertEqual(
            set(已应用),
            {"满仓自动顺手刷墙", "刷墙资源阈值比例", "单次顺手刷墙上限"},
        )
        self.assertTrue(设置.满仓自动顺手刷墙)
        self.assertEqual(设置.刷墙资源阈值比例, 85)
        self.assertEqual(设置.单次顺手刷墙上限, 1)
        with self.assertRaises(ValueError):
            应用参数(设置, "resource_policy", {"单次顺手刷墙上限": "3"})

    def test_刷墙阈值与工人可用性边界条件(self):
        # 历史已知 20M 上限，18.2M (91%) >= 90%，17M (85%) < 90%
        历史 = {"金币": 20_000_000, "圣水": 20_000_000}
        self.assertTrue(
            金水是否达到刷墙阈值({"金币": 18_200_000, "圣水": 5_000_000, "识别成功": True}, 90, 历史)[0]
        )
        self.assertFalse(
            金水是否达到刷墙阈值({"金币": 17_000_000, "圣水": 17_000_000, "识别成功": True}, 90, 历史)[0]
        )

        with tempfile.TemporaryDirectory() as 临时目录:
            数据库 = 任务数据库(str(Path(临时目录) / "workers.db"))
            上下文 = SimpleNamespace(机器人标志="bot_w", 数据库=数据库, op=None)

            # 0 空闲工人 -> 不可用
            数据库.更新状态("bot_w", "工人状态", {"空闲工人": 0, "工人总数": 5, "更新时间": time.time()})
            可用, _ = 检查是否存在可用工人(上下文, 允许刷新=False)
            self.assertFalse(可用)

            # 哥布林 1/7 假空闲 -> 不可用
            数据库.更新状态("bot_w", "工人状态", {"空闲工人": 1, "工人总数": 7, "更新时间": time.time()})
            可用, 原因 = 检查是否存在可用工人(上下文, 允许刷新=False)
            self.assertFalse(可用)
            self.assertIn("哥布林", 原因)

            # 真实空闲工人 1/5 -> 可用
            数据库.更新状态("bot_w", "工人状态", {"空闲工人": 1, "工人总数": 5, "更新时间": time.time()})
            可用, _ = 检查是否存在可用工人(上下文, 允许刷新=False)
            self.assertTrue(可用)

    def test_满仓顺手刷墙开关控制与上限及异常安全跳过(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            数据库 = 任务数据库(str(Path(临时目录) / "wall_opt.db"))
            数据库.更新状态("bot_wall", "工人状态", {"空闲工人": 2, "工人总数": 5, "更新时间": time.time()})
            资源 = {"金币": 20_000_000, "圣水": 20_000_000, "黑油": 300_000, "识别成功": True}

            # 1. 默认关闭时不触发
            机器人关 = SimpleNamespace(设置=机器人设置(满仓自动顺手刷墙=False))
            上下文 = SimpleNamespace(
                机器人标志="bot_wall",
                数据库=数据库,
                停止事件=threading.Event(),
                置脚本状态=Mock(),
                设置=机器人关.设置,
            )
            假墙任务类 = Mock()
            self.assertFalse(尝试满仓顺手刷墙(机器人关, 上下文, 资源, 墙任务类=假墙任务类))
            假墙任务类.assert_not_called()

            # 2. 开启开关且即使主开关 开启刷墙=False，仍应按 1~2 块上限执行
            设置开 = 机器人设置(开启刷墙=False, 满仓自动顺手刷墙=True, 单次顺手刷墙上限=2)
            数据库.保存机器人设置("bot_wall", 设置开)
            机器人开 = SimpleNamespace(设置=设置开)
            上下文.设置 = 设置开

            # 用真实 城墙升级任务 验证最大升级块数=2 与忽略开关
            真实墙任务 = 城墙升级任务(上下文, 最大升级块数=2, 忽略开关=True)
            真实墙任务.刷一次墙 = Mock(return_value=True)
            self.assertTrue(真实墙任务.执行())
            self.assertEqual(真实墙任务.刷一次墙.call_count, 2)
            self.assertEqual(上下文._本次顺手刷墙成功块数, 2)

            # 3. 墙任务抛异常时安全跳过且不阻塞主流程，也不残留 刷墙需要资源
            def _故障任务(*args, **kwargs):
                obj = SimpleNamespace()
                def _boom(**_kw):
                    上下文.刷墙需要资源 = True
                    raise RuntimeError("模拟墙面板识别异常")
                obj.执行 = _boom
                return obj

            上下文.刷墙需要资源 = False
            self.assertFalse(尝试满仓顺手刷墙(机器人开, 上下文, 资源, 墙任务类=_故障任务))
            self.assertFalse(上下文.刷墙需要资源)

    def test_主世界刷资源满仓处触发顺手刷墙并在资源下降后继续打鱼(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            数据库 = 任务数据库(str(Path(临时目录) / "main_loop.db"))
            设置 = 机器人设置(
                开启刷墙=False,
                满仓自动顺手刷墙=True,
                刷墙资源阈值比例=90,
                单次顺手刷墙上限=2,
                资源打满后动作="退出",
                黑油储存上限=500_000,
            )
            数据库.保存机器人设置("bot_farm", 设置)
            数据库.更新状态("bot_farm", "工人状态", {"空闲工人": 2, "工人总数": 5, "更新时间": time.time()})
            数据库.更新状态(
                "bot_farm",
                "家乡资源",
                {"金币": 20_000_000, "圣水": 20_000_000, "黑油": 500_000, "识别成功": True},
            )

            机器人 = 自动化机器人.__new__(自动化机器人)
            机器人.机器人标志 = "bot_farm"
            机器人.数据库 = 数据库
            机器人.停止事件 = threading.Event()
            机器人._进入并确认主世界 = Mock(return_value=True)
            机器人._断线时恢复游戏连接 = Mock(return_value=True)
            机器人._清理残留英雄升级详情 = Mock(return_value=True)
            机器人._打鱼间隙检查部落竞赛 = Mock(return_value=True)
            机器人._战后连续确认主世界主页 = Mock(return_value=True)
            机器人._满仓继续打鱼 = Mock(return_value=False)

            上下文 = SimpleNamespace(
                机器人标志="bot_farm",
                数据库=数据库,
                设置=设置,
                停止事件=机器人.停止事件,
                置脚本状态=Mock(),
                脚本延时=Mock(),
                op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=_构造测试帧())),
                _资源计划已打满=False,
            )
            检测登录 = SimpleNamespace(执行=Mock(return_value=True))

            # 第一次更新资源显示满仓 -> 顺手刷墙后资源下降 -> 发起 1 场进攻并在战后停止
            def _模拟资源更新(_上下文):
                次数 = getattr(_模拟资源更新, "n", 0) + 1
                _模拟资源更新.n = 次数
                if 次数 == 1:
                    数据库.更新状态(
                        "bot_farm",
                        "家乡资源",
                        {"金币": 20_000_000, "圣水": 20_000_000, "黑油": 500_000, "识别成功": True},
                    )
                else:
                    数据库.更新状态(
                        "bot_farm",
                        "家乡资源",
                        {"金币": 15_000_000, "圣水": 16_000_000, "黑油": 500_000, "识别成功": True},
                    )
                return SimpleNamespace(执行=Mock(return_value=True))

            def _模拟打鱼(_上下文):
                机器人.停止事件.set()
                return SimpleNamespace(执行=Mock(return_value=True))

            with patch("线程.自动化机器人.收集资源任务", return_value=SimpleNamespace(执行=Mock(return_value=True))), \
                    patch("线程.自动化机器人.更新家乡资源状态任务", side_effect=_模拟资源更新), \
                    patch("线程.自动化机器人.主世界打鱼任务", side_effect=_模拟打鱼) as mock_attack, \
                    patch("任务流程.升级城墙.城墙升级任务") as mock_wall_cls:
                def _执行刷墙(**kwargs):
                    上下文._本次顺手刷墙成功块数 = 2
                    return True
                mock_wall_cls.return_value.执行.side_effect = _执行刷墙

                机器人._执行主世界刷资源计划(上下文, 检测登录)

            mock_wall_cls.assert_called_once()
            mock_attack.assert_called_once()
            self.assertFalse(上下文._资源计划已打满)


if __name__ == "__main__":
    unittest.main()
