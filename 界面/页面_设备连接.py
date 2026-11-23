"""模拟器连接（MAA 式）：一键检测并连接；手动连接放在“高级”里。"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from 应用 import 设备服务 as 服务模块
from 应用.设备服务 import 设备服务, 连接表单
from 界面.页面基类 import 页面基类
from 界面.组件 import BGR转图像, 卡片, 后台执行, 提示错误, 标签, 横排, 确认

_条目角色 = Qt.UserRole + 1


class _进度信号(QObject):
    文本 = Signal(str)


class 设备连接页(页面基类):
    标题 = "模拟器连接"
    说明 = "点“一键检测并连接”即可：自动找到模拟器、连上 ADB，并选出正在运行部落冲突的那台。"

    def __init__(self, 上下文):
        super().__init__(上下文)
        self._机器人ID = None
        self._服务 = 设备服务(上下文.控制器.数据库)
        self._设备信息 = {}
        self._原图: QPixmap | None = None
        self._忙 = False
        self._检测adb = ""
        self._进度 = _进度信号()
        self._进度.文本.connect(self._追加检测日志, Qt.QueuedConnection)

        主体 = QHBoxLayout()
        主体.setSpacing(16)
        左 = QVBoxLayout()
        左.setSpacing(16)
        左.addWidget(self._构建一键卡())
        左.addWidget(self._构建高级卡())
        左.addStretch(1)
        左容器 = QWidget()
        左容器.setLayout(左)
        左容器.setMinimumWidth(430)
        左容器.setMaximumWidth(520)
        主体.addWidget(左容器)
        主体.addWidget(self._构建预览卡(), 1)
        self.布局.addLayout(主体, 1)

    # ================================================================ 构建
    def _构建一键卡(self) -> 卡片:
        卡 = 卡片("一键连接")
        self.当前连接 = 标签("当前：未连接", "次要", 换行=True)
        卡.布局.addWidget(self.当前连接)
        self.检测按钮 = QPushButton("一键检测并连接")
        self.检测按钮.setObjectName("主按钮")
        self.检测按钮.clicked.connect(self.一键检测)
        重启 = QPushButton("重启 ADB")
        重启.setToolTip("连不上或设备显示 offline 时使用；只影响本程序专用的 ADB 服务")
        重启.clicked.connect(self._重启ADB)
        卡.布局.addLayout(横排(self.检测按钮, 重启, None))
        self.结果列表 = QListWidget()
        self.结果列表.setFixedHeight(140)
        self.结果列表.itemSelectionChanged.connect(self._结果选择变化)
        self.结果列表.itemDoubleClicked.connect(lambda _: self._使用所选())
        卡.布局.addWidget(self.结果列表)
        self.使用按钮 = QPushButton("使用所选设备")
        self.使用按钮.setEnabled(False)
        self.使用按钮.clicked.connect(self._使用所选)
        卡.布局.addLayout(横排(self.使用按钮, None))
        self.检测日志 = 标签("尚未检测。", "弱", 换行=True)
        卡.布局.addWidget(self.检测日志)
        self.自动检测 = QCheckBox("开始任务时自动检测连接（设备变化时自动重新绑定）")
        self.自动检测.setChecked(True)
        self.自动检测.toggled.connect(self._自动检测变化)
        卡.布局.addWidget(self.自动检测)
        return 卡

    def _构建高级卡(self) -> 卡片:
        卡 = 卡片()
        self._高级开关 = QToolButton()
        self._高级开关.setText("▸ 手动连接（高级）")
        self._高级开关.setCheckable(True)
        self._高级开关.setStyleSheet("QToolButton { border: none; font-weight: 600; }")
        self._高级开关.toggled.connect(self._切换高级)
        卡.布局.addWidget(self._高级开关)
        self._高级区 = QWidget()
        区 = QVBoxLayout(self._高级区)
        区.setContentsMargins(0, 0, 0, 0)
        表单 = QFormLayout()
        表单.setVerticalSpacing(10)
        表单.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        表单.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.adb路径 = QLineEdit()
        self.adb路径.setPlaceholderText("模拟器目录里的 adb.exe")
        浏览 = QPushButton("浏览…")
        浏览.clicked.connect(self._浏览)
        表单.addRow("ADB 程序", 横排(self.adb路径, 浏览, 间距=6))
        self.网络地址 = QLineEdit()
        self.网络地址.setPlaceholderText("127.0.0.1:16384")
        连接 = QPushButton("连接")
        连接.clicked.connect(self._连接地址)
        表单.addRow("连接地址", 横排(self.网络地址, 连接, 间距=6))
        self.设备 = QComboBox()
        self.设备.currentTextChanged.connect(self._设备变化)
        扫描 = QPushButton("扫描")
        扫描.clicked.connect(self.扫描)
        表单.addRow("设备", 横排(self.设备, 扫描, 间距=6))
        区.addLayout(表单)
        self.设备描述 = 标签("", "弱", 换行=True)
        区.addWidget(self.设备描述)
        self.已确认 = QCheckBox("我确认这是 Android 模拟器（不是实体手机）")
        self.已确认.toggled.connect(self._确认变化)
        区.addWidget(self.已确认)
        保存 = QPushButton("保存手动连接")
        保存.clicked.connect(self.保存)
        区.addLayout(横排(保存, None))
        卡.布局.addWidget(self._高级区)
        self._高级区.setVisible(False)
        return 卡

    def _构建预览卡(self) -> 卡片:
        卡 = 卡片("画面预览")
        self.预览 = QLabel("连接后点击“测试截图”核对画面。")
        self.预览.setObjectName("弱")
        self.预览.setAlignment(Qt.AlignCenter)
        self.预览.setMinimumSize(320, 240)
        self.预览.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        卡.布局.addWidget(self.预览, 1)
        self.截图按钮 = QPushButton("测试截图")
        self.截图按钮.clicked.connect(self.测试截图)
        self.预览尺寸 = 标签("未获取截图", "弱")
        卡.布局.addLayout(横排(self.截图按钮, None, self.预览尺寸))
        self.状态 = 标签("", "次要", 换行=True)
        卡.布局.addWidget(self.状态)
        return 卡

    # ================================================================ 载入
    def 载入(self):
        self._机器人ID = self.控制器.实例ID
        self._原图 = None
        self.预览.setPixmap(QPixmap())
        self.预览.setText("连接后点击“测试截图”核对画面。")
        self.预览尺寸.setText("未获取截图")
        self._刷新当前连接()

    def _刷新当前连接(self):
        self.控制器.设置已变更()
        表单 = self._服务.读取表单(self._机器人ID)
        self.adb路径.setText(表单.adb路径)
        self.自动检测.blockSignals(True)
        self.自动检测.setChecked(表单.自动检测路径)
        self.自动检测.blockSignals(False)
        self.设备.blockSignals(True)
        self.设备.clear()
        if 表单.设备序列号:
            self.设备.addItem(表单.设备序列号)
        self.设备.blockSignals(False)
        self.已确认.blockSignals(True)
        self.已确认.setChecked(表单.已确认模拟器)
        self.已确认.blockSignals(False)
        if 表单.设备序列号 and 表单.已确认模拟器:
            self.当前连接.setText(f"当前：{表单.设备序列号}（已确认为模拟器）")
        elif 表单.设备序列号:
            self.当前连接.setText(f"当前：{表单.设备序列号}（尚未确认为模拟器）")
        else:
            self.当前连接.setText("当前：未连接。开始任务时会自动检测，也可以现在点“一键检测并连接”。")

    def _表单(self) -> 连接表单:
        return 连接表单(
            adb路径=self.adb路径.text().strip(),
            自动检测路径=self.自动检测.isChecked(),
            设备序列号=self.设备.currentText().strip(),
            已确认模拟器=self.已确认.isChecked(),
        )

    def _后台(self, 提示: str, 工作, 完成, 显示=None):
        显示 = 显示 or self.状态
        if self._忙:
            显示.setText("上一个操作仍在进行，请稍候…")
            return
        self._忙 = True
        self.检测按钮.setEnabled(False)
        显示.setText(提示)

        def 成功(结果):
            self._忙 = False
            self.检测按钮.setEnabled(True)
            完成(结果)

        def 失败(信息):
            self._忙 = False
            self.检测按钮.setEnabled(True)
            显示.setText(f"失败：{信息}")

        后台执行(工作, 成功, 失败)

    # ================================================================ 一键检测
    def 一键检测(self):
        self.结果列表.clear()
        self.使用按钮.setEnabled(False)
        self._检测日志行: list[str] = []
        机器人ID = self._机器人ID
        数据库 = self.控制器.数据库

        def 工作():
            return 服务模块.一键检测(数据库, 机器人ID, 进度=self._进度.文本.emit)

        self._后台("正在查找模拟器…", 工作, self._检测完成, 显示=self.检测日志)

    def _追加检测日志(self, 文本: str):
        行 = getattr(self, "_检测日志行", [])
        行.append(文本)
        self._检测日志行 = 行[-6:]
        self.检测日志.setText("\n".join(self._检测日志行))

    def _检测完成(self, 结果):
        self._检测adb = 结果.adb路径
        self.检测日志.setText("\n".join(结果.日志[-6:]))
        for 条目 in 结果.条目:
            项 = QListWidgetItem(条目.显示文本)
            项.setData(_条目角色, 条目)
            项.setToolTip(f"{条目.说明}\n{条目.设备.显示文本}")
            self.结果列表.addItem(项)
            if 条目.推荐:
                self.结果列表.setCurrentItem(项)
        推荐 = 结果.推荐
        if 推荐 is not None:
            self._保存检测(推荐)
            self.上下文.记录操作(f"一键连接：{推荐.显示文本}")

    def _结果选择变化(self):
        self.使用按钮.setEnabled(self.结果列表.currentItem() is not None)

    def _使用所选(self):
        项 = self.结果列表.currentItem()
        if 项 is None:
            return
        条目 = 项.data(_条目角色)
        if 条目.类型 == "设备" and not 确认(
            self, "确认目标",
            f"{条目.序列号} 不是从已知模拟器端口发现的设备。\n确认它是 Android 模拟器（不是实体手机）？",
        ):
            return
        self._保存检测(条目)
        self.上下文.记录操作(f"已选择设备：{条目.序列号}")

    def _保存检测(self, 条目):
        try:
            服务模块.使用检测结果(self.控制器.数据库, self._机器人ID, self._检测adb, 条目.序列号)
        except Exception as 异常:
            提示错误(self, "保存失败", str(异常))
            return
        self._刷新当前连接()
        self.状态.setText(f"已连接 {条目.序列号}。可以点“测试截图”核对画面。")

    def _自动检测变化(self, 选中):
        try:
            服务模块.设置自动检测(self.控制器.数据库, self._机器人ID, 选中)
        except Exception as 异常:
            提示错误(self, "保存失败", str(异常))

    def _重启ADB(self):
        路径 = self._检测adb or self.adb路径.text().strip()
        self._后台("正在重启 ADB 服务…", lambda: 服务模块.重启ADB(路径), self.状态.setText)

    # ================================================================ 手动
    def _切换高级(self, 展开):
        self._高级开关.setText(("▾" if 展开 else "▸") + " 手动连接（高级）")
        self._高级区.setVisible(展开)

    def _浏览(self):
        路径, _ = QFileDialog.getOpenFileName(self, "选择模拟器目录中的 adb.exe", "", "ADB 程序 (adb.exe HD-Adb.exe nox_adb.exe);;所有文件 (*.*)")
        if 路径:
            self.adb路径.setText(路径)

    def 扫描(self):
        表单 = self._表单()

        def 完成(结果):
            self.adb路径.setText(结果.adb路径)
            self._设备信息 = {设备.序列号: 设备 for 设备 in 结果.设备}
            原选择 = self.设备.currentText()
            self.设备.blockSignals(True)
            self.设备.clear()
            self.设备.addItems(list(self._设备信息))
            # 不替用户自动选中设备，防止把连接中的实体手机当模拟器。
            if 原选择 in self._设备信息:
                self.设备.setCurrentText(原选择)
            else:
                self.设备.setCurrentIndex(-1)
            self.设备.blockSignals(False)
            self.设备描述.setText("\n".join(设备.显示文本 for 设备 in 结果.设备) or "没有在线设备。")
            self.状态.setText(f"发现 {len(结果.设备)} 台设备。")

        self._后台(
            "正在扫描 ADB 设备…",
            lambda: 设备服务.扫描(表单.adb路径, True, 表单.设备序列号),
            完成,
        )

    def _连接地址(self):
        表单 = self._表单()
        地址 = self.网络地址.text().strip()

        def 完成(结果):
            路径, 文本 = 结果
            self.adb路径.setText(路径)
            self.状态.setText(f"{文本}；请点“扫描”并选择设备。")

        self._后台(f"正在连接 {地址}…", lambda: 设备服务.连接网络地址(表单.adb路径, True, 地址), 完成)

    def _设备变化(self, 序列号):
        self.已确认.setChecked(False)
        设备 = self._设备信息.get(序列号)
        if 序列号:
            self.设备描述.setText(f"目标：{序列号}\n{getattr(设备, '描述', '') or 'ADB 设备'}\n切换设备后请重新确认。")

    def _确认变化(self, 选中):
        if 选中 and not self.设备.currentText().strip():
            self.已确认.setChecked(False)
            self.状态.setText("请先扫描并选择一个 ADB 设备。")
        elif 选中 and getattr(self._设备信息.get(self.设备.currentText()), "疑似实体设备", False):
            self.状态.setText("注意：该设备看起来像实体手机。只有模拟器才允许被控制。")

    def 保存(self):
        try:
            路径 = self._服务.保存(self._机器人ID, self._表单())
        except Exception as 异常:
            提示错误(self, "保存失败", str(异常))
            return
        self.adb路径.setText(路径)
        self._刷新当前连接()
        self.状态.setText(f"手动连接已保存：{self.设备.currentText() or '未选择设备'}")
        self.上下文.记录操作("模拟器连接已保存（手动）")

    # ================================================================ 截图
    def 测试截图(self):
        表单 = self._服务.读取表单(self._机器人ID)
        机器人ID = self._机器人ID

        def 完成(图像):
            self._原图 = QPixmap.fromImage(BGR转图像(图像))
            self._刷新预览()
            self.预览尺寸.setText(f"{图像.shape[1]} × {图像.shape[0]}")
            self.状态.setText("连接和截图正常，可以开始任务。")

        self._后台("正在获取截图…", lambda: self._服务.测试截图(机器人ID, 表单), 完成)

    def _刷新预览(self):
        if self._原图 is None or self._原图.isNull():
            return
        self.预览.setPixmap(self._原图.scaled(self.预览.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, 事件):
        super().resizeEvent(事件)
        self._刷新预览()
