"""主窗口：侧栏导航 + 顶部运行控制 + 页面区。只控制一个游戏。"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from 应用.控制器 import 应用控制器, 状态暂停中, 状态运行中
from 应用.快捷键 import 全局快捷键
from 应用.日志模型 import 日志聚合器
from 界面.主题 import 全部配色, 浅色, 深色, 生成样式表
from 界面.页面基类 import 界面上下文, 页面基类
from 界面.组件 import 后台执行, 品牌标志, 提示错误, 提示信息, 标签, 状态胶囊, 确认

页面顺序 = ("一键运行", "模拟器连接")


class _热键信号(QObject):
    按下 = Signal(str)
    注册失败 = Signal(str)


class 主窗口(QMainWindow):
    窗口标题 = "城控 · 部落冲突控制台"

    def __init__(self, 控制器: 应用控制器, 日志队列, 版本号: str):
        super().__init__()
        self.控制器 = 控制器
        self.版本号 = 版本号
        self._设置 = QSettings("COCauto", "城控")
        self._配色 = 全部配色.get(str(self._设置.value("主题", 浅色.名称)), 浅色)
        self._悬浮窗 = None
        self._最新发布 = None
        self._关闭中 = False

        数据库 = 控制器.数据库
        self.聚合器 = 日志聚合器(
            日志队列,
            读取历史=lambda 标志, 起始: 数据库.查询日志历史(标志, 起始时间=起始),
            获取机器人列表=lambda: [控制器.实例ID],
        )
        self.上下文 = 界面上下文(
            控制器=控制器, 聚合器=self.聚合器, 配色=self._配色,
            记录操作=self._记录操作, 打开页面=self.打开页面,
        )

        self.setWindowTitle(self.窗口标题)
        self.setMinimumSize(1120, 680)
        self._构建界面()
        self._应用主题(self._配色)
        self._恢复窗口尺寸()

        self._刷新计时 = QTimer(self)
        self._刷新计时.timeout.connect(self._每秒刷新)
        self._刷新计时.start(1000)
        self._日志计时 = QTimer(self)
        self._日志计时.timeout.connect(self._消费日志)
        self._日志计时.start(500)
        self._历史计时 = QTimer(self)
        self._历史计时.timeout.connect(self._同步历史)
        self._历史计时.start(3000)

        self._热键信号 = _热键信号()
        self._热键信号.按下.connect(self._处理热键)
        self._热键信号.注册失败.connect(self._启用窗口内热键)
        self._热键 = 全局快捷键(self._热键信号.按下.emit, self._热键信号.注册失败.emit)
        self._热键.启动()

    # ================================================================ 构建
    def _构建界面(self):
        根 = QWidget()
        根.setObjectName("根")
        横 = QHBoxLayout(根)
        横.setContentsMargins(0, 0, 0, 0)
        横.setSpacing(0)
        横.addWidget(self._构建侧栏())
        右 = QVBoxLayout()
        右.setContentsMargins(0, 0, 0, 0)
        右.setSpacing(0)
        右.addWidget(self._构建顶栏())
        self._栈 = QStackedWidget()
        右.addWidget(self._栈, 1)
        横.addLayout(右, 1)
        self.setCentralWidget(根)
        self._创建页面()

    def _构建侧栏(self) -> QWidget:
        侧栏 = QWidget()
        侧栏.setObjectName("侧栏")
        侧栏.setFixedWidth(196)
        布局 = QVBoxLayout(侧栏)
        布局.setContentsMargins(14, 18, 14, 16)
        布局.setSpacing(4)
        品牌行 = QHBoxLayout()
        品牌行.setSpacing(10)
        品牌行.addWidget(品牌标志(38))
        品牌字 = QVBoxLayout()
        品牌字.setSpacing(0)
        名 = QLabel("城控")
        名.setObjectName("品牌")
        副 = QLabel("部落冲突控制台")
        副.setObjectName("品牌副标题")
        品牌字.addWidget(名)
        品牌字.addWidget(副)
        品牌行.addLayout(品牌字)
        品牌行.addStretch(1)
        布局.addLayout(品牌行)
        布局.addSpacing(18)

        self._导航组 = QButtonGroup(self)
        self._导航组.setExclusive(True)
        self._导航按钮: dict[str, QPushButton] = {}
        for 名称 in 页面顺序:
            按钮 = QPushButton(名称)
            按钮.setObjectName("导航")
            按钮.setCheckable(True)
            按钮.setCursor(Qt.PointingHandCursor)
            按钮.clicked.connect(lambda _=False, 页=名称: self.打开页面(页))
            self._导航组.addButton(按钮)
            self._导航按钮[名称] = 按钮
            布局.addWidget(按钮)
        布局.addStretch(1)

        self._主题按钮 = QPushButton()
        self._主题按钮.setObjectName("导航")
        self._主题按钮.clicked.connect(self._切换主题)
        布局.addWidget(self._主题按钮)
        self._更新按钮 = QPushButton("检查更新")
        self._更新按钮.setObjectName("导航")
        self._更新按钮.clicked.connect(lambda: self._检查更新(手动=True))
        布局.addWidget(self._更新按钮)
        self._更新提示 = QPushButton("")
        self._更新提示.setObjectName("链接")
        self._更新提示.setVisible(False)
        self._更新提示.clicked.connect(self._打开更新页)
        布局.addWidget(self._更新提示)
        版本 = 标签(f"版本 {self.版本号}", "弱")
        版本.setContentsMargins(14, 6, 0, 0)
        布局.addWidget(版本)
        return 侧栏

    def _构建顶栏(self) -> QWidget:
        顶栏 = QWidget()
        顶栏.setObjectName("顶栏")
        布局 = QHBoxLayout(顶栏)
        布局.setContentsMargins(28, 14, 24, 14)
        布局.setSpacing(10)
        标题区 = QVBoxLayout()
        标题区.setSpacing(2)
        self._页标题 = 标签("", "页标题")
        self._页说明 = 标签("", "次要")
        标题区.addWidget(self._页标题)
        标题区.addWidget(self._页说明)
        布局.addLayout(标题区, 1)
        self.状态 = 状态胶囊(self._配色)
        布局.addWidget(self.状态, 0, Qt.AlignVCenter)
        布局.addSpacing(6)
        self.主按钮 = QPushButton("开始")
        self.主按钮.setObjectName("主按钮")
        self.主按钮.setMinimumWidth(104)
        self.主按钮.setToolTip("F1：开始或继续")
        self.主按钮.clicked.connect(self._主按钮点击)
        self.暂停按钮 = QPushButton("暂停")
        self.暂停按钮.setToolTip("F2：暂停（游戏倒计时不会暂停）")
        self.暂停按钮.clicked.connect(self._暂停)
        self.停止按钮 = QPushButton("停止")
        self.停止按钮.setObjectName("危险按钮")
        self.停止按钮.clicked.connect(self._停止)
        for 按钮 in (self.主按钮, self.暂停按钮, self.停止按钮):
            按钮.setCursor(Qt.PointingHandCursor)
            布局.addWidget(按钮, 0, Qt.AlignVCenter)
        return 顶栏

    def _创建页面(self):
        from 界面.页面_运行 import 运行页
        from 界面.页面_设备连接 import 设备连接页

        self._页面: dict[str, 页面基类] = {
            "一键运行": 运行页(self.上下文, self.切换悬浮窗),
            "模拟器连接": 设备连接页(self.上下文),
        }
        for 页 in self._页面.values():
            self._栈.addWidget(页)

    # ================================================================ 启动后
    def 载入(self):
        """控制器准备完成后调用：各页面读取设置，打开主页。"""
        try:
            self.控制器.准备()
        except Exception as 异常:
            提示错误(self, "配置加载错误", str(异常))
        for 页 in self._页面.values():
            页.载入()
        self.打开页面("一键运行")
        self._刷新运行控制()
        QTimer.singleShot(1500, lambda: self._检查更新(手动=False))

    # ================================================================ 导航
    def 打开页面(self, 名称: str):
        页 = self._页面[名称]
        self._栈.setCurrentWidget(页)
        self._导航按钮[名称].setChecked(True)
        self._页标题.setText(页.标题)
        self._页说明.setText(页.说明)
        if 名称 == "一键运行":
            self._同步历史()
        页.页面显示()

    def _当前页(self) -> 页面基类:
        return self._栈.currentWidget()

    # ================================================================ 运行控制
    def _刷新运行控制(self):
        状态 = self.控制器.状态
        self.状态.设置(状态)
        self.主按钮.setText("继续" if 状态 == 状态暂停中 else "开始")
        self.主按钮.setEnabled(状态 != 状态运行中)
        self.暂停按钮.setEnabled(状态 == 状态运行中)
        self.停止按钮.setEnabled(状态 in (状态运行中, 状态暂停中))

    def _保存未提交设置(self):
        计划 = getattr(self._页面.get("一键运行"), "计划", None)
        if 计划 is not None and 计划.有未保存修改:
            计划.保存()

    def _主按钮点击(self):
        try:
            if self.控制器.状态 == 状态暂停中:
                self.控制器.继续()
                self._记录操作("继续")
            else:
                self._保存未提交设置()
                self.控制器.启动()
                self._记录操作("开始")
        except Exception as 异常:
            提示错误(self, "无法开始", str(异常))
        self._刷新运行控制()

    def _暂停(self):
        if self.控制器.仅暂停():
            self._记录操作("暂停")
        self._刷新运行控制()

    def _停止(self):
        self.控制器.停止("界面停止按钮")
        self._记录操作("停止")
        self._刷新运行控制()

    def _处理热键(self, 按键: str):
        try:
            if 按键 == "F1":
                self._保存未提交设置()
                if self.控制器.开始或继续():
                    self._记录操作("F1：开始／继续")
            elif 按键 == "F2" and self.控制器.仅暂停():
                self._记录操作("F2：暂停，等待继续")
        except Exception as 异常:
            self._记录操作(f"{按键} 操作失败：{异常}")
        self._刷新运行控制()

    def _启用窗口内热键(self, 按键: str):
        快捷键 = QShortcut(QKeySequence(按键), self)
        快捷键.setContext(Qt.ApplicationShortcut)
        快捷键.activated.connect(lambda 名称=按键: self._处理热键(名称))

    # ================================================================ 定时
    def _每秒刷新(self):
        try:
            self._刷新运行控制()
            self._当前页().定时刷新()
            if self._悬浮窗 is not None:
                self._悬浮窗.刷新()
        except Exception as 异常:  # 刷新异常不能让定时器停摆
            print(f"界面刷新异常：{异常}")

    def _消费日志(self):
        self.聚合器.消费实时队列()

    def _同步历史(self):
        if self._当前页() is self._页面.get("一键运行") or self._悬浮窗 is not None:
            self.聚合器.同步历史()

    def _记录操作(self, 内容: str):
        self.聚合器.记录操作(内容)

    # ================================================================ 悬浮窗
    def 切换悬浮窗(self):
        if self._悬浮窗 is not None:
            self._悬浮窗.close()
            return
        from 界面.悬浮日志 import 悬浮日志窗

        self._悬浮窗 = 悬浮日志窗(self.上下文, self._隐藏到悬浮窗, self._悬浮窗已关闭)
        self._同步历史()
        self._悬浮窗.刷新()
        self._悬浮窗.show()

    def _隐藏到悬浮窗(self):
        self.hide()

    def _悬浮窗已关闭(self):
        self._悬浮窗 = None
        if not self.isVisible():
            self.showNormal()
            self.activateWindow()

    # ================================================================ 主题
    def _切换主题(self):
        self._应用主题(深色 if self._配色 is 浅色 else 浅色)

    def _应用主题(self, 色):
        self._配色 = 色
        self.上下文.配色 = 色
        self._设置.setValue("主题", 色.名称)
        QApplication.instance().setStyleSheet(生成样式表(色))
        self._主题按钮.setText("切换到浅色" if 色 is 深色 else "切换到深色")
        self.状态.应用配色(色)
        for 页 in getattr(self, "_页面", {}).values():
            页.应用配色(色)

    # ================================================================ 更新
    def _检查更新(self, 手动: bool):
        from 工具包.更新检查器 import 获取最新发布, 有可用更新

        self._更新按钮.setEnabled(False)
        self._更新按钮.setText("检查中…")

        def 完成(发布):
            self._更新按钮.setEnabled(True)
            self._更新按钮.setText("检查更新")
            self._最新发布 = 发布 if 有可用更新(self.版本号, 发布) else None
            if self._最新发布 is not None:
                self._更新提示.setText(f"发现新版本 {self._最新发布.版本} ›")
                self._更新提示.setVisible(True)
            elif 手动:
                self._更新提示.setVisible(False)
                提示信息(self, "检查更新", "当前已是最新版本。" if 发布 is not None else "暂时无法连接发布页，请稍后再试。")

        后台执行(lambda: 获取最新发布(timeout=4), 完成, lambda _信息: 完成(None))

    def _打开更新页(self):
        if self._最新发布 is not None:
            webbrowser.open(self._最新发布.页面地址, new=2)

    # ================================================================ 窗口
    def _恢复窗口尺寸(self):
        几何 = self._设置.value("窗口几何")
        if 几何 is None or not self.restoreGeometry(几何):
            屏幕 = QApplication.primaryScreen().availableGeometry()
            宽 = min(1360, max(1120, 屏幕.width() - 100))
            高 = min(840, max(680, 屏幕.height() - 120))
            self.resize(宽, 高)
            self.move(屏幕.center().x() - 宽 // 2, 屏幕.center().y() - 高 // 2)

    def 唤醒(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, 事件):
        if self._关闭中:
            事件.accept()
            return
        if self.控制器.状态 in (状态运行中, 状态暂停中) and not 确认(
            self, "退出控制台", "任务仍在运行。退出会停止任务，确定退出？",
        ):
            事件.ignore()
            return
        self._关闭中 = True
        self._设置.setValue("窗口几何", self.saveGeometry())
        self._保存未提交设置()
        for 计时 in (self._刷新计时, self._日志计时, self._历史计时):
            计时.stop()
        self._热键.关闭()
        if self._悬浮窗 is not None:
            self._悬浮窗.close()
        self.控制器.关闭()
        事件.accept()
