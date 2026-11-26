"""C2 都城突袭出击（capital_raid）：周末窗口、免费次数、宝石护栏、简化下兵、停止与失败语义。"""
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from 任务流程.日常 import 日常公共
from 任务流程.日常 import 都城突袭 as 突袭模块
from 任务流程.日常.都城突袭 import (
    都城突袭任务, 是否突袭周末, 本周末标识, 距突袭周末开始秒, 解析剩余次数,
)
from 数据库.任务数据库 import 任务计划定义映射, 机器人设置

周六 = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)   # 2026-11-27 是周五
周三 = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


class 假数据库:
    def __init__(self):
        self.状态 = {}

    def 获取最新完整状态(self, 标志):
        return SimpleNamespace(状态数据=dict(self.状态))

    def 更新状态(self, 标志, 类型, 数据):
        self.状态[类型] = 数据


class 模拟游戏:
    """按点击切换页面，OCR 按页面和区域返回文字。"""

    def __init__(self, 参数, 剩余=2, 进攻文本="进攻", 战斗可确认=True, 会结算=True):
        self.参数 = 参数
        self.页面 = "主页"
        self.剩余 = 剩余
        self.进攻文本 = 进攻文本
        self.战斗可确认 = 战斗可确认
        self.会结算 = 会结算
        self.下兵次数 = 0
        self.图 = np.zeros((600, 800, 3), np.uint8)

    def 点击(self, x, y, **k):
        点 = (int(x), int(y))
        p = self.参数
        if self.页面 == "主页" and 点 == tuple(p["都城入口"]):
            self.页面 = "都城"
        elif self.页面 == "都城" and 点 == (700, 540):
            self.页面 = "突袭"
        elif self.页面 == "突袭" and 点 == (680, 560):
            self.剩余 -= 1
            self.页面 = "战斗"
        elif self.页面 == "战斗" and 点 in [tuple(v) for v in p["下兵点"]]:
            self.下兵次数 += 1
            if self.会结算 and self.下兵次数 % (len(p["兵种栏格子"]) * p["每格下兵次数"]) == 0:
                self.页面 = "结算"
        elif self.页面 == "结算" and 点 == (400, 520):
            self.页面 = "突袭"
        elif self.页面 == "突袭" and 点 == tuple(p["退出突袭页点"]):
            self.页面 = "都城"
        elif self.页面 == "都城" and 点 == (60, 560):
            self.页面 = "主页"
        return True

    def OCR(self, 图, 区域):
        区域 = tuple(int(v) for v in 区域)
        p = self.参数
        规则 = {
            tuple(p["都城页确认区域"]): {"都城": [("部落都城", (400, 40))]},
            tuple(p["突袭页确认区域"]): {"突袭": [("突袭周末", (400, 45))]},
            tuple(p["突袭入口区域"]): {"都城": [("突袭", (700, 540))]},
            tuple(p["剩余次数区域"]): {"突袭": [(f"剩余出击{self.剩余}/6", (650, 500))]},
            tuple(p["进攻按钮区域"]): {"突袭": [(self.进攻文本, (680, 560))]},
            tuple(p["战斗确认区域"]): {"战斗": [("结束战斗", (100, 560))] if self.战斗可确认 else []},
            tuple(p["结算区域"]): {"结算": [("回营", (400, 520))]},
            tuple(p["返回按钮区域"]): {"都城": [("返回", (60, 560))]},
        }
        项 = 规则.get(区域, {}).get(self.页面, [])
        return [(日常公共.规范文本(文), 心) for 文, 心 in 项]


def 参数(**覆盖):
    值 = dict(
        突袭模块.默认参数, calibrated=True, 都城入口=[100, 450], 退出突袭页点=[760, 40],
        兵种栏格子=[[100, 560], [160, 560]], 下兵点=[[50, 300], [750, 300]],
        每格下兵次数=2, 下兵间隔毫秒=0, 战斗最长秒=2, 结算轮询毫秒=0,
    )
    值.update(覆盖)
    return 值


def 构造(现在=周六, 游戏参数=None, **游戏选项):
    p = 游戏参数 or 参数()
    游戏 = 模拟游戏(p, **游戏选项)
    ctx = SimpleNamespace(
        机器人标志="t", 数据库=假数据库(), 设置=机器人设置(), 置脚本状态=Mock(), 脚本延时=Mock(),
        请求任务计划等待=Mock(), 页面恢复失败=False, 停止事件=SimpleNamespace(is_set=lambda: False),
        op=SimpleNamespace(获取屏幕图像cv=lambda *a, **k: 游戏.图),
    )
    ctx.点击 = Mock(side_effect=游戏.点击)
    任务 = 都城突袭任务(ctx, p, 现在=现在)
    任务.OCR = 游戏.OCR
    return 任务, ctx, 游戏


