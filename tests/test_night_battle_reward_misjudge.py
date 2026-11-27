"""rc164 11-27 21:57 夜世界战斗误判奖励选择 → 安全待命永久停滞回放。

1. 夜世界下兵时“請選擇其他兵種/你無法在紅線區域內派遣部隊！”红色飘字与
   爆炸红光拼出“奖励选择红色横幅 + 2 张卡片”，同帧红色放弃按钮 0.93、
   战斗倒计时 0.96 仍被挂起成奖励候选，下兵失败进入安全待命。
2. 安全待命连续 3 帧“战斗中”即自动恢复，耗掉唯一额度，在战场里开下一轮
   （部落竞赛/主世界刷资源）世界识别失败再次待命。
3. 战斗结束回营后停在夜世界主页（0.74），额度已用完，永久只读等待。

样本均为现场截图只读复制。
"""
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from 模块.检测.页面识别器 import 页面识别器
from 模块.检测.模板匹配器 import 模板匹配引擎
from 线程.自动化机器人 import 自动化机器人

测试目录 = Path(__file__).resolve().parent
样本目录 = 测试目录 / "回放样本"
战斗飘字图 = 样本目录 / "night_battle_reward_misjudge_20261127_215731.png"
夜世界主页图 = (
    样本目录 / "standby_night_home_20261127_220053.png",
    样本目录 / "standby_night_home_current_20261127_220053.png",
)


def 读取(文件: Path) -> np.ndarray:
    图像 = cv2.imdecode(np.fromfile(str(文件), dtype=np.uint8), cv2.IMREAD_COLOR)
    if 图像 is None:
        raise AssertionError(f"无法读取样本：{文件}")
    if 图像.shape[:2] != (600, 800):
        图像 = cv2.resize(图像, (800, 600), interpolation=cv2.INTER_AREA)
    return 图像


def _页面(名称, 世界=None, 可信度=0.0):
    return SimpleNamespace(页面=名称, 世界=世界, 可信度=可信度)


class 夜世界战斗飘字误判奖励回放测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.引擎 = 模板匹配引擎(图片库路径=测试目录.parent / "img")

    def test_红色飘字战斗帧识别为战斗中而非奖励候选(self):
        图 = 读取(战斗飘字图)
        for 战斗中 in (True, False):
            with self.subTest(战斗中=战斗中):
                结果 = 页面识别器(self.引擎).识别(图, 战斗中=战斗中)
                self.assertEqual(结果.页面, "战斗中", 结果.依据)
                self.assertFalse(any("奖励" in 项 for 项 in 结果.依据), 结果.依据)

    def test_红色飘字连续新帧不会跨帧确认奖励选择(self):
        识别器 = 页面识别器(self.引擎)
        图 = 读取(战斗飘字图)
        with patch(
            "模块.检测.页面识别器._奖励候选单调时间",
            side_effect=[10.0, 10.6, 11.2],
        ):
            页面序列 = [
                识别器.识别(图.copy(), 战斗中=True).页面 for _ in range(3)
            ]
        self.assertEqual(页面序列, ["战斗中"] * 3)

    def test_回营后的夜世界主页截图识别为夜世界主页(self):
        for 文件 in 夜世界主页图:
            with self.subTest(文件=文件.name):
                结果 = 页面识别器(self.引擎).识别(读取(文件), 战斗中=False)
                self.assertEqual(结果.页面, "夜世界主页", 结果.依据)
                self.assertEqual(结果.世界, "夜世界")
                self.assertGreaterEqual(结果.可信度, 0.70)


class 安全待命战斗中到夜世界主页恢复测试(unittest.TestCase):
    def _创建机器人(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.停止事件 = threading.Event()
        机器人.继续事件 = threading.Event()
        机器人.继续事件.set()
        机器人.停止原因 = ""
        机器人.记录日志 = Mock()
        时间 = [0.0]

        def 等待(timeout=None):
            时间[0] += float(timeout or 0.0)
            return 机器人.停止事件.is_set()

        机器人.停止事件.wait = Mock(side_effect=等待)
        计时器 = patch(
            "线程.自动化机器人._安全待命单调时间", side_effect=lambda: 时间[0]
        )
        计时器.start()
        self.addCleanup(计时器.stop)
        return 机器人

    def test_战斗中不耗额度_结算回营后夜世界主页恢复并认清夜世界(self):
        机器人 = self._创建机器人()
        战斗页 = _页面("战斗中", 可信度=0.96)
        结算页 = _页面("战斗结算", 可信度=0.94)
        夜页 = _页面("夜世界主页", "夜世界", 0.74)
        页面序列 = [战斗页] * 8 + [结算页, 结算页] + [夜页] * 3

        def 读取页面(**_参数):
            if not 页面序列:
                机器人.停止事件.set()
                return 夜页
            return 页面序列.pop(0)

        上下文 = SimpleNamespace(
            _待命恢复世界="夜世界",
            _战斗中=True,
            识别点击画面=Mock(side_effect=读取页面),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        机器人._安全待命结算回营 = Mock(return_value=True)

        self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))

        机器人._安全待命结算回营.assert_called_once()
        self.assertEqual(上下文._安全待命自动恢复次数, 1)
        self.assertEqual(上下文._待命恢复世界, "夜世界")
        self.assertFalse(上下文._战斗中)
        恢复日志 = [
            调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list
            if "自动恢复：" in 调用.args[0]
        ]
        self.assertEqual(len(恢复日志), 1)
        self.assertIn("夜世界主页", 恢复日志[0])

    def test_主世界任务待命中的夜世界主页也可恢复且心跳不只等主世界(self):
        机器人 = self._创建机器人()
        夜页 = _页面("夜世界主页", "夜世界", 0.74)
        上下文 = SimpleNamespace(
            _待命恢复世界="主世界",
            识别点击画面=Mock(return_value=夜页),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))
        self.assertEqual(上下文._待命恢复世界, "夜世界")
        self.assertEqual(上下文.识别点击画面.call_count, 3)


