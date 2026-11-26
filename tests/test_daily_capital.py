"""C1 都城捐金币 + 日常面板公共护栏：未校准拒绝、宝石护栏、只用都城金币、OCR 不可用拒绝点击。"""
import pathlib
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.日常 import 日常公共
from 任务流程.日常 import 都城捐金币 as 都城模块
from 任务流程.日常.都城捐金币 import 都城捐金币任务
from 数据库.任务数据库 import 任务计划定义映射, 机器人设置

根目录 = pathlib.Path(__file__).resolve().parents[1]


def 读图(相对):
    return cv2.imdecode(np.fromfile(str(根目录 / 相对), dtype=np.uint8), cv2.IMREAD_COLOR)


class 假数据库:
    def __init__(self):
        self.状态 = {}

    def 获取最新完整状态(self, 标志):
        return SimpleNamespace(状态数据=dict(self.状态))

    def 更新状态(self, 标志, 类型, 数据):
        self.状态[类型] = 数据


def 上下文(图=None, **设置项):
    图 = 图 if 图 is not None else np.zeros((600, 800, 3), np.uint8)
    return SimpleNamespace(
        机器人标志="t", 数据库=假数据库(), 设置=机器人设置(**设置项),
        置脚本状态=Mock(), 脚本延时=Mock(), 请求任务计划等待=Mock(),
        点击=Mock(return_value=True), 页面恢复失败=False,
        停止事件=SimpleNamespace(is_set=lambda: False),
        op=SimpleNamespace(获取屏幕图像cv=lambda *a, **k: 图),
    )


def 随机图案(种子, 高=40, 宽=40):
    return np.random.default_rng(种子).integers(0, 255, (高, 宽, 3), dtype=np.uint8)


class 假OCR:
    """按区域返回文字：规则 [(区域判定函数, [(文本, 中心)])]。"""

    def __init__(self, 规则):
        self.规则 = 规则

    def __call__(self, 图, 区域):
        结果 = []
        for 判定, 项 in self.规则:
            if 判定(tuple(int(v) for v in 区域)):
                项 = 项() if callable(项) else 项
                结果.extend((日常公共.规范文本(文), 心) for 文, 心 in 项)
        return 结果


# ================================================================== C1 都城
class 都城前置测试(unittest.TestCase):
    def test_未校准拒绝运行(self):
        ctx = 上下文(是否捐都城金币=True)
        任务 = 都城捐金币任务(ctx, dict(都城模块.默认参数))
        self.assertTrue(任务.执行())
        ctx.点击.assert_not_called()
        self.assertFalse(日常公共.已校准(都城模块.读取参数()))

    def test_已校准但没有都城金币模板也拒绝(self):
        ctx = 上下文()
        任务 = 都城捐金币任务(ctx, dict(都城模块.默认参数, calibrated=True))
        self.assertTrue(任务.执行())
        ctx.点击.assert_not_called()
        self.assertTrue(any("都城金币图标模板" in str(c.args[0]) for c in ctx.置脚本状态.call_args_list))

    def test_默认关闭且已注册(self):
        self.assertFalse(机器人设置().是否捐都城金币)
        self.assertIn("capital_donate", 任务计划定义映射)


