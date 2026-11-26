"""方案 A 主界面的附加部件：运行光条、每日战报卡、配置方案（预设）窗口。

数据全部来自 应用/战报服务、应用/预设服务；这里只负责展示和交互。
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QListWidget, QListWidgetItem, QPushButton, QSizePolicy,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from 界面.组件 import 后台执行, 标签, 横排


# ====================================================================== 运行光条
class 运行光条(QWidget):
    """状态栏下方 3px 光条：运行中暖金光带循环扫过，暂停时静止半亮，停止时只剩底线。"""

    def __init__(self, 强调色: str = "#F59E0B", 父=None):
        super().__init__(父)
        self.setFixedHeight(3)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._强调 = QColor(强调色)
        self._底色 = QColor(255, 255, 255, 14)
        self._状态 = "已停止"
        self._位置 = 0.0
        self._动画 = QVariantAnimation(self)
        self._动画.setStartValue(-0.3)
        self._动画.setEndValue(1.3)
        self._动画.setDuration(1800)
        self._动画.setLoopCount(-1)
        self._动画.valueChanged.connect(self._更新位置)

    @property
    def 状态(self) -> str:
        return self._状态

    def 设置配色(self, 强调色: str, 底色: QColor):
        self._强调 = QColor(强调色)
        self._底色 = QColor(底色)
        self.update()

    def 设置状态(self, 状态: str):
        if 状态 == self._状态:
            return
        self._状态 = 状态
        if 状态 == "运行中":
            self._动画.start()
        else:
            self._动画.stop()
        self.update()

    def _更新位置(self, 值):
        self._位置 = float(值)
        self.update()

    def paintEvent(self, _事件):
        画笔 = QPainter(self)
        宽, 高 = self.width(), self.height()
        画笔.fillRect(0, 0, 宽, 高, self._底色)
        if self._状态 == "暂停中":
            色 = QColor(self._强调)
            色.setAlpha(110)
            画笔.fillRect(0, 0, 宽, 高, 色)
        elif self._状态 == "运行中":
            中心 = self._位置 * 宽
            渐变 = QLinearGradient(中心 - 宽 * 0.25, 0, 中心 + 宽 * 0.25, 0)
            透明 = QColor(self._强调)
            透明.setAlpha(0)
            渐变.setColorAt(0.0, 透明)
            渐变.setColorAt(0.5, self._强调)
            渐变.setColorAt(1.0, 透明)
            淡底 = QColor(self._强调)
            淡底.setAlpha(45)
            画笔.fillRect(0, 0, 宽, 高, 淡底)
            画笔.fillRect(0, 0, 宽, 高, 渐变)
        画笔.end()


# ====================================================================== 战报
def _万(数值: float) -> str:
    数值 = float(数值 or 0)
    if abs(数值) >= 1_000_000:
        return f"{数值 / 1_000_000:.1f}M"
    if abs(数值) >= 10_000:
        return f"{数值 / 1000:.0f}k"
    return f"{数值:.0f}"


def _对比(今, 昨, 格式=lambda 值: str(值), 越大越好: bool = True) -> tuple[str, str]:
    """返回 (今日文本, 与昨日对比文本)。"""
    if 今 is None:
        return "—", ""
    if 昨 is None or 昨 == 0:
        return 格式(今), ""
    差 = 今 - 昨
    if abs(差) < 1e-9:
        return 格式(今), "持平"
    箭头 = "↑" if 差 > 0 else "↓"
    return 格式(今), f"{箭头} {格式(abs(差))}"


class 小时曲线(QWidget):
    """0~23 时每小时场次（柱）与金币收益（折线）。"""

    def __init__(self, 父=None):
        super().__init__(父)
        self.setMinimumHeight(150)
        self._项 = ()
        self._强调 = QColor("#F59E0B")
        self._文字 = QColor("#9CA3AF")
        self._线 = QColor(255, 255, 255, 20)

    def 设置数据(self, 分小时, 强调色: str | None = None, 文字色: str | None = None):
        self._项 = tuple(分小时 or ())
        if 强调色:
            self._强调 = QColor(强调色)
        if 文字色:
            self._文字 = QColor(文字色)
        self.update()

    def paintEvent(self, _事件):
        画笔 = QPainter(self)
        画笔.setRenderHint(QPainter.Antialiasing)
        左, 上, 右, 下 = 28, 10, 8, 20
        区 = QRectF(左, 上, max(10, self.width() - 左 - 右), max(10, self.height() - 上 - 下))
        画笔.setPen(QPen(self._线, 1))
        for 行 in range(4):
            y = 区.top() + 区.height() * 行 / 3
            画笔.drawLine(int(区.left()), int(y), int(区.right()), int(y))
        字体 = QFont(self.font())
        字体.setPointSizeF(max(7.0, 字体.pointSizeF() - 2))
        画笔.setFont(字体)
        画笔.setPen(self._文字)
        for 小时 in (0, 6, 12, 18, 23):
            x = 区.left() + 区.width() * (小时 + 0.5) / 24
            画笔.drawText(QRectF(x - 12, 区.bottom() + 3, 24, 14), Qt.AlignCenter, str(小时))
        if not self._项:
            画笔.drawText(区, Qt.AlignCenter, "今天还没有战斗记录")
            画笔.end()
            return
        最多场 = max(1, max(项.场次 for 项 in self._项))
        最多金 = max(1, max(max(0, 项.金币) for 项 in self._项))
        画笔.drawText(QRectF(0, 区.top() - 6, 左 - 4, 14), Qt.AlignRight, str(最多场))
        柱宽 = 区.width() / 24 * 0.56
        柱色 = QColor(self._强调)
        柱色.setAlpha(150)
        for 项 in self._项:
            if 项.场次 <= 0:
                continue
            高 = 区.height() * 项.场次 / 最多场
            x = 区.left() + 区.width() * (项.小时 + 0.5) / 24 - 柱宽 / 2
            画笔.fillRect(QRectF(x, 区.bottom() - 高, 柱宽, 高), 柱色)
        画笔.setPen(QPen(QColor("#E5E7EB"), 1.6))
        上一点 = None
        for 项 in self._项:
            x = 区.left() + 区.width() * (项.小时 + 0.5) / 24
            y = 区.bottom() - 区.height() * max(0, 项.金币) / 最多金
            if 上一点 is not None:
                画笔.drawLine(int(上一点[0]), int(上一点[1]), int(x), int(y))
            上一点 = (x, y)
        画笔.end()


class 战报窗口(QDialog):
    """每日战报卡：今日 vs 昨日 + 每小时效率曲线。数据在后台线程读取。"""

    指标 = (
        ("总场次", "场次", str, True),
        ("胜率", "胜率", lambda 值: f"{值:.0f}%", True),
        ("平均摧毁率", "平均摧毁率", lambda 值: f"{值:.0f}%", True),
        ("总掠夺金币", "金币", _万, True),
        ("总掠夺圣水", "圣水", _万, True),
        ("总掠夺黑油", "黑油", _万, True),
        ("每小时场次", "场/小时", lambda 值: f"{值:.1f}", True),
        ("每小时金币", "金币/小时", _万, True),
        ("平均搜敌次数", "平均搜敌", lambda 值: f"{值:.1f}", False),
    )

    def __init__(self, 数据库, 机器人ID: str, 配色, 父=None):
        super().__init__(父)
        self.setObjectName("根")
        self.setWindowTitle("今日战报")
        self.setMinimumSize(560, 460)
        self.resize(640, 520)
        self._数据库 = 数据库
        self._机器人ID = 机器人ID
        self._配色 = 配色
        self.结果 = None

        布局 = QVBoxLayout(self)
        布局.setContentsMargins(18, 16, 18, 16)
        布局.setSpacing(12)
        self.标题 = 标签("今日战报", "卡片标题")
        self.副标题 = 标签("正在统计…", "弱")
        刷新 = QPushButton("刷新")
        刷新.clicked.connect(self.刷新)
        布局.addLayout(横排(self.标题, self.副标题, None, 刷新))
        self._网格 = QGridLayout()
        self._网格.setHorizontalSpacing(18)
        self._网格.setVerticalSpacing(10)
        self.单元: dict[str, tuple[QLabel, QLabel]] = {}
        for 序号, (键, 名称, _格式, _好) in enumerate(self.指标):
            行, 列 = divmod(序号, 3)
            框 = QVBoxLayout()
            框.setSpacing(0)
            名 = 标签(名称, "数据名")
            值 = QLabel("—")
            值.setObjectName("数据值")
            差 = 标签("", "弱")
            框.addWidget(名)
            框.addWidget(值)
            框.addWidget(差)
            self._网格.addLayout(框, 行, 列)
            self.单元[键] = (值, 差)
        布局.addLayout(self._网格)
        布局.addWidget(标签("每小时效率（柱：场次，线：金币收益）", "次要"))
        self.曲线 = 小时曲线()
        布局.addWidget(self.曲线, 1)

    def 刷新(self):
        self.副标题.setText("正在统计…")
        from 应用.战报服务 import 战报服务

        服务 = 战报服务(self._数据库)
        后台执行(lambda: 服务.生成战报(self._机器人ID), self.显示, lambda 信息: self.副标题.setText(f"统计失败：{信息}"))

    def 显示(self, 结果):
        self.结果 = 结果
        今, 昨 = 结果.今日, 结果.昨日
        self.副标题.setText(f"{今.日期} · 对比昨日 {昨.日期}")
        for 键, _名称, 格式, 越大越好 in self.指标:
            今值, 昨值 = getattr(今, 键), getattr(昨, 键)
            文本, 差 = _对比(今值, 昨值, 格式)
            值框, 差框 = self.单元[键]
            值框.setText(文本)
            差框.setText(f"昨日 {格式(昨值) if 昨值 is not None else '—'}  {差}".strip())
            好 = ("↑" in 差) == 越大越好 if 差 and 差 != "持平" else None
            颜色 = "" if 好 is None else (self._配色.成功 if 好 else self._配色.错误)
            差框.setStyleSheet(f"color: {颜色};" if 颜色 else "")
        self.曲线.设置数据(结果.今日分小时, self._配色.强调, self._配色.次要文字)


# ====================================================================== 配置方案
def _值文本(值) -> str:
    if isinstance(值, bool):
        return "开" if 值 else "关"
    if isinstance(值, (list, tuple)):
        return "、".join(map(str, 值)) or "（空）"
    if 值 in ("", None):
        return "（空）"
    return str(值)


class 预设窗口(QDialog):
    """多套配置方案：一键切换、差异预览、撤销、保存当前、JSON 导入导出。"""

    def __init__(self, 数据库, 机器人ID: str, 应用前回调: Callable[[], None],
                 应用后回调: Callable[[str], None], 父=None):
        super().__init__(父)
        from 应用.预设服务 import 预设服务

        self.setObjectName("根")
        self.setWindowTitle("配置方案")
        self.setMinimumSize(720, 480)
        self.resize(820, 560)
        self.服务 = 预设服务(数据库)
        self._机器人ID = 机器人ID
        self._应用前 = 应用前回调
        self._应用后 = 应用后回调

        横 = QHBoxLayout(self)
        横.setContentsMargins(16, 14, 16, 14)
        横.setSpacing(14)
        左 = QVBoxLayout()
        左.addWidget(标签("方案", "卡片标题"))
        self.列表 = QListWidget()
        self.列表.setObjectName("设置导航")
        self.列表.setFixedWidth(220)
        self.列表.currentItemChanged.connect(lambda *_: self._预览())
        左.addWidget(self.列表, 1)
        保存当前 = QPushButton("保存当前为方案…")
        保存当前.clicked.connect(self._保存当前)
        导入 = QPushButton("导入 JSON…")
        导入.clicked.connect(self._导入)
        导出 = QPushButton("导出 JSON…")
        导出.clicked.connect(self._导出)
        左.addWidget(保存当前)
        左.addLayout(横排(导入, 导出, 间距=6))
        横.addLayout(左)

        右 = QVBoxLayout()
        self.说明 = 标签("", "弱", 换行=True)
        self.摘要 = 标签("", "次要", 换行=True)
        右.addWidget(self.说明)
        右.addWidget(self.摘要)
        self.差异表 = QTableWidget(0, 3)
        self.差异表.setHorizontalHeaderLabels(("参数", "当前", "应用后"))
        self.差异表.verticalHeader().setVisible(False)
        self.差异表.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.差异表.setSelectionMode(QAbstractItemView.NoSelection)
        self.差异表.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.差异表.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.差异表.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        右.addWidget(self.差异表, 1)
        self.状态 = 标签("", "弱", 换行=True)
        self.撤销按钮 = QPushButton("撤销上次切换")
        self.撤销按钮.clicked.connect(self._撤销)
        self.应用按钮 = QPushButton("应用此方案")
        self.应用按钮.setObjectName("主按钮")
        self.应用按钮.clicked.connect(self._应用)
        右.addLayout(横排(self.状态, None, self.撤销按钮, self.应用按钮))
        横.addLayout(右, 1)
        self.载入()

    # ------------------------------------------------------------ 列表
    def 载入(self, 选中: str | None = None):
        当前 = 选中 or (self.列表.currentItem().data(Qt.UserRole) if self.列表.currentItem() else None)
        self.列表.blockSignals(True)
        self.列表.clear()
        for 方案 in self.服务.获取预设列表():
            项 = QListWidgetItem(("★ " if 方案.内置 else "") + 方案.名称)
            项.setData(Qt.UserRole, 方案.名称)
            项.setToolTip(方案.说明)
            self.列表.addItem(项)
            if 方案.名称 == 当前:
                self.列表.setCurrentItem(项)
        self.列表.blockSignals(False)
        if self.列表.currentItem() is None and self.列表.count():
            self.列表.setCurrentRow(0)
        self._预览()

    @property
    def 当前方案名(self) -> str | None:
        项 = self.列表.currentItem()
        return 项.data(Qt.UserRole) if 项 else None

    def _预览(self):
        名称 = self.当前方案名
        self.撤销按钮.setEnabled(self.服务.是否有回退快照(self._机器人ID))
        if not 名称:
            self.差异表.setRowCount(0)
            self.应用按钮.setEnabled(False)
            return
        方案 = self.服务.获取预设(名称)
        self.说明.setText(方案.说明)
        差异 = self.服务.预览差异(self._机器人ID, 方案)
        self.摘要.setText(差异.摘要)
        self.差异表.setRowCount(len(差异.变更项))
        for 行, 项 in enumerate(差异.变更项):
            for 列, 文本 in enumerate((项.显示名称, _值文本(项.当前值), _值文本(项.目标值))):
                单元 = QTableWidgetItem(文本)
                单元.setToolTip(文本)
                self.差异表.setItem(行, 列, 单元)
        self.应用按钮.setEnabled(差异.是否有变更)

    # ------------------------------------------------------------ 操作
    def _应用(self):
        名称 = self.当前方案名
        if not 名称:
            return
        self._应用前()
        结果 = self.服务.应用预设(self._机器人ID, 名称)
        self.状态.setText(f"已切换到「{名称}」，修改 {len(结果.变更项)} 项；可随时撤销")
        self._应用后(f"切换配置方案：{名称}（{len(结果.变更项)} 项）")
        self._预览()

    def _撤销(self):
        self._应用前()
        结果 = self.服务.回退预设(self._机器人ID)
        self.状态.setText(结果.说明)
        if 结果.成功:
            self._应用后(结果.说明)
        self._预览()

    def _保存当前(self):
        名称, 确定 = QInputDialog.getText(self, "保存当前为方案", "方案名称：")
        名称 = (名称 or "").strip()
        if not 确定 or not 名称:
            return
        self._应用前()
        try:
            self.服务.保存当前为预设(self._机器人ID, 名称)
        except ValueError as 异常:
            self.状态.setText(str(异常))
            return
        self.状态.setText(f"已保存方案「{名称}」")
        self.载入(名称)

    def _导入(self):
        路径, _ = QFileDialog.getOpenFileName(self, "导入配置方案", "", "JSON (*.json)")
        if not 路径:
            return
        self.导入文件(路径)

    def 导入文件(self, 路径: str) -> bool:
        try:
            with open(路径, encoding="utf-8-sig") as 文件:
                文本 = 文件.read()
            方案 = self.服务.导入预设JSON(文本, 覆盖名称=self._导入名称(文本, 路径))
        except (OSError, ValueError) as 异常:
            self.状态.setText(f"导入失败：{异常}")
            return False
        self.状态.setText(f"已导入方案「{方案.名称}」，确认差异后点“应用此方案”")
        self.载入(方案.名称)
        return True

    def _导入名称(self, 文本: str, 路径: str) -> str:
        """内置方案不能被导入覆盖；同名或无名时改成「名称（导入）」。"""
        import json
        from pathlib import Path

        try:
            载荷 = json.loads(文本)
            名称 = str(载荷.get("名称") or "").strip() if isinstance(载荷, dict) else ""
        except ValueError:
            名称 = ""
        名称 = 名称 or Path(路径).stem or "导入方案"
        内置 = {方案.名称 for 方案 in self.服务.获取内置预设列表()}
        return f"{名称}（导入）" if 名称 in 内置 else 名称

    def _导出(self):
        名称 = self.当前方案名
        if not 名称:
            return
        路径, _ = QFileDialog.getSaveFileName(self, "导出配置方案", f"{名称}.json", "JSON (*.json)")
        if 路径:
            self.导出文件(名称, 路径)

    def 导出文件(self, 名称: str, 路径: str) -> bool:
        try:
            self.服务.写入预设JSON文件(名称, 路径)
        except (OSError, ValueError) as 异常:
            self.状态.setText(f"导出失败：{异常}")
            return False
        self.状态.setText(f"已导出到 {路径}")
        return True


# ====================================================================== 现场图
class 现场图索引:
    """缓存现场截图列表（后台扫描，最多每 30 秒一次），按日志时间就近匹配。"""

    刷新间隔秒 = 30.0

    def __init__(self, 服务=None, 窗口秒: float = 60.0):
        if 服务 is None:
            from 应用.现场图服务 import 现场图服务

            服务 = 现场图服务()
        self.服务 = 服务
        self.窗口秒 = 窗口秒
        self._时间轴: list[float] = []
        self._条目: list = []
        self._上次扫描 = 0.0
        self._扫描中 = False

    def 设置条目(self, 条目):
        按时间 = sorted(条目, key=lambda 项: 项.时间戳)
        self._条目 = 按时间
        self._时间轴 = [项.时间戳 for 项 in 按时间]

    def 刷新(self, 同步: bool = False):
        import time as _time

        if self._扫描中 or (_time.time() - self._上次扫描 < self.刷新间隔秒 and self._条目):
            return
        self._上次扫描 = _time.time()
        if 同步:
            self.设置条目(self.服务.扫描全部())
            return
        self._扫描中 = True

        def 完成(条目):
            self._扫描中 = False
            self.设置条目(条目)

        def 失败(_信息):
            self._扫描中 = False

        后台执行(self.服务.扫描全部, 完成, 失败)

    def 查找(self, 时间戳: float):
        import bisect

        if not self._时间轴:
            return None
        位置 = bisect.bisect_left(self._时间轴, 时间戳)
        最佳, 最佳差 = None, self.窗口秒 + 1
        for 序号 in (位置 - 1, 位置):
            if 0 <= 序号 < len(self._条目):
                差 = abs(self._条目[序号].时间戳 - 时间戳)
                if 差 <= self.窗口秒 and 差 < 最佳差:
                    最佳, 最佳差 = self._条目[序号], 差
        return 最佳


def 打开现场图(条目, 日志文本: str, 父=None):
    from 界面.高级主题 import 现场截图预览弹窗

    弹窗 = 现场截图预览弹窗(
        条目.文件路径, "异常现场截图", 条目.时间文本,
        {"分类": 条目.分类, "文件": 条目.文件名, "日志": 日志文本}, 父,
    )
    弹窗.setAttribute(Qt.WA_DeleteOnClose, True)
    弹窗.show()
    return 弹窗