class 安全待命总时长上限测试(unittest.TestCase):
    """复审 aca9a9c P1：战斗永不结束/页面一直未知时不能无限只读等待。"""

    def _创建机器人(self):
        机器人 = 安全待命战斗中到夜世界主页恢复测试._创建机器人(self)
        机器人._处理待命超时告警 = Mock()
        return 机器人

    @staticmethod
    def _上下文(读取页面, 重启=None):
        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=读取页面),
            置脚本状态=Mock(),
            脚本延时=Mock(),
            点击已确认安全按钮=Mock(),
            页面恢复失败=True,
        )
        if 重启 is not None:
            上下文.安全重启游戏应用 = 重启
        return 上下文

    @staticmethod
    def _状态(上下文):
        return [调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list]

    def test_超时后安全重启一次并在夜世界主页按原逻辑恢复(self):
        机器人 = self._创建机器人()
        已重启 = [False]

        def 重启():
            已重启[0] = True
            return True

        def 读取页面(**_参数):
            if 已重启[0]:
                return _页面("夜世界主页", "夜世界", 0.74)
            return _页面("战斗中", 可信度=0.96)

        重启函数 = Mock(side_effect=重启)
        上下文 = self._上下文(读取页面, 重启函数)

        self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))

        重启函数.assert_called_once_with()
        self.assertFalse(机器人.停止事件.is_set())
        self.assertEqual(上下文._安全待命自动恢复次数, 1)
        self.assertEqual(上下文._待命恢复世界, "夜世界")
        上下文.点击已确认安全按钮.assert_not_called()
        self.assertFalse(any("[严重]" in 项 for 项 in self._状态(上下文)))

    def test_超时后重启失败则严重日志并安全停止(self):
        for 重启 in (Mock(return_value=False), Mock(side_effect=RuntimeError("adb"))):
            with self.subTest(重启=重启):
                机器人 = self._创建机器人()
                上下文 = self._上下文(
                    lambda **_参数: _页面("战斗中", 可信度=0.96), 重启
                )

                self.assertFalse(机器人._等待人工恢复主世界(上下文, Mock()))

                重启.assert_called_once_with()
                self.assertTrue(机器人.停止事件.is_set())
                self.assertTrue(上下文.页面恢复失败)
                self.assertFalse(hasattr(上下文, "_安全待命自动恢复次数"))
                self.assertTrue(any("[严重]" in 项 for 项 in self._状态(上下文)))
                上下文.点击已确认安全按钮.assert_not_called()
                # 首次截图在 0 秒，上限 900 秒，每轮 5 秒：不会无限等待。
                self.assertLessEqual(上下文.识别点击画面.call_count, 182)

    def test_无安全重启流程时到上限直接严重停止(self):
        机器人 = self._创建机器人()
        上下文 = self._上下文(lambda **_参数: _页面("未知"))

        self.assertFalse(机器人._等待人工恢复主世界(上下文, Mock()))

        self.assertTrue(机器人.停止事件.is_set())
        self.assertTrue(上下文.页面恢复失败)
        严重日志 = [项 for 项 in self._状态(上下文) if "[严重]" in 项]
        self.assertEqual(len(严重日志), 1)
        self.assertIn("未知", 严重日志[0])
        机器人.记录日志.assert_any_call(严重日志[0], 120)

    def test_重启成功但仍未回主页则第二个上限停止且只重启一次(self):
        机器人 = self._创建机器人()
        重启 = Mock(return_value=True)
        上下文 = self._上下文(lambda **_参数: _页面("未知"), 重启)

        self.assertFalse(机器人._等待人工恢复主世界(上下文, Mock()))

        重启.assert_called_once_with()
        self.assertTrue(机器人.停止事件.is_set())
        self.assertTrue(上下文.页面恢复失败)
        self.assertGreater(上下文.识别点击画面.call_count, 300)
        self.assertLessEqual(上下文.识别点击画面.call_count, 365)


if __name__ == "__main__":
    unittest.main()
