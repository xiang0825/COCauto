"""夜世界首个兵槽点击被结算跨帧护栏短暂拒绝时的重试与收尾。

回放 rc155 实机日志（2026-11-26 14:45~14:46，任务日志 560762~560777）：
立即寻找 -> 单帧“战斗星级奖励”误报（登记 2.5 秒结算视觉保护）-> 未知 ->
专用倒计时复核确认战斗 -> 点首个兵槽被“结算视觉刚跨帧消失”拒绝 ->
旧流程直接终止打鱼链并安全待命，战斗页一直挂着不下兵。
"""

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from 任务流程.夜世界.夜世界打鱼 import 夜世界打鱼任务
from 任务流程.夜世界.夜世界打鱼.现场截图 import 保存夜世界现场截图
from 任务流程.夜世界.夜世界打鱼.等待进入战斗 import 等待进入战斗


class _假时钟:
    def __init__(self):
        self.现在 = 1000.0

    def monotonic(self):
        return self.现在

    def 延时(self, 毫秒):
        self.现在 += float(毫秒) / 1000.0


def _日志(上下文):
    return [str(调用.args[0]) for 调用 in 上下文.置脚本状态.call_args_list if 调用.args]


class 首兵槽护栏重试测试(unittest.TestCase):
    def _构造回放上下文(self, 时钟, 页面序列, 永久拒绝=False):
        上下文 = SimpleNamespace(
            页面恢复失败=False,
            _战斗中=False,
            _最近结算视觉时间=0.0,
            置脚本状态=Mock(),
            停止事件=threading.Event(),
        )
        序列 = iter(页面序列)

        def 识别点击画面():
            try:
                页面 = next(序列)
            except StopIteration:
                页面 = "未知"
            # 与 基础任务框架.识别点击画面 一致：结算类页面登记跨帧保护。
            if 页面 in {"战斗结算", "战斗奖励选择", "战斗星级奖励"}:
                上下文._最近结算视觉时间 = 时钟.monotonic()
            return SimpleNamespace(页面=页面)

        def 点击(x, y, 是否精确点击=False):
            # 与 检查宝石商店危险页面 的 2.5 秒结算视觉保护一致。
            if 永久拒绝:
                return False
            最近 = 上下文._最近结算视觉时间
            if 最近 and 时钟.monotonic() - 最近 < 2.5:
                return False
            return True

        上下文.识别点击画面 = 识别点击画面
        上下文.点击 = Mock(side_effect=点击)
        上下文.处理战斗星级奖励弹窗 = Mock(return_value=False)
        上下文.脚本延时 = Mock(side_effect=时钟.延时)
        return 上下文

    def test_rc155日志序列回放_护栏窗口过期后重试成功选中兵槽(self):
        时钟 = _假时钟()
        上下文 = self._构造回放上下文(
            时钟, ["未知", "战斗星级奖励", "未知", "未知", "未知"]
        )
        任务 = 等待进入战斗.__new__(等待进入战斗)
        任务.上下文 = 上下文
        # 第一帧“未知”尚未出现倒计时；之后专用复核确认战斗。
        任务._页面已确认夜世界战斗 = Mock(side_effect=[False, True, True, True])

        with patch("time.monotonic", 时钟.monotonic):
            self.assertTrue(任务.执行())

        self.assertEqual(上下文.点击.call_count, 2)
        for 调用 in 上下文.点击.call_args_list:
            self.assertEqual(调用.args, (150, 520))
        self.assertTrue(上下文._战斗中)
        self.assertFalse(上下文.页面恢复失败)
        self.assertFalse(上下文._夜世界首兵槽未选中)
        日志 = _日志(上下文)
        self.assertTrue(any("暂时拒绝（第1次）" in 行 for 行 in 日志))
        self.assertTrue(any("选中首个普通兵槽" in 行 for 行 in 日志))
        # 等待时长覆盖剩余保护窗口，而不是盲目高频重点。
        self.assertGreaterEqual(上下文.脚本延时.call_args_list[-1].args[0], 600)

    def test_持续被拒绝时有限重试后交给回营且不标记页面恢复失败(self):
        时钟 = _假时钟()
        上下文 = self._构造回放上下文(时钟, [], 永久拒绝=True)
        任务 = 等待进入战斗.__new__(等待进入战斗)
        任务.上下文 = 上下文
        任务._页面已确认夜世界战斗 = Mock(return_value=True)

        with patch("time.monotonic", 时钟.monotonic):
            self.assertFalse(任务.执行())

        self.assertEqual(上下文.点击.call_count, 等待进入战斗.首兵槽最大尝试次数)
        self.assertTrue(上下文._夜世界首兵槽未选中)
        self.assertTrue(上下文._战斗中)
        self.assertFalse(上下文.页面恢复失败)
        self.assertTrue(any("交给回营流程" in 行 for 行 in _日志(上下文)))

    def test_结算页仍直接失败且不走兵槽重试(self):
        时钟 = _假时钟()
        上下文 = self._构造回放上下文(时钟, ["战斗结算"])
        任务 = 等待进入战斗.__new__(等待进入战斗)
        任务.上下文 = 上下文
        任务._页面已确认夜世界战斗 = Mock(return_value=True)

        with patch("time.monotonic", 时钟.monotonic):
            self.assertFalse(任务.执行())

        上下文.点击.assert_not_called()
        self.assertTrue(上下文.页面恢复失败)
        self.assertFalse(上下文._夜世界首兵槽未选中)

    def test_保护剩余秒数有上下限(self):
        时钟 = _假时钟()
        任务 = 等待进入战斗.__new__(等待进入战斗)
        任务.上下文 = SimpleNamespace(_最近结算视觉时间=0.0)
        with patch("time.monotonic", 时钟.monotonic):
            self.assertAlmostEqual(任务._结算视觉保护剩余秒(), 0.6)
            任务.上下文._最近结算视觉时间 = 时钟.现在 - 0.5
            self.assertAlmostEqual(任务._结算视觉保护剩余秒(), 2.2)
            任务.上下文._最近结算视觉时间 = 时钟.现在 + 10
            self.assertAlmostEqual(任务._结算视觉保护剩余秒(), 3.0)


