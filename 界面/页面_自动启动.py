"""自动启动：每天定时开始任务（Windows 计划任务）。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import QCheckBox, QPushButton, QTimeEdit

from 界面.页面基类 import 页面基类
from 界面.组件 import 卡片, 后台执行, 提示错误, 标签, 横排


class 自动启动页(页面基类):
    标题 = "自动启动"
    说明 = "每天到点自动开始任务。启动时仍会执行与手动开始相同的模拟器和任务检查。"

    def __init__(self, 上下文):
        super().__init__(上下文)
        self._管理器 = None

        卡 = 卡片("每日定时")
        self.启用 = QCheckBox("每天定时开始")
        self.时间 = QTimeEdit(QTime(9, 0))
        self.时间.setDisplayFormat("HH:mm")
        self.时间.setButtonSymbols(QTimeEdit.NoButtons)
        self.时间.setMinimumSize(88, 34)
        self.时间.setAlignment(Qt.AlignCenter)
        self.虚拟环境 = QCheckBox("使用虚拟环境（.venv）启动")
        self.虚拟环境.setChecked(True)
        卡.布局.addLayout(横排(self.启用, self.时间, None))
        卡.布局.addWidget(self.虚拟环境)
        self.状态 = 标签("未配置", "次要")
        保存 = QPushButton("保存")
        保存.setObjectName("主按钮")
        保存.clicked.connect(self._保存)
        卡.布局.addLayout(横排(self.状态, None, 保存))
        self.启用.toggled.connect(lambda 选中: self.状态.setText("已启用（未保存）" if 选中 else "已关闭（未保存）"))
        self.布局.addWidget(卡)
        self.布局.addWidget(标签(
            "自动启动通过 Windows 计划任务在指定时间运行启动脚本。电脑需要处于开机且已登录状态；"
            "若计划任务被系统或安全软件删除，状态会显示“计划任务丢失”。",
            "提示条", 换行=True,
        ))
        self.布局.addStretch(1)

    @property
    def 管理器(self):
        if self._管理器 is None:
            from 模块.自动启动管理器 import 自动启动管理器
            self._管理器 = 自动启动管理器()
        return self._管理器

    def 载入(self):
        标识 = self.控制器.实例ID
        try:
            配置 = self.管理器.获取所有自动启动配置().get(标识) or {}
        except Exception:
            配置 = {}
        self.启用.blockSignals(True)
        self.启用.setChecked(bool(配置.get("启用", False)))
        self.启用.blockSignals(False)
        时, _, 分 = str(配置.get("时间", "09:00")).partition(":")
        try:
            self.时间.setTime(QTime(int(时), int(分 or 0)))
        except ValueError:
            pass
        self.虚拟环境.setChecked(bool(配置.get("使用虚拟环境", True)))
        if not 配置.get("启用"):
            self.状态.setText("未启用")
            return
        self.状态.setText("检查中…")
        任务名称 = 配置.get("任务名称")
        后台执行(
            lambda: bool(任务名称) and self.管理器.检查计划任务是否存在(任务名称),
            lambda 存在: self.状态.setText(
                f"✓ 已设置，每天 {配置.get('时间', '')} 开始" if 存在 else "⚠ 配置存在但计划任务丢失"
            ),
            lambda 信息: self.状态.setText(f"检查失败：{信息}"),
        )

    def _保存(self):
        标识 = self.控制器.实例ID
        时间 = self.时间.time().toString("HH:mm")
        try:
            if self.启用.isChecked():
                成功 = self.管理器.设置机器人自动启动(标识, 时间, self.虚拟环境.isChecked())
                self.状态.setText(f"✓ 已设置，每天 {时间} 开始" if 成功 else "✗ 设置失败")
            else:
                成功 = self.管理器.取消机器人自动启动(标识)
                self.状态.setText("已关闭自动启动" if 成功 else "✗ 取消失败")
        except Exception as 异常:
            self.状态.setText(f"✗ 错误：{异常}")
            提示错误(self, "操作失败", str(异常))
            return
        if 成功:
            self.上下文.记录操作("自动启动设置已保存")