def 点(ctx):
    return [c.args[:2] for c in ctx.点击.call_args_list]


class 时间窗口测试(unittest.TestCase):
    def test_突袭周末边界(self):
        def t(日, 时, 分=0):
            return datetime(2026, 11, 日, 时, 分, tzinfo=timezone.utc)

        self.assertFalse(是否突袭周末(t(27, 6, 59)))
        self.assertTrue(是否突袭周末(t(27, 7, 0)))
        self.assertTrue(是否突袭周末(t(29, 23, 0)))
        self.assertTrue(是否突袭周末(t(30, 6, 59)))
        self.assertFalse(是否突袭周末(t(30, 7, 0)))
        self.assertFalse(是否突袭周末(周三))

    def test_本周末标识与距开始(self):
        self.assertEqual(本周末标识(周六), "2026-11-27")
        self.assertEqual(本周末标识(datetime(2026, 11, 30, 3, tzinfo=timezone.utc)), "2026-11-27")
        self.assertAlmostEqual(距突袭周末开始秒(datetime(2026, 11, 27, 6, tzinfo=timezone.utc)), 3600, delta=1)

    def test_解析剩余次数(self):
        正则 = 突袭模块.默认参数["剩余次数正则"]
        self.assertEqual(解析剩余次数("剩余出击 5 / 6", 正则), 5)
        self.assertEqual(解析剩余次数("0/6", 正则), 0)
        self.assertIsNone(解析剩余次数("剩余出击", 正则))


class 前置拒绝测试(unittest.TestCase):
    def test_未校准拒绝运行零点击(self):
        任务, ctx, _ = 构造(游戏参数=dict(突袭模块.默认参数))
        self.assertTrue(任务.执行())
        ctx.点击.assert_not_called()
        self.assertFalse(日常公共.已校准(突袭模块.读取参数()))

    def test_下兵点未配置拒绝运行(self):
        任务, ctx, _ = 构造(游戏参数=参数(下兵点=[]))
        self.assertTrue(任务.执行())
        ctx.点击.assert_not_called()

    def test_非突袭周末不运行并等待(self):
        任务, ctx, _ = 构造(现在=周三)
        self.assertTrue(任务.执行())
        ctx.点击.assert_not_called()
        ctx.请求任务计划等待.assert_called()

    def test_本周末次数用完后不再进入(self):
        任务, ctx, _ = 构造()
        日常公共.写入任务记录(ctx.数据库, "t", "capital_raid", {"周末": "2026-11-27", "次数用完": True})
        self.assertTrue(任务.执行())
        ctx.点击.assert_not_called()

    def test_默认关闭且已注册(self):
        self.assertFalse(机器人设置().是否都城突袭出击)
        self.assertIn("capital_raid", 任务计划定义映射)
        self.assertEqual(机器人设置(都城突袭每轮最多出击=99).都城突袭每轮最多出击, 6)


