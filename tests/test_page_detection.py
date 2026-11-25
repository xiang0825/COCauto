import pathlib
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from 模块.检测.页面识别器 import 页面识别器, 页面识别结果
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
        路径 = self.根目录 / ".tmp" / 名称
        if not 路径.exists():
            return None
        数据 = np.fromfile(路径, dtype=np.uint8)
        return cv2.imdecode(数据, cv2.IMREAD_COLOR)

    def test_哥布林宝石提示覆盖主页时优先拦截(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (365, 100), (740, 412), (220, 220, 220), -1)
        cv2.rectangle(图像, (700, 108), (730, 150), (20, 20, 210), -1)
        cv2.rectangle(图像, (490, 326), (613, 398), (60, 210, 80), -1)
        识别器 = 页面识别器(Mock())
        self.assertEqual(识别器.定位哥布林宝石提示关闭按钮(图像), (716, 128))
        self.assertEqual(识别器.识别(图像).页面, "哥布林宝石提示")
        图像[325:400, 490:614] = (220, 220, 220)
        self.assertIsNone(识别器.定位哥布林宝石提示关闭按钮(图像))

    def test_顶号等待按毫秒单位为200秒(self):
        self.assertEqual(检测游戏登录状态任务.顶号等待毫秒, 200_000)

    def test_登录图标命中但结算页未确认主页(self):
        """回营后的底层主页图标不能提前结束登录检测。"""
        上下文 = SimpleNamespace(置脚本状态=Mock())
        任务 = 检测游戏登录状态任务.__new__(检测游戏登录状态任务)
        任务.上下文 = 上下文
        页面识别 = Mock()
        页面识别.识别.return_value = SimpleNamespace(
            页面="战斗结算", 世界=None, 可信度=0.94
        )

        self.assertFalse(
            任务._登录主页已确认(np.zeros((600, 800, 3), dtype=np.uint8), 页面识别)
        )
        self.assertTrue(any("未确认游戏主页" in 调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list))

    def test_登录图标命中且页级确认主世界才算登录(self):
        上下文 = SimpleNamespace(置脚本状态=Mock())
        任务 = 检测游戏登录状态任务.__new__(检测游戏登录状态任务)
        任务.上下文 = 上下文
        页面识别 = Mock()
        页面识别.识别.return_value = SimpleNamespace(
            页面="主世界主页", 世界="主世界", 可信度=0.78
        )

        self.assertTrue(
            任务._登录主页已确认(np.zeros((600, 800, 3), dtype=np.uint8), 页面识别)
        )
        上下文.置脚本状态.assert_not_called()

    def test_登录页级识别接受已登录的主世界多人战斗选择页(self):
        上下文 = SimpleNamespace(置脚本状态=Mock())
        任务 = 检测游戏登录状态任务.__new__(检测游戏登录状态任务)
        任务.上下文 = 上下文
        页面识别 = Mock()
        页面识别.识别.return_value = SimpleNamespace(
            页面="主世界战斗模式选择", 世界="主世界", 可信度=0.96
        )

        self.assertTrue(
            任务._登录主页已确认(np.zeros((600, 800, 3), dtype=np.uint8), 页面识别)
        )
        上下文.置脚本状态.assert_not_called()

    def test_启动登录两帧确认模式选择页后不做主页缩放(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=画面),
                设备=SimpleNamespace(
                    获取当前前台包名=Mock(return_value="com.supercell.clashofclans")
                ),
            ),
            设置=SimpleNamespace(部落冲突包名="com.supercell.clashofclans"),
            停止事件=threading.Event(),
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
            游戏内拉远视距=Mock(),
        )
        任务 = 检测游戏登录状态任务.__new__(检测游戏登录状态任务)
        任务.上下文 = 上下文
        任务.第一次检测游戏登录 = True
        模式页 = SimpleNamespace(
            页面="主世界战斗模式选择", 世界="主世界", 可信度=0.96
        )

        with patch("任务流程.检测游戏登录状态.模板匹配引擎"), \
                patch("任务流程.检测游戏登录状态.页面识别器") as 页面工厂, \
                patch.object(任务, "_启动阶段处理英雄升级详情", return_value=False), \
                patch.object(任务, "_启动阶段处理研究目标页", return_value=False), \
                patch.object(任务, "_启动阶段处理主世界活动弹窗", return_value=False), \
                patch.object(
                    检测游戏登录状态任务,
                    "_检测断线弹窗",
                    return_value=(False, (0, 0)),
                ):
            页面工厂.return_value.识别.return_value = 模式页
            self.assertTrue(任务.执行())

        self.assertTrue(上下文._主世界战斗模式选择页)
        上下文.游戏内拉远视距.assert_not_called()
        self.assertFalse(上下文.停止事件.is_set())

    def test_多人战斗模式页必须同时看到普通与排位按钮(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(画面, (46, 409), (227, 482), (44, 173, 249), -1)
        cv2.rectangle(画面, (345, 409), (526, 482), (255, 126, 35), -1)

        结果 = self.识别器.识别(画面)

        self.assertEqual(结果.页面, "主世界战斗模式选择")
        self.assertEqual(结果.世界, "主世界")
        self.assertGreaterEqual(结果.可信度, 0.90)
        self.assertEqual(
            页面识别器.定位主世界战斗模式普通按钮(画面), (137, 446)
        )

    def test_只有橙色按钮不能确认多人战斗模式页(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(画面, (46, 409), (227, 482), (44, 173, 249), -1)

        self.assertIsNone(页面识别器.定位主世界战斗模式普通按钮(画面))
        self.assertNotEqual(self.识别器.识别(画面).页面, "主世界战斗模式选择")

    def test_每次登录重连都重新确认CoC前台(self):
        """重连任务不能复用上一次执行的前台确认结果。"""
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        前台查询 = Mock(return_value="com.supercell.clashofclans")
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=屏幕),
                设备=SimpleNamespace(获取当前前台包名=前台查询),
            ),
            设置=SimpleNamespace(部落冲突包名="com.supercell.clashofclans"),
            数据库=Mock(),
            机器人标志="robot_test",
            停止事件=threading.Event(),
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
            点击已确认安全按钮=Mock(return_value=False),
        )
        任务 = 检测游戏登录状态任务(上下文)
        # 模拟上一轮执行留下的状态；本轮必须清零后再次查询。
        任务._前台状态已记录 = True

        class 假引擎:
            def 执行匹配(self, _图像, 模板路径, **_参数):
                if "登录弹窗的确定" in 模板路径:
                    return True, (320, 400), 0.95
                return False, (0, 0), 0.0

        with patch("任务流程.检测游戏登录状态.模板匹配引擎", return_value=假引擎()), \
             patch("任务流程.检测游戏登录状态.页面识别器") as 页面识别器:
            页面识别器.return_value.识别.return_value = SimpleNamespace(页面="未知")
            任务._检测断线弹窗 = Mock(return_value=(False, (0, 0)))
            self.assertFalse(任务.执行(首次登录=False))

        前台查询.assert_called_once_with()

    def test_启动时军队配置页先安全关闭再继续主页识别(self):
        """已打开军队页不能等待登录超时，也不能用ESC退出游戏。"""
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 中央配置面板 + 右下绿色攻击按钮，复现进攻入口识别所需的
        # 两个独立证据；不依赖本机当前模拟器截图。
        屏幕[80:530, 96:704] = (180, 180, 180)
        屏幕[490:570, 560:760] = (0, 200, 100)
        上下文 = SimpleNamespace(
            数据库=Mock(),
            机器人标志="robot_test",
            清理主世界活动弹窗=Mock(return_value=True),
            置脚本状态=Mock(),
            脚本延时=Mock(),
            页面恢复失败=False,
            停止事件=threading.Event(),
        )
        任务 = 检测游戏登录状态任务(上下文)

        self.assertTrue(任务._启动阶段处理军队配置页(屏幕))
        self.assertTrue(getattr(上下文, "_启动时已有游戏页面", False))
        上下文.清理主世界活动弹窗.assert_called_once_with(屏幕)
        self.assertFalse(上下文.停止事件.is_set())
        self.assertTrue(any("军队配置页" in 调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list))

    def test_实机军队配置页右上角关闭点可被识别(self):
        屏幕 = self._读取截图("army_config_current2.png")
        if 屏幕 is None:
            self.skipTest("没有维护观察截图")
        关闭点 = 任务上下文._检测主世界活动弹窗关闭点(屏幕)
        self.assertIsNotNone(关闭点)
        self.assertAlmostEqual(关闭点[0], 773, delta=8)
        self.assertAlmostEqual(关闭点[1], 54, delta=8)

    def test_启动时军队配置页优先调用专用关闭器(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[80:530, 96:704] = (180, 180, 180)
        屏幕[490:570, 560:760] = (0, 200, 100)
        上下文 = SimpleNamespace(
            数据库=Mock(),
            机器人标志="robot_test",
            关闭军队配置页=Mock(return_value=True),
            清理主世界活动弹窗=Mock(return_value=False),
            置脚本状态=Mock(),
            脚本延时=Mock(),
            页面恢复失败=False,
            停止事件=threading.Event(),
        )
        任务 = 检测游戏登录状态任务(上下文)

        self.assertTrue(任务._启动阶段处理军队配置页(屏幕))
        上下文.关闭军队配置页.assert_called_once_with(屏幕)
        上下文.清理主世界活动弹窗.assert_not_called()
        self.assertFalse(上下文.停止事件.is_set())

    def test_启动时活动面板在主页匹配前安全关闭(self):
        上下文 = SimpleNamespace(
            数据库=Mock(),
            机器人标志="robot_test",
            清理主世界活动弹窗=Mock(return_value=True),
            置脚本状态=Mock(),
            脚本延时=Mock(),
            页面恢复失败=False,
            停止事件=threading.Event(),
        )
        任务 = 检测游戏登录状态任务(上下文)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        with patch.object(
            任务上下文,
            "_检测主世界活动弹窗关闭点",
            return_value=(710, 38),
        ):
            self.assertTrue(任务._启动阶段处理主世界活动弹窗(屏幕))
        上下文.清理主世界活动弹窗.assert_called_once_with(屏幕)
        self.assertFalse(上下文.页面恢复失败)
        self.assertFalse(上下文.停止事件.is_set())
        self.assertTrue(any("活动/奖励面板" in 调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list))

    def test_启动时战斗阶段明确为开始时要求接管下兵(self):
        上下文 = SimpleNamespace(
            数据库=Mock(),
            机器人标志="robot_test",
            获取模板识别器=Mock(return_value=Mock()),
            获取OCR引擎=Mock(return_value=Mock(return_value=(
            [([[350, 10], [430, 10], [430, 30], [350, 30]], "離戰鬥開始剩下", 0.95)],
            None,
            ))),
        )
        任务 = 检测游戏登录状态任务(上下文)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        with patch(
            "任务流程.检测游戏登录状态.安全OCR引擎",
            side_effect=AssertionError("启动OCR应来自任务上下文"),
            create=True,
        ):
            self.assertIs(任务._识别启动时战斗阶段(屏幕), False)
        上下文.获取OCR引擎.assert_called_once_with()

    def test_启动时战斗阶段明确为结束时只等待回营(self):
        上下文 = SimpleNamespace(
            数据库=Mock(),
            机器人标志="robot_test",
            获取模板识别器=Mock(return_value=Mock()),
            获取OCR引擎=Mock(return_value=Mock(return_value=(
            [([[350, 10], [430, 10], [430, 30], [350, 30]], "離戰鬥結束剩下", 0.95)],
            None,
            ))),
        )
        任务 = 检测游戏登录状态任务(上下文)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        with patch(
            "任务流程.检测游戏登录状态.安全OCR引擎",
            side_effect=AssertionError("启动OCR应来自任务上下文"),
            create=True,
        ):
            self.assertIs(任务._识别启动时战斗阶段(屏幕), True)
        上下文.获取OCR引擎.assert_called_once_with()

    def test_实机战斗截图识别为战斗中(self):
        图像 = self._读取截图("runtime_world_after_fix.png")
        if 图像 is None:
            self.skipTest("没有维护观察截图")
        结果 = self.识别器.识别(图像)
        self.assertEqual(结果.页面, "战斗中")

    def test_战斗HUD与配置页误候选同时存在时优先识别战斗(self):
        """新 UI 的战场绿色区域不能让军队页候选压过战斗 HUD。"""
        图像 = self._读取截图("runtime_world_after_fix.png")
        if 图像 is None:
            self.skipTest("没有维护观察截图")
        with patch.object(
            self.识别器, "定位军队配置页攻击按钮", return_value=(570, 479)
        ):
            结果 = self.识别器.识别(图像, 战斗中=True)
        self.assertEqual(结果.页面, "战斗中", 结果.摘要())

    def test_红色放弃按钮兜底识别战斗页(self):
        """模板文字变化时仍能用左下角红色按钮识别战斗页。"""
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (10, 430), (105, 470), (0, 0, 220), -1)
        结果 = self.识别器.识别(图像, 战斗中=True)
        self.assertEqual(结果.页面, "战斗中")
        self.assertTrue(any("红色放弃按钮" in 依据 for 依据 in 结果.依据))

    def test_主世界左下竖向回营卡片识别为结算页(self):
        """国际服主世界结算页的左下“回营”卡片不能漏检。"""
        图像 = np.full((600, 800, 3), (35, 35, 35), dtype=np.uint8)
        # 主世界结算结果区域：暗色结果遮罩加少量亮色统计文字。
        cv2.rectangle(图像, (360, 165), (475, 195), (235, 235, 235), -1)
        # 实机约为 x=12..93、y=478..584 的浅色竖向回营卡片。
        cv2.rectangle(图像, (12, 478), (93, 584), (180, 180, 180), -1)

        回营点 = self.识别器.定位结算回营按钮(图像)
        self.assertIsNotNone(回营点)
        self.assertAlmostEqual(回营点[0], 52, delta=8)
        self.assertAlmostEqual(回营点[1], 531, delta=10)
        结果 = self.识别器.识别(图像)
        self.assertEqual(结果.页面, "战斗结算")

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

    def test_1280x720右锚定活动弹窗红色X返回安全关闭点(self):
        """MuMu 宽屏右边缘的活动 X 不能因 0.96 边界被漏检。"""
        图像 = np.full((720, 1280, 3), (55, 115, 60), dtype=np.uint8)
        cv2.rectangle(图像, (120, 24), (1130, 635), (80, 80, 80), -1)
        cv2.rectangle(图像, (1200, 29), (1247, 77), (20, 20, 220), -1)
        cv2.line(图像, (1210, 39), (1237, 68), (245, 245, 245), 7)
        cv2.line(图像, (1237, 39), (1210, 68), (245, 245, 245), 7)

        关闭点 = 任务上下文._检测主世界活动弹窗关闭点(图像)

        self.assertIsNotNone(关闭点)
        self.assertAlmostEqual(关闭点[0], 765, delta=10)
        self.assertAlmostEqual(关闭点[1], 44, delta=8)

    def test_主世界右上普通红色控件不会被当活动弹窗(self):
        图像 = np.full((600, 800, 3), (55, 115, 60), dtype=np.uint8)
        cv2.rectangle(图像, (700, 20), (735, 55), (20, 20, 220), -1)

        self.assertIsNone(任务上下文._检测主世界活动弹窗关闭点(图像))

    def test_中央教程只有正文没有按钮时安全停止(self):
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

        self.assertIsNone(候选)

    def test_中央教程误把左下世界切换入口当继续按钮时安全停止(self):
        """地图上的教程关键词不能授权点击飞艇/世界切换入口。"""
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.获取OCR引擎 = Mock(return_value=Mock(return_value=(
            [
                ([[200, 170], [500, 170], [500, 210], [200, 210]],
                 "首领", 0.95),
            ],
            None,
        )))
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 模拟左下常驻世界入口/飞艇附近的大块绿色控件；旧回退会把
        # 它当作教程“继续”，实机坐标约为 (226,568)。
        cv2.rectangle(图像, (150, 525), (300, 580), (0, 220, 0), -1)

        self.assertIsNone(上下文._识别中央游戏提示(图像))

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

    def test_传统能力继续提示可以识别中央继续按钮(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.获取OCR引擎 = Mock(return_value=Mock(return_value=(
            [
                ([[234, 336], [374, 336], [374, 386], [234, 386]],
                 "繼續", 0.98),
            ],
            None,
        )))
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)

        候选 = 上下文._识别中央游戏提示(图像)

        self.assertIsNotNone(候选)
        self.assertEqual(候选["点击点"], (400, 505))

    def test_延时期间会低频处理异步中央能力提示(self):
        """能力弹层在任务运行中出现时，不能等到下一轮任务才处理。"""
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.停止事件 = threading.Event()
        上下文.继续事件 = threading.Event()
        上下文.继续事件.set()
        上下文._战斗中 = False
        上下文.op = None
        上下文._升级完成弹窗调度时间 = 10**9
        上下文._星级奖励调度时间 = 10**9
        上下文.自动确认升级完成弹窗 = Mock()
        上下文.处理战斗星级奖励弹窗 = Mock()
        上下文.清理中央游戏提示 = Mock(return_value=True)
        上下文.企业微信通知器 = None
        上下文.上报间隔秒 = 0

        上下文.脚本延时(800)

        self.assertGreaterEqual(上下文.清理中央游戏提示.call_count, 1)
        self.assertLessEqual(上下文.清理中央游戏提示.call_count, 2)

    def test_延时期间断线页面不会处理底层中央提示(self):
        """后台低频检查也必须阻止断线遮罩下的底层 OCR 点击。"""
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.停止事件 = threading.Event()
        上下文.继续事件 = threading.Event()
        上下文.继续事件.set()
        上下文._战斗中 = False
        上下文._升级完成弹窗调度时间 = 10**9
        上下文._星级奖励调度时间 = 10**9
        上下文.自动确认升级完成弹窗 = Mock()
        上下文.处理战斗星级奖励弹窗 = Mock()
        上下文.清理中央游戏提示 = Mock(return_value=True)
        上下文.企业微信通知器 = None
        上下文.上报间隔秒 = 0
        上下文.op = SimpleNamespace(
            获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))
        )
        上下文.获取模板识别器 = Mock(return_value=Mock())

        with patch("模块.检测.页面识别器.页面识别器") as 页面识别器:
            页面识别器.return_value.识别.return_value = SimpleNamespace(
                页面="断线弹窗"
            )
            上下文.脚本延时(800)

        上下文.清理中央游戏提示.assert_not_called()

    def test_长时间待机把中央提示扫描降到低频(self):
        """长时间待机不应按普通操作频率反复截图检查教程弹层。"""
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.停止事件 = threading.Event()
        上下文.继续事件 = threading.Event()
        上下文.继续事件.set()
        上下文._战斗中 = False
        上下文._任务计划长时间等待 = True
        上下文._升级完成弹窗调度时间 = time.monotonic()
        上下文._中央提示调度时间 = time.monotonic()
        上下文._星级奖励调度时间 = time.monotonic()
        上下文.自动确认升级完成弹窗 = Mock()
        上下文.处理战斗星级奖励弹窗 = Mock()
        上下文.清理中央游戏提示 = Mock(return_value=False)
        上下文.企业微信通知器 = None
        上下文.上报间隔秒 = 0

        上下文.脚本延时(900)

        上下文.清理中央游戏提示.assert_not_called()

    def test_中央说明正文较大时仍优先点击底部继续按钮(self):
        """不能把能力说明正文当成继续按钮点击。"""
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.获取OCR引擎 = Mock(side_effect=[
            Mock(return_value=(
                [
                    ([[350, 250], [650, 250], [650, 285], [350, 285]],
                     "魔法護盾不會影響排位", 0.98),
                ],
                None,
            )),
            Mock(return_value=(
                [
                    ([[300, 78], [340, 78], [340, 100], [300, 100]],
                     "继續", 0.70),
                ],
                None,
            )),
        ])
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)

        候选 = 上下文._识别中央游戏提示(图像)

        self.assertIsNotNone(候选)
        self.assertEqual(候选["文本"], "继續")
        self.assertGreater(候选["点击点"][1], 450)

    def test_能力正文漏掉按钮文字时使用绿色按钮中心(self):
        """正文 OCR 只能确认提示存在，点击点必须来自底部按钮几何。"""
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.获取OCR引擎 = Mock(return_value=Mock(return_value=(
            [
                ([[350, 250], [650, 250], [650, 285], [350, 285]],
                 "魔法護盾不會影響排位", 0.98),
            ],
            None,
        )))
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (275, 490), (525, 545), (60, 150, 70), -1)

        候选 = 上下文._识别中央游戏提示(图像)

        self.assertIsNotNone(候选)
        self.assertEqual(候选["点击点"], (400, 518))

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

    def test_战斗倒计时存在时仍识别奖励遮罩(self):
        """实机活动奖励卡出现时倒计时仍继续，不能放行下兵点击。"""
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
        self.assertEqual(结果.页面, "战斗奖励选择")
        self.assertTrue(any("奖励选择红色横幅" in 依据 for 依据 in 结果.依据))

    def test_红色最后倒计时存在时仍识别奖励遮罩(self):
        """即使最后几秒倒计时变红，覆盖地图的卡片也要阻断点击。"""
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
        self.assertEqual(结果.页面, "战斗奖励选择")
        self.assertTrue(any("奖励选择红色横幅" in 依据 for 依据 in 结果.依据))

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

    def test_夜世界蓝紫结算页的绿色回营按钮可识别(self):
        """夜世界结算页没有金色横幅时也必须能安全回营。"""
        图像 = np.full((600, 800, 3), (18, 25, 42), dtype=np.uint8)
        cv2.rectangle(图像, (315, 485), (485, 565), (90, 220, 120), -1)
        # 模拟结算页中央星级/百分比的亮色结构，而不是依赖固定文字模板。
        for 中心 in ((275, 175), (400, 175), (525, 175)):
            cv2.circle(图像, 中心, 28, (235, 235, 235), -1)
        cv2.putText(
            图像, "0%", (350, 335), cv2.FONT_HERSHEY_SIMPLEX,
            1.8, (255, 255, 255), 4, cv2.LINE_AA,
        )
        结果 = self.识别器.识别(图像, 战斗中=True)
        self.assertEqual(结果.页面, "战斗结算")
        self.assertEqual(self.识别器.定位结算回营按钮(图像), (400, 525))

    def test_三帧复核时单个残留战斗信号可由结算结构与回营按钮覆盖(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        识别器 = 页面识别器(Mock())
        识别器._结算结果视觉分数 = Mock(return_value=0.94)
        识别器._定位绿色回营按钮 = Mock(return_value=(400, 525))
        识别器._红色放弃按钮分数 = Mock(return_value=0.0)
        识别器._战斗倒计时分数 = Mock(return_value=0.96)

        # 默认页面复核仍拒绝战斗倒计时；只有回营状态机已完成前两帧
        # 结算复核后，才可请求此单帧残留信号的受限回退。
        self.assertIsNone(识别器.定位结算回营按钮(图像))
        self.assertEqual(
            识别器.定位结算回营按钮(图像, 允许单帧战斗信号=True),
            (400, 525),
        )

        识别器._红色放弃按钮分数 = Mock(return_value=0.93)
        self.assertIsNone(
            识别器.定位结算回营按钮(图像, 允许单帧战斗信号=True)
        )

    def test_夜世界暗色结果遮罩仍可识别结算页(self):
        """实机暗色结算动画中亮色星级结构不足时仍必须能回营。"""
        图像 = np.full((600, 800, 3), (12, 18, 30), dtype=np.uint8)
        cv2.rectangle(图像, (315, 485), (485, 565), (90, 220, 120), -1)
        cv2.putText(
            图像, "0%", (350, 335), cv2.FONT_HERSHEY_SIMPLEX,
            1.8, (255, 255, 255), 4, cv2.LINE_AA,
        )
        结果 = 页面识别器(Mock()).识别(图像, 战斗中=True)
        self.assertEqual(结果.页面, "战斗结算")

    def test_战斗底部高兵栏绿色区域不会当成回营按钮(self):
        """实机战斗底部部署区不能触发假结算。"""
        识别器 = 页面识别器(Mock())
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 约等于实机 1280x720 截图中 x=486..793、y=547..712 的
        # 兵栏/部署背景，宽高比约1.86，不是横向回营按钮。
        cv2.rectangle(图像, (304, 456), (496, 599), (90, 220, 120), -1)
        self.assertIsNone(识别器._定位绿色回营按钮(图像))
        识别器._最佳分数 = Mock(return_value=0.0)
        结果 = 识别器.识别(图像, 战斗中=True)
        self.assertNotEqual(结果.页面, "战斗结算")

    def test_夜世界结算绿色回营按钮可识别(self):
        """夜世界实机按钮较窄，不能被战斗兵栏保护条件排除。"""
        识别器 = 页面识别器(Mock())
        图像 = np.full((600, 800, 3), (38, 45, 70), dtype=np.uint8)
        cv2.rectangle(图像, (348, 481), (452, 535), (105, 225, 75), -1)
        cv2.putText(
            图像, "69%", (335, 280), cv2.FONT_HERSHEY_SIMPLEX,
            2.0, (245, 245, 245), 4, cv2.LINE_AA
        )
        self.assertIsNotNone(识别器._定位绿色回营按钮(图像))
        self.assertEqual(识别器.识别(图像, 战斗中=False).页面, "战斗结算")

    def test_夜世界胜利之星奖励弹窗定位中央确定按钮(self):
        """回营后的星级奖励遮罩不能被底层夜世界资源栏掩盖。"""
        图像 = np.full((600, 800, 3), (154, 68, 40), dtype=np.uint8)
        cv2.rectangle(图像, (120, 70), (680, 540), (154, 68, 40), -1)
        cv2.rectangle(图像, (340, 420), (460, 500), (70, 210, 140), -1)
        识别器 = 页面识别器(Mock())
        识别器._最佳分数 = Mock(return_value=0.0)
        识别器._红色放弃按钮分数 = Mock(return_value=0.0)
        识别器._战斗倒计时分数 = Mock(return_value=0.0)
        结果 = 识别器.识别(图像)
        self.assertEqual(结果.页面, "战斗星级奖励")
        self.assertEqual(识别器.定位战斗星级奖励确定按钮(图像), (400, 460))

    def test_实机缩放奖励页较低确定按钮仍可识别(self):
        """1280x720 实机缩放后确定按钮约落在参考 y=512。"""
        图像 = np.full((600, 800, 3), (18, 25, 42), dtype=np.uint8)
        cv2.rectangle(图像, (90, 25), (710, 520), (180, 75, 60), -1)
        cv2.rectangle(图像, (336, 480), (465, 551), (70, 210, 140), -1)
        识别器 = 页面识别器(Mock())
        self.assertEqual(
            识别器.定位战斗星级奖励确定按钮(图像), (401, 516)
        )

    def test_战斗中的蓝紫结构不能抢先误判星级奖励(self):
        """战斗倒计时和放弃按钮存在时必须继续下兵。"""
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        识别器 = 页面识别器(Mock())
        识别器._最佳分数 = Mock(return_value=0.0)
        识别器._红色放弃按钮分数 = Mock(return_value=0.93)
        识别器._战斗倒计时分数 = Mock(return_value=0.96)
        识别器._战斗星级奖励视觉分数 = Mock(return_value=0.96)
        结果 = 识别器.识别(图像, 战斗中=True)
        self.assertEqual(结果.页面, "战斗中")
        self.assertNotEqual(结果.页面, "战斗星级奖励")

    def test_夜世界结算页底部回营按钮不误判星级奖励(self):
        """结算页按钮在更低位置，不能被当成中央确定按钮。"""
        图像 = np.full((600, 800, 3), (18, 25, 42), dtype=np.uint8)
        cv2.rectangle(图像, (315, 485), (485, 565), (90, 220, 120), -1)
        self.assertIsNone(self.识别器.定位战斗星级奖励确定按钮(图像))

    def test_新版胜利之星弹窗需标题与领取按钮同时确认(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        def 文字框(x, y):
            return ([[x - 20, y - 10], [x + 20, y - 10],
                     [x + 20, y + 10], [x - 20, y + 10]],)
        OCR = [
            (文字框(400, 150)[0], "已收到勝利之星", 0.99),
            (文字框(415, 480)[0], "领取", 0.99),
        ]
        self.assertEqual(
            self.识别器.识别战后奖励按钮(图像, OCR),
            ("领取", (415, 480)),
        )
        self.assertIsNone(
            self.识别器.识别战后奖励按钮(
                图像, [(文字框(415, 480)[0], "领取", 0.99)]
            )
        )

    def test_宝箱动画跳过与二次确认使用受限坐标(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        跳过框 = [[730, 540], [770, 540], [770, 570], [730, 570]]
        self.assertIsNone(
            self.识别器.识别战后奖励按钮(
                图像, [(跳过框, "跳過", 0.99)]
            )
        )
        self.assertEqual(
            self.识别器.识别战后奖励按钮(
                图像, [(跳过框, "跳過", 0.99)], 奖励动画处理中=True
            ),
            ("跳过动画", (750, 555)),
        )

        cv2.rectangle(图像, (480, 350), (600, 430), (0, 255, 0), -1)
        OCR = [
            ([[330, 170], [470, 170], [470, 190], [330, 190]],
             "跳過寶箱動畫", 0.99),
            ([[290, 240], [520, 240], [520, 270], [290, 270]],
             "你將獲得，但會跳過實箱動。仍要跳過", 0.98),
        ]
        操作, 点 = self.识别器.识别战后奖励按钮(
            图像, OCR, 奖励动画处理中=True
        )
        self.assertEqual(操作, "确认跳过")
        self.assertGreaterEqual(图像[点[1], 点[0], 1], 200)
        self.assertGreater(点[0], 480)

    def test_战后短窗口将新式奖励页送入受保护页面分支(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        def 文字框(x, y):
            return [[x - 20, y - 10], [x + 20, y - 10],
                    [x + 20, y + 10], [x - 20, y + 10]]
        OCR = [
            (文字框(400, 150), "已收到勝利之星", 0.99),
            (文字框(415, 480), "领取", 0.99),
        ]
        识别器 = 页面识别器(Mock())
        with patch.object(
            识别器,
            "识别",
            return_value=页面识别结果(
                页面="主世界主页", 世界="主世界", 可信度=0.8, 依据=()
            ),
        ):
            上下文 = object.__new__(任务上下文)
            上下文._战斗中 = False
            上下文._战后星级奖励检查截止时间 = float("inf")
            上下文._获取点击识别截图 = Mock(return_value=图像)
            上下文._获取点击页面识别器 = Mock(return_value=识别器)
            上下文.获取OCR引擎 = Mock(
                return_value=Mock(return_value=(OCR, None))
            )
            上下文.置脚本状态 = Mock()

            结果 = 上下文.识别点击画面(强制=True)

        self.assertEqual(结果.页面, "战斗星级奖励")
        self.assertEqual(
            上下文._最近战后奖励按钮候选[:2],
            ("领取", (415, 480)),
        )

    def test_确认战后窗口可识别回营后直接出现的宝箱跳过按钮(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        跳过框 = [[730, 540], [770, 540], [770, 570], [730, 570]]
        上下文 = object.__new__(任务上下文)
        上下文._战斗中 = False
        上下文._战后星级奖励检查截止时间 = float("inf")
        上下文._战后奖励动画处理中 = False
        上下文._战后奖励OCR检查时间 = 0.0
        上下文._战后奖励OCR缓存帧ID = None
        上下文._战后奖励OCR缓存候选 = None
        上下文.获取OCR引擎 = Mock(
            return_value=Mock(
                return_value=([(跳过框, "跳過", 0.99)], None)
            )
        )

        候选 = 上下文._识别战后奖励按钮(
            图像, self.识别器, "未知"
        )

        self.assertEqual(候选, ("跳过动画", (750, 555)))

    def test_残留战斗标记但倒计时已消失时允许OCR复核奖励页(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        def 文字框(x, y):
            return [[x - 20, y - 10], [x + 20, y - 10],
                    [x + 20, y + 10], [x - 20, y + 10]]
        OCR = [
            (文字框(400, 150), "已收到勝利之星", 0.99),
            (文字框(415, 480), "领取", 0.99),
        ]
        识别器 = 页面识别器(Mock())
        识别器._战斗倒计时分数 = Mock(return_value=0.0)
        with patch.object(
            识别器,
            "识别",
            return_value=页面识别结果(
                页面="战斗中", 世界=None, 可信度=0.93, 依据=("残留放弃按钮",)
            ),
        ):
            上下文 = object.__new__(任务上下文)
            上下文._战斗中 = True
            上下文._战后星级奖励检查截止时间 = float("inf")
            上下文._获取点击识别截图 = Mock(return_value=图像)
            上下文._获取点击页面识别器 = Mock(return_value=识别器)
            上下文.获取OCR引擎 = Mock(
                return_value=Mock(return_value=(OCR, None))
            )
            上下文.置脚本状态 = Mock()
            结果 = 上下文.识别点击画面(强制=True)

        self.assertEqual(结果.页面, "战斗星级奖励")
        识别器._战斗倒计时分数.assert_called_once_with(图像)

    def test_活跃战斗倒计时下不加载战后OCR(self):
        上下文 = object.__new__(任务上下文)
        上下文._战斗中 = True
        上下文._战后星级奖励检查截止时间 = float("inf")
        识别器 = Mock()
        识别器._战斗倒计时分数.return_value = 0.96
        上下文.获取OCR引擎 = Mock()
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)

        self.assertIsNone(
            上下文._识别战后奖励按钮(图像, 识别器, "战斗中")
        )
        上下文.获取OCR引擎.assert_not_called()

    def test_新式胜利之星领取使用安全按钮通道并进入动画状态(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文 = object.__new__(任务上下文)
        上下文._战斗中 = True
        上下文._最近战后奖励按钮候选 = ("领取", (415, 480), id(图像))
        上下文._点击识别截图 = 图像
        上下文.点击已确认安全按钮 = Mock(return_value=True)
        上下文.清除战斗结算保护状态 = Mock()
        上下文.置脚本状态 = Mock()

        self.assertTrue(上下文.处理战斗星级奖励弹窗())
        上下文.点击已确认安全按钮.assert_called_once_with(
            415, 480, 延时=350
        )
        self.assertTrue(上下文._战后奖励动画处理中)
        self.assertGreater(上下文._战后星级奖励检查截止时间, 0)
        self.assertFalse(上下文._战斗中)

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

    def test_评分样式多按钮弹窗不能进入断线恢复(self):
        图像 = np.full((600, 800, 3), (10, 18, 22), dtype=np.uint8)
        cv2.rectangle(图像, (164, 180), (635, 423), (32, 26, 29), -1)
        for 左, 上, 右, 下 in ((201, 218, 404, 244), (201, 270, 580, 294),
                               (201, 306, 332, 328), (201, 368, 235, 389),
                               (475, 368, 540, 389), (575, 368, 610, 389)):
            cv2.rectangle(图像, (左, 上), (右, 下), (220, 220, 220), -1)
        for 画面 in (图像, cv2.resize(图像, (1280, 720))):
            with self.subTest(尺寸=画面.shape):
                self.assertEqual(self.识别器.识别(画面).页面, "多按钮弹窗")
                self.assertEqual(检测游戏登录状态任务._检测断线弹窗(画面),
                                 (False, (0, 0)))

    def test_超级部队选择卡片弹窗优先于主世界HUD(self):
        """中央卡片覆盖主页时必须识别弹窗，不能让资源任务穿透。"""
        图像 = np.full((600, 800, 3), (30, 40, 50), dtype=np.uint8)
        for x in (120, 280, 440, 600):
            cv2.rectangle(图像, (x, 220), (x + 90, 360), (0, 0, 220), -1)
            cv2.rectangle(图像, (x, 400), (x + 90, 530), (0, 0, 220), -1)
        cv2.rectangle(图像, (650, 25), (705, 80), (0, 0, 220), -1)
        cv2.line(图像, (662, 37), (693, 68), (255, 255, 255), 5)
        cv2.line(图像, (693, 37), (662, 68), (255, 255, 255), 5)

        结果 = self.识别器.识别(图像)

        self.assertEqual(结果.页面, "选择卡片弹窗")
        self.assertGreaterEqual(结果.可信度, 0.90)
        关闭点 = self.识别器.定位选择卡片弹窗关闭按钮(图像)
        self.assertIsNotNone(关闭点)
        self.assertAlmostEqual(关闭点[0], 678, delta=8)
        self.assertAlmostEqual(关闭点[1], 53, delta=8)
        # 战斗标志可能在过渡期尚未清除；没有战斗 HUD 时真实卡片仍须拦截。
        self.assertEqual(self.识别器.识别(图像, 战斗中=True).页面, "选择卡片弹窗")

    def test_战场底部兵栏不应伪装成选择卡片弹窗(self):
        """实机搜索后持续误报卡片弹窗，导致整场 0% 不下兵。"""
        图像 = np.full((600, 800, 3), (30, 40, 50), dtype=np.uint8)
        for x in (120, 280, 440, 600):
            cv2.rectangle(图像, (x, 400), (x + 90, 530), (0, 0, 220), -1)
        cv2.rectangle(图像, (650, 25), (705, 80), (0, 0, 220), -1)
        cv2.line(图像, (662, 37), (693, 68), (255, 255, 255), 5)
        cv2.line(图像, (693, 37), (662, 68), (255, 255, 255), 5)
        cv2.rectangle(图像, (12, 430), (105, 467), (0, 0, 220), -1)
        cv2.putText(图像, "27", (346, 80), cv2.FONT_HERSHEY_SIMPLEX,
                    1.8, (255, 255, 255), 4)

        self.assertEqual(self.识别器.识别(图像, 战斗中=True).页面, "战斗中")

    def test_宽屏底部结束战斗按钮与倒计时优先于卡片误判(self):
        """16:9 新界面按钮更靠下，红色按钮仍应与倒计时组成战场证据。"""
        图像 = np.full((576, 1024, 3), (30, 40, 50), dtype=np.uint8)
        for x in (120, 300, 480, 660):
            cv2.rectangle(图像, (x, 190), (x + 120, 340), (0, 0, 220), -1)
        cv2.rectangle(图像, (850, 25), (920, 80), (0, 0, 220), -1)
        cv2.line(图像, (862, 37), (908, 68), (255, 255, 255), 5)
        cv2.line(图像, (908, 37), (862, 68), (255, 255, 255), 5)
        cv2.rectangle(图像, (15, 451), (135, 491), (0, 0, 220), -1)
        cv2.putText(
            图像, "2:40", (460, 88), cv2.FONT_HERSHEY_SIMPLEX,
            1.0, (255, 255, 255), 3,
        )

        self.assertGreaterEqual(self.识别器._选择卡片弹窗分数(图像), 0.90)
        self.assertGreaterEqual(self.识别器._红色放弃按钮分数(图像), 0.90)
        self.assertGreaterEqual(self.识别器._战斗倒计时分数(图像), 0.90)
        self.assertEqual(self.识别器.识别(图像, 战斗中=False).页面, "战斗中")

    def test_双重战斗画面证据在战斗状态未初始化时优先于卡片误判(self):
        """进攻初始化前的点击护栏也要识别明确战场，不能误清理成卡片弹窗。"""
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        with patch.object(self.识别器, "_系统维护分数", return_value=0.0), \
             patch.object(self.识别器, "_选择卡片弹窗分数", return_value=0.97), \
             patch.object(self.识别器, "_升级详情弹窗分数", return_value=0.0), \
             patch.object(self.识别器, "_断线弹窗分数", return_value=0.0), \
             patch.object(self.识别器, "_红色放弃按钮分数", return_value=0.93), \
             patch.object(self.识别器, "_战斗倒计时分数", return_value=0.96), \
             patch.object(self.识别器, "_最佳分数", return_value=0.0), \
             patch.object(self.识别器, "_结算结果视觉分数", return_value=0.0), \
             patch.object(self.识别器, "_奖励选择横幅分数", return_value=0.0):
            结果 = self.识别器.识别(图像, 战斗中=False)

        self.assertEqual(结果.页面, "战斗中")

    def test_升级详情弹窗优先于主世界HUD(self):
        """升级面板露出主页徽章时不能继续读取资源或点击入口。"""
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (70, 20), (730, 580), (70, 80, 90), -1)
        cv2.rectangle(图像, (90, 30), (650, 80), (100, 100, 105), -1)
        cv2.rectangle(图像, (690, 20), (730, 70), (0, 0, 220), -1)
        cv2.line(图像, (698, 28), (722, 62), (245, 245, 245), 6)
        cv2.line(图像, (722, 28), (698, 62), (245, 245, 245), 6)

        结果 = self.识别器.识别(图像)

        self.assertEqual(结果.页面, "升级详情弹窗")
        self.assertGreaterEqual(结果.可信度, 0.90)
        关闭点 = self.识别器.定位升级详情弹窗关闭按钮(图像)
        self.assertIsNotNone(关闭点)
        self.assertAlmostEqual(关闭点[0], 710, delta=5)
        self.assertAlmostEqual(关闭点[1], 45, delta=5)

    def test_双重战斗画面证据优先于升级详情且不依赖状态标志(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        with patch.object(self.识别器, "_升级详情弹窗分数", return_value=0.96), \
             patch.object(self.识别器, "_红色放弃按钮分数", return_value=0.93), \
             patch.object(self.识别器, "_战斗倒计时分数", return_value=0.96), \
             patch.object(self.识别器, "_最佳分数", return_value=0.0), \
             patch.object(self.识别器, "_结算结果视觉分数", return_value=0.0), \
             patch.object(self.识别器, "_奖励选择横幅分数", return_value=0.0):
            self.assertEqual(self.识别器.识别(图像, 战斗中=True).页面, "战斗中")
            self.assertEqual(self.识别器.识别(图像, 战斗中=False).页面, "战斗中")

    def test_升级详情只有单一战斗证据仍须拦截(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        with patch.object(self.识别器, "_升级详情弹窗分数", return_value=0.96), \
             patch.object(self.识别器, "_红色放弃按钮分数", return_value=0.93), \
             patch.object(self.识别器, "_战斗倒计时分数", return_value=0.0):
            self.assertEqual(self.识别器.识别(图像, 战斗中=True).页面, "升级详情弹窗")

    def test_实机结算摧毁率区域不会误报战斗倒计时(self):
        区域路径 = self.根目录 / "tests" / "fixtures" / "page_detection" / "settlement_counter_header.png"
        区域 = cv2.imread(str(区域路径))
        self.assertIsNotNone(区域)
        高, 宽 = 580, 1023
        图像 = np.zeros((高, 宽, 3), dtype=np.uint8)
        左 = int(宽 * 0.32)
        图像[:区域.shape[0], 左:左 + 区域.shape[1]] = 区域

        with patch.object(self.识别器, "_结算结果视觉分数", return_value=0.96), \
             patch.object(self.识别器, "_红色放弃按钮分数", return_value=0.0), \
             patch.object(self.识别器, "_最佳分数", return_value=0.0), \
             patch.object(self.识别器, "_奖励选择横幅分数", return_value=0.0):
            结果 = self.识别器.识别(图像, 战斗中=True)

        self.assertEqual(结果.页面, "战斗结算")

    def test_战斗放弃按钮仍可阻止伪结算(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        with patch.object(self.识别器, "_结算结果视觉分数", return_value=0.96), \
             patch.object(self.识别器, "_战斗倒计时分数", return_value=0.96), \
             patch.object(self.识别器, "_红色放弃按钮分数", return_value=0.93), \
             patch.object(self.识别器, "_最佳分数", return_value=0.0), \
             patch.object(self.识别器, "_奖励选择横幅分数", return_value=0.0):
            self.assertEqual(self.识别器.识别(图像, 战斗中=True).页面, "战斗中")

    def test_升级详情弹窗点击护栏阻断原始输入(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.检查宝石商店危险页面 = Mock(return_value=False)
        上下文._最近点击页面结果 = SimpleNamespace(页面="升级详情弹窗")
        上下文._点击识别截图 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文.关闭升级详情弹窗 = Mock(return_value=True)

        self.assertTrue(上下文.输入前安全检查())
        上下文.关闭升级详情弹窗.assert_called_once_with(上下文._点击识别截图)

    def test_活动OCR与升级OCR互斥(self):
        活动OCR = [
            ([], "活動"),
            ([], "剩餘時間：4小時22分鐘"),
            ([], "部落競賽"),
        ]
        升级OCR = [
            ([], "正在將野蠻人之王升至84級"),
            ([], "剩餘時間：1小時"),
        ]

        self.assertTrue(任务上下文._OCR确认主世界活动弹窗(活动OCR))
        self.assertFalse(任务上下文._OCR确认主世界活动弹窗(升级OCR))
        self.assertFalse(任务上下文._OCR确认升级详情页(活动OCR))
        self.assertTrue(任务上下文._OCR确认升级详情页(升级OCR))

    def test_升级几何误判活动页时交给活动关闭器(self):
        """活动页命中升级几何特征时仍只允许活动专用安全关闭。"""
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文._点击识别截图 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文.检查宝石商店危险页面 = Mock(return_value=False)
        上下文._最近点击页面结果 = SimpleNamespace(页面="升级详情弹窗")
        上下文.页面恢复失败 = False
        上下文.关闭升级详情弹窗 = Mock(return_value=False)
        上下文.清理主世界活动弹窗 = Mock(return_value=True)

        self.assertTrue(上下文.输入前安全检查())
        上下文.关闭升级详情弹窗.assert_called_once_with(上下文._点击识别截图)
        上下文.清理主世界活动弹窗.assert_called_once_with(上下文._点击识别截图)

    def test_选择卡片弹窗点击护栏先清理并阻断输入(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.检查宝石商店危险页面 = Mock(return_value=False)
        上下文._最近点击页面结果 = SimpleNamespace(页面="选择卡片弹窗")
        上下文._点击识别截图 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文.清理选择卡片弹窗 = Mock(return_value=True)

        self.assertTrue(上下文.输入前安全检查())
        上下文.清理选择卡片弹窗.assert_called_once_with(上下文._点击识别截图)

    def test_选择卡片关闭后断线页交给登录恢复(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文._内存保护已触发 = False
        上下文.op = SimpleNamespace(
            清理截图缓存=Mock(),
            获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8)),
        )
        上下文.脚本延时 = Mock()
        上下文.置脚本状态 = Mock()
        上下文.点击已确认安全按钮 = Mock(return_value=True)
        识别器 = Mock()
        识别器.识别.side_effect = [
            SimpleNamespace(页面="选择卡片弹窗"),
            SimpleNamespace(页面="断线弹窗"),
        ]
        识别器.定位选择卡片弹窗关闭按钮.return_value = (684, 58)
        上下文._获取点击页面识别器 = Mock(return_value=识别器)

        self.assertTrue(
            上下文.清理选择卡片弹窗(np.zeros((600, 800, 3), dtype=np.uint8))
        )
        上下文.点击已确认安全按钮.assert_called_once_with(684, 58, 延时=260)
        self.assertTrue(any("交给登录恢复流程" in 调用.args[0]
                            for 调用 in 上下文.置脚本状态.call_args_list))

    def test_多按钮弹窗文字未确认时禁止穿透输入(self):
        for 已清理 in (False, True):
            with self.subTest(已清理=已清理):
                上下文 = 任务上下文.__new__(任务上下文)
                上下文.检查宝石商店危险页面 = Mock(return_value=False)
                上下文._最近点击页面结果 = SimpleNamespace(页面="多按钮弹窗")
                上下文.清理官方评分弹窗 = Mock(return_value=已清理)
                self.assertTrue(上下文.输入前安全检查())
                上下文.清理官方评分弹窗.assert_called_once_with()

    def test_已确认研究目标页允许研究流程继续点击(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.检查宝石商店危险页面 = Mock(return_value=False)
        上下文._最近点击页面结果 = SimpleNamespace(页面="多按钮弹窗")
        上下文._研究面板已确认 = True
        上下文.清理官方评分弹窗 = Mock(return_value=False)

        self.assertFalse(上下文.输入前安全检查())
        上下文.清理官方评分弹窗.assert_not_called()

    def test_主页识别到升级面板几何候选时先走安全关闭器(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文._点击识别截图 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文.检查宝石商店危险页面 = Mock(return_value=False)
        上下文._最近点击页面结果 = SimpleNamespace(页面="主世界主页")
        上下文._检测升级详情弹窗关闭点 = Mock(return_value=(710, 45))
        上下文.关闭升级详情弹窗 = Mock(return_value=True)

        self.assertTrue(上下文.输入前安全检查())
        上下文.关闭升级详情弹窗.assert_called_once_with(上下文._点击识别截图)

    def test_普通主页没有升级面板几何候选时不触发OCR关闭器(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文._点击识别截图 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文.检查宝石商店危险页面 = Mock(return_value=False)
        上下文._最近点击页面结果 = SimpleNamespace(页面="主世界主页")
        上下文._检测升级详情弹窗关闭点 = Mock(return_value=None)
        上下文.关闭升级详情弹窗 = Mock(return_value=True)

        self.assertFalse(上下文.输入前安全检查())
        上下文.关闭升级详情弹窗.assert_not_called()

    def test_城墙已确认资源点击时不被升级面板护栏拦截(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文._城墙升级资源点击中 = True
        上下文._点击识别截图 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文.检查宝石商店危险页面 = Mock(return_value=False)
        上下文._最近点击页面结果 = SimpleNamespace(页面="主世界主页")
        上下文._检测升级详情弹窗关闭点 = Mock(return_value=(710, 45))
        上下文.关闭升级详情弹窗 = Mock(return_value=True)

        self.assertFalse(上下文.输入前安全检查())
        上下文.关闭升级详情弹窗.assert_not_called()

    def test_主页活动面板候选时先安全关闭不穿透(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文._点击识别截图 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文.检查宝石商店危险页面 = Mock(return_value=False)
        上下文._最近点击页面结果 = SimpleNamespace(页面="主世界主页")
        上下文._检测主世界活动弹窗关闭点 = Mock(return_value=(710, 38))
        上下文.清理主世界活动弹窗 = Mock(return_value=True)
        上下文._检测升级详情弹窗关闭点 = Mock(return_value=None)
        上下文.关闭升级详情弹窗 = Mock(return_value=True)

        self.assertTrue(上下文.输入前安全检查())
        上下文.清理主世界活动弹窗.assert_called_once_with(上下文._点击识别截图)
        上下文.关闭升级详情弹窗.assert_not_called()

    def test_系统维护页优先于断线弹窗识别(self):
        """维护页的黄黑警示带优先于中央深色面板，避免重复点击重试。"""
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        图像[:18, :] = (20, 210, 245)
        cv2.rectangle(图像, (195, 190), (635, 430), (32, 26, 29), -1)
        cv2.rectangle(图像, (250, 220), (500, 235), (235, 235, 235), -1)
        cv2.rectangle(图像, (250, 280), (580, 296), (225, 225, 225), -1)
        cv2.rectangle(图像, (260, 380), (420, 398), (240, 240, 240), -1)

        结果 = self.识别器.识别(图像)

        self.assertEqual(结果.页面, "系统维护")
        self.assertTrue(any("黄黑维护警示带" in 依据 for 依据 in 结果.依据))

    def test_战斗顶部黄色HUD条单独出现不应识别为系统维护(self):
        """黄条可能来自战斗HUD；维护页还必须有中央维护弹窗证据。"""
        图像 = np.full((600, 800, 3), (70, 100, 55), dtype=np.uint8)
        图像[:18, :] = (20, 210, 245)

        结果 = self.识别器.识别(图像, 战斗中=True)

        self.assertNotEqual(结果.页面, "系统维护")

    def test_维护页登录任务安全停止不点击(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[:18, :] = (20, 210, 245)
        cv2.rectangle(屏幕, (195, 190), (635, 430), (32, 26, 29), -1)
        cv2.rectangle(屏幕, (250, 220), (500, 235), (235, 235, 235), -1)
        cv2.rectangle(屏幕, (250, 280), (580, 296), (225, 225, 225), -1)
        cv2.rectangle(屏幕, (260, 380), (420, 398), (240, 240, 240), -1)
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

    def test_伪结算视觉不能覆盖仍在运行的战斗倒计时(self):
        """实战里的回营/横幅误报不得压过仍在运行的倒计时。"""
        识别器 = 页面识别器(Mock())
        识别器._最佳分数 = Mock(return_value=0.0)
        识别器._红色放弃按钮分数 = Mock(return_value=0.0)
        识别器._结算结果视觉分数 = Mock(return_value=0.92)
        识别器._战斗倒计时分数 = Mock(return_value=0.96)
        识别器._奖励选择横幅分数 = Mock(return_value=0.0)
        识别器.世界识别 = SimpleNamespace(
            识别=Mock(return_value=SimpleNamespace(当前世界=None))
        )

        结果 = 识别器.识别(
            np.zeros((600, 800, 3), dtype=np.uint8), 战斗中=True
        )

        self.assertEqual(结果.页面, "战斗中")
        self.assertIn("战斗倒计时0.96", " ".join(结果.依据))

    def test_红色放弃按钮在倒计时漏检时优先于伪结算(self):
        """实战红字倒计时偶尔漏检，仍可见的放弃按钮不能被伪结算覆盖。"""
        识别器 = 页面识别器(Mock())
        识别器._最佳分数 = Mock(return_value=0.85)
        识别器._红色放弃按钮分数 = Mock(return_value=0.93)
        识别器._战斗倒计时分数 = Mock(return_value=0.0)
        结果 = 识别器.识别(np.zeros((600, 800, 3), dtype=np.uint8), 战斗中=True)
        self.assertEqual(结果.页面, "战斗中")
        self.assertTrue(any("红色放弃按钮" in 依据 for 依据 in 结果.依据))

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

    def test_启动时结算按钮首帧漏检后双帧复核再回营(self):
        上下文 = SimpleNamespace(
            数据库=Mock(),
            机器人标志="robot_test",
            置脚本状态=Mock(),
            点击已确认安全按钮=Mock(return_value=True),
            脚本延时=Mock(),
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(
                    side_effect=[
                        np.zeros((600, 800, 3), dtype=np.uint8),
                        np.zeros((600, 800, 3), dtype=np.uint8),
                    ]
                )
            ),
        )
        任务 = 检测游戏登录状态任务(上下文)
        结算页 = SimpleNamespace(页面="战斗结算", 可信度=0.94)
        页面识别 = Mock()
        页面识别.识别.return_value = 结算页
        页面识别.定位结算回营按钮.side_effect = [None, (53, 531), (53, 531)]
        识图引擎 = Mock()
        识图引擎.执行匹配.return_value = (False, (0, 0), 0.0)
        初始帧 = np.zeros((600, 800, 3), dtype=np.uint8)

        self.assertTrue(任务._启动阶段处理结算页(初始帧, 识图引擎, 页面识别))

        上下文.点击已确认安全按钮.assert_called_once_with(53, 531, 延时=180)
        self.assertEqual(页面识别.定位结算回营按钮.call_count, 3)
        self.assertTrue(any("双帧确认" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_启动时结算页复核转场后不盲点回营(self):
        上下文 = SimpleNamespace(
            数据库=Mock(),
            机器人标志="robot_test",
            置脚本状态=Mock(),
            点击已确认安全按钮=Mock(return_value=True),
            脚本延时=Mock(),
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(
                    return_value=np.zeros((600, 800, 3), dtype=np.uint8)
                )
            ),
        )
        任务 = 检测游戏登录状态任务(上下文)
        页面识别 = Mock()
        页面识别.识别.side_effect = [
            SimpleNamespace(页面="战斗结算", 可信度=0.94),
            SimpleNamespace(页面="未知", 可信度=0.0),
        ]
        页面识别.定位结算回营按钮.side_effect = [None, (53, 531)]
        识图引擎 = Mock()
        识图引擎.执行匹配.return_value = (False, (0, 0), 0.0)

        self.assertTrue(
            任务._启动阶段处理结算页(
                np.zeros((600, 800, 3), dtype=np.uint8), 识图引擎, 页面识别
            )
        )

        上下文.点击已确认安全按钮.assert_not_called()

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

    def test_断线弹窗恢复成功后继续确认主页并只点击一次(self):
        """完整回放断线→重新登入→主页，不能停在恢复分支或重复点击。"""
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(side_effect=[屏幕, 屏幕, 屏幕]),
                设备=SimpleNamespace(
                    获取当前前台包名=Mock(return_value="com.supercell.clashofclans")
                ),
            ),
            设置=SimpleNamespace(部落冲突包名="com.supercell.clashofclans"),
            数据库=Mock(),
            机器人标志="robot_test",
            停止事件=threading.Event(),
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
            点击已确认安全按钮=Mock(return_value=True),
        )
        任务 = 检测游戏登录状态任务(上下文)
        任务.第一次检测游戏登录 = False
        任务._检测断线弹窗 = Mock(
            side_effect=[(True, (256, 365)), (False, (0, 0))]
        )
        for 方法名 in (
            "_启动阶段处理英雄升级详情",
            "_启动阶段处理研究目标页",
            "_启动阶段处理结算页",
            "_启动阶段处理军队配置页",
            "_启动阶段处理主世界活动弹窗",
        ):
            setattr(任务, 方法名, Mock(return_value=False))
        任务._登录主页已确认 = Mock(return_value=True)

        class 假引擎:
            def 执行匹配(self, _图像, 模板路径, **_参数):
                if "家乡进攻图标" in 模板路径 or "不用拉远视距" in 模板路径:
                    return True, (100, 100), 0.95
                return False, (0, 0), 0.0

        class 假页面识别器:
            def 识别(self, _图像, **_参数):
                return SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.78)

        with patch("任务流程.检测游戏登录状态.模板匹配引擎", return_value=假引擎()), \
             patch("任务流程.检测游戏登录状态.页面识别器", return_value=假页面识别器()):
            self.assertTrue(任务.执行(首次登录=False))

        上下文.点击已确认安全按钮.assert_called_once_with(256, 365, 延时=180)
        self.assertEqual(任务._断线弹窗恢复次数, 1)
        self.assertFalse(上下文.页面恢复失败)
        self.assertFalse(上下文.停止事件.is_set())
        self.assertTrue(any("重新载入游戏" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_战斗中重连只确认页面不执行首次缩放(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕)),
            数据库=Mock(),
            机器人标志="robot_test",
            停止事件=threading.Event(),
            置脚本状态=Mock(),
            脚本延时=Mock(),
            游戏内拉远视距=Mock(side_effect=AssertionError("重连时不得缩放")),
        )
        任务 = 检测游戏登录状态任务(上下文)
        任务._检测断线弹窗 = Mock(return_value=(False, (0, 0)))
        for 方法名 in (
            "_启动阶段处理英雄升级详情", "_启动阶段处理研究目标页",
            "_启动阶段处理结算页", "_启动阶段处理军队配置页",
            "_启动阶段处理主世界活动弹窗",
        ):
            setattr(任务, 方法名, Mock(return_value=False))

        class 假引擎:
            def 执行匹配(self, _图像, _模板路径, **_参数):
                return False, (0, 0), 0.0

        class 假页面识别器:
            def 识别(self, _图像, **_参数):
                return SimpleNamespace(页面="战斗中", 世界=None, 可信度=0.96)

        with patch("任务流程.检测游戏登录状态.模板匹配引擎", return_value=假引擎()), \
             patch("任务流程.检测游戏登录状态.页面识别器", return_value=假页面识别器()):
            self.assertTrue(任务.执行(首次登录=False, 仅恢复连接=True))

        上下文.游戏内拉远视距.assert_not_called()
        self.assertTrue(上下文._启动时已有战斗)

    def test_再次登录遇到英雄详情也绝不拉远视距(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕)),
            数据库=Mock(),
            机器人标志="robot_test",
            停止事件=threading.Event(),
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
            游戏内拉远视距=Mock(side_effect=AssertionError("英雄详情上不得缩放")),
        )
        任务 = 检测游戏登录状态任务(上下文)
        任务.第一次检测游戏登录 = False
        任务._检测断线弹窗 = Mock(return_value=(False, (0, 0)))
        任务._启动阶段处理英雄升级详情 = Mock(side_effect=[True, False])

        def 匹配(_图像, 模板路径, **_参数):
            命中 = "家乡进攻图标" in 模板路径 or "不用拉远视距" in 模板路径
            return 命中, (0, 0), 0.9 if 命中 else 0.0

        with patch("任务流程.检测游戏登录状态.模板匹配引擎") as 模板类, \
             patch("任务流程.检测游戏登录状态.页面识别器") as 页面类:
            模板类.return_value.执行匹配.side_effect = 匹配
            详情 = SimpleNamespace(页面="升级详情弹窗")
            主页 = SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.78)
            页面调用 = iter((详情, 主页))
            页面类.return_value.识别.side_effect = (
                lambda *_参数, **_关键字: next(页面调用, 主页)
            )
            self.assertTrue(任务.执行(首次登录=False))

        上下文.游戏内拉远视距.assert_not_called()
        self.assertEqual(任务._启动阶段处理英雄升级详情.call_count, 2)

    def test_断线盖住英雄详情时先恢复最上层弹窗(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕)),
            数据库=Mock(),
            机器人标志="robot_test",
            停止事件=threading.Event(),
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
            游戏内拉远视距=Mock(side_effect=AssertionError("遮挡页上不得缩放")),
        )
        任务 = 检测游戏登录状态任务(上下文)
        任务.第一次检测游戏登录 = False
        任务._检测断线弹窗 = Mock(side_effect=[
            (True, (256, 365)), (False, (0, 0)), (False, (0, 0))
        ])
        任务._执行断线恢复点击 = Mock(return_value=True)
        任务._启动阶段处理英雄升级详情 = Mock(side_effect=[True, False])

        def 匹配(_图像, 模板路径, **_参数):
            命中 = "家乡进攻图标" in 模板路径 or "不用拉远视距" in 模板路径
            return 命中, (0, 0), 0.9 if 命中 else 0.0

        with patch("任务流程.检测游戏登录状态.模板匹配引擎") as 模板类, \
             patch("任务流程.检测游戏登录状态.页面识别器") as 页面类:
            模板类.return_value.执行匹配.side_effect = 匹配
            详情 = SimpleNamespace(页面="升级详情弹窗")
            主页 = SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.78)
            页面调用 = iter((详情, 详情, 主页))
            页面类.return_value.识别.side_effect = (
                lambda *_参数, **_关键字: next(页面调用, 主页)
            )
            self.assertTrue(任务.执行(首次登录=False))

        任务._执行断线恢复点击.assert_called_once_with(256, 365)
        self.assertEqual(任务._启动阶段处理英雄升级详情.call_count, 2)
        上下文.游戏内拉远视距.assert_not_called()

    def test_欢迎回来战报必须有标题和绿色确定按钮(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[475:530, 365:455] = (0, 210, 110)
        OCR项 = [
            ([[328, 64], [468, 64], [468, 91], [328, 91]], "首領，歡迎回來！"),
            ([[398, 492], [423, 492], [423, 511], [398, 511]], "确定"),
        ]
        OCR = Mock(return_value=(OCR项, None))
        任务 = 检测游戏登录状态任务.__new__(检测游戏登录状态任务)
        任务.上下文 = SimpleNamespace(获取OCR引擎=lambda: OCR)

        self.assertEqual(任务._定位欢迎回来确定按钮(屏幕), (410, 501))
        OCR.return_value = ([
            (OCR项[0][0], "其他弹窗"), OCR项[1]
        ], None)
        self.assertIsNone(任务._定位欢迎回来确定按钮(屏幕))
        OCR.return_value = (OCR项, None)
        self.assertIsNone(任务._定位欢迎回来确定按钮(np.zeros_like(屏幕)))

    def test_欢迎回来战报双帧确认后关闭并继续登录(self):
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
            游戏内拉远视距=Mock(side_effect=AssertionError("不应在战报上缩放")),
        )
        任务 = 检测游戏登录状态任务(上下文)
        任务.第一次检测游戏登录 = False
        任务._检测断线弹窗 = Mock(return_value=(False, (0, 0)))
        任务._定位欢迎回来确定按钮 = Mock(
            side_effect=[(410, 501), (410, 501)]
        )
        任务._登录主页已确认 = Mock(return_value=True)
        for 方法名 in (
            "_启动阶段处理英雄升级详情", "_启动阶段处理研究目标页",
            "_启动阶段处理结算页", "_启动阶段处理军队配置页",
            "_启动阶段处理主世界活动弹窗",
        ):
            setattr(任务, 方法名, Mock(return_value=False))

        class 假引擎:
            def 执行匹配(self, _图像, 模板路径, **_参数):
                if "家乡进攻图标" in 模板路径 or "不用拉远视距" in 模板路径:
                    return True, (100, 100), 0.95
                return False, (0, 0), 0.0

        with patch("任务流程.检测游戏登录状态.模板匹配引擎", return_value=假引擎()), \
             patch("任务流程.检测游戏登录状态.页面识别器") as 页面类:
            页面类.return_value.识别.side_effect = [
                SimpleNamespace(页面="多按钮弹窗"),
                SimpleNamespace(页面="主世界主页"),
            ]
            self.assertTrue(任务.执行(首次登录=False))

        上下文.点击已确认安全按钮.assert_called_once_with(410, 501, 延时=180)
        上下文.游戏内拉远视距.assert_not_called()

    def test_旧版断线模板连续命中也受三次恢复上限保护(self):
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
                patch("任务流程.检测游戏登录状态.页面识别器") as 页面识别器:
            引擎类.return_value.执行匹配.return_value = (True, (20, 30), 0.95)
            页面识别器.return_value.识别.return_value = SimpleNamespace(页面="未知")
            任务._检测断线弹窗 = Mock(return_value=(False, (0, 0)))
            self.assertFalse(任务.执行(首次登录=False))

        self.assertEqual(上下文.点击已确认安全按钮.call_count, 3)
        self.assertTrue(上下文.页面恢复失败)
        self.assertTrue(上下文.停止事件.is_set())
        self.assertTrue(any("旧版断线模板" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_断线弹窗优先于底层中央能力提示(self):
        """断线遮住能力层时不能先点击被遮挡的底层继续按钮。"""
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕)),
            数据库=Mock(),
            机器人标志="robot_test",
            停止事件=threading.Event(),
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
            点击已确认安全按钮=Mock(return_value=False),
            清理中央游戏提示=Mock(return_value=True),
        )
        任务 = 检测游戏登录状态任务(上下文)
        with patch("任务流程.检测游戏登录状态.模板匹配引擎") as 引擎类, \
             patch("任务流程.检测游戏登录状态.页面识别器") as 页面识别器:
            引擎类.return_value.执行匹配.return_value = (False, (0, 0), 0.0)
            页面识别器.return_value.识别.return_value = SimpleNamespace(页面="断线弹窗")
            任务._检测断线弹窗 = Mock(return_value=(True, (416, 440)))
            self.assertFalse(任务.执行(首次登录=False))

        上下文.清理中央游戏提示.assert_not_called()
        上下文.点击已确认安全按钮.assert_called_once_with(416, 440, 延时=180)

    def test_登录确定按钮被拒绝时停止恢复不继续轮询(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕)),
            数据库=Mock(),
            机器人标志="robot_test",
            停止事件=threading.Event(),
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
            点击已确认安全按钮=Mock(return_value=False),
        )
        任务 = 检测游戏登录状态任务(上下文)

        class 假引擎:
            def 执行匹配(self, _图像, 模板路径, **_参数):
                if "登录弹窗的确定" in 模板路径:
                    return True, (320, 400), 0.95
                return False, (0, 0), 0.0

        with patch("任务流程.检测游戏登录状态.模板匹配引擎", return_value=假引擎()), \
             patch("任务流程.检测游戏登录状态.页面识别器") as 页面识别器:
            页面识别器.return_value.识别.return_value = SimpleNamespace(页面="未知")
            任务._检测断线弹窗 = Mock(return_value=(False, (0, 0)))
            self.assertFalse(任务.执行(首次登录=False))

        self.assertTrue(上下文.页面恢复失败)
        self.assertEqual(上下文.脚本延时.call_count, 1)
        self.assertTrue(any("输入被拒绝" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

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

    def test_结算回营按钮紧邻暗色草地时仍可剥离定位(self):
        """周边暗色草地与按钮黑边在闭运算粘连时，仍能定位到实心绿色按钮。"""
        图像 = np.full((600, 800, 3), (30, 30, 30), dtype=np.uint8)
        cv2.rectangle(图像, (175, 130), (625, 255), (30, 185, 235), -1)
        # 暗色背景草地 (BGR=(40,115,45), HSV V=115) 紧挨按钮边缘 1~2px，
        # 模拟 071950 / 081054 中 (7,5) 闭运算把草地粘连成超高连通域的场景。
        cv2.rectangle(图像, (360, 456), (440, 487), (40, 115, 45), -1)
        cv2.rectangle(图像, (455, 478), (496, 526), (40, 115, 45), -1)
        cv2.rectangle(图像, (349, 489), (453, 547), (70, 225, 100), -1)

        识别器 = 页面识别器(Mock())
        识别器._最佳分数 = Mock(return_value=0.0)
        点 = 识别器.定位结算回营按钮(图像)
        self.assertIsNotNone(点)
        self.assertAlmostEqual(点[0], 401, delta=4)
        self.assertAlmostEqual(点[1], 518, delta=4)
        结果 = 识别器.识别(图像, 战斗中=False)
        self.assertEqual(结果.页面, "战斗结算", 结果.摘要())
        self.assertGreaterEqual(结果.可信度, 0.94)

    def test_结算兜底确认主世界后仍保留页面识别战斗结算结果(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        识别器 = 页面识别器(Mock())
        识别器._最佳分数 = Mock(return_value=0.0)
        识别器._红色放弃按钮分数 = Mock(return_value=0.0)
        识别器._战斗倒计时分数 = Mock(return_value=0.0)
        识别器._奖励选择横幅分数 = Mock(return_value=0.0)
        识别器._结算结果视觉分数 = Mock(return_value=0.96)
        识别器.世界识别 = SimpleNamespace(
            识别=Mock(
                return_value=SimpleNamespace(
                    当前世界="主世界",
                    依据=("结算页主世界三栏资源栏0.92", "结算页回营结构"),
                )
            )
        )

        结果 = 识别器.识别(图像, 战斗中=False)
        self.assertEqual(结果.页面, "战斗结算", 结果.摘要())
        self.assertGreaterEqual(结果.可信度, 0.96)

    def test_主页绿色控件与宝石商店按钮不触发结算回营按钮(self):
        # 1) 主页草地/底部绿色控件但无结算横幅/遮罩
        主页伪按钮 = np.full((600, 800, 3), (55, 125, 65), dtype=np.uint8)
        cv2.rectangle(主页伪按钮, (349, 489), (453, 547), (70, 225, 100), -1)
        self.assertIsNone(self.识别器.定位结算回营按钮(主页伪按钮))

        # 2) 宝石/商店对话框（哥布林宝石按钮或右下购买按钮）
        宝石弹窗 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(宝石弹窗, (365, 100), (740, 412), (220, 220, 220), -1)
        cv2.rectangle(宝石弹窗, (700, 108), (730, 150), (20, 20, 210), -1)
        cv2.rectangle(宝石弹窗, (490, 326), (613, 398), (60, 210, 80), -1)
        self.assertIsNone(self.识别器.定位结算回营按钮(宝石弹窗))

        商店绿按钮 = np.full((600, 800, 3), (45, 45, 50), dtype=np.uint8)
        cv2.rectangle(商店绿按钮, (150, 120), (650, 440), (210, 205, 195), -1)
        cv2.rectangle(商店绿按钮, (349, 489), (453, 547), (70, 225, 100), -1)
        self.assertIsNone(self.识别器.定位结算回营按钮(商店绿按钮))

    def test_战斗兵栏与夜世界无按钮过渡页不触发结算回营按钮(self):
        # 1) 战斗中兵栏绿色卡槽 + 放弃/倒计时
        战斗兵栏 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(战斗兵栏, (10, 430), (105, 470), (0, 0, 220), -1)
        for x in range(180, 620, 72):
            cv2.rectangle(战斗兵栏, (x, 495), (x + 56, 585), (70, 220, 100), -1)
        self.assertIsNone(self.识别器.定位结算回营按钮(战斗兵栏))

        # 2) 夜世界无回营按钮的过渡页
        夜世界无按钮 = np.full((600, 800, 3), (18, 25, 42), dtype=np.uint8)
        for 中心 in ((275, 175), (400, 175), (525, 175)):
            cv2.circle(夜世界无按钮, 中心, 28, (235, 235, 235), -1)
        cv2.putText(
            夜世界无按钮, "0%", (350, 335), cv2.FONT_HERSHEY_SIMPLEX,
            1.8, (255, 255, 255), 4, cv2.LINE_AA,
        )
        self.assertIsNone(self.识别器.定位结算回营按钮(夜世界无按钮))

    @staticmethod
    def _读取宝箱领奖实机图():
        路径 = (
            pathlib.Path(__file__).resolve().parent
            / "fixtures"
            / "奖励宝箱"
            / "live_reward_screen_1280x720.png"
        )
        数据 = np.fromfile(str(路径), dtype=np.uint8)
        图 = cv2.imdecode(数据, cv2.IMREAD_COLOR)
        if 图 is None:
            raise AssertionError(f"无法读取测试截图: {路径}")
        return cv2.resize(图, (800, 600), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _读取主世界实机图():
        路径 = (
            pathlib.Path(__file__).resolve().parent
            / "fixtures"
            / "coc_home_18_647_5.png"
        )
        数据 = np.fromfile(str(路径), dtype=np.uint8)
        图 = cv2.imdecode(数据, cv2.IMREAD_COLOR)
        if 图 is None:
            raise AssertionError(f"无法读取测试截图: {路径}")
        return 图

    def test_宝箱领奖页安全清理_正例与连续多页收起(self):
        领奖图 = self._读取宝箱领奖实机图()
        主页图 = self._读取主世界实机图()
        画面序列 = [领奖图, 领奖图, 主页图]
        点击记录 = []

        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文._内存保护已触发 = False
        上下文._宝箱领奖连续点击次数 = 0
        上下文.页面恢复失败 = False
        上下文.停止事件 = threading.Event()
        上下文._获取点击页面识别器 = lambda: self.识别器
        上下文.获取模板识别器 = lambda: self.引擎
        上下文.获取OCR引擎 = lambda: lambda _图: (
            [([[360, 500], [420, 500], [420, 530], [360, 530]], "繼續", 0.96)],
            None,
        )
        上下文.脚本延时 = Mock()
        上下文.置脚本状态 = Mock()
        上下文.op = SimpleNamespace(
            获取屏幕图像cv=lambda *_a, **_k: 画面序列[0]
        )

        def _点击(x, y, 延时=0):
            点击记录.append((x, y))
            if len(画面序列) > 1:
                画面序列.pop(0)
            return True

        上下文.点击已确认安全按钮 = _点击

        self.assertTrue(上下文.清理宝箱领奖页(领奖图))
        self.assertEqual(点击记录, [(392, 515), (392, 515)])
        self.assertEqual(上下文._宝箱领奖连续点击次数, 0)
        self.assertFalse(上下文.页面恢复失败)

    def test_宝箱领奖页安全清理_拒绝危险词缺继续宝石模板与点击上限(self):
        领奖图 = self._读取宝箱领奖实机图()

        # 1) OCR 含危险词（寶石/購買/商店/立即完成）→ 严禁点击
        for 危险词 in ("寶石", "購買", "商店", "立即完成"):
            with self.subTest(危险词=危险词):
                上下文 = 任务上下文.__new__(任务上下文)
                上下文._战斗中 = False
                上下文._内存保护已触发 = False
                上下文._宝箱领奖连续点击次数 = 0
                上下文.页面恢复失败 = False
                上下文.停止事件 = threading.Event()
                上下文._获取点击页面识别器 = lambda: self.识别器
                上下文.获取模板识别器 = lambda: self.引擎
                上下文.获取OCR引擎 = lambda: lambda _图, 词=危险词: (
                    [
                        ([[360, 500], [420, 500], [420, 530], [360, 530]], "繼續", 0.96),
                        ([[340, 260], [460, 290], [460, 310], [340, 310]], f"花費50{词}", 0.95),
                    ],
                    None,
                )
                上下文.点击已确认安全按钮 = Mock(return_value=True)
                上下文.脚本延时 = Mock()
                上下文.置脚本状态 = Mock()
                上下文.op = SimpleNamespace(获取屏幕图像cv=Mock(return_value=领奖图))

                self.assertFalse(上下文.清理宝箱领奖页(领奖图))
                上下文.点击已确认安全按钮.assert_not_called()
                self.assertTrue(上下文.页面恢复失败)

        # 2) OCR 缺少底部居中“继续/繼續” → 不盲点
        上下文无继续 = 任务上下文.__new__(任务上下文)
        上下文无继续._战斗中 = False
        上下文无继续._内存保护已触发 = False
        上下文无继续._宝箱领奖连续点击次数 = 0
        上下文无继续.页面恢复失败 = False
        上下文无继续.停止事件 = threading.Event()
        上下文无继续._获取点击页面识别器 = lambda: self.识别器
        上下文无继续.获取模板识别器 = lambda: self.引擎
        上下文无继续.获取OCR引擎 = lambda: lambda _图: (
            [([[300, 380], [500, 380], [500, 410], [300, 410]], "2倍戰鬥糕點", 0.95)],
            None,
        )
        上下文无继续.点击已确认安全按钮 = Mock(return_value=True)
        上下文无继续.脚本延时 = Mock()
        上下文无继续.置脚本状态 = Mock()
        上下文无继续.op = SimpleNamespace(获取屏幕图像cv=Mock(return_value=领奖图))
        self.assertFalse(上下文无继续.清理宝箱领奖页(领奖图))
        上下文无继续.点击已确认安全按钮.assert_not_called()
        self.assertTrue(上下文无继续.页面恢复失败)

        # 3) 中央宝石模板命中 → 严禁点击并触发宝石保护
        上下文宝石 = 任务上下文.__new__(任务上下文)
        上下文宝石._战斗中 = False
        上下文宝石._内存保护已触发 = False
        上下文宝石._宝箱领奖连续点击次数 = 0
        上下文宝石.页面恢复失败 = False
        上下文宝石._宝石保护已触发 = False
        上下文宝石.停止事件 = threading.Event()
        上下文宝石._获取点击页面识别器 = lambda: self.识别器
        上下文宝石._存在中央宝石危险模板 = Mock(return_value=(True, "宝石.bmp、宝石1.bmp@390,280"))
        上下文宝石.获取OCR引擎 = Mock()
        上下文宝石.点击已确认安全按钮 = Mock(return_value=True)
        上下文宝石.脚本延时 = Mock()
        上下文宝石.置脚本状态 = Mock()
        上下文宝石.op = SimpleNamespace(获取屏幕图像cv=Mock(return_value=领奖图))
        self.assertFalse(上下文宝石.清理宝箱领奖页(领奖图))
        上下文宝石.点击已确认安全按钮.assert_not_called()
        上下文宝石.获取OCR引擎.assert_not_called()
        self.assertTrue(上下文宝石.页面恢复失败)
        self.assertTrue(上下文宝石._宝石保护已触发)

        # 4) 达到点击上限 3 次后拒绝继续点击
        上下文上限 = 任务上下文.__new__(任务上下文)
        上下文上限._战斗中 = False
        上下文上限._内存保护已触发 = False
        上下文上限._宝箱领奖连续点击次数 = 0
        上下文上限.页面恢复失败 = False
        上下文上限.停止事件 = threading.Event()
        上下文上限._获取点击页面识别器 = lambda: self.识别器
        上下文上限.获取模板识别器 = lambda: self.引擎
        上下文上限.获取OCR引擎 = lambda: lambda _图: (
            [([[360, 500], [420, 500], [420, 530], [360, 530]], "繼續", 0.96)],
            None,
        )
        上下文上限.点击已确认安全按钮 = Mock(return_value=True)
        上下文上限.脚本延时 = Mock()
        上下文上限.置脚本状态 = Mock()
        上下文上限.op = SimpleNamespace(获取屏幕图像cv=Mock(return_value=领奖图))
        self.assertFalse(上下文上限.清理宝箱领奖页(领奖图))
        self.assertEqual(上下文上限.点击已确认安全按钮.call_count, 3)
        self.assertTrue(上下文上限.页面恢复失败)
        # 再次调用直接拒绝
        self.assertFalse(上下文上限.清理宝箱领奖页(领奖图))
        self.assertEqual(上下文上限.点击已确认安全按钮.call_count, 3)

    def test_宝箱领奖页在安全护栏_登录_进攻与待命链路安全处理(self):
        领奖图 = self._读取宝箱领奖实机图()
        主页图 = self._读取主世界实机图()

        # 1) 输入前安全检查拦截宝箱领奖页并清理
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文._点击识别截图 = 领奖图
        上下文.检查宝石商店危险页面 = Mock(return_value=False)
        上下文._最近点击页面结果 = SimpleNamespace(页面="宝箱领奖页")
        上下文.清理宝箱领奖页 = Mock(return_value=True)
        self.assertTrue(上下文.输入前安全检查())
        上下文.清理宝箱领奖页.assert_called_once_with(领奖图)

        # 2) 登录检测任务遇到宝箱领奖页先安全收起再继续确认主页
        登录上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(side_effect=[领奖图, 主页图, 主页图]),
                设备=SimpleNamespace(
                    获取当前前台包名=Mock(return_value="com.supercell.clashofclans")
                ),
            ),
            设置=SimpleNamespace(部落冲突包名="com.supercell.clashofclans"),
            数据库=Mock(),
            机器人标志="robot_test",
            停止事件=threading.Event(),
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
            清理宝箱领奖页=Mock(return_value=True),
        )
        登录任务 = 检测游戏登录状态任务(登录上下文)
        登录任务.第一次检测游戏登录 = False
        登录任务._检测断线弹窗 = Mock(return_value=(False, (0, 0)))
        登录任务._登录主页已确认 = Mock(return_value=True)
        def _匹配登录模板(_图像, 模板路径, **_参数):
            命中 = "家乡进攻图标" in 模板路径 or "不用拉远视距" in 模板路径
            return 命中, (100, 100), 0.95 if 命中 else 0.0

        with patch("任务流程.检测游戏登录状态.模板匹配引擎") as 模板类, \
             patch("任务流程.检测游戏登录状态.页面识别器", return_value=self.识别器):
            模板类.return_value.执行匹配.side_effect = _匹配登录模板
            self.assertTrue(登录任务.执行(首次登录=False))
        登录上下文.清理宝箱领奖页.assert_called_once()

        # 3) 打开进攻页面识别到宝箱领奖页并尝试安全收起；失败则阻止打开进攻页
        from 任务流程.主世界打鱼.打开进攻页面 import 打开进攻页面任务
        进攻上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=领奖图)),
            数据库=Mock(),
            机器人标志="robot_test",
            获取模板识别器=lambda: self.引擎,
            _获取点击页面识别器=lambda: self.识别器,
            _战斗中=False,
            识别点击画面=Mock(return_value=SimpleNamespace(页面="宝箱领奖页", 世界=None, 可信度=0.96)),
            清理宝箱领奖页=Mock(return_value=False),
            停止事件=threading.Event(),
            置脚本状态=Mock(),
        )
        进攻任务 = 打开进攻页面任务(进攻上下文)
        self.assertEqual(进攻任务._识别已存在的战斗页面(进攻上下文, 强制=True), "宝箱领奖页")
        self.assertFalse(进攻任务.执行())
        进攻上下文.清理宝箱领奖页.assert_called_once()

        # 4) 自动化机器人._安全待命单次 遇到宝箱领奖页能安全收起并在双帧主页后恢复
        from 线程.自动化机器人 import 自动化机器人
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.停止事件 = Mock()
        机器人.停止事件.is_set.return_value = False
        机器人.停止事件.wait.return_value = False
        机器人.继续事件 = threading.Event()
        机器人.继续事件.set()
        机器人.停止原因 = None
        机器人.数据库 = None
        机器人.记录日志 = Mock()
        页面序列 = iter([
            SimpleNamespace(页面="宝箱领奖页", 世界=None, 可信度=0.96),
            SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.95),
            SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.95),
        ])
        待命上下文 = SimpleNamespace(
            设置=SimpleNamespace(未知页面待命通知秒数=180),
            停止事件=机器人.停止事件,
            页面恢复失败=True,
            _宝箱领奖连续点击次数=0,
            _宝石保护已触发=False,
            _战斗中=False,
            _战斗结束已确认=False,
            _最近点击页面结果=SimpleNamespace(页面="宝箱领奖页"),
            识别点击画面=Mock(side_effect=lambda 强制=True: next(页面序列)),
            清理宝箱领奖页=Mock(return_value=True),
            置脚本状态=Mock(),
        )
        with patch("线程.自动化机器人.检测游戏登录状态任务"):
            self.assertTrue(机器人._安全待命单次(待命上下文, "主世界"))
        待命上下文.清理宝箱领奖页.assert_called_once()
        self.assertEqual(待命上下文.识别点击画面.call_count, 3)

    def test_宝箱领奖页清理_OCR期间触发停止事件立即中止且不点击(self):
        领奖图 = self._读取宝箱领奖实机图()
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文._内存保护已触发 = False
        上下文._宝箱领奖连续点击次数 = 0
        上下文.页面恢复失败 = False
        上下文.停止事件 = threading.Event()
        上下文._获取点击页面识别器 = lambda: self.识别器
        上下文.获取模板识别器 = lambda: self.引擎

        def _OCR并停止(_图):
            上下文.停止事件.set()
            return (
                [([[360, 500], [420, 500], [420, 530], [360, 530]], "繼續", 0.96)],
                None,
            )

        上下文.获取OCR引擎 = lambda: _OCR并停止
        上下文.点击已确认安全按钮 = Mock(return_value=True)
        上下文.脚本延时 = Mock()
        上下文.置脚本状态 = Mock()
        上下文.op = SimpleNamespace(获取屏幕图像cv=Mock(return_value=领奖图))

        self.assertFalse(上下文.清理宝箱领奖页(领奖图))
        self.assertEqual(上下文._宝箱领奖连续点击次数, 0)
        上下文.点击已确认安全按钮.assert_not_called()

    def test_宝箱领奖页清理_复核循环入口响应停止事件立即中止(self):
        领奖图 = self._读取宝箱领奖实机图()
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文._内存保护已触发 = False
        上下文._宝箱领奖连续点击次数 = 0
        上下文.页面恢复失败 = False
        上下文.停止事件 = threading.Event()
        上下文._获取点击页面识别器 = lambda: self.识别器
        上下文.获取模板识别器 = lambda: self.引擎
        上下文.获取OCR引擎 = lambda: lambda _图: (
            [([[360, 500], [420, 500], [420, 530], [360, 530]], "繼續", 0.96)],
            None,
        )

        def _点击后停止(_x, _y, 延时=0):
            上下文.停止事件.set()
            return True

        上下文.点击已确认安全按钮 = Mock(side_effect=_点击后停止)
        上下文.脚本延时 = Mock()
        上下文.置脚本状态 = Mock()
        上下文.op = SimpleNamespace(获取屏幕图像cv=Mock(return_value=领奖图))

        self.assertFalse(上下文.清理宝箱领奖页(领奖图))
        上下文.点击已确认安全按钮.assert_called_once()
        上下文.脚本延时.assert_not_called()
        上下文.op.获取屏幕图像cv.assert_not_called()

    def test_点击已确认安全按钮_停止事件已置位时不移动也不点击(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.停止事件 = threading.Event()
        上下文.停止事件.set()
        上下文.置脚本状态 = Mock()
        上下文.脚本延时 = Mock()
        原回调 = Mock()
        上下文.鼠标 = SimpleNamespace(
            移动到=Mock(),
            左键点击=Mock(return_value=True),
            _安全点击检查回调=原回调,
        )

        self.assertFalse(上下文.点击已确认安全按钮(392, 515, 延时=450))
        上下文.鼠标.移动到.assert_not_called()
        上下文.鼠标.左键点击.assert_not_called()
        上下文.脚本延时.assert_not_called()
        self.assertIs(上下文.鼠标._安全点击检查回调, 原回调)


if __name__ == "__main__":
    unittest.main()
