"""高级设置窗口：模拟器连接、平时不用调的参数、通知、官方数据和常规选项。

参数写进主界面任务计划组件持有的同一个设置对象（``保存外部修改``），
所以两边同时打开也不会互相覆盖。每页修改 600ms 后自动保存。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from 应用 import 任务计划 as 计划
from 数据库.任务数据库 import 机器人设置
from 界面.参数表单 import 参数表单
from 界面.组件 import 后台执行, 提示信息, 提示错误, 标签, 横排, 确认

连接页键 = "connection"
# 主界面「更多参数」从哪个任务跳到哪一页。
任务对应高级页 = {
    "main_resource": "adv_search",
    "night_resource": "adv_search",
    "event": "adv_event",
    "donate_troops": "adv_daily",
}
页顺序 = (连接页键, "adv_search", "adv_combat", "adv_event", "adv_daily", "adv_notification", "adv_official", "adv_general")


class _参数页(QWidget):
    def __init__(self, 键: str, 计划组件, 附加控件: list[QWidget] | None = None):
        super().__init__()
        self.键 = 键
        self._计划 = 计划组件
        self.页 = 计划.高级参数表[键]
        self._计时 = QTimer(self)
        self._计时.setSingleShot(True)
        self._计时.setInterval(600)
        self._计时.timeout.connect(self.保存)
        self._载入中 = False

        外层 = QVBoxLayout(self)
        外层.setContentsMargins(0, 0, 0, 0)
        内容 = QWidget()
        内容.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        布局 = QVBoxLayout(内容)
        布局.setContentsMargins(22, 16, 22, 16)
        布局.setSpacing(10)
        布局.addWidget(标签(self.页.标题, "卡片标题"))
        布局.addWidget(标签(self.页.说明, "弱", 换行=True))
        self.表单 = 参数表单(self._安排保存, 多选列数=3)
        布局.addWidget(self.表单)
        for 控件 in 附加控件 or []:
            布局.addWidget(控件)
        self.状态 = 标签("修改会自动保存", "弱", 换行=True)
        恢复 = QPushButton("恢复默认")
        恢复.setToolTip("把本页参数恢复为默认值")
        恢复.clicked.connect(self.恢复默认)
        布局.addLayout(横排(self.状态, None, 恢复))
        布局.addStretch(1)
        滚动 = QScrollArea()
        滚动.setWidgetResizable(True)
        滚动.setFrameShape(QFrame.NoFrame)
        滚动.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        滚动.setWidget(内容)
        外层.addWidget(滚动)

    def 载入(self):
        self._载入中 = True
        try:
            if self._计划.设置 is not None:
                self.表单.显示(self.页, self._计划.设置)
        finally:
            self._载入中 = False

    def _安排保存(self):
        if self._载入中:
            return
        self.状态.setText("正在保存…")
        self._计时.start()

    @property
    def 有未保存修改(self) -> bool:
        return self._计时.isActive()

    def 保存(self) -> bool:
        self._计时.stop()
        值 = self.表单.表单值()
        错误 = self._计划.保存外部修改(lambda 设置: 计划.应用参数(设置, self.键, 值))
        self.状态.setText(f"未保存：{错误}" if 错误 else "✓ 已自动保存")
        return 错误 is None

    def 恢复默认(self):
        默认 = 机器人设置()

        def 修改(设置):
            for 字段 in self.页.字段:
                setattr(设置, 字段.字段, getattr(默认, 字段.字段))

        错误 = self._计划.保存外部修改(修改)
        self.载入()
        self.状态.setText(f"未恢复：{错误}" if 错误 else "已恢复默认")


class 高级设置窗口(QDialog):
    def __init__(self, 上下文, 计划组件, 版本号: str, 切换主题, 检查更新, 父=None, 托盘开关=None):
        super().__init__(父)
        self.setWindowTitle("高级设置")
        self.setObjectName("根")
        self.setMinimumSize(760, 520)
        self.resize(900, 640)
        self.上下文 = 上下文
        self._计划 = 计划组件

        横 = QHBoxLayout(self)
        横.setContentsMargins(0, 0, 0, 0)
        横.setSpacing(0)
        侧栏 = QWidget()
        侧栏.setObjectName("侧栏")
        侧栏.setFixedWidth(170)
        侧布局 = QVBoxLayout(侧栏)
        侧布局.setContentsMargins(10, 14, 10, 12)
        self.导航 = QListWidget()
        self.导航.setObjectName("设置导航")
        侧布局.addWidget(self.导航, 1)
        版本 = 标签(f"版本 {版本号}", "弱")
        self.更新按钮 = QPushButton("检查更新")
        self.更新按钮.setObjectName("链接")
        self.更新按钮.clicked.connect(检查更新)
        侧布局.addLayout(横排(版本, None, self.更新按钮, 间距=4))
        横.addWidget(侧栏)
        self.栈 = QStackedWidget()
        横.addWidget(self.栈, 1)

        from 界面.页面_设备连接 import 设备连接页

        self.连接页 = 设备连接页(上下文, 纵向=True)
        self.页面: dict[str, QWidget] = {连接页键: self.连接页}
        self.服务器 = QComboBox()
        self.服务器.addItems(计划.服务器选项)
        self.服务器.currentTextChanged.connect(self._服务器变化)
        self.主题按钮 = QPushButton("切换深色/浅色")
        self.主题按钮.clicked.connect(切换主题)
        常规附加 = QWidget()
        常规布局 = QVBoxLayout(常规附加)
        常规布局.setContentsMargins(0, 6, 0, 0)
        常规布局.setSpacing(8)
        常规布局.addLayout(横排(标签("服务器", "次要"), self.服务器, None))
        常规布局.addLayout(横排(标签("界面主题", "次要"), self.主题按钮, None))
        from 界面.高级主题 import 滑动开关

        # 托盘开关是界面偏好（QSettings），不写进机器人设置；默认关闭＝关窗即退出。
        self._托盘开关 = 托盘开关
        self.托盘开关 = 滑动开关("关闭窗口时最小化到系统托盘（关闭时点 × 直接退出程序）")
        self.托盘开关.setVisible(托盘开关 is not None)
        self.托盘开关.toggled.connect(self._托盘开关变化)
        常规布局.addWidget(self.托盘开关)
        self.问题包按钮 = QPushButton("导出问题包")
        self.问题包按钮.setToolTip(
            "把最近日志、异常现场摘要、运行状态、版本和（去掉账号/密钥、已打码的）配置打成 zip，放在程序同级目录"
        )
        self.问题包按钮.clicked.connect(self._导出问题包)
        常规布局.addLayout(横排(标签("排查问题", "次要"), self.问题包按钮, None))
        测试通知 = QPushButton("发送测试桌面通知")
        测试通知.setToolTip("立即在屏幕右下角弹一条测试通知（不节流、不影响脚本运行）")
        测试通知.clicked.connect(self._发送测试桌面通知)
        附加 = {"adv_general": [常规附加], "adv_notification": [测试通知]}
        for 键 in 页顺序[1:]:
            self.页面[键] = _参数页(键, 计划组件, 附加.get(键))
        for 键 in 页顺序:
            标题 = "模拟器连接" if 键 == 连接页键 else 计划.高级参数表[键].标题
            项 = QListWidgetItem(标题)
            项.setData(Qt.UserRole + 1, 键)
            self.导航.addItem(项)
            self.栈.addWidget(self.页面[键])
        self.导航.currentRowChanged.connect(self.栈.setCurrentIndex)
        self.导航.setCurrentRow(0)
        self._载入中 = False

    # ------------------------------------------------------------ 生命周期
    def 载入(self):
        self._载入中 = True
        try:
            self.连接页.载入()
            for 键, 页 in self.页面.items():
                if isinstance(页, _参数页):
                    页.载入()
            设置 = self._计划.设置
            self.服务器.setCurrentText(getattr(设置, "服务器", "国际服") or "国际服")
            if self._托盘开关 is not None:
                self.托盘开关.setChecked(bool(self._托盘开关[0]()))
        finally:
            self._载入中 = False

    def 打开页(self, 键: str):
        键 = 任务对应高级页.get(键, 键)
        if 键 not in 页顺序:
            键 = "adv_combat"
        self.导航.setCurrentRow(页顺序.index(键))

    @property
    def 当前页键(self) -> str:
        return 页顺序[self.导航.currentRow()]

    def _发送测试桌面通知(self):
        try:
            from 工具包.桌面通知 import 发送测试通知

            成功 = bool(发送测试通知())
        except Exception:
            成功 = False
        self.页面["adv_notification"].状态.setText(
            "已发送测试桌面通知" if 成功 else "测试桌面通知发送失败"
        )

    def _导出问题包(self):
        from 应用.问题包 import 导出问题包

        # 截图里可能有玩家名/部落名，默认不带，用户确认才带。
        包含截图 = 确认(
            self, "导出问题包",
            "是否附带异常现场截图？\n截图画面里可能有玩家名、部落名等个人信息。\n选“否”只导出已打码的日志和摘要。",
        )
        self.问题包按钮.setEnabled(False)
        self.问题包按钮.setText("导出中…")
        数据库 = self.上下文.控制器.数据库

        def 结束():
            self.问题包按钮.setEnabled(True)
            self.问题包按钮.setText("导出问题包")

        def 成功(路径):
            结束()
            记录 = getattr(self.上下文, "记录操作", None)
            if callable(记录):
                记录(f"已导出问题包：{路径}")
            提示信息(
                self, "问题包已导出",
                f"问题包已保存到：\n{路径}\n\n账号、令牌、Webhook、设备序列号已去除，日志里的玩家名/标签、IP 已打码。",
            )

        def 失败(错误: str):
            结束()
            提示错误(self, "导出问题包失败", 错误)

        后台执行(lambda: 导出问题包(数据库, 包含截图=包含截图), 成功, 失败)

    def _托盘开关变化(self, 启用: bool):
        if self._载入中 or self._托盘开关 is None:
            return
        self._托盘开关[1](bool(启用))

    def _服务器变化(self, 名称: str):
        if self._载入中:
            return

        def 修改(设置):
            设置.服务器 = 名称 or "国际服"
        self._计划.保存外部修改(修改)

    def 保存全部(self):
        for 页 in self.页面.values():
            if isinstance(页, _参数页) and 页.有未保存修改:
                页.保存()

    def done(self, 结果):
        self.保存全部()
        super().done(结果)