class 出击流程测试(unittest.TestCase):
    def test_用完免费次数后退出并返回主世界(self):
        任务, ctx, 游戏 = 构造(剩余=2)
        self.assertTrue(任务.执行())
        self.assertEqual(游戏.页面, "主页")
        self.assertEqual(任务.本轮出击, 2)
        self.assertEqual(点(ctx).count((680, 560)), 2)
        self.assertEqual(游戏.下兵次数, 8)
        记录 = 日常公共.读取任务记录(ctx.数据库, "t", "capital_raid")
        self.assertEqual(记录["出击次数"], 2)
        self.assertTrue(记录["次数用完"])
        self.assertFalse(ctx.页面恢复失败)

    def test_每轮上限(self):
        任务, ctx, 游戏 = 构造(剩余=5)
        ctx.设置 = 机器人设置(都城突袭每轮最多出击=1)
        self.assertTrue(任务.执行())
        self.assertEqual(任务.本轮出击, 1)
        self.assertEqual(游戏.页面, "主页")
        self.assertFalse(日常公共.读取任务记录(ctx.数据库, "t", "capital_raid")["次数用完"])

    def test_剩余次数读不出不出击(self):
        任务, ctx, 游戏 = 构造()
        原OCR = 任务.OCR
        任务.OCR = lambda 图, 区域: [] if tuple(区域) == tuple(任务.参数["剩余次数区域"]) else 原OCR(图, 区域)
        self.assertTrue(任务.执行())
        self.assertNotIn((680, 560), 点(ctx))
        self.assertEqual(游戏.页面, "主页")

    def test_进攻按钮文字含宝石不点(self):
        任务, ctx, 游戏 = 构造(进攻文本="10宝石进攻")
        self.assertTrue(任务.执行())
        self.assertNotIn((680, 560), 点(ctx))

    def test_进攻按钮区域有宝石图标不点(self):
        任务, ctx, 游戏 = 构造()
        宝石 = 日常公共.读取图片(日常公共.宝石图标路径)
        游戏.图[540:540 + 宝石.shape[0], 700:700 + 宝石.shape[1]] = 宝石
        self.assertTrue(任务.执行())
        self.assertNotIn((680, 560), 点(ctx))

    def test_护栏OCR异常时进攻按钮不点(self):
        任务, ctx, 游戏 = 构造()
        原OCR = 任务.OCR
        次数 = {"n": 0}

        def OCR(图, 区域):
            if tuple(区域) == tuple(任务.参数["进攻按钮区域"]):
                次数["n"] += 1
                if 次数["n"] >= 2:  # 第一次是找按钮，第二次是点击前护栏
                    raise 日常公共.OCR不可用("模拟崩溃")
            return 原OCR(图, 区域)

        任务.OCR = OCR
        self.assertTrue(任务.执行())
        self.assertNotIn((680, 560), 点(ctx))

    def test_未确认进入战斗标记页面不可信(self):
        任务, ctx, 游戏 = 构造(战斗可确认=False)
        self.assertFalse(任务.执行())
        self.assertTrue(ctx.页面恢复失败)
        self.assertEqual(游戏.下兵次数, 0)

    def test_结算超时标记页面不可信(self):
        任务, ctx, 游戏 = 构造(会结算=False, 游戏参数=参数(战斗最长秒=0.05))
        self.assertFalse(任务.执行())
        self.assertTrue(ctx.页面恢复失败)
        self.assertNotIn((400, 520), 点(ctx))
        self.assertEqual(日常公共.读取任务记录(ctx.数据库, "t", "capital_raid")["出击次数"], 1)

    def test_下兵中停止后零点击且不标记失败(self):
        任务, ctx, 游戏 = 构造()
        原 = ctx.点击.side_effect

        def 点击(x, y, **k):
            结果 = 原(x, y, **k)
            if (int(x), int(y)) == (50, 300):
                ctx.停止事件 = SimpleNamespace(is_set=lambda: True)
            return 结果

        ctx.点击 = Mock(side_effect=点击)
        self.assertTrue(任务.执行())
        self.assertEqual(点(ctx)[-1], (50, 300))
        self.assertFalse(ctx.页面恢复失败)

    def test_退出突袭页前确认失败不点(self):
        任务, ctx, 游戏 = 构造()
        游戏.页面 = "突袭"
        原OCR = 任务.OCR
        区 = tuple(任务.参数["突袭页确认区域"])
        次数 = {"n": 0}

        def OCR(图, 区域):
            if tuple(区域) == 区:
                次数["n"] += 1
                if 次数["n"] >= 2:  # 安全关闭重新截图确认时突袭页已不在
                    return []
            return 原OCR(图, 区域)

        任务.OCR = OCR
        self.assertFalse(任务._退出突袭页())
        ctx.点击.assert_not_called()

    def test_退出突袭页正常关闭回到都城(self):
        任务, ctx, 游戏 = 构造()
        游戏.页面 = "突袭"
        self.assertTrue(任务._退出突袭页())
        self.assertEqual(点(ctx), [(760, 40)])
        self.assertEqual(游戏.页面, "都城")

