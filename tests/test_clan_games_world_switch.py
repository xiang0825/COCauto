"""部落竞赛：人在夜世界先安全回主世界再看任务；每次跳过写清原因；不接捐兵类任务。"""
import time
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.test_clan_games import (
    假数据库,
    文本_金币,
    文本_黑油,
    文本_夜世界,
    文本_捐兵,
    构造任务,
    模拟游戏,
    配置,
)
from 任务流程.活动.部落竞赛 import 命中不接名单, 识别任务类型, 部落竞赛任务


def 标准卡片():
    卡片 = [dict(文本=文本_夜世界, 积分="150")] * 12
    卡片[8] = dict(文本=文本_金币, 积分="150")
    卡片[11] = dict(文本=文本_黑油, 积分="300")
    return 卡片


def 夜世界识别(游戏):
    def 识别(强制=False):
        if 游戏.状态 == "night":
            return SimpleNamespace(页面="夜世界主页", 世界="夜世界", 可信度=0.74)
        return SimpleNamespace(页面="主世界主页" if 游戏.状态 == "home" else "未知", 世界="主世界")
    return 识别


class 夜世界先回主世界测试(unittest.TestCase):
    def _夜世界任务(self, 回主世界行为):
        游戏 = 模拟游戏(卡片=标准卡片())
        游戏.状态 = "night"
        任务, 上下文, 日志, _, _ = 构造任务(游戏)
        上下文.识别点击画面 = 夜世界识别(游戏)
        调用 = []

        def 回主世界():
            调用.append(游戏.状态)
            return 回主世界行为(游戏, 上下文)

        任务._回主世界 = 回主世界
        return 任务, 上下文, 日志, 游戏, 调用

    def test_夜世界先切回主世界再打开面板接任务(self):
        def 成功(游戏, 上下文):
            游戏.状态 = "home"
            return True

        任务, 上下文, 日志, 游戏, 调用 = self._夜世界任务(成功)
        self.assertTrue(任务.执行())
        self.assertEqual(调用, ["night"])
        self.assertEqual(任务.结果, "已接任务")
        self.assertEqual(游戏.开始点击, [11])
        文本 = "\n".join(日志)
        self.assertIn("先安全切回主世界", 文本)
        self.assertIn("夜世界", 文本)
        self.assertIn("已回到主世界主页", 文本)

    def test_回不了主世界写原因按非主世界冷却并继续后续任务(self):
        任务, 上下文, 日志, 游戏, 调用 = self._夜世界任务(lambda 游戏, 上下文: False)
        self.assertTrue(任务.执行())
        self.assertEqual(调用, ["night"])
        self.assertEqual(游戏.点击记录, [])
        记录 = 上下文.数据库.状态["部落竞赛检查记录"]
        self.assertEqual(记录["结果"], "非主世界")
        self.assertLessEqual(记录["下次检查时间"] - time.time(), 5 * 60 + 5)
        self.assertTrue(any("无法回到主世界主页" in 行 and "5分钟后重试" in 行 for 行 in 日志))

    def test_切换后仍不在主页也不点击(self):
        任务, 上下文, 日志, 游戏, _ = self._夜世界任务(lambda 游戏, 上下文: True)
        self.assertTrue(任务.执行())
        self.assertEqual(游戏.点击记录, [])
        self.assertTrue(any("切换后仍未确认主世界主页" in 行 for 行 in 日志))

    def test_切换异常写原因不抛出(self):
        def 异常(游戏, 上下文):
            raise RuntimeError("截图失败")

        任务, 上下文, 日志, 游戏, _ = self._夜世界任务(异常)
        self.assertTrue(任务.执行())
        self.assertTrue(any("切换异常：截图失败" in 行 for 行 in 日志))

    def test_切换流程判定页面不可恢复时返回False交给安全待命(self):
        def 失败并标记(游戏, 上下文):
            上下文.页面恢复失败 = True
            return False

        任务, 上下文, _, 游戏, _ = self._夜世界任务(失败并标记)
        self.assertFalse(任务.执行())
        self.assertEqual(游戏.点击记录, [])

    def test_已在主世界主页不调用切换(self):
        游戏 = 模拟游戏(卡片=标准卡片())
        任务, _, _, _, _ = 构造任务(游戏)
        任务._回主世界 = Mock(return_value=True)
        self.assertTrue(任务.执行())
        任务._回主世界.assert_not_called()

    def test_冷却中不切世界(self):
        游戏 = 模拟游戏(卡片=标准卡片())
        游戏.状态 = "night"
        数据库 = 假数据库()
        数据库.状态["部落竞赛检查记录"] = {"下次检查时间": time.time() + 600, "结果": "已接任务"}
        任务, 上下文, _, _, _ = 构造任务(游戏, 数据库=数据库)
        上下文.识别点击画面 = 夜世界识别(游戏)
        任务._回主世界 = Mock(return_value=True)
        self.assertTrue(任务.执行())
        任务._回主世界.assert_not_called()
        self.assertEqual(游戏.点击记录, [])


