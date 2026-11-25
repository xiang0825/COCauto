import unittest
import unittest.mock
import itertools
import os
import threading
from pathlib import Path
import tempfile
from types import SimpleNamespace

import cv2
import numpy as np

from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务
from 任务流程.检测游戏登录状态 import 检测游戏登录状态任务
from 模块.检测.页面识别器 import 页面识别器


class _匹配器:
    def 执行匹配(self, _图像, 模板路径, **_参数):
        if "家乡进攻图标" in 模板路径:
            return True, (0, 0), None
        return True, (120, 130), None


class _屏幕:
    def 获取屏幕图像cv(self, *_区域):
        return object()


class _数据库:
    def 获取机器人设置(self, _机器人标志):
        return type("设置", (), {"是否试战统计胜率": False})()


class _上下文:
    op = _屏幕()
    数据库 = _数据库()
    机器人标志 = "测试机器人"

    def __init__(self):
        self.点击记录 = []
        self.状态 = []

    def 点击(self, x, y, *参数, **关键字参数):
        self.点击记录.append((x, y))

    def 脚本延时(self, _毫秒):
        pass

    def 置脚本状态(self, 文本, *参数, **关键字参数):
        self.状态.append(文本)


class 回营状态机测试(unittest.TestCase):
    def test_战斗结束等待期间刷新摧毁率并只保留最高值(self):
        上下文 = _上下文()
        上下文.本场实时摧毁率 = 12
        上下文.本场最高实时摧毁率 = 12
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.ocr引擎 = unittest.mock.Mock(
            return_value=([(None, "摧毁率"), (None, "45%")], None)
        )

        self.assertEqual(
            任务._等待中更新实时摧毁率(上下文, np.zeros((600, 800, 3), dtype=np.uint8)),
            45,
        )
        区域 = 任务.ocr引擎.call_args.args[0]
        self.assertEqual(区域.shape[:2], (120, 170))
        self.assertEqual(上下文.本场最高实时摧毁率, 45)
        self.assertIn("摧毁率进度：45%", 上下文.状态[-1])

        任务.ocr引擎 = unittest.mock.Mock(return_value=([(None, "40%")], None))
        self.assertEqual(
            任务._等待中更新实时摧毁率(上下文, np.zeros((600, 800, 3), dtype=np.uint8)),
            45,
        )
        self.assertEqual(上下文.本场实时摧毁率, 45)

    def test_资源栏或徽章单独出现不是可接管主世界(self):
        判定 = 等待战斗结束并回营任务._可接续主世界页面可信
        self.assertFalse(判定(SimpleNamespace(
            页面="主世界主页", 可信度=0.78,
            依据=("主世界资源栏0.98", "主世界蓝色等级徽章"),
        )))
        self.assertFalse(判定(SimpleNamespace(
            页面="主世界主页", 可信度=0.50,
            依据=("主世界资源栏0.98",),
        )))
        self.assertFalse(判定(SimpleNamespace(
            页面="主世界主页", 可信度=0.70,
            依据=("新版战斗入口0.99",),
        )))
        self.assertTrue(判定(SimpleNamespace(
            页面="主世界主页", 可信度=0.57,
            依据=("主世界资源栏0.98", "主世界入口0.90"),
        )))
        self.assertTrue(判定(SimpleNamespace(
            页面="主世界主页", 可信度=0.70,
            依据=("主世界资源栏0.94", "新版战斗入口0.99"),
        )))

    def test_主页证据优先于残留战斗HUD(self):
        """主城已确认时不能被旧战斗HUD特征拖到六分钟停机。"""
        上下文 = _上下文()
        上下文._已确认进入战斗 = True
        上下文._战斗中 = True
        上下文.清除战斗结算保护状态 = unittest.mock.Mock()
        上下文._获取点击页面识别器 = lambda: SimpleNamespace(
            识别=lambda _图像, **_参数: SimpleNamespace(
                页面="主世界主页", 可信度=0.78,
                依据=("主世界资源栏0.98", "主世界入口0.90", "主世界蓝色等级徽章"),
            ),
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务.等待主界面就绪 = unittest.mock.Mock(return_value=True)
        任务._画面仍在战斗 = unittest.mock.Mock(return_value=True)
        任务.记录战斗结果 = unittest.mock.Mock()

        self.assertTrue(任务.等待回营地按钮出现(上下文))
        任务._画面仍在战斗.assert_not_called()
        任务.等待主界面就绪.assert_called_once_with(上下文)
        任务.记录战斗结果.assert_not_called()
        self.assertFalse(上下文._战斗中)
        self.assertEqual(上下文.点击记录, [])

    def test_单帧主页误报后新帧仍在战斗时继续等待结算(self):
        主页 = object()
        战斗画面 = object()

        class 屏幕:
            def __init__(自身):
                自身.画面 = iter((主页, 战斗画面, 战斗画面))

            def 获取屏幕图像cv(自身, *_区域, **_关键字):
                return next(自身.画面)

        class 停止事件:
            def __init__(自身):
                自身.检查次数 = 0

            def is_set(自身):
                自身.检查次数 += 1
                return 自身.检查次数 >= 3

        页面结果 = iter((
            SimpleNamespace(
                页面="主世界主页", 可信度=0.78,
                依据=("主世界资源栏0.98", "主世界入口0.90"),
            ),
            SimpleNamespace(页面="战斗中", 可信度=0.96, 依据=("战斗中",)),
            SimpleNamespace(页面="战斗中", 可信度=0.96, 依据=("战斗中",)),
        ))
        上下文 = _上下文()
        上下文.op = 屏幕()
        上下文._已确认进入战斗 = True
        上下文.停止事件 = 停止事件()
        上下文._获取点击页面识别器 = lambda: SimpleNamespace(
            识别=lambda *_参数, **_关键字: next(页面结果)
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务._画面仍在战斗 = unittest.mock.Mock(return_value=True)
        任务._等待中更新实时摧毁率 = unittest.mock.Mock()
        任务._确认无结算回城 = unittest.mock.Mock(return_value=True)

        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.time",
            return_value=100.0,
        ), unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.monotonic",
            return_value=10.0,
        ), unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.检测游戏登录状态任务._检测断线弹窗",
            return_value=(False, (0, 0)),
        ):
            self.assertFalse(任务.等待回营地按钮出现(上下文))

        任务._确认无结算回城.assert_not_called()
        self.assertEqual(任务._画面仍在战斗.call_count, 2)
        任务._画面仍在战斗.assert_has_calls([
            unittest.mock.call(上下文, 战斗画面),
            unittest.mock.call(上下文, 战斗画面),
        ])
        self.assertTrue(
            any("主世界候选" in 状态 and "战斗" in 状态 for 状态 in 上下文.状态),
            repr(上下文.状态),
        )

    def test_仅弱主页候选仍须遵守战斗HUD(self):
        上下文 = _上下文()
        上下文._已确认进入战斗 = True
        上下文._获取点击页面识别器 = lambda: SimpleNamespace(
            识别=lambda _图像, **_参数: SimpleNamespace(
                页面="主世界主页", 可信度=0.50
            ),
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务._画面仍在战斗 = unittest.mock.Mock(return_value=True)
        任务.等待主界面就绪 = unittest.mock.Mock()
        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.time",
            side_effect=[0, 1, 2, 361],
        ):
            self.assertFalse(任务.等待回营地按钮出现(上下文))
        任务._画面仍在战斗.assert_called_once()
        任务.等待主界面就绪.assert_not_called()

    def test_人工回营后连续确认主城可继续但不补造战果(self):
        上下文 = _上下文()
        上下文._已确认进入战斗 = True
        上下文._战斗中 = True
        上下文._战斗结束已确认 = True
        上下文._战斗结束截图 = object()
        上下文.清除战斗结算保护状态 = unittest.mock.Mock()
        上下文._获取点击页面识别器 = lambda: SimpleNamespace(
            _红色放弃按钮分数=lambda _图像: 0.0,
            _战斗倒计时分数=lambda _图像: 0.0,
            识别=lambda _图像, **_参数: SimpleNamespace(
                页面="主世界主页", 可信度=0.78,
                依据=("主世界资源栏0.98", "主世界入口0.90", "主世界蓝色等级徽章"),
            ),
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务.等待主界面就绪 = unittest.mock.Mock(return_value=True)
        任务.记录战斗结果 = unittest.mock.Mock()

        self.assertTrue(任务.等待回营地按钮出现(上下文))
        任务.等待主界面就绪.assert_called_once_with(上下文)
        任务.记录战斗结果.assert_not_called()
        self.assertEqual(上下文.点击记录, [])
        self.assertFalse(上下文._已确认进入战斗)
        self.assertFalse(上下文._战斗中)
        上下文.清除战斗结算保护状态.assert_called_once_with(
            来源="人工或游戏自动回营后主世界"
        )
        self.assertIn("不计入学习胜率", " ".join(上下文.状态))

    def test_启动时接管战斗人工回主世界后可接续(self):
        上下文 = _上下文()
        上下文._启动时已有战斗 = True
        上下文._已确认进入战斗 = False
        上下文.清除战斗结算保护状态 = unittest.mock.Mock()

        class 停止事件:
            def __init__(自身):
                自身.检查次数 = 0

            def is_set(自身):
                自身.检查次数 += 1
                return 自身.检查次数 >= 2

        上下文.停止事件 = 停止事件()
        上下文._获取点击页面识别器 = lambda: SimpleNamespace(
            识别=lambda *_参数, **_关键字: SimpleNamespace(
                页面="主世界主页",
                可信度=0.78,
                依据=("主世界资源栏0.98", "主世界入口0.90"),
            ),
        )

        class 不匹配:
            def 执行匹配(自身, *_参数, **_关键字):
                return False, (0, 0), None

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 不匹配()
        任务.等待主界面就绪 = unittest.mock.Mock(return_value=True)
        任务.记录战斗结果 = unittest.mock.Mock()

        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.检测游戏登录状态任务._检测断线弹窗",
            return_value=(False, (0, 0)),
        ):
            self.assertTrue(任务.等待回营地按钮出现(上下文))

        任务.等待主界面就绪.assert_called_once_with(上下文)
        任务.记录战斗结果.assert_not_called()
        上下文.清除战斗结算保护状态.assert_called_once_with(
            来源="人工或游戏自动回营后主世界"
        )
        self.assertFalse(上下文._启动时已有战斗)
        self.assertIn("不计入学习胜率", " ".join(上下文.状态))

    def test_人工回营仅单帧主城不允许继续(self):
        上下文 = _上下文()
        上下文._已确认进入战斗 = True
        上下文._获取点击页面识别器 = lambda: SimpleNamespace(
            _红色放弃按钮分数=lambda _图像: 0.0,
            _战斗倒计时分数=lambda _图像: 0.0,
            识别=lambda _图像, **_参数: SimpleNamespace(
                页面="主世界主页", 可信度=0.78,
                依据=("主世界资源栏0.98", "主世界入口0.90", "主世界蓝色等级徽章"),
            ),
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务.等待主界面就绪 = unittest.mock.Mock(return_value=False)
        任务.记录战斗结果 = unittest.mock.Mock()

        self.assertFalse(任务.等待回营地按钮出现(上下文))
        任务.记录战斗结果.assert_not_called()
        self.assertEqual(上下文.点击记录, [])
        self.assertTrue(上下文._已确认进入战斗)

    def test_战斗HUD下的断线弹窗必须先于底层战斗判定(self):
        画面 = np.full((600, 800, 3), (10, 18, 22), dtype=np.uint8)
        cv2.rectangle(画面, (20, 430), (150, 477), (0, 0, 210), -1)
        cv2.rectangle(画面, (164, 180), (635, 423), (32, 26, 29), -1)
        for 左, 上, 右, 下 in (
            (201, 218, 304, 244), (201, 270, 580, 294),
            (201, 306, 232, 328), (201, 368, 325, 389),
        ):
            cv2.rectangle(画面, (左, 上), (右, 下), (220, 220, 220), -1)
        识别器 = 页面识别器(unittest.mock.Mock())
        上下文 = SimpleNamespace(_获取点击页面识别器=lambda: 识别器)

        self.assertTrue(等待战斗结束并回营任务._画面仍在战斗(上下文, 画面))
        self.assertTrue(检测游戏登录状态任务._检测断线弹窗(画面)[0])

    def test_回营等待断线重连回城不伪造战斗结果(self):
        断线 = np.zeros((600, 800, 3), dtype=np.uint8)
        断线[0, 0, 0] = 1
        主页 = np.zeros_like(断线)
        主页[0, 0, 0] = 2

        class 屏幕:
            def __init__(自身):
                自身.画面 = iter((断线, 断线, 主页, 主页, 主页, 主页))

            def 获取屏幕图像cv(自身, *_区域, **_参数):
                return next(自身.画面)

        class 识别器:
            def _红色放弃按钮分数(自身, 图像):
                # 重连主页残留战斗按钮特征，不能先用它排除主页。
                return 0.93

            def _战斗倒计时分数(自身, _图像):
                return 0.0

            def 识别(自身, 图像, **_参数):
                return SimpleNamespace(
                    页面="主世界主页" if 图像[0, 0, 0] == 2 else "断线弹窗",
                    可信度=0.78,
                    依据=("主世界资源栏0.98", "主世界入口0.90"),
                )

        class 不匹配:
            def 执行匹配(自身, *_参数, **_关键字):
                return False, (0, 0), None

        上下文 = _上下文()
        上下文.op = 屏幕()
        上下文._获取点击页面识别器 = lambda: 识别器()
        上下文._已确认进入战斗 = True
        上下文._战斗中 = True
        上下文._启动时已有战斗 = True
        上下文.清除战斗结算保护状态 = unittest.mock.Mock()
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 不匹配()
        任务.记录战斗结果 = unittest.mock.Mock()

        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.检测游戏登录状态任务"
        ) as 登录类:
            登录类._检测断线弹窗.side_effect = itertools.chain(
                [(True, (250, 365)), (True, (250, 365))],
                itertools.repeat((False, (0, 0))),
            )
            def 模拟重连清理战斗标志(**_参数):
                上下文._已确认进入战斗 = False
                return True

            登录类.return_value.执行.side_effect = 模拟重连清理战斗标志
            self.assertTrue(任务.等待回营地按钮出现(上下文))
            登录类.return_value.执行.assert_called_once_with(
                首次登录=False, 仅恢复连接=True
            )

        self.assertFalse(上下文._已确认进入战斗)
        self.assertFalse(上下文._战斗中)
        self.assertFalse(上下文._启动时已有战斗)
        self.assertEqual(上下文.点击记录, [])
        任务.记录战斗结果.assert_not_called()
        上下文.清除战斗结算保护状态.assert_called_once_with(
            来源="断线重连后主世界"
        )
        self.assertIn("本场战斗结果丢失", " ".join(上下文.状态))

    def test_回营等待断线重连失败不继续点击(self):
        上下文 = _上下文()
        上下文.op = SimpleNamespace(
            获取屏幕图像cv=unittest.mock.Mock(return_value=object())
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = unittest.mock.Mock()
        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.检测游戏登录状态任务"
        ) as 登录类:
            登录类._检测断线弹窗.return_value = True, (250, 365)
            登录类.return_value.执行.return_value = False
            self.assertFalse(任务.等待回营地按钮出现(上下文))
            登录类.return_value.执行.assert_called_once()
        self.assertTrue(上下文.页面恢复失败)
        self.assertEqual(上下文.点击记录, [])

    def test_回营等待允许再次确认的短暂断线后回城(self):
        断线 = np.zeros((600, 800, 3), dtype=np.uint8)
        断线[0, 0, 0] = 1
        主页 = np.zeros_like(断线)
        主页[0, 0, 0] = 2
        画面 = iter((断线, 断线, 断线, 断线, 主页, 主页, 主页, 主页))
        上下文 = _上下文()
        上下文.op = SimpleNamespace(
            获取屏幕图像cv=lambda *_参数, **_关键字: next(画面)
        )
        上下文._获取点击页面识别器 = lambda: SimpleNamespace(
            识别=lambda *_参数, **_关键字: SimpleNamespace(
                页面="主世界主页", 可信度=0.78,
                依据=("主世界资源栏0.98", "主世界入口0.90"),
            )
        )
        上下文._已确认进入战斗 = True
        上下文.清除战斗结算保护状态 = unittest.mock.Mock()
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = SimpleNamespace(
            执行匹配=lambda *_参数, **_关键字: (False, (0, 0), None)
        )
        任务.记录战斗结果 = unittest.mock.Mock()

        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.检测游戏登录状态任务"
        ) as 登录类, unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.monotonic",
            side_effect=(n * 3 for n in itertools.count()),
        ), unittest.mock.patch.object(任务, "_画面仍在战斗", return_value=False):
            登录类._检测断线弹窗.side_effect = itertools.chain(
                [(True, (250, 365)) for _ in range(4)],
                itertools.repeat((False, (0, 0))),
            )
            登录类.return_value.执行.return_value = True
            self.assertTrue(任务.等待回营地按钮出现(上下文))
            self.assertEqual(登录类.return_value.执行.call_count, 2)

        self.assertEqual(上下文.点击记录, [])
        任务.记录战斗结果.assert_not_called()
        self.assertFalse(上下文._已确认进入战斗)

    def test_单帧断线候选消失后不重连也不使用旧帧点击(self):
        class 屏幕:
            def __init__(自身):
                自身.画面 = iter((object(), object()))

            def 获取屏幕图像cv(自身, *_区域, **_参数):
                return next(自身.画面)

        class 不匹配:
            def 执行匹配(自身, *_参数, **_关键字):
                return False, (0, 0), None

        上下文 = _上下文()
        上下文.op = 屏幕()
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 不匹配()
        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.检测游戏登录状态任务"
        ) as 登录类, unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.time",
            side_effect=[0, 1, 2, 361],
        ):
            登录类._检测断线弹窗.side_effect = [
                (True, (250, 365)), (False, (0, 0))
            ]
            self.assertFalse(任务.等待回营地按钮出现(上下文))
            登录类.assert_not_called()
        self.assertEqual(上下文.点击记录, [])

    def test_长时间等待结算会续报心跳(self):
        class 未命中匹配器:
            def 执行匹配(self, *_参数, **_关键字):
                return False, (0, 0), None

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 未命中匹配器()
        上下文 = _上下文()
        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.time",
            side_effect=[0, 1, 2, 361],
        ), unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.monotonic",
            side_effect=[0, 21],
        ):
            self.assertFalse(任务.等待回营地按钮出现(上下文))
        self.assertIn("仍在等待战斗结算及回营按钮", 上下文.状态)

    def test_超过六分钟后人工回营仍自动接续(self):
        当前时间 = [0.0]

        class 屏幕:
            def 获取屏幕图像cv(自身, *_区域, **_参数):
                return "主页" if 当前时间[0] >= 360 else "等待结算"

        class 页面识别器:
            def 识别(自身, 图像, **_参数):
                if 图像 == "主页":
                    return SimpleNamespace(
                        页面="主世界主页",
                        可信度=0.70,
                        依据=("主世界资源栏0.94", "新版战斗入口0.99"),
                    )
                return SimpleNamespace(页面="战斗中", 可信度=0.96, 依据=("战斗中",))

        上下文 = _上下文()
        上下文._已确认进入战斗 = True
        上下文.停止事件 = threading.Event()
        上下文.op = 屏幕()
        上下文._获取点击页面识别器 = lambda: 页面识别器()
        上下文.脚本延时 = lambda _毫秒: 当前时间.__setitem__(
            0, 当前时间[0] + 181
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务._确认无结算回城 = unittest.mock.Mock(return_value=True)

        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.time",
            side_effect=lambda: 当前时间[0],
        ), unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.monotonic",
            side_effect=lambda: 当前时间[0],
        ), unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.检测游戏登录状态任务._检测断线弹窗",
            return_value=(False, (0, 0)),
        ), unittest.mock.patch.object(
            任务, "_画面仍在战斗", side_effect=lambda *_参数: 当前时间[0] < 360
        ), unittest.mock.patch.object(
            任务, "_等待中更新实时摧毁率"
        ):
            self.assertTrue(任务.等待回营地按钮出现(上下文))

        任务._确认无结算回城.assert_called_once_with(
            上下文, "人工或游戏自动回营", 结果已记录=False
        )
        self.assertIn("超过6分钟", " ".join(上下文.状态))
        self.assertEqual(上下文.点击记录, [])

    def test_三分钟后才出现真实结算仍能回营(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务.记录战斗结果 = unittest.mock.Mock(return_value=True)
        任务.等待主界面就绪 = unittest.mock.Mock(return_value=True)
        上下文 = _上下文()
        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.time",
            side_effect=[0, 181, 181],
        ):
            self.assertTrue(任务.等待回营地按钮出现(上下文))
        self.assertEqual(上下文.点击记录, [(120, 130)])
        self.assertTrue(any("超过3分钟" in 项 for 项 in 上下文.状态))

    def test_结果截图使用中文目录仍能写入(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        上下文 = SimpleNamespace(
            设置=SimpleNamespace(是否采集进攻界面图像=True),
            置脚本状态=unittest.mock.Mock(),
        )
        画面 = np.zeros((24, 32, 3), dtype=np.uint8)
        原目录 = os.getcwd()
        with tempfile.TemporaryDirectory() as 临时目录:
            try:
                os.chdir(临时目录)
                任务.保存战斗结果截图(上下文, 画面)
            finally:
                os.chdir(原目录)
            文件 = list(Path(临时目录).glob("数据集/战斗结果/*.png"))
            self.assertEqual(len(文件), 1)
            self.assertGreater(文件[0].stat().st_size, 0)

    def test_速刷等待后已自然结算时跳过放弃确认(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        上下文 = type("上下文", (), {"_战斗结束已确认": True})()

        self.assertTrue(任务._当前已确认结算页(上下文))

    def test_速刷寻找放弃按钮期间自然结算时不报放弃按钮丢失(self):
        class 设置:
            是否快速刷资源 = True

        class 数据库:
            def 获取机器人设置(self, _机器人标志):
                return 设置()

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        上下文 = type(
            "上下文",
            (),
            {
                "数据库": 数据库(),
                "机器人标志": "测试机器人",
                "状态": [],
                "脚本延时": lambda _自身, _毫秒: None,
                "置脚本状态": lambda _自身, 文本, *_参数, **_关键字: _自身.状态.append(文本),
            },
        )()
        复核次数 = {"值": 0}

        def 结算页复核(_上下文):
            复核次数["值"] += 1
            return 复核次数["值"] >= 2

        任务._当前已确认结算页 = 结算页复核
        任务.点击放弃战斗按钮 = lambda _上下文: False
        任务.等待回营地按钮出现 = lambda _上下文: True
        任务.上下文 = 上下文

        self.assertTrue(任务.执行())
        self.assertIn("寻找放弃按钮期间战斗已自然结束", " ".join(上下文.状态))

    def test_速刷投降后立即结算时不重复点击确认按钮(self):
        class 设置:
            是否快速刷资源 = True

        class 数据库:
            def 获取机器人设置(self, _机器人标志):
                return 设置()

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        上下文 = type(
            "上下文",
            (),
            {
                "数据库": 数据库(),
                "机器人标志": "测试机器人",
                "状态": [],
                "脚本延时": lambda _自身, _毫秒: None,
                "置脚本状态": lambda _自身, 文本, *_参数, **_关键字: _自身.状态.append(文本),
            },
        )()
        复核次数 = {"值": 0}

        def 结算页复核(_上下文):
            复核次数["值"] += 1
            return 复核次数["值"] >= 2

        任务._当前已确认结算页 = 结算页复核
        任务.点击放弃战斗按钮 = lambda _上下文: True
        任务.点击确定 = lambda _上下文: (_ for _ in ()).throw(
            AssertionError("结算页不应再次点击投降确认")
        )
        任务.等待回营地按钮出现 = lambda _上下文: True
        任务.上下文 = 上下文

        self.assertTrue(任务.执行())
        self.assertIn("放弃操作后战斗已进入结算页", " ".join(上下文.状态))

    def test_速刷放弃后直接回主世界但无结算时禁止下一场(self):
        class 设置:
            是否快速刷资源 = True

        class 数据库:
            def 获取机器人设置(self, _机器人标志):
                return 设置()

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        上下文 = type(
            "上下文",
            (),
            {
                "数据库": 数据库(),
                "机器人标志": "测试机器人",
                "状态": [],
                "脚本延时": lambda _自身, _毫秒: None,
                "置脚本状态": lambda _自身, 文本, *_参数, **_关键字: _自身.状态.append(文本),
            },
        )()
        任务._当前已确认结算页 = lambda _上下文: False
        任务.点击放弃战斗按钮 = lambda _上下文: True
        任务.点击确定 = lambda _上下文: False
        任务.等待主界面就绪 = lambda _上下文: True
        任务.等待回营地按钮出现 = unittest.mock.Mock(
            side_effect=AssertionError("无结算时不应继续回营")
        )
        任务.上下文 = 上下文

        self.assertFalse(任务.执行())
        self.assertIn("直接回到主世界", " ".join(上下文.状态))
        self.assertIn("禁止开始下一场", " ".join(上下文.状态))
        任务.等待回营地按钮出现.assert_not_called()

    def test_速刷按钮模板低分时用战斗页红色几何定位(self):
        class 页面识别:
            def 识别(self, _图像, **_参数):
                return type("结果", (), {"页面": "战斗中"})()

        上下文 = type(
            "上下文",
            (),
            {"_获取点击页面识别器": lambda _自身: 页面识别()},
        )()
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (10, 430), (103, 467), (0, 0, 210), -1)
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)

        坐标 = 任务._定位红色放弃按钮(上下文, 图像)

        self.assertIsNotNone(坐标)
        self.assertTrue(0 <= 坐标[0] <= 800)
        self.assertTrue(0 <= 坐标[1] <= 600)

    def test_投降确认框模板低分时用双按钮几何定位(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (237, 347), (386, 428), (0, 130, 240), -1)
        cv2.rectangle(图像, (412, 347), (561, 429), (90, 210, 70), -1)
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)

        坐标 = 任务._定位放弃确认按钮(图像)

        self.assertIsNotNone(坐标)
        self.assertGreaterEqual(坐标[0], 400)
        self.assertGreaterEqual(坐标[1], 300)

    def test_投降确认框使用专用安全点击通道避免被断线护栏拦截(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (237, 347), (386, 428), (0, 130, 240), -1)
        cv2.rectangle(图像, (412, 347), (561, 429), (90, 210, 70), -1)

        class 低分匹配器:
            def 执行匹配(self, *_参数, **_关键字参数):
                return False, (0, 0), None

        class 屏幕:
            def 获取屏幕图像cv(self, *_区域):
                return 图像

        class 上下文:
            op = 屏幕()
            模板识别 = 低分匹配器()

            def __init__(自身):
                自身.专用点击 = []

            def 置脚本状态(自身, _文本, *_参数, **_关键字参数):
                pass

            def 脚本延时(自身, _毫秒):
                pass

            def 点击已确认安全按钮(自身, x, y, 延时=100):
                自身.专用点击.append((x, y, 延时))
                return True

            def 点击(自身, *_参数, **_关键字参数):
                raise AssertionError("投降确认框不应走普通点击护栏")

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        上下文实例 = 上下文()
        任务.模板识别 = 上下文实例.模板识别
        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.time",
            side_effect=[0, 1],
        ):
            self.assertTrue(任务.点击确定(上下文实例))
        self.assertEqual(len(上下文实例.专用点击), 1)
        self.assertEqual(上下文实例.专用点击[0][2], 100)

    def test_OCR胜负结果不能把未知当胜利(self):
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("胜利！"), "胜利")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("战斗失败"), "失败")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("戰鬥勝利！"), "胜利")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("戰鬥失敗"), "失败")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("氧败"), "失败")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("胜"), "胜利")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("结束战斗"), "未知")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本提取摧毁率("摧毁率 67%"), 67)
        self.assertEqual(等待战斗结束并回营任务.从OCR文本提取摧毁率("摧毀率 67％"), 67)
        self.assertEqual(
            等待战斗结束并回营任务.合并本场摧毁率(0, 32),
            0,
        )
        # 结果页上的最终结算率必须胜过战斗中较早的实时读数。
        self.assertEqual(
            等待战斗结束并回营任务.合并本场摧毁率(22, 42),
            22,
        )
        self.assertEqual(
            等待战斗结束并回营任务.合并本场摧毁率(67, 32),
            67,
        )
        self.assertEqual(
            等待战斗结束并回营任务.合并本场摧毁率(None, 32),
            32,
        )
        self.assertIsNone(等待战斗结束并回营任务.识别星数(None, "结束战斗"))
        self.assertEqual(等待战斗结束并回营任务.校正星数("失败", 3, 49), 0)
        self.assertEqual(等待战斗结束并回营任务.校正星数("失败", 0, 52), 1)
        self.assertEqual(等待战斗结束并回营任务.校正星数("胜利", None, 35), 1)
        self.assertIsNone(等待战斗结束并回营任务.校正星数("胜利", 3, 99))
        self.assertEqual(等待战斗结束并回营任务.校正星数("胜利", 3, 100), 3)
        self.assertIn("未识别战斗结果", 等待战斗结束并回营任务.生成战斗诊断("未知", None, None, {}))

    def test_百分百摧毁时结果页星形误识别不应记录为矛盾(self):
        原始星数 = 2
        星数 = 等待战斗结束并回营任务.校正星数("胜利", 原始星数, 100)
        说明 = 等待战斗结束并回营任务.星数校正说明(
            "胜利", 原始星数, 星数, 100
        )
        self.assertEqual(星数, 3)
        self.assertIn("按规则确认3星", 说明)
        self.assertNotIn("矛盾", 说明)

    def test_三星胜利将单点实时进度误差校正为百分百(self):
        self.assertEqual(
            等待战斗结束并回营任务.校正三星摧毁率("胜利", 3, 99),
            99,
        )
        self.assertEqual(
            等待战斗结束并回营任务.校正三星摧毁率(
                "胜利", 3, 99, 结算页已复核=True
            ),
            100,
        )
        self.assertEqual(
            等待战斗结束并回营任务.校正三星摧毁率("胜利", 3, 98),
            98,
        )
        self.assertEqual(
            等待战斗结束并回营任务.校正三星摧毁率("胜利", 2, 99),
            99,
        )

    def test_复核结算页的三星胜利可纠正明显落后的实时摧毁率(self):
        self.assertEqual(
            等待战斗结束并回营任务.校正三星摧毁率(
                "胜利", 3, 87, 结算页已复核=True
            ),
            100,
        )
        self.assertEqual(
            等待战斗结束并回营任务.校正三星摧毁率(
                "胜利", 3, 87, 结算页已复核=False
            ),
            87,
        )

    def test_已复核三星结算且结算OCR漏读时不因旧实时百分比卡住(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务._画面仍在战斗 = unittest.mock.Mock(return_value=False)
        任务.识别结算帧 = unittest.mock.Mock(
            return_value=([], "胜利", "胜利", None)
        )
        任务.识别星数 = unittest.mock.Mock(return_value=3)
        任务.保存战斗结果截图 = unittest.mock.Mock()
        任务.更新战斗学习 = unittest.mock.Mock()
        任务.生成战斗诊断 = unittest.mock.Mock(return_value="已确认三星")
        数据库 = unittest.mock.Mock()
        数据库.获取最新完整状态.return_value = SimpleNamespace(状态数据={})
        上下文 = SimpleNamespace(
            数据库=数据库,
            机器人标志="测试机器人",
            置脚本状态=unittest.mock.Mock(),
            本场实时摧毁率=87,
            本场最高实时摧毁率=87,
            本场目标战利品={},
            英雄技能状态={},
        )

        self.assertTrue(
            任务.记录战斗结果(
                上下文,
                np.zeros((600, 800, 3), dtype=np.uint8),
                结算页已复核=True,
            )
        )

        统计 = 数据库.更新状态.call_args.args[2]
        self.assertEqual(统计["最近结果"], "胜利")
        self.assertEqual(统计["最近星数"], 3)
        self.assertEqual(统计["最近摧毁率"], 100)
        self.assertEqual(统计["胜场"], 1)
        self.assertTrue(any(
            "三星" in 调用.args[0] and "100%" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_未复核三星与99实时进度保持待复核(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务._画面仍在战斗 = unittest.mock.Mock(return_value=False)
        任务.识别结算帧 = unittest.mock.Mock(
            return_value=([], "胜利", "胜利", None)
        )
        任务.识别星数 = unittest.mock.Mock(return_value=3)
        任务.保存战斗结果截图 = unittest.mock.Mock()
        任务.更新战斗学习 = unittest.mock.Mock()
        任务.生成战斗诊断 = unittest.mock.Mock(return_value="已确认三星")
        数据库 = unittest.mock.Mock()
        数据库.获取最新完整状态.return_value = SimpleNamespace(状态数据={})
        上下文 = SimpleNamespace(
            数据库=数据库,
            机器人标志="测试机器人",
            置脚本状态=unittest.mock.Mock(),
            本场实时摧毁率=99,
            本场最高实时摧毁率=99,
            本场目标战利品={},
            英雄技能状态={},
        )

        self.assertFalse(
            任务.记录战斗结果(上下文, np.zeros((600, 800, 3), dtype=np.uint8))
        )
        统计 = 数据库.更新状态.call_args.args[2]
        self.assertIsNone(统计["最近星数"])
        self.assertEqual(统计["最近摧毁率"], 99)
        self.assertFalse(
            any(
                "实时99%校正为最终100%" in call.args[0]
                for call in 上下文.置脚本状态.call_args_list
            )
        )

    def test_普通结算最终帧必须同时复核结算结构和同位置回营按钮(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务._页面确认是结算页 = unittest.mock.Mock(return_value=True)
        任务._复核最终帧结算按钮 = unittest.mock.Mock(return_value=True)
        上下文 = object()
        画面 = object()
        候选点 = (120, 450)

        self.assertTrue(
            任务._复核最终结算页证据(上下文, 画面, 候选点)
        )
        任务._页面确认是结算页.assert_called_once_with(上下文, 画面)
        任务._复核最终帧结算按钮.assert_called_once_with(
            上下文, 画面, 候选点
        )

        任务._复核最终帧结算按钮.return_value = False
        self.assertFalse(
            任务._复核最终结算页证据(上下文, 画面, 候选点)
        )

    def test_普通无战斗HUD结算帧将同帧复核传给结果记录(self):
        class 低分匹配器:
            def 执行匹配(self, *_参数, **_关键字参数):
                return False, (0, 0), None

        class 页面识别器:
            def _红色放弃按钮分数(self, _图像):
                return 0.0

            def _战斗倒计时分数(self, _图像):
                return 0.0

            def 识别(self, _图像, **_参数):
                return SimpleNamespace(页面="战斗结算", 可信度=0.96)

            def 定位结算回营按钮(self, _图像, **_参数):
                return (436, 553)

        class 屏幕:
            def 获取屏幕图像cv(self, *_区域, **_参数):
                return np.zeros((600, 800, 3), dtype=np.uint8)

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 低分匹配器()
        任务.记录战斗结果 = unittest.mock.Mock(return_value=True)
        任务.等待主界面就绪 = unittest.mock.Mock(return_value=True)
        上下文 = _上下文()
        上下文.op = 屏幕()
        上下文._已确认进入战斗 = True
        上下文._获取点击页面识别器 = lambda: 页面识别器()
        上下文.点击已确认安全按钮 = unittest.mock.Mock(return_value=True)
        上下文.清除战斗结算保护状态 = unittest.mock.Mock()

        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.time",
            side_effect=[0, 1, 2, 361],
        ), unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.检测游戏登录状态任务._检测断线弹窗",
            return_value=(False, None),
        ):
            self.assertTrue(任务.等待回营地按钮出现(上下文))

        任务.记录战斗结果.assert_called_once()
        self.assertIs(任务.记录战斗结果.call_args.args[2], True)
        上下文.点击已确认安全按钮.assert_called_once_with(436, 553)

    def test_战斗胜率诊断与学习层最终建议保持一致(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务._画面仍在战斗 = unittest.mock.Mock(return_value=False)
        任务.识别结算帧 = unittest.mock.Mock(
            return_value=([], "胜利", "胜利", 53)
        )
        任务.识别星数 = unittest.mock.Mock(return_value=1)
        任务.保存战斗结果截图 = unittest.mock.Mock()
        任务.更新战斗学习 = unittest.mock.Mock(return_value={
            "最近原因": "双方向低表现，下一场集中资源",
            "下一场建议": "集中资源",
        })
        任务.生成战斗诊断 = unittest.mock.Mock(
            return_value="旧通用诊断：下一场分散入口"
        )
        数据库 = unittest.mock.Mock()
        数据库.获取最新完整状态.return_value = SimpleNamespace(状态数据={})
        上下文 = SimpleNamespace(
            数据库=数据库,
            机器人标志="测试机器人",
            置脚本状态=unittest.mock.Mock(),
            本场实时摧毁率=53,
            本场最高实时摧毁率=53,
            本场目标战利品={},
            英雄技能状态={},
        )

        self.assertTrue(
            任务.记录战斗结果(上下文, np.zeros((600, 800, 3), dtype=np.uint8))
        )

        战斗胜率 = 数据库.更新状态.call_args.args[2]
        self.assertEqual(战斗胜率["最近诊断"], "双方向低表现，下一场集中资源")
        状态文本 = "\n".join(call.args[0] for call in 上下文.置脚本状态.call_args_list)
        self.assertIn("双方向低表现，下一场集中资源", 状态文本)
        self.assertNotIn("旧通用诊断：下一场分散入口", 状态文本)

    def test_摧毁率超过50但文字识别战败时按规则记录一星胜利(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务._画面仍在战斗 = unittest.mock.Mock(return_value=False)
        任务.识别结算帧 = unittest.mock.Mock(
            return_value=([], "失败", "失败", 52)
        )
        任务.识别星数 = unittest.mock.Mock(return_value=0)
        任务.保存战斗结果截图 = unittest.mock.Mock()
        任务.更新战斗学习 = unittest.mock.Mock(return_value={})
        任务.生成战斗诊断 = unittest.mock.Mock(return_value="已校正")
        数据库 = unittest.mock.Mock()
        数据库.获取最新完整状态.return_value = SimpleNamespace(状态数据={})
        上下文 = SimpleNamespace(
            数据库=数据库,
            机器人标志="测试机器人",
            置脚本状态=unittest.mock.Mock(),
            本场实时摧毁率=0,
            本场最高实时摧毁率=0,
            本场目标战利品={},
            英雄技能状态={},
        )

        self.assertTrue(
            任务.记录战斗结果(上下文, np.zeros((600, 800, 3), dtype=np.uint8))
        )

        统计 = 数据库.更新状态.call_args.args[2]
        self.assertEqual(统计["最近结果"], "胜利")
        self.assertEqual(统计["最近星数"], 1)
        self.assertEqual(统计["胜场"], 1)
        self.assertTrue(any("50%" in call.args[0] for call in 上下文.置脚本状态.call_args_list))

    def test_未复核结算帧仍保留残留倒计时保护(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务._画面仍在战斗 = unittest.mock.Mock(return_value=True)
        上下文 = SimpleNamespace(置脚本状态=unittest.mock.Mock())

        self.assertFalse(
            任务.记录战斗结果(
                上下文, np.zeros((600, 800, 3), dtype=np.uint8)
            )
        )

        上下文.置脚本状态.assert_called_once_with(
            "战斗画面仍有放弃按钮或倒计时，拒绝记录伪结算结果"
        )

    def test_胜利文字已识别但星数待定时刷新结算帧(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务._画面仍在战斗 = unittest.mock.Mock(return_value=False)
        任务.识别结算帧 = unittest.mock.Mock(side_effect=[
            ([], "胜利", "胜利", 98),
            ([], "胜利", "胜利", 100),
        ])
        任务.识别星数 = unittest.mock.Mock(side_effect=[None, 3])
        任务.保存战斗结果截图 = unittest.mock.Mock()
        任务.更新战斗学习 = unittest.mock.Mock()
        任务.生成战斗诊断 = unittest.mock.Mock(return_value="已确认三星")
        数据库 = unittest.mock.Mock()
        数据库.获取最新完整状态.return_value = SimpleNamespace(状态数据={})
        上下文 = SimpleNamespace(
            数据库=数据库,
            机器人标志="测试机器人",
            置脚本状态=unittest.mock.Mock(),
            脚本延时=unittest.mock.Mock(),
            op=SimpleNamespace(
                获取屏幕图像cv=unittest.mock.Mock(
                    return_value=np.ones((600, 800, 3), dtype=np.uint8)
                )
            ),
            本场实时摧毁率=98,
            本场最高实时摧毁率=98,
            本场目标战利品={},
            英雄技能状态={},
        )

        self.assertTrue(
            任务.记录战斗结果(
                上下文, np.zeros((600, 800, 3), dtype=np.uint8)
            )
        )
        self.assertEqual(任务.识别结算帧.call_count, 2)
        上下文.脚本延时.assert_called_once_with(800)
        统计 = 数据库.更新状态.call_args.args[2]
        self.assertEqual(统计["最近星数"], 3)
        self.assertEqual(统计["最近摧毁率"], 100)

    def test_零摧毁率却识别到星数时不写入战果(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.识别结算帧 = unittest.mock.Mock(return_value=([], "胜利", "胜利", 0))
        任务.识别星数 = unittest.mock.Mock(return_value=3)
        任务.保存战斗结果截图 = unittest.mock.Mock()
        上下文 = SimpleNamespace(
            数据库=unittest.mock.Mock(),
            置脚本状态=unittest.mock.Mock(),
        )

        self.assertFalse(任务.记录战斗结果(上下文, np.zeros((600, 800, 3), dtype=np.uint8)))
        上下文.数据库.获取最新完整状态.assert_not_called()
        self.assertIn("结果矛盾", " ".join(调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list))

    def test_无本场资源评分的多方向低摧毁不应误判可达性(self):
        上下文 = SimpleNamespace(
            本场进攻目标数量=18,
            本场边缘目标数量=14,
            本场进攻方向数量=4,
            _本场已确认投放数量=18,
            _本场已确认投放方向集合={"左上", "右上", "左下", "右下"},
        )
        诊断 = 等待战斗结束并回营任务.生成战斗诊断(
            "失败", 0, 28, {"资源评分状态": "不可用"}, 上下文
        )
        self.assertIn("多方向实际投放", 诊断)
        self.assertIn("本场目标可达评分不可用", 诊断)
        self.assertIn("下一场集中主力", 诊断)
        self.assertNotIn("优先筛选可达评分更高", 诊断)

    def test_仅有计划目标但实际投放不足时不认定完成分散覆盖(self):
        记录 = {
            "目标数量": 18,
            "边缘目标数量": 14,
            "进攻方向数量": 4,
        }
        self.assertFalse(
            等待战斗结束并回营任务._战斗记录已完成分散覆盖(记录)
        )
        记录.update({
            "实际投放数量": 3,
            "实际投放方向": ["左上", "右下"],
        })
        记录["可部署单位数量"] = 4
        self.assertFalse(
            等待战斗结束并回营任务._战斗记录已完成分散覆盖(记录)
        )
        记录["实际投放数量"] = 4
        self.assertTrue(
            等待战斗结束并回营任务._战斗记录已完成分散覆盖(记录)
        )

    def test_低摧毁率诊断能指出实际下兵方向不足(self):
        上下文 = SimpleNamespace(
            本场进攻目标数量=2,
            本场边缘目标数量=1,
            本场进攻方向数量=1,
            _本场已确认投放数量=4,
            _本场已确认投放方向集合={"左上"},
        )
        诊断 = 等待战斗结束并回营任务.生成战斗诊断(
            "失败", 0, 28, {}, 上下文
        )
        self.assertIn("实际下兵仅覆盖1个方向", 诊断)

    def test_低星胜利诊断只承诺当前支持的策略(self):
        诊断 = 等待战斗结束并回营任务.生成战斗诊断(
            "胜利", 1, 82, {}
        )
        self.assertIn("单星胜利", 诊断)
        self.assertIn("优先保留当前胜率策略", 诊断)
        self.assertIn("完整投兵样本", 诊断)
        self.assertNotIn("提高目标可达评分", 诊断)
        self.assertNotIn("核心建筑", 诊断)

    def test_未充分投放的战果不应误导目标和进攻策略学习(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [{
                            "结果": "失败", "星数": 0, "摧毁率": 16,
                            "可部署单位数量": 34, "实际投放数量": 5,
                            "部署比例": 14.7, "策略样本有效": False,
                        }],
                        "下一场建议": "集中资源",
                        "建议依据": "保留历史建议",
                    }
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            当前兵栏清单=[
                {"类别": "兵种", "数量": 8},
                {"类别": "兵种", "数量": 22},
                {"类别": "兵种", "数量": 2},
                {"类别": "英雄", "数量": 1},
                {"类别": "攻城器械", "数量": 1},
            ],
            本场进攻策略="稳健三星/集中主力左下",
            本场进攻方向=["左下"],
            本场进攻目标数量=2,
            本场边缘目标数量=2,
            本场进攻方向数量=1,
            _本场已确认投放数量=5,
            _本场已确认投放方向集合={"左下"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)

        结果 = 任务.更新战斗学习(
            上下文,
            "失败",
            0,
            16,
            {
                "资源易窃取评分": 8.5,
                "资源易窃取评分依据": {"高价值资源可达折算": 75.8},
            },
        )

        记录 = 数据库实例.保存状态["近期"][-1]
        self.assertEqual(记录["可部署单位数量"], 34)
        self.assertEqual(记录["部署比例"], 14.7)
        self.assertFalse(记录["策略样本有效"])
        self.assertEqual(结果["下一场建议"], "集中资源")
        self.assertIn("5/34", 结果["最近原因"])
        self.assertIn("不用于策略归因", 结果["最近原因"])

    def test_战斗学习保存目标证据并改变下一场建议(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "摧毁率": 28},
                            {"结果": "失败", "摧毁率": 33},
                        ]
                    }
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="资源全覆盖+分散探索",
            本场进攻方向=["左上", "右下", "左下", "右上"],
            本场进攻目标数量=18,
            本场边缘目标数量=14,
            本场进攻方向数量=4,
            当前兵栏清单=[{"类别": "兵种", "数量": 18}],
            _本场已确认投放数量=18,
            _本场已确认投放方向集合={"左上", "右上", "左下", "右下"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.更新战斗学习(
            上下文,
            "失败",
            0,
            28,
            {"金币": 0, "圣水": 100, "黑油": 200},
        )
        记录 = 数据库实例.保存状态["近期"][-1]
        self.assertEqual(记录["目标数量"], 18)
        self.assertEqual(记录["边缘目标数量"], 14)
        self.assertEqual(记录["进攻方向数量"], 4)
        self.assertEqual(记录["实际投放数量"], 18)
        self.assertEqual(set(记录["实际投放方向"]), {"左上", "右上", "左下", "右下"})
        self.assertEqual(数据库实例.保存状态["下一场建议"], "集中资源")
        self.assertIn("评分不可用", 数据库实例.保存状态["建议依据"])

    def test_兵栏总数未知且实际只下少量兵时不用于策略归因(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {"近期": [], "下一场建议": "分散探索"}
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="稳健三星/集中主力左下",
            本场进攻方向=["左下"],
            本场进攻目标数量=2,
            本场边缘目标数量=2,
            本场进攻方向数量=1,
            _本场已确认投放数量=5,
            _本场已确认投放方向集合={"左下"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)

        任务.更新战斗学习(上下文, "失败", 0, 30, {})

        记录 = 数据库实例.保存状态["近期"][-1]
        self.assertIsNone(记录["可部署单位数量"])
        self.assertFalse(记录["策略样本有效"])
        self.assertEqual(数据库实例.保存状态["下一场建议"], "分散探索")
        self.assertIn("总兵力未知", 数据库实例.保存状态["最近原因"])
        可用于学习 = 等待战斗结束并回营任务._战斗记录可用于策略学习
        self.assertFalse(可用于学习({"实际投放数量": 5}))
        self.assertTrue(可用于学习({"实际投放数量": 34}))

    def test_近期目标质量相近时按完整投兵的实际胜率偏向多方向(self):
        def 记录(结果, 星数, 摧毁率, 方向):
            return {
                "结果": 结果,
                "星数": 星数,
                "摧毁率": 摧毁率,
                "策略": "稳健三星/分散探索" if len(方向) > 1 else "稳健三星/集中主力",
                "实际投放数量": 34,
                "可部署单位数量": 34,
                "策略样本有效": True,
                "实际投放方向": 方向,
                "资源易窃取评分": 8.8,
                "资源易窃取评分依据": {"高价值资源可达折算": 75.0},
            }

        历史 = [
            记录("胜利", 3, 100, ["左上", "右上"]),
            *[记录("失败", 0, 35, ["左上"]) for _ in range(5)],
            记录("胜利", 2, 63, ["左上"]),
            *[记录("胜利", 1, 55, ["左上", "右上"]) for _ in range(4)],
            *[记录("失败", 0, 35, ["左上", "右上"]) for _ in range(2)],
        ]
        历史[0]["实际投放数量"] = 5
        历史[0]["可部署单位数量"] = 34
        历史[0]["策略样本有效"] = False
        未知兵力总数样本 = 记录("胜利", 3, 100, ["左上", "右上"])
        未知兵力总数样本["可部署单位数量"] = None
        历史.append(未知兵力总数样本)

        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={"战斗学习": {"近期": 历史}})

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="稳健三星/集中主力左上",
            本场进攻方向=["左上"],
            本场进攻目标数量=2,
            本场边缘目标数量=2,
            本场进攻方向数量=1,
            _本场已确认投放数量=34,
            _本场已确认投放方向集合={"左上"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.更新战斗学习(
            上下文,
            "失败",
            0,
            31,
            {
                "资源易窃取评分": 8.8,
                "资源易窃取评分依据": {"高价值资源可达折算": 75.0},
            },
        )

        学习 = 数据库实例.保存状态
        self.assertEqual(学习["下一场建议"], "分散探索")
        self.assertIn("滚动策略对比", 学习["最近原因"])
        self.assertIn("多方向4/6胜", 学习["最近原因"])

    def test_高评分高可达且已双向投放低表现后切换集中主力(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 45},
                            {"结果": "失败", "星数": 0, "摧毁率": 49},
                        ]
                    }
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="稳健三星/自适应分散探索",
            本场进攻方向=["右上", "右下"],
            本场进攻目标数量=4,
            本场边缘目标数量=4,
            本场进攻方向数量=2,
            当前兵栏清单=[{"类别": "兵种", "数量": 4}],
            _本场已确认投放数量=4,
            _本场已确认投放方向集合={"左上", "右下"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.更新战斗学习(
            上下文,
            "失败",
            0,
            33,
            {
                "金币": 2_316_340,
                "圣水": 2_316_326,
                "黑油": 17_047,
                "资源易窃取评分": 8.9,
                "资源易窃取评分依据": {"高价值资源可达折算": 74.9},
            },
        )

        学习 = 数据库实例.保存状态
        self.assertEqual(学习["下一场建议"], "集中资源")
        self.assertIn("集中主力方向", 学习["最近原因"])
        self.assertIn("双方向实际投放", 学习["建议依据"])
        self.assertNotIn("提高目标可达评分", 学习["最近原因"])

    def test_近期有失败但本场两星集中胜利时保留有效策略(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 34},
                            {"结果": "失败", "星数": 0, "摧毁率": 28},
                        ]
                    }
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="稳健三星/集中左上",
            本场进攻方向=["左上"],
            本场进攻目标数量=4,
            本场边缘目标数量=4,
            本场进攻方向数量=1,
            当前兵栏清单=[{"类别": "兵种", "数量": 34}],
            _本场已确认投放数量=34,
            _本场已确认投放方向集合={"左上"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)

        任务.更新战斗学习(
            上下文,
            "胜利",
            2,
            72,
            {
                "金币": 359_884,
                "圣水": 543_600,
                "黑油": 6_095,
                "资源易窃取评分": 7.9,
                "资源易窃取评分依据": {"储存建筑数": 1, "高价值资源可达折算": 50.5},
            },
        )

        学习 = 数据库实例.保存状态
        self.assertEqual(学习["下一场建议"], "集中资源")
        self.assertIn("本场单方向集中取得2星", 学习["建议依据"])
        self.assertIn("本场表现正常", 学习["最近原因"])

    def test_本场已集中且高可达低表现时提高门槛并分散(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 36},
                            {"结果": "失败", "星数": 0, "摧毁率": 44},
                        ]
                    }
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="稳健三星/集中左下",
            本场进攻方向=["左下"],
            本场进攻目标数量=4,
            本场边缘目标数量=4,
            本场进攻方向数量=1,
            当前兵栏清单=[{"类别": "兵种", "数量": 34}],
            _本场已确认投放数量=34,
            _本场已确认投放方向集合={"左下"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.生成战斗诊断 = lambda *_参数: (
            "高评分且高可达资源目标仍低摧毁：可达评分已足够，"
            "下一场集中主力方向、减少分兵并观察突破效果"
        )

        任务.更新战斗学习(
            上下文,
            "失败",
            0,
            36,
            {"资源易窃取评分": 9.1, "资源易窃取评分依据": {"高价值资源可达折算": 80}},
        )

        学习 = 数据库实例.保存状态
        self.assertEqual(学习["下一场建议"], "提高目标可达评分")
        self.assertIn("临时收紧搜索门槛", 学习["建议依据"])
        self.assertIn("提高目标可达评分并继续双方向探索", 学习["最近原因"])

    def test_先前失败被胜利打断后单场失败不触发策略切换(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 36},
                            {"结果": "胜利", "星数": 2, "摧毁率": 62},
                        ]
                    }
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="稳健三星/集中左下",
            本场进攻方向=["左下"],
            本场进攻目标数量=4,
            本场边缘目标数量=4,
            本场进攻方向数量=1,
            当前兵栏清单=[{"类别": "兵种", "数量": 34}],
            _本场已确认投放数量=34,
            _本场已确认投放方向集合={"左下"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.生成战斗诊断 = lambda *_参数: (
            "高评分且高可达资源目标仍低摧毁：可达评分已足够，"
            "下一场集中主力方向、减少分兵并观察突破效果"
        )

        任务.更新战斗学习(
            上下文,
            "失败",
            0,
            36,
            {"资源易窃取评分": 9.1, "资源易窃取评分依据": {"高价值资源可达折算": 80}},
        )

        学习 = 数据库实例.保存状态
        self.assertEqual(学习["下一场建议"], "集中资源")
        self.assertNotIn("提高目标可达评分", 学习["建议依据"])

    def test_一星胜利打断旧失败序列并保留当前集中策略(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 40},
                            {"结果": "失败", "星数": 0, "摧毁率": 44},
                        ]
                    }
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="稳健三星/集中左上",
            本场进攻方向=["左上"],
            本场进攻目标数量=4,
            本场边缘目标数量=4,
            本场进攻方向数量=1,
            当前兵栏清单=[{"类别": "兵种", "数量": 34}],
            _本场已确认投放数量=34,
            _本场已确认投放方向集合={"左上"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.生成战斗诊断 = lambda *_参数: (
            "已获胜但星数偏低：下一场提高目标可达评分，"
            "并在有可靠目标时分散入口"
        )

        任务.更新战斗学习(
            上下文,
            "胜利",
            1,
            50,
            {"资源易窃取评分": 8.2, "资源易窃取评分依据": {"高价值资源可达折算": 66.6}},
        )

        学习 = 数据库实例.保存状态
        self.assertEqual(学习["下一场建议"], "集中资源")
        self.assertIn("本场单方向集中取得1星胜利", 学习["建议依据"])

    def test_最近已评分低表现目标可达偏低时继续筛选(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "星数": 0, "摧毁率": 45},
                            {"结果": "失败", "星数": 0, "摧毁率": 49},
                        ]
                    }
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="稳健三星/自适应分散探索",
            本场进攻方向=["右上", "左下"],
            本场进攻目标数量=4,
            本场边缘目标数量=4,
            本场进攻方向数量=2,
            当前兵栏清单=[{"类别": "兵种", "数量": 4}],
            _本场已确认投放数量=4,
            _本场已确认投放方向集合={"右上", "左下"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)

        任务.更新战斗学习(
            上下文,
            "失败",
            0,
            30,
            {
                "资源易窃取评分": 7.4,
                "资源易窃取评分依据": {"高价值资源可达折算": 55.2},
            },
        )

        self.assertEqual(数据库实例.保存状态["下一场建议"], "提高目标可达评分")
        self.assertIn("低于集中突破门槛", 数据库实例.保存状态["建议依据"])

    def test_后续战斗无评分时沿用最近高可达失败证据(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {
                                "结果": "失败", "星数": 0, "摧毁率": 33,
                                "资源易窃取评分": 8.9,
                                "资源易窃取评分依据": {
                                    "高价值资源可达折算": 74.9,
                                },
                                "目标数量": 4,
                                "边缘目标数量": 4,
                                "进攻方向数量": 2,
                                "可部署单位数量": 4,
                                "实际投放数量": 4,
                                "实际投放方向": ["右上", "左下"],
                            },
                            {
                                "结果": "失败", "星数": 0, "摧毁率": 49,
                                "资源易窃取评分": None,
                                "资源易窃取评分依据": {"状态": "不可用"},
                                "目标数量": 4,
                                "边缘目标数量": 4,
                                "进攻方向数量": 2,
                                "可部署单位数量": 4,
                                "实际投放数量": 4,
                                "实际投放方向": ["右上", "左下"],
                            },
                        ]
                    }
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="稳健三星/自适应分散探索",
            本场进攻方向=["右上", "左下"],
            本场进攻目标数量=4,
            本场边缘目标数量=4,
            本场进攻方向数量=2,
            当前兵栏清单=[{"类别": "兵种", "数量": 4}],
            _本场已确认投放数量=4,
            _本场已确认投放方向集合={"右上", "左下"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)

        任务.更新战斗学习(
            上下文,
            "失败",
            0,
            30,
            {
                "金币": None,
                "圣水": None,
                "黑油": None,
                "资源评分状态": "不可用",
            },
        )

        self.assertEqual(数据库实例.保存状态["下一场建议"], "集中资源")
        self.assertIn("8.9", 数据库实例.保存状态["建议依据"])

    def test_一星胜利按胜率目标保留当前集中策略(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "胜利", "星数": 1, "摧毁率": 73},
                            {"结果": "胜利", "星数": 1, "摧毁率": 54},
                        ]
                    }
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
               自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="稳健三星/集中左下",
            本场进攻方向=["左下"],
            本场进攻目标数量=4,
            本场边缘目标数量=4,
            本场进攻方向数量=1,
            当前兵栏清单=[{"类别": "兵种", "数量": 34}],
            _本场已确认投放数量=34,
            _本场已确认投放方向集合={"左下"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)

        任务.更新战斗学习(
            上下文, "胜利", 1, 54,
            {"金币": 500_000, "圣水": 600_000, "黑油": 0},
        )

        self.assertEqual(数据库实例.保存状态["下一场建议"], "集中资源")
        self.assertIn("本场单方向集中取得1星胜利", 数据库实例.保存状态["建议依据"])
        self.assertNotIn("提高目标可达评分", 数据库实例.保存状态["最近原因"])

    def test_双方向分散覆盖且无评分时集中主力验证(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "摧毁率": 10},
                            {"结果": "失败", "摧毁率": 20},
                        ]
                    }
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="资源全覆盖+分散探索",
            本场进攻方向=["左上", "右上"],
            本场进攻目标数量=18,
            本场边缘目标数量=14,
            本场进攻方向数量=2,
            当前兵栏清单=[{"类别": "兵种", "数量": 18}],
            _本场已确认投放数量=18,
            _本场已确认投放方向集合={"左上", "右上"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.更新战斗学习(
            上下文,
            "失败",
            0,
            20,
            {"金币": 0, "圣水": 100, "黑油": 200},
        )
        self.assertEqual(数据库实例.保存状态["下一场建议"], "集中资源")
        self.assertIn("评分不可用", 数据库实例.保存状态["建议依据"])

    def test_实战上限四目标无评分时低表现后切换为集中资源(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "摧毁率": 48},
                            {"结果": "失败", "摧毁率": 38},
                        ]
                    }
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="稳健三星/自适应分散探索",
            本场进攻方向=["左上", "右上", "左下", "右下"],
            本场进攻目标数量=4,
            本场边缘目标数量=4,
            本场进攻方向数量=4,
            当前兵栏清单=[{"类别": "兵种", "数量": 4}],
            _本场已确认投放数量=4,
            _本场已确认投放方向集合={"左上", "右上", "左下", "右下"},
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.更新战斗学习(
            上下文,
            "失败",
            0,
            38,
            {"金币": 2048281, "圣水": 1943095, "黑油": 0},
        )
        self.assertEqual(数据库实例.保存状态["下一场建议"], "集中资源")
        self.assertIn("评分不可用", 数据库实例.保存状态["建议依据"])

    def test_实机结算星形布局识别两星(self):
        图片 = Path(__file__).resolve().parents[1] / ".tmp" / "runtime_after_battle_wait.png"
        if not 图片.exists():
            self.skipTest("没有维护观察截图")
        数据 = np.fromfile(图片, dtype=np.uint8)
        图像 = cv2.imdecode(数据, cv2.IMREAD_COLOR)
        self.assertIsNotNone(图像)
        self.assertEqual(等待战斗结束并回营任务.识别星数(图像, "胜利"), 2)

    def test_测试服夜世界三角星布局无胜负文字仍识别亮星(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)

        def 画星(中心x, 中心y, 半径=52):
            点 = []
            for 索引 in range(10):
                角度 = -np.pi / 2 + 索引 * np.pi / 5
                当前半径 = 半径 if 索引 % 2 == 0 else 半径 * 0.42
                点.append((
                    round(中心x + 当前半径 * np.cos(角度)),
                    round(中心y + 当前半径 * np.sin(角度)),
                ))
            cv2.fillPoly(图像, [np.asarray(点, dtype=np.int32)], (40, 180, 240))

        # 夜世界测试服实际布局为左下、中央上、右下；这里只点亮左星。
        画星(310, 180)
        self.assertEqual(
            等待战斗结束并回营任务.识别星数(图像, "推毁率54%"),
            1,
        )

    def test_结算横幅灰度OCR补足繁体战败(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        调用维度 = []

        def 假OCR(图像, **_参数):
            调用维度.append(getattr(图像, "ndim", None))
            if getattr(图像, "ndim", None) == 2:
                return [([], "載敗")], None
            return [], None

        任务.ocr引擎 = 假OCR
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        文本 = 任务.识别结果页横幅文本(图像)
        self.assertIn("敗", 文本)
        self.assertIn(3, 调用维度)
        self.assertIn(2, 调用维度)

    def test_点击回营后必须确认主界面(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务.记录战斗结果 = lambda *_参数, **_关键字: True
        上下文 = _上下文()

        结果 = 任务.等待回营地按钮出现(上下文)

        self.assertTrue(结果)
        self.assertEqual(上下文.点击记录, [(120, 130)])
        self.assertIn("已确认回到主界面，可进入下一场", 上下文.状态)

    def test_回营使用已确认安全按钮绕过结算页普通点击护栏(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务.记录战斗结果 = lambda *_参数, **_关键字: True
        上下文 = _上下文()
        上下文.点击 = unittest.mock.Mock(
            side_effect=AssertionError("结算页不应使用普通点击")
        )
        上下文.点击已确认安全按钮 = unittest.mock.Mock(return_value=True)

        结果 = 任务.等待回营地按钮出现(上下文)

        self.assertTrue(结果)
        上下文.点击已确认安全按钮.assert_called_once_with(120, 130)
        上下文.点击.assert_not_called()

    def test_主世界左下回营卡片模板失配时走视觉回营回退(self):
        """真实主世界结算布局没有中央模板时仍必须安全回营。"""
        结算图 = np.full((600, 800, 3), (35, 35, 35), dtype=np.uint8)
        cv2.rectangle(结算图, (360, 165), (475, 195), (235, 235, 235), -1)
        cv2.rectangle(结算图, (12, 478), (93, 584), (180, 180, 180), -1)

        class 低分匹配器:
            def 执行匹配(self, *_参数, **_关键字参数):
                return False, (0, 0), None

        class 页面识别器:
            def __init__(自身):
                自身.次数 = 0

            def 识别(自身, _图像, **_参数):
                自身.次数 += 1
                页面 = "战斗结算" if 自身.次数 <= 2 else "主世界主页"
                return type("结果", (), {
                    "页面": 页面, "可信度": 0.92,
                    "依据": ("主世界资源栏0.98", "主世界入口0.90")
                    if 页面 == "主世界主页" else (),
                })()

            def 定位结算回营按钮(自身, _图像):
                return (52, 530)

        class 屏幕:
            def 获取屏幕图像cv(自身, *_区域):
                return 结算图

        class 上下文:
            op = 屏幕()
            模板识别 = 低分匹配器()
            _已确认进入战斗 = False

            def __init__(自身):
                自身.点击记录 = []
                自身.状态 = []
                自身._获取点击页面识别器 = lambda: 页面识别器实例

            def 置脚本状态(自身, 文本, *_参数, **_关键字参数):
                自身.状态.append(文本)

            def 脚本延时(自身, _毫秒):
                pass

            def 点击(自身, x, y, *_参数, **_关键字参数):
                自身.点击记录.append((x, y))
                return True

        页面识别器实例 = 页面识别器()
        上下文实例 = 上下文()
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 上下文实例.模板识别
        任务.记录战斗结果 = lambda *_参数, **_关键字: True
        任务.上下文 = 上下文实例

        self.assertTrue(任务.等待回营地按钮出现(上下文实例))
        self.assertEqual(上下文实例.点击记录, [(52, 530)])
        self.assertIn("视觉确认结算页回营按钮", " ".join(上下文实例.状态))

    def test_单帧误判结算随后仍是战斗时不点击(self):
        class 低分匹配器:
            def 执行匹配(self, *_参数, **_关键字参数):
                return False, (0, 0), None

        class 页面识别器:
            def __init__(自身):
                自身.次数 = 0

            def 识别(自身, _图像, **_参数):
                自身.次数 += 1
                return SimpleNamespace(
                    页面="战斗结算" if 自身.次数 == 1 else "战斗中",
                    可信度=0.96,
                )

            def 定位结算回营按钮(自身, _图像):
                return (80, 522)

        class 屏幕:
            def 获取屏幕图像cv(self, *_区域, **_参数):
                return np.zeros((600, 800, 3), dtype=np.uint8)

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 低分匹配器()
        任务.记录战斗结果 = unittest.mock.Mock(return_value=True)
        上下文 = _上下文()
        上下文.op = 屏幕()
        上下文._获取点击页面识别器 = lambda: 页面识别器实例
        页面识别器实例 = 页面识别器()

        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.time",
            side_effect=[0, 1, 2, 361],
        ):
            self.assertFalse(任务.等待回营地按钮出现(上下文))
        self.assertEqual(上下文.点击记录, [])
        任务.记录战斗结果.assert_not_called()
        self.assertIn("单帧", " ".join(上下文.状态))

    def test_两帧伪结算后新帧仍有放弃按钮不记录也不点击(self):
        """实机第三场倒计时尚在，却连续误报结算并误记胜利。"""
        class 低分匹配器:
            def 执行匹配(self, *_参数, **_关键字参数):
                return False, (0, 0), None

        class 页面识别器:
            def _红色放弃按钮分数(self, 图像):
                return 0.93 if 图像[0, 0, 0] == 2 else 0.0

            def _战斗倒计时分数(self, _图像):
                return 0.0

            def 识别(self, _图像, **_参数):
                return SimpleNamespace(页面="战斗结算", 可信度=0.94)

            def 定位结算回营按钮(self, _图像):
                return (436, 553)

        class 屏幕:
            def __init__(self):
                self.次数 = 0

            def 获取屏幕图像cv(self, *_区域, **_参数):
                图像 = np.zeros((600, 800, 3), dtype=np.uint8)
                图像[0, 0, 0] = min(self.次数, 2)
                self.次数 += 1
                return 图像

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 低分匹配器()
        任务.记录战斗结果 = unittest.mock.Mock(return_value=True)
        上下文 = _上下文()
        上下文.op = 屏幕()
        上下文._获取点击页面识别器 = lambda: 页面识别器()
        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.time",
            side_effect=[0, 1, 2, 361],
        ):
            self.assertFalse(任务.等待回营地按钮出现(上下文))
        任务.记录战斗结果.assert_not_called()
        self.assertEqual(上下文.点击记录, [])
        self.assertTrue(any("不记录结果、不点击回营" in 项 for 项 in 上下文.状态))

    def test_第三帧单项战斗信号但结算页和回营按钮稳定时继续(self):
        class 低分匹配器:
            def 执行匹配(self, *_参数, **_关键字参数):
                return False, (0, 0), None

        class 页面识别器:
            def _红色放弃按钮分数(self, _图像):
                return 0.0

            def _战斗倒计时分数(self, 图像):
                return 0.96 if 图像[0, 0, 0] == 2 else 0.0

            def _结算结果视觉分数(self, _图像):
                return 0.94

            def 识别(self, _图像, **_参数):
                return SimpleNamespace(页面="战斗结算", 可信度=0.94)

            def 定位结算回营按钮(self, 图像, 允许单帧战斗信号=False):
                if 图像[0, 0, 0] == 2 and not 允许单帧战斗信号:
                    return None
                return (436, 553)

        class 屏幕:
            def __init__(self):
                self.次数 = 0

            def 获取屏幕图像cv(self, *_区域, **_参数):
                图像 = np.zeros((600, 800, 3), dtype=np.uint8)
                图像[0, 0, 0] = min(self.次数, 2)
                self.次数 += 1
                return 图像

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 低分匹配器()
        任务.识别结算帧 = unittest.mock.Mock(
            return_value=([], "战败", "失败", 44)
        )
        任务.识别星数 = unittest.mock.Mock(return_value=0)
        任务.保存战斗结果截图 = unittest.mock.Mock()
        任务.更新战斗学习 = unittest.mock.Mock()
        任务.生成战斗诊断 = unittest.mock.Mock(return_value="已确认战败")
        数据库 = unittest.mock.Mock()
        数据库.获取最新完整状态.return_value = SimpleNamespace(状态数据={})
        任务.等待主界面就绪 = unittest.mock.Mock(return_value=True)
        上下文 = _上下文()
        上下文.数据库 = 数据库
        上下文.机器人标志 = "测试机器人"
        上下文.本场实时摧毁率 = 44
        上下文.本场最高实时摧毁率 = 44
        上下文.本场目标战利品 = {}
        上下文.英雄技能状态 = {}
        上下文.op = 屏幕()
        上下文._已确认进入战斗 = True
        上下文.点击已确认安全按钮 = unittest.mock.Mock(return_value=True)
        上下文.清除战斗结算保护状态 = unittest.mock.Mock()
        页面 = 页面识别器()
        上下文._获取点击页面识别器 = lambda: 页面

        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.time",
            side_effect=[0, 1, 2, 361],
        ), unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.检测游戏登录状态任务._检测断线弹窗",
            return_value=(False, None),
        ):
            回营成功 = 任务.等待回营地按钮出现(上下文)

        self.assertTrue(回营成功)
        上下文.点击已确认安全按钮.assert_called_once_with(436, 553)
        self.assertTrue(any("单项残留战斗信号" in 项 for 项 in 上下文.状态))
        统计 = 数据库.更新状态.call_args.args[2]
        self.assertEqual(统计["最近结果"], "失败")
        self.assertEqual(统计["最近星数"], 0)
        self.assertEqual(统计["最近摧毁率"], 44)

    def test_旧战斗结束标记不能覆盖当前放弃按钮(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        识别器 = SimpleNamespace(
            _红色放弃按钮分数=lambda _图像: 0.93,
            _战斗倒计时分数=lambda _图像: 0.96,
        )
        上下文 = SimpleNamespace(
            _战斗结束已确认=True,
            _获取点击页面识别器=lambda: 识别器,
        )
        self.assertFalse(任务._结果页按钮可信(上下文, 画面))

    def test_主世界页级识别低于模板阈值仍可确认回营(self):
        class 页级识别器:
            def 识别(self, _图像, **_参数):
                return SimpleNamespace(
                    页面="主世界主页",
                    可信度=0.57,
                    依据=("主世界资源栏0.98", "主世界入口0.90"),
                )

        class 低模板匹配器:
            def 执行匹配(self, _图像, _模板路径, **_参数):
                return False, (0, 0), None

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 低模板匹配器()
        上下文 = _上下文()
        上下文._获取点击页面识别器 = lambda: 页级识别器()

        self.assertTrue(任务.等待主界面就绪(上下文))
        self.assertIn("页面识别连续确认已回到主世界", " ".join(上下文.状态))

    def test_人工回到新版主世界战斗模式选择页后可接续(self):
        页面 = SimpleNamespace(
            页面="主世界战斗模式选择",
            世界="主世界",
            可信度=0.96,
            依据=("左侧橙色普通战斗按钮", "右侧蓝色排位报名按钮"),
        )
        self.assertTrue(等待战斗结束并回营任务._可接续主世界页面可信(页面))

        页面.可信度 = 0.89
        self.assertFalse(等待战斗结束并回营任务._可接续主世界页面可信(页面))
        页面.可信度 = 0.96
        页面.世界 = "夜世界"
        self.assertFalse(等待战斗结束并回营任务._可接续主世界页面可信(页面))

    def test_回营确认新版模式页时保存任务接续状态(self):
        class 页面识别器:
            def 识别(自身, _图像, **_参数):
                return SimpleNamespace(
                    页面="主世界战斗模式选择",
                    世界="主世界",
                    可信度=0.96,
                )

        class 屏幕:
            def 获取屏幕图像cv(自身, *_区域):
                return object()

        上下文 = _上下文()
        上下文.op = 屏幕()
        上下文._获取点击页面识别器 = lambda: 页面识别器()
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = unittest.mock.Mock()

        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.检测游戏登录状态任务._检测断线弹窗",
            return_value=(False, (0, 0)),
        ):
            self.assertTrue(任务.等待主界面就绪(上下文))

        self.assertTrue(上下文._主世界战斗模式选择页)
        任务.模板识别.执行匹配.assert_not_called()

    def test_战斗等待期间人工回到新版主世界页后接续任务(self):
        class 页面识别器:
            def 识别(自身, _图像, **_参数):
                return SimpleNamespace(
                    页面="主世界战斗模式选择",
                    世界="主世界",
                    可信度=0.96,
                    依据=("左侧橙色普通战斗按钮", "右侧蓝色排位报名按钮"),
                )

        class 屏幕:
            def 获取屏幕图像cv(自身, *_区域, **_参数):
                return object()

        上下文 = _上下文()
        上下文._已确认进入战斗 = True
        上下文.op = 屏幕()
        上下文._获取点击页面识别器 = lambda: 页面识别器()
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务._确认无结算回城 = unittest.mock.Mock(return_value=True)

        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.检测游戏登录状态任务._检测断线弹窗",
            return_value=(False, (0, 0)),
        ):
            self.assertTrue(任务.等待回营地按钮出现(上下文))

        任务._确认无结算回城.assert_called_once_with(
            上下文, "人工或游戏自动回营", 结果已记录=False
        )

    def test_新版主页战斗入口证据可连续确认回营(self):
        class 新版主页识别器:
            def 识别(self, _图像, **_参数):
                return SimpleNamespace(
                    页面="主世界主页",
                    可信度=0.70,
                    依据=("主世界资源栏0.94", "新版战斗入口0.99"),
                )

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = unittest.mock.Mock()
        上下文 = _上下文()
        上下文._获取点击页面识别器 = lambda: 新版主页识别器()

        self.assertTrue(任务.等待主界面就绪(上下文))
        self.assertIn("页面识别连续确认已回到主世界", " ".join(上下文.状态))
        任务.模板识别.执行匹配.assert_not_called()

    def test_断线弹窗露出底层主世界图标时不能误判回营(self):
        class 页面识别器:
            def 识别(self, _图像, **_参数):
                return SimpleNamespace(页面="断线弹窗", 可信度=0.98)

        class 评分匹配器:
            def __init__(自身):
                自身.调用次数 = 0

            def 执行匹配(自身, _图像, 模板路径, **_参数):
                自身.调用次数 += 1
                if "家乡进攻图标" in 模板路径:
                    return True, (0, 0), None
                return False, (0, 0), None

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 评分匹配器()
        上下文 = _上下文()
        上下文._获取点击页面识别器 = lambda: 页面识别器()

        # 让超时测试不等待真实30秒：第一次进入循环，第二次直接超时。
        with unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.time",
            side_effect=[0, 1, 31],
        ):
            结果 = 任务.等待主界面就绪(上下文)

        self.assertFalse(结果)
        self.assertEqual(上下文.点击记录, [])
        self.assertEqual(任务.模板识别.调用次数, 0)
        self.assertIn("断线弹窗", " ".join(上下文.状态))

    def test_主世界页级识别被断线遮罩误导时不放行(self):
        上下文 = _上下文()
        上下文._获取点击页面识别器 = lambda: SimpleNamespace(
            识别=lambda _图像, **_参数: SimpleNamespace(
                页面="主世界主页", 可信度=0.78
            )
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = unittest.mock.Mock()
        with unittest.mock.patch.object(
            检测游戏登录状态任务, "_检测断线弹窗",
            return_value=(True, (250, 365)),
        ), unittest.mock.patch(
            "任务流程.主世界打鱼.等待战斗结束并回营.time.time",
            side_effect=[0, 1, 31],
        ):
            self.assertFalse(任务.等待主界面就绪(上下文))
        self.assertIn("断线弹窗", " ".join(上下文.状态))
        self.assertEqual(上下文.点击记录, [])

    def test_实机零点八五分结算按钮会进入回营流程(self):
        class 评分匹配器:
            def 执行匹配(self, _图像, 模板路径, 相似度阈值=0.8, **_参数):
                if "家乡进攻图标" in 模板路径:
                    return True, (0, 0), None
                if "回营" in 模板路径:
                    return 相似度阈值 <= 0.85, (409, 520), None
                return False, (0, 0), None

        class 页面识别器:
            def __init__(自身):
                自身.调用次数 = 0

            def 识别(self, _图像, **_参数):
                self.调用次数 += 1
                return SimpleNamespace(
                    页面="主世界主页", 可信度=0.78,
                    依据=("主世界资源栏0.98", "主世界入口0.90"),
                )

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 评分匹配器()
        任务.记录战斗结果 = lambda *_参数, **_关键字: True
        上下文 = _上下文()
        页面识别器实例 = 页面识别器()
        上下文._获取点击页面识别器 = lambda: 页面识别器实例
        上下文._战斗结束已确认 = True

        结果 = 任务.等待回营地按钮出现(上下文)

        self.assertTrue(结果)
        self.assertEqual(上下文.点击记录, [(409, 520)])
        self.assertIn("检测到回营按钮，点击返回主界面", 上下文.状态)

    def test_回营点击未生效后复核按钮再试一次(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务.记录战斗结果 = unittest.mock.Mock(return_value=True)
        任务.等待主界面就绪 = unittest.mock.Mock(side_effect=[False, True])
        上下文 = _上下文()
        上下文._战斗结束已确认 = True

        self.assertTrue(任务.等待回营地按钮出现(上下文))
        self.assertEqual(上下文.点击记录, [(120, 130), (120, 130)])
        任务.记录战斗结果.assert_called_once()

    def test_两次回营点击仍未确认主世界则停止(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务.记录战斗结果 = unittest.mock.Mock(return_value=True)
        任务.等待主界面就绪 = unittest.mock.Mock(side_effect=[False, False])
        上下文 = _上下文()
        上下文._战斗结束已确认 = True

        self.assertFalse(任务.等待回营地按钮出现(上下文))
        self.assertEqual(len(上下文.点击记录), 2)

    def test_战斗统计不完整时不点击回营也不开启下一场(self):
        class 评分匹配器:
            def 执行匹配(self, _图像, 模板路径, 相似度阈值=0.8, **_参数):
                if "回营" in 模板路径:
                    return 相似度阈值 <= 0.85, (409, 520), None
                return False, (0, 0), None

        class 页面识别器:
            def 识别(self, _图像, **_参数):
                return SimpleNamespace(页面="战斗结算", 可信度=0.85)

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 评分匹配器()
        任务.记录战斗结果 = lambda *_参数, **_关键字: False
        上下文 = _上下文()
        上下文._获取点击页面识别器 = lambda: 页面识别器()

        任务.等待主界面就绪 = unittest.mock.Mock(return_value=True)

        # rc147：字段补拍仍不完整时，两张新帧确认结算页与同位置回营按钮
        # 后安全回营，本场不计入统计（原先会停在结算页安全待命 10~20 分钟）。
        结果 = 任务.等待回营地按钮出现(上下文)

        self.assertTrue(结果)
        self.assertEqual(上下文.点击记录[:1], [(409, 520)])
        self.assertIn("不计入", " ".join(上下文.状态))

    def test_战斗统计不完整且新帧不是结算页时不点击回营(self):
        class 评分匹配器:
            def 执行匹配(self, _图像, 模板路径, 相似度阈值=0.8, **_参数):
                if "回营" in 模板路径:
                    return 相似度阈值 <= 0.85, (409, 520), None
                return False, (0, 0), None

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 评分匹配器()
        任务.记录战斗结果 = lambda *_参数, **_关键字: False
        任务._两帧确认结算页可回营 = lambda *_参数: False
        上下文 = _上下文()
        上下文._获取点击页面识别器 = lambda: SimpleNamespace(
            识别=lambda *_a, **_k: SimpleNamespace(页面="战斗结算", 可信度=0.85)
        )

        结果 = 任务.等待回营地按钮出现(上下文)

        self.assertFalse(结果)
        self.assertEqual(上下文.点击记录, [])
        self.assertIn("未完整确认", " ".join(上下文.状态))

    def test_回营按钮输入被拒绝时不继续确认主界面(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务.记录战斗结果 = lambda *_参数, **_关键字: True
        任务.等待主界面就绪 = unittest.mock.Mock(return_value=True)
        上下文 = _上下文()
        上下文._战斗结束已确认 = True
        原始点击 = 上下文.点击

        def 拒绝点击(*参数, **关键字):
            原始点击(*参数, **关键字)
            return False

        上下文.点击 = 拒绝点击

        结果 = 任务.等待回营地按钮出现(上下文)

        self.assertFalse(结果)
        任务.等待主界面就绪.assert_not_called()
        self.assertIn("输入被拒绝", " ".join(上下文.状态))


if __name__ == "__main__":
    unittest.main()
