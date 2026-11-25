"""主窗口（方案 A 单屏）：状态栏 + 今日数据条 + 提醒条 + 任务/参数/日志三栏。

只控制一个游戏。连接、高级参数、主题和更新收进「高级设置」窗口。
"""
from __future__ import annotations

import time
import webbrowser

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from 应用.控制器 import 应用控制器, 状态已停止, 状态暂停中, 状态运行中
from 应用.快捷键 import 全局快捷键
from 应用.日志模型 import 展示文本, 日志聚合器
from 数据库.今日统计 import 格式化数量
from 界面.主题 import 全部配色, 浅色, 深色, 生成样式表
from 界面.页面基类 import 界面上下文
from 界面.组件 import 后台执行, 提示错误, 提示信息, 标签, 状态胶囊, 省略标签, 确认

# 竞赛积分超过这么久没更新，多半是上一期的数据，不再显示。
竞赛积分有效秒 = 10 * 24 * 3600
# 提醒条只显示最近这段时间内的异常。
提醒有效秒 = 30 * 60


def 界面设置() -> QSettings:
    """窗口尺寸、主题等界面偏好；测试里替换成临时文件，避免清掉真实设置。"""
    return QSettings("COCauto", "城控")


class _热键信号(QObject):
    按下 = Signal(str)
    注册失败 = Signal(str)


def 时长文本(秒: float) -> str:
    秒 = int(max(0, 秒))
    时, 余 = divmod(秒, 3600)
    return f"{时}:{余 // 60:02d}" if 时 else f"{余 // 60} 分钟"


class _数据项(QWidget):
    def __init__(self, 名称: str, 色名: str | None = None):
        super().__init__()
        布局 = QVBoxLayout(self)
        布局.setContentsMargins(12, 0, 12, 0)
        布局.setSpacing(0)
        self.名 = 标签(名称, "数据名")
        self.值 = QLabel("—")
        self.值.setObjectName(色名 or "数据值")
        布局.addWidget(self.名)
        布局.addWidget(self.值)


