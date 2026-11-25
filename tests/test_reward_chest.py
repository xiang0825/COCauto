"""胜利之星奖励宝箱：按实机截图校准的识别与敲开流程。"""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from 任务流程.主世界打鱼 import 奖励宝箱 as 宝箱

素材 = Path(__file__).parent / "fixtures" / "奖励宝箱"


def _读(名称):
    return cv2.imdecode(np.fromfile(str(素材 / 名称), np.uint8), cv2.IMREAD_COLOR)


def _框(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


class 宝箱页识别测试(unittest.TestCase):
    def test_实机截图的黄色擀面杖根数(self):
        self.assertEqual(宝箱.识别宝箱页(_读("宝箱页_4根.png")), 4)
        self.assertEqual(宝箱.识别宝箱页(_读("宝箱页_3根.png")), 3)
        self.assertEqual(宝箱.识别宝箱页(_读("宝箱页_1根.png")), 1)

    def test_奖励页和其他画面不是宝箱页(self):
        self.assertIsNone(宝箱.识别宝箱页(_读("奖励页_繼續.png")))
        self.assertIsNone(宝箱.识别宝箱页(np.zeros((600, 800, 3), np.uint8)))
        self.assertIsNone(宝箱.识别宝箱页(np.full((600, 800, 3), 200, np.uint8)))

    def test_定位继续按钮(self):
        结果 = [(_框(300, 440, 480, 470), "物品已運送到臨時倉庫。", 0.9),
              (_框(360, 500, 420, 525), "繼續", 0.95)]
        self.assertEqual(宝箱.定位继续按钮(结果), (390, 512))
        self.assertIsNone(宝箱.定位继续按钮([(_框(0, 0, 9, 9), "繼續", 0.9),
                                        (_框(0, 0, 9, 9), "使用寶石", 0.9)]))
        self.assertIsNone(宝箱.定位继续按钮([(_框(0, 0, 9, 9), "4倍戰鬥糕點", 0.9)]))


class 假上下文:
    """按点击推进画面：4 根 → 3 根 → 1 根（再敲不变）→ 开箱后奖励页。"""

    def __init__(self, 画面序列, 奖励页OCR=None, 回主世界=True):
        self.点击记录, self.延时记录, self.日志 = [], [], []
        self._画面 = list(画面序列)
        self._奖励页OCR = 奖励页OCR if 奖励页OCR is not None else [
            (_框(360, 500, 420, 525), "繼續", 0.95)]
        self._回主世界 = 回主世界
        self.op = SimpleNamespace(获取屏幕图像cv=self._截图)

    def _截图(self, *_a, **_k):
        return self._画面[0]

    def 获取OCR引擎(self):
        return lambda *_a, **_k: (self._奖励页OCR, None)

    def 点击已确认安全按钮(self, x, y, 延时=100):
        self.点击记录.append((x, y))
        if len(self._画面) > 1:
            self._画面.pop(0)
        return True

    def 脚本延时(self, 毫秒):
        self.延时记录.append(毫秒)

    def 置脚本状态(self, 文本, *_a, **_k):
        self.日志.append(文本)

    def 识别点击画面(self, 强制=False):
        return SimpleNamespace(页面="主世界主页" if self._回主世界 else "未知")


class 敲宝箱流程测试(unittest.TestCase):
    def setUp(self):
        self._旧目录 = os.getcwd()
        os.chdir(tempfile.mkdtemp())

    def tearDown(self):
        os.chdir(self._旧目录)

    def test_敲到3根_再敲3次_等3秒_点繼續_回主世界(self):
        四, 三, 一, 奖励 = (_读(n) for n in ("宝箱页_4根.png", "宝箱页_3根.png", "宝箱页_1根.png", "奖励页_繼續.png"))
        上下文 = 假上下文([四, 三, 一, 一, 奖励])
        self.assertTrue(宝箱.开启奖励宝箱(上下文))
        敲宝箱 = [点 for 点 in 上下文.点击记录 if 点 == 宝箱.宝箱点击点]
        self.assertEqual(len(敲宝箱), 1 + 3)           # 敲到 3 根 1 次 + 补敲 3 次
        self.assertEqual(上下文.点击记录[-1], (390, 512))  # 最后点“繼續”
        self.assertIn(3000, 上下文.延时记录)
        self.assertIn("回到主世界", 上下文.日志[-1])

    def test_领取后等宝箱页出现再敲(self):
        黑 = np.zeros((600, 800, 3), np.uint8)
        三, 一, 奖励 = (_读(n) for n in ("宝箱页_3根.png", "宝箱页_1根.png", "奖励页_繼續.png"))
        上下文 = 假上下文([黑, 三, 一, 奖励])
        原截图 = 上下文._截图
        次数 = [0]

        def 截图(*a, **k):  # 头两帧还是过场黑屏，之后出现宝箱页
            次数[0] += 1
            if 次数[0] == 2 and len(上下文._画面) > 1 and 上下文._画面[0] is 黑:
                上下文._画面.pop(0)
            return 原截图()
        上下文.op.获取屏幕图像cv = 截图
        self.assertTrue(宝箱.开启奖励宝箱(上下文, 等待出现秒=5.0))
        self.assertIn(500, 上下文.延时记录)

    def test_不是宝箱页什么都不点(self):
        上下文 = 假上下文([np.zeros((600, 800, 3), np.uint8)])
        self.assertFalse(宝箱.开启奖励宝箱(上下文))
        self.assertEqual(上下文.点击记录, [])

    def test_敲了不变化时有上限(self):
        四 = _读("宝箱页_4根.png")
        上下文 = 假上下文([四])
        self.assertFalse(宝箱.开启奖励宝箱(上下文))
        self.assertEqual(len(上下文.点击记录), 宝箱.最多敲击次数)

    def test_找不到繼續按钮不乱点(self):
        三, 奖励 = _读("宝箱页_3根.png"), _读("奖励页_繼續.png")
        上下文 = 假上下文([三, 奖励], 奖励页OCR=[])
        with patch.object(宝箱, "继续按钮等待秒", 0.01):
            self.assertFalse(宝箱.开启奖励宝箱(上下文))
        self.assertEqual(len(上下文.点击记录), 3)  # 只有补敲 3 次

    def test_奖励页有宝石字样不点(self):
        三, 奖励 = _读("宝箱页_3根.png"), _读("奖励页_繼續.png")
        上下文 = 假上下文([三, 奖励], 奖励页OCR=[(_框(0, 0, 9, 9), "繼續", 0.9),
                                            (_框(0, 0, 9, 9), "購買", 0.9)])
        with patch.object(宝箱, "继续按钮等待秒", 0.01):
            self.assertFalse(宝箱.开启奖励宝箱(上下文))


import threading


class 宝箱页识别补充测试(unittest.TestCase):
    def test_实机1280x720敲宝箱截图识别为4根(self):
        实机图 = _读("live_chest_tap_1280x720.png")
        self.assertEqual(实机图.shape[:2], (720, 1280))
        self.assertEqual(宝箱.识别宝箱页(实机图), 4)
        缩小图 = cv2.resize(实机图, (800, 600), interpolation=cv2.INTER_AREA)
        self.assertEqual(宝箱.识别宝箱页(缩小图), 4)

    def test_危险文字扩充覆盖商店充值与英文词(self):
        for 危险词 in ("商店", "立即完成", "充值", "儲值", "特惠", "禮包", "Store", "Buy Gems"):
            self.assertIsNone(
                宝箱.定位继续按钮([
                    (_框(360, 500, 420, 525), "繼續", 0.95),
                    (_框(100, 100, 200, 130), 危险词, 0.95),
                ]),
                f"未拦截危险文字: {危险词}",
            )


class 敲宝箱加固测试(unittest.TestCase):
    def setUp(self):
        self._旧目录 = os.getcwd()
        os.chdir(tempfile.mkdtemp())

    def tearDown(self):
        os.chdir(self._旧目录)

    def test_停止事件触发时立即中止且不继续点击(self):
        实机图 = _读("live_chest_tap_1280x720.png")
        三, 一, 奖励 = (_读(n) for n in ("宝箱页_3根.png", "宝箱页_1根.png", "奖励页_繼續.png"))

        # 1) 进入前已置位停止事件：0 次点击
        ctx1 = 假上下文([实机图, 三, 一, 奖励])
        ctx1.停止事件 = threading.Event()
        ctx1.停止事件.set()
        self.assertFalse(宝箱.开启奖励宝箱(ctx1))
        self.assertEqual(ctx1.点击记录, [])
        self.assertFalse(getattr(ctx1, "_正在开启奖励宝箱", False))

        # 2) 敲第 1 下时收到停止事件：立刻停止，不再继续敲
        ctx2 = 假上下文([实机图, 三, 一, 奖励])
        ctx2.停止事件 = threading.Event()
        原点击 = ctx2.点击已确认安全按钮

        def _点一次即停(x, y, 延时=100):
            原点击(x, y, 延时=延时)
            ctx2.停止事件.set()
            return True

        ctx2.点击已确认安全按钮 = _点一次即停
        self.assertFalse(宝箱.开启奖励宝箱(ctx2))
        self.assertEqual(len(ctx2.点击记录), 1)
        self.assertFalse(getattr(ctx2, "_正在开启奖励宝箱", False))

        # 3) 开箱等待 3 秒期间触发停止事件：不再调用 OCR 也不点繼續
        ctx3 = 假上下文([三, 一, 奖励])
        ctx3.停止事件 = threading.Event()
        ocr调用 = []
        ctx3.获取OCR引擎 = lambda: (lambda *_a, **_k: (ocr调用.append(1) or [], None))

        def _延时中断(毫秒):
            ctx3.延时记录.append(毫秒)
            if 毫秒 == 宝箱.开箱等待毫秒:
                ctx3.停止事件.set()

        ctx3.脚本延时 = _延时中断
        self.assertFalse(宝箱.开启奖励宝箱(ctx3))
        self.assertEqual(len(ctx3.点击记录), 3)
        self.assertEqual(ocr调用, [])
        self.assertFalse(getattr(ctx3, "_正在开启奖励宝箱", False))

    def test_开箱后衔接清理宝箱领奖页支持连续多页与宝石保护拦截(self):
        实机图 = _读("live_chest_tap_1280x720.png")
        三, 一, 奖励 = (_读(n) for n in ("宝箱页_3根.png", "宝箱页_1根.png", "奖励页_繼續.png"))

        # 1) 衔接上下文.清理宝箱领奖页完成连续多张领奖页后确认回到主世界
        ctx1 = 假上下文([实机图, 三, 一, 奖励])
        ctx1.停止事件 = threading.Event()
        ctx1.页面恢复失败 = True  # 模拟待命恢复前置失败状态，不应误阻断步骤3
        清理调用 = []

        def _清理多页(_图像=None):
            清理调用.append(True)
            ctx1._最近点击页面结果 = SimpleNamespace(页面="主世界主页")
            ctx1.页面恢复失败 = False
            return True

        ctx1.清理宝箱领奖页 = _清理多页
        self.assertTrue(宝箱.开启奖励宝箱(ctx1))
        self.assertEqual(len(清理调用), 1)
        self.assertFalse(ctx1.页面恢复失败)

        # 2) 中央宝石危险模板命中时绝不点击继续
        ctx2 = 假上下文([三, 奖励])
        ctx2.停止事件 = threading.Event()
        ctx2._存在中央宝石危险模板 = lambda _图: (True, "宝石.bmp@400,300")
        with patch.object(宝箱, "继续按钮等待秒", 0.05):
            self.assertFalse(宝箱.开启奖励宝箱(ctx2))
        self.assertEqual(len(ctx2.点击记录), 3)  # 仅补敲 3 次，未点击繼續

    def test_非底部居中继续文字或坐标畸形时拒绝定位与点击(self):
        # 1) 顶部、中央、左右侧出现的「繼續」或坐标解析失败绝不回退默认点
        for 非法项 in (
            [(_框(350, 70, 450, 110), "繼續", 0.95)],     # 屏幕上方
            [(_框(350, 260, 450, 300), "繼續", 0.95)],    # 屏幕中央教程/弹窗
            [(_框(40, 500, 140, 530), "繼續", 0.95)],     # 底部左侧
            [(_框(650, 500, 750, 530), "繼續", 0.95)],    # 底部右侧
            [(None, "繼續", 0.95)],                        # 坐标缺失
            [("bad-box", "繼續", 0.95)],                   # 坐标格式非法
            [([[float("nan"), 500], [420, 500], [420, 525], [360, 525]], "繼續", 0.95)],
            [(_框(100, 100, 700, 580), "繼續", 0.95)],    # 跨屏畸形大框中心落入底部
        ):
            self.assertIsNone(宝箱.定位继续按钮(非法项), f"误放行非法坐标: {非法项}")

        # 2) 实机 1280x720 奖励页缩放到 800x600 时真实位置仍可正常定位与点击
        三, 实机奖励 = _读("宝箱页_3根.png"), _读("live_reward_screen_1280x720.png")
        ctx_ok = 假上下文([三, 实机奖励], 奖励页OCR=[(_框(376, 501, 411, 529), "繼續", 0.95)])
        self.assertTrue(宝箱.开启奖励宝箱(ctx_ok))
        self.assertEqual(ctx_ok.点击记录[-1], (393, 515))

        # 3) 中央/上方弹窗出现「繼續」时，开启奖励宝箱拒绝点击继续按钮
        ctx_bad_ocr = 假上下文(
            [三, 实机奖励],
            奖励页OCR=[
                (_框(350, 80, 450, 120), "繼續", 0.95),
                (_框(350, 260, 450, 300), "继续", 0.95),
            ],
        )
        with patch.object(宝箱, "继续按钮等待秒", 0.05):
            self.assertFalse(宝箱.开启奖励宝箱(ctx_bad_ocr))
        self.assertEqual(len(ctx_bad_ocr.点击记录), 3)  # 仅补敲 3 次，绝不点繼續

    def test_非宝箱领奖页即使底部出现继续OCR也绝不回退点击(self):
        三 = _读("宝箱页_3根.png")
        # 构造非奖励页画面（带中央弹窗与底部绿色按钮色块，但非宝箱木桌领奖页）
        未知教程页 = np.full((600, 800, 3), 50, np.uint8)
        cv2.rectangle(未知教程页, (180, 130), (620, 420), (235, 235, 235), -1)
        cv2.rectangle(未知教程页, (330, 488), (455, 542), (60, 200, 80), -1)

        # 1) 无清理宝箱领奖页回调（仅走奖励宝箱内置回退校验）
        ctx1 = 假上下文([三, 未知教程页], 奖励页OCR=[(_框(360, 500, 420, 525), "繼續", 0.95)])
        with patch.object(宝箱, "继续按钮等待秒", 0.05):
            self.assertFalse(宝箱.开启奖励宝箱(ctx1))
        self.assertEqual(len(ctx1.点击记录), 3)  # 仅补敲 3 次，未点击繼續

        # 2) 有清理宝箱领奖页但返回 False（页面识别为非宝箱领奖页），也严禁回退点击
        ctx2 = 假上下文([三, 未知教程页], 奖励页OCR=[(_框(360, 500, 420, 525), "繼續", 0.95)])
        清理调用 = []
        ctx2.清理宝箱领奖页 = lambda _图像=None: (清理调用.append(True) or False)
        with patch.object(宝箱, "继续按钮等待秒", 0.05):
            self.assertFalse(宝箱.开启奖励宝箱(ctx2))
        self.assertGreaterEqual(len(清理调用), 1)
        self.assertEqual(len(ctx2.点击记录), 3)  # 绝不调用点击已确认安全按钮点繼續


if __name__ == "__main__":
    unittest.main()