class 都城流程测试(unittest.TestCase):
    def setUp(self):
        self.金币 = 随机图案(7, 20, 20)
        日常公共._图片缓存["测试/都城金币.png"] = self.金币
        self.图 = np.zeros((600, 800, 3), np.uint8)
        self.参数 = dict(
            都城模块.默认参数, calibrated=True, 都城入口=[100, 450], 捐献目标点=[400, 300],
            都城金币图标模板="测试/都城金币.png", 关闭捐献弹窗点=[50, 300],
        )

    def tearDown(self):
        日常公共._图片缓存.pop("测试/都城金币.png", None)

    def _任务(self, 余额="12,000", 确认文本="捐献", 有金币图标=True, 都城页=True, 捐献弹窗=True, **设置项):
        if 有金币图标:
            self.图[440:460, 330:350] = self.金币
        ctx = 上下文(self.图, **设置项)
        任务 = 都城捐金币任务(ctx, self.参数)
        p = self.参数
        任务.OCR = 假OCR([
            (lambda r: r == tuple(p["都城页确认区域"]), [("部落都城", (400, 40))] if 都城页 else []),
            (lambda r: r == tuple(p["都城金币余额区域"]), [(余额, (700, 30))]),
            (lambda r: r == tuple(p["捐献按钮区域"]), [("捐献", (400, 520))]),
            (lambda r: r == tuple(p["捐献弹窗确认区域"]),
             lambda: [("捐献", (400, 100))] if (捐献弹窗() if callable(捐献弹窗) else 捐献弹窗) else []),
            (lambda r: r == tuple(p["确认捐献按钮区域"]), [(确认文本, (400, 450))]),
            (lambda r: r == tuple(p["返回按钮区域"]), [("返回", (60, 560))]),
        ])
        return 任务, ctx

    def _点(self, ctx):
        return [c.args[:2] for c in ctx.点击.call_args_list]

    def test_完整流程(self):
        任务, ctx = self._任务()
        self.assertTrue(任务.执行())
        self.assertEqual(self._点(ctx), [(100, 450), (400, 300), (400, 520), (400, 450), (60, 560)])
        self.assertTrue(任务.已捐献)

    def test_没有都城金币图标不点确认(self):
        任务, ctx = self._任务(有金币图标=False)
        self.assertTrue(任务.执行())
        self.assertNotIn((400, 450), self._点(ctx))
        self.assertIn((50, 300), self._点(ctx))
        self.assertFalse(任务.已捐献)

    def test_确认按钮有宝石图标不点(self):
        宝石 = 日常公共.读取图片(日常公共.宝石图标路径)
        self.图[400:400 + 宝石.shape[0], 450:450 + 宝石.shape[1]] = 宝石
        任务, ctx = self._任务()
        self.assertTrue(任务.执行())
        self.assertNotIn((400, 450), self._点(ctx))

    def test_确认文字含宝石不点(self):
        任务, ctx = self._任务(确认文本="用宝石捐献")
        self.assertTrue(任务.执行())
        self.assertNotIn((400, 450), self._点(ctx))

    def test_余额低于起点不捐但正常返回(self):
        任务, ctx = self._任务(余额="500", 都城金币捐献起点=1000)
        self.assertTrue(任务.执行())
        self.assertEqual(self._点(ctx), [(100, 450), (60, 560)])

    def test_未确认都城页标记页面不可信(self):
        任务, ctx = self._任务(都城页=False)
        self.assertFalse(任务.执行())
        self.assertTrue(ctx.页面恢复失败)
        self.assertEqual(self._点(ctx), [(100, 450)])

    def test_关闭弹窗前确认失败不点关闭点(self):
        # 第一次 OCR 确认弹窗在（允许打开），关闭前重新确认时弹窗已不在。
        次数 = {"n": 0}

        def 弹窗在():
            次数["n"] += 1
            return 次数["n"] == 1

        任务, ctx = self._任务(有金币图标=False, 捐献弹窗=弹窗在)
        self.assertFalse(任务.执行())
        self.assertNotIn((50, 300), self._点(ctx))
        self.assertNotIn((60, 560), self._点(ctx))
        self.assertTrue(ctx.页面恢复失败)

    def test_停止后零点击且不标记失败(self):
        任务, ctx = self._任务()

        def 点击(x, y, **k):
            if (x, y) == (400, 520):
                ctx.停止事件 = SimpleNamespace(is_set=lambda: True)
            return True

        ctx.点击 = Mock(side_effect=点击)
        self.assertTrue(任务.执行())
        self.assertEqual(self._点(ctx), [(100, 450), (400, 300), (400, 520)])
        self.assertFalse(ctx.页面恢复失败)
        self.assertEqual(日常公共.读取任务记录(ctx.数据库, "t", "capital_donate"), {})

    def test_OCR不可用时确认按钮拒绝点击(self):
        任务, ctx = self._任务()
        原OCR = 任务.OCR
        p = self.参数
        任务_计数 = {"找到": False}

        def OCR(图, 区域):
            # 第一次（找确认按钮）正常；第二次（点击前护栏）OCR 崩溃。
            if tuple(区域) == tuple(p["确认捐献按钮区域"]) and 任务_计数["找到"]:
                raise 日常公共.OCR不可用("模拟 OCR 崩溃")
            结果 = 原OCR(图, 区域)
            if tuple(区域) == tuple(p["确认捐献按钮区域"]):
                任务_计数["找到"] = True
            return 结果

        任务.OCR = OCR
        self.assertTrue(任务.执行())
        self.assertNotIn((400, 450), self._点(ctx))
        self.assertFalse(任务.已捐献)



