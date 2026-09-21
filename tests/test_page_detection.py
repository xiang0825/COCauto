import pathlib
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from 模块.检测.页面识别器 import 页面识别器
from 模块.检测.模板匹配器 import 模板匹配引擎
from 任务流程.基础任务框架 import 任务上下文
from 任务流程.检测游戏登录状态 import 检测游戏登录状态任务


class 页面识别测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.根目录 = pathlib.Path(__file__).resolve().parents[1]
        cls.引擎 = 模板匹配引擎(图片库路径=cls.根目录 / "img")
        cls.识别器 = 页面识别器(cls.引擎)

    def _读取截图(self, 名称):
        数据 = np.fromfile(self.根目录 / ".tmp" / 名称, dtype=np.uint8)
        return cv2.imdecode(数据, cv2.IMREAD_COLOR)

    def test_实机战斗截图识别为战斗中(self):
        图像 = self._读取截图("runtime_world_after_fix.png")
        if 图像 is None:
            self.skipTest("没有维护观察截图")
        结果 = self.识别器.识别(图像)
        self.assertEqual(结果.页面, "战斗中")

    def test_红色放弃按钮兜底识别战斗页(self):
        """模板文字变化时仍能用左下角红色按钮识别战斗页。"""
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (10, 430), (105, 470), (0, 0, 220), -1)
        结果 = self.识别器.识别(图像, 战斗中=True)
        self.assertEqual(结果.页面, "战斗中")
        self.assertTrue(any("红色放弃按钮" in 依据 for 依据 in 结果.依据))

    def test_奖励选择横幅优先于左下角战斗按钮(self):
        """奖励覆盖层仍带放弃按钮时，不能继续被识别为战斗页。"""
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (214, 70), (588, 121), (0, 0, 220), -1)
        cv2.rectangle(图像, (10, 430), (105, 470), (0, 0, 220), -1)
        结果 = self.识别器.识别(图像, 战斗中=True)
        self.assertEqual(结果.页面, "战斗奖励选择")
        self.assertTrue(any("奖励选择红色横幅" in 依据 for 依据 in 结果.依据))

    def test_源码运行不依赖当前工作目录寻找图片库(self):
        """从其他 cwd 启动后，模板库仍应定位到源码根目录。"""
        预期根目录 = self.根目录
        旧MEIPASS = getattr(sys, "_MEIPASS", None)
        是否有MEIPASS = hasattr(sys, "_MEIPASS")
        if 是否有MEIPASS:
            delattr(sys, "_MEIPASS")
        try:
            with patch("模块.检测.模板匹配器.Path.cwd", return_value=pathlib.Path("C:/not-the-project")):
                self.assertEqual(self.引擎.获取资源目录(), 预期根目录)
        finally:
            if 是否有MEIPASS:
                sys._MEIPASS = 旧MEIPASS

    def test_实机主世界截图识别为主世界主页(self):
        图像 = self._读取截图("runtime_observation_after10s.png")
        if 图像 is None:
            self.skipTest("没有维护观察截图")
        结果 = self.识别器.识别(图像)
        self.assertEqual(结果.页面, "主世界主页")

    def test_实机结算截图识别为战斗结算(self):
        图像 = self._读取截图("runtime_after_battle_wait.png")
        if 图像 is None:
            self.skipTest("没有维护观察截图")
        结果 = self.识别器.识别(图像)
        self.assertEqual(结果.页面, "战斗结算")

    def test_点击识别截图在短窗口内复用(self):
        上下文 = 任务上下文.__new__(任务上下文)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文.op = SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕))
        上下文._点击识别截图时间 = 0.0
        上下文._点击识别截图 = None
        # 首次强制获取后，第二次普通获取必须命中缓存。
        第一张 = 上下文._获取点击识别截图(强制=True)
        第二张 = 上下文._获取点击识别截图(强制=False)
        self.assertIs(第一张, 第二张)
        上下文.op.获取屏幕图像cv.assert_called_once_with(0, 0, 800, 600, 强制刷新=True)

    def test_战斗护栏强制复核不绕过ADB截图节流(self):
        """战斗输入不能因“强制检查”在每次下兵都重新抓全屏。"""
        上下文 = 任务上下文.__new__(任务上下文)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文.op = SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕))
        上下文._战斗中 = True
        上下文._点击识别截图时间 = 0.0
        上下文._点击识别截图 = None

        上下文._获取点击识别截图(强制=True)

        上下文.op.获取屏幕图像cv.assert_called_once_with(0, 0, 800, 600, 强制刷新=False)

    def test_战斗结算页阻止原始鼠标输入且不发送ESC(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.检查宝石商店危险页面 = Mock(return_value=False)
        上下文._最近点击页面结果 = SimpleNamespace(页面="战斗结算")
        上下文._战斗中 = True
        上下文.置脚本状态 = Mock()
        self.assertTrue(上下文.输入前安全检查())
        self.assertTrue(上下文._战斗结束已确认)
        self.assertTrue(any("阻止继续下兵" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_战斗护栏截图失败时阻止输入(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = True
        上下文.置脚本状态 = Mock()
        上下文.识别点击画面 = Mock(return_value=None)

        self.assertTrue(上下文.检查宝石商店危险页面())
        上下文.识别点击画面.assert_called_once()
        self.assertTrue(any("阻止后续下兵" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_战斗过渡页面阻止输入(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = True
        上下文.置脚本状态 = Mock()
        上下文.识别点击画面 = Mock(
            return_value=SimpleNamespace(页面="战斗过渡")
        )

        self.assertTrue(上下文.检查宝石商店危险页面())
        self.assertTrue(any("尚未确认战斗画面" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_奖励选择弹窗阻止输入并停止任务(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = True
        上下文.停止事件 = Mock()
        上下文.置脚本状态 = Mock()
        上下文.识别点击画面 = Mock(
            return_value=SimpleNamespace(页面="战斗奖励选择")
        )

        self.assertTrue(上下文.检查宝石商店危险页面())
        上下文.停止事件.set.assert_called_once()
        self.assertTrue(上下文._战斗奖励弹窗已确认)
        self.assertTrue(上下文.页面恢复失败)
        self.assertTrue(any("奖励选择弹窗" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_内存错误释放资源并停止任务(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.停止事件 = Mock()
        上下文.置脚本状态 = Mock()
        上下文.释放识别模型 = Mock()

        上下文.触发内存保护("测试OCR", RuntimeError("bad allocation"))

        self.assertTrue(上下文._内存保护已触发)
        self.assertTrue(上下文.页面恢复失败)
        上下文.释放识别模型.assert_called_once()
        上下文.停止事件.set.assert_called_once()
        self.assertTrue(any("不关闭CoC" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_内存保护异常不触发截图通知或自动恢复(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.停止事件 = Mock()
        上下文.置脚本状态 = Mock()
        上下文.释放识别模型 = Mock()
        上下文.发送企业微信通知 = Mock()
        上下文.是否内存异常 = 任务上下文.是否内存异常
        上下文.处理异常("检查图像任务", RuntimeError("主机内存保护已触发"))

        上下文.发送企业微信通知.assert_called_once()
        self.assertFalse(上下文.发送企业微信通知.call_args.kwargs["包含截图"])
        self.assertTrue(any("不是普通ADB断线" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_断线弹窗连续失败三次后安全停止而不无限点击(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕)),
            数据库=Mock(),
            机器人标志="robot_test",
            停止事件=threading.Event(),
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
            点击已确认安全按钮=Mock(return_value=True),
        )
        任务 = 检测游戏登录状态任务(上下文)
        with patch("任务流程.检测游戏登录状态.模板匹配引擎") as 引擎类, \
                patch.object(任务, "_检测断线弹窗", return_value=(True, (256, 365))):
            引擎类.return_value.执行匹配.return_value = (False, (0, 0), 0.0)
            self.assertFalse(任务.执行(首次登录=False))
        self.assertEqual(上下文.点击已确认安全按钮.call_count, 3)
        self.assertTrue(上下文.页面恢复失败)
        self.assertTrue(上下文.停止事件.is_set())
        self.assertTrue(any("恢复3次仍未消失" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_普通点击前后都会记录页面识别(self):
        屏幕 = self._读取截图("runtime_observation_after10s.png")
        if 屏幕 is None:
            self.skipTest("没有维护观察截图")
        日志 = []
        鼠标 = SimpleNamespace(移动到=Mock(), 左键点击=Mock(return_value=True))
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.op = SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕))
        上下文.鼠标 = 鼠标
        上下文.脚本延时 = Mock()
        上下文.置脚本状态 = 日志.append
        self.assertTrue(上下文.点击(400, 300, 延时=1, 是否精确点击=True))
        self.assertGreaterEqual(上下文.op.获取屏幕图像cv.call_count, 2)
        self.assertTrue(any("页面=主世界主页" in 文本 for 文本 in 日志))


if __name__ == "__main__":
    unittest.main()
