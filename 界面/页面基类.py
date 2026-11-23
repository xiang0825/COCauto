"""页面公共接口与界面上下文。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from 应用.控制器 import 应用控制器
from 应用.日志模型 import 日志聚合器
from 界面.主题 import 配色


@dataclass
class 界面上下文:
    控制器: 应用控制器
    聚合器: 日志聚合器
    配色: 配色
    记录操作: Callable[[str], None]
    打开页面: Callable[[str], None]


class 页面基类(QWidget):
    标题 = ""
    说明 = ""

    def __init__(self, 上下文: 界面上下文, 可滚动: bool = True):
        super().__init__()
        self.上下文 = 上下文
        外层 = QVBoxLayout(self)
        外层.setContentsMargins(0, 0, 0, 0)
        内容 = QWidget()
        self.布局 = QVBoxLayout(内容)
        self.布局.setContentsMargins(24, 20, 24, 22)
        self.布局.setSpacing(16)
        if 可滚动:
            滚动 = QScrollArea()
            滚动.setWidgetResizable(True)
            滚动.setWidget(内容)
            外层.addWidget(滚动)
        else:
            外层.addWidget(内容)

    @property
    def 控制器(self) -> 应用控制器:
        return self.上下文.控制器

    def 载入(self) -> None:
        """控制器准备完成后调用一次，读取设置。"""

    def 页面显示(self) -> None:
        """页面切到前台时调用。"""

    def 定时刷新(self) -> None:
        """主窗口每秒调用一次（仅当前页面）。"""

    def 应用配色(self, 色: 配色) -> None:
        """切换浅色/深色时调用。"""
