"""B 自动捐兵 / C1 都城捐金币：未校准拒绝、宝石护栏、保留规则、只用都城金币。"""
import pathlib
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.日常 import 日常公共
from 任务流程.日常 import 捐兵 as 捐兵模块
from 任务流程.日常 import 都城捐金币 as 都城模块
from 任务流程.日常.捐兵 import 捐兵任务, 可捐, 主力单位
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
                结果.extend((日常公共.规范文本(文), 心) for 文, 心 in 项)
        return 结果


# ================================================================== B 捐兵
class 捐兵前置测试(unittest.TestCase):
    def test_未配置目标跳过不点击(self):
        ctx = 上下文()
        任务 = 捐兵任务(ctx, dict(捐兵模块.默认参数, calibrated=True))
        self.assertTrue(任务.执行())
        ctx.点击.assert_not_called()

    def test_未校准即使勾选也拒绝运行(self):
        ctx = 上下文(是否自动捐兵=True, 捐兵兵种=["野蛮人"])
        任务 = 捐兵任务(ctx, dict(捐兵模块.默认参数))
        self.assertTrue(任务.执行())
        ctx.点击.assert_not_called()
        self.assertTrue(any("尚未实机校准" in str(c.args[0]) for c in ctx.置脚本状态.call_args_list))

    def test_仓库自带JSON未校准(self):
        self.assertFalse(日常公共.已校准(捐兵模块.读取参数()))

    def test_冷却中不点击(self):
        ctx = 上下文(捐兵兵种=["野蛮人"])
        日常公共.写入任务记录(ctx.数据库, "t", "donate_troops", {"日期": 日常公共.今天(), "下次检查时间": time.time() + 600})
        任务 = 捐兵任务(ctx, dict(捐兵模块.默认参数, calibrated=True))
        self.assertTrue(任务.执行())
        ctx.点击.assert_not_called()


class 保留规则测试(unittest.TestCase):
    def test_主力兵保留数量(self):
        设置 = 机器人设置(配兵兵种=["野蛮人"], 捐兵主力保留数量=5)
        self.assertIn("野蛮人", 主力单位(设置))
        self.assertFalse(可捐("野蛮人", 5, 设置))
        self.assertTrue(可捐("野蛮人", 6, 设置))
        self.assertTrue(可捐("弓箭手", 1, 设置))
        self.assertFalse(可捐("弓箭手", 0, 设置))
        self.assertFalse(可捐("弓箭手", None, 设置))

    def test_阵容预设里的单位也算主力(self):
        from 任务流程.军队配置.阵容预设 import 预设列表

        预设 = 预设列表[0]
        设置 = 机器人设置(阵容预设=预设.名称, 捐兵主力保留数量=3)
        单位 = next(iter(预设.兵种权重))
        self.assertIn(单位, 主力单位(设置))
        self.assertFalse(可捐(单位, 3, 设置))

    def test_设置清洗未知兵种(self):
        设置 = 机器人设置(捐兵兵种=["野蛮人", "不存在", "野蛮人"], 捐兵法术=["闪电法术", "x"])
        self.assertEqual(设置.捐兵兵种, ["野蛮人"])
        self.assertEqual(设置.捐兵法术, ["闪电法术"])
        self.assertFalse(机器人设置().是否自动捐兵)
        self.assertIn("donate_troops", 任务计划定义映射)


