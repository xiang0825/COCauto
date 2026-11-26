"""暗黑高级感 UI 组件套件 offscreen 单元测试。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QAbstractAnimation, QEventLoop, QPoint, QRect, Qt, QTimer
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPixmap
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QWidget
except ImportError:  # pragma: no cover
    QApplication = None


def _处理事件(毫秒: int = 20) -> None:
    应用 = QApplication.instance()
    if 应用 is None:
        return
    循环 = QEventLoop()
    QTimer.singleShot(毫秒, 循环.quit)
    循环.exec()


@unittest.skipIf(QApplication is None, "未安装 PySide6")
class 高级UI组件测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.应用 = QApplication.instance() or QApplication([])

    # ---------------------------------------------------------------- 开机动画
    def test_开机动画进度阶段与平滑淡出显示主窗(self):
        from 界面.启动动画 import 卡片背景色, 高级启动画面

        self.assertEqual(卡片背景色, "#111318")
        启动窗 = 高级启动画面(标题="城控", 副标题="部落冲突控制台", 版本号="v2.0")
        主窗 = QWidget()
        主窗.resize(320, 200)
        try:
            self.assertTrue(bool(启动窗.windowFlags() & Qt.FramelessWindowHint))
            self.assertTrue(启动窗.testAttribute(Qt.WA_TranslucentBackground))

            启动窗.show()
            self.应用.processEvents()
            self.assertEqual(启动窗._入场动画.duration(), 420)
            self.assertGreaterEqual(启动窗.推荐最小展示毫秒, 800)
            self.assertLessEqual(启动窗.推荐最大展示毫秒, 1300)

            for 进度, 阶段 in (
                (15, "校验单实例"),
                (45, "归档上次日志"),
                (75, "探测模拟器"),
                (100, "就绪"),
            ):
                启动窗.更新进度(进度, 阶段)
                self.assertEqual(启动窗.进度, 进度)
                self.assertEqual(启动窗.阶段文案, 阶段)

            # 越界百分比自动钳位
            启动窗.更新进度(-20)
            self.assertEqual(启动窗.进度, 0)
            启动窗.更新进度(150)
            self.assertEqual(启动窗.进度, 100)

            # 触发 offscreen 绘制路径确保 QPainter 无异常
            快照 = 启动窗.grab()
            self.assertFalse(快照.isNull())

            完成标记 = []
            启动窗.淡出并显示主窗(主窗, 淡出毫秒=40, 完成回调=lambda: 完成标记.append(True))
            self.assertTrue(主窗.isVisible())
            _处理事件(120)
            self.assertTrue(完成标记)
            self.assertFalse(启动窗.isVisible())
        finally:
            启动窗.close()
            主窗.close()

    def test_开机动画零毫秒淡出直接切入主窗(self):
        from 界面.启动动画 import 高级启动画面

        启动窗 = 高级启动画面()
        主窗 = QWidget()
        try:
            启动窗.show()
            启动窗.淡出并显示主窗(主窗, 淡出毫秒=0)
            self.assertTrue(主窗.isVisible())
            self.assertFalse(启动窗.isVisible())
        finally:
            启动窗.close()
            主窗.close()

    # ---------------------------------------------------------------- 主题与 SVG 图标
    def test_暗黑主题样式表与高级配色常量(self):
        from 界面.高级主题 import (
            主底色,
            卡片底色,
            强调金,
            悬浮底色,
            异常红,
            生成高级暗黑样式表,
            运行绿,
            高级深色,
        )

        self.assertEqual(主底色, "#0F1115")
        self.assertEqual(卡片底色, "#161920")
        self.assertEqual(悬浮底色, "#1E222B")
        self.assertEqual(强调金, "#F59E0B")
        self.assertEqual(运行绿, "#22C55E")
        self.assertEqual(异常红, "#EF4444")
        self.assertEqual(高级深色.背景, "#0F1115")

        样式 = 生成高级暗黑样式表()
        for 片段 in (
            "#0F1115",
            "#161920",
            "#1E222B",
            "rgba(255, 255, 255, 0.08)",
            "#F59E0B",
            "QLabel#等宽数字",
            "QScrollBar:vertical",
            "QPushButton#主按钮",
        ):
            self.assertIn(片段, 样式)

        测试控件 = QWidget()
        try:
            测试控件.setStyleSheet(样式)
            测试控件.show()
            self.应用.processEvents()
        finally:
            测试控件.close()

    def test_内联矢量SVG图标覆盖全部分类且高DPI清晰(self):
        from 界面.高级主题 import 创建矢量图标, 支持图标名称, 强调金

        必需图标 = ("金币", "圣水", "黑油", "运行", "暂停", "设置", "战报", "截图", "日志")
        支持列表 = 支持图标名称()
        for 名称 in 必需图标:
            self.assertIn(名称, 支持列表)
            图标 = 创建矢量图标(名称, 颜色=强调金, 尺寸=20)
            self.assertFalse(图标.isNull(), f"图标 {名称} 不应为空")
            图 = 图标.pixmap(20, 20)
            self.assertFalse(图.isNull())
            self.assertGreaterEqual(图.width(), 20)
            # 确认不是全透明空画布
            图像 = 图.toImage()
            存在非透明像素 = any(
                图像.pixelColor(x, y).alpha() > 0
                for x in range(图像.width())
                for y in range(图像.height())
            )
            self.assertTrue(存在非透明像素, f"图标 {名称} 像素全透明")

        # 未知名称安全兜底不崩溃
        兜底图标 = 创建矢量图标("不存在的图标", 颜色="#FFFFFF", 尺寸=16)
        self.assertFalse(兜底图标.isNull())

    # ---------------------------------------------------------------- 微动效控件
    def test_呼吸状态指示灯按状态切换动画与颜色(self):
        from 界面.高级主题 import 呼吸状态指示灯, 强调金, 异常红, 文字弱色, 运行绿

        指示灯 = 呼吸状态指示灯("待机", 尺寸=16)
        try:
            指示灯.show()
            self.assertEqual(指示灯.当前颜色, QColor(文字弱色))
            self.assertNotEqual(指示灯._动画.state(), QAbstractAnimation.Running)

            指示灯.设置状态("运行中")
            self.assertEqual(指示灯.当前颜色, QColor(运行绿))
            self.assertEqual(指示灯._动画.duration(), 2000)
            self.assertEqual(指示灯._动画.state(), QAbstractAnimation.Running)
            self.assertFalse(指示灯.grab().isNull())

            指示灯.设置状态("暂停中")
            self.assertEqual(指示灯.当前颜色, QColor(强调金))
            self.assertNotEqual(指示灯._动画.state(), QAbstractAnimation.Running)

            指示灯.设置状态("异常")
            self.assertEqual(指示灯.当前颜色, QColor(异常红))
            self.assertNotEqual(指示灯._动画.state(), QAbstractAnimation.Running)
        finally:
            指示灯.close()

    def test_滑动开关状态切换信号与120ms过渡(self):
        from 界面.高级主题 import 滑动开关

        开关 = 滑动开关("自动捐兵", 选中=False)
        变化记录: list[bool] = []
        开关.toggled.connect(变化记录.append)
        try:
            开关.show()
            self.assertFalse(开关.isChecked())
            self.assertEqual(开关.滑块进度, 0.0)
            self.assertEqual(开关._动画.duration(), 120)

            开关.setChecked(True)
            self.assertTrue(开关.isChecked())
            self.assertEqual(变化记录, [True])
            _处理事件(160)
            self.assertAlmostEqual(开关.滑块进度, 1.0, places=2)

            开关.click()
            self.assertFalse(开关.isChecked())
            self.assertEqual(变化记录, [True, False])
            _处理事件(160)
            self.assertAlmostEqual(开关.滑块进度, 0.0, places=2)
            self.assertFalse(开关.grab().isNull())
        finally:
            开关.close()

    def test_日志胶囊标签按类别自动配色(self):
        from 界面.高级主题 import 日志胶囊标签, 支持日志类别

        self.assertEqual(支持日志类别, ("搜敌", "进攻", "竞赛", "保护", "异常", "系统"))
        胶囊 = 日志胶囊标签("搜敌")
        try:
            已见字色 = set()
            for 类别 in 支持日志类别:
                胶囊.设置类别(类别)
                self.assertEqual(胶囊.类别, 类别)
                self.assertEqual(胶囊.text(), 类别)
                字色, 底色, 描边 = 胶囊.配色方案()
                已见字色.add(字色)
                self.assertIn(底色, 胶囊.styleSheet())
                self.assertIn(描边, 胶囊.styleSheet())
            self.assertEqual(len(已见字色), len(支持日志类别))

            # 未知类别兜底到系统配色而不丢失文本
            胶囊.设置类别("自定义")
            self.assertEqual(胶囊.text(), "自定义")
            self.assertEqual(胶囊.配色方案(), 日志胶囊标签("系统").配色方案())
        finally:
            胶囊.close()

    # ---------------------------------------------------------------- 截图预览弹窗
    def test_现场截图预览弹窗支持合法图片与缺失损坏优雅降级(self):
        from 界面.高级主题 import 现场截图预览弹窗

        with tempfile.TemporaryDirectory() as 临时目录:
            目录 = Path(临时目录)
            合法图路径 = 目录 / "battle_fail.png"
            图像 = QImage(320, 180, QImage.Format_RGB32)
            图像.fill(QColor("#22C55E"))
            self.assertTrue(图像.save(str(合法图路径), "PNG"))

            弹窗 = 现场截图预览弹窗(
                合法图路径,
                标题="搜敌异常现场",
                时间文本="12:30:45",
                元数据={"实例": "robot_1", "阶段": "识图超时"},
            )
            try:
                弹窗.show()
                self.应用.processEvents()
                self.assertTrue(弹窗.等待加载())
                self.assertEqual(弹窗.错误提示, "")
                self.assertIn("320×180", 弹窗.元数据标签.text())
                self.assertIn("识图超时", 弹窗.元数据标签.text())

                弹窗.原始尺寸()
                self.assertAlmostEqual(弹窗.缩放比例, 1.0, places=2)
                弹窗.放大()
                self.assertGreater(弹窗.缩放比例, 1.0)
                弹窗.缩小()
                self.assertAlmostEqual(弹窗.缩放比例, 1.0, places=2)
                弹窗.适应窗口()
                self.assertEqual(弹窗.比例标签.text(), "适应")
            finally:
                弹窗.close()

            # 缺失文件优雅降级
            缺失弹窗 = 现场截图预览弹窗(目录 / "missing.png", 标题="缺失图")
            try:
                self.assertFalse(缺失弹窗.是否加载成功)
                self.assertIn("不存在", 缺失弹窗.错误提示)
                self.assertFalse(缺失弹窗.放大按钮.isEnabled())
                self.assertIn("不存在", 缺失弹窗.画布标签.text())
            finally:
                缺失弹窗.close()

            # 损坏文件优雅降级
            损坏路径 = 目录 / "corrupt.png"
            损坏路径.write_bytes(b"not-a-valid-png")
            损坏弹窗 = 现场截图预览弹窗(损坏路径, 标题="损坏图")
            try:
                self.assertFalse(损坏弹窗.等待加载())
                self.assertTrue(bool(损坏弹窗.错误提示))
                self.assertFalse(损坏弹窗.原寸按钮.isEnabled())
            finally:
                损坏弹窗.close()

    def test_现场截图在后台解码不阻塞界面(self):
        from unittest import mock

        from 界面.高级主题 import 现场截图预览弹窗

        with tempfile.TemporaryDirectory() as 临时目录:
            路径 = Path(临时目录) / "scene.png"
            图像 = QImage(64, 36, QImage.Format_RGB32)
            图像.fill(QColor("#334155"))
            self.assertTrue(图像.save(str(路径), "PNG"))
            with mock.patch("界面.高级主题.QImageReader", side_effect=AssertionError("界面线程解码")),                     mock.patch("界面.组件.后台执行") as 后台:
                弹窗 = 现场截图预览弹窗(路径)
            try:
                后台.assert_called_once()
                self.assertTrue(弹窗.加载中)
                self.assertFalse(弹窗.是否加载成功)
                self.assertIn("正在加载", 弹窗.画布标签.text())
                self.assertFalse(弹窗.放大按钮.isEnabled())
            finally:
                弹窗.close()
            # 关闭后才到的解码结果直接丢弃
            弹窗2 = 现场截图预览弹窗(路径)
            弹窗2.close()
            self.assertFalse(弹窗2.等待加载())
            self.assertFalse(弹窗2.加载中)

    # ---------------------------------------------------------------- 窗口几何记忆
    def test_窗口几何保存与恢复并校验屏幕边界(self):
        from 界面.高级主题 import 保存窗口几何, 恢复窗口几何

        with tempfile.TemporaryDirectory() as 临时目录:
            存储路径 = Path(临时目录) / "window_geo.json"
            窗口 = QWidget()
            窗口.setMinimumSize(300, 200)
            窗口.setGeometry(100, 90, 520, 360)
            try:
                self.assertTrue(保存窗口几何(窗口, 存储路径))
                self.assertTrue(存储路径.is_file())

                新窗口 = QWidget()
                新窗口.setMinimumSize(300, 200)
                try:
                    self.assertTrue(恢复窗口几何(新窗口, 存储路径))
                    屏幕 = QGuiApplication.primaryScreen().availableGeometry()
                    self.assertTrue(屏幕.contains(新窗口.geometry().topLeft()))
                    self.assertEqual(新窗口.width(), 520)
                    self.assertEqual(新窗口.height(), 360)

                    # 模拟外接屏断开导致保存坐标完全跑出屏幕外
                    存储路径.write_text(
                        json.dumps({"x": 99999, "y": 99999, "width": 600, "height": 400, "maximized": False}),
                        encoding="utf-8",
                    )
                    self.assertTrue(恢复窗口几何(新窗口, 存储路径))
                    self.assertTrue(屏幕.intersects(新窗口.geometry()))
                    self.assertTrue(屏幕.contains(新窗口.geometry().center()))

                    # 损坏 JSON 安全返回 False 且不删除文件
                    存储路径.write_text("{broken-json", encoding="utf-8")
                    self.assertFalse(恢复窗口几何(新窗口, 存储路径))
                    self.assertTrue(存储路径.is_file())
                    self.assertFalse(恢复窗口几何(新窗口, Path(临时目录) / "none.json"))
                finally:
                    新窗口.close()
            finally:
                窗口.close()

    # ---------------------------------------------------------------- 系统托盘
    def test_系统托盘在offscreen下安全降级且菜单回调正常(self):
        from 界面.系统托盘 import 系统托盘控制器

        主窗 = QWidget()
        主窗.唤醒 = mock.Mock()
        显隐次数 = []
        启停次数 = []
        退出次数 = []

        控制器 = 系统托盘控制器(
            主窗口=主窗,
            显示隐藏回调=lambda: 显隐次数.append(1),
            开始暂停回调=lambda: 启停次数.append(1),
            退出回调=lambda: 退出次数.append(1),
        )
        try:
            self.assertFalse(控制器.是否可用)
            self.assertFalse(控制器.显示())
            self.assertFalse(控制器.发送提示("标题", "内容"))
            控制器.更新运行状态("运行中", "今日 8 场 · 金币 520万")
            self.assertIn("运行中", 控制器.概览动作.text())
            self.assertIn("520万", 控制器.概览动作.text())
            self.assertFalse(控制器.概览动作.isEnabled())
            self.assertEqual(控制器.启停动作.text(), "暂停运行")

            控制器.更新运行状态("暂停中", "已暂停")
            self.assertEqual(控制器.启停动作.text(), "继续运行")

            控制器.更新运行状态("已停止", "待命")
            self.assertEqual(控制器.启停动作.text(), "开始运行")

            控制器.显隐动作.trigger()
            控制器.启停动作.trigger()
            控制器.退出动作.trigger()
            self.assertEqual(len(显隐次数), 1)
            self.assertEqual(len(启停次数), 1)
            self.assertEqual(len(退出次数), 1)

            # 激活信号唤起主窗
            控制器._处理激活(QSystemTrayIcon.DoubleClick)
            主窗.唤醒.assert_called_once()
        finally:
            控制器.关闭()
            主窗.close()

    def test_系统托盘在支持环境下可创建并响应单击双击(self):
        from 界面.系统托盘 import 系统托盘控制器

        主窗 = QWidget()
        主窗.唤醒 = mock.Mock()
        假托盘实例 = mock.MagicMock()
        假托盘实例.activated = mock.MagicMock()

        with (
            mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": "windows"}),
            mock.patch("界面.系统托盘.QSystemTrayIcon") as 托盘类,
        ):
            托盘类.isSystemTrayAvailable.return_value = True
            托盘类.Trigger = QSystemTrayIcon.Trigger
            托盘类.DoubleClick = QSystemTrayIcon.DoubleClick
            托盘类.Information = QSystemTrayIcon.Information
            托盘类.return_value = 假托盘实例

            控制器 = 系统托盘控制器(主窗口=主窗)
            try:
                self.assertTrue(控制器.是否可用)
                托盘类.assert_called_once()
                self.assertTrue(控制器.显示())
                假托盘实例.show.assert_called_once()

                控制器.更新运行状态("运行中", "今日 3 场")
                假托盘实例.setToolTip.assert_called()
                self.assertTrue(控制器.发送提示("任务完成", "已收获资源"))
                假托盘实例.showMessage.assert_called_once()

                控制器._处理激活(QSystemTrayIcon.Trigger)
                主窗.唤醒.assert_called_once()
            finally:
                控制器.关闭()
                假托盘实例.hide.assert_called()
                主窗.close()


if __name__ == "__main__":
    unittest.main()