class 打鱼间隙场次测试(unittest.TestCase):
    """2026-11-26 18:20 实机：接任务后 41 秒、一场没打就在打鱼间隙又开了竞赛面板。"""

    def test_接任务后下一次进攻前不开面板打完一场后才复查(self):
        游戏 = 模拟游戏(卡片=标准卡片())
        数据库 = 假数据库()
        任务, _, _, _, _ = 构造任务(游戏, 数据库=数据库)
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "已接任务")
        数据库.状态["部落竞赛检查记录"]["下次检查时间"] = time.time() + 600
        点击数 = len(游戏.点击记录)

        任务2, _, 日志2, _, _ = 构造任务(游戏, 数据库=数据库)
        任务2._流程 = lambda: self.fail("第一场还没打，不应开面板")
        self.assertTrue(任务2.执行(进攻前=True))  # 第 1 场进攻前
        self.assertEqual(len(游戏.点击记录), 点击数)
        self.assertTrue(any("本轮跳过（打鱼间隙）" in 行 and "再打完1场" in 行 for 行 in 日志2))

        任务3, _, 日志3, _, _ = 构造任务(游戏, 数据库=数据库)
        调用 = []
        任务3._流程 = lambda: 调用.append(1) or "已有任务"
        任务3._回到主页 = lambda: True
        self.assertTrue(任务3.执行(进攻前=True))  # 第 2 场进攻前：已打完 1 场
        self.assertEqual(调用, [1])
        self.assertTrue(any("触发：主世界刷资源打鱼间隙" in 行 and "已完成1场" in 行 for 行 in 日志3))

    def test_任务计划触发也写明来源(self):
        游戏 = 模拟游戏(卡片=标准卡片())
        任务, _, 日志, _, _ = 构造任务(游戏)
        任务.执行()
        self.assertTrue(any("触发：任务计划 部落竞赛接任务；首次检查" in 行 for 行 in 日志))


