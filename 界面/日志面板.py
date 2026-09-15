"""运行观察面板：集中显示所有机器人的历史日志和实时消息。"""
import queue
import re
import time
import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Callable, Optional


class 日志面板(ttk.Frame):
    """主界面底部的运行观察区。"""

    def __init__(
        self,
        父容器,
        日志队列: queue.Queue,
        获取当前机器人回调: Callable,
        获取所有机器人回调: Optional[Callable] = None,
    ):
        super().__init__(父容器)
        self.日志队列 = 日志队列
        self.获取当前机器人 = 获取当前机器人回调
        self.获取所有机器人 = 获取所有机器人回调 or (lambda: {})
        self.日志缓存时间戳 = {}
        self.日志缓存内容 = {}
        self._实时日志 = []
        self._操作日志 = []
        self._历史日志有变化 = False
        self._上次数据库同步 = 0.0

        self._创建界面()
        self._定时刷新日志()

    def _创建界面(self):
        顶栏 = ttk.Frame(self)
        顶栏.pack(fill=tk.X, padx=5, pady=(4, 0))
        ttk.Label(顶栏, text="运行观察（全部机器人）").pack(side=tk.LEFT)
        self.状态标签 = ttk.Label(顶栏, text="等待日志…", foreground="#6b7280")
        self.状态标签.pack(side=tk.RIGHT)

        # 日志不做自动换行，窗口缩放时 Tk 无需重新计算每一行的折行位置。
        self.日志文本框 = scrolledtext.ScrolledText(
            self, wrap=tk.NONE, font=("Consolas", 10), height=9
        )
        self.日志文本框.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.日志文本框.configure(state="disabled")

    def _定时刷新日志(self):
        """持续消费实时队列，不因当前选中机器人而丢弃消息。"""
        有变化 = False
        while True:
            try:
                日志消息 = self.日志队列.get_nowait()
            except queue.Empty:
                break
            当前时间 = time.time()
            if isinstance(日志消息, dict):
                机器人ID = str(日志消息.get("机器人ID") or "系统")
                内容 = str(日志消息.get("内容", ""))
                级别 = 日志消息.get("级别", "正常")
                try:
                    记录时间 = float(日志消息.get("记录时间", 当前时间))
                except (TypeError, ValueError):
                    记录时间 = 当前时间
                self._实时日志.append((记录时间, 机器人ID, 内容, 级别))
            else:
                self._实时日志.append((当前时间, "系统", str(日志消息), "正常"))
            有变化 = True
        if time.time() - self._上次数据库同步 >= 1.0:
            self._历史日志有变化 = False
            self._获取历史日志()
            self._上次数据库同步 = time.time()
            有变化 = 有变化 or self._历史日志有变化
        if 有变化:
            self._渲染日志()
        self.after(500, self._定时刷新日志)

    def _获取历史日志(self):
        历史 = []
        try:
            机器人池 = self.获取所有机器人() or {}
        except Exception:
            机器人池 = {}
        for 机器人ID, 机器人 in 机器人池.items():
            try:
                标志 = str(机器人ID)
                上次时间 = self.日志缓存时间戳.get(标志, 0)
                日志列表 = 机器人.数据库.查询日志历史(
                    标志, 起始时间=上次时间 + 0.00001
                )
                if 日志列表:
                    self._历史日志有变化 = True
                    self.日志缓存时间戳[标志] = max(
                        项.记录时间 for 项 in 日志列表
                    )
                    self.日志缓存内容.setdefault(标志, []).extend(日志列表)
                for 项 in self.日志缓存内容.get(标志, []):
                    历史.append((项.记录时间, 标志, 项.日志内容, "正常"))
            except Exception:
                continue
        return 历史

    @staticmethod
    def _推断级别(文本: str, 默认级别: str = "正常") -> str:
        if 默认级别 in {"警告", "错误"}:
            return 默认级别
        文本 = str(文本).strip()
        if 文本.startswith("[错误]"):
            return "错误"
        if 文本.startswith("[警告]"):
            return "警告"
        return "正常"

    @staticmethod
    def _去掉实时前缀(文本: str) -> str:
        """历史日志没有时间前缀，实时队列有；去掉后才能合并同一条记录。"""
        return re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", str(文本))

    def 更新日志显示(self):
        """合并全部机器人历史日志、实时消息和界面操作日志。"""
        self._获取历史日志()
        self._渲染日志()

    def _渲染日志(self):
        """只负责渲染缓存，避免窗口缩放时反复访问数据库和重绘文本框。"""
        全部日志 = []
        for 标志, 日志列表 in self.日志缓存内容.items():
            全部日志.extend((项.记录时间, 标志, 项.日志内容, "正常") for 项 in 日志列表)
        全部日志.extend(self._实时日志)
        全部日志.extend(self._操作日志)
        全部日志.sort(key=lambda 项: 项[0])

        # 同一条运行日志同时存在于数据库历史和实时队列中；使用数据库
        # 返回的记录时间做关联，并去掉实时消息的显示前缀，避免重复渲染。
        去重日志 = []
        已显示 = set()
        for 项 in 全部日志:
            时间戳, 机器人ID, 内容, 级别 = 项
            关键字 = (
                str(机器人ID),
                round(float(时间戳), 6),
                self._去掉实时前缀(内容),
            )
            if 关键字 in 已显示:
                continue
            已显示.add(关键字)
            去重日志.append(项)
        全部日志 = 去重日志

        当前视图 = self.日志文本框.yview()
        self.日志文本框.configure(state="normal")
        self.日志文本框.delete("1.0", tk.END)
        self.日志文本框.tag_configure("正常", foreground="#1f2937")
        self.日志文本框.tag_configure("警告", foreground="#b45309")
        self.日志文本框.tag_configure("错误", foreground="#b91c1c")

        if not 全部日志:
            self.日志文本框.insert(
                tk.END,
                "尚无运行日志。创建机器人并连接模拟器后，所有机器人状态会显示在这里。\n",
                "正常",
            )
            self.状态标签.configure(text="等待日志…")
        else:
            for 时间戳, 机器人ID, 内容, 级别 in 全部日志[-500:]:
                时间文本 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(时间戳))
                self.日志文本框.insert(
                    tk.END,
                    f"{时间文本}  [{机器人ID}] {内容}\n",
                    self._推断级别(内容, 级别),
                )
            self.状态标签.configure(text=f"已显示 {min(len(全部日志), 500)} 条")

        self.日志文本框.configure(state="disabled")
        if not 当前视图 or 当前视图[1] > 0.95:
            self.日志文本框.see(tk.END)
        else:
            self.日志文本框.yview_moveto(当前视图[0])

    def 记录操作日志(self, 内容: str):
        """把 UI 操作也作为系统日志保留在统一观察区。"""
        self._操作日志.append((time.time(), "系统", f"[操作] {内容}", "正常"))
        self._操作日志 = self._操作日志[-200:]
        self.更新日志显示()

    def 通知机器人切换(self):
        """兼容旧调用：切换机器人不改变日志过滤范围，只触发刷新。"""
        self.更新日志显示()
