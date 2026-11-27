"""系统托盘常驻控制器：支持显示/隐藏主窗、开始/暂停、今日概览状态行与 offscreen 安全降级。"""
from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from 界面.高级主题 import 强调金, 创建矢量图标


def _默认托盘图标() -> QIcon:
    try:
        from 界面.组件 import 应用图标
        图标 = 应用图标()
        if not 图标.isNull():
            return 图标
    except Exception:
        pass
    return 创建矢量图标("主窗", 强调金, 32)


class 系统托盘控制器(QObject):
    """封装 QSystemTrayIcon 与右键菜单；在不支持托盘或 offscreen 环境安全降级。"""

    请求显示隐藏 = Signal()
    请求切换运行 = Signal()
    请求退出 = Signal()

    def __init__(
        self,
        主窗口: QWidget | None = None,
        图标: QIcon | None = None,
        显示隐藏回调: Callable[[], None] | None = None,
        开始暂停回调: Callable[[], None] | None = None,
        退出回调: Callable[[], None] | None = None,
        名称: str = "城控 · 部落冲突控制台",
        父: QObject | None = None,
    ):
        super().__init__(父 if 父 is not None else 主窗口)
        self._主窗口 = 主窗口
        self._显示隐藏回调 = 显示隐藏回调
        self._开始暂停回调 = 开始暂停回调
        self._退出回调 = 退出回调
        self._名称 = 名称
        self._状态文案 = "待机中"
        self._今日摘要 = "暂无战绩"
        self._已关闭 = False

        self._托盘: QSystemTrayIcon | None = None
        self._菜单 = QMenu()
        self._构建菜单()

        self._可用 = self._检测可用性()
        if self._可用:
            try:
                托盘图标 = 图标 if (图标 is not None and not 图标.isNull()) else _默认托盘图标()
                self._托盘 = QSystemTrayIcon(托盘图标, self)
                self._托盘.setContextMenu(self._菜单)
                self._托盘.activated.connect(self._处理激活)
            except Exception:
                self._托盘 = None
                self._可用 = False

        self.更新运行状态(self._状态文案, self._今日摘要)

    @staticmethod
    def _检测可用性() -> bool:
        if os.environ.get("QT_QPA_PLATFORM", "").strip().lower() == "offscreen":
            return False
        try:
            return bool(QSystemTrayIcon.isSystemTrayAvailable())
        except Exception:
            return False

    @property
    def 是否可用(self) -> bool:
        return bool(self._可用 and self._托盘 is not None and not self._已关闭)

    @property
    def 菜单(self) -> QMenu:
        return self._菜单

    def _构建菜单(self) -> None:
        self.概览动作 = QAction("状态：待机中 · 今日：暂无战绩", self)
        self.概览动作.setEnabled(False)

        self.显隐动作 = QAction("显示/隐藏主窗", self)
        self.显隐动作.setIcon(创建矢量图标("主窗", 尺寸=16))
        self.显隐动作.triggered.connect(self._触发显示隐藏)

        self.启停动作 = QAction("开始运行", self)
        self.启停动作.setIcon(创建矢量图标("运行", 尺寸=16))
        self.启停动作.triggered.connect(self._触发开始暂停)

        self.退出动作 = QAction("退出程序", self)
        self.退出动作.setIcon(创建矢量图标("关闭", 尺寸=16))
        self.退出动作.triggered.connect(self._触发退出)

        self._菜单.addAction(self.概览动作)
        self._菜单.addSeparator()
        self._菜单.addAction(self.显隐动作)
        self._菜单.addAction(self.启停动作)
        self._菜单.addSeparator()
        self._菜单.addAction(self.退出动作)

    # ================================================================ 公开 API
    def 显示(self) -> bool:
        if not self.是否可用:
            return False
        try:
            self._托盘.show()
            return True
        except Exception:
            return False

    def 隐藏(self) -> None:
        if self._托盘 is not None:
            try:
                self._托盘.hide()
            except Exception:
                pass

    def 更新运行状态(self, 状态文案: str, 今日摘要: str = "") -> None:
        """同步更新托盘悬浮提示、今日概览状态行及开始/暂停菜单文字。"""
        self._状态文案 = str(状态文案 or "待机中").strip() or "待机中"
        self._今日摘要 = str(今日摘要 or "").strip()

        概览文本 = (
            f"状态：{self._状态文案} · {self._今日摘要}"
            if self._今日摘要
            else f"状态：{self._状态文案}"
        )
        self.概览动作.setText(概览文本)

        运行中 = self._状态文案 in ("运行中", "运行")
        暂停中 = self._状态文案 in ("暂停中", "暂停")
        if 运行中:
            self.启停动作.setText("暂停运行")
            self.启停动作.setIcon(创建矢量图标("暂停", 尺寸=16))
        elif 暂停中:
            self.启停动作.setText("继续运行")
            self.启停动作.setIcon(创建矢量图标("运行", 尺寸=16))
        else:
            self.启停动作.setText("开始运行")
            self.启停动作.setIcon(创建矢量图标("运行", 尺寸=16))

        提示文本 = f"{self._名称}\n{概览文本}"
        if self.是否可用:
            try:
                self._托盘.setToolTip(提示文本)
            except Exception:
                pass

    def 关闭(self) -> None:
        if self._已关闭:
            return
        self._已关闭 = True
        self.隐藏()
        if self._托盘 is not None:
            try:
                self._托盘.setContextMenu(None)
                self._托盘.deleteLater()
            except Exception:
                pass
            self._托盘 = None

    # ================================================================ 内部交互
    def _处理激活(self, 原因: QSystemTrayIcon.ActivationReason) -> None:
        if 原因 in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._唤起主窗()

    def _唤起主窗(self) -> None:
        if self._主窗口 is not None:
            唤醒方法 = getattr(self._主窗口, "唤醒", None)
            if callable(唤醒方法):
                唤醒方法()
            else:
                self._主窗口.showNormal()
                self._主窗口.raise_()
                self._主窗口.activateWindow()
        elif self._显示隐藏回调 is not None:
            self._显示隐藏回调()
        self.请求显示隐藏.emit()

    def _触发显示隐藏(self) -> None:
        if self._显示隐藏回调 is not None:
            self._显示隐藏回调()
        elif self._主窗口 is not None:
            if self._主窗口.isVisible() and not self._主窗口.isMinimized():
                self._主窗口.hide()
            else:
                self._唤起主窗()
                return
        self.请求显示隐藏.emit()

    def _触发开始暂停(self) -> None:
        if self._开始暂停回调 is not None:
            self._开始暂停回调()
        self.请求切换运行.emit()

    def _触发退出(self) -> None:
        if self._退出回调 is not None:
            self._退出回调()
        self.请求退出.emit()


__all__ = ["系统托盘控制器"]