class 跳过原因测试(unittest.TestCase):
    def test_冷却中写出剩余分钟上次结果和已接任务(self):
        游戏 = 模拟游戏(卡片=标准卡片())
        数据库 = 假数据库()
        数据库.状态["部落竞赛检查记录"] = {
            "下次检查时间": time.time() + 17 * 60 + 5,
            "时间": time.time() - 60,
            "结果": "已接任务",
            "当前任务": "掠夺黑油（300分）",
            "下次检查进攻计数": 5,
            "进攻计数": 3,
        }
        任务, _, 日志, _, _ = 构造任务(游戏, 数据库=数据库)
        self.assertTrue(任务.执行())
        self.assertEqual(游戏.点击记录, [])
        self.assertEqual(len(日志), 1)
        行 = 日志[0]
        self.assertIn("本轮跳过", 行)
        self.assertIn("还剩约18分钟", 行)
        self.assertIn("任务计划", 行)
        self.assertIn("再打完2场", 行)
        self.assertIn("上次结果：已接任务", 行)
        self.assertIn("已接任务：掠夺黑油（300分）", 行)

    def test_未开启时任务计划调用也写原因(self):
        游戏 = 模拟游戏()
        任务, _, 日志, _, _ = 构造任务(游戏, 设置=SimpleNamespace(是否部落竞赛接任务=False))
        self.assertTrue(任务.执行())
        self.assertTrue(any("未开启" in 行 for 行 in 日志))

    def test_无可接任务清空界面上的旧任务(self):
        游戏 = 模拟游戏()  # 全部是夜世界任务
        数据库 = 假数据库()
        数据库.状态["部落竞赛检查记录"] = {"当前任务": "掠夺金币（150分）", "当前任务时间": 1.0,
                                     "当前任务进度": [3, 5]}
        任务, 上下文, _, _, _ = 构造任务(游戏, 数据库=数据库)
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "无可接任务")
        记录 = 上下文.数据库.状态["部落竞赛检查记录"]
        self.assertNotIn("当前任务", 记录)
        self.assertNotIn("当前任务进度", 记录)

    def test_已有任务记录进度且无名字时标记进行中(self):
        游戏 = 模拟游戏(卡片=标准卡片(), 已有任务=True)
        任务, 上下文, _, _, _ = 构造任务(游戏)
        任务._读取进度 = lambda 项列表: (2, 5)
        任务._存在进行中任务 = lambda 图像, 项列表: True
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "已有任务")
        记录 = 上下文.数据库.状态["部落竞赛检查记录"]
        self.assertEqual(记录["当前任务进度"], [2, 5])
        self.assertEqual(记录["当前任务"], "进行中的任务")


class 捐兵不接测试(unittest.TestCase):
    def test_资源里有捐兵类不接名单(self):
        self.assertIn("捐兵类", 配置.get("不接名单", {}))

    def test_捐兵捐法术捐攻城机器都命中不接名单(self):
        for 文本 in (
            文本_捐兵,
            "捐贈5個法術",
            "捐赠1台攻城机器",
            "在部落中捐兵總計50空間",
            "向部落成員捐贈攻城機器",
            "Donate 20 troops",
        ):
            with self.subTest(文本=文本):
                self.assertEqual(命中不接名单(文本, 配置), "捐兵类")
                self.assertIsNone(识别任务类型(文本, 配置))

    def test_白名单关键词凑上也不接(self):
        # OCR 把捐兵任务读成带“掠/金币”字样，仍以不接名单为准。
        self.assertIsNone(识别任务类型("捐贈部隊並掠奪200000金幣", 配置))

    def test_正常打鱼任务不受影响(self):
        self.assertIsNone(命中不接名单(文本_金币, 配置))
        self.assertEqual(识别任务类型(文本_金币, 配置), "掠夺金币")

    def test_流程里捐兵卡不点开始且日志写明不接名单(self):
        卡片 = [dict(文本=文本_夜世界, 积分="150")] * 12
        卡片[11] = dict(文本="捐贈1台攻城機器並掠奪200000金", 积分="300")
        卡片[8] = dict(文本=文本_金币, 积分="150")
        游戏 = 模拟游戏(卡片=卡片)
        任务, _, 日志, _, _ = 构造任务(游戏)
        self.assertTrue(任务.执行())
        self.assertEqual(游戏.开始点击, [8])
        self.assertTrue(any("不接名单:捐兵类" in 行 for 行 in 日志))


