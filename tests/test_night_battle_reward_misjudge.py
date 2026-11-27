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


if __name__ == "__main__":
    unittest.main()
