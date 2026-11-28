"""配色令牌与 Qt 样式表。浅色/深色两套，界面只引用令牌名。"""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass


@dataclass(frozen=True)
class 配色:
    名称: str
    背景: str          # 窗口底色
    侧栏: str
    卡片: str
    卡片描边: str
    分隔: str
    文字: str
    次要文字: str
    弱文字: str
    强调: str          # 品牌橙
    强调悬停: str
    强调浅: str        # 选中/提示底色
    强调文字: str      # 在强调浅底上的文字
    输入底: str
    成功: str
    警告: str
    错误: str
    日志底: str


浅色 = 配色(
    名称="浅色",
    背景="#f5f6f8", 侧栏="#ffffff", 卡片="#ffffff", 卡片描边="#e3e7ec",
    分隔="#e8ebef", 文字="#1f2733", 次要文字="#5c6878", 弱文字="#8b96a5",
    强调="#c2602d", 强调悬停="#a9521f", 强调浅="#fdeee3", 强调文字="#8f4321",
    输入底="#ffffff", 成功="#1f9d63", 警告="#b7791f", 错误="#c53030",
    日志底="#fbfcfd",
)

深色 = 配色(
    名称="深色",
    背景="#14181e", 侧栏="#1a1f27", 卡片="#1e242d", 卡片描边="#2b3340",
    分隔="#262d38", 文字="#e7ebf0", 次要文字="#a3adbb", 弱文字="#728093",
    强调="#e07a43", 强调悬停="#f08c55", 强调浅="#3a2a21", 强调文字="#ffc9a8",
    输入底="#171c23", 成功="#4cc98d", 警告="#f0b452", 错误="#ff7b72",
    日志底="#161b22",
)

全部配色 = {浅色.名称: 浅色, 深色.名称: 深色}


def 状态颜色(色: 配色, 状态: str) -> str:
    return {
        "运行中": 色.成功,
        "暂停中": 色.警告,
        "已停止": 色.弱文字,
    }.get(状态, 色.弱文字)


def 级别颜色(色: 配色, 级别: str) -> str:
    return {
        "警告": 色.警告, "错误": 色.错误, "成功": 色.成功, "次要": 色.弱文字,
    }.get(级别, 色.文字)


def _图标文件(名称: str, 颜色: str, 绘制) -> str:
    """样式表只能引用文件路径；用 QPainter 画 PNG 写到临时目录。

    不依赖 SVG 图像插件（打包后插件缺失时图标会消失）。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    目录 = os.path.join(tempfile.gettempdir(), "cocauto-ui")
    os.makedirs(目录, exist_ok=True)
    键 = hashlib.md5(f"{名称}-{颜色}-v1".encode()).hexdigest()[:12]
    路径 = os.path.join(目录, f"{名称}-{键}.png")
    if not os.path.isfile(路径):
        图 = QPixmap(32, 32)
        图.fill(Qt.transparent)
        画笔 = QPainter(图)
        画笔.setRenderHint(QPainter.Antialiasing)
        笔 = QPen(QColor(颜色), 4.2)
        笔.setCapStyle(Qt.RoundCap)
        笔.setJoinStyle(Qt.RoundJoin)
        画笔.setPen(笔)
        绘制(画笔)
        画笔.end()
        图.save(路径, "PNG")
    return 路径.replace("\\", "/")


def _勾选图标() -> str:
    from PySide6.QtCore import QPointF

    return _图标文件("勾选", "#ffffff", lambda 笔: 笔.drawPolyline(
        [QPointF(7.5, 16.5), QPointF(13.5, 22.5), QPointF(25, 10)]
    ))


def _下拉图标(颜色: str) -> str:
    from PySide6.QtCore import QPointF

    return _图标文件("下拉", 颜色, lambda 笔: 笔.drawPolyline(
        [QPointF(8, 12.5), QPointF(16, 20.5), QPointF(24, 12.5)]
    ))


默认主题名 = "高级暗黑"


def 按名称取配色(名称: str | None) -> 配色:
    """高级暗黑是默认主题；旧版保存的“深色”也映射到高级暗黑。"""
    from 界面.高级主题 import 高级深色

    if 名称 == 浅色.名称:
        return 浅色
    return 高级深色


def 下一个配色(色: 配色) -> 配色:
    return 按名称取配色(默认主题名 if 色.名称 == 浅色.名称 else 浅色.名称)


def 生成样式表(色: 配色) -> str:
    if 色.名称 == 默认主题名:
        from 界面.高级主题 import 生成高级暗黑样式表

        return 生成高级暗黑样式表() + 方案A样式(色)
    勾选 = _勾选图标()
    下拉 = _下拉图标(色.次要文字)
    return f"""
