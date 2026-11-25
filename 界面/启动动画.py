"""暗黑极简微光开机动画：无边框圆角悬浮卡片 + 微缩淡入 + 暖金斜光扫过 + 2px 光带进度。"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

卡片背景色 = "#111318"
卡片描边Alpha = 20  # rgba(255, 255, 255, 0.08)
暖金主色 = "#F59E0B"


class 高级启动画面(QWidget):
    """暗黑极简微光开机启动卡片（纯原生 QPainter + QVariantAnimation，零外部依赖）。"""

    推荐最小展示毫秒 = 800
    推荐最大展示毫秒 = 1300
    默认淡出毫秒 = 240

    def __init__(
        self,
        标题: str = "城控",
        副标题: str = "部落冲突控制台",
        版本号: str = "",
        父: QWidget | None = None,
    ):
        super().__init__(父)
        self._标题 = 标题
        self._副标题 = 副标题
        self._版本号 = str(版本号 or "").strip()

        self._目标进度 = 0
        self._显示进度 = 0.0
        self._阶段文案 = "正在初始化…"
        self._入场进度 = 0.0
        self._扫光位置 = -0.35
        self._淡出中 = False
        self._动画已启动 = False

        self._阴影边距 = 22
        self._卡片宽 = 420
        self._卡片高 = 236
        self.setFixedSize(
            self._卡片宽 + self._阴影边距 * 2,
            self._卡片高 + self._阴影边距 * 2,
        )

        self.setWindowFlags(
            Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        # 1. Logo / 标题微缩淡入：0.92 -> 1.0 (OutCubic)
        self._入场动画 = QVariantAnimation(self)
        self._入场动画.setStartValue(0.0)
        self._入场动画.setEndValue(1.0)
        self._入场动画.setDuration(420)
        self._入场动画.setEasingCurve(QEasingCurve.OutCubic)
        self._入场动画.valueChanged.connect(self._更新入场)

        # 2. 低饱和暖金色斜光扫过动画
        self._扫光动画 = QVariantAnimation(self)
        self._扫光动画.setStartValue(-0.35)
        self._扫光动画.setEndValue(1.35)
        self._扫光动画.setDuration(880)
        self._扫光动画.setEasingCurve(QEasingCurve.InOutSine)
        self._扫光动画.valueChanged.connect(self._更新扫光)

        # 3. 2px 进度光带平滑过渡
        self._进度动画 = QVariantAnimation(self)
        self._进度动画.setDuration(110)
        self._进度动画.setEasingCurve(QEasingCurve.OutCubic)
        self._进度动画.valueChanged.connect(self._更新显示进度)

        # 4. 淡出动画
        self._淡出主窗: QWidget | None = None
        self._淡出完成回调: Callable[[], None] | None = None
        self._淡出动画 = QPropertyAnimation(self, b"windowOpacity", self)
        self._淡出动画.setEasingCurve(QEasingCurve.OutCubic)
        self._淡出动画.finished.connect(self._执行淡出收尾)

        if 父 is None:
            self._居中到屏幕()

    def _居中到屏幕(self) -> None:
        屏幕 = QGuiApplication.primaryScreen()
        if 屏幕 is None:
            return
        可用区 = 屏幕.availableGeometry()
        if 可用区.isValid():
            self.move(
                可用区.center().x() - self.width() // 2,
                可用区.center().y() - self.height() // 2,
            )

    @property
    def 进度(self) -> int:
        return self._目标进度

    @property
    def 阶段文案(self) -> str:
        return self._阶段文案

    def 启动动画(self) -> None:
        """显式启动微缩淡入与斜光扫过动画（showEvent 时会自动触发）。"""
        if self._动画已启动:
            return
        self._动画已启动 = True
        self._入场动画.start()
        self._扫光动画.start()

    def _更新入场(self, 值: float) -> None:
        self._入场进度 = float(值)
        self.update()

    def _更新扫光(self, 值: float) -> None:
        self._扫光位置 = float(值)
        self.update()

    def _更新显示进度(self, 值: float) -> None:
        self._显示进度 = float(值)
        self.update()

    def showEvent(self, 事件) -> None:
        super().showEvent(事件)
        self.启动动画()

    def closeEvent(self, 事件) -> None:
        for 动画 in (self._入场动画, self._扫光动画, self._进度动画, self._淡出动画):
            if 动画.state() == QAbstractAnimation.Running:
                动画.stop()
        super().closeEvent(事件)

    def 更新进度(self, 百分比: int, 阶段文案: str | None = None) -> None:
        """实时更新 2px 进度光带与等宽小字阶段文案。"""
        目标 = max(0, min(100, int(百分比)))
        self._目标进度 = 目标
        if 阶段文案 is not None:
            self._阶段文案 = str(阶段文案)

        if not self.isVisible():
            self._显示进度 = float(目标)
        else:
            self._进度动画.stop()
            self._进度动画.setStartValue(self._显示进度)
            self._进度动画.setEndValue(float(目标))
            self._进度动画.start()
        self.update()

    def _执行淡出收尾(self) -> None:
        主窗 = self._淡出主窗
        回调 = self._淡出完成回调
        self._淡出主窗 = None
        self._淡出完成回调 = None
        self.close()
        if 主窗 is not None:
            主窗.raise_()
            主窗.activateWindow()
        if 回调 is not None:
            回调()

    def 淡出并显示主窗(
        self,
        主窗口: QWidget | None,
        淡出毫秒: int = 默认淡出毫秒,
        完成回调: Callable[[], None] | None = None,
    ) -> None:
        """平滑溶解切入主窗，无闪烁、不阻塞启动流程。"""
        if self._淡出中:
            return
        self._淡出中 = True
        self._淡出主窗 = 主窗口
        self._淡出完成回调 = 完成回调

        # 先在底层显示主窗口，再溶解启动卡，避免窗口切换出现闪烁黑帧/白帧。
        if 主窗口 is not None:
            主窗口.show()

        时长 = max(0, int(淡出毫秒))
        if 时长 == 0 or not self.isVisible():
            self.setWindowOpacity(0.0)
            self._执行淡出收尾()
            return

        self._淡出动画.stop()
        self._淡出动画.setDuration(时长)
        self._淡出动画.setStartValue(float(self.windowOpacity()))
        self._淡出动画.setEndValue(0.0)
        self._淡出动画.start()

    # ================================================================ 绘制
    def _绘制柔和投影(self, 画笔: QPainter, 卡片区域: QRectF) -> None:
        层数 = 7
        for i in range(层数, 0, -1):
            扩张 = i * 2.2
            透明度 = int(28 * (1.0 - (i - 1) / 层数) ** 1.4)
            阴影区 = 卡片区域.adjusted(-扩张, -扩张 + 3.0, 扩张,扩张 + 3.0)
            画笔.setPen(Qt.NoPen)
            画笔.setBrush(QColor(0, 0, 0, 透明度))
            画笔.drawRoundedRect(阴影区, 18.0 + 扩张 * 0.4, 18.0 + 扩张 * 0.4)

    def _绘制品牌徽章(self, 画笔: QPainter, 左: float, 顶: float, 边长: float) -> None:
        比 = 边长 / 64.0
        画笔.save()
        画笔.translate(左, 顶)

        徽章底 = QRectF(1 * 比, 1 * 比, 62 * 比, 62 * 比)
        画笔.setPen(QPen(QColor(245, 158, 11, 88), 1.2))
        画笔.setBrush(QColor("#1A1E28"))
        画笔.drawRoundedRect(徽章底, 16 * 比, 16 * 比)

        路径 = QPainterPath()
        点 = [
            (16, 46), (16, 24), (23, 24), (23, 18), (30, 18), (30, 24),
            (36, 24), (36, 18), (43, 18), (43, 24), (49, 24), (49, 46),
        ]
        路径.moveTo(QPointF(点[0][0] * 比, 点[0][1] * 比))
        for x, y in 点[1:]:
            路径.lineTo(QPointF(x * 比, y * 比))
        路径.closeSubpath()

        画笔.setPen(Qt.NoPen)
        画笔.setBrush(QColor(暖金主色))
        画笔.drawPath(路径)

        画笔.setBrush(QColor("#1A1E28"))
        画笔.drawRect(QRectF(28.5 * 比, 33.5 * 比, 8 * 比, 12.5 * 比))
        画笔.setPen(QPen(QColor("#FBBF24"), max(1.0, 1.8 * 比)))
        画笔.drawLine(QPointF(15 * 比, 47.5 * 比), QPointF(50 * 比, 47.5 * 比))
        画笔.restore()

    def paintEvent(self, _事件) -> None:
        画笔 = QPainter(self)
        画笔.setRenderHint(QPainter.Antialiasing)
        画笔.setRenderHint(QPainter.TextAntialiasing)

        边距 = float(self._阴影边距)
        卡片区域 = QRectF(边距, 边距, float(self._卡片宽), float(self._卡片高))

        # 1. 柔和投影
        self._绘制柔和投影(画笔, 卡片区域)

        # 2. 深炭灰圆角卡片底 + 顶部微弱环境光 + 1px 亮描边
        裁剪路径 = QPainterPath()
        裁剪路径.addRoundedRect(卡片区域, 16.0, 16.0)

        画笔.save()
        画笔.setClipPath(裁剪路径)
        画笔.fillRect(卡片区域, QColor(卡片背景色))

        顶光中心 = QPointF(卡片区域.center().x(), 卡片区域.top() + 26.0)
        顶光 = QRadialGradient(顶光中心, 卡片区域.width() * 0.56)
        顶光.setColorAt(0.0, QColor(245, 158, 11, 22))
        顶光.setColorAt(0.55, QColor(245, 158, 11, 6))
        顶光.setColorAt(1.0, QColor(245, 158, 11, 0))
        画笔.fillRect(卡片区域, 顶光)

        # 3. 低饱和暖金色斜光扫过
        扫光中心x = 卡片区域.left() + 卡片区域.width() * self._扫光位置
        斜光 = QLinearGradient(
            QPointF(扫光中心x - 110.0, 卡片区域.top()),
            QPointF(扫光中心x + 110.0, 卡片区域.bottom()),
        )
        斜光.setColorAt(0.0, QColor(245, 196, 108, 0))
        斜光.setColorAt(0.45, QColor(245, 196, 108, 18))
        斜光.setColorAt(0.50, QColor(253, 224, 150, 28))
        斜光.setColorAt(0.55, QColor(245, 196, 108, 18))
        斜光.setColorAt(1.0, QColor(245, 196, 108, 0))
        画笔.fillRect(卡片区域, 斜光)

        # 4. 居中 Logo + 标题微缩淡入（0.92 -> 1.0）
        入场 = self._入场进度 if self._动画已启动 else 1.0
        缩放 = 0.92 + 0.08 * 入场
        中心区域中心 = QPointF(卡片区域.center().x(), 卡片区域.top() + 94.0)

        画笔.save()
        画笔.setOpacity(max(0.0, min(1.0, 入场)))
        画笔.translate(中心区域中心)
        画笔.scale(缩放, 缩放)
        画笔.translate(-中心区域中心)

        徽章边长 = 46.0
        self._绘制品牌徽章(
            画笔,
            卡片区域.center().x() - 徽章边长 / 2.0,
            卡片区域.top() + 42.0,
            徽章边长,
        )

        标题字 = QFont("Microsoft YaHei UI", 18)
        标题字.setBold(True)
        画笔.setFont(标题字)
        画笔.setPen(QColor("#F3F4F6"))
        标题区 = QRectF(卡片区域.left() + 24.0, 卡片区域.top() + 98.0, 卡片区域.width() - 48.0, 30.0)
        画笔.drawText(标题区, Qt.AlignCenter, self._标题)

        副标文案 = f"{self._副标题} · {self._版本号}" if self._版本号 else self._副标题
        副标字 = QFont("Microsoft YaHei UI", 10)
        画笔.setFont(副标字)
        画笔.setPen(QColor("#9CA3AF"))
        副标区 = QRectF(卡片区域.left() + 24.0, 卡片区域.top() + 128.0, 卡片区域.width() - 48.0, 20.0)
        画笔.drawText(副标区, Qt.AlignCenter, 副标文案)
        画笔.restore()

        # 5. 下方等宽小字阶段文案 + 2px 极细进度光带
        文案边距 = 28.0
        阶段区 = QRectF(
            卡片区域.left() + 文案边距,
            卡片区域.bottom() - 44.0,
            卡片区域.width() - 文案边距 * 2.0 - 44.0,
            18.0,
        )
        比例区 = QRectF(
            卡片区域.right() - 文案边距 - 44.0,
            卡片区域.bottom() - 44.0,
            44.0,
            18.0,
        )
        等宽字 = QFont("Consolas", 9)
        等宽字.setStyleHint(QFont.Monospace)
        画笔.setFont(等宽字)
        画笔.setPen(QColor("#9CA3AF"))
        画笔.drawText(阶段区, Qt.AlignLeft | Qt.AlignVCenter, self._阶段文案)

        画笔.setPen(QColor("#F59E0B"))
        画笔.drawText(比例区, Qt.AlignRight | Qt.AlignVCenter, f"{self._目标进度:>3d}%")

        轨道区 = QRectF(
            卡片区域.left() + 文案边距,
            卡片区域.bottom() - 20.0,
            卡片区域.width() - 文案边距 * 2.0,
            2.0,
        )
        画笔.setPen(Qt.NoPen)
        画笔.setBrush(QColor(255, 255, 255, 16))
        画笔.drawRoundedRect(轨道区, 1.0, 1.0)

        进度比例 = max(0.0, min(1.0, self._显示进度 / 100.0))
        if 进度比例 > 0.0:
            填充宽 = 轨道区.width() * 进度比例
            填充区 = QRectF(轨道区.left(), 轨道区.top(), 填充宽, 2.0)
            光带 = QLinearGradient(填充区.topLeft(), 填充区.topRight())
            光带.setColorAt(0.0, QColor("#B45309"))
            光带.setColorAt(0.75, QColor("#F59E0B"))
            光带.setColorAt(1.0, QColor("#FDE68A"))
            画笔.setBrush(光带)
            画笔.drawRoundedRect(填充区, 1.0, 1.0)

            光点中心 = QPointF(填充区.right(), 填充区.center().y())
            光晕 = QRadialGradient(光点中心, 7.0)
            光晕.setColorAt(0.0, QColor(253, 230, 138, 170))
            光晕.setColorAt(1.0, QColor(245, 158, 11, 0))
            画笔.setBrush(光晕)
            画笔.drawEllipse(光点中心, 7.0, 5.0)

        画笔.restore()

        # 6. 1px rgba(255,255,255,0.08) 极细亮描边
        画笔.setPen(QPen(QColor(255, 255, 255, 卡片描边Alpha), 1.0))
        画笔.setBrush(Qt.NoBrush)
        画笔.drawRoundedRect(卡片区域.adjusted(0.5, 0.5, -0.5, -0.5), 16.0, 16.0)
        画笔.end()


__all__ = ["高级启动画面", "卡片背景色", "暖金主色"]
