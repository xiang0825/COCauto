"""暗黑高级感视觉组件套件：三阶深灰主题、内联 SVG 图标、微动效控件与现场截图预览。

本模块完全独立，可按需一行导入装配，不改动任何既有界面文件。
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QAbstractAnimation,
    QByteArray,
    QEasingCurve,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QImageReader,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtSvg import QSvgRenderer
except ImportError:  # pragma: no cover - 极端精简环境回退
    QSvgRenderer = None

from 界面.主题 import 配色, _下拉图标, _勾选图标

# ==================================================================== 色彩与样式常量
主底色 = "#0F1115"
卡片底色 = "#161920"
悬浮底色 = "#1E222B"

边框色 = "rgba(255, 255, 255, 0.08)"
边框亮色 = "rgba(255, 255, 255, 0.14)"
分隔色 = "rgba(255, 255, 255, 0.06)"

强调金 = "#F59E0B"
强调金悬停 = "#FBBF24"
强调金按压 = "#D97706"
强调金浅 = "rgba(245, 158, 11, 0.14)"

运行绿 = "#22C55E"
异常红 = "#EF4444"

文字主色 = "#F3F4F6"
文字次色 = "#9CA3AF"
文字弱色 = "#6B7280"

界面字体栈 = '"Microsoft YaHei UI", "PingFang SC", "Segoe UI", sans-serif'
等宽字体栈 = '"Cascadia Mono", "Consolas", "JetBrains Mono", "Microsoft YaHei UI", monospace'

高级深色 = 配色(
    名称="高级暗黑",
    背景=主底色,
    侧栏="#12151B",
    卡片=卡片底色,
    卡片描边="#252A36",
    分隔="#202530",
    文字=文字主色,
    次要文字=文字次色,
    弱文字=文字弱色,
    强调=强调金,
    强调悬停=强调金悬停,
    强调浅="#2E2414",
    强调文字="#FDE68A",
    输入底="#12151B",
    成功=运行绿,
    警告=强调金,
    错误=异常红,
    日志底=主底色,
)

暗黑主题常量: dict[str, str] = {
    "主底": 主底色,
    "卡片": 卡片底色,
    "悬浮": 悬浮底色,
    "边框": 边框色,
    "边框亮": 边框亮色,
    "分隔": 分隔色,
    "强调金": 强调金,
    "运行绿": 运行绿,
    "异常红": 异常红,
    "文字主": 文字主色,
    "文字次": 文字次色,
    "文字弱": 文字弱色,
}


def 生成高级暗黑样式表() -> str:
    """生成三阶深灰 + 1px 低透明边框 + 单一暖金强调色的高级暗黑样式表。"""
    勾选 = _勾选图标()
    下拉 = _下拉图标(文字次色)
    return f"""
* {{
    font-family: {界面字体栈};
    font-size: 13px;
    color: {文字主色};
}}
QMainWindow, QDialog, QWidget#根 {{
    background: {主底色};
}}
QWidget#侧栏 {{
    background: #12151B;
    border-right: 1px solid {分隔色};
}}
QWidget#顶栏 {{
    background: #12151B;
    border-bottom: 1px solid {分隔色};
}}

QLabel#品牌 {{
    font-size: 18px;
    font-weight: 700;
    color: {文字主色};
}}
QLabel#品牌副标题, QLabel#弱 {{
    color: {文字弱色};
    font-size: 12px;
}}
QLabel#次要 {{
    color: {文字次色};
}}
QLabel#页标题 {{
    font-size: 22px;
    font-weight: 700;
    color: {文字主色};
}}
QLabel#卡片标题 {{
    font-size: 14px;
    font-weight: 600;
    color: {文字主色};
}}
QLabel#等宽数字, QLabel[tabular="true"], QLabel#大数字 {{
    font-family: {等宽字体栈};
    color: {文字主色};
}}
QLabel#大数字 {{
    font-size: 26px;
    font-weight: 700;
}}
QLabel#提示条 {{
    background: {强调金浅};
    color: #FDE68A;
    border: 1px solid rgba(245, 158, 11, 0.25);
    border-radius: 8px;
    padding: 10px 14px;
}}
QLabel#错误提示 {{ color: {异常红}; }}
QLabel#成功提示 {{ color: {运行绿}; }}

QFrame#卡片, QFrame#高级卡片 {{
    background: {卡片底色};
    border: 1px solid {边框色};
    border-radius: 12px;
}}
QFrame#悬浮卡片, QWidget#悬浮层 {{
    background: {悬浮底色};
    border: 1px solid {边框亮色};
    border-radius: 10px;
}}
QFrame#分隔线 {{
    background: {分隔色};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

