import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest.mock
import importlib

import cv2
import numpy as np

from 任务流程.主世界打鱼.打开进攻页面 import 打开进攻页面任务
from 任务流程.主世界打鱼 import 主世界打鱼任务
from 任务流程.主世界打鱼.搜索页面识别 import 搜索页面识别器
from 任务流程.主世界打鱼.进攻 import 进攻任务
from 任务流程.夜世界.夜世界打鱼.打开进攻页面任务 import 打开进攻页面


class 打开进攻页面测试(unittest.TestCase):
    def test_入口收到停止请求时不发送任何点击(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        停止事件 = threading.Event()
        停止事件.set()
        上下文 = SimpleNamespace(
            停止事件=停止事件,
            置脚本状态=Mock(),
            点击=Mock(),
        )
        任务.上下文 = 上下文

        self.assertFalse(任务.执行())
        上下文.点击.assert_not_called()
        self.assertTrue(
            any("禁止发送入口点击" in 调用.args[0]
                for 调用 in 上下文.置脚本状态.call_args_list)
        )

    @staticmethod
    def 军队配置画面():
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 军队配置页中央的浅色面板是攻击按钮的联合证据。
        cv2.rectangle(画面, (100, 80), (700, 520), (205, 205, 205), -1)
        # 与当前 CoC 绿色“攻击!”按钮相同的高饱和黄绿色区域。
        cv2.rectangle(画面, (630, 515), (780, 555), (73, 227, 154), -1)
        return 画面

    @staticmethod
    def 攻击选择画面():
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 选择面板左下的“寻找战斗目标”橙色按钮。
        cv2.rectangle(画面, (46, 409), (227, 482), (44, 173, 249), -1)
        return 画面

    def test_主世界右下绿色区域不会被当成军队页攻击按钮(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        画面[:, :] = (40, 115, 55)
        cv2.rectangle(画面, (630, 515), (780, 555), (73, 227, 154), -1)
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)

        self.assertIsNone(任务._检测攻击按钮(画面))

    def test_攻击按钮使用动态识别而不是固定坐标(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        结果 = 任务._检测攻击按钮(self.军队配置画面())
        self.assertIsNotNone(结果)
        self.assertAlmostEqual(结果[0], 705, delta=3)
        self.assertAlmostEqual(结果[1], 535, delta=3)

    def test_军队容量OCR只提取主军队容量(self):
        OCR结果 = (
            [
                [None, "352/352", 0.99],
                [None, "11/11", 0.99],
                [None, "3/3", 0.99],
            ],
            [1.0, 1.0, 1.0],
        )
        self.assertEqual(
            打开进攻页面任务._从军队容量OCR提取(OCR结果),
            (352, 352),
        )

    def test_军队容量未满时阻止攻击并请求等待(self):
        OCR引擎 = Mock(return_value=(
            [[[0, 0], "120/352", 0.99]],
            [1.0],
        ))
        上下文 = SimpleNamespace(
            获取OCR引擎=Mock(return_value=OCR引擎),
            请求任务计划等待=Mock(),
            置脚本状态=Mock(),
        )
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        任务._军队容量上次检查时间 = 0.0

        self.assertFalse(任务._检查军队容量(
            上下文, np.zeros((600, 800, 3), dtype=np.uint8)
        ))
        self.assertTrue(上下文._军队未满待机)
        上下文.请求任务计划等待.assert_called_once_with(60, "军队容量未满")
        self.assertTrue(any(
            "120/352" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_攻击选择面板动态识别寻找目标按钮(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        结果 = 任务._检测寻找目标按钮(self.攻击选择画面())
        self.assertIsNotNone(结果)
        self.assertAlmostEqual(结果[0], 137, delta=5)
        self.assertAlmostEqual(结果[1], 445, delta=5)

    def test_先点击寻找目标再点击军队页攻击按钮(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        页面状态 = iter((
            SimpleNamespace(页面="未知"),
            SimpleNamespace(页面="未知"),
            SimpleNamespace(页面="战斗中"),
        ))
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(
                    side_effect=[self.攻击选择画面(), self.军队配置画面(), self.军队配置画面()]
                )
            ),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            识别点击画面=Mock(side_effect=lambda **_: next(页面状态)),
        )
        任务.模板识别 = Mock()

        self.assertTrue(任务._等待并点击攻击按钮(上下文))
        self.assertEqual(
            上下文.点击.call_args_list,
            [
                unittest.mock.call(137, 446, 延时=700, 是否精确点击=True),
                unittest.mock.call(705, 535, 延时=700, 是否精确点击=True),
            ],
        )

    def test_夜世界进攻入口点击被拒绝时不继续识别下一页(self):
        任务 = 打开进攻页面.__new__(打开进攻页面)
        上下文 = SimpleNamespace(
            点击=Mock(return_value=False),
            置脚本状态=Mock(),
        )
        任务.上下文 = 上下文
        任务.是否出现开始进攻 = Mock(return_value=True)

        self.assertFalse(任务.执行())
        任务.是否出现开始进攻.assert_not_called()

    def test_点击后必须确认进入搜索页面(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=self.军队配置画面())
            ),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        with patch.object(
            任务, "_是否出现下一个", side_effect=[False, True, True]
        ):
            self.assertTrue(任务._等待并点击攻击按钮(上下文))

        上下文.点击.assert_called_once_with(
            705, 535, 延时=700, 是否精确点击=True
        )

    def test_主世界入口无响应时只在主页证据下有限重试(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        页面识别 = SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.78)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))
            ),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            识别点击画面=Mock(return_value=页面识别),
        )
        任务.模板识别 = Mock()
        任务.主世界入口重试间隔秒 = 0
        任务._识别已存在的战斗页面 = Mock(
            side_effect=[None, None, None, "战斗中"]
        )
        任务._是否出现下一个 = Mock(return_value=False)
        任务._检测寻找目标按钮 = Mock(side_effect=[None, (137, 445)])
        任务._检测攻击按钮 = Mock(side_effect=[None, (705, 535)])

        self.assertTrue(任务._等待并点击攻击按钮(上下文, 主世界入口已点击=True))
        self.assertEqual(
            上下文.点击.call_args_list,
            [
                unittest.mock.call(62, 546, 700, 是否精确点击=True),
                unittest.mock.call(137, 445, 延时=700, 是否精确点击=True),
                unittest.mock.call(705, 535, 延时=700, 是否精确点击=True),
            ],
        )
        self.assertTrue(any("安全重试" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_启动时已经在战斗页不再点击主世界入口(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            识别点击画面=Mock(
                return_value=SimpleNamespace(页面="战斗中")
            ),
            点击=Mock(),
            停止事件=threading.Event(),
        )

        任务.上下文 = 上下文
        self.assertTrue(任务.执行())
        self.assertTrue(上下文._入口已进入战斗)
        上下文.点击.assert_not_called()

    def test_未连续确认主世界主页时阻止入口点击(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            识别点击画面=Mock(
                side_effect=[
                    SimpleNamespace(
                        页面="夜世界主页", 世界="夜世界", 可信度=0.78
                    ),
                    SimpleNamespace(页面="未知", 世界=None, 可信度=0.0),
                ]
            ),
            脚本延时=Mock(),
            点击=Mock(),
        )

        self.assertFalse(任务._确认主世界主页(上下文))
        上下文.点击.assert_not_called()

    def test_连续两帧主世界主页才允许入口点击(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            识别点击画面=Mock(
                side_effect=[
                    SimpleNamespace(
                        页面="主世界主页", 世界="主世界", 可信度=0.78
                    ),
                    SimpleNamespace(
                        页面="主世界主页", 世界="主世界", 可信度=0.78
                    ),
                ]
            ),
            脚本延时=Mock(),
        )

        self.assertTrue(任务._确认主世界主页(上下文))

    def test_攻击按钮点击后直接进入战斗会交给下兵流程(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        页面状态 = iter((
            SimpleNamespace(页面="未知"),
            SimpleNamespace(页面="战斗中"),
        ))
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=self.军队配置画面())
            ),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            识别点击画面=Mock(side_effect=lambda **_: next(页面状态)),
        )

        self.assertTrue(任务._等待并点击攻击按钮(上下文))
        self.assertTrue(上下文._入口已进入战斗)
        self.assertEqual(上下文.本场资源评分状态, "不可用")
        self.assertIsNone(上下文.本场目标战利品["资源易窃取评分"])
        self.assertIn("直接进入战斗", 上下文.本场资源评分说明)
        上下文.点击.assert_called_once_with(
            705, 535, 延时=700, 是否精确点击=True
        )

    def test_搜索页下一個按钮优先于结束战斗特征(self):
        """搜索页也有结束战斗按钮，必须先走资源评分而不是直接下兵。"""
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=self.军队配置画面())
            ),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务._是否出现下一个 = Mock(side_effect=[True, True])
        任务._识别已存在的战斗页面 = Mock(return_value="战斗中")
        任务._最近搜索页识别依据 = "按钮区域"
        任务._最近搜索页识别分数 = 0.91
        任务._标记本场资源评分不可用 = Mock()

        self.assertTrue(任务._等待并点击攻击按钮(上下文))
        self.assertEqual(上下文.本场资源评分状态, "待评分")
        self.assertIn("已确认敌方搜索页", 上下文.本场资源评分说明)
        任务._识别已存在的战斗页面.assert_not_called()
        任务._标记本场资源评分不可用.assert_not_called()
        上下文.点击.assert_not_called()

    def test_攻击后结算过渡单帧不会跳过下兵(self):
        """攻击点击后的结算视觉过渡帧必须等下一帧，不能误判为已结算。"""
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        页面状态 = iter((
            None,          # 军队配置页，允许点击攻击
            "战斗结算",    # 上一场结果层残留
            "战斗结算",    # 即使连续命中也不能跳过本场下兵
            "战斗中",      # 下一帧真实战斗页
        ))
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=self.军队配置画面())
            ),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务._识别已存在的战斗页面 = Mock(
            side_effect=lambda *args, **kwargs: next(页面状态)
        )
        任务._检测攻击按钮 = Mock(side_effect=[(705, 535), None, None, None])
        任务._检测寻找目标按钮 = Mock(return_value=None)
        任务._是否出现下一个 = Mock(return_value=False)

        self.assertTrue(任务._等待并点击攻击按钮(上下文))
        self.assertTrue(上下文._入口已进入战斗)
        self.assertFalse(getattr(上下文, "_入口已进入结算", False))
        self.assertTrue(any(
            "攻击后出现战斗结算视觉过渡层" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))
        上下文.点击.assert_called_once_with(
            705, 535, 延时=700, 是否精确点击=True
        )

    def test_入口轻量结算识别会登记宝石跨帧保护(self):
        """入口识别到结算时，基础护栏不得把同一过渡帧误当宝石页。"""
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        识别器 = Mock()
        识别器.识别.return_value = SimpleNamespace(页面="战斗结算")
        上下文 = SimpleNamespace(
            _获取点击页面识别器=Mock(return_value=识别器),
            置脚本状态=Mock(),
        )

        结果 = 任务._识别已存在的战斗页面(
            上下文,
            屏幕图像=np.zeros((600, 800, 3), dtype=np.uint8),
        )

        self.assertEqual(结果, "战斗结算")
        self.assertGreater(
            getattr(上下文, "_最近结算视觉时间", 0.0),
            0.0,
        )
        self.assertFalse(getattr(上下文, "_结算视觉跨帧阻断日志", True))
        识别器.识别.assert_called_once_with(
            unittest.mock.ANY,
            战斗中=False,
        )

    def test_点击寻找目标后不再关闭主页弹窗(self):
        """攻击流程开始后，过渡帧不能再次触发升级/宝石恢复输入。"""
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        页面状态 = iter((None, None, "战斗中"))
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))
            ),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            关闭升级详情弹窗=Mock(return_value=False),
            停止事件=threading.Event(),
        )
        任务._是否出现下一个 = Mock(return_value=False)
        任务._识别已存在的战斗页面 = Mock(
            side_effect=lambda *args, **kwargs: next(页面状态)
        )
        任务._检测寻找目标按钮 = Mock(side_effect=[(137, 445), None, None])
        任务._检测攻击按钮 = Mock(return_value=None)

        self.assertTrue(任务._等待并点击攻击按钮(上下文))
        上下文.关闭升级详情弹窗.assert_called_once()
        上下文.点击.assert_called_once_with(
            137, 445, 延时=700, 是否精确点击=True
        )

    def test_直接点击军队攻击后不再点击寻找目标(self):
        """军队页攻击已发出后，不能把过渡帧上的橙色区域当入口。"""
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        页面状态 = iter((None, None, "战斗中"))
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))
            ),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            关闭升级详情弹窗=Mock(return_value=False),
            停止事件=threading.Event(),
        )
        任务._是否出现下一个 = Mock(return_value=False)
        任务._识别已存在的战斗页面 = Mock(
            side_effect=lambda *args, **kwargs: next(页面状态)
        )
        任务._检测寻找目标按钮 = Mock(side_effect=[None, (137, 445)])
        任务._检测攻击按钮 = Mock(side_effect=[(705, 535), None, None])

        self.assertTrue(任务._等待并点击攻击按钮(上下文))
        任务._检测寻找目标按钮.assert_called_once()
        上下文.点击.assert_called_once_with(
            705, 535, 延时=700, 是否精确点击=True
        )

    def test_攻击点击后护栏短暂返回False但已进入战斗仍继续(self):
        """真实点击已切入战斗时，不能因结算跨帧把任务链提前终止。"""
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        页面状态 = iter((
            SimpleNamespace(页面="战斗结算"),
            SimpleNamespace(页面="战斗中"),
        ))
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=self.军队配置画面())
            ),
            点击=Mock(return_value=False),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            识别点击画面=Mock(side_effect=lambda **_: next(页面状态)),
        )
        任务._识别已存在的战斗页面 = Mock(side_effect=[None, "战斗中"])
        任务._检测攻击按钮 = Mock(side_effect=[(705, 535), None, None])
        任务._检测寻找目标按钮 = Mock(return_value=None)
        任务._是否出现下一个 = Mock(return_value=False)

        self.assertTrue(任务._等待并点击攻击按钮(上下文))
        self.assertTrue(上下文._入口已进入战斗)
        self.assertTrue(any(
            "按已进入攻击流程继续复核" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))
        上下文.点击.assert_called_once_with(
            705, 535, 延时=700, 是否精确点击=True
        )

    def test_入口超时边界仍在战斗时交给下兵流程(self):
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        上下文 = SimpleNamespace(
            停止事件=threading.Event(),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务._识别已存在的战斗页面 = Mock(return_value="战斗中")
        任务._标记本场资源评分不可用 = Mock()

        self.assertTrue(任务._超时后接管已进入战斗(上下文, True, False))
        self.assertTrue(上下文._入口已进入战斗)
        任务._标记本场资源评分不可用.assert_called_once()
        self.assertTrue(any(
            "超时边界确认仍在战斗页" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_入口超时边界沿用本轮已确认战斗证据(self):
        """避免已看到战斗页后因过渡帧把入口误报失败。"""
        任务 = 打开进攻页面任务.__new__(打开进攻页面任务)
        上下文 = SimpleNamespace(
            停止事件=threading.Event(),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            _进攻入口最近确认战斗时间=time.monotonic(),
        )

        任务._识别已存在的战斗页面 = Mock(return_value=None)

        self.assertTrue(任务._超时后接管已进入战斗(上下文, True, False))
        self.assertTrue(上下文._入口已进入战斗)
        任务._识别已存在的战斗页面.assert_not_called()
        self.assertTrue(any(
            "沿用本轮已确认的战斗页" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_新一场开始会清除上一场资源评分(self):
        上下文 = SimpleNamespace(
            本场目标战利品={"金币": 900000},
            本场资源易窃取评分=8.8,
            本场资源评估={"评分依据": "旧目标"},
            本场资源评分状态="已完成",
            本场资源评分说明="旧目标",
        )

        主世界打鱼任务._重置本场目标评估(上下文)

        self.assertEqual(上下文.本场目标战利品, {})
        self.assertIsNone(上下文.本场资源易窃取评分)
        self.assertEqual(上下文.本场资源评估, {})
        self.assertEqual(上下文.本场资源评分状态, "未确认")

    def test_主世界打鱼任务出口未确认主世界时禁止下一轮(self):
        """回营子任务误报成功时，外层任务仍不能放行下一轮。"""
        主世界打鱼模块 = importlib.import_module("任务流程.主世界打鱼.__init__")
        执行顺序 = []

        class 假子任务:
            def __init__(自身, 名称):
                自身.名称 = 名称

            def 执行(自身):
                执行顺序.append(自身.名称)
                return True

        class 假回营任务(假子任务):
            def 等待主界面就绪(自身, _上下文):
                return False

        上下文 = SimpleNamespace(
            机器人标志="robot_1",
            数据库=SimpleNamespace(),
            置脚本状态=Mock(),
            _入口已进入结算=True,
        )
        with patch.object(
            主世界打鱼模块,
            "打开进攻页面任务",
            side_effect=lambda _上下文: 假子任务("入口"),
        ), patch.object(
            主世界打鱼模块,
            "搜索目标敌人任务",
            side_effect=lambda _上下文: 假子任务("搜索"),
        ), patch.object(
            主世界打鱼模块,
            "进攻任务",
            side_effect=lambda _上下文: 假子任务("进攻"),
        ), patch.object(
            主世界打鱼模块,
            "等待战斗结束并回营任务",
            side_effect=lambda _上下文: 假回营任务("回营"),
        ):
            任务 = 主世界打鱼模块.主世界打鱼任务(上下文)
            self.assertFalse(任务.执行())

        self.assertEqual(执行顺序, ["入口", "搜索", "进攻", "回营"])
        self.assertTrue(上下文._入口已进入结算)
        self.assertIn(
            "主世界打鱼任务出口未连续确认主世界，禁止开始下一轮",
            [调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list],
        )

    def test_军队未满时主世界任务跳过搜索和下兵(self):
        主世界打鱼模块 = importlib.import_module("任务流程.主世界打鱼.__init__")
        执行顺序 = []

        class 假入口任务:
            def __init__(自身, _上下文):
                pass

            def 执行(自身):
                执行顺序.append("入口")
                上下文._军队未满待机 = True
                return True

        class 不应执行任务:
            def __init__(自身, _上下文):
                pass

            def 执行(自身):
                执行顺序.append("错误执行")
                return True

        上下文 = SimpleNamespace(
            机器人标志="robot_1",
            数据库=SimpleNamespace(),
            置脚本状态=Mock(),
            请求任务计划等待=Mock(),
        )
        with patch.object(
            主世界打鱼模块, "打开进攻页面任务", 假入口任务
        ), patch.object(
            主世界打鱼模块, "搜索目标敌人任务", 不应执行任务
        ), patch.object(
            主世界打鱼模块, "进攻任务", 不应执行任务
        ), patch.object(
            主世界打鱼模块, "等待战斗结束并回营任务", 不应执行任务
        ):
            任务 = 主世界打鱼模块.主世界打鱼任务(上下文)
            self.assertTrue(任务.执行())

        self.assertEqual(执行顺序, ["入口"])
        上下文.请求任务计划等待.assert_called_once_with(60, "军队容量未满")
        # 保留给外层资源计划消费；外层处理后才会清除该标志。
        self.assertTrue(getattr(上下文, "_军队未满待机", False))

    def test_繁体下一個按钮通过颜色和位置识别(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 模拟实机搜索页的橙黄色“下一個”按钮；文字繁简不影响识别。
        cv2.rectangle(画面, (664, 389), (793, 466), (80, 190, 245), -1)
        命中, 中心, 依据, 分数 = 搜索页面识别器.查找下一个按钮(画面)
        self.assertTrue(命中)
        self.assertAlmostEqual(中心[0], 729, delta=5)
        self.assertAlmostEqual(中心[1], 428, delta=5)
        self.assertIn("按钮", 依据)
        self.assertGreaterEqual(分数, 0.30)

    def test_军队页底部攻击按钮不被当成下一個按钮(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(画面, (630, 515), (780, 555), (73, 227, 154), -1)
        命中, _, _, _ = 搜索页面识别器.查找下一个按钮(画面)
        self.assertFalse(命中)

    def test_兵栏第一格避开结束战斗按钮并覆盖当前实机卡牌(self):
        第一格 = 进攻任务.兵栏槽位[0][1]
        第二格 = 进攻任务.兵栏槽位[1][1]
        self.assertGreaterEqual(第一格[0], 50)
        self.assertLessEqual(第一格[1], 500)
        self.assertGreater(第二格[0], 第一格[0])
        self.assertEqual(len(进攻任务.兵栏槽位), 8)

    def test_兵栏空槽OCR的XO不会把等级读成兵量(self):
        任务 = 进攻任务.__new__(进攻任务)
        self.assertEqual(任务._识别槽位数量(np.zeros((20, 20, 3), dtype=np.uint8), "XO|12"), 0)

    def test_夜世界开始进攻兼容简体和繁体OCR(self):
        self.assertTrue(打开进攻页面._OCR包含文本(
            [[[[0, 0], [100, 0], [100, 30], [0, 30]], "開始進攻", 0.93]],
            ("开始进攻", "開始進攻"),
        ))
        self.assertTrue(打开进攻页面._OCR包含文本(
            [[[[0, 0], [100, 0], [100, 30], [0, 30]], "开始进攻", 0.93]],
            ("开始进攻", "開始進攻"),
        ))

    def test_夜世界立即寻找按钮补回OCR裁剪偏移(self):
        任务 = 打开进攻页面.__new__(打开进攻页面)
        任务.执行OCR识别 = Mock(return_value=[
            [[[150, 60], [230, 60], [230, 92], [150, 92]], "立即尋找！", 0.91]
        ])
        self.assertEqual(任务._查找立即寻找按钮中心(), (620, 396))

    def test_夜世界立即寻找OCR不命中时使用参考坐标(self):
        任务 = 打开进攻页面.__new__(打开进攻页面)
        任务.执行OCR识别 = Mock(return_value=[])
        self.assertIsNone(任务._查找立即寻找按钮中心())


if __name__ == "__main__":
    unittest.main()