* {{
    font-family: "Microsoft YaHei UI", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 13px;
    color: {色.文字};
}}
QMainWindow, QWidget#根 {{ background: {色.背景}; }}
QWidget#侧栏 {{ background: {色.侧栏}; border-right: 1px solid {色.分隔}; }}
QWidget#顶栏 {{ background: {色.侧栏}; border-bottom: 1px solid {色.分隔}; }}
QLabel#品牌 {{ font-size: 18px; font-weight: 700; }}
QLabel#品牌副标题, QLabel#弱 {{ color: {色.弱文字}; font-size: 12px; }}
QLabel#次要 {{ color: {色.次要文字}; }}
QLabel#页标题 {{ font-size: 22px; font-weight: 700; }}
QLabel#卡片标题 {{ font-size: 15px; font-weight: 600; }}
QLabel#大数字 {{ font-size: 26px; font-weight: 700; }}
QLabel#提示条 {{
    background: {色.强调浅}; color: {色.强调文字};
    border-radius: 8px; padding: 10px 14px;
}}
QLabel#错误提示 {{ color: {色.错误}; }}
QLabel#成功提示 {{ color: {色.成功}; }}

QPushButton#导航 {{
    text-align: left; padding: 9px 14px; border: none; border-radius: 8px;
    color: {色.次要文字}; background: transparent; font-size: 14px;
}}
QPushButton#导航:hover {{ background: {色.背景}; color: {色.文字}; }}
QPushButton#导航:checked {{
    background: {色.强调浅}; color: {色.强调文字}; font-weight: 600;
    border-left: 3px solid {色.强调}; padding-left: 11px;
}}

QFrame#卡片 {{
    background: {色.卡片}; border: 1px solid {色.卡片描边}; border-radius: 12px;
}}
QFrame#分隔线 {{ background: {色.分隔}; max-height: 1px; min-height: 1px; border: none; }}

QPushButton {{
    background: {色.卡片}; border: 1px solid {色.卡片描边}; border-radius: 8px;
    padding: 7px 14px; min-height: 18px;
}}
QPushButton:hover {{ border-color: {色.强调}; color: {色.强调文字}; }}
QPushButton:pressed {{ background: {色.强调浅}; }}
QPushButton:disabled {{ color: {色.弱文字}; border-color: {色.分隔}; background: {色.背景}; }}
QPushButton#主按钮 {{
    background: {色.强调}; color: #ffffff; border: 1px solid {色.强调}; font-weight: 600;
}}
QPushButton#主按钮:hover {{ background: {色.强调悬停}; border-color: {色.强调悬停}; color: #ffffff; }}
QPushButton#主按钮:disabled {{ background: {色.分隔}; border-color: {色.分隔}; color: {色.弱文字}; }}
QPushButton#危险按钮:hover {{ border-color: {色.错误}; color: {色.错误}; }}
QPushButton#链接 {{
    border: none; background: transparent; color: {色.强调}; padding: 2px 4px;
}}
QPushButton#链接:hover {{ text-decoration: underline; }}
QToolButton {{
    border: 1px solid {色.卡片描边}; border-radius: 6px; padding: 3px 6px; background: {色.卡片};
}}
QToolButton:hover {{ border-color: {色.强调}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit, QPlainTextEdit {{
    background: {色.输入底}; border: 1px solid {色.卡片描边}; border-radius: 7px;
    padding: 6px 9px; selection-background-color: {色.强调};
    selection-color: #ffffff;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QTimeEdit:focus, QPlainTextEdit:focus {{ border-color: {色.强调}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({下拉}); width: 12px; height: 12px; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{
    background: {色.卡片}; border: 1px solid {色.卡片描边};
    selection-background-color: {色.强调浅}; selection-color: {色.强调文字};
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {色.卡片描边}; background: {色.输入底};
}}
QCheckBox::indicator:checked, QListWidget::indicator:checked {{
    background: {色.强调}; border-color: {色.强调}; image: url({勾选});
}}
QListWidget::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {色.弱文字}; background: {色.输入底};
}}
QCheckBox::indicator:hover, QListWidget::indicator:hover {{ border-color: {色.强调}; }}