class 夜世界任务链收尾测试(unittest.TestCase):
    def _运行任务链(self, 上下文, 结果表, 回营结果=True):
        子任务 = {}

        def 工厂(名称):
            def 构造(_上下文):
                假 = Mock()
                假.执行.side_effect = 结果表[名称]
                子任务[名称] = 假
                return 假
            return 构造

        class 假等待进入战斗(等待进入战斗):
            def __init__(self, _上下文):
                self.上下文 = _上下文

            def 执行(self):
                return 结果表["等待进入战斗"]()

        假等待进入战斗.__name__ = "等待进入战斗"

        回营 = Mock()
        回营.执行.return_value = 回营结果
        任务 = 夜世界打鱼任务.__new__(夜世界打鱼任务)
        任务.上下文 = 上下文
        截图 = Mock(return_value=None)
        with patch("任务流程.夜世界.夜世界打鱼.打开进攻页面", 工厂("打开进攻页面")), \
             patch("任务流程.夜世界.夜世界打鱼.等待进入战斗", 假等待进入战斗), \
             patch("任务流程.夜世界.夜世界打鱼.下兵", 工厂("下兵")), \
             patch("任务流程.夜世界.夜世界打鱼.等待回营或第二次战斗", Mock(return_value=回营)), \
             patch("任务流程.夜世界.夜世界打鱼.保存夜世界现场截图", 截图), \
             patch("任务流程.夜世界.夜世界打鱼.停止并等待英雄技能线程", return_value=True):
            结果 = 任务.执行()
        return 结果, 子任务, 回营, 截图

    @staticmethod
    def _上下文():
        return SimpleNamespace(置脚本状态=Mock(), 页面恢复失败=False, _战斗中=False)

    def test_兵槽一直未选中时走回营流程结束本场并继续(self):
        上下文 = self._上下文()

        def 等待失败():
            上下文._夜世界首兵槽未选中 = True
            上下文._战斗中 = True
            return False

        结果, 子任务, 回营, 截图 = self._运行任务链(上下文, {
            "打开进攻页面": [True],
            "等待进入战斗": 等待失败,
            "下兵": [True],
            "等待回营或第二次战斗": [True],
        })

        self.assertTrue(结果)
        self.assertFalse(上下文.页面恢复失败)
        子任务["下兵"].执行.assert_not_called()
        # 回营实例：链里构造一次（未执行到），收尾时再构造并执行一次。
        self.assertEqual(回营.执行.call_count, 1)
        截图.assert_called_once_with(上下文, "等待进入战斗")
        self.assertFalse(上下文._夜世界首兵槽未选中)
        self.assertTrue(any("安全回营，继续下一场" in 行 for 行 in _日志(上下文)))

    def test_未下兵本场回营失败时保留画面并停止(self):
        上下文 = self._上下文()

        def 等待失败():
            上下文._夜世界首兵槽未选中 = True
            return False

        结果, _子任务, 回营, 截图 = self._运行任务链(上下文, {
            "打开进攻页面": [True],
            "等待进入战斗": 等待失败,
            "下兵": [True],
            "等待回营或第二次战斗": [True],
        }, 回营结果=False)

        self.assertFalse(结果)
        self.assertTrue(上下文.页面恢复失败)
        self.assertEqual(回营.执行.call_count, 1)
        self.assertEqual(
            [调用.args[1] for 调用 in 截图.call_args_list],
            ["等待进入战斗", "未下兵回营"],
        )

    def test_其它步骤失败只保存现场不走回营收尾(self):
        上下文 = self._上下文()
        结果, _子任务, 回营, 截图 = self._运行任务链(上下文, {
            "打开进攻页面": [False],
            "等待进入战斗": lambda: True,
            "下兵": [True],
            "等待回营或第二次战斗": [True],
        })

        self.assertFalse(结果)
        回营.执行.assert_not_called()
        截图.assert_called_once_with(上下文, "Mock")


