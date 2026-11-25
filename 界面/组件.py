"""通用界面组件与后台任务工具。"""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QImage, QIcon
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QSizePolicy, QVBoxLayout, QWidget,
)

from 界面.主题 import 配色, 状态颜色


# ------------------------------------------------------------------ 后台执行
class _任务信号(QObject):
    成功 = Signal(object)
    失败 = Signal(str)


class _后台任务(QRunnable):
    def __init__(self, 函数: Callable[[], Any]):
        super().__init__()
        self.函数 = 函数
        self.信号 = _任务信号()

    def run(self):  # noqa: D401 - Qt 接口
        try:
            结果 = self.函数()
        except Exception as 异常:  # 后台失败统一回到界面线程显示
            traceback.print_exc()
            self.信号.失败.emit(str(异常) or type(异常).__name__)
        else:
            self.信号.成功.emit(结果)


_进行中: set[_后台任务] = set()


def 后台执行(
    函数: Callable[[], Any],
    成功: Callable[[Any], None] | None = None,
    失败: Callable[[str], None] | None = None,
) -> None:
    """在线程池执行耗时函数，回调在界面线程触发。"""
    任务 = _后台任务(函数)
    _进行中.add(任务)

    def _完成(结果):
        _进行中.discard(任务)
        if 成功:
            成功(结果)

    def _出错(信息):
        _进行中.discard(任务)
        if 失败:
            失败(信息)

    任务.信号.成功.connect(_完成, Qt.QueuedConnection)
    任务.信号.失败.connect(_出错, Qt.QueuedConnection)
    任务.setAutoDelete(False)
    QThreadPool.globalInstance().start(任务)


# ------------------------------------------------------------------ 基础部件
class 卡片(QFrame):
    def __init__(self, 标题: str | None = None, 父=None, 边距: int = 20):
        super().__init__(父)
        self.setObjectName("卡片")
        self.布局 = QVBoxLayout(self)
        self.布局.setContentsMargins(边距, 边距 - 2, 边距, 边距)
        self.布局.setSpacing(10)
        if 标题:
            self.标题 = QLabel(标题)
            self.标题.setObjectName("卡片标题")
            self.布局.addWidget(self.标题)


def 标签(文本: str = "", 样式名: str | None = None, 换行: bool = False) -> QLabel:
    控件 = QLabel(文本)
    if 样式名:
        控件.setObjectName(样式名)
    if 换行:
        控件.setWordWrap(True)
    控件.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return 控件


def 分隔线() -> QFrame:
    线 = QFrame()
    线.setObjectName("分隔线")
    线.setFrameShape(QFrame.NoFrame)
    return 线


def 横排(*控件, 间距: int = 8, 拉伸在末尾: bool = False) -> QHBoxLayout:
    布局 = QHBoxLayout()
    布局.setSpacing(间距)
    布局.setContentsMargins(0, 0, 0, 0)
    for 项 in 控件:
        if 项 is None:
            布局.addStretch(1)
        elif isinstance(项, QWidget):
            布局.addWidget(项)
        else:
            布局.addLayout(项)
    if 拉伸在末尾:
        布局.addStretch(1)
    return 布局


class 省略标签(QLabel):
    """单行文字，放不下时末尾显示“…”，完整内容在提示里。"""

    def __init__(self, 文本: str = "", 父=None):
        super().__init__(父)
        self._全文 = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.设置文本(文本)

    def 设置文本(self, 文本: str):
        if 文本 == self._全文:
            return
        self._全文 = 文本
        self.setToolTip(文本)
        self._更新()

    def 全文(self) -> str:
        return self._全文

    def resizeEvent(self, 事件):
        super().resizeEvent(事件)
        self._更新()

    def _更新(self):
        宽 = max(10, self.width() - 2)
        super().setText(self.fontMetrics().elidedText(self._全文, Qt.ElideRight, 宽))