class OCR限时测试(unittest.TestCase):
    """2026-11-26 18:14 实机：点开活动列表后首次 OCR 2 分钟无返回、无日志。"""

    def tearDown(self):
        部落竞赛任务._OCR进行中 = None

    def test_OCR卡住时写进度日志并按超时安全收尾(self):
        import threading

        游戏 = 模拟游戏(卡片=标准卡片())
        放行 = threading.Event()
        任务, 上下文, 日志, _, _ = 构造任务(
            游戏, 配置覆盖={"超时": {**配置["超时"], "OCR秒": 1.2, "OCR进度日志秒": 1}})

        def 卡住的OCR(图):
            放行.wait(10)
            return 游戏.ocr结果(), None

        上下文.获取OCR引擎 = lambda: 卡住的OCR
        try:
            self.assertTrue(任务.执行())
        finally:
            放行.set()
        self.assertEqual(任务.结果, "入口异常")  # 卡在活动列表标题 OCR：写原因、存现场、关 X、记冷却
        self.assertEqual(游戏.开始点击, [])
        self.assertEqual(游戏.状态, "home")  # OCR 卡住也用模板复核后关掉活动列表
        self.assertFalse(上下文.页面恢复失败)
        文本 = "|".join(日志)
        self.assertIn("OCR 识别中", 文本)
        self.assertIn("OCR 识别超过1秒仍未返回", 文本)
        记录 = 上下文.数据库.状态["部落竞赛检查记录"]
        self.assertEqual(记录["结果"], "入口异常")

    def test_上一次OCR未返回时不并发调用引擎(self):
        import threading

        放行 = threading.Event()
        旧 = threading.Thread(target=放行.wait, args=(5,), daemon=True)
        旧.start()
        部落竞赛任务._OCR进行中 = 旧
        任务, 上下文, _, _, _ = 构造任务(模拟游戏())
        上下文.获取OCR引擎 = Mock()
        from 任务流程.活动.部落竞赛 import 部落竞赛超时
        try:
            with self.assertRaises(部落竞赛超时):
                任务._OCR(None)
        finally:
            放行.set()
        上下文.获取OCR引擎.assert_not_called()

    def test_OCR异常按没有文字处理(self):
        任务, 上下文, 日志, _, _ = 构造任务(模拟游戏())
        上下文.获取OCR引擎 = Mock(side_effect=RuntimeError("模型坏了"))
        self.assertEqual(任务._OCR(None), [])
        self.assertTrue(any("OCR 失败：模型坏了" in 行 for 行 in 日志))


class 活动列表快速确认测试(unittest.TestCase):
    """2026-11-26 实机：确认活动列表 164~251 秒，原因是每次轮询都整屏 OCR 文字最多的活动列表。"""

    def _列表任务(self, 页面="活动弹窗", 可信度=0.95):
        游戏 = 模拟游戏(卡片=标准卡片())
        游戏.状态 = "events"
        游戏.列表滑动 = 1
        任务, 上下文, 日志, _, _ = 构造任务(游戏)
        上下文.识别点击画面 = lambda 强制=False: SimpleNamespace(页面=页面, 世界=None, 可信度=可信度)
        区域记录 = []
        原OCR = 任务._OCR

        def 记录OCR(图像, 区域=None):
            区域记录.append(None if 区域 is None else tuple(区域))
            return 原OCR(图像, 区域)

        任务._OCR = 记录OCR
        return 任务, 区域记录

    def test_视觉特征加关闭X模板确认时不做OCR(self):
        任务, 区域记录 = self._列表任务()
        self.assertTrue(任务._活动列表已打开())
        self.assertEqual(区域记录, [])

    def test_视觉特征不足时只OCR标题小区域(self):
        任务, 区域记录 = self._列表任务(页面="未知", 可信度=0.0)
        self.assertTrue(任务._活动列表已打开())
        self.assertEqual(区域记录, [tuple(配置["活动列表"]["标题ROI"])])

    def test_没有关闭X模板不确认也不OCR(self):
        任务, 区域记录 = self._列表任务()
        任务._匹配模板 = lambda 图像, 名称, 区域=None: None
        self.assertIsNone(任务._活动列表已打开())
        self.assertEqual(区域记录, [])

    def test_找竞赛开启只OCR列表区且坐标还原到整屏(self):
        任务, 区域记录 = self._列表任务()
        self.assertEqual(任务._找部落竞赛开启(), (592, 492))
        self.assertTrue(区域记录)
        self.assertTrue(all(区域 == tuple(配置["活动列表"]["列表ROI"]) for 区域 in 区域记录))

    def test_整个流程不再整屏OCR活动列表(self):
        游戏 = 模拟游戏(卡片=标准卡片())
        任务, 上下文, _, _, _ = 构造任务(游戏)

        def 识别(强制=False):
            if 游戏.状态 == "events":
                return SimpleNamespace(页面="活动弹窗", 世界=None, 可信度=0.95)
            return SimpleNamespace(页面="主世界主页" if 游戏.状态 == "home" else "未知", 世界="主世界")

        上下文.识别点击画面 = 识别
        状态记录 = []
        原OCR = 任务._OCR
        任务._OCR = lambda 图像, 区域=None: 状态记录.append((游戏.状态, 区域)) or 原OCR(图像, 区域)
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "已接任务")
        self.assertFalse([记录 for 记录 in 状态记录 if 记录 == ("events", None)])


