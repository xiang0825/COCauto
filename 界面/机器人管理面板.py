"""
机器人管理面板模块 - 机器人列表、状态显示和控制功能
"""
import tkinter as tk
import threading
from tkinter import simpledialog, ttk, messagebox
from typing import Callable, Optional

from 数据库.任务数据库 import 机器人设置


class 机器人管理面板(ttk.LabelFrame):
    """机器人管理面板"""

    def __init__(self, 父容器, 监控中心, 选择变化回调: Callable[[Optional[str]], None]):
        """
        初始化机器人管理面板
        :param 父容器: 父容器控件
        :param 监控中心: 机器人监控中心实例
        :param 选择变化回调: 机器人选择变化时的回调函数，参数为机器人ID（或None）
        """
        super().__init__(父容器, text="机器人管理")
        self.监控中心 = 监控中心
        self.选择变化回调 = 选择变化回调
        self.当前机器人ID: Optional[str] = None

        self._创建界面()
        self._定时刷新机器人列表()

    def _创建界面(self):
        """创建管理面板界面"""
        # 机器人列表 Treeview
        self.机器人列表框 = ttk.Treeview(self, columns=('status'), show='tree headings', height=8, style="Robot.Treeview")
        self.机器人列表框.column('#0', width=250, anchor=tk.W)
        self.机器人列表框.heading('#0', text='机器人标识', anchor=tk.W)
        self.机器人列表框.column('status', width=80, anchor=tk.CENTER)
        self.机器人列表框.heading('status', text='状态', anchor=tk.CENTER)
        self.机器人列表框.pack(pady=5, fill=tk.BOTH, expand=True)
        self.机器人列表框.bind('<<TreeviewSelect>>', self._更新当前选择)
        self.机器人列表框.bind("<Button-1>", self._处理列表点击)

        # 列表操作按钮
        列表操作面板 = ttk.Frame(self)
        列表操作面板.pack(pady=5, fill=tk.X)
        ttk.Button(列表操作面板, text="新建机器人", command=self._新建机器人).pack(side=tk.LEFT, padx=2)
        ttk.Button(列表操作面板, text="刷新列表", command=self.更新机器人列表).pack(side=tk.LEFT, padx=2)
        ttk.Button(列表操作面板, text="删除选中", command=self._删除选中机器人).pack(side=tk.LEFT, padx=2)

        # 控制按钮
        控制按钮框架 = ttk.LabelFrame(self, text="控制当前选中")
        控制按钮框架.pack(fill=tk.X, pady=5)

        控制按钮框架.columnconfigure(0, weight=1)
        控制按钮框架.columnconfigure(1, weight=1)
        ttk.Button(控制按钮框架, text="▶ 启动", command=self._启动机器人).grid(row=0, column=0, sticky=tk.EW, padx=5, pady=4)
        ttk.Button(控制按钮框架, text="暂停", command=self._暂停机器人).grid(row=0, column=1, sticky=tk.EW, padx=5, pady=4)
        ttk.Button(控制按钮框架, text="继续", command=self._继续机器人).grid(row=1, column=0, sticky=tk.EW, padx=5, pady=4)
        ttk.Button(控制按钮框架, text="■ 停止", command=self._停止机器人).grid(row=1, column=1, sticky=tk.EW, padx=5, pady=4)

    def _定时刷新机器人列表(self):
        """定时刷新机器人列表"""
        self.更新机器人列表()
        self.after(1500, self._定时刷新机器人列表)

    def 获取当前机器人(self):
        """返回当前选中的机器人实例"""
        if self.当前机器人ID:
            return self.监控中心.机器人池.get(self.当前机器人ID)
        return None

    def _处理列表点击(self, event):
        """处理列表点击。

        机器人列表通常只有一个默认机器人；点击列表空白处不应意外清空当前
        配置，否则任务计划页会立刻变成“请选择机器人”，看起来像所有配置失效。
        """
        item = self.机器人列表框.identify_row(event.y)
        if not item:
            return

    def _更新当前选择(self, event):
        """处理列表选择变化"""
        选中项 = self.机器人列表框.selection()
        if not 选中项:
            return

        新机器人ID = self.机器人列表框.item(选中项[0], 'text')

        # 只有当机器人改变时才更新
        if 新机器人ID != self.当前机器人ID:
            self.当前机器人ID = 新机器人ID
            self.更新状态显示()
            self.选择变化回调(新机器人ID)

    def 更新状态显示(self):
        """兼容旧回调；状态直接显示在机器人列表的“状态”列。"""
        return

    def 选中机器人(self, 机器人ID: str):
        """选中指定机器人，用于首次启动时自动选中默认项。"""
        self.更新机器人列表()
        for 项 in self.机器人列表框.get_children():
            if self.机器人列表框.item(项, "text") == 机器人ID:
                self.当前机器人ID = 机器人ID
                self.机器人列表框.selection_set(项)
                self.机器人列表框.focus(项)
                self.更新状态显示()
                self.选择变化回调(机器人ID)
                return

    def 更新机器人列表(self):
        """刷新列表显示"""
        原列表项 = {self.机器人列表框.item(item, 'text'): item
                    for item in self.机器人列表框.get_children()}

        # 同步监控中心的机器人
        for 标识 in self.监控中心.机器人池.keys():
            if 标识 not in 原列表项:
                self.机器人列表框.insert('', tk.END, text=标识, values=('未运行',))

        # 移除不存在的项
        for 标识, item in 原列表项.items():
            if 标识 not in self.监控中心.机器人池:
                self.机器人列表框.delete(item)

        # 更新状态显示
        for item in self.机器人列表框.get_children():
            标识 = self.机器人列表框.item(item, 'text')
            if robot := self.监控中心.机器人池.get(标识):
                self.机器人列表框.set(item, 'status', robot.当前状态)

        # 清除所有选择
        self.机器人列表框.selection_remove(self.机器人列表框.selection())

        # 重新设置选择（如果有当前ID）
        if self.当前机器人ID:
            for item in self.机器人列表框.get_children():
                if self.机器人列表框.item(item, 'text') == self.当前机器人ID:
                    self.机器人列表框.selection_set(item)
                    break

    def _启动机器人(self):
        """启动当前选中的机器人"""
        机器人 = self.获取当前机器人()
        if 机器人:
            try:
                self.监控中心.启动机器人(机器人.机器人标志)
                return f"{机器人.机器人标志} 已启动"
            except Exception as e:
                messagebox.showerror("启动失败", str(e))
        return None

    def _暂停机器人(self):
        """暂停当前选中的机器人"""
        机器人 = self.获取当前机器人()
        if 机器人:
            try:
                机器人.暂停()
                return f"{机器人.机器人标志} 已暂停"
            except Exception as e:
                messagebox.showerror("暂停失败", str(e))
        return None

    def _继续机器人(self):
        """继续当前选中的机器人"""
        机器人 = self.获取当前机器人()
        if 机器人:
            try:
                机器人.继续()
                return f"{机器人.机器人标志} 已继续运行"
            except Exception as e:
                messagebox.showerror("继续失败", str(e))
        return None

    def _停止机器人(self):
        """停止当前选中的机器人"""
        机器人 = self.获取当前机器人()
        if 机器人:
            try:
                # 停止可能需要等待 ADB 命令返回，不能阻塞 Tk 主线程。
                threading.Thread(
                    target=机器人.停止,
                    name=f"停止-{机器人.机器人标志}",
                    daemon=True,
                ).start()
                return f"{机器人.机器人标志} 已停止"
            except Exception as e:
                messagebox.showerror("停止失败", str(e))
        return None

    def _新建机器人(self):
        """创建默认配置，并交给任务计划页继续设置。"""
        默认标识 = "robot_1"
        已有标识 = set(self.监控中心.机器人池)
        序号 = 1
        while 默认标识 in 已有标识:
            序号 += 1
            默认标识 = f"robot_{序号}"
        标识 = simpledialog.askstring(
            "新建机器人",
            "请输入机器人标识：",
            initialvalue=默认标识,
            parent=self,
        )
        if not 标识 or not 标识.strip():
            return
        标识 = 标识.strip()
        if 标识 in 已有标识:
            messagebox.showerror("创建失败", f"机器人“{标识}”已经存在。", parent=self)
            return
        try:
            self.监控中心.创建机器人(标识, 机器人设置())
            self.更新机器人列表()
            for 项 in self.机器人列表框.get_children():
                if self.机器人列表框.item(项, "text") == 标识:
                    self.机器人列表框.selection_set(项)
                    self.机器人列表框.focus(项)
                    self.当前机器人ID = 标识
                    self.更新状态显示()
                    self.选择变化回调(标识)
                    break
        except Exception as 异常:
            messagebox.showerror("创建失败", str(异常), parent=self)

    def _删除选中机器人(self):
        """删除选中的机器人"""
        if not self.当前机器人ID:
            return

        if not messagebox.askyesno("确认删除", f"确定要永久删除 {self.当前机器人ID} 的配置吗？"):
            return

        删除的ID = self.当前机器人ID
        try:
            # 判断机器人是否在机器人池中
            if self.当前机器人ID in self.监控中心.机器人池:
                try:
                    # 停止机器人并移除
                    机器人实例 = self.监控中心.机器人池[self.当前机器人ID]
                    机器人实例.停止(等待=False)
                    del self.监控中心.机器人池[self.当前机器人ID]
                except Exception as e:
                    messagebox.showwarning("停止失败", f"停止机器人时发生错误：{e}")

            # 清除当前选择并刷新列表
            self.当前机器人ID = None
            self.更新机器人列表()
            self.更新状态显示()

            # 通知主控类删除配置
            self.选择变化回调(None, 删除=删除的ID)

        except Exception as e:
            messagebox.showerror("删除失败", f"删除过程中发生异常：{e}")
