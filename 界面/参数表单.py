"""按 ``参数页`` 自动生成的参数表单（主界面常用参数与高级设置共用）。

标签放在控件上方、逐行纵向排列：窄栏里也不会出现 QFormLayout 换行时
标签与控件重叠的问题；多选项（兵种、白名单）按可用宽度分列。
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QLabel, QLineEdit, QPlainTextEdit,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from 应用 import 任务计划 as 计划
from 界面.组件 import 标签


class 参数表单(QWidget):
    """显示一页参数；任何修改都调用 ``修改回调``。"""

    def __init__(self, 修改回调: Callable[[], None], 多选列数: int = 1, 显示提示: bool = True, 父=None):
        super().__init__(父)
        self._修改回调 = 修改回调
        self._多选列数 = max(1, 多选列数)
        self._显示提示 = 显示提示
        self.编辑器: dict[str, QWidget] = {}
        self.页: 计划.参数页 | None = None
        self._布局 = QVBoxLayout(self)
        self._布局.setContentsMargins(0, 0, 0, 0)
        self._布局.setSpacing(10)

    # ------------------------------------------------------------ 构建
    def 清空(self):
        while self._布局.count():
            项 = self._布局.takeAt(0)
            控件 = 项.widget()
            if 控件 is not None:
                控件.hide()
                控件.deleteLater()
        self.编辑器.clear()
        self.页 = None

    def 显示(self, 页: 计划.参数页, 设置):
        self.清空()
        self.页 = 页
        if not 页.字段:
            self._布局.addWidget(标签("该任务没有额外参数，勾选即可启用。", "弱", 换行=True))
        for 字段 in 页.字段:
            编辑器 = self._创建编辑器(字段, 设置)
            self.编辑器[字段.字段] = 编辑器
            行 = QWidget()
            行布局 = QVBoxLayout(行)
            行布局.setContentsMargins(0, 0, 0, 0)
            行布局.setSpacing(4)
            if 字段.类型 != "bool":
                名 = QLabel(字段.标签)
                名.setObjectName("次要")
                行布局.addWidget(名)
            行布局.addWidget(编辑器)
            if 字段.提示:
                行布局.addWidget(标签(字段.提示, "弱", 换行=True))
            self._布局.addWidget(行)
        if self._显示提示:
            for 文本 in 页.提示:
                self._布局.addWidget(标签(文本, "提示条", 换行=True))
        self._布局.addStretch(1)

    def _创建编辑器(self, 字段: 计划.参数字段, 设置) -> QWidget:
        值 = 字段.当前值(设置)
        if 字段.类型 == "bool":
            控件 = QCheckBox(字段.标签)
            控件.setChecked(bool(值))
            控件.toggled.connect(lambda _=None: self._修改回调())
        elif 字段.类型 == "choice":
            控件 = QComboBox()
            控件.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            控件.setMinimumContentsLength(6)
            控件.addItems(list(字段.选项))
            if 值 and str(值) not in 字段.选项:
                控件.addItem(str(值))
            控件.setCurrentText(str(值 or ""))
            控件.currentTextChanged.connect(lambda _=None: self._修改回调())
        elif 字段.类型 == "multi":
            控件 = self._创建多选(字段, 值)
        elif 字段.类型 == "list":
            控件 = QPlainTextEdit(str(值 or ""))
            控件.setFixedHeight(64)
            控件.setPlaceholderText("例如：弓箭塔、加农炮")
            控件.textChanged.connect(lambda: self._修改回调())
        else:
            控件 = QLineEdit("" if 值 is None else str(值))
            if 字段.类型 == "secret":
                控件.setEchoMode(QLineEdit.Password)
                控件.setPlaceholderText("粘贴 Token")
            if 字段.类型 in ("int", "float"):
                控件.setMaximumWidth(220)
            控件.textEdited.connect(lambda _=None: self._修改回调())
        return 控件

    def _创建多选(self, 字段: 计划.参数字段, 值) -> QWidget:
        from 任务流程.军队配置 import 兵种资料

        控件 = QScrollArea()
        控件.setWidgetResizable(True)
        控件.setFrameShape(QFrame.NoFrame)
        控件.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        行数 = -(-len(字段.选项) // self._多选列数)
        控件.setFixedHeight(min(行数, 7) * 28 + 6)
        内容 = QWidget()
        内容.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        网格 = QGridLayout(内容)
        网格.setContentsMargins(0, 0, 8, 0)
        网格.setHorizontalSpacing(14)
        网格.setVerticalSpacing(6)
        控件.setWidget(内容)
        控件.勾选框 = {}
        已选 = set(值 or [])
        for 序号, 名称 in enumerate(字段.选项):
            框 = QCheckBox(兵种资料.显示名(名称))
            职责 = 兵种资料.职责(名称)
            法术职责 = 兵种资料.法术职责(名称)
            if 职责:
                框.setToolTip(f"{职责}：{兵种资料.职责说明[职责]}")
            elif 法术职责:
                框.setToolTip(f"{法术职责}：{兵种资料.法术职责说明[法术职责]}")
            框.setChecked(名称 in 已选)
            框.toggled.connect(lambda _=None: self._修改回调())
            网格.addWidget(框, 序号 // self._多选列数, 序号 % self._多选列数)
            控件.勾选框[名称] = 框
        return 控件

    # ------------------------------------------------------------ 读取
    def 表单值(self) -> dict:
        值 = {}
        for 名称, 控件 in self.编辑器.items():
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