QPushButton#导航 {{
    text-align: left;
    padding: 9px 14px;
    border: 1px solid transparent;
    border-radius: 8px;
    color: {文字次色};
    background: transparent;
    font-size: 13px;
}}
QPushButton#导航:hover {{
    background: {悬浮底色};
    color: {文字主色};
}}
QPushButton#导航:checked {{
    background: {强调金浅};
    color: #FDE68A;
    font-weight: 600;
    border: 1px solid rgba(245, 158, 11, 0.24);
    border-left: 3px solid {强调金};
    padding-left: 12px;
}}

QPushButton {{
    background: {悬浮底色};
    color: {文字主色};
    border: 1px solid {边框色};
    border-radius: 8px;
    padding: 7px 14px;
    min-height: 18px;
}}
QPushButton:hover {{
    background: #252A36;
    border-color: rgba(245, 158, 11, 0.45);
    color: #FDE68A;
}}
QPushButton:pressed {{
    background: #1A1E26;
    border-color: {强调金};
}}
QPushButton:disabled {{
    color: {文字弱色};
    border-color: {分隔色};
    background: {卡片底色};
}}
QPushButton#主按钮 {{
    background: {强调金};
    color: {主底色};
    border: 1px solid {强调金};
    font-weight: 700;
}}
QPushButton#主按钮:hover {{
    background: {强调金悬停};
    border-color: {强调金悬停};
    color: {主底色};
}}
QPushButton#主按钮:pressed {{
    background: {强调金按压};
    border-color: {强调金按压};
    color: {主底色};
}}
QPushButton#主按钮:disabled {{
    background: #232732;
    border-color: {分隔色};
    color: {文字弱色};
}}
QPushButton#危险按钮:hover {{
    background: rgba(239, 68, 68, 0.14);
    border-color: rgba(239, 68, 68, 0.55);
    color: #FCA5A5;
}}
QPushButton#幽灵按钮 {{
    background: transparent;
    border: 1px solid transparent;
    color: {文字次色};
}}
QPushButton#幽灵按钮:hover {{
    background: {悬浮底色};
    border-color: {边框色};
    color: {文字主色};
}}
QPushButton#链接 {{
    border: none;
    background: transparent;
    color: {强调金};
    padding: 2px 4px;
}}
QPushButton#链接:hover {{
    color: {强调金悬停};
    text-decoration: underline;
}}
QToolButton {{
    border: 1px solid {边框色};
    border-radius: 7px;
    padding: 4px 8px;
    background: {悬浮底色};
    color: {文字主色};
}}
QToolButton:hover {{
    border-color: rgba(245, 158, 11, 0.45);
    background: #252A36;
}}
QToolButton::menu-indicator {{ image: none; width: 0; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit, QPlainTextEdit {{
    background: #12151B;
    border: 1px solid {边框色};
    border-radius: 7px;
    padding: 6px 10px;
    color: {文字主色};
    selection-background-color: {强调金};
    selection-color: {主底色};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QTimeEdit:focus, QPlainTextEdit:focus {{
    border-color: {强调金};
    background: {卡片底色};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({下拉}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {悬浮底色};
    border: 1px solid {边框亮色};
    selection-background-color: {强调金浅};
    selection-color: #FDE68A;
}}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {边框亮色};
    background: #12151B;
}}
QCheckBox::indicator:checked, QListWidget::indicator:checked {{
    background: {强调金};
    border-color: {强调金};
    image: url({勾选});
}}
QListWidget::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {文字弱色};
    background: #12151B;
}}
QCheckBox::indicator:hover, QListWidget::indicator:hover {{
    border-color: {强调金};
}}

QListWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{
    border-radius: 8px;
    padding: 8px 8px;
    margin: 1px 0;
}}
QListWidget::item:hover {{ background: {悬浮底色}; }}
QListWidget::item:selected {{
    background: {强调金浅};
    color: #FDE68A;
}}

QTextBrowser#日志 {{
    background: {主底色};
    border: 1px solid {边框色};
    border-radius: 10px;
    padding: 8px 10px;
    font-family: {等宽字体栈};
    font-size: 12px;
}}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.12);
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(255, 255, 255, 0.24);
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 0.12);
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: rgba(255, 255, 255, 0.24);
}}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {{
    width: 0;
    height: 0;
    background: transparent;
}}

QMenu {{
    background: {悬浮底色};
    border: 1px solid {边框亮色};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 14px;
    border-radius: 5px;
    color: {文字主色};
}}
QMenu::item:selected {{
    background: {强调金浅};
    color: #FDE68A;
}}
QMenu::item:disabled {{
    color: {文字弱色};
}}
QMenu::separator {{
    height: 1px;
    background: {分隔色};
    margin: 4px 8px;
}}

