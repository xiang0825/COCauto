"""手机控制：局域网服务、一次性配对码与授权管理。"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from 界面.页面基类 import 页面基类
from 界面.组件 import PIL转图像, 卡片, 提示错误, 提示信息, 标签, 横排, 确认


class 手机控制页(页面基类):
    标题 = "手机控制"
    说明 = "手动开启后，同一局域网内已配对的手机可以查看状态并开始、暂停或停止任务。"

    def __init__(self, 上下文, 控制桥):
        super().__init__(上下文)
        self._桥 = 控制桥
        self._服务信息 = None
        self._配对码 = ""
        self._配对截止 = 0.0

        服务卡 = 卡片("局域网服务")
        self.地址 = QComboBox()
        self.地址.setMinimumWidth(220)
        刷新地址 = QPushButton("刷新")
        刷新地址.clicked.connect(self._刷新地址)
        self.启动按钮 = QPushButton("启动手机控制")
        self.启动按钮.setObjectName("主按钮")
        self.启动按钮.clicked.connect(self._启动)
        self.停止按钮 = QPushButton("停止服务")
        self.停止按钮.setEnabled(False)
        self.停止按钮.clicked.connect(self._停止)
        服务卡.布局.addLayout(横排(标签("绑定地址", "次要"), self.地址, 刷新地址, None, self.启动按钮, self.停止按钮))
        self.服务状态 = 标签("手机控制服务未开启", "次要", 换行=True)
        服务卡.布局.addWidget(self.服务状态)
        服务卡.布局.addWidget(标签("只绑定选定的本机私有地址，不开放公网监听，也不配置路由器转发。", "弱", 换行=True))
        self.布局.addWidget(服务卡)

        配对卡 = 卡片("手机配对")
        内容 = QHBoxLayout()
        内容.setSpacing(24)
        左 = QVBoxLayout()
        self.运行状态 = 标签("服务未开启", "次要", 换行=True)
        左.addWidget(self.运行状态)
        self.配对按钮 = QPushButton("生成 5 分钟配对码")
        self.配对按钮.setEnabled(False)
        self.配对按钮.clicked.connect(self._生成配对码)
        左.addLayout(横排(self.配对按钮, None))
        self.配对状态 = 标签("启动服务后生成一次性配对码。", 换行=True)
        self.配对状态.setStyleSheet("font-size: 15px;")
        左.addWidget(self.配对状态)
        撤销 = QPushButton("撤销全部手机授权")
        撤销.setObjectName("危险按钮")
        撤销.clicked.connect(self._撤销)
        左.addLayout(横排(撤销, None))
        左.addStretch(1)
        内容.addLayout(左, 1)
        self.二维码 = QLabel("二维码会显示在这里")
        self.二维码.setObjectName("弱")
        self.二维码.setAlignment(Qt.AlignCenter)
        self.二维码.setFixedSize(230, 230)
        内容.addWidget(self.二维码)
        配对卡.布局.addLayout(内容)
        self.布局.addWidget(配对卡)
        self.布局.addStretch(1)

        self._命令计时 = QTimer(self)
        self._命令计时.timeout.connect(self._处理远程命令)
        self._命令计时.start(100)
        self._状态计时 = QTimer(self)
        self._状态计时.timeout.connect(self._刷新运行状态)
        self._状态计时.start(1000)
        self._地址计时 = QTimer(self)
        self._地址计时.timeout.connect(self._刷新地址)
        self._地址计时.start(15000)
        self._刷新地址()

    # ------------------------------------------------------------ 服务
    def _刷新地址(self):
        if self._服务信息 is not None:
            return
        try:
            from 服务.局域网控制服务 import list_private_local_addresses
            地址列表 = list_private_local_addresses()
        except Exception:
            地址列表 = []
        当前 = self.地址.currentText()
        self.地址.clear()
        self.地址.addItems(地址列表)
        if 当前 in 地址列表:
            self.地址.setCurrentText(当前)
        self.启动按钮.setEnabled(bool(地址列表))
        self.服务状态.setText(
            "请选择本机局域网地址，然后手动启动服务。" if 地址列表
            else "未发现可用的本机私有地址，请确认电脑已连接局域网。"
        )

    def _启动(self):
        机器人ID = self.控制器.实例ID
        地址 = self.地址.currentText().strip()
        if not 地址:
            提示信息(self, "选择网络", "请先选择本机局域网地址。")
            return
        try:
            信息 = self._桥.start(地址, 机器人ID)
        except Exception as 异常:
            提示错误(self, "启动手机控制失败", str(异常))
            return
        self._服务信息 = 信息
        self.启动按钮.setEnabled(False)
        self.地址.setEnabled(False)
        self.停止按钮.setEnabled(True)
        self.配对按钮.setEnabled(True)
        self.服务状态.setText(
            f"服务运行中 · {信息['endpoint']}\n证书指纹 {信息['fingerprint']}"
        )
        self.配对状态.setText("每个配对码仅能使用一次，5 分钟后自动失效。")
        self.上下文.记录操作(f"手机控制服务已启动：{地址}")

    def _停止(self):
        try:
            self._桥.stop()
        except Exception as 异常:
            提示错误(self, "停止手机控制失败", str(异常))
            return
        self._服务信息 = None
        self._清除配对()
        self.配对状态.setText("服务已停止。")
        self.地址.setEnabled(True)
        self.停止按钮.setEnabled(False)
        self.配对按钮.setEnabled(False)
        self._刷新地址()
        self.上下文.记录操作("手机控制服务已停止")

    # ------------------------------------------------------------ 配对
    def _清除配对(self):
        self._配对码 = ""
        self._配对截止 = 0.0
        self.二维码.setPixmap(QPixmap())
        self.二维码.setText("二维码会显示在这里")

    def _生成配对码(self):
        if not self._服务信息:
            return
        try:
            from 服务.局域网控制服务 import create_pairing_qr_image
            配对 = self._桥.begin_pairing()
            图片 = create_pairing_qr_image(配对["qr_payload"])
        except Exception as 异常:
            提示错误(self, "生成配对码失败", str(异常))
            return
        图 = QPixmap.fromImage(PIL转图像(图片))
        self.二维码.setPixmap(图.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._配对码 = 配对["code"]
        self._配对截止 = time.monotonic() + max(0.0, float(配对["expires_at"]) - time.monotonic())
        self._更新倒计时()
        self.上下文.记录操作("已生成一次性手机配对码")

    def _更新倒计时(self):
        if not self._配对码:
            return
        剩余 = max(0, int(self._配对截止 - time.monotonic()))
        if 剩余 == 0:
            self._清除配对()
            self.配对状态.setText("配对码已过期，请重新生成。")
            return
        self.配对状态.setText(f"配对码：<b>{self._配对码}</b>　剩余 {剩余 // 60}:{剩余 % 60:02d}")

    def _撤销(self):
        if not 确认(self, "撤销授权", "撤销所有已配对手机的授权？手机需要重新配对。"):
            return
        try:
            数量 = self._桥.revoke_all()
        except Exception as 异常:
            提示错误(self, "撤销授权失败", str(异常))
            return
        self._清除配对()
        self.配对状态.setText(f"已撤销 {数量} 个手机授权和所有待用配对码。")
        self.上下文.记录操作(f"已撤销全部手机授权：{数量} 个")

    # ------------------------------------------------------------ 轮询
    def _处理远程命令(self):
        try:
            if self._桥.is_running:
                self._桥.process_pending()
        except Exception as 异常:
            self.服务状态.setText(f"手机命令处理异常：{异常}")

    def _刷新运行状态(self):
        self._更新倒计时()
        if not self._服务信息:
            return
        try:
            快照 = self._桥.refresh_bound_snapshot()
        except Exception as 异常:
            self.运行状态.setText(f"无法读取运行状态：{异常}")
            return
        if 快照:
            任务 = "、".join(快照["selected_tasks"]) or "未选择任务"
            self.运行状态.setText(
                f"{快照['state']} · ADB：{快照['adb_state']} · "
                f"游戏：{快照['game_state']}\n任务：{任务} · 版本：{快照['version']}"
            )

    def 关闭(self):
        for 计时 in (self._命令计时, self._状态计时, self._地址计时):
            计时.stop()
        try:
            self._桥.stop()
        except Exception:
            pass
