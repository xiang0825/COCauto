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

    def test_顶号等待按毫秒单位为200秒(self):
        self.assertEqual(检测游戏登录状态任务.顶号等待毫秒, 200_000)

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

    def test_1280x720战斗倒计时优先于奖励页误报(self):
        """高分辨率实机中倒计时存在时，不能停在奖励选择页。"""
        图像 = np.zeros((720, 1280, 3), dtype=np.uint8)
        # 模拟当前 MuMu 实机布局：左下角放弃按钮和顶部倒计时。
        cv2.rectangle(图像, (18, 512), (165, 563), (0, 0, 220), -1)
        cv2.putText(
            图像, "1:07", (545, 78), cv2.FONT_HERSHEY_SIMPLEX,
            1.7, (255, 255, 255), 4, cv2.LINE_AA,
        )
        结果 = self.识别器.识别(图像, 战斗中=True)
        self.assertEqual(结果.页面, "战斗中")
        self.assertTrue(any("战斗倒计时" in 依据 for 依据 in 结果.依据))

    def test_升级详情弹窗只返回右上角安全关闭点(self):
        """遮罩上的绿色宝石按钮和最右侧控件都不能成为点击目标。"""
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (70, 20), (730, 580), (70, 80, 90), -1)
        cv2.rectangle(图像, (90, 30), (650, 80), (100, 100, 105), -1)
        cv2.rectangle(图像, (690, 20), (730, 70), (0, 0, 220), -1)
        # 模拟升级弹窗右侧背景中另一个红色控件，位置应被排除。
        cv2.rectangle(图像, (750, 65), (790, 105), (0, 0, 220), -1)

        关闭点 = 任务上下文._检测升级详情弹窗关闭点(图像)

        self.assertIsNotNone(关闭点)
        self.assertAlmostEqual(关闭点[0], 710, delta=2)
        self.assertAlmostEqual(关闭点[1], 45, delta=2)

    def test_普通主世界没有升级详情关闭点(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        图像[:, :] = (35, 90, 45)
        cv2.rectangle(图像, (752, 68), (790, 108), (0, 0, 220), -1)

        self.assertIsNone(任务上下文._检测升级详情弹窗关闭点(图像))

    def test_主世界活动弹窗红色X返回安全关闭点(self):
        图像 = np.full((600, 800, 3), (55, 115, 60), dtype=np.uint8)
        cv2.rectangle(图像, (80, 20), (720, 570), (80, 80, 80), -1)
        cv2.rectangle(图像, (680, 20), (735, 80), (20, 20, 220), -1)
        cv2.line(图像, (695, 35), (720, 65), (245, 245, 245), 7)
        cv2.line(图像, (720, 35), (695, 65), (245, 245, 245), 7)

        关闭点 = 任务上下文._检测主世界活动弹窗关闭点(图像)

        self.assertIsNotNone(关闭点)
        self.assertAlmostEqual(关闭点[0], 707, delta=8)
        self.assertAlmostEqual(关闭点[1], 50, delta=8)

    def test_主世界右上普通红色控件不会被当活动弹窗(self):
        图像 = np.full((600, 800, 3), (55, 115, 60), dtype=np.uint8)
        cv2.rectangle(图像, (700, 20), (735, 55), (20, 20, 220), -1)

        self.assertIsNone(任务上下文._检测主世界活动弹窗关闭点(图像))

    def test_中央教程提示只返回下半屏正文点击点(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.获取OCR引擎 = Mock(return_value=Mock(return_value=(
            [
                ([[200, 220], [500, 220], [500, 260], [200, 260]],
                 "冠军，记得领取你可能错过的奖励。", 0.95),
            ],
            None,
        )))
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)

        候选 = 上下文._识别中央游戏提示(图像)

        self.assertIsNotNone(候选)
        self.assertEqual(候选["点击点"], (446, 384))

    def test_顶部资源栏文字不能触发中央教程提示(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.获取OCR引擎 = Mock(return_value=Mock(return_value=(
            [
                ([[650, 10], [790, 10], [790, 35], [650, 35]],
                 "领取奖励", 0.99),
            ],
            None,
        )))
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)

        self.assertIsNone(上下文._识别中央游戏提示(图像))

    def test_奖励选择横幅优先于左下角战斗按钮(self):
        """奖励覆盖层仍带放弃按钮时，不能继续被识别为战斗页。"""
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (214, 70), (588, 121), (0, 0, 220), -1)
        cv2.rectangle(图像, (10, 430), (105, 470), (0, 0, 220), -1)
        for 左, 上, 右, 下 in (
            (175, 185, 305, 445),
            (340, 190, 470, 450),
            (500, 135, 625, 420),
        ):
            cv2.rectangle(图像, (左, 上), (右, 下), (220, 220, 220), 8)
        结果 = self.识别器.识别(图像, 战斗中=True)
        self.assertEqual(结果.页面, "战斗奖励选择")
        self.assertTrue(any("奖励选择红色横幅" in 依据 for 依据 in 结果.依据))

    def test_战斗倒计时存在时不误判奖励选择(self):
        """战场顶部倒计时比地图上的伪卡片结构更强，必须保留战斗页。"""
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (214, 70), (588, 121), (0, 0, 220), -1)
        cv2.rectangle(图像, (10, 430), (105, 470), (0, 0, 220), -1)
        for 左, 上, 右, 下 in (
            (175, 185, 305, 445),
            (340, 190, 470, 450),
            (500, 135, 625, 420),
        ):
            cv2.rectangle(图像, (左, 上), (右, 下), (220, 220, 220), 8)
        cv2.putText(
            图像, "45", (380, 80), cv2.FONT_HERSHEY_SIMPLEX,
            1.4, (255, 255, 255), 3, cv2.LINE_AA,
        )
        结果 = self.识别器.识别(图像, 战斗中=True)
        self.assertEqual(结果.页面, "战斗中")
        self.assertTrue(any("战斗倒计时" in 依据 for 依据 in 结果.依据))

    def test_红色最后倒计时存在时不误判奖励选择(self):
        """最后几秒倒计时变红时，仍不能把战场结构误判为奖励页。"""
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (214, 70), (588, 121), (0, 0, 220), -1)
        cv2.rectangle(图像, (10, 430), (105, 470), (0, 0, 220), -1)
        for 左, 上, 右, 下 in (
            (175, 185, 305, 445),
            (340, 190, 470, 450),
            (500, 135, 625, 420),
        ):
            cv2.rectangle(图像, (左, 上), (右, 下), (220, 220, 220), 8)
        cv2.putText(
            图像, "TIME", (300, 40), cv2.FONT_HERSHEY_SIMPLEX,
            0.8, (0, 0, 220), 3, cv2.LINE_AA,
        )
        cv2.putText(
            图像, "6", (390, 92), cv2.FONT_HERSHEY_SIMPLEX,
            1.8, (0, 0, 220), 4, cv2.LINE_AA,
        )
        结果 = self.识别器.识别(图像, 战斗中=True)
        self.assertEqual(结果.页面, "战斗中")
        self.assertTrue(any("战斗倒计时" in 依据 for 依据 in 结果.依据))

    def test_结果横幅和底部回营按钮优先识别结算页(self):
        """回营模板失配时，真实结算画面的视觉结构仍优先于奖励页。"""
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (175, 130), (625, 255), (30, 185, 235), -1)
        cv2.rectangle(图像, (315, 485), (485, 565), (90, 220, 120), -1)
        识别器 = 页面识别器(Mock())
        识别器._最佳分数 = Mock(return_value=0.0)
        结果 = 识别器.识别(图像, 战斗中=True)
        self.assertEqual(结果.页面, "战斗结算")
        self.assertTrue(any("结果横幅+回营视觉" in 依据 for 依据 in 结果.依据))

    def test_实机断线弹窗识别为断线页面(self):
        """中央连接中断遮罩不能被当成未知页面继续发送输入。"""
        图像 = np.full((600, 800, 3), (10, 18, 22), dtype=np.uint8)
        cv2.rectangle(图像, (164, 180), (635, 423), (32, 26, 29), -1)
        cv2.rectangle(图像, (201, 218), (304, 244), (220, 220, 220), -1)
        cv2.rectangle(图像, (201, 270), (580, 294), (220, 220, 220), -1)
        cv2.rectangle(图像, (201, 306), (232, 328), (220, 220, 220), -1)
        cv2.rectangle(图像, (201, 368), (325, 389), (220, 220, 220), -1)
        结果 = self.识别器.识别(图像)
        self.assertEqual(结果.页面, "断线弹窗")
        self.assertTrue(any("中央断线弹窗" in 依据 for 依据 in 结果.依据))

    def test_系统维护页优先于断线弹窗识别(self):
        """维护页的黄黑警示带优先于中央深色面板，避免重复点击重试。"""
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        图像[:18, :] = (20, 210, 245)
        cv2.rectangle(图像, (195, 190), (635, 430), (32, 26, 29), -1)

        结果 = self.识别器.识别(图像)

        self.assertEqual(结果.页面, "系统维护")
        self.assertTrue(any("黄黑维护警示带" in 依据 for 依据 in 结果.依据))

    def test_维护页登录任务安全停止不点击(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[:18, :] = (20, 210, 245)
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

        self.assertFalse(任务.执行(首次登录=False))
        上下文.点击已确认安全按钮.assert_not_called()
        self.assertTrue(上下文.页面恢复失败)
        self.assertTrue(上下文.停止事件.is_set())
        self.assertTrue(any("系统维护页面" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_维护页点击护栏阻断普通输入(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文._获取点击识别截图 = Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))
        上下文.识别点击画面 = Mock(
            return_value=SimpleNamespace(页面="系统维护")
        )
        上下文.停止事件 = Mock()
        上下文.置脚本状态 = Mock()
        上下文.页面恢复失败 = False

        self.assertTrue(上下文.检查宝石商店危险页面())
        self.assertTrue(上下文.页面恢复失败)
        上下文.停止事件.set.assert_called_once()
        self.assertFalse(上下文.点击(400, 300))

    def test_右锚定断线弹窗识别为断线页面(self):
        """右侧横向布局的重新登入面板也必须被识别并拦截输入。"""
        画面 = np.full((600, 800, 3), (70, 100, 55), dtype=np.uint8)
        # 复现实机截图的右锚定面板：x=309、y=235、491x247。
        画面[235:482, 309:800] = (36, 39, 45)
        # 三段亮色文字的几何占位，模拟标题、正文和左侧重新登入按钮。
        画面[270:300, 345:590] = (235, 235, 235)
        画面[330:360, 345:700] = (225, 225, 225)
        画面[425:455, 345:560] = (240, 240, 240)
        结果 = self.识别器.识别(画面)
        self.assertEqual(结果.页面, "断线弹窗")
        self.assertGreaterEqual(结果.可信度, 0.90)

    def test_实机右锚定断线截图识别(self):
        """若维护实测截图存在，直接回放当前实机画面，防止规则回退。"""
        from pathlib import Path

        路径 = Path(__file__).resolve().parents[2] / ".tmp" / "continuation_current.png"
        if not 路径.exists():
            self.skipTest("当前实机截图未提供")
        画面 = cv2.imread(str(路径))
        self.assertIsNotNone(画面)
        结果 = self.识别器.识别(画面)
        self.assertEqual(结果.页面, "断线弹窗")

    def test_结算按钮优先于结算动画奖励横幅(self):
        识别器 = 页面识别器(Mock())
        识别器._最佳分数 = Mock(side_effect=lambda _图像, 模板: 0.85 if "回营" in 模板 else 0.0)
        识别器._红色放弃按钮分数 = Mock(return_value=0.0)
        识别器._奖励选择横幅分数 = Mock(return_value=0.96)
        识别器._奖励卡片结构数量 = Mock(return_value=3)
        结果 = 识别器.识别(np.zeros((600, 800, 3), dtype=np.uint8), 战斗中=True)
        self.assertEqual(结果.页面, "战斗结算")

    def test_战斗倒计时优先于误报结算按钮(self):
        """仍有倒计时时，即使结算模板误命中也必须继续下兵。"""
        识别器 = 页面识别器(Mock())
        识别器._最佳分数 = Mock(return_value=0.85)
        识别器._红色放弃按钮分数 = Mock(return_value=0.0)
        识别器._战斗倒计时分数 = Mock(return_value=0.96)
        结果 = 识别器.识别(np.zeros((600, 800, 3), dtype=np.uint8), 战斗中=True)
        self.assertEqual(结果.页面, "战斗中")
        self.assertTrue(any("战斗倒计时" in 依据 for 依据 in 结果.依据))

    def test_奖励过渡复核结算页不会停止任务(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = True
        上下文.停止事件 = Mock()
        上下文.置脚本状态 = Mock()
        上下文.脚本延时 = Mock()
        上下文.识别点击画面 = Mock(
            side_effect=[
                SimpleNamespace(页面="战斗奖励选择"),
                SimpleNamespace(页面="战斗结算"),
            ]
        )
        self.assertTrue(上下文.检查宝石商店危险页面())
        上下文.停止事件.set.assert_not_called()
        self.assertTrue(上下文._战斗结束已确认)
        self.assertIn((800,), [调用.args for 调用 in 上下文.脚本延时.call_args_list])

    def test_奖励过渡连续慢帧后仍能复核到结算页(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = True
        上下文.停止事件 = Mock()
        上下文.置脚本状态 = Mock()
        上下文.脚本延时 = Mock()
        上下文.识别点击画面 = Mock(side_effect=[
            SimpleNamespace(页面="战斗奖励选择"),
            SimpleNamespace(页面="战斗奖励选择"),
            SimpleNamespace(页面="战斗结算"),
        ])

        self.assertTrue(上下文.检查宝石商店危险页面())
        上下文.停止事件.set.assert_not_called()
        self.assertTrue(上下文._战斗结束已确认)
        self.assertEqual(上下文.识别点击画面.call_count, 3)
        self.assertIn((500,), [调用.args for 调用 in 上下文.脚本延时.call_args_list])

    def test_单独红色横幅不会误报奖励页(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (214, 70), (588, 121), (0, 0, 220), -1)
        结果 = self.识别器.识别(图像, 战斗中=True)
        self.assertNotEqual(结果.页面, "战斗奖励选择")

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

    def test_当前实机缩放主世界不会误报战斗结算(self):
        """主世界草地大面积变绿时，不能被视觉结算兜底误判。"""
        from pathlib import Path

        路径 = Path(__file__).resolve().parents[2] / ".tmp" / "current_logical_full.png"
        if not 路径.exists():
            self.skipTest("当前维护截图未提供")
        图像 = cv2.imread(str(路径))
        self.assertIsNotNone(图像)
        结果 = self.识别器.识别(图像)
        self.assertEqual(结果.页面, "主世界主页")
        self.assertEqual(结果.世界, "主世界")

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

    def test_奖励选择过渡阻止输入但不提前停止任务(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = True
        上下文.停止事件 = Mock()
        上下文.置脚本状态 = Mock()
        上下文.识别点击画面 = Mock(
            return_value=SimpleNamespace(页面="战斗奖励选择")
        )

        self.assertTrue(上下文.检查宝石商店危险页面())
        上下文.停止事件.set.assert_not_called()
        self.assertTrue(上下文._战斗奖励弹窗已确认)
        self.assertFalse(getattr(上下文, "页面恢复失败", False))
        self.assertTrue(any("等待结算页" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_实机战败结算截图不会识别为奖励选择(self):
        from pathlib import Path

        路径 = Path(__file__).resolve().parents[2] / ".tmp" / "battle_v1_latest.png"
        if not 路径.exists():
            self.skipTest("没有维护实机战败结算截图")
        图像 = cv2.imdecode(np.fromfile(路径, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(图像)
        结果 = self.识别器.识别(图像)
        self.assertEqual(结果.页面, "战斗结算")

    def test_启动时结算页先回营不误判主页(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.数据库 = Mock()
        上下文.机器人标志 = "robot_test"
        上下文.置脚本状态 = Mock()
        上下文.点击已确认安全按钮 = Mock(return_value=True)
        上下文.脚本延时 = Mock()
        任务 = 检测游戏登录状态任务(上下文)
        页面结果 = SimpleNamespace(页面="战斗结算", 可信度=0.85)
        页面识别 = Mock()
        页面识别.识别.return_value = 页面结果
        识图引擎 = Mock()
        识图引擎.执行匹配.return_value = (True, (640, 620), 0.85)

        self.assertTrue(任务._启动阶段处理结算页(np.zeros((600, 800, 3), dtype=np.uint8), 识图引擎, 页面识别))
        上下文.点击已确认安全按钮.assert_called_once_with(640, 620, 延时=180)
        self.assertTrue(any("先点击回营" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

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