QToolTip {{
    background: {悬浮底色};
    color: {文字主色};
    border: 1px solid {边框亮色};
    border-radius: 6px;
    padding: 5px 8px;
}}
QMessageBox {{
    background: {卡片底色};
}}
"""


# ==================================================================== 内联 SVG 图标工厂
_SVG模板映射: dict[str, str] = {
    "金币": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M12 7v10M14.8 9.4c-.5-.8-1.5-1.2-2.8-1.2-1.6 0-2.7.7-2.7 1.8 '
        '0 1.2 1.1 1.6 2.7 1.9 1.7.3 2.9.8 2.9 2.1 0 1.2-1.2 2-2.9 2-1.4 0-2.5-.5-3-1.4"/>'
        '</svg>'
    ),
    "圣水": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 2.8C12 2.8 5.5 10.2 5.5 14.8a6.5 6.5 0 0 0 13 0C18.5 10.2 12 2.8 12 2.8Z"/>'
        '<path d="M9.2 15.2a2.9 2.9 0 0 0 2.8 2.6"/>'
        '</svg>'
    ),
    "黑油": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M9 3h6M10 3v4.2L5.6 15.4A3.5 3.5 0 0 0 8.7 20.5h6.6a3.5 3.5 0 0 0 3.1-5.1L14 7.2V3"/>'
        '<path d="M7.6 15h8.8"/>'
        '</svg>'
    ),
    "运行": (
        '<svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.4" '
        'stroke-linejoin="round">'
        '<polygon points="7,5 19,12 7,19"/>'
        '</svg>'
    ),
    "暂停": (
        '<svg viewBox="0 0 24 24" fill="currentColor">'
        '<rect x="6" y="5" width="4.2" height="14" rx="1.4"/>'
        '<rect x="13.8" y="5" width="4.2" height="14" rx="1.4"/>'
        '</svg>'
    ),
    "停止": (
        '<svg viewBox="0 0 24 24" fill="currentColor">'
        '<rect x="6" y="6" width="12" height="12" rx="2.2"/>'
        '</svg>'
    ),
    "设置": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="3.2"/>'
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06'
        'a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09'
        'a1.65 1.65 0 0 0-1.08-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06'
        'a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09'
        'a1.65 1.65 0 0 0 1.51-1.08 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06'
        'a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09'
        'a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06'
        'a1.65 1.65 0 0 0-.33 1.82V9c.26.6.85 1 1.51 1H21a2 2 0 1 1 0 4h-.09'
        'a1.65 1.65 0 0 0-1.51 1Z"/>'
        '</svg>'
    ),
    "战报": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 2.8 4.8 5.8v5.5c0 4.7 3.1 8.8 7.2 9.9 4.1-1.1 7.2-5.2 7.2-9.9V5.8L12 2.8Z"/>'
        '<path d="M8.8 14.5 11 11.4l2.2 1.8 2.4-3.6"/>'
        '</svg>'
    ),
    "截图": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/>'
        '<circle cx="9" cy="10" r="1.6"/>'
        '<path d="m20.5 15.5-4.3-4.3a1.5 1.5 0 0 0-2.1 0L7 18.3"/>'
        '</svg>'
    ),
    "日志": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="4" y="4" width="16" height="16" rx="2.5"/>'
        '<path d="M8 9h8M8 13h8M8 17h5"/>'
        '</svg>'
    ),
    "警告": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M10.3 4.3 2.7 17.5A1.9 1.9 0 0 0 4.4 20.3h15.2a1.9 1.9 0 0 0 1.7-2.8L13.7 4.3a1.9 1.9 0 0 0-3.4 0Z"/>'
        '<path d="M12 9.5v4.2M12 16.8h.01"/>'
        '</svg>'
    ),
    "刷新": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M20 11a8 8 0 0 0-14.9-3M4 4v4h4"/>'
        '<path d="M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4"/>'
        '</svg>'
    ),
    "关闭": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
        'stroke-linecap="round">'
        '<path d="M6 6l12 12M18 6 6 18"/>'
        '</svg>'
    ),
    "放大": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round">'
        '<circle cx="11" cy="11" r="6.5"/>'
        '<path d="m16 16 4.5 4.5M11 8.2v5.6M8.2 11h5.6"/>'
        '</svg>'
    ),
    "缩小": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round">'
        '<circle cx="11" cy="11" r="6.5"/>'
        '<path d="m16 16 4.5 4.5M8.2 11h5.6"/>'
        '</svg>'
    ),
    "适应": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>'
        '</svg>'
    ),
    "主窗": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/>'
        '<path d="M3.5 9h17"/>'
        '</svg>'
    ),
}


def 支持图标名称() -> tuple[str, ...]:
    """返回所有内置矢量图标名称。"""
    return tuple(_SVG模板映射.keys())


def 创建矢量图标(名称: str, 颜色: str = 文字主色, 尺寸: int = 16) -> QIcon:
    """将内联 SVG 渲染为多倍率高清 QIcon（不依赖 SVG imageformat 插件）。"""
    逻辑尺寸 = max(8, int(尺寸))
    svg源码 = _SVG模板映射.get(名称, _SVG模板映射["日志"]).replace("currentColor", 颜色)
    图标 = QIcon()

    if QSvgRenderer is not None:
        渲染器 = QSvgRenderer(QByteArray(svg源码.encode("utf-8")))
        if 渲染器.isValid():
            for 倍率 in (1, 2):
                图 = QPixmap(逻辑尺寸 * 倍率, 逻辑尺寸 * 倍率)
                图.fill(Qt.transparent)
                图.setDevicePixelRatio(float(倍率))
                画笔 = QPainter(图)
                画笔.setRenderHint(QPainter.Antialiasing)
                画笔.setRenderHint(QPainter.SmoothPixmapTransform)
                渲染器.render(画笔, QRectF(0, 0, 逻辑尺寸, 逻辑尺寸))
                画笔.end()
                图标.addPixmap(图)
            return 图标

    # 兜底矢量绘制（仅在 QtSvg 缺失时触发）
    图 = QPixmap(逻辑尺寸 * 2, 逻辑尺寸 * 2)
    图.fill(Qt.transparent)
    图.setDevicePixelRatio(2.0)
    画笔 = QPainter(图)
    画笔.setRenderHint(QPainter.Antialiasing)
    画笔.setPen(QPen(QColor(颜色), 1.6))
    画笔.drawRoundedRect(QRectF(2.5, 2.5, 逻辑尺寸 - 5, 逻辑尺寸 - 5), 3, 3)
    画笔.end()
    图标.addPixmap(图)
    return 图标


# ==================================================================== 控件 1：呼吸状态指示灯
_指示灯色板: dict[str, str] = {
    "运行中": 运行绿,
    "运行": 运行绿,
    "暂停中": 强调金,
    "暂停": 强调金,
    "警告": 强调金,
    "异常": 异常红,
    "错误": 异常红,
    "失败": 异常红,
    "待机": 文字弱色,
    "已停止": 文字弱色,
    "停止": 文字弱色,
}


class 呼吸状态指示灯(QWidget):
    """运行态 2 秒周期柔和呼吸光晕，待机/暂停/异常态稳定纯色。"""

    呼吸周期毫秒 = 2000

    def __init__(self, 状态: str = "待机", 尺寸: int = 14, 父: QWidget | None = None):
        super().__init__(父)
        self._状态 = ""
        self._尺寸 = max(8, int(尺寸))
        self._相位 = 0.0

        self._动画 = QVariantAnimation(self)
        self._动画.setStartValue(0.0)
        self._动画.setEndValue(1.0)
        self._动画.setDuration(self.呼吸周期毫秒)
        self._动画.setLoopCount(-1)
        self._动画.valueChanged.connect(self._更新相位)

        self.setFixedSize(self._尺寸, self._尺寸)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.设置状态(状态)

    @property
    def 状态(self) -> str:
        return self._状态

    @property
    def 当前颜色(self) -> QColor:
        return QColor(_指示灯色板.get(self._状态, 文字弱色))

    def _是否运行态(self, 状态: str) -> bool:
        return 状态 in ("运行中", "运行")

    def 设置状态(self, 状态: str) -> None:
        新状态 = str(状态 or "待机")
        if 新状态 == self._状态:
            return
        self._状态 = 新状态
        if self._是否运行态(新状态):
            if self._动画.state() != QAbstractAnimation.Running:
                self._动画.start()
        else:
            self._动画.stop()
            self._相位 = 0.0
        self.update()

    def _更新相位(self, 值: float) -> None:
        # 正弦平滑呼吸曲线：0 -> 1 -> 0
        self._相位 = 0.5 - 0.5 * math.cos(float(值) * 2.0 * math.pi)
        self.update()

    def closeEvent(self, 事件) -> None:
        self._动画.stop()
        super().closeEvent(事件)

    def sizeHint(self) -> QSize:
        return QSize(self._尺寸, self._尺寸)

    def paintEvent(self, _事件) -> None:
        画笔 = QPainter(self)
        画笔.setRenderHint(QPainter.Antialiasing)
        中心 = QRectF(self.rect()).center()
        基准色 = self.当前颜色
        核半径 = max(2.6, self._尺寸 * 0.25)

        if self._是否运行态(self._状态):
            光晕半径 = 核半径 + (self._尺寸 * 0.25) * (0.45 + 0.55 * self._相位)
            渐变 = QRadialGradient(中心, 光晕半径)
            外色 = QColor(基准色)
            外色.setAlpha(int(38 + 72 * self._相位))
            渐变.setColorAt(0.0, 外色)
            渐变.setColorAt(0.65, QColor(基准色.red(), 基准色.green(), 基准色.blue(), int(24 + 34 * self._相位)))
            渐变.setColorAt(1.0, QColor(基准色.red(), 基准色.green(), 基准色.blue(), 0))
            画笔.setPen(Qt.NoPen)
            画笔.setBrush(渐变)
            画笔.drawEllipse(中心, 光晕半径, 光晕半径)

        画笔.setPen(Qt.NoPen)
        画笔.setBrush(基准色)
        画笔.drawEllipse(中心, 核半径, 核半径)
        画笔.end()


# ==================================================================== 控件 2：滑动开关
class 滑动开关(QAbstractButton):
    """圆角胶囊滑动开关（120ms 过渡动效），兼容 QAbstractButton 接口。"""

    过渡毫秒 = 120

    def __init__(
        self,
        文本: str = "",
        选中: bool = False,
        强调色: str = 强调金,
        父: QWidget | None = None,
    ):
        super().__init__(父)
        self._强调色 = QColor(强调色)
        self._滑块位置 = 1.0 if 选中 else 0.0
        self._轨道宽 = 40
        self._轨道高 = 22

        self._动画 = QVariantAnimation(self)
        self._动画.setDuration(self.过渡毫秒)
        self._动画.setEasingCurve(QEasingCurve.OutCubic)
        self._动画.valueChanged.connect(self._设置滑块位置)

        self.setCheckable(True)
        self.setText(文本)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        if 选中:
            super().setChecked(True)
            self._滑块位置 = 1.0

    @property
    def 滑块进度(self) -> float:
        return self._滑块位置

    def _设置滑块位置(self, 值: float) -> None:
        self._滑块位置 = float(值)
        self.update()

    def _播放过渡(self, 目标选中: bool) -> None:
        目标 = 1.0 if 目标选中 else 0.0
        self._动画.stop()
        self._动画.setStartValue(self._滑块位置)
        self._动画.setEndValue(目标)
        self._动画.start()

    def setChecked(self, checked: bool) -> None:
        目标 = bool(checked)
        原状态 = self.isChecked()
        super().setChecked(目标)
        if 原状态 != 目标:
            self._播放过渡(目标)
        else:
            self._滑块位置 = 1.0 if 目标 else 0.0
            self.update()

    def nextCheckState(self) -> None:
        self.setChecked(not self.isChecked())

    def sizeHint(self) -> QSize:
        文本 = self.text().strip()
        if not 文本:
            return QSize(self._轨道宽, self._轨道高)
        字宽 = self.fontMetrics().horizontalAdvance(文本)
        return QSize(self._轨道宽 + 10 + 字宽 + 4, max(self._轨道高, self.fontMetrics().height() + 4))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def closeEvent(self, 事件) -> None:
        self._动画.stop()
        super().closeEvent(事件)

    def paintEvent(self, _事件) -> None:
        画笔 = QPainter(self)
        画笔.setRenderHint(QPainter.Antialiasing)

        顶部偏移 = max(0.0, (self.height() - self._轨道高) / 2.0)
        轨道矩形 = QRectF(0.5, 顶部偏移 + 0.5, self._轨道宽 - 1.0, self._轨道高 - 1.0)
        圆角 = 轨道矩形.height() / 2.0

        t = max(0.0, min(1.0, self._滑块位置))
        关底 = QColor("#1E222B")
        开底 = self._强调色
        底色 = QColor(
            int(关底.red() + (开底.red() - 关底.red()) * t),
            int(关底.green() + (开底.green() - 关底.green()) * t),
            int(关底.blue() + (开底.blue() - 关底.blue()) * t),
            160 if not self.isEnabled() else 255,
        )
        边框 = QColor(255, 255, 255, 26) if t < 0.5 else QColor(开底.red(), 开底.green(), 开底.blue(), 190)

        画笔.setPen(QPen(边框, 1.0))
        画笔.setBrush(底色)
        画笔.drawRoundedRect(轨道矩形, 圆角, 圆角)

        边距 = 3.0
        滑块直径 = self._轨道高 - 边距 * 2.0
        最小x = 边距
        最大x = self._轨道宽 - 边距 - 滑块直径
        滑块x = 最小x + (最大x - 最小x) * t
        滑块矩形 = QRectF(滑块x, 顶部偏移 + 边距, 滑块直径, 滑块直径)

        画笔.setPen(Qt.NoPen)
        画笔.setBrush(QColor("#F9FAFB") if self.isEnabled() else QColor("#9CA3AF"))
        画笔.drawEllipse(滑块矩形)

        文本 = self.text().strip()
        if 文本:
            画笔.setPen(QColor(文字主色 if self.isEnabled() else 文字弱色))
            文本矩形 = QRectF(
                self._轨道宽 + 10.0,
                0.0,
                max(0.0, self.width() - self._轨道宽 - 10.0),
                float(self.height()),
            )
            画笔.drawText(文本矩形, Qt.AlignVCenter | Qt.AlignLeft, 文本)
        画笔.end()


# ==================================================================== 控件 3：日志胶囊标签
_日志胶囊样式表: dict[str, tuple[str, str, str]] = {
    # 类别: (文字色, 半透明底色, 半透明描边)
    "搜敌": ("#93C5FD", "rgba(59, 130, 246, 0.14)", "rgba(59, 130, 246, 0.28)"),
    "进攻": ("#FCD34D", "rgba(245, 158, 11, 0.14)", "rgba(245, 158, 11, 0.30)"),
    "竞赛": ("#C4B5FD", "rgba(139, 92, 246, 0.14)", "rgba(139, 92, 246, 0.28)"),
    "保护": ("#86EFAC", "rgba(34, 197, 94, 0.14)", "rgba(34, 197, 94, 0.28)"),
    "异常": ("#FCA5A5", "rgba(239, 68, 68, 0.16)", "rgba(239, 68, 68, 0.34)"),
    "系统": ("#D1D5DB", "rgba(156, 163, 175, 0.12)", "rgba(156, 163, 175, 0.24)"),
}

支持日志类别: tuple[str, ...] = tuple(_日志胶囊样式表.keys())


class 日志胶囊标签(QLabel):
    """按日志类别自动匹配克制深色半透明配色的胶囊标签。"""

    def __init__(self, 类别: str = "系统", 父: QWidget | None = None):
        super().__init__(父)
        self._类别 = ""
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.设置类别(类别)

    @property
    def 类别(self) -> str:
        return self._类别

    def 配色方案(self) -> tuple[str, str, str]:
        return _日志胶囊样式表.get(self._类别, _日志胶囊样式表["系统"])

    def 设置类别(self, 类别: str) -> None:
        规范类别 = str(类别 or "系统").strip() or "系统"
        self._类别 = 规范类别
        self.setText(规范类别)
        字色, 底色, 描边 = self.配色方案()
        self.setStyleSheet(
            f"QLabel {{ color: {字色}; background: {底色}; border: 1px solid {描边};"
            " border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600; }}"
        )


# ==================================================================== 控件 4：现场截图预览弹窗
class 现场截图预览弹窗(QDialog):
    """异常日志直看现场图弹窗：支持高清缩放与缺失/损坏优雅提示。"""

    def __init__(
        self,
        图片路径: str | Path,
        标题: str = "现场截图预览",
        时间文本: str = "",
        元数据: dict[str, Any] | str | None = None,
        父: QWidget | None = None,
    ):
        super().__init__(父)
        self.图片路径 = Path(str(图片路径)) if str(图片路径 or "").strip() else None
        self.是否加载成功 = False
        self.错误提示 = ""
        self._原图 = QPixmap()
        self._缩放比例 = 1.0
        self._适应模式 = True

        self.setWindowTitle(标题 or "现场截图预览")
        self.resize(860, 620)
        self.setMinimumSize(480, 360)
        self.setStyleSheet(生成高级暗黑样式表())

        根布局 = QVBoxLayout(self)
        根布局.setContentsMargins(16, 14, 16, 14)
        根布局.setSpacing(10)

        # 顶部标题与元数据栏
        顶栏 = QFrame()
        顶栏.setObjectName("高级卡片")
        顶栏布局 = QHBoxLayout(顶栏)
        顶栏布局.setContentsMargins(14, 10, 14, 10)
        顶栏布局.setSpacing(10)

        左侧信息 = QVBoxLayout()
        左侧信息.setSpacing(3)
        标题行 = QHBoxLayout()
        标题行.setSpacing(8)
        图标框 = QLabel()
        图标框.setPixmap(创建矢量图标("截图", 强调金, 18).pixmap(18, 18))
        self.标题标签 = QLabel(标题 or "现场截图预览")
        self.标题标签.setObjectName("卡片标题")
        标题行.addWidget(图标框)
        标题行.addWidget(self.标题标签)
        if 时间文本:
            时间胶囊 = QLabel(时间文本)
            时间胶囊.setObjectName("等宽数字")
            时间胶囊.setStyleSheet(
                f"color: {文字次色}; background: {悬浮底色}; border: 1px solid {边框色};"
                " border-radius: 6px; padding: 2px 8px; font-size: 11px;"
            )
            标题行.addWidget(时间胶囊)
        标题行.addStretch(1)
        左侧信息.addLayout(标题行)

        self.元数据标签 = QLabel()
        self.元数据标签.setObjectName("弱")
        self.元数据标签.setWordWrap(True)
        左侧信息.addWidget(self.元数据标签)
        顶栏布局.addLayout(左侧信息, 1)

        # 缩放工具栏
        self.缩小按钮 = QPushButton("－")
        self.缩小按钮.setToolTip("缩小")
        self.缩小按钮.setFixedWidth(34)
        self.缩小按钮.clicked.connect(self.缩小)
        self.比例标签 = QLabel("适应")
        self.比例标签.setObjectName("等宽数字")
        self.比例标签.setAlignment(Qt.AlignCenter)
        self.比例标签.setMinimumWidth(52)
        self.放大按钮 = QPushButton("＋")
        self.放大按钮.setToolTip("放大")
        self.放大按钮.setFixedWidth(34)
        self.放大按钮.clicked.connect(self.放大)
        self.适应按钮 = QPushButton("适应窗口")
        self.适应按钮.clicked.connect(self.适应窗口)
        self.原寸按钮 = QPushButton("1:1")
        self.原寸按钮.clicked.connect(self.原始尺寸)
        关闭按钮 = QPushButton("关闭")
        关闭按钮.clicked.connect(self.accept)

        for 按钮 in (self.缩小按钮, self.比例标签, self.放大按钮, self.适应按钮, self.原寸按钮, 关闭按钮):
            顶栏布局.addWidget(按钮)
        根布局.addWidget(顶栏)

        # 图像预览区
        内容卡 = QFrame()
        内容卡.setObjectName("高级卡片")
        内容布局 = QVBoxLayout(内容卡)
        内容布局.setContentsMargins(8, 8, 8, 8)
        self.滚动区 = QScrollArea()
        self.滚动区.setWidgetResizable(True)
        self.滚动区.setAlignment(Qt.AlignCenter)

        self.画布标签 = QLabel()
        self.画布标签.setAlignment(Qt.AlignCenter)
        self.画布标签.setWordWrap(True)
        self.滚动区.setWidget(self.画布标签)
        内容布局.addWidget(self.滚动区, 1)
        根布局.addWidget(内容卡, 1)

        self._载入图片(元数据)

    @property
    def 缩放比例(self) -> float:
        return self._缩放比例

    def _格式化元数据(self, 元数据: dict[str, Any] | str | None, 分辨率: str = "") -> str:
        片段: list[str] = []
        if 分辨率:
            片段.append(分辨率)
        if isinstance(元数据, dict):
            for 键, 值 in 元数据.items():
                if 值 not in (None, ""):
                    片段.append(f"{键}: {值}")
        elif isinstance(元数据, str) and 元数据.strip():
            片段.append(元数据.strip())
        if self.图片路径 is not None:
            片段.append(str(self.图片路径))
        return "  ·  ".join(片段)

    def _载入图片(self, 元数据: dict[str, Any] | str | None) -> None:
        if self.图片路径 is None or not self.图片路径.exists() or not self.图片路径.is_file():
            self._设置错误状态("截图文件不存在或已被清理", 元数据)
            return
        读取器 = QImageReader(str(self.图片路径))
        读取器.setAutoTransform(True)
        图像 = 读取器.read()
        if 图像.isNull():
            详细 = 读取器.errorString() or "格式不受支持或文件已损坏"
            self._设置错误状态(f"无法读取现场截图（{详细}）", 元数据)
            return

        self._原图 = QPixmap.fromImage(图像)
        if self._原图.isNull() or self._原图.width() <= 0 or self._原图.height() <= 0:
            self._设置错误状态("截图图像内容为空", 元数据)
            return

        self.是否加载成功 = True
        self.错误提示 = ""
        分辨率 = f"{self._原图.width()}×{self._原图.height()}"
        self.元数据标签.setText(self._格式化元数据(元数据, 分辨率))
        self.适应窗口()

    def _设置错误状态(self, 原因: str, 元数据: dict[str, Any] | str | None) -> None:
        self.是否加载成功 = False
        self.错误提示 = 原因
        self.元数据标签.setText(self._格式化元数据(元数据))
        for 控件 in (self.缩小按钮, self.放大按钮, self.适应按钮, self.原寸按钮):
            控件.setEnabled(False)
        self.比例标签.setText("--")
        self.画布标签.setStyleSheet(
            f"color: {文字次色}; padding: 28px; font-size: 13px;"
        )
        路径文本 = str(self.图片路径) if self.图片路径 else "（未提供路径）"
        self.画布标签.setText(f"⚠ {原因}\n\n路径：{路径文本}")

    def _刷新视图(self) -> None:
        if not self.是否加载成功 or self._原图.isNull():
            return
        视口 = self.滚动区.viewport().size()
        if self._适应模式:
            目标宽 = max(64, 视口.width() - 16)
            目标高 = max(64, 视口.height() - 16)
            缩放图 = self._原图.scaled(目标宽, 目标高, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if self._原图.width() > 0:
                self._缩放比例 = 缩放图.width() / float(self._原图.width())
            self.比例标签.setText("适应")
        else:
            目标宽 = max(1, int(round(self._原图.width() * self._缩放比例)))
            目标高 = max(1, int(round(self._原图.height() * self._缩放比例)))
            缩放图 = self._原图.scaled(目标宽, 目标高, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.比例标签.setText(f"{int(round(self._缩放比例 * 100))}%")
        self.画布标签.setPixmap(缩放图)

    def 适应窗口(self) -> None:
        self._适应模式 = True
        self._刷新视图()

    def 原始尺寸(self) -> None:
        self._适应模式 = False
        self._缩放比例 = 1.0
        self._刷新视图()

    def 放大(self) -> None:
        self._适应模式 = False
        self._缩放比例 = min(4.0, round(self._缩放比例 * 1.25, 3))
        self._刷新视图()

    def 缩小(self) -> None:
        self._适应模式 = False
        self._缩放比例 = max(0.15, round(self._缩放比例 / 1.25, 3))
        self._刷新视图()

    def resizeEvent(self, 事件) -> None:
        super().resizeEvent(事件)
        if self._适应模式 and self.是否加载成功:
            self._刷新视图()

    def wheelEvent(self, 事件: QWheelEvent) -> None:
        if self.是否加载成功:
            增量 = 事件.angleDelta().y()
            if 增量 > 0:
                self.放大()
                事件.accept()
                return
            if 增量 < 0:
                self.缩小()
                事件.accept()
                return
        super().wheelEvent(事件)


# ==================================================================== 窗口位置记忆助手
def _屏幕列表() -> list[QRect]:
    屏幕对象 = QGuiApplication.screens()
    区域列表 = [屏.availableGeometry() for 屏 in 屏幕对象 if 屏 is not None]
    if not 区域列表:
        主屏 = QGuiApplication.primaryScreen()
        if 主屏 is not None:
            区域列表.append(主屏.availableGeometry())
    return [区域 for 区域 in 区域列表 if 区域.isValid() and 区域.width() > 0 and 区域.height() > 0]


def _校验并修正矩形(矩形: QRect, 最小宽: int, 最小高: int) -> QRect | None:
    屏幕们 = _屏幕列表()
    if not 屏幕们 or not 矩形.isValid():
        return None

    # 找到与保存矩形相交面积最大的屏幕；若全在屏幕外（例如外接屏已断开），回退主屏。
    目标屏 = max(
        屏幕们,
        key=lambda 屏: max(0, 屏.intersected(矩形).width()) * max(0, 屏.intersected(矩形).height()),
    )
    相交 = 目标屏.intersected(矩形)
    if 相交.width() < 80 or 相交.height() < 60:
        目标屏 = 屏幕们[0]
        宽 = min(max(矩形.width(), 最小宽), 目标屏.width())
        高 = min(max(矩形.height(), 最小高), 目标屏.height())
        x = 目标屏.center().x() - 宽 // 2
        y = 目标屏.center().y() - 高 // 2
        return QRect(x, y, 宽, 高)

    宽 = min(max(矩形.width(), 最小宽), 目标屏.width())
    高 = min(max(矩形.height(), 最小高), 目标屏.height())
    x = max(目标屏.left(), min(矩形.left(), 目标屏.right() - 宽 + 1))
    y = max(目标屏.top(), min(矩形.top(), 目标屏.bottom() - 高 + 1))
    return QRect(x, y, 宽, 高)


def 保存窗口几何(窗口: QWidget, 存储路径: str | Path) -> bool:
    """安全保存窗口几何位置与尺寸到 JSON 文件（不删除任何现有文件）。"""
    if 窗口 is None:
        return False
    try:
        目标 = Path(存储路径)
        目标.parent.mkdir(parents=True, exist_ok=True)
        几何 = 窗口.normalGeometry() if 窗口.isMaximized() else 窗口.geometry()
        数据 = {
            "x": int(几何.x()),
            "y": int(几何.y()),
            "width": int(几何.width()),
            "height": int(几何.height()),
            "maximized": bool(窗口.isMaximized()),
        }
        目标.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def 恢复窗口几何(窗口: QWidget, 存储路径: str | Path) -> bool:
    """从 JSON 恢复窗口位置与尺寸，并安全校验屏幕边界防止跑出可视区。"""
    if 窗口 is None:
        return False
    try:
        目标 = Path(存储路径)
        if not 目标.is_file():
            return False
        数据 = json.loads(目标.read_text(encoding="utf-8"))
        if not isinstance(数据, dict):
            return False
        x = int(数据["x"])
        y = int(数据["y"])
        宽 = int(数据["width"])
        高 = int(数据["height"])
        最大化 = bool(数据.get("maximized", False))
    except Exception:
        return False

    if 宽 <= 0 or 高 <= 0:
        return False

    最小宽 = max(200, 窗口.minimumWidth())
    最小高 = max(150, 窗口.minimumHeight())
    修正矩形 = _校验并修正矩形(QRect(x, y, 宽, 高), 最小宽, 最小高)
    if 修正矩形 is None:
        return False

    窗口.setGeometry(修正矩形)
    if 最大化:
        窗口.showMaximized()
    return True


__all__ = [
    "主底色",
    "卡片底色",
    "悬浮底色",
    "边框色",
    "边框亮色",
    "分隔色",
    "强调金",
    "强调金悬停",
    "强调金按压",
    "强调金浅",
    "运行绿",
    "异常红",
    "文字主色",
    "文字次色",
    "文字弱色",
    "界面字体栈",
    "等宽字体栈",
    "高级深色",
    "暗黑主题常量",
    "生成高级暗黑样式表",
    "支持图标名称",
    "创建矢量图标",
    "呼吸状态指示灯",
    "滑动开关",
    "支持日志类别",
    "日志胶囊标签",
    "现场截图预览弹窗",
    "保存窗口几何",
    "恢复窗口几何",
]