QListWidget {{
    background: transparent; border: none; outline: none;
}}
QListWidget::item {{
    border-radius: 8px; padding: 8px 6px; margin: 1px 0;
}}
QListWidget::item:hover {{ background: {色.背景}; }}
QListWidget::item:selected {{ background: {色.强调浅}; color: {色.强调文字}; }}

QTextBrowser#日志 {{
    background: {色.日志底}; border: 1px solid {色.卡片描边}; border-radius: 10px;
    padding: 8px 10px; font-size: 13px;
}}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {色.卡片描边}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {色.弱文字}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {色.卡片描边}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QToolTip {{
    background: {色.卡片}; color: {色.文字}; border: 1px solid {色.卡片描边}; padding: 5px;
}}
QMessageBox {{ background: {色.卡片}; }}
""" + 方案A样式(色)


def 是暗色(色: 配色) -> bool:
    return 色.名称 != "浅色"


def 方案A样式(色: 配色) -> str:
    """主窗口单屏布局（状态栏、数据条、提醒条、分段按钮）专用样式，浅色与暗色共用。"""
    暗 = 是暗色(色)
    return f"""
QDialog#根 {{ background: {色.背景}; }}
QLabel#当前动作 {{ font-size: 14px; font-weight: 600; }}
QPushButton#设备芯片 {{
    padding: 3px 10px; font-size: 12px; color: {色.次要文字}; border-radius: 6px;
}}
QWidget#数据条 {{ background: {色.侧栏}; border-bottom: 1px solid {色.分隔}; }}
QLabel#数据名 {{ color: {色.弱文字}; font-size: 11px; }}
QLabel#数据值, QLabel#数据值金, QLabel#数据值水 {{
    font-size: 18px; font-weight: 700;
    font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei UI", monospace;
}}
QLabel#数据值金 {{ color: {色.警告}; }}
QLabel#数据值水 {{ color: {"#C4B5FD" if 暗 else "#9b3fb0"}; }}
QFrame#竖分隔 {{ background: {色.分隔}; min-width: 1px; max-width: 1px; border: none; }}
QProgressBar#竞赛进度 {{ border: none; background: {色.分隔}; border-radius: 3px; }}
QProgressBar#竞赛进度::chunk {{ background: {色.强调}; border-radius: 3px; }}
QFrame#提醒条 {{
    background: {"rgba(245, 158, 11, 0.10)" if 暗 else "#fff6e5"};
    border: 1px solid {"rgba(245, 158, 11, 0.28)" if 暗 else "#f3dfb5"}; border-radius: 8px;
}}
QLabel#提醒文字 {{ color: {色.警告}; }}
QPushButton#分段 {{ padding: 3px 9px; border-radius: 6px; font-size: 12px; min-height: 14px; }}
QPushButton#分段:checked {{
    background: {色.强调浅}; color: {色.强调文字}; border-color: {色.强调}; font-weight: 600;
}}
QListWidget#任务列表::item {{ padding: 2px 4px; margin: 0; }}
QListWidget#设置导航::item {{ padding: 7px 10px; }}
QTableWidget {{
    background: {色.卡片}; color: {色.文字}; gridline-color: {色.分隔};
    border: 1px solid {色.卡片描边}; border-radius: 8px;
}}
QTableWidget::item {{ padding: 4px 6px; }}
QHeaderView::section {{
    background: {色.输入底}; color: {色.次要文字}; border: none;
    border-bottom: 1px solid {色.分隔}; padding: 6px 8px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {色.输入底}; border: none; }}
"""
