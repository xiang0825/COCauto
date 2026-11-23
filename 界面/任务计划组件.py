"""任务列表与任务设置（MAA 式：左侧勾选排序，中间按任务配置，自动保存）。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QLineEdit, QListWidget,
    QScrollArea,
    QListWidgetItem, QPlainTextEdit, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from 应用 import 任务计划 as 计划
from 界面.组件 import 卡片, 标签, 横排

_键角色 = Qt.UserRole + 1


class 任务计划组件:
    """创建两张卡片：``任务卡``（勾选/排序）和 ``设置卡``（参数表单）。"""

    def __init__(self, 上下文):
        self.上下文 = 上下文
        self._设置 = None
        self._当前页键 = "main_resource"
        self._编辑器: dict[str, QWidget] = {}
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

    # ------------------------------------------------------------ 构建
    def _构建任务卡(self) -> 卡片:
        卡 = 卡片("任务")
        卡.setMinimumWidth(260)
        卡.setMaximumWidth(320)
        self.任务列表 = QListWidget()
        self.任务列表.setDragDropMode(QAbstractItemView.InternalMove)
        self.任务列表.setDefaultDropAction(Qt.MoveAction)
        self.任务列表.itemChanged.connect(self._任务勾选变化)
        self.任务列表.currentItemChanged.connect(self._选中任务)
        self.任务列表.model().rowsMoved.connect(lambda *_: self._安排保存("顺序已调整"))
        卡.布局.addWidget(self.任务列表, 3)
        上移 = QToolButton(); 上移.setText("↑"); 上移.setToolTip("上移"); 上移.clicked.connect(lambda: self._移动(-1))
        下移 = QToolButton(); 下移.setText("↓"); 下移.setToolTip("下移"); 下移.clicked.connect(lambda: self._移动(1))
        全选 = QToolButton(); 全选.setText("全选"); 全选.clicked.connect(lambda: self._全部勾选(True))
        清空 = QToolButton(); 清空.setText("清空"); 清空.clicked.connect(lambda: self._全部勾选(False))
        卡.布局.addLayout(横排(上移, 下移, None, 全选, 清空, 间距=4))
        卡.布局.addWidget(标签("拖动或用箭头调整执行顺序", "弱"))

        卡.布局.addWidget(标签("通用设置", "卡片标题"))
        self.选项列表 = QListWidget()
        self.选项列表.currentItemChanged.connect(self._选中选项)
        for 键 in 计划.全局配置键:
            项 = QListWidgetItem(f"⚙  {计划.任务参数表[键].标题}")
            项.setData(_键角色, 键)
            self.选项列表.addItem(项)
        self.选项列表.setFixedHeight(len(计划.全局配置键) * 38 + 6)
        卡.布局.addWidget(self.选项列表)
        self.服务器 = QComboBox()
        self.服务器.addItems(计划.服务器选项)
        self.服务器.currentTextChanged.connect(lambda _: self._安排保存("服务器已修改"))
        卡.布局.addLayout(横排(标签("服务器", "次要"), self.服务器, None))
        return 卡

    def _构建设置卡(self) -> 卡片:
        卡 = 卡片()
        self.参数标题 = 标签("任务设置", "卡片标题")
        self.参数说明 = 标签("", "次要", 换行=True)
        卡.布局.addWidget(self.参数标题)
        卡.布局.addWidget(self.参数说明)
        self._表单容器 = QWidget()
        self._表单 = QFormLayout(self._表单容器)
        self._表单.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._表单.setHorizontalSpacing(14)
        self._表单.setVerticalSpacing(12)
        卡.布局.addWidget(self._表单容器)
        self._提示区 = QVBoxLayout()
        卡.布局.addLayout(self._提示区)
        卡.布局.addStretch(1)
        self.状态 = 标签("修改会自动保存", "弱", 换行=True)
        立即保存 = QPushButton("立即保存")
        立即保存.clicked.connect(self.保存)
        卡.布局.addLayout(横排(self.状态, None, 立即保存))
        卡.布局.addWidget(标签("启动游戏、登录检查和收集资源是固定步骤，总会先执行。", "弱", 换行=True))
        return 卡

    # ------------------------------------------------------------ 载入
    def 载入(self):
        self._载入中 = True
        try:
            self._设置 = self.控制器.获取设置()
            self.服务器.setCurrentText(getattr(self._设置, "服务器", "国际服") or "国际服")
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
            项 = QListWidgetItem(行.名称)
            项.setData(_键角色, 行.键)
            项.setFlags(项.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            项.setCheckState(Qt.Checked if 行.已启用 else Qt.Unchecked)
            提示 = 行.说明
            if 行.类型 in ("list", "string"):
                提示 += "\n需要在任务设置中填写目标后才会执行。"
            项.setToolTip(提示)
            self.任务列表.addItem(项)
            if 行.键 == 当前键:
                self.任务列表.setCurrentItem(项)
        self.任务列表.blockSignals(False)

    @property
    def 有未保存修改(self) -> bool:
        return self.保存计时.isActive()

    # ------------------------------------------------------------ 交互
    def _选中任务(self, 当前, _之前):
        if 当前 is None:
            return
        self.选项列表.blockSignals(True)
        self.选项列表.setCurrentItem(None)
        self.选项列表.blockSignals(False)
        self._切换参数页(当前.data(_键角色))

    def _选中选项(self, 当前, _之前):
        if 当前 is None:
            return
        self.任务列表.blockSignals(True)
        self.任务列表.setCurrentItem(None)
        self.任务列表.blockSignals(False)
        self._切换参数页(当前.data(_键角色))

    def _切换参数页(self, 键):
        if 键 == self._当前页键 and self._编辑器:
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
        项 = self.任务列表.takeItem(行)
        self.任务列表.insertItem(新行, 项)
        self.任务列表.setCurrentRow(新行)
        self._安排保存("顺序已调整")

    # ------------------------------------------------------------ 表单
    def _清空表单(self):
        while self._表单.rowCount():
            self._表单.removeRow(0)
        while self._提示区.count():
            项 = self._提示区.takeAt(0)
            if 项.widget():
                项.widget().hide()
                项.widget().deleteLater()
        self._编辑器.clear()

    def _显示参数页(self, 键):
        self._当前页键 = 键
        self._清空表单()
        页 = 计划.任务参数表.get(键)
        if self._设置 is None or 页 is None:
            return
        self.参数标题.setText(页.标题)
        self.参数说明.setText(页.说明)
        if not 页.字段:
            self._提示区.addWidget(标签("该任务没有额外参数，勾选左侧即可启用。", "弱"))
        for 字段 in 页.字段:
            编辑器 = self._创建编辑器(字段)
            self._编辑器[字段.字段] = 编辑器
            self._表单.addRow("" if 字段.类型 == "bool" else 字段.标签, 编辑器)
            if 字段.提示:
                self._表单.addRow("", 标签(字段.提示, "弱", 换行=True))
        for 文本 in 页.提示:
            self._提示区.addWidget(标签(文本, "提示条", 换行=True))

    def _创建编辑器(self, 字段: 计划.参数字段) -> QWidget:
        值 = 字段.当前值(self._设置)
        if 字段.类型 == "bool":
            控件 = QCheckBox(字段.标签)
            控件.setChecked(bool(值))
            控件.toggled.connect(lambda _=None: self._安排保存())
        elif 字段.类型 == "choice":
            控件 = QComboBox()
            控件.addItems(list(字段.选项))
            if 值 and str(值) not in 字段.选项:
                控件.addItem(str(值))
            控件.setCurrentText(str(值 or ""))
            控件.currentTextChanged.connect(lambda _=None: self._安排保存())
        elif 字段.类型 == "multi":
            from 任务流程.军队配置 import 兵种资料
            # 兵种多，放进固定高度的滚动区，避免把表单行挤扁。
            控件 = QScrollArea()
            控件.setWidgetResizable(True)
            控件.setFrameShape(QFrame.NoFrame)
            控件.setMinimumHeight(260)
            控件.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            内容 = QWidget()
            网格 = QGridLayout(内容)
            网格.setContentsMargins(0, 0, 8, 0)
            网格.setHorizontalSpacing(12)
            网格.setVerticalSpacing(6)
            控件.setWidget(内容)
            控件.勾选框 = {}
            已选 = set(值 or [])
            for 序号, 名称 in enumerate(字段.选项):
                框 = QCheckBox(兵种资料.显示名(名称))
                职责 = 兵种资料.职责(名称)
                if 职责:
                    框.setToolTip(f"{职责}：{兵种资料.职责说明[职责]}")
                框.setChecked(名称 in 已选)
                框.toggled.connect(lambda _=None: self._安排保存())
                网格.addWidget(框, 序号, 0)
                控件.勾选框[名称] = 框
        elif 字段.类型 == "list":
            控件 = QPlainTextEdit(str(值 or ""))
            控件.setFixedHeight(72)
            控件.setPlaceholderText("例如：弓箭塔、加农炮")
            控件.textChanged.connect(lambda: self._安排保存())
        else:
            控件 = QLineEdit("" if 值 is None else str(值))
            if 字段.类型 == "secret":
                控件.setEchoMode(QLineEdit.Password)
                控件.setPlaceholderText("粘贴 Token")
            if 字段.类型 in ("int", "float"):
                控件.setMaximumWidth(200)
                控件.setAlignment(Qt.AlignRight)
            控件.textEdited.connect(lambda _=None: self._安排保存())
        return 控件

    def _表单值(self) -> dict:
        值 = {}
        for 名称, 控件 in self._编辑器.items():
            if hasattr(控件, "勾选框"):
                值[名称] = [项 for 项, 框 in 控件.勾选框.items() if 框.isChecked()]
            elif isinstance(控件, QCheckBox):
                值[名称] = 控件.isChecked()
            elif isinstance(控件, QComboBox):
                值[名称] = 控件.currentText()
            elif isinstance(控件, QPlainTextEdit):
                值[名称] = 控件.toPlainText()
            else:
                值[名称] = 控件.text()
        return 值

    # ------------------------------------------------------------ 保存
    def _安排保存(self, 说明: str = ""):
        if self._载入中 or self._设置 is None:
            return
        self.状态.setText((说明 + "，" if 说明 else "") + "正在保存…")
        self.保存计时.start()

    def 保存(self) -> bool:
        self.保存计时.stop()
        if self._设置 is None:
            return False
        设置 = self._设置
        try:
            if self._当前页键 in 计划.任务参数表:
                计划.应用参数(设置, self._当前页键, self._表单值())
            顺序 = []
            for 行 in range(self.任务列表.count()):
                项 = self.任务列表.item(行)
                键 = 项.data(_键角色)
                顺序.append(键)
                计划.设置任务开关(设置, 键, 项.checkState() == Qt.Checked)
            if 顺序:
                设置.任务计划顺序 = 顺序
            设置.服务器 = self.服务器.currentText() or "国际服"
            self.控制器.保存设置(设置)
        except ValueError as 异常:
            self.状态.setText(f"未保存：{异常}")
            return False
        except Exception as 异常:
            self.状态.setText(f"保存失败：{异常}")
            self.上下文.记录操作(f"任务设置保存失败：{异常}")
            return False
        self.状态.setText("已自动保存")
        self.上下文.记录操作("任务设置已保存")
        # 同步 list/string 任务的真实启用状态（目标为空时不会启用）。
        缺目标 = []
        self._载入中 = True
        try:
            for 行 in range(self.任务列表.count()):
                项 = self.任务列表.item(行)
                启用 = 计划.任务计划是否启用(设置, 项.data(_键角色))
                if 项.checkState() == Qt.Checked and not 启用:
                    缺目标.append(项.text())
                项.setCheckState(Qt.Checked if 启用 else Qt.Unchecked)
        finally:
            self._载入中 = False
        if 缺目标:
            self.状态.setText(f"已保存；“{'、'.join(缺目标)}”需要先填写目标才会启用")
        return True
