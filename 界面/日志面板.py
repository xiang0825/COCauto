"""清晰的运行日志面板：重点筛选、去重和可读的事件时间线。"""
import queue
import re
import time
import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Callable, Optional


class 日志面板(ttk.Frame):
    """主界面右侧的运行观察区。底层历史不删除，只改变可视化方式。"""

    # 高频页面轮询、坐标尝试和截图缓存不适合默认占满观察区。
    _噪声片段 = (
        "点击护栏画面识别",
        "页面识别：页面=",
        "页面=战斗中，世界=未知，置信度=1.00",
        "截图缓存",
        "识别等待",
    )
    _重点片段 = (
        "启动",
        "停止",
        "暂停",
        "继续",
        "连接",
        "ADB",
        "任务计划",
        "按任务计划",
        "失败",
        "异常",
        "错误",
        "警告",
        "危险",
        "资源不足",
        "缺少资源",
        "刷墙",
        "城墙",
        "升级",
        "战斗",
        "进攻",
        "战利品",
        "胜利",
        "星",
        "摧毁",
        "回营",
        "下一场",
        "主世界",
        "夜世界",
        "宝石",
        "商店",
        "下兵点未被游戏接受",
        "线程即将死亡",
    )

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
        self._隐藏历史截止时间 = 0.0
        self._筛选模式 = None
        self._自动滚动 = None

        self._创建界面()
        self._定时刷新日志()

    def _创建界面(self):
        顶栏 = ttk.Frame(self)
        顶栏.pack(fill=tk.X, padx=6, pady=(4, 2))

        左侧 = ttk.Frame(顶栏)
        左侧.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(左侧, text="重点日志").pack(side=tk.LEFT)
        ttk.Label(
            左侧,
            text="  默认隐藏高频轮询，全部记录仍可切换查看",
            foreground="#718096",
        ).pack(side=tk.LEFT)

        右侧 = ttk.Frame(顶栏)
        右侧.pack(side=tk.RIGHT)
        ttk.Label(右侧, text="显示").pack(side=tk.LEFT, padx=(0, 4))
        self._筛选模式 = tk.StringVar(value="重点")
        模式选择 = ttk.Combobox(
            右侧,
            textvariable=self._筛选模式,
            values=("重点", "全部", "异常"),
            state="readonly",
            width=6,
        )
        模式选择.pack(side=tk.LEFT)
        模式选择.bind("<<ComboboxSelected>>", lambda _事件: self._渲染日志())
        self._自动滚动 = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            右侧,
            text="跟随",
            variable=self._自动滚动,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(
            右侧,
            text="清空显示",
            command=self._清空显示,
        ).pack(side=tk.LEFT, padx=(6, 0))

        信息栏 = ttk.Frame(self)
        信息栏.pack(fill=tk.X, padx=6, pady=(0, 3))
        self.状态标签 = ttk.Label(
            信息栏,
            text="等待日志…",
            foreground="#52627a",
        )
        self.状态标签.pack(side=tk.LEFT)
        ttk.Label(
            信息栏,
            text="仅清除当前显示，不删除数据库历史",
            foreground="#8a96a8",
        ).pack(side=tk.RIGHT)

        # 不自动换行，避免窗口缩放时重复计算长行；水平滚动可查看完整文本。
        self.日志文本框 = scrolledtext.ScrolledText(
            self,
            wrap=tk.NONE,
            font=("Consolas", 10),
            height=12,
            background="#fbfcfe",
            foreground="#263449",
            insertbackground="#263449",
            selectbackground="#cfe1ff",
            relief=tk.FLAT,
            borderwidth=0,
            padx=8,
            pady=7,
        )
        self.日志文本框.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.日志文本框.configure(state="disabled")

    def _定时刷新日志(self):
        """持续消费实时队列，不因当前选中机器人而丢弃消息。"""
        有变化 = False
        # 每次 UI tick 最多消费固定数量；即使生产者短时集中写日志，
        # 也不让 Tk 主线程一次性渲染几千条消息而假死。
        for _ in range(250):
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
            try:
                self.日志队列.task_done()
            except ValueError:
                pass
            有变化 = True
        # 长时间运行只保留近期实时消息，历史仍由数据库按需读取。
        self._实时日志 = self._实时日志[-3000:]

        if time.time() - self._上次数据库同步 >= 1.0:
            self._历史日志有变化 = False
            self._获取历史日志()
            self._上次数据库同步 = time.time()
            有变化 = 有变化 or self._历史日志有变化
        if 有变化:
            self._渲染日志()
        self.after(500, self._定时刷新日志)

    def _获取历史日志(self):
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
                    # 防止长时间运行时 GUI 历史缓存无限增长。
                    self.日志缓存内容[标志] = self.日志缓存内容[标志][-4000:]
            except Exception:
                continue

    @staticmethod
    def _推断级别(文本: str, 默认级别: str = "正常") -> str:
        if 默认级别 in {"警告", "错误"}:
            return 默认级别
        文本 = str(文本).strip()
        if 文本.startswith("[错误]") or any(
            关键词 in 文本 for 关键词 in ("异常", "错误", "失败", "危险", "线程即将死亡")
        ):
            return "错误"
        if 文本.startswith("[警告]") or any(
            关键词 in 文本 for 关键词 in ("警告", "资源不足", "未匹配", "被拒绝")
        ):
            return "警告"
        return "正常"

    @classmethod
    def _是否重点(cls, 文本: str, 级别: str) -> bool:
        文本 = cls._去掉实时前缀(文本)
        if any(片段 in 文本 for 片段 in cls._噪声片段):
            return False
        return cls._推断级别(文本, 级别) != "正常" or any(
            片段 in 文本 for 片段 in cls._重点片段
        )

    @staticmethod
    def _去掉实时前缀(文本: str) -> str:
        """历史日志没有时间前缀，实时队列有；去掉后才能合并同一条记录。"""
        return re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", str(文本))

    def 更新日志显示(self):
        """合并全部机器人历史日志、实时消息和界面操作日志。"""
        self._获取历史日志()
        self._渲染日志()

    def _收集日志(self):
        全部日志 = []
        for 标志, 日志列表 in self.日志缓存内容.items():
            全部日志.extend((项.记录时间, 标志, 项.日志内容, "正常") for 项 in 日志列表)
        全部日志.extend(self._实时日志)
        全部日志.extend(self._操作日志)
        全部日志.sort(key=lambda 项: 项[0])

        # 同一条运行日志同时存在于数据库历史和实时队列中。
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
            if float(时间戳) >= self._隐藏历史截止时间:
                去重日志.append(项)
        return 去重日志

    def _过滤日志(self, 全部日志):
        模式 = self._筛选模式.get() if self._筛选模式 else "重点"
        if 模式 == "全部":
            return 全部日志
        if 模式 == "异常":
            return [
                项 for 项 in 全部日志
                if self._推断级别(项[2], 项[3]) in {"警告", "错误"}
            ]
        return [项 for 项 in 全部日志 if self._是否重点(项[2], 项[3])]

    def _合并连续重复(self, 日志列表):
        """把连续的相同轮询消息折叠成一行，保留重复次数。"""
        结果 = []
        for 项 in 日志列表:
            时间戳, 机器人ID, 内容, 级别 = 项
            内容 = self._去掉实时前缀(内容)
            级别 = self._推断级别(内容, 级别)
            if 结果:
                上一条 = 结果[-1]
                相同 = (
                    上一条[1] == str(机器人ID)
                    and self._去掉实时前缀(上一条[2]) == 内容
                    and 上一条[3] == 级别
                    and float(时间戳) - float(上一条[0]) <= 60
                )
                if 相同:
                    结果[-1] = (
                        时间戳, 上一条[1], 上一条[2], 上一条[3], 上一条[4] + 1
                    )
                    continue
            结果.append((时间戳, str(机器人ID), 内容, 级别, 1))
        return 结果

    def _渲染日志(self):
        """只负责渲染缓存，不在窗口缩放时访问数据库。"""
        全部日志 = self._收集日志()
        过滤日志 = self._过滤日志(全部日志)
        合并日志 = self._合并连续重复(过滤日志)
        当前模式 = self._筛选模式.get() if self._筛选模式 else "重点"
        显示上限 = 180 if 当前模式 != "全部" else 260
        待显示 = 合并日志[-显示上限:]

        当前视图 = self.日志文本框.yview()
        self.日志文本框.configure(state="normal")
        self.日志文本框.delete("1.0", tk.END)
        self.日志文本框.tag_configure("正常", foreground="#263449", spacing3=3)
        self.日志文本框.tag_configure("警告", foreground="#a15c00", spacing3=3)
        self.日志文本框.tag_configure("错误", foreground="#b42318", spacing3=3)
        self.日志文本框.tag_configure("时间", foreground="#8492a6")
        self.日志文本框.tag_configure("机器人", foreground="#3b5b87")

        if not 待显示:
            提示 = {
                "异常": "当前没有异常记录。",
                "重点": "当前没有重点事件，任务运行后会在这里显示。",
                "全部": "当前没有运行日志。",
            }.get(当前模式, "当前没有运行日志。")
            self.日志文本框.insert(tk.END, 提示 + "\n", "正常")
        else:
            for 时间戳, 机器人ID, 内容, 级别, 重复次数 in 待显示:
                时间文本 = time.strftime("%H:%M:%S", time.localtime(时间戳))
                图标 = {"正常": "●", "警告": "▲", "错误": "✖"}.get(级别, "●")
                重复文本 = f"  ×{重复次数}" if 重复次数 > 1 else ""
                self.日志文本框.insert(tk.END, f"{时间文本}  ", "时间")
                self.日志文本框.insert(tk.END, f"{图标} ", 级别)
                self.日志文本框.insert(tk.END, f"{机器人ID}  ", "机器人")
                self.日志文本框.insert(
                    tk.END,
                    f"{内容}{重复文本}\n",
                    级别,
                )

        异常数 = sum(
            1 for 项 in 全部日志
            if self._推断级别(项[2], 项[3]) in {"警告", "错误"}
        )
        self.状态标签.configure(
            text=f"{当前模式} · 显示 {len(待显示)}/{len(过滤日志)} 条 · 异常 {异常数} · 总计 {len(全部日志)}"
        )
        self.日志文本框.configure(state="disabled")
        if self._自动滚动 is not None and self._自动滚动.get():
            self.日志文本框.see(tk.END)
        elif 当前视图:
            self.日志文本框.yview_moveto(当前视图[0])

    def _清空显示(self):
        """只隐藏当前之前的记录，数据库和任务引擎不受影响。"""
        self._隐藏历史截止时间 = time.time()
        self._实时日志 = [
            项 for 项 in self._实时日志
            if float(项[0]) >= self._隐藏历史截止时间
        ]
        self._操作日志.clear()
        self._渲染日志()

    def 记录操作日志(self, 内容: str):
        """把 UI 操作作为系统日志保留在统一观察区。"""
        self._操作日志.append((time.time(), "系统", f"[操作] {内容}", "正常"))
        self._操作日志 = self._操作日志[-200:]
        self._渲染日志()

    def 通知机器人切换(self):
        """切换机器人不改变日志过滤范围，只触发刷新。"""
        self._渲染日志()