class 审查修订测试(unittest.TestCase):
    def test_写点击日志期间收到停止不再发送点击(self):
        import threading
        from 任务流程.活动.部落竞赛 import 部落竞赛超时

        游戏 = 模拟游戏(卡片=标准卡片())
        任务, 上下文, _, _, _ = 构造任务(游戏)
        停止 = threading.Event()
        上下文.停止事件 = 停止
        原日志 = 上下文.置脚本状态

        def 日志时停止(文本, *参数):
            原日志(文本, *参数)
            if 文本.startswith("部落竞赛：点击"):
                停止.set()

        上下文.置脚本状态 = 日志时停止
        任务._截止 = 1e9
        with self.assertRaises(部落竞赛超时):
            任务._点击((196, 556), "活动按钮")
        self.assertEqual(游戏.点击记录, [])

    def test_框架点击在发送前再查停止事件(self):
        import threading
        from 任务流程.基础任务框架 import 任务上下文

        上下文 = 任务上下文.__new__(任务上下文)
        上下文.停止事件 = threading.Event()
        上下文.停止事件.set()
        上下文.检查宝石商店危险页面 = lambda 强制=False: False
        上下文._最近点击页面结果 = SimpleNamespace(页面="主世界主页")
        上下文.鼠标 = Mock()
        self.assertFalse(上下文.点击(100, 100))
        上下文.鼠标.移动到.assert_not_called()
        上下文.鼠标.左键点击.assert_not_called()

    def test_关闭设置时打鱼间隙也写来源和原因(self):
        游戏 = 模拟游戏()
        任务, _, 日志, _, _ = 构造任务(游戏, 设置=SimpleNamespace(是否部落竞赛接任务=False))
        self.assertTrue(任务.执行(进攻前=True))
        self.assertTrue(any("本轮跳过（打鱼间隙）" in 行 and "未开启" in 行 for 行 in 日志))

    def test_面板详情关闭等步骤只OCR小区域_仅面板内容整帧一次(self):
        游戏 = 模拟游戏(卡片=标准卡片())
        任务, _, _, _, _ = 构造任务(游戏)
        记录 = []
        原OCR = 任务._OCR
        任务._OCR = lambda 图像, 区域=None: 记录.append((游戏.状态, 游戏.详情, 区域)) or 原OCR(图像, 区域)
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "已接任务")
        整帧 = [项 for 项 in 记录 if 项[2] is None]
        # 唯一的整帧 OCR 是确认面板后读面板内容那一次（没有打开详情）
        self.assertEqual(len(整帧), 1)
        self.assertEqual(整帧[0][:2], ("panel", None))

    def test_面板模板不在时不做OCR(self):
        游戏 = 模拟游戏()
        游戏.状态 = "events"
        任务, _, _, _, _ = 构造任务(游戏)
        任务._OCR = Mock(return_value=[])
        self.assertIsNone(任务._识别竞赛面板())
        任务._OCR.assert_not_called()


class 引擎注入回主世界测试(unittest.TestCase):
    def _机器人(self):
        from 线程.自动化机器人 import 自动化机器人
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人._同步官方账号数据 = Mock(return_value=None)
        机器人._进入并确认主世界 = Mock(return_value=True)
        return 机器人

    def test_任务计划调用注入复用的主世界切换(self):
        机器人 = self._机器人()
        上下文 = SimpleNamespace()
        with patch.object(部落竞赛任务, "执行", autospec=True, return_value=True) as 执行:
            with patch.object(部落竞赛任务, "__init__", autospec=True, return_value=None) as 构造:
                self.assertTrue(机器人._执行部落竞赛计划(上下文))
        回主世界 = 构造.call_args.kwargs["回主世界"]
        self.assertTrue(callable(回主世界))
        self.assertTrue(回主世界())
        机器人._进入并确认主世界.assert_called_once_with(上下文, "部落竞赛")
        self.assertFalse(执行.call_args.kwargs["进攻前"])

    def test_打鱼间隙调用不切世界(self):
        机器人 = self._机器人()
        with patch.object(部落竞赛任务, "执行", autospec=True, return_value=True):
            with patch.object(部落竞赛任务, "__init__", autospec=True, return_value=None) as 构造:
                机器人._执行部落竞赛计划(SimpleNamespace(), 进攻前=True)
        self.assertIsNone(构造.call_args.kwargs["回主世界"])