class 主窗口(QMainWindow):
    窗口标题 = "城控 · 部落冲突控制台"

    def __init__(self, 控制器: 应用控制器, 日志队列, 版本号: str):
        super().__init__()
        self.控制器 = 控制器
        self.版本号 = 版本号
        self._设置 = 界面设置()
        self._配色 = 全部配色.get(str(self._设置.value("主题", 浅色.名称)), 浅色)
        self._悬浮窗 = None
        self._高级设置 = None
        self._最新发布 = None
        self._关闭中 = False
        self._提醒已读至 = time.time() - 提醒有效秒
        self._当前提醒 = None

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
        self.setMinimumSize(800, 540)
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
        from 界面.页面_运行 import 运行页

        根 = QWidget()
        根.setObjectName("根")
        纵 = QVBoxLayout(根)
        纵.setContentsMargins(0, 0, 0, 0)
        纵.setSpacing(0)
        纵.addWidget(self._构建顶栏())
        纵.addWidget(self._构建数据条())
        纵.addWidget(self._构建提醒条())
        self.运行页 = 运行页(self.上下文, self.切换悬浮窗, self.打开高级设置)
        纵.addWidget(self.运行页, 1)
        self.setCentralWidget(根)
        # 旧接口：部分调用方按名称取页面。
        self._页面 = {"一键运行": self.运行页}

    def _构建顶栏(self) -> QWidget:
        顶栏 = QWidget()
        顶栏.setObjectName("顶栏")
        布局 = QHBoxLayout(顶栏)
        布局.setContentsMargins(14, 10, 14, 10)
        布局.setSpacing(10)
        self.状态 = 状态胶囊(self._配色)
        布局.addWidget(self.状态, 0, Qt.AlignVCenter)
        self.当前动作 = 省略标签("")
        self.当前动作.setObjectName("当前动作")
        布局.addWidget(self.当前动作, 1)
        self.设备按钮 = QPushButton("")
        self.设备按钮.setObjectName("设备芯片")
        self.设备按钮.setToolTip("模拟器连接（点击打开连接设置）")
        self.设备按钮.clicked.connect(lambda: self.打开高级设置("connection"))
        布局.addWidget(self.设备按钮, 0, Qt.AlignVCenter)
        self.主按钮 = QPushButton("开始")
        self.主按钮.setObjectName("主按钮")
        self.主按钮.setMinimumWidth(92)
        self.主按钮.clicked.connect(self._主按钮点击)
        self.停止按钮 = QPushButton("停止")
        self.停止按钮.setObjectName("危险按钮")
        self.停止按钮.clicked.connect(self._停止)
        self.设置按钮 = QPushButton("高级设置")
        self.设置按钮.clicked.connect(lambda: self.打开高级设置())
        for 按钮 in (self.主按钮, self.停止按钮, self.设置按钮):
            按钮.setCursor(Qt.PointingHandCursor)
            布局.addWidget(按钮, 0, Qt.AlignVCenter)
        return 顶栏

    def _构建数据条(self) -> QWidget:
        条 = QWidget()
        条.setObjectName("数据条")
        布局 = QHBoxLayout(条)
        布局.setContentsMargins(2, 8, 14, 8)
        布局.setSpacing(0)
        self.数据项 = {
            "场次": _数据项("今日场次"),
            "胜率": _数据项("胜率"),
            "金币": _数据项("金币", "数据值金"),
            "圣水": _数据项("圣水", "数据值水"),
            "黑油": _数据项("黑油"),
        }
        self.数据项["金币"].setToolTip("今日战前→战后资源净变化累计（已扣除训练消耗、含战后收集；读数可疑的场次不计入）")
        for 名, 项 in self.数据项.items():
            if 名 != "场次":
                分隔 = QFrame()
                分隔.setObjectName("竖分隔")
                布局.addWidget(分隔)
            布局.addWidget(项, 1)
        分隔 = QFrame()
        分隔.setObjectName("竖分隔")
        布局.addWidget(分隔)
        竞赛 = QWidget()
        竞赛布局 = QVBoxLayout(竞赛)
        竞赛布局.setContentsMargins(12, 0, 0, 0)
        竞赛布局.setSpacing(4)
        self.竞赛文字 = 标签("部落竞赛", "数据名")
        self.竞赛进度 = QProgressBar()
        self.竞赛进度.setObjectName("竞赛进度")
        self.竞赛进度.setTextVisible(False)
        self.竞赛进度.setFixedHeight(6)
        self.竞赛进度.setRange(0, 1)
        self.竞赛进度.setValue(0)
        竞赛布局.addWidget(self.竞赛文字)
        竞赛布局.addWidget(self.竞赛进度)
        布局.addWidget(竞赛, 2)
        return 条

    def _构建提醒条(self) -> QWidget:
        外 = QWidget()
        外布局 = QHBoxLayout(外)
        外布局.setContentsMargins(14, 8, 14, 0)
        self.提醒条 = QFrame()
        self.提醒条.setObjectName("提醒条")
        布局 = QHBoxLayout(self.提醒条)
        布局.setContentsMargins(10, 4, 6, 4)
        布局.setSpacing(8)
        self.提醒文字 = 省略标签("")
        self.提醒文字.setObjectName("提醒文字")
        布局.addWidget(self.提醒文字, 1)
        查看 = QPushButton("查看")
        查看.setObjectName("链接")
        查看.clicked.connect(self._查看提醒)
        关闭 = QPushButton("知道了")
        关闭.setObjectName("链接")
        关闭.clicked.connect(self._关闭提醒)
        布局.addWidget(查看)
        布局.addWidget(关闭)
        外布局.addWidget(self.提醒条)
        self._提醒外框 = 外
        外.setVisible(False)
        return 外

    # ================================================================ 启动后
    def 载入(self):
        """控制器准备完成后调用：读取设置，刷新状态。"""
        try:
            self.控制器.准备()
        except Exception as 异常:
            提示错误(self, "配置加载错误", str(异常))
        self.运行页.载入()
        self._同步历史()
        self._每秒刷新()
        QTimer.singleShot(1500, lambda: self._检查更新(手动=False))

    def 打开页面(self, 名称: str):
        """兼容旧调用：只有一个主页面；其余名称打开高级设置。"""
        if 名称 in ("一键运行", "", None):
            self.运行页.页面显示()
            return
        self.打开高级设置("connection" if 名称 == "模拟器连接" else 名称)

    def 打开高级设置(self, 页键: str | None = None):
        from 界面.高级设置 import 高级设置窗口

        if self._高级设置 is None:
            self._高级设置 = 高级设置窗口(
                self.上下文, self.运行页.计划, self.版本号,
                self._切换主题, lambda: self._检查更新(手动=True), self,
            )
            self._高级设置.finished.connect(self._高级设置关闭)
        self._高级设置.载入()
        if 页键:
            self._高级设置.打开页(页键)
        self._高级设置.show()
        self._高级设置.raise_()
        self._高级设置.activateWindow()

    def _高级设置关闭(self, _结果=None):
        self.控制器.设置已变更()
        if not self.运行页.计划.有未保存修改:
            self.运行页.计划.载入()

    # ================================================================ 运行控制
    def _刷新运行控制(self):
        状态 = self.控制器.状态
        self.状态.设置(状态)
        self.主按钮.setText({状态运行中: "暂停", 状态暂停中: "继续"}.get(状态, "开始"))
        self.主按钮.setToolTip("F2：暂停（游戏倒计时不会暂停）" if 状态 == 状态运行中 else "F1：开始或继续")
        self.停止按钮.setEnabled(状态 in (状态运行中, 状态暂停中))

    def _保存未提交设置(self):
        计划 = self.运行页.计划
        if 计划.有未保存修改:
            计划.保存()
        if self._高级设置 is not None:
            self._高级设置.保存全部()

    def _主按钮点击(self):
        try:
            状态 = self.控制器.状态
            if 状态 == 状态运行中:
                if self.控制器.仅暂停():
                    self._记录操作("暂停")
            elif 状态 == 状态暂停中:
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

    # ================================================================ 状态与数据
    def _刷新状态栏(self):
        快照 = self.控制器.快照()
        self.设备按钮.setText(f"模拟器 {快照.设备序列号} ✓" if 快照.设备已确认 and 快照.设备序列号
                           else (f"模拟器 {快照.设备序列号}（未确认）" if 快照.设备序列号 else "模拟器未连接"))
        if 快照.状态 == 状态已停止:
            原因 = 快照.停止原因
            文本 = ("尚未开始：勾选任务后点击“开始”（F1）" if 原因 in ("", "未启动")
                  else f"已停止：{原因}")
        elif 快照.状态 == 状态暂停中:
            文本 = "已暂停，按 F1 或“继续”恢复；游戏倒计时不会暂停"
        else:
            阶段 = self.聚合器.当前阶段(self.控制器.实例ID)
            文本 = 展示文本(阶段) if 阶段 else "正在运行，等待下一条关键状态…"
            if 快照.已运行秒 is not None:
                文本 += f" · 已运行 {时长文本(快照.已运行秒)}"
        self.当前动作.设置文本(文本)

    def _刷新数据条(self):
        try:
            概况 = self.控制器.今日概况()
        except Exception:
            return
        今日 = 概况.今日
        self.数据项["场次"].值.setText(str(今日.场次))
        self.数据项["胜率"].值.setText(f"{今日.胜率}%" if 今日.胜率 is not None else "—")
        self.数据项["胜率"].setToolTip(
            f"胜 {今日.胜} · 负 {今日.负}" + (f" · 平均 {今日.平均星数}★" if 今日.平均星数 is not None else "")
        )
        for 资源 in ("金币", "圣水", "黑油"):
            值 = getattr(今日, 资源)
            self.数据项[资源].值.setText(格式化数量(值) if 今日.收益场次 else "—")
        积分 = 概况.竞赛积分
        积分时间 = float(概况.竞赛.get("个人积分时间", 0) or 0)
        if 积分 and time.time() - 积分时间 < 竞赛积分有效秒 and 积分[1] > 0:
            self.竞赛文字.setText(f"部落竞赛 · {积分[0]} / {积分[1]}")
            self.竞赛进度.setRange(0, 积分[1])
            self.竞赛进度.setValue(min(积分[0], 积分[1]))
        else:
            self.竞赛文字.setText("部落竞赛 · 暂无积分")
            self.竞赛进度.setRange(0, 1)
            self.竞赛进度.setValue(0)
        提示 = []
        if 概况.竞赛.get("当前任务"):
            提示.append(f"当前任务：{概况.竞赛['当前任务']}")
        下次 = float(概况.竞赛.get("下次检查时间", 0) or 0)
        if 下次 > time.time():
            提示.append("下次检查 " + time.strftime("%H:%M", time.localtime(下次)))
        if 概况.竞赛.get("结果"):
            提示.append(f"上次结果：{概况.竞赛['结果']}")
        self.竞赛文字.setToolTip("\n".join(提示))
        self.竞赛进度.setToolTip("\n".join(提示))

    def _刷新提醒(self):
        项 = self.聚合器.最近异常(max(self._提醒已读至, time.time() - 提醒有效秒))
        self._当前提醒 = 项
        if 项 is None:
            self._提醒外框.setVisible(False)
            return
        文本 = f"⚠ {time.strftime('%H:%M', time.localtime(项.时间戳))}  {展示文本(项.内容)}"
        self.提醒文字.设置文本(文本)
        self._提醒外框.setVisible(True)

    def _查看提醒(self):
        self.运行页.切换模式("异常")

    def _关闭提醒(self):
        if self._当前提醒 is not None:
            self._提醒已读至 = self._当前提醒.时间戳
        self._刷新提醒()

    # ================================================================ 定时
    def _每秒刷新(self):
        try:
            self._刷新运行控制()
            self._刷新状态栏()
            self._刷新数据条()
            self._刷新提醒()
            self.运行页.定时刷新()
            if self._悬浮窗 is not None:
                self._悬浮窗.刷新()
        except Exception as 异常:  # 刷新异常不能让定时器停摆
            print(f"界面刷新异常：{异常}")

    def _消费日志(self):
        self.聚合器.消费实时队列()

    def _同步历史(self):
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
        self.状态.应用配色(色)
        self.运行页.应用配色(色)

    # ================================================================ 更新
    def _检查更新(self, 手动: bool):
        from 工具包.更新检查器 import 获取最新发布, 有可用更新

        按钮 = getattr(self._高级设置, "更新按钮", None)
        if 按钮 is not None:
            按钮.setEnabled(False)
            按钮.setText("检查中…")

        def 完成(发布):
            if 按钮 is not None:
                按钮.setEnabled(True)
                按钮.setText("检查更新")
            self._最新发布 = 发布 if 有可用更新(self.版本号, 发布) else None
            if self._最新发布 is not None:
                self.设置按钮.setText(f"高级设置 · 新版本 {self._最新发布.版本}")
                self.设置按钮.setToolTip("发现新版本，点击“高级设置”里的“检查更新”打开下载页")
                if 手动:
                    self._打开更新页()
            elif 手动:
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
            宽 = min(1040, max(800, 屏幕.width() - 100))
            高 = min(680, max(540, 屏幕.height() - 120))
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
        if self._高级设置 is not None:
            self._高级设置.close()
        self.控制器.关闭()
        事件.accept()
