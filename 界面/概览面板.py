"""首页只回答三个问题：连接了吗、选了什么、最近发生了什么。"""
import time
import tkinter as tk
from tkinter import ttk

from 数据库.任务数据库 import (
    任务计划定义列表,
    任务计划是否启用,
    规范化任务计划顺序,
)


class 概览面板(ttk.Frame):
    def __init__(self, 父容器, 监控中心, 数据库, 获取当前机器人回调, 打开页面=None):
        super().__init__(父容器)
        self.监控中心 = 监控中心
        self.数据库 = 数据库
        self.获取当前机器人回调 = 获取当前机器人回调
        self.打开页面 = 打开页面 or (lambda _名称: None)
        self._上次机器人ID = None
        self._下次日志读取时间 = 0.0
        self._下次配置读取时间 = 0.0
        self._设置缓存 = None
        self._上次任务表快照 = None

        self.状态 = tk.StringVar(value="未选择机器人")
        self.连接 = tk.StringVar(value="未选择机器人")
        self.停止原因 = tk.StringVar(value="—")
        self.最近日志 = tk.StringVar(value="暂无运行日志")
        self.任务摘要 = tk.StringVar(value="尚未选择任务")
        self._创建界面()
        self.刷新()
        self._定时刷新()

    def _创建界面(self):
        引导 = tk.Frame(self, bg="#fff0e1", padx=20, pady=16)
        引导.pack(fill=tk.X, pady=(0, 16))
        文案 = tk.Frame(引导, bg="#fff0e1")
        文案.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(文案, text="准备开始", bg="#fff0e1", fg="#8f4c2d",
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor=tk.W)
        tk.Label(文案, text="确认模拟器 → 勾选任务 → 点击顶部启动。",
                 bg="#fff0e1", fg="#735f51",
                 font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(4, 0))
        tk.Button(引导, text="检查连接", command=lambda: self.打开页面("模拟器连接"),
                  bg="#ffffff", fg="#8f4c2d", relief=tk.FLAT, bd=0,
                  padx=14, pady=7, cursor="hand2").pack(side=tk.RIGHT)
        tk.Button(引导, text="编辑任务", command=lambda: self.打开页面("任务计划"),
                  bg="#ffffff", fg="#8f4c2d", relief=tk.FLAT, bd=0,
                  padx=14, pady=7, cursor="hand2").pack(side=tk.RIGHT, padx=(0, 8))

        中段 = ttk.Frame(self)
        中段.pack(fill=tk.X)
        中段.columnconfigure(0, weight=1, uniform="cards")
        中段.columnconfigure(1, weight=1, uniform="cards")
        状态卡 = ttk.Frame(中段, style="Card.TFrame", padding=20)
        状态卡.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(状态卡, text="运行状态", style="Card.TLabel",
                  font=("Microsoft YaHei UI", 12, "bold")).pack(anchor=tk.W, pady=(0, 12))
        self._状态行(状态卡, "机器人", self.状态)
        self._状态行(状态卡, "模拟器", self.连接)
        self._状态行(状态卡, "停止原因", self.停止原因)

        任务卡 = ttk.Frame(中段, style="Card.TFrame", padding=20)
        任务卡.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ttk.Label(任务卡, text="已选任务", style="Card.TLabel",
                  font=("Microsoft YaHei UI", 12, "bold")).pack(anchor=tk.W)
        ttk.Label(任务卡, textvariable=self.任务摘要,
                  style="CardMuted.TLabel").pack(anchor=tk.W, pady=(3, 10))
        self.任务容器 = ttk.Frame(任务卡, style="CardBody.TFrame")
        self.任务容器.pack(fill=tk.X)

        事件卡 = ttk.Frame(self, style="Card.TFrame", padding=20)
        事件卡.pack(fill=tk.X, pady=(16, 0))
        ttk.Label(事件卡, text="最近事件", style="Card.TLabel",
                  font=("Microsoft YaHei UI", 12, "bold")).pack(anchor=tk.W)
        ttk.Label(事件卡, textvariable=self.最近日志, style="CardMuted.TLabel",
                  wraplength=1000).pack(anchor=tk.W, pady=(9, 0))

    @staticmethod
    def _状态行(父容器, 名称, 变量):
        行 = ttk.Frame(父容器, style="CardBody.TFrame")
        行.pack(fill=tk.X, pady=5)
        ttk.Label(行, text=名称, style="CardMuted.TLabel", width=9).pack(side=tk.LEFT)
        ttk.Label(行, textvariable=变量, style="Card.TLabel",
                  wraplength=320).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _定时刷新(self):
        try:
            self._刷新状态()
        except tk.TclError:
            return
        except Exception:
            pass
        self.after(1500, self._定时刷新)

    def _刷新状态(self, 强制读取配置=False):
        机器人 = self.获取当前机器人回调()
        if 机器人 is None:
            self.状态.set("未选择机器人")
            self.连接.set("未选择机器人")
            self.停止原因.set("—")
            self.最近日志.set("暂无运行日志")
            self._刷新任务表(None)
            self._设置缓存 = None
            self._上次机器人ID = None
            return

        self.状态.set(str(getattr(机器人, "当前状态", "未知")))
        self.停止原因.set(str(getattr(机器人, "停止原因", "") or "—"))
        机器人ID = getattr(机器人, "机器人标志", None)
        if (强制读取配置 or 机器人ID != self._上次机器人ID
                or time.monotonic() >= self._下次配置读取时间):
            self._设置缓存 = 机器人.设置
            self._下次配置读取时间 = time.monotonic() + 3
        设置 = self._设置缓存
        序列号 = (getattr(设置, "ADB设备序列号", "") or "").strip()
        已确认 = bool(getattr(设置, "ADB已确认模拟器", False))
        if 已确认 and 序列号:
            self.连接.set(f"已确认 · {序列号}")
        elif 序列号:
            self.连接.set(f"未确认 · {序列号}")
        else:
            self.连接.set("未配置")

        if 机器人ID != self._上次机器人ID or time.monotonic() >= self._下次日志读取时间:
            self._上次机器人ID = 机器人ID
            self._读取最近日志(机器人ID)
        self._刷新任务表(设置)

    def _读取最近日志(self, 机器人ID):
        self._下次日志读取时间 = time.monotonic() + 4
        try:
            日志 = self.数据库.读取最后日志(机器人ID)
        except Exception:
            日志 = None
        self.最近日志.set((日志.日志内容 if 日志 else "暂无运行日志")[:180])

    def _刷新任务表(self, 设置):
        if 设置 is None:
            快照 = ()
        else:
            顺序 = 规范化任务计划顺序(getattr(设置, "任务计划顺序", None))
            定义 = {项.键: 项 for 项 in 任务计划定义列表}
            快照 = tuple(
                (定义[键].名称, 定义[键].说明)
                for 键 in 顺序
                if 键 in 定义 and 任务计划是否启用(设置, 键)
            )
        if 快照 == self._上次任务表快照:
            return
        self._上次任务表快照 = 快照
        self.任务摘要.set(f"共 {len(快照)} 项，按设置顺序执行" if 快照 else "尚未选择任务")
        for 控件 in self.任务容器.winfo_children():
            控件.destroy()
        if not 快照:
            ttk.Label(self.任务容器, text="前往「任务计划」勾选要执行的任务。",
                      style="CardMuted.TLabel").pack(anchor=tk.W, pady=8)
            return
        for 序号, (名称, _说明) in enumerate(快照[:5], 1):
            行 = ttk.Frame(self.任务容器, style="CardBody.TFrame")
            行.pack(fill=tk.X, pady=4)
            ttk.Label(行, text=f"{序号:02d}", style="CardMuted.TLabel",
                      width=4).pack(side=tk.LEFT)
            ttk.Label(行, text=名称, style="Card.TLabel").pack(side=tk.LEFT)
        if len(快照) > 5:
            ttk.Label(self.任务容器, text=f"另外 {len(快照) - 5} 项请到任务计划查看",
                      style="CardMuted.TLabel").pack(anchor=tk.W, pady=(6, 0))

    def 刷新(self):
        self._刷新状态(强制读取配置=True)