if __name__ == "__main__":
    unittest.main()


class 活动列表不卡主循环测试(unittest.TestCase):
    """2026-11-26 19:44 rc157 实机：确认活动列表后约 3 分钟无日志。

    根因：_等待 里的 脚本延时 顺带跑升级完成弹窗整屏 OCR（同步、无超时），
    活动列表文字最多，一次几分钟。部落竞赛 自己的 OCR 限时/进度日志管不到。
    """

    def tearDown(self):
        部落竞赛任务._OCR进行中 = None

    def test_流程期间设置流程标记_结束后清除(self):
        游戏 = 模拟游戏(卡片=标准卡片())
        任务, 上下文, _, _, _ = 构造任务(游戏)
        看到 = []
        原延时 = 上下文.脚本延时
        上下文.脚本延时 = lambda 毫秒: 看到.append(getattr(上下文, "_部落竞赛流程中", None)) or 原延时(毫秒)
        self.assertTrue(任务.执行())
        self.assertTrue(看到)
        self.assertTrue(all(看到))
        self.assertFalse(上下文._部落竞赛流程中)

    def test_流程异常时也清除流程标记(self):
        游戏 = 模拟游戏(卡片=标准卡片())
        任务, 上下文, _, _, _ = 构造任务(游戏)
        任务._流程 = Mock(side_effect=RuntimeError("坏了"))
        self.assertTrue(任务.执行())
        self.assertFalse(上下文._部落竞赛流程中)

    def test_延时被后台检查占住时写日志(self):
        游戏 = 模拟游戏(卡片=标准卡片())
        任务, 上下文, 日志, _, _ = 构造任务(
            游戏, 配置覆盖={"超时": {**配置["超时"], "慢调用日志秒": 0.05}})
        上下文.脚本延时 = lambda 毫秒: time.sleep(0.15)
        任务._延时(10)
        self.assertTrue(any("实际多用了" in 行 for 行 in 日志), 日志)

    def test_活动列表识别慢时几秒内超时_写日志_关面板回主页(self):
        游戏 = 模拟游戏(卡片=标准卡片())
        任务, 上下文, 日志, _, 时间 = 构造任务(
            游戏, 配置覆盖={"超时": {**配置["超时"], "慢调用日志秒": 0.05, "活动列表秒": 6}})
        调用 = {"n": 0}

        def 慢且不确认():
            # 模拟识别阻塞：真实耗时 + 流程时钟各走 2 秒，始终没确认到列表。
            调用["n"] += 1
            time.sleep(0.06)
            时间["t"] += 2.0
            return None

        任务._活动列表已打开 = 慢且不确认
        开始 = time.monotonic()
        self.assertTrue(任务.执行())
        self.assertLess(time.monotonic() - 开始, 5)
        self.assertEqual(任务.结果, "入口异常")
        self.assertEqual(游戏.状态, "home")
        self.assertEqual(游戏.开始点击, [])
        self.assertFalse(上下文.页面恢复失败)
        # 每次尝试最多 6 秒（3 次识别），2 次入口重试
        self.assertLessEqual(调用["n"], 2 * 4)
        文本 = "|".join(日志)
        self.assertIn("确认活动列表单次识别耗时", 文本)
        self.assertIn("秒内未确认", 文本)
        self.assertIn("按冷却稍后重试", 文本)
        记录 = 上下文.数据库.状态["部落竞赛检查记录"]
        self.assertEqual(记录["结果"], "入口异常")
        self.assertGreater(记录["下次检查时间"], 记录["时间"])

    def test_活动列表标题OCR阻塞时按短限时收尾不等60秒(self):
        import threading

        游戏 = 模拟游戏(卡片=标准卡片())
        放行 = threading.Event()
        任务, 上下文, 日志, _, _ = 构造任务(
            游戏, 配置覆盖={"超时": {**配置["超时"], "活动列表OCR秒": 1, "OCR进度日志秒": 1}})
        # 视觉特征不足，只能走标题小区域 OCR；OCR 卡住不返回。
        上下文.识别点击画面 = lambda 强制=False: SimpleNamespace(
            页面="主世界主页" if 游戏.状态 == "home" else "未知", 世界="主世界", 可信度=0.9)

        def 卡住的OCR(图):
            放行.wait(10)
            return 游戏.ocr结果(), None

        上下文.获取OCR引擎 = lambda: 卡住的OCR
        开始 = time.monotonic()
        try:
            self.assertTrue(任务.执行())
        finally:
            放行.set()
        self.assertLess(time.monotonic() - 开始, 5)
        # 标题 OCR 超时和步骤超时同样处理：写原因、存现场、安全关 X、记冷却。
        self.assertEqual(任务.结果, "入口异常")
        self.assertEqual(游戏.状态, "home")
        self.assertEqual(游戏.开始点击, [])
        self.assertFalse(上下文.页面恢复失败)
        文本 = "|".join(日志)
        self.assertIn("OCR 识别超过1秒仍未返回", 文本)
        self.assertIn("活动列表标题OCR异常", 文本)
        self.assertIn("活动列表未确认：已保存现场截图", 文本)
        self.assertTrue(sorted(Path(上下文.待命现场目录).glob("clan_entry_*活动列表未确认.png")))
        记录 = 上下文.数据库.状态["部落竞赛检查记录"]
        self.assertEqual(记录["结果"], "入口异常")
        self.assertGreater(记录["下次检查时间"], 记录["时间"])

    def test_标题OCR抛异常时保存现场并回主页(self):
        from 任务流程.活动.部落竞赛 import 部落竞赛超时

        游戏 = 模拟游戏(卡片=标准卡片())
        任务, 上下文, 日志, _, _ = 构造任务(游戏)
        上下文.识别点击画面 = lambda 强制=False: SimpleNamespace(
            页面="主世界主页" if 游戏.状态 == "home" else "未知", 世界="主世界", 可信度=0.9)
        原OCR = 任务._OCR

        def OCR(图像, 区域=None):
            if 区域 is not None and tuple(区域) == tuple(配置["活动列表"]["标题ROI"]):
                raise 部落竞赛超时("OCR 识别超过5秒未返回")
            return 原OCR(图像, 区域)

        任务._OCR = OCR
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "入口异常")
        self.assertEqual(游戏.状态, "home")
        self.assertEqual(游戏.开始点击, [])
        self.assertFalse(上下文.页面恢复失败)
        self.assertIn("活动列表标题OCR异常", "|".join(日志))
        self.assertTrue(sorted(Path(上下文.待命现场目录).glob("clan_entry_*活动列表未确认.png")))
        self.assertEqual(上下文.数据库.状态["部落竞赛检查记录"]["结果"], "入口异常")

    def test_停止请求不被当成OCR异常吞掉(self):
        from 任务流程.活动.部落竞赛 import 部落竞赛超时

        游戏 = 模拟游戏(卡片=标准卡片())
        任务, 上下文, 日志, _, _ = 构造任务(游戏)
        任务._活动列表已打开 = Mock(side_effect=部落竞赛超时("收到停止请求"))
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "超时")
        self.assertNotIn("活动列表标题OCR异常", "|".join(日志))

    def test_停止事件时零点击(self):
        import threading

        游戏 = 模拟游戏(卡片=标准卡片())
        任务, 上下文, _, _, _ = 构造任务(游戏)
        上下文.停止事件 = threading.Event()
        上下文.停止事件.set()
        任务.执行()
        self.assertEqual(游戏.点击记录 if hasattr(游戏, "点击记录") else [], [])
        self.assertEqual(游戏.开始点击, [])
