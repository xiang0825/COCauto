"""横向机器人选择与运行控制。"""
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from 数据库.任务数据库 import 机器人设置


class 机器人管理面板(ttk.Frame):
    def __init__(self, 父容器, 监控中心, 选择变化回调):
        super().__init__(父容器, style="Bar.TFrame")
        self.监控中心 = 监控中心
        self.选择变化回调 = 选择变化回调
        self.当前机器人ID = None
        self._机器人变量 = tk.StringVar()
        self._状态变量 = tk.StringVar(value="未选择机器人")
        self._创建界面()
        self._定时刷新机器人列表()

    def _创建界面(self):
        tk.Label(self, text="机器人", bg="#ffffff", fg="#697788",
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 10))
        self.机器人选择 = ttk.Combobox(
            self, textvariable=self._机器人变量, state="readonly", width=16,
        )
        self.机器人选择.pack(side=tk.LEFT)
        self.机器人选择.bind("<<ComboboxSelected>>", self._更新当前选择)
        ttk.Button(self, text="新建", command=self._新建机器人).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(self, text="删除", command=self._删除选中机器人).pack(side=tk.LEFT, padx=(4, 0))
        tk.Label(self, textvariable=self._状态变量, bg="#ffffff", fg="#697788",
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(16, 0))

        操作 = ttk.Frame(self, style="Bar.TFrame")
        操作.pack(side=tk.RIGHT)
        self.启动按钮 = tk.Button(操作, text="启动", command=self._启动机器人,
                  bg="#bd6536", fg="#ffffff", activebackground="#a7562b",
                  activeforeground="#ffffff", relief=tk.FLAT, bd=0,
                  padx=22, pady=7, cursor="hand2",
                  font=("Microsoft YaHei UI", 10, "bold"))
        self.启动按钮.pack(side=tk.LEFT, padx=(0, 8))
        self.暂停按钮 = ttk.Button(操作, text="暂停", command=self._暂停机器人)
        self.暂停按钮.pack(side=tk.LEFT)
        self.继续按钮 = ttk.Button(操作, text="继续", command=self._继续机器人)
        self.继续按钮.pack(side=tk.LEFT, padx=(4, 0))
        self.停止按钮 = ttk.Button(操作, text="停止", command=self._停止机器人)
        self.停止按钮.pack(side=tk.LEFT, padx=(4, 0))

    def _定时刷新机器人列表(self):
        self.更新机器人列表()
        self.after(3000, self._定时刷新机器人列表)

    def 获取当前机器人(self):
        return self.监控中心.机器人池.get(self.当前机器人ID)

    def _更新当前选择(self, _事件=None):
        新ID = self._机器人变量.get()
        if 新ID and 新ID != self.当前机器人ID:
            self.当前机器人ID = 新ID
            self.更新状态显示()
            self.选择变化回调(新ID)

    def 更新状态显示(self):
        机器人 = self.获取当前机器人()
        状态 = str(getattr(机器人, "当前状态", "未选择机器人"))
        self._状态变量.set(状态)
        正在运行 = 状态 == "运行中"
        暂停中 = 状态 == "暂停中"
        self.启动按钮.configure(state=tk.NORMAL if 机器人 and not (正在运行 or 暂停中) else tk.DISABLED)
        self.暂停按钮.configure(state=tk.NORMAL if 正在运行 else tk.DISABLED)
        self.继续按钮.configure(state=tk.NORMAL if 暂停中 else tk.DISABLED)
        self.停止按钮.configure(state=tk.NORMAL if 正在运行 or 暂停中 else tk.DISABLED)

    def 选中机器人(self, 机器人ID):
        self.更新机器人列表()
        if 机器人ID not in self.监控中心.机器人池:
            return
        self._机器人变量.set(机器人ID)
        self._更新当前选择()

    def 更新机器人列表(self):
        标识 = tuple(self.监控中心.机器人池)
        if tuple(self.机器人选择.cget("values")) != 标识:
            self.机器人选择.configure(values=标识)
        if self.当前机器人ID not in self.监控中心.机器人池:
            self.当前机器人ID = None
            self._机器人变量.set("")
        self.更新状态显示()

    def _启动机器人(self):
        机器人 = self.获取当前机器人()
        if not 机器人:
            messagebox.showinfo("选择机器人", "请先选择机器人。", parent=self)
            return
        try:
            self.监控中心.启动机器人(机器人.机器人标志)
            self.更新状态显示()
        except Exception as 异常:
            messagebox.showerror("启动失败", str(异常), parent=self)

    def _暂停机器人(self):
        机器人 = self.获取当前机器人()
        if 机器人:
            try:
                机器人.暂停()
                self.更新状态显示()
            except Exception as 异常:
                messagebox.showerror("暂停失败", str(异常), parent=self)

    def _继续机器人(self):
        机器人 = self.获取当前机器人()
        if 机器人:
            try:
                机器人.继续()
                self.更新状态显示()
            except Exception as 异常:
                messagebox.showerror("继续失败", str(异常), parent=self)

    def _停止机器人(self):
        机器人 = self.获取当前机器人()
        if 机器人:
            threading.Thread(target=机器人.停止,
                             name=f"停止-{机器人.机器人标志}", daemon=True).start()

    def _新建机器人(self):
        已有 = set(self.监控中心.机器人池)
        序号 = 1
        while f"robot_{序号}" in 已有:
            序号 += 1
        标识 = simpledialog.askstring("新建机器人", "机器人名称：",
                                    initialvalue=f"robot_{序号}", parent=self)
        if not 标识 or not 标识.strip():
            return
        标识 = 标识.strip()
        if 标识 in 已有:
            messagebox.showerror("创建失败", "该名称已存在。", parent=self)
            return
        try:
            self.监控中心.创建机器人(标识, 机器人设置())
            self.选中机器人(标识)
        except Exception as 异常:
            messagebox.showerror("创建失败", str(异常), parent=self)

    def _删除选中机器人(self):
        机器人 = self.获取当前机器人()
        if not 机器人:
            return
        标识 = self.当前机器人ID
        if not messagebox.askyesno("确认删除", f"永久删除 {标识} 的配置？", parent=self):
            return
        try:
            机器人.停止(等待=False)
            del self.监控中心.机器人池[标识]
            self.当前机器人ID = None
            self.更新机器人列表()
            self.选择变化回调(None, 删除=标识)
            剩余 = tuple(self.监控中心.机器人池)
            if 剩余:
                self.选中机器人(剩余[0])
        except Exception as 异常:
            messagebox.showerror("删除失败", str(异常), parent=self)
