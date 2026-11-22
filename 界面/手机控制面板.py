"""桌面端局域网手机控制设置。"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

from 服务.局域网控制服务 import (
    create_pairing_qr_image,
    list_private_local_addresses,
)


class 手机控制面板(ttk.Frame):
    def __init__(self, 父容器, *, 控制桥, 获取当前机器人, 操作日志回调=None):
        super().__init__(父容器)
        self._控制桥 = 控制桥
        self._获取当前机器人 = 获取当前机器人
        self._操作日志回调 = 操作日志回调 or (lambda _内容: None)
        self._服务信息 = None
        self._配对码 = ""
        self._配对过期时间 = 0.0
        self._二维码图片 = None
        self._地址 = tk.StringVar()
        self._状态 = tk.StringVar(value="手机控制服务未开启")
        self._配对状态 = tk.StringVar(value="启动服务后生成一次性配对码。")
        self._运行状态 = tk.StringVar(value="尚未连接机器人")
        self._创建界面()
        self._刷新地址()
        self.after(100, self._处理远程命令)
        self.after(1000, self._刷新运行状态)

    def _创建界面(self):
        引导 = tk.Frame(self, bg="#fff0e1", padx=22, pady=18)
        引导.pack(fill=tk.X, pady=(0, 16))
        文案 = tk.Frame(引导, bg="#fff0e1")
        文案.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            文案,
            text="手机控制",
            bg="#fff0e1",
            fg="#8f4c2d",
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(anchor=tk.W)
        tk.Label(
            文案,
            text="手动开启后，通过同一局域网安全查看状态并控制已选机器人。",
            bg="#fff0e1",
            fg="#735f51",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor=tk.W, pady=(5, 0))

        网络卡 = ttk.Frame(self, style="Card.TFrame", padding=22)
        网络卡.pack(fill=tk.X, pady=(0, 14))
        ttk.Label(
            网络卡, text="局域网服务", style="Card.TLabel",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).grid(row=0, column=0, sticky="w", columnspan=3)
        ttk.Label(网络卡, text="绑定地址", style="CardMuted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(14, 0)
        )
        self._地址选择 = ttk.Combobox(
            网络卡, textvariable=self._地址, state="readonly", width=28
        )
        self._地址选择.grid(row=1, column=1, sticky="w", padx=(12, 16), pady=(14, 0))
        self._启动按钮 = ttk.Button(
            网络卡, text="启动手机控制", command=self._启动服务
        )
        self._启动按钮.grid(row=1, column=2, sticky="w", pady=(14, 0))
        self._停止按钮 = ttk.Button(
            网络卡, text="停止服务", command=self._停止服务, state=tk.DISABLED
        )
        self._停止按钮.grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(14, 0))
        ttk.Label(
            网络卡,
            textvariable=self._状态,
            style="CardMuted.TLabel",
            wraplength=900,
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(12, 0))
        ttk.Label(
            网络卡,
            text="只绑定选定的本机私有地址；不开放公网监听，也不配置路由器转发。",
            style="CardMuted.TLabel",
            wraplength=900,
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(5, 0))

        配对卡 = ttk.Frame(self, style="Card.TFrame", padding=22)
        配对卡.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            配对卡, text="手机配对", style="Card.TLabel",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor=tk.W)
        配对内容 = ttk.Frame(配对卡, style="CardBody.TFrame")
        配对内容.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        左侧 = ttk.Frame(配对内容, style="CardBody.TFrame")
        左侧.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._二维码标签 = ttk.Label(配对内容, text="二维码会显示在这里。", anchor="center")
        self._二维码标签.pack(side=tk.RIGHT, padx=(24, 4), pady=4)
        ttk.Label(
            左侧,
            textvariable=self._运行状态,
            style="CardMuted.TLabel",
            wraplength=760,
        ).pack(anchor=tk.W, pady=(2, 12))
        self._生成配对按钮 = ttk.Button(
            左侧,
            text="生成 5 分钟配对码",
            command=self._生成配对码,
            state=tk.DISABLED,
        )
        self._生成配对按钮.pack(anchor=tk.W)
        ttk.Label(
            左侧,
            textvariable=self._配对状态,
            style="Card.TLabel",
            wraplength=760,
        ).pack(anchor=tk.W, pady=(10, 0))
        self._撤销按钮 = ttk.Button(
            左侧,
            text="撤销全部手机授权",
            command=self._撤销授权,
        )
        self._撤销按钮.pack(anchor=tk.W, pady=(16, 0))

    def _刷新地址(self):
        try:
            addresses = list_private_local_addresses()
        except Exception:
            addresses = []
        self._地址选择.configure(values=addresses)
        if self._服务信息 is None:
            if self._地址.get() not in addresses:
                self._地址.set(addresses[0] if addresses else "")
            if addresses:
                self._状态.set("请选择本机局域网地址，然后手动启动服务。")
            else:
                self._状态.set("未发现可用的本机私有地址，请确认电脑已连接局域网。")
        self.after(15000, self._刷新地址)

    def _启动服务(self):
        robot_id = str(self._获取当前机器人() or "").strip()
        address = self._地址.get().strip()
        if not robot_id:
            messagebox.showinfo("选择机器人", "请先在顶部选择一个机器人。", parent=self)
            return
        if not address:
            messagebox.showinfo("选择网络", "请先选择本机局域网地址。", parent=self)
            return
        try:
            info = self._控制桥.start(address, robot_id)
        except Exception as error:
            messagebox.showerror("启动手机控制失败", str(error), parent=self)
            return
        self._服务信息 = info
        self._启动按钮.configure(state=tk.DISABLED)
        self._地址选择.configure(state=tk.DISABLED)
        self._停止按钮.configure(state=tk.NORMAL)
        self._生成配对按钮.configure(state=tk.NORMAL)
        self._状态.set(
            f"服务运行中 · {info['endpoint']} · 绑定机器人 {robot_id} · "
            f"证书指纹 {info['fingerprint']}"
        )
        self._配对状态.set("每个配对码仅能使用一次，5 分钟后自动失效。")
        self._操作日志回调(f"手机控制服务已启动：{robot_id} / {address}")

    def _停止服务(self):
        try:
            self._控制桥.stop()
        except Exception as error:
            messagebox.showerror("停止手机控制失败", str(error), parent=self)
            return
        self._服务信息 = None
        self._配对码 = ""
        self._配对过期时间 = 0.0
        self._二维码图片 = None
        self._二维码标签.configure(image="", text="二维码会显示在这里。")
        self._配对状态.set("服务已停止。")
        self._状态.set("手机控制服务未开启")
        self._启动按钮.configure(state=tk.NORMAL if self._地址.get() else tk.DISABLED)
        self._地址选择.configure(state="readonly")
        self._停止按钮.configure(state=tk.DISABLED)
        self._生成配对按钮.configure(state=tk.DISABLED)
        self._操作日志回调("手机控制服务已停止")

    def _生成配对码(self):
        if not self._服务信息:
            return
        try:
            pairing = self._控制桥.begin_pairing()
            image = create_pairing_qr_image(pairing["qr_payload"])
            from PIL import ImageTk

            image.thumbnail((210, 210))
            self._二维码图片 = ImageTk.PhotoImage(image)
        except Exception as error:
            messagebox.showerror("生成配对码失败", str(error), parent=self)
            return
        self._配对码 = pairing["code"]
        self._配对过期时间 = time.monotonic() + max(
            0.0, float(pairing["expires_at"]) - time.monotonic()
        )
        self._二维码标签.configure(image=self._二维码图片, text="")
        self._更新配对倒计时()
        self._操作日志回调(f"已为 {pairing['robot_id']} 生成一次性手机配对码")

    def _更新配对倒计时(self):
        if not self._配对码:
            return
        remaining = max(0, int(self._配对过期时间 - time.monotonic()))
        if remaining == 0:
            self._配对码 = ""
            self._配对状态.set("配对码已过期，请重新生成。")
            return
        self._配对状态.set(
            f"配对码：{self._配对码}    剩余 {remaining // 60}:{remaining % 60:02d}"
        )
        self.after(1000, self._更新配对倒计时)

    def _撤销授权(self):
        try:
            revoked = self._控制桥.revoke_all()
        except Exception as error:
            messagebox.showerror("撤销授权失败", str(error), parent=self)
            return
        self._配对码 = ""
        self._配对过期时间 = 0.0
        self._二维码图片 = None
        self._二维码标签.configure(image="", text="二维码会显示在这里。")
        self._配对状态.set(f"已撤销 {revoked} 个手机授权和所有待用配对码。")
        self._操作日志回调(f"已撤销全部手机授权：{revoked} 个")

    def _处理远程命令(self):
        try:
            if self._控制桥.is_running:
                self._控制桥.process_pending()
        except tk.TclError:
            return
        except Exception as error:
            self._状态.set(f"手机命令处理异常：{error}")
        self.after(100, self._处理远程命令)

    def _刷新运行状态(self):
        if self._服务信息:
            try:
                snapshot = self._控制桥.refresh_bound_snapshot()
                if snapshot:
                    tasks = "、".join(snapshot["selected_tasks"]) or "未选择任务"
                    self._运行状态.set(
                        f"机器人 {snapshot['robot_id']} · {snapshot['state']} · "
                        f"ADB：{snapshot['adb_state']} · 游戏：{snapshot['game_state']} · "
                        f"任务：{tasks} · 版本：{snapshot['version']}"
                    )
            except Exception as error:
                self._运行状态.set(f"无法读取机器人状态：{error}")
        self.after(1000, self._刷新运行状态)
