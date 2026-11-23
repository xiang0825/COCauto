"""一键运行（MAA 式主页）：任务 · 任务设置 · 运行状态与日志，一屏完成。"""
from __future__ import annotations

import time

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QPushButton, QVBoxLayout

from 界面.任务计划组件 import 任务计划组件
from 界面.日志视图 import 日志视图
from 界面.页面基类 import 页面基类
from 界面.组件 import 卡片, 标签, 状态胶囊, 横排


class 运行页(页面基类):
    标题 = "一键运行"
    说明 = "勾选任务并排好顺序，点击右上角“开始”。只运行你勾选的任务。"

    def __init__(self, 上下文, 打开悬浮窗):
        super().__init__(上下文, 可滚动=False)
        self.计划 = 任务计划组件(上下文)

        主体 = QHBoxLayout()
        主体.setSpacing(14)
        主体.addWidget(self.计划.任务卡)
        主体.addWidget(self.计划.设置卡, 4)

        右栏 = QVBoxLayout()
        右栏.setSpacing(14)
        状态卡 = 卡片("运行状态")
        self.状态 = 状态胶囊(上下文.配色)
        self.设备 = 标签("", "次要")
        状态卡.布局.addLayout(横排(self.状态, None, self.设备))
        self.阶段 = 标签("", 换行=True)
        状态卡.布局.addWidget(self.阶段)
        self.阶段时间 = 标签("", "弱")
        状态卡.布局.addWidget(self.阶段时间)
        右栏.addWidget(状态卡)

        日志卡 = 卡片("日志")
        self.详细 = QCheckBox("详细")
        self.详细.setToolTip("显示全部日志，包括高频的页面识别记录")
        self.详细.toggled.connect(lambda _: self.刷新日志(强制=True))
        self.跟随 = QCheckBox("跟随")
        self.跟随.setChecked(True)
        self.跟随.toggled.connect(self._跟随变化)
        悬浮 = QPushButton("悬浮窗")
        悬浮.setToolTip("置顶半透明日志窗，边看游戏边看日志")
        悬浮.clicked.connect(打开悬浮窗)
        清空 = QPushButton("清空")
        清空.setToolTip("只清除显示，不删除历史记录")
        清空.clicked.connect(self._清空)
        日志卡.布局.addLayout(横排(self.跟随, self.详细, None, 悬浮, 清空, 间距=6))
        self.视图 = 日志视图(上下文.配色)
        日志卡.布局.addWidget(self.视图, 1)
        右栏.addWidget(日志卡, 1)
        主体.addLayout(右栏, 5)
        self.布局.addLayout(主体, 1)

    # ------------------------------------------------------------ 生命周期
    def 载入(self):
        self.计划.载入()
        self.定时刷新()

    def 页面显示(self):
        if not self.计划.有未保存修改:
            self.计划.载入()
        self.刷新日志(强制=True)

    def 应用配色(self, 色):
        self.状态.应用配色(色)
        self.视图.应用配色(色)
        self.刷新日志(强制=True)

    def 定时刷新(self):
        快照 = self.控制器.快照()
        self.状态.设置(快照.状态)
        self.设备.setText(f"模拟器：{快照.设备描述}")
        if 快照.状态 == "已停止":
            原因 = 快照.停止原因
            self.阶段.setText(
                "尚未开始。确认模拟器后点击“开始”。" if 原因 in ("", "未启动")
                else f"停止原因：{原因}"
            )
        elif 快照.状态 == "暂停中":
            self.阶段.setText("已暂停，按 F1 或“继续”恢复；游戏倒计时不会暂停。")
        else:
            self.阶段.setText(
                self.上下文.聚合器.当前阶段(self.控制器.实例ID) or "正在运行，等待下一条关键状态…"
            )
        self.阶段时间.setText(
            "最近事件 " + time.strftime("%H:%M:%S", time.localtime(快照.最近日志时间))
            if 快照.最近日志时间 else ""
        )
        self.刷新日志()

    # ------------------------------------------------------------ 日志
    def _跟随变化(self, 选中):
        self.视图.跟随 = 选中
        if 选中:
            self.刷新日志(强制=True)

    def _清空(self):
        self.上下文.聚合器.清空显示()
        self.刷新日志(强制=True)

    def 刷新日志(self, 强制: bool = False):
        结果 = self.上下文.聚合器.渲染("全部" if self.详细.isChecked() else "重点")
        if 强制:
            self.视图.应用配色(self.上下文.配色)
        self.视图.显示(结果, self.上下文.配色)