class 状态胶囊(QLabel):
    """● 运行中 这类带颜色圆点的状态标签。"""

    def __init__(self, 色: 配色, 父=None):
        super().__init__(父)
        self._色 = 色
        self._状态 = ""
        self.设置("已停止")

    def 应用配色(self, 色: 配色):
        self._色 = 色
        self.设置(self._状态, 强制=True)

    def 设置(self, 状态: str, 文本: str | None = None, 强制: bool = False):
        if 状态 == self._状态 and not 强制 and 文本 is None:
            return
        self._状态 = 状态
        颜色 = 状态颜色(self._色, 状态)
        底色 = QColor(颜色)
        底色.setAlpha(36)
        self.setText(f"● {文本 or 状态}")
        self.setStyleSheet(
            f"QLabel {{ color: {颜色}; background: rgba({底色.red()},{底色.green()},"
            f"{底色.blue()},{底色.alpha()}); border-radius: 11px; padding: 3px 11px;"
            f" font-weight: 600; }}"
        )


class 品牌标志(QWidget):
    """自绘城垛标志，不依赖图片资源。"""

    def __init__(self, 大小: int = 40, 父=None):
        super().__init__(父)
        self.setFixedSize(大小, 大小)

    def paintEvent(self, _事件):
        绘制标志(QPainter(self), self.width())


def 绘制标志(画笔: QPainter, 大小: int) -> None:
    画笔.setRenderHint(QPainter.Antialiasing)
    比 = 大小 / 64
    画笔.setPen(Qt.NoPen)
    画笔.setBrush(QColor("#fdeee3"))
    画笔.drawRoundedRect(QRectF(1 * 比, 1 * 比, 62 * 比, 62 * 比), 16 * 比, 16 * 比)
    路径 = QPainterPath()
    点 = [(15, 46), (15, 23), (23, 23), (23, 17), (30, 17), (30, 23), (36, 23),
         (36, 17), (43, 17), (43, 23), (50, 23), (50, 46)]
    路径.moveTo(QPointF(点[0][0] * 比, 点[0][1] * 比))
    for x, y in 点[1:]:
        路径.lineTo(QPointF(x * 比, y * 比))
    路径.closeSubpath()
    画笔.setBrush(QColor("#c2602d"))
    画笔.drawPath(路径)
    画笔.setBrush(QColor("#fdeee3"))
    画笔.drawRect(QRectF(28 * 比, 33 * 比, 9 * 比, 13 * 比))
    画笔.setPen(QPen(QColor("#8f4321"), max(1.0, 2 * 比)))
    画笔.drawLine(QPointF(14 * 比, 47 * 比), QPointF(51 * 比, 47 * 比))
    画笔.end()


def 应用图标() -> QIcon:
    图标 = QIcon()
    for 尺寸 in (16, 24, 32, 48, 64, 128, 256):
        图 = QPixmap(尺寸, 尺寸)
        图.fill(Qt.transparent)
        绘制标志(QPainter(图), 尺寸)
        图标.addPixmap(图)
    return 图标


# ------------------------------------------------------------------ 图像
def BGR转图像(数组) -> QImage:
    """OpenCV BGR 数组 → QImage（复制数据，避免数组释放后悬空）。"""
    高, 宽 = 数组.shape[:2]
    if 数组.ndim == 2:
        return QImage(数组.data, 宽, 高, 数组.strides[0], QImage.Format_Grayscale8).copy()
    通道 = 数组.shape[2]
    格式 = QImage.Format_BGR888 if 通道 == 3 else QImage.Format_ARGB32
    return QImage(数组.data, 宽, 高, 数组.strides[0], 格式).copy()


def PIL转图像(图片) -> QImage:
    图片 = 图片.convert("RGBA")
    数据 = 图片.tobytes("raw", "RGBA")
    return QImage(数据, 图片.width, 图片.height, 图片.width * 4, QImage.Format_RGBA8888).copy()


# ------------------------------------------------------------------ 对话框
def 提示错误(父, 标题: str, 内容: str) -> None:
    QMessageBox.critical(父, 标题, 内容)


def 提示信息(父, 标题: str, 内容: str) -> None:
    QMessageBox.information(父, 标题, 内容)


def 确认(父, 标题: str, 内容: str) -> bool:
    return QMessageBox.question(
        父, 标题, 内容, QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
    ) == QMessageBox.Yes


def 扩展策略(控件: QWidget, 水平=True, 垂直=False) -> QWidget:
    控件.setSizePolicy(
        QSizePolicy.Expanding if 水平 else QSizePolicy.Preferred,
        QSizePolicy.Expanding if 垂直 else QSizePolicy.Preferred,
    )
    return 控件