class 下兵逐点护栏测试(unittest.TestCase):
    """屁股审查：选槽和每个下兵点前都要新帧 + 战斗页确认 + 宝石图标 + 危险词 + 停止。"""

    def test_每次下兵点击前都重新截图(self):
        任务, ctx, 游戏 = 构造(剩余=1)
        截图次数 = {"n": 0}
        原截图 = ctx.op.获取屏幕图像cv
        ctx.op = SimpleNamespace(获取屏幕图像cv=lambda *a, **k: (截图次数.__setitem__("n", 截图次数["n"] + 1), 原截图())[1])
        下兵前截图 = []
        原点击 = ctx.点击.side_effect

        def 点击(x, y, **k):
            if 游戏.页面 == "战斗":
                下兵前截图.append(截图次数["n"])
            return 原点击(x, y, **k)

        ctx.点击 = Mock(side_effect=点击)
        self.assertTrue(任务.执行())
        # 战斗中 2 次选槽 + 4 次下兵，每次点击前截图计数都严格增加
        self.assertEqual(len(下兵前截图), 6)
        self.assertEqual(len(set(下兵前截图)), 6)

    def test_下兵中途战斗页消失立即停止(self):
        任务, ctx, 游戏 = 构造(会结算=False, 游戏参数=参数(战斗最长秒=0.05))
        原点击 = ctx.点击.side_effect

        def 点击(x, y, **k):
            结果 = 原点击(x, y, **k)
            if (int(x), int(y)) == (50, 300):
                游戏.页面 = "未知"
            return 结果

        ctx.点击 = Mock(side_effect=点击)
        self.assertFalse(任务.执行())
        下兵 = [c for c in 点(ctx) if c in ((50, 300), (750, 300))]
        self.assertEqual(下兵, [(50, 300)])

    def test_下兵点附近出现危险词则跳过该点(self):
        任务, ctx, 游戏 = 构造(剩余=1)
        原OCR = 任务.OCR

        def OCR(图, 区域):
            x1, y1, x2, y2 = 区域
            if x1 <= 50 <= x2 and y1 <= 300 <= y2 and x2 - x1 <= 40:
                return [("宝石", (50, 300))]
            return 原OCR(图, 区域)

        任务.OCR = OCR
        游戏.会结算 = False
        游戏参数 = 任务.参数
        任务.参数 = dict(游戏参数, 战斗最长秒=0.05)
        任务.执行()
        self.assertNotIn((50, 300), 点(ctx))
        self.assertIn((750, 300), 点(ctx))

    def test_下兵途中出现宝石图标后不再点该点(self):
        任务, ctx, 游戏 = 构造(剩余=1)
        宝石 = 日常公共.读取图片(日常公共.宝石图标路径)
        原点击 = ctx.点击.side_effect

        def 点击(x, y, **k):
            结果 = 原点击(x, y, **k)
            if (int(x), int(y)) == (750, 300):
                游戏.图[284:284 + 宝石.shape[0], 737:737 + 宝石.shape[1]] = 宝石
            return 结果

        ctx.点击 = Mock(side_effect=点击)
        游戏.会结算 = False
        任务.参数 = dict(任务.参数, 战斗最长秒=0.05)
        任务.执行()
        self.assertEqual(点(ctx).count((750, 300)), 1)
        self.assertEqual(点(ctx).count((50, 300)), 2)

    def test_兵种栏格子有危险词则跳过该格(self):
        任务, ctx, 游戏 = 构造(剩余=1)
        原OCR = 任务.OCR

        def OCR(图, 区域):
            x1, y1, x2, y2 = 区域
            if x1 <= 100 <= x2 and y1 <= 560 <= y2 and x2 - x1 <= 60:
                return [("购买", (100, 560))]
            return 原OCR(图, 区域)

        任务.OCR = OCR
        游戏.会结算 = False
        任务.参数 = dict(任务.参数, 战斗最长秒=0.05)
        任务.执行()
        self.assertNotIn((100, 560), 点(ctx))
        self.assertIn((160, 560), 点(ctx))


class 剩余次数读不出测试(unittest.TestCase):
    def _读不出任务(self):
        任务, ctx, 游戏 = 构造()
        原OCR = 任务.OCR
        任务.OCR = lambda 图, 区域: [] if tuple(区域) == tuple(任务.参数["剩余次数区域"]) else 原OCR(图, 区域)
        return 任务, ctx, 游戏

    def test_连续读不出达到上限放弃本周末(self):
        数据库 = None
        for 第几次 in range(1, 4):
            任务, ctx, 游戏 = self._读不出任务()
            if 数据库 is not None:
                ctx.数据库 = 数据库
                任务.数据库 = 数据库
            数据库 = ctx.数据库
            # 冷却已过：清掉下次检查时间
            记录 = 日常公共.读取任务记录(数据库, "t", "capital_raid")
            if 记录:
                记录["下次检查时间"] = 0
                日常公共.写入任务记录(数据库, "t", "capital_raid", 记录)
            self.assertTrue(任务.执行())
            记录 = 日常公共.读取任务记录(数据库, "t", "capital_raid")
            self.assertEqual(记录["读不出次数"], 第几次)
            self.assertEqual(记录["次数用完"], 第几次 >= 3)
        self.assertTrue(any("放弃本周末" in str(c.args[0]) for c in ctx.置脚本状态.call_args_list))
        # 放弃后不再进入
        任务2, ctx2, _ = 构造()
        ctx2.数据库 = 任务2.数据库 = 数据库
        记录["下次检查时间"] = 0
        日常公共.写入任务记录(数据库, "t", "capital_raid", 记录)
        self.assertTrue(任务2.执行())
        ctx2.点击.assert_not_called()

    def test_读到次数后清零计数(self):
        任务, ctx, _ = 构造(剩余=1)
        日常公共.写入任务记录(ctx.数据库, "t", "capital_raid",
                       {"周末": "2026-11-27", "读不出次数": 2, "出击次数": 0, "次数用完": False})
        self.assertTrue(任务.执行())
        self.assertEqual(日常公共.读取任务记录(ctx.数据库, "t", "capital_raid")["读不出次数"], 0)


if __name__ == "__main__":
    unittest.main()