class 捐兵流程测试(unittest.TestCase):
    """合成画面：在弹窗格子区放一个兵种图案，OCR 由假函数给出。"""

    def setUp(self):
        self.模板 = 随机图案(1, 20, 20)
        日常公共._图片缓存["测试/野蛮人.png"] = self.模板
        self.图 = np.zeros((600, 800, 3), np.uint8)
        self.图[310:330, 510:530] = self.模板  # 格子中心 (520, 320)
        self.参数 = dict(捐兵模块.默认参数, calibrated=True, 兵种模板={"野蛮人": "测试/野蛮人.png"},
                       每个请求最多点击=3)

    def tearDown(self):
        日常公共._图片缓存.pop("测试/野蛮人.png", None)

    def _任务(self, 数量文本="x9", 增援=True, 弹窗=True, 聊天=True, **设置项):
        ctx = 上下文(self.图, 捐兵兵种=["野蛮人"], **设置项)
        任务 = 捐兵任务(ctx, self.参数)
        已点增援 = {"n": 0}
        原点击 = ctx.点击

        def 点击(x, y, **k):
            if (x, y) == (60, 200):
                已点增援["n"] += 1
            return 原点击(x, y, **k)

        ctx.点击 = Mock(side_effect=点击)
        p = self.参数
        任务.OCR = 假OCR([
            (lambda r: r == tuple(p["聊天面板确认区域"]), [("部落", (50, 20))] if 聊天 else []),
            (lambda r: r == tuple(p["请求列表区域"]),
             [("增援", (60, 200))] if 增援 and 已点增援["n"] == 0 else []),
            (lambda r: r == tuple(p["捐兵弹窗确认区域"]), [("部落增援", (600, 40))] if 弹窗 else []),
            # 数量文字在格子中心上方 (520, 295)：数量 OCR 与格子护栏 OCR 都会读到。
            (lambda r: r[0] <= 520 <= r[2] and r[1] <= 295 <= r[3] and r[2] - r[0] < 100,
             [(数量文本, (520, 295))]),
        ])
        return 任务, ctx

    def _点击点(self, ctx):
        return [c.args[:2] for c in ctx.点击.call_args_list]

    def test_完整流程只点聊天增援格子和关闭点(self):
        任务, ctx = self._任务()
        self.assertTrue(任务.执行())
        点 = self._点击点(ctx)
        self.assertEqual(点[0], (45, 310))
        self.assertEqual(点[1], (60, 200))
        self.assertEqual(点.count((520, 320)), 3)  # 每个请求最多点击 3
        self.assertEqual(点[-2:], [(200, 300), (420, 300)])
        self.assertEqual(任务.本轮捐出, 3)
        记录 = 日常公共.读取任务记录(ctx.数据库, "t", "donate_troops")
        self.assertEqual(记录["今日捐出"], 3)

    def test_主力兵数量不足不捐(self):
        任务, ctx = self._任务(数量文本="x5", 配兵兵种=["野蛮人"], 捐兵主力保留数量=5)
        self.assertTrue(任务.执行())
        self.assertNotIn((520, 320), self._点击点(ctx))

    def test_数量读不出不捐(self):
        任务, ctx = self._任务(数量文本="??")
        self.assertTrue(任务.执行())
        self.assertNotIn((520, 320), self._点击点(ctx))

    def test_格子有宝石图标不点(self):
        宝石 = 日常公共.读取图片(日常公共.宝石图标路径)
        self.图[322:322 + 宝石.shape[0], 524:524 + 宝石.shape[1]] = 宝石
        任务, ctx = self._任务()
        self.assertTrue(任务.执行())
        self.assertNotIn((520, 320), self._点击点(ctx))

    def test_格子文字含宝石不点(self):
        任务, ctx = self._任务(数量文本="50宝石")
        self.assertTrue(任务.执行())
        self.assertNotIn((520, 320), self._点击点(ctx))

    def test_没有模板的兵种不点(self):
        self.参数["兵种模板"] = {}
        任务, ctx = self._任务()
        self.assertTrue(任务.执行())
        self.assertNotIn((520, 320), self._点击点(ctx))

    def test_聊天面板未确认则停止并标记页面不可信(self):
        任务, ctx = self._任务(聊天=False)
        self.assertFalse(任务.执行())
        self.assertTrue(ctx.页面恢复失败)
        self.assertEqual(self._点击点(ctx), [(45, 310)])

    def test_捐兵弹窗未确认则停止(self):
        任务, ctx = self._任务(弹窗=False)
        self.assertFalse(任务.执行())
        self.assertNotIn((520, 320), self._点击点(ctx))

    def test_含危险词的增援按钮不点(self):
        任务, ctx = self._任务()
        p = self.参数
        任务.OCR = 假OCR([
            (lambda r: r == tuple(p["聊天面板确认区域"]), [("部落", (50, 20))]),
            (lambda r: r == tuple(p["请求列表区域"]), [("宝石增援", (60, 200))]),
        ])
        self.assertTrue(任务.执行())
        self.assertNotIn((60, 200), self._点击点(ctx))


class 捐兵回放测试(unittest.TestCase):
    """真实主页截图：右上宝石计数会被护栏拦下，左侧聊天按钮区域不会。"""

    def test_真实主页宝石图标拦截(self):
        图 = 读图("tests/fixtures/coc_home_18_647_5.png")
        ctx = 上下文(图)
        任务 = 捐兵任务(ctx, dict(捐兵模块.默认参数, calibrated=True))
        任务.OCR = lambda 图_, 区域: []
        self.assertTrue(任务.点击前护栏(图, 日常公共.扩展区域((45, 310), 30, 30), "聊天按钮"))
        self.assertFalse(任务.点击前护栏(图, 日常公共.扩展区域((777, 156), 40, 30), "宝石计数"))


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

    def _任务(self, 余额="12,000", 确认文本="捐献", 有金币图标=True, 都城页=True, **设置项):
        if 有金币图标:
            self.图[440:460, 330:350] = self.金币
        ctx = 上下文(self.图, **设置项)
        任务 = 都城捐金币任务(ctx, self.参数)
        p = self.参数
        任务.OCR = 假OCR([
            (lambda r: r == tuple(p["都城页确认区域"]), [("部落都城", (400, 40))] if 都城页 else []),
            (lambda r: r == tuple(p["都城金币余额区域"]), [(余额, (700, 30))]),
            (lambda r: r == tuple(p["捐献按钮区域"]), [("捐献", (400, 520))]),
            (lambda r: r == tuple(p["捐献弹窗确认区域"]), [("捐献", (400, 100))]),
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


class 公共工具测试(unittest.TestCase):
    def test_解析数量(self):
        self.assertEqual(日常公共.解析数量("x12"), 12)
        self.assertEqual(日常公共.解析数量("1,234"), 1234)
        self.assertIsNone(日常公共.解析数量("abc"))

    def test_OCR偏移到全图坐标(self):
        ctx = 上下文()
        ctx.获取OCR引擎 = lambda: (lambda 图: ([([[0, 0], [10, 0], [10, 10], [0, 10]], "增 援", 0.9)], 0.1))
        任务 = 捐兵任务(ctx, dict(捐兵模块.默认参数))
        结果 = 任务.OCR(np.zeros((600, 800, 3), np.uint8), (100, 200, 300, 400))
        self.assertEqual(结果, [("增援", (105.0, 205.0))])


if __name__ == "__main__":
    unittest.main()
