"""一键运行（MAA 式单屏）：任务 · 常用参数 · 日志 三栏。

运行状态、今日数据和提醒在主窗口顶部；这里只放三栏内容。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton

from 应用.日志模型 import 筛选模式列表
from 界面.任务计划组件 import 任务计划组件
from 界面.日志视图 import 日志视图
from 界面.页面基类 import 页面基类
from 界面.组件 import 卡片, 标签, 横排


class 运行页(页面基类):
    标题 = "一键运行"
    说明 = "勾选任务并排好顺序，点击“开始”。只运行你勾选的任务。"

    def __init__(self, 上下文, 打开悬浮窗, 打开高级设置=None):
        super().__init__(上下文, 可滚动=False)
        self.布局.setContentsMargins(14, 10, 14, 12)
        self.计划 = 任务计划组件(上下文, 打开高级设置)
        self._模式 = "重点"

        主体 = QHBoxLayout()
        主体.setSpacing(10)
        主体.addWidget(self.计划.任务卡, 0)
        主体.addWidget(self.计划.设置卡, 4)

        日志卡 = 卡片(边距=14)
        日志卡.setMinimumWidth(260)
        self._模式组 = QButtonGroup(self)
        self._模式组.setExclusive(True)
        self.模式按钮: dict[str, QPushButton] = {}
        for 模式 in 筛选模式列表:
            按钮 = QPushButton(模式)
            按钮.setObjectName("分段")
            按钮.setCheckable(True)
            按钮.setChecked(模式 == self._模式)
            按钮.clicked.connect(lambda _=False, 名=模式: self.切换模式(名))
            self._模式组.addButton(按钮)
            self.模式按钮[模式] = 按钮
        悬浮 = QPushButton("悬浮")
        悬浮.setObjectName("分段")
        悬浮.setToolTip("置顶半透明日志窗，边看游戏边看日志")
        悬浮.clicked.connect(打开悬浮窗)
        日志卡.布局.addLayout(横排(
            标签("日志", "卡片标题"), None, *self.模式按钮.values(), 悬浮, 间距=4,
        ))
        self.视图 = 日志视图(上下文.配色)
        self.视图.自动跟随 = True
        self.视图.setContextMenuPolicy(Qt.CustomContextMenu)
        self.视图.customContextMenuRequested.connect(self._右键菜单)
        # 异常行“现场图”链接：按日志时间就近匹配 数据集/待命现场、低星复盘 的截图。
        self.现场图 = None
        try:
            from 界面.方案A部件 import 现场图索引

            self.现场图 = 现场图索引()
            self.视图.现场图查找 = self.现场图.查找
        except Exception:
            self.现场图 = None
        self.视图.请求现场图.connect(self.打开现场图)
        self._现场图数量 = 0
        日志卡.布局.addWidget(self.视图, 1)
        主体.addWidget(日志卡, 5)
        self.布局.addLayout(主体, 1)

    # ------------------------------------------------------------ 生命周期
    def 载入(self):
        self.计划.载入()
        self.刷新日志(强制=True)

    def 页面显示(self):
        if not self.计划.有未保存修改:
            self.计划.载入()
        self.刷新日志(强制=True)

    def 应用配色(self, 色):
        self.视图.应用配色(色)
        self.计划._刷新运行标记()
        self.刷新日志(强制=True)

    def 定时刷新(self):
        if self.现场图 is not None:
            self.现场图.刷新()
            数量 = len(self.现场图._条目)
            if 数量 != self._现场图数量:
                self._现场图数量 = 数量
                self.视图.现场图版本 += 1
        self.刷新日志()

    def 打开现场图(self, 时间戳: float, 日志文本: str):
        if self.现场图 is None:
            return None
        条目 = self.现场图.查找(时间戳)
        if 条目 is None:
            return None
        from 界面.方案A部件 import 打开现场图

        return 打开现场图(条目, 日志文本, self)

    # ------------------------------------------------------------ 日志
    @property
    def 模式(self) -> str:
        return self._模式

    def 切换模式(self, 模式: str):
        self._模式 = 模式
        self.模式按钮[模式].setChecked(True)
        self.刷新日志(强制=True)

    def _右键菜单(self, 位置):
        菜单 = self.视图.createStandardContextMenu()
        菜单.addSeparator()
        菜单.addAction("清空显示（不删除历史）", self._清空)
        菜单.exec(self.视图.viewport().mapToGlobal(位置))

    def _清空(self):
        self.上下文.聚合器.清空显示()
        self.刷新日志(强制=True)

    def 刷新日志(self, 强制: bool = False):
        结果 = self.上下文.聚合器.渲染(self._模式)
        if 强制:
            self.视图.应用配色(self.上下文.配色)
        self.视图.显示(结果, self.上下文.配色)
