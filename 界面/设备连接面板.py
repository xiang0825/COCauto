"""ADB 设备选择、截图预览与分辨率管理。"""
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cv2
from PIL import Image, ImageTk

from 模块.ADB设备操作类 import ADB设备操作类, ADB错误


class 设备连接面板(ttk.Frame):
    def __init__(self, 父容器, 数据库, 获取机器人回调):
        super().__init__(父容器, padding=14)
        self.数据库 = 数据库
        self.获取机器人回调 = 获取机器人回调
        self.当前机器人ID = None
        self._设备信息 = {}
        self._预览图 = None
        self.adb路径 = tk.StringVar()
        self.网络地址 = tk.StringVar()
        self.设备序列号 = tk.StringVar()
        self.设备已确认 = tk.BooleanVar(value=False)
        self.状态 = tk.StringVar(value="先选择机器人，然后扫描模拟器的 ADB 设备。")
        self._创建界面()

    def _创建界面(self):
        标题 = ttk.Frame(self)
        标题.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(标题, text="模拟器连接", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor=tk.W)
        ttk.Label(
            标题,
            text="每台设备都通过 adb -s 序列号隔离；截图和触控不会占用 Windows 鼠标、键盘或模拟器窗口。",
            wraplength=760,
        ).pack(anchor=tk.W, pady=(4, 0))

        内容 = ttk.Frame(self)
        内容.pack(fill=tk.BOTH, expand=True)
        左侧 = ttk.Frame(内容)
        左侧.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 16))
        右侧 = ttk.LabelFrame(内容, text="设备画面预览", padding=8)
        右侧.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(左侧, text="ADB 程序路径").pack(anchor=tk.W)
        路径行 = ttk.Frame(左侧)
        路径行.pack(fill=tk.X, pady=(3, 8))
        self.路径输入 = ttk.Entry(路径行, textvariable=self.adb路径, width=34)
        self.路径输入.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(路径行, text="浏览…", command=self._浏览ADB).pack(side=tk.LEFT, padx=(5, 0))

        ttk.Label(左侧, text="在线设备（请选模拟器序列号）").pack(anchor=tk.W)
        设备行 = ttk.Frame(左侧)
        设备行.pack(fill=tk.X, pady=(3, 8))
        self.设备选择 = ttk.Combobox(设备行, textvariable=self.设备序列号, width=31, state="readonly")
        self.设备选择.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.设备选择.bind("<<ComboboxSelected>>", self._设备更改)
        ttk.Button(设备行, text="扫描", command=self.扫描设备).pack(side=tk.LEFT, padx=(5, 0))

        ttk.Label(左侧, text="可选：连接 ADB 网络地址（host:port）").pack(anchor=tk.W, pady=(3, 0))
        网络行 = ttk.Frame(左侧)
        网络行.pack(fill=tk.X, pady=(3, 8))
        ttk.Entry(网络行, textvariable=self.网络地址, width=27).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(网络行, text="连接地址", command=self.连接网络地址).pack(side=tk.LEFT, padx=(5, 0))

        self.设备描述 = ttk.Label(左侧, text="尚未扫描设备。", wraplength=330)
        self.设备描述.pack(anchor=tk.W, fill=tk.X, pady=(0, 9))

        ttk.Checkbutton(
            左侧,
            text="确认目标为模拟器（非实体手机）",
            variable=self.设备已确认,
            command=self._确认状态变化,
        ).pack(anchor=tk.W, pady=(2, 8))

        按钮区 = ttk.Frame(左侧)
        按钮区.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(按钮区, text="保存连接", command=self.保存连接).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(按钮区, text="测试连接并截图", command=self.测试截图).pack(side=tk.LEFT)

        ttk.Separator(左侧).pack(fill=tk.X, pady=9)
        ttk.Label(左侧, text="脚本坐标自动适配实际分辨率。", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(
            左侧,
            text="任务以 800×600 为逻辑坐标，运行时自动映射到模拟器实际尺寸；下面按钮仅用于手动修改 Android 显示设置。",
            wraplength=330,
        ).pack(anchor=tk.W, pady=(3, 7))
        分辨率按钮 = ttk.Frame(左侧)
        分辨率按钮.pack(fill=tk.X)
        ttk.Button(分辨率按钮, text="设为 800×600", command=self.设置分辨率).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(分辨率按钮, text="恢复默认", command=self.恢复分辨率).pack(side=tk.LEFT)

        ttk.Label(左侧, textvariable=self.状态, wraplength=340, justify=tk.LEFT).pack(anchor=tk.W, pady=(12, 0))

        self.预览 = ttk.Label(右侧, text="连接后点击“测试连接并截图”显示画面。", anchor=tk.CENTER)
        self.预览.pack(fill=tk.BOTH, expand=True)
        self.预览尺寸 = ttk.Label(右侧, text="未获取截图", anchor=tk.W)
        self.预览尺寸.pack(fill=tk.X, pady=(5, 0))

    def 载入机器人(self, 机器人ID):
        self.当前机器人ID = 机器人ID
        if not 机器人ID:
            self.adb路径.set("")
            self.设备序列号.set("")
            self.设备已确认.set(False)
            self.设备描述.config(text="请先在左侧选择一个机器人配置。")
            self.状态.set("尚未选择机器人。")
            return
        设置 = self.数据库.获取机器人设置(机器人ID)
        self.adb路径.set(设置.ADB路径 or "")
        self.设备序列号.set(设置.ADB设备序列号 or "")
        self.设备已确认.set(bool(设置.ADB已确认模拟器))
        self.设备描述.config(text=f"机器人：{机器人ID}\n已保存设备：{设置.ADB设备序列号 or '未选择'}")
        self.状态.set("设置已载入。点击“扫描”检查在线设备。")
        self._预览图 = None
        self.预览.configure(image="", text="连接后点击“测试连接并截图”显示画面。")
        self.预览尺寸.config(text="未获取截图")

    def _浏览ADB(self):
        路径 = filedialog.askopenfilename(
            title="选择模拟器目录中的 adb.exe",
            filetypes=(("ADB 程序", "adb.exe"), ("所有文件", "*.*")),
        )
        if 路径:
            self.adb路径.set(路径)

    def _设备更改(self, _事件=None):
        self.设备已确认.set(False)
        设备 = self._设备信息.get(self.设备序列号.get())
        描述 = 设备.描述 if 设备 else ""
        self.设备描述.config(text=f"目标：{self.设备序列号.get()}\n{描述 or 'ADB 设备'}\n切换设备后请重新确认目标为模拟器。")

    def _确认状态变化(self):
        if self.设备已确认.get() and not self.设备序列号.get().strip():
            self.设备已确认.set(False)
            messagebox.showwarning("尚未选择设备", "请先扫描并选择一个 ADB 设备。", parent=self)

    def _后台(self, 工作, 成功提示):
        def 执行():
            try:
                结果 = 工作()
            except Exception as 异常:
                self.after(0, lambda 错误=str(异常): self.状态.set(f"失败：{错误}"))
                return
            self.after(0, lambda: 成功提示(结果))
        threading.Thread(target=执行, name="ADB连接任务", daemon=True).start()

    def 扫描设备(self):
        self.状态.set("正在扫描 ADB 设备…")
        adb路径 = self.adb路径.get().strip()
        def 完成(设备列表):
            self._设备信息 = {设备.序列号: 设备 for 设备 in 设备列表}
            self.设备选择.configure(values=[设备.序列号 for 设备 in 设备列表])
            if self.设备序列号.get() not in self._设备信息 and 设备列表:
                # 不替用户自动选中唯一设备，防止把连接中的实体手机当模拟器。
                self.设备序列号.set("")
            if not 设备列表:
                self.设备描述.config(text="未发现设备。请在模拟器设置中启用 ADB 调试并保持模拟器运行。")
                self.状态.set("没有在线 ADB 设备。")
            else:
                self.设备描述.config(text="\n".join(设备.显示文本 for 设备 in 设备列表))
                self.状态.set(f"发现 {len(设备列表)} 台设备。请选择要连接的模拟器。")
        self._后台(lambda: ADB设备操作类.扫描设备(adb路径), 完成)

    def 连接网络地址(self):
        地址 = self.网络地址.get().strip()
        self.状态.set(f"正在连接 ADB 地址 {地址}…")
        adb路径 = self.adb路径.get().strip()
        def 完成(文本):
            self.状态.set(f"{文本}；请扫描设备并明确选择目标。")
        self._后台(lambda: ADB设备操作类.连接网络设备(adb路径, 地址), 完成)

    def _取已确认设备(self):
        if not self.设备序列号.get().strip():
            raise ADB错误("请先扫描并选择设备。")
        if not self.设备已确认.get():
            raise ADB错误("请确认目标是 Android 模拟器，不是实体手机。")
        设备 = ADB设备操作类(self.adb路径.get().strip(), self.设备序列号.get().strip())
        设备.确认在线()
        return 设备

    def 保存连接(self):
        if not self.当前机器人ID:
            messagebox.showwarning("尚未选择机器人", "请先在左侧选择或创建机器人配置。", parent=self)
            return
        try:
            if self.设备已确认.get():
                if not self.设备序列号.get().strip():
                    raise ADB错误("请先扫描并选择设备。")
                ADB设备操作类.解析ADB路径(self.adb路径.get().strip())
            设置 = self.数据库.获取机器人设置(self.当前机器人ID)
            设置.ADB路径 = self.adb路径.get().strip()
            设置.ADB设备序列号 = self.设备序列号.get().strip()
            设置.ADB已确认模拟器 = bool(self.设备已确认.get() and 设置.ADB设备序列号)
            self.数据库.保存机器人设置(self.当前机器人ID, 设置)
            self.状态.set(f"连接配置已保存：{设置.ADB设备序列号 or '未选择设备'}")
        except Exception as 异常:
            messagebox.showerror("保存失败", str(异常), parent=self)

    def 测试截图(self):
        self.状态.set("正在验证 ADB 连接并获取截图…")
        def 完成(结果):
            图像, 尺寸 = 结果
            画面 = Image.fromarray(cv2.cvtColor(图像, cv2.COLOR_BGR2RGB))
            画面.thumbnail((850, 600), Image.Resampling.LANCZOS)
            self._预览图 = ImageTk.PhotoImage(画面)
            self.预览.configure(image=self._预览图, text="")
            自然宽, 自然高 = 尺寸
            self.预览尺寸.config(text=f"设备原始截图：{自然宽} × {自然高}；脚本需要 800 × 600。")
            if 尺寸 == (800, 600):
                self.状态.set("连接和截图正常。可保存连接，再从左侧启动机器人。")
            else:
                self.状态.set(f"连接和截图正常；已启用自动适配（实际 {自然宽}×{自然高}，逻辑 800×600）。")
        def 工作():
            设备 = self._取已确认设备()
            图像 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
            return 图像, (图像.shape[1], 图像.shape[0])
        self._后台(工作, 完成)

    def 设置分辨率(self):
        self._运行分辨率操作("设置为 800×600", lambda 设备: 设备.设置屏幕尺寸(800, 600))

    def 恢复分辨率(self):
        self._运行分辨率操作("恢复 Android 默认分辨率", lambda 设备: 设备.恢复屏幕尺寸())

    def _运行分辨率操作(self, 文案, 操作):
        if not messagebox.askyesno("确认模拟器设置", f"确定要对 {self.设备序列号.get()} 执行“{文案}”吗？\n\n仅对已确认的模拟器发送 ADB 显示设置命令。", parent=self):
            return
        self.状态.set(f"正在{文案}…")
        def 完成(_结果):
            self.状态.set(f"已{文案}。请重新点击“测试连接并截图”核对画面。")
        self._后台(lambda: 操作(self._取已确认设备()), 完成)