class 公共工具测试(unittest.TestCase):
    def test_解析数量(self):
        self.assertEqual(日常公共.解析数量("x12"), 12)
        self.assertEqual(日常公共.解析数量("1,234"), 1234)
        self.assertIsNone(日常公共.解析数量("abc"))

    def test_OCR偏移到全图坐标(self):
        ctx = 上下文()
        ctx.获取OCR引擎 = lambda: (lambda 图: ([([[0, 0], [10, 0], [10, 10], [0, 10]], "增 援", 0.9)], 0.1))
        任务 = 都城捐金币任务(ctx, dict(都城模块.默认参数))
        结果 = 任务.OCR(np.zeros((600, 800, 3), np.uint8), (100, 200, 300, 400))
        self.assertEqual(结果, [("增援", (105.0, 205.0))])


class 公共护栏测试(unittest.TestCase):
    """日常面板基类（C1/C2 共用）：OCR 不可用拒绝点击、停止后不点、真实截图宝石拦截。"""

    def _任务(self, 图=None):
        ctx = 上下文(图)
        return 都城捐金币任务(ctx, dict(都城模块.默认参数, calibrated=True)), ctx

    def test_OCR引擎缺失时护栏拒绝点击(self):
        任务, ctx = self._任务()
        self.assertFalse(任务.点击前护栏(np.zeros((600, 800, 3), np.uint8), (0, 0, 100, 100), "测试"))

    def test_OCR异常时护栏拒绝点击(self):
        任务, ctx = self._任务()

        def 坏引擎(图):
            raise RuntimeError("onnx 崩溃")

        ctx.获取OCR引擎 = lambda: 坏引擎
        self.assertFalse(任务.点击前护栏(np.zeros((600, 800, 3), np.uint8), (0, 0, 100, 100), "测试"))
        # 找按钮/确认页面时 OCR 不可用按“没找到”处理（不点）。
        self.assertIsNone(任务.区域有关键词(np.zeros((600, 800, 3), np.uint8), (0, 0, 100, 100), ["返回"]))

    def test_停止后点击与安全关闭都不发点击(self):
        任务, ctx = self._任务()
        ctx.停止事件 = SimpleNamespace(is_set=lambda: True)
        self.assertFalse(任务.点击(10, 10, "测试"))
        self.assertTrue(任务.安全关闭((10, 10), (0, 0, 100, 100), ["捐献"], "测试"))
        ctx.点击.assert_not_called()

    def test_安全关闭前确认失败不点(self):
        任务, ctx = self._任务()
        任务.OCR = 假OCR([])
        self.assertFalse(任务.安全关闭((10, 10), (0, 0, 100, 100), ["捐献"], "测试"))
        ctx.点击.assert_not_called()

    def test_关闭点有宝石图标不点(self):
        图 = np.zeros((600, 800, 3), np.uint8)
        宝石 = 日常公共.读取图片(日常公共.宝石图标路径)
        图[290:290 + 宝石.shape[0], 410:410 + 宝石.shape[1]] = 宝石
        任务, ctx = self._任务(图)
        任务.OCR = 假OCR([(lambda r: r == (0, 0, 100, 100), [("捐献", (50, 50))])])
        self.assertFalse(任务.安全关闭((420, 300), (0, 0, 100, 100), ["捐献"], "测试"))
        ctx.点击.assert_not_called()

    def test_真实主页截图宝石计数被拦截(self):
        图 = 读图("tests/fixtures/coc_home_18_647_5.png")
        任务, ctx = self._任务(图)
        任务.OCR = lambda 图_, 区域: []
        self.assertTrue(任务.点击前护栏(图, 日常公共.扩展区域((45, 310), 30, 30), "左侧按钮"))
        self.assertFalse(任务.点击前护栏(图, 日常公共.扩展区域((777, 156), 40, 30), "宝石计数"))


if __name__ == "__main__":
    unittest.main()
