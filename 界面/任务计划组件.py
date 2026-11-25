"""任务列表与常用参数（MAA 式：左侧勾选排序，中间选中任务的常用参数，自动保存）。

高级参数在「高级设置」窗口里编辑，但与这里共用同一个设置对象和保存入口，
两边不会互相覆盖。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QListWidget, QListWidgetItem, QMenu, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from 应用 import 任务计划 as 计划
from 界面.参数表单 import 参数表单
from 界面.组件 import 卡片, 标签, 横排

_键角色 = Qt.UserRole + 1

# 列表里用短名称，窄栏也不换行；完整名称在提示里。
任务短名 = {
    "event": "部落竞赛",
    "building": "建议升级建筑",
    "hero": "英雄/建筑升级",
    "research": "兵种/法术研究",
}


class 任务计划组件:
    """创建两张卡片：``任务卡``（勾选/排序）和 ``设置卡``（选中任务的常用参数）。"""

    def __init__(self, 上下文, 打开高级设置=None):
        self.上下文 = 上下文
        self._打开高级设置 = 打开高级设置
        self._设置 = None
        self._当前页键 = "main_resource"
        self._载入中 = False
        self.保存计时 = QTimer()
        self.保存计时.setSingleShot(True)
        self.保存计时.setInterval(600)
        self.保存计时.timeout.connect(self.保存)
        self.任务卡 = self._构建任务卡()
        self.设置卡 = self._构建设置卡()

    @property
    def 控制器(self):
        return self.上下文.控制器

    @property
    def 设置(self):
        return self._设置

    @property
    def _编辑器(self):
        return self.表单.编辑器

    # ------------------------------------------------------------ 构建
    def _构建任务卡(self) -> 卡片:
        卡 = 卡片("任务", 边距=14)
        卡.setMinimumWidth(190)
        卡.setMaximumWidth(240)
        self.任务列表 = QListWidget()
        self.任务列表.setObjectName("任务列表")
        self.任务列表.setDragDropMode(QAbstractItemView.InternalMove)
        self.任务列表.setDefaultDropAction(Qt.MoveAction)
        self.任务列表.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.任务列表.setContextMenuPolicy(Qt.CustomContextMenu)
        self.任务列表.customContextMenuRequested.connect(self._右键菜单)
        self.任务列表.itemChanged.connect(self._任务勾选变化)
        self.任务列表.currentItemChanged.connect(self._选中任务)
        self.任务列表.model().rowsMoved.connect(lambda *_: self._安排保存("顺序已调整"))
        卡.布局.addWidget(self.任务列表, 1)
        卡.布局.addWidget(标签("拖动调整顺序 · 右键全选/清空", "弱", 换行=True))
        卡.布局.addWidget(标签("启动游戏、收集资源总会先执行", "弱", 换行=True))
        return 卡

    def _构建设置卡(self) -> 卡片:
        卡 = 卡片(边距=14)
        卡.setMinimumWidth(250)
        self.参数标题 = 标签("任务设置", "卡片标题")
        self.参数说明 = 标签("", "弱", 换行=True)
        卡.布局.addWidget(self.参数标题)
        卡.布局.addWidget(self.参数说明)
        self.表单 = 参数表单(self._安排保存, 多选列数=1)
        内容 = QWidget()
        内容布局 = QVBoxLayout(内容)
        内容布局.setContentsMargins(0, 0, 8, 0)
        内容布局.addWidget(self.表单)
        self._参数滚动区 = QScrollArea()
        self._参数滚动区.setWidgetResizable(True)
        self._参数滚动区.setFrameShape(QFrame.NoFrame)
        self._参数滚动区.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._参数滚动区.setWidget(内容)
        卡.布局.addWidget(self._参数滚动区, 1)
        self.状态 = 标签("修改会自动保存", "弱", 换行=True)
        更多 = QPushButton("更多参数 ›")
        更多.setObjectName("链接")
        更多.setToolTip("在高级设置里编辑其余参数")
        更多.clicked.connect(self._更多参数)
        卡.布局.addLayout(横排(self.状态, None, 更多))
        return 卡

    # ------------------------------------------------------------ 载入
    def 载入(self):
        self._载入中 = True
        try:
            self._设置 = self.控制器.获取设置()
            self._重建任务列表()
            self._显示参数页(self._当前页键)
            self.状态.setText("修改会自动保存")
        finally:
            self._载入中 = False

    def _重建任务列表(self):
        当前键 = self._当前页键
        self.任务列表.blockSignals(True)
        self.任务列表.clear()
        for 行 in 计划.任务行列表(self._设置):
            项 = QListWidgetItem(任务短名.get(行.键, 行.名称))
            项.setData(_键角色, 行.键)
            项.setFlags(项.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            项.setCheckState(Qt.Checked if 行.已启用 else Qt.Unchecked)
            提示 = f"{行.名称}：{行.说明}"
            if 行.类型 in ("list", "string"):
                提示 += "\n需要先填写目标才会执行。"
            项.setToolTip(提示)
            self.任务列表.addItem(项)
            if 行.键 == 当前键:
                self.任务列表.setCurrentItem(项)
        self.任务列表.blockSignals(False)

    @property
    def 有未保存修改(self) -> bool:
        return self.保存计时.isActive()

    # ------------------------------------------------------------ 交互
    def 选择任务(self, 键: str) -> bool:
        for 行 in range(self.任务列表.count()):
            if self.任务列表.item(行).data(_键角色) == 键:
                self.任务列表.setCurrentRow(行)
                return True
        return False

    def _选中任务(self, 当前, _之前):
        if 当前 is None:
            return
        键 = 当前.data(_键角色)
        if 键 == self._当前页键 and self.表单.页 is not None:
            return
        if self.保存计时.isActive():
            self.保存()
        self._显示参数页(键)

    def _任务勾选变化(self, 项: QListWidgetItem):
        if self._载入中:
            return
        键 = 项.data(_键角色)
        if 项.checkState() == Qt.Checked and 键 in ("hero", "pet", "research"):
            if not 计划.任务计划是否启用(self._设置, 键):
                self.任务列表.setCurrentItem(项)
                self.状态.setText(f"请为“{计划.任务参数表[键].标题}”填写目标，填写后即启用")
        self._安排保存("任务开关已修改")

    def _右键菜单(self, 位置):
        菜单 = QMenu(self.任务列表)
        菜单.addAction("全部勾选", lambda: self._全部勾选(True))
        菜单.addAction("全部取消", lambda: self._全部勾选(False))
        菜单.addSeparator()
        菜单.addAction("上移", lambda: self._移动(-1))
        菜单.addAction("下移", lambda: self._移动(1))
        菜单.exec(self.任务列表.viewport().mapToGlobal(位置))

    def _全部勾选(self, 勾选: bool):
        self._载入中 = True
        for 行 in range(self.任务列表.count()):
            self.任务列表.item(行).setCheckState(Qt.Checked if 勾选 else Qt.Unchecked)
        self._载入中 = False
        self._安排保存("已全选" if 勾选 else "已清空")

    def _移动(self, 方向: int):
        行 = self.任务列表.currentRow()
        新行 = 行 + 方向
        if 行 < 0 or not 0 <= 新行 < self.任务列表.count():
            return
        self.任务列表.blockSignals(True)
        项 = self.任务列表.takeItem(行)
        self.任务列表.insertItem(新行, 项)
        self.任务列表.setCurrentRow(新行)
        self.任务列表.blockSignals(False)
        self._安排保存("顺序已调整")

    def _更多参数(self):
        if self._打开高级设置 is not None:
            self._打开高级设置(self._当前页键)

    # ------------------------------------------------------------ 表单
    def _显示参数页(self, 键):
        self._当前页键 = 键
        页 = 计划.主界面参数表.get(键)
        if self._设置 is None or 页 is None:
            self.表单.清空()
            return
        self.参数标题.setText(页.标题)
        self.参数说明.setText(页.说明)
        self.表单.显示(页, self._设置)

    # ------------------------------------------------------------ 保存
    def _安排保存(self, 说明: str = ""):
        if self._载入中 or self._设置 is None:
            return
        self.状态.setText((说明 + "，" if 说明 else "") + "正在保存…")
        self.保存计时.start()

    def _写入任务列表(self, 设置):
        顺序 = []
        for 行 in range(self.任务列表.count()):
            项 = self.任务列表.item(行)
            键 = 项.data(_键角色)
            顺序.append(键)
            计划.设置任务开关(设置, 键, 项.checkState() == Qt.Checked)
        if 顺序:
            设置.任务计划顺序 = 顺序

    def 保存(self) -> bool:
        self.保存计时.stop()
        if self._设置 is None:
            return False
        设置 = self._设置
        try:
            if self._当前页键 in 计划.主界面参数表 and self.表单.页 is not None:
                计划.应用参数(设置, self._当前页键, self.表单.表单值())
            self._写入任务列表(设置)
            self.控制器.保存任务设置(设置)
        except ValueError as 异常:
            self.状态.setText(f"未保存：{异常}")
            return False
        except Exception as 异常:
            self.状态.setText(f"保存失败：{异常}")
            self.上下文.记录操作(f"任务设置保存失败：{异常}")
            return False
        self.状态.setText("✓ 已自动保存")
        self.上下文.记录操作("任务设置已保存")
        self._同步启用状态()
        return True

    def 保存外部修改(self, 修改) -> str | None:
        """高级设置窗口用：在同一个设置对象上应用 ``修改(设置)`` 并保存，失败返回原因。"""
        if self._设置 is None:
            return "设置尚未载入"
        if self.保存计时.isActive():
            self.保存()
        try:
            修改(self._设置)
            self.控制器.保存任务设置(self._设置)
        except ValueError as 异常:
            return str(异常)
        except Exception as 异常:
            self.上下文.记录操作(f"高级设置保存失败：{异常}")
            return f"保存失败：{异常}"
        self.上下文.记录操作("高级设置已保存")
        # 主界面表单可能显示同一字段（如资源打满后动作），重新渲染保持一致。
        self._载入中 = True
        try:
            self._显示参数页(self._当前页键)
        finally:
            self._载入中 = False
        return None

    def _同步启用状态(self):
        """同步 list/string 任务的真实启用状态（目标为空时不会启用）。"""
        缺目标 = []
        self._载入中 = True
        try:
            for 行 in range(self.任务列表.count()):
                项 = self.任务列表.item(行)
                启用 = 计划.任务计划是否启用(self._设置, 项.data(_键角色))
                if 项.checkState() == Qt.Checked and not 启用:
                    缺目标.append(项.text())
                项.setCheckState(Qt.Checked if 启用 else Qt.Unchecked)
        finally:
            self._载入中 = False
        if 缺目标:
            self.状态.setText(f"已保存；“{'、'.join(缺目标)}”需要先填写目标才会启用")
