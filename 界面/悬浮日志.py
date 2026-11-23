"""置顶半透明日志小窗：边看游戏边看机器人状态。"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from 界面.主题 import 深色, 生成样式表, 状态颜色
from 界面.日志视图 import 日志视图
from 界面.组件 import 横排


class 悬浮日志窗(QWidget):
    def __init__(self, 上下文, 隐藏主窗口, 关闭回调):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.上下文 = 上下文
        self._隐藏主窗口 = 隐藏主窗口
        self._关闭回调 = 关闭回调
        self.setWindowTitle("运行日志 · 悬浮")
        self.setWindowOpacity(0.86)
        self.setObjectName("根")
        self.setStyleSheet(生成样式表(深色))
        self.resize(760, 400)
        self.setMinimumSize(480, 240)
        屏幕 = QGuiApplication.primaryScreen().availableGeometry()
        self.move(QPoint(屏幕.right() - self.width() - 30, 屏幕.top() + 75))

        布局 = QVBoxLayout(self)
        布局.setContentsMargins(12, 10, 12, 12)
        布局.setSpacing(8)
        标题 = QLabel("运行日志")
        标题.setObjectName("卡片标题")
        self.详细 = QCheckBox("详细")
        self.跟随 = QCheckBox("跟随")
        self.跟随.setChecked(True)
        隐藏 = QPushButton("隐藏主界面")
        隐藏.clicked.connect(self._隐藏主窗口)
        关闭 = QPushButton("关闭悬浮")
        关闭.clicked.connect(self.close)
        布局.addLayout(横排(标题, None, self.跟随, self.详细, 隐藏, 关闭))

        状态卡 = QFrame()
        状态卡.setObjectName("卡片")
        状态布局 = QVBoxLayout(状态卡)
        状态布局.setContentsMargins(12, 8, 12, 8)
        self.机器人 = QLabel("城控")
        self.机器人.setObjectName("次要")
        self.状态 = QLabel("未运行")
        状态布局.addLayout(横排(self.机器人, None, self.状态))
        self.阶段 = QLabel("等待任务状态…")
        self.阶段.setWordWrap(True)
        状态布局.addWidget(self.阶段)
        热键 = QLabel("F1 开始／继续    F2 暂停  ·  暂停时游戏计时仍会继续")
        热键.setObjectName("弱")
        状态布局.addWidget(热键)
        布局.addWidget(状态卡)

        self.视图 = 日志视图(深色)
        布局.addWidget(self.视图, 1)
        self.跟随.toggled.connect(lambda 选中: setattr(self.视图, "跟随", 选中))

    def 刷新(self):
        结果 = self.上下文.聚合器.渲染("全部" if self.详细.isChecked() else "重点")
        self.视图.显示(结果, 深色)
        快照 = self.上下文.控制器.快照()
        self.机器人.setText(f"模拟器：{快照.设备描述}")
        self.状态.setText(f"● {快照.状态}")
        self.状态.setStyleSheet(f"color:{状态颜色(深色, 快照.状态)}; font-weight:600;")
        if 快照.状态 == "暂停中":
            self.阶段.setText("已暂停，按 F1 继续；游戏计时不会暂停。")
        elif 快照.状态 == "已停止":
            self.阶段.setText(
                f"停止原因：{快照.停止原因}" if 快照.停止原因 not in ("", "未启动") else "已停止，按 F1 开始。"
            )
        else:
            self.阶段.setText(
                self.上下文.聚合器.当前阶段(self.上下文.控制器.实例ID) or "正在运行，等待下一条关键状态…"
            )

    def closeEvent(self, 事件):
        super().closeEvent(事件)
        self._关闭回调()