class 夜世界现场截图测试(unittest.TestCase):
    def test_保存night前缀截图且遵守上限不删除旧图(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文 = SimpleNamespace(置脚本状态=Mock(), op=None)
        with tempfile.TemporaryDirectory() as 目录:
            路径 = 保存夜世界现场截图(上下文, "等待进入战斗", 图像, 截图目录=目录)
            self.assertIsNotNone(路径)
            self.assertTrue(路径.name.startswith("night_等待进入战斗_"))
            self.assertTrue(路径.exists())
            第二张 = 保存夜世界现场截图(
                上下文, "下兵", 图像, 截图目录=目录, 最大留图数=1
            )
            self.assertIsNone(第二张)
            self.assertEqual(len(list(Path(目录).glob("night_*.png"))), 1)

    def test_无画面时不保存也不抛异常(self):
        上下文 = SimpleNamespace(置脚本状态=Mock(), op=None, _点击识别截图=None)
        with tempfile.TemporaryDirectory() as 目录:
            self.assertIsNone(保存夜世界现场截图(上下文, "下兵", 截图目录=目录))
            self.assertEqual(list(Path(目录).iterdir()), [])

    def test_从上下文取新帧保存(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        取图 = Mock(return_value=图像)
        上下文 = SimpleNamespace(
            置脚本状态=Mock(), op=SimpleNamespace(获取屏幕图像cv=取图)
        )
        with tempfile.TemporaryDirectory() as 目录:
            上下文._夜世界现场截图目录 = 目录
            路径 = 保存夜世界现场截图(上下文, "打开:进攻/页面")
            self.assertIsNotNone(路径)
            self.assertNotIn(":", 路径.name)
            取图.assert_called_once_with(0, 0, 800, 600, 强制刷新=True)


if __name__ == "__main__":
    unittest.main()
