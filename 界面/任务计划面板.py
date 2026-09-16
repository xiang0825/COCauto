"""MAA 风格的任务选择、排序与即时配置面板。"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from 数据库.任务数据库 import 默认任务计划顺序, 机器人设置


def 生成任务计划(设置) -> list[dict[str, str]]:
    """根据现有机器人配置生成任务状态，供 UI 和测试共同使用。"""
    if 设置 is None:
        return []

    def 布尔字段(字段名: str, 默认值: bool = False) -> bool:
        return bool(getattr(设置, 字段名, 默认值))

    英雄建筑 = getattr(设置, "欲升级的英雄或建筑", None) or []
    战宠 = getattr(设置, "欲升级的战宠", "") or ""
    研究 = getattr(设置, "欲升级的兵种或法术", "") or ""
    return [
        {"名称": "启动游戏与登录检查", "状态": "固定步骤", "说明": "启动客户端并确认进入可操作的主界面"},
        {"名称": "收集已有资源", "状态": "固定步骤", "说明": "读取并收集可领取资源"},
        {"名称": "主世界刷资源", "状态": "已启用" if 布尔字段("是否刷主世界") else "未启用", "说明": "按资源阈值搜索并进攻"},
        {"名称": "夜世界刷资源", "状态": "已启用" if 布尔字段("是否刷夜世界") else "未启用", "说明": "执行夜世界搜索、下兵和回营流程"},
        {"名称": "速刷资源", "状态": "已启用" if 布尔字段("是否快速刷资源") else "未启用", "说明": "下兵后快速结束战斗"},
        {"名称": "天鹰火炮成就", "状态": "已启用" if 布尔字段("是否刷天鹰火炮") else "未启用", "说明": "搜索目标并执行成就战斗流程"},
        {"名称": "刷墙", "状态": "已启用" if 布尔字段("开启刷墙") else "未启用", "说明": "达到金币或圣水阈值后执行刷墙"},
        {"名称": "建议建筑升级", "状态": "已启用" if 布尔字段("是否升级建议升级的建筑") else "未启用", "说明": "按游戏建议选择可升级建筑"},
        {"名称": "英雄或建筑升级", "状态": "已启用" if 英雄建筑 else "未启用", "说明": "目标：" + ("、".join(map(str, 英雄建筑)) if 英雄建筑 else "未设置目标")},
        {"名称": "战宠升级", "状态": "已启用" if 战宠 else "未启用", "说明": "目标：" + (战宠 or "未设置目标")},
        {"名称": "兵种或法术研究", "状态": "已启用" if 研究 else "未启用", "说明": "目标：" + (研究 or "未设置目标")},
        {"名称": "资源打满后的行为", "状态": getattr(设置, "资源打满后动作", "退出"), "说明": "资源达到目标后退出任务或保持待机"},
    ]


class 任务计划面板(ttk.Frame):
    """左侧勾选并排序任务，右侧修改参数，修改后自动保存。"""

    _任务定义 = (
        ("main_resource", "主世界刷资源", "是否刷主世界", "bool"),
        ("night_resource", "夜世界刷资源", "是否刷夜世界", "bool"),
        ("eagle", "天鹰火炮成就", "是否刷天鹰火炮", "bool"),
        ("wall", "刷墙", "开启刷墙", "bool"),
        ("building", "建议建筑升级", "是否升级建议升级的建筑", "bool"),
        ("hero", "英雄或建筑升级", "欲升级的英雄或建筑", "list"),
        ("pet", "战宠升级", "欲升级的战宠", "string"),
        ("research", "兵种或法术研究", "欲升级的兵种或法术", "string"),
    )
    _配置任务 = {
        "resource_policy": "资源打满后的行为",
        "combat_options": "进攻选项",
        "notification": "通知与状态上报",
    }

    def __init__(self, 父容器, 数据库, 获取机器人回调: Callable[[], Optional[str]], 操作日志回调: Optional[Callable[[str], None]] = None):
        super().__init__(父容器, padding=14)
        self.数据库 = 数据库
        self.获取机器人回调 = 获取机器人回调
        self.操作日志回调 = 操作日志回调
        self.当前机器人ID: Optional[str] = None
        self._设置: Optional[机器人设置] = None
        self._任务变量: dict[str, tk.BooleanVar] = {}
        self._编辑控件: dict[str, tk.Entry | ttk.Combobox] = {}
        self._当前任务 = ""
        self._载入中 = False
        self._自动保存计时器 = None
        self._创建界面()

    def _创建界面(self):
        标题栏 = ttk.Frame(self)
        标题栏.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(标题栏, text="任务计划", font=("Microsoft YaHei UI", 16, "bold")).pack(side=tk.LEFT)
        ttk.Label(标题栏, text="勾选、排序后立即生效；配置修改会自动保存。", foreground="#6b7280").pack(side=tk.LEFT, padx=(12, 0), pady=(4, 0))

        顶部 = ttk.Frame(self)
        顶部.pack(fill=tk.X, pady=(0, 8))
        self.当前配置 = tk.StringVar(value="未选择机器人")
        ttk.Label(顶部, textvariable=self.当前配置).pack(side=tk.LEFT)
        ttk.Label(顶部, text="服务器").pack(side=tk.RIGHT, padx=(12, 4))
        self.服务器变量 = tk.StringVar()
        self.服务器选择 = ttk.Combobox(顶部, textvariable=self.服务器变量, values=["国际服", "调试服务器"], state="readonly", width=12)
        self.服务器选择.pack(side=tk.RIGHT)
        self.服务器选择.bind("<<ComboboxSelected>>", lambda _event: self._安排自动保存())

        主体 = ttk.Frame(self)
        主体.pack(fill=tk.BOTH, expand=True)
        任务区 = ttk.LabelFrame(主体, text="任务计划（↑ ↓ 调整执行顺序）", padding=8)
        任务区.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        self._任务行容器 = ttk.Frame(任务区)
        self._任务行容器.pack(fill=tk.Y, expand=True)
        ttk.Label(任务区, text="启动、登录和资源收集为固定步骤。", foreground="#6b7280", wraplength=250).pack(anchor=tk.W, pady=(10, 0))

        参数区 = ttk.LabelFrame(主体, text="当前任务配置", padding=10)
        参数区.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._参数标题 = ttk.Label(参数区, text="请选择任务", font=("Microsoft YaHei UI", 12, "bold"))
        self._参数标题.pack(anchor=tk.W)
        self._参数说明 = ttk.Label(参数区, text="", foreground="#6b7280", wraplength=560)
        self._参数说明.pack(anchor=tk.W, pady=(3, 12))
        self._参数内容 = ttk.Frame(参数区)
        self._参数内容.pack(fill=tk.BOTH, expand=True, anchor=tk.N)

        底栏 = ttk.Frame(self)
        底栏.pack(fill=tk.X, pady=(10, 0))
        self.状态 = tk.StringVar(value="请选择机器人")
        ttk.Label(底栏, textvariable=self.状态).pack(side=tk.LEFT)
        ttk.Button(底栏, text="立即保存", command=self._保存内部).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(底栏, text="刷新观察", command=self.刷新).pack(side=tk.RIGHT)

    def 载入机器人(self, 机器人ID: Optional[str]):
        self.当前机器人ID = 机器人ID
        if not 机器人ID:
            所有配置 = self.数据库.查询所有机器人设置()
            if len(所有配置) == 1:
                # 列表空白、窗口重载或删除回调传入 None 时，单机器人直接恢复配置。
                self.刷新(next(iter(所有配置)))
                return
            self._设置 = None
            self.当前配置.set("未选择机器人")
            self.服务器变量.set("")
            self._重建任务列表()
            self._显示参数("")
            self.状态.set("请选择机器人")
            return
        self.刷新()

    def 刷新(self, _机器人ID: Optional[str] = None):
        机器人ID = _机器人ID or self.当前机器人ID or self.获取机器人回调()
        if not 机器人ID:
            # 只有一个机器人时自动恢复它，避免列表被误点空白后任务页失去配置。
            所有配置 = self.数据库.查询所有机器人设置()
            if len(所有配置) == 1:
                机器人ID = next(iter(所有配置))
        self.当前机器人ID = 机器人ID
        if not 机器人ID:
            self.载入机器人(None)
            return
        self._载入中 = True
        self._设置 = self.数据库.获取机器人设置(机器人ID)
        self.服务器变量.set(getattr(self._设置, "服务器", "国际服"))
        self.当前配置.set(f"机器人：{机器人ID}    ADB：{getattr(self._设置, 'ADB设备序列号', '') or '未配置'}")
        self._重建任务列表()
        self._显示参数(self._当前任务 or "主世界刷资源")
        self._载入中 = False
        self.状态.set("配置已载入；任务和参数修改会自动保存")

    def _任务状态(self, 字段: str, 类型: str) -> bool:
        if not self._设置:
            return False
        值 = getattr(self._设置, 字段, False)
        return bool(值 if 类型 != "list" else (值 or []))

    def _重建任务列表(self):
        for 控件 in self._任务行容器.winfo_children():
            控件.destroy()
        self._任务变量.clear()
        if not self._设置:
            return
        定义 = {键: (名称, 字段, 类型) for 键, 名称, 字段, 类型 in self._任务定义}
        顺序 = list(getattr(self._设置, "任务计划顺序", []) or 默认任务计划顺序)
        顺序 += [键 for 键, *_ in self._任务定义 if 键 not in 顺序]
        for 序号, 键 in enumerate(顺序, 1):
            if 键 not in 定义:
                continue
            名称, 字段, 类型 = 定义[键]
            行 = ttk.Frame(self._任务行容器)
            行.pack(fill=tk.X, pady=2)
            变量 = tk.BooleanVar(value=self._任务状态(字段, 类型))
            self._任务变量[名称] = 变量
            ttk.Checkbutton(行, text=f"{序号:02d} {名称}", variable=变量, command=self._任务开关改变).pack(side=tk.LEFT, fill=tk.X, expand=True)
            ttk.Button(行, text="↑", width=3, command=lambda 键=键: self._移动任务(键, -1)).pack(side=tk.RIGHT, padx=(2, 0))
            ttk.Button(行, text="↓", width=3, command=lambda 键=键: self._移动任务(键, 1)).pack(side=tk.RIGHT, padx=(2, 0))
            ttk.Button(行, text="配置", width=6, command=lambda 名称=名称: self._显示参数(名称)).pack(side=tk.RIGHT, padx=(2, 0))

        for 键, 名称 in self._配置任务.items():
            行 = ttk.Frame(self._任务行容器)
            行.pack(fill=tk.X, pady=2)
            ttk.Label(行, text=f"⚙ {名称}").pack(side=tk.LEFT, fill=tk.X, expand=True)
            ttk.Button(行, text="配置", width=6, command=lambda 键=键: self._显示参数(键)).pack(side=tk.RIGHT)
        固定 = ttk.Frame(self._任务行容器)
        固定.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(固定, text="✓ 启动游戏与登录检查", foreground="#2563eb").pack(anchor=tk.W, pady=2)
        ttk.Label(固定, text="✓ 收集已有资源", foreground="#2563eb").pack(anchor=tk.W, pady=2)

    def _任务开关改变(self):
        self.状态.set("任务开关已修改，正在自动保存…")
        self._安排自动保存()

    def _移动任务(self, 键: str, 方向: int):
        if not self._设置:
            return
        顺序 = list(getattr(self._设置, "任务计划顺序", []) or 默认任务计划顺序)
        if 键 not in 顺序:
            顺序.append(键)
        新索引 = 顺序.index(键) + 方向
        if not 0 <= 新索引 < len(顺序):
            return
        顺序.remove(键)
        顺序.insert(新索引, 键)
        self._设置.任务计划顺序 = 顺序
        self._保存内部()
        self._重建任务列表()
        self._显示参数(self._当前任务)

    def _清空参数内容(self):
        for 控件 in self._参数内容.winfo_children():
            控件.destroy()
        self._编辑控件.clear()

    def _增加输入项(self, 标签: str, 字段: str, 值, 宽度: int = 28):
        行 = ttk.Frame(self._参数内容)
        行.pack(fill=tk.X, pady=5)
        ttk.Label(行, text=标签, width=18).pack(side=tk.LEFT)
        输入 = ttk.Entry(行, width=宽度)
        输入.insert(0, str(值 if 值 is not None else ""))
        输入.bind("<KeyRelease>", lambda _event: self._安排自动保存())
        输入.bind("<FocusOut>", lambda _event: self._安排自动保存())
        输入.bind("<Return>", lambda _event: self._安排自动保存())
        输入.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._编辑控件[字段] = 输入
        return 输入

    def _增加下拉项(self, 标签: str, 字段: str, 值, 选项: list[str]):
        行 = ttk.Frame(self._参数内容)
        行.pack(fill=tk.X, pady=5)
        ttk.Label(行, text=标签, width=18).pack(side=tk.LEFT)
        输入 = ttk.Combobox(行, values=选项, state="readonly", width=26)
        输入.set(str(值 or ""))
        输入.bind("<<ComboboxSelected>>", lambda _event: self._安排自动保存())
        输入.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._编辑控件[字段] = 输入
        return 输入

    def _增加勾选项(self, 标签: str, 字段: str, 值: bool):
        变量 = tk.BooleanVar(value=bool(值))
        ttk.Checkbutton(
            self._参数内容,
            text=标签,
            variable=变量,
            command=self._安排自动保存,
        ).pack(anchor=tk.W, pady=5)
        self._编辑控件[字段] = 变量
        return 变量

    def _显示参数(self, 任务名称: str):
        if not self._设置:
            self._当前任务 = ""
            self._参数标题.configure(text="请选择机器人")
            self._参数说明.configure(text="")
            self._清空参数内容()
            return
        self._当前任务 = 任务名称
        self._清空参数内容()
        计划项 = next((项 for 项 in 生成任务计划(self._设置) if 项["名称"] == 任务名称), None)
        self._参数标题.configure(text=任务名称 or "任务参数")
        self._参数说明.configure(text=(计划项 or {}).get("说明", "修改后自动保存。"))
        if 任务名称 in ("主世界刷资源", "夜世界刷资源"):
            self._增加输入项("最低目标资源", "欲进攻的最小资源", getattr(self._设置, "欲进攻的最小资源", 0))
            self._增加下拉项("战利品优先级", "战利品优先级", getattr(self._设置, "战利品优先级", "均衡"), ["均衡", "金币", "圣水", "黑水"])
            self._增加输入项("资源边缘比例", "欲进攻资源建筑靠近地图边缘最小比例", getattr(self._设置, "欲进攻资源建筑靠近地图边缘最小比例", 0.5))
            ttk.Label(
                self._参数内容,
                text="资源易窃取评分固定为 0~10，必须严格大于 5 才进攻；5 分及以下自动跳过。",
                foreground="#2563eb",
                wraplength=560,
            ).pack(anchor=tk.W, pady=5)
            self._增加输入项("漏兵检测格数", "漏下兵种检测格数", getattr(self._设置, "漏下兵种检测格数", 1))
        elif 任务名称 == "刷墙":
            self._增加输入项("起始金币", "刷墙起始金币", getattr(self._设置, "刷墙起始金币", 0))
            self._增加输入项("起始圣水", "刷墙起始圣水", getattr(self._设置, "刷墙起始圣水", 0))
        elif 任务名称 == "英雄或建筑升级":
            目标 = getattr(self._设置, "欲升级的英雄或建筑", []) or []
            self._增加输入项("升级目标", "欲升级的英雄或建筑", "、".join(map(str, 目标)), 46)
            self._增加输入项("检查间隔（小时）", "建筑升级检查间隔", getattr(self._设置, "建筑升级检查间隔", 0))
            ttk.Label(self._参数内容, text="多个目标请用中文顿号、逗号或换行分隔。", foreground="#6b7280").pack(anchor=tk.W, pady=(0, 6))
        elif 任务名称 == "战宠升级":
            选项 = list(机器人设置.__dataclass_fields__["欲升级的战宠"].metadata.get("选项", []))
            self._增加下拉项("战宠", "欲升级的战宠", getattr(self._设置, "欲升级的战宠", ""), 选项)
            self._增加输入项("检查间隔（小时）", "战宠升级检查间隔", getattr(self._设置, "战宠升级检查间隔", 0))
        elif 任务名称 == "兵种或法术研究":
            选项 = list(机器人设置.__dataclass_fields__["欲升级的兵种或法术"].metadata.get("选项", []))
            self._增加下拉项("研究目标", "欲升级的兵种或法术", getattr(self._设置, "欲升级的兵种或法术", ""), 选项)
            self._增加输入项("检查间隔（小时）", "研究升级检查间隔", getattr(self._设置, "研究升级检查间隔", 1))
        elif 任务名称 == "资源打满后的行为" or 任务名称 == "resource_policy":
            self._增加下拉项("打满后动作", "资源打满后动作", getattr(self._设置, "资源打满后动作", "退出"), ["退出", "待机"])
            ttk.Label(self._参数内容, text="退出：完成任务并停止线程；待机：保持连接和界面观察，不再继续进攻。", wraplength=560).pack(anchor=tk.W, pady=5)
        elif 任务名称 == "进攻选项" or 任务名称 == "combat_options":
            self._增加勾选项("快速结束资源战斗（速刷）", "是否快速刷资源", getattr(self._设置, "是否快速刷资源", False))
            self._增加输入项("下兵间隔（毫秒）", "下兵间隔毫秒", getattr(self._设置, "下兵间隔毫秒", 25))
            self._增加勾选项("启用高速下兵", "是否启用高速下兵", getattr(self._设置, "是否启用高速下兵", True))
            self._增加下拉项("高速下兵方式", "高速下兵方式", getattr(self._设置, "高速下兵方式", "快速连点"), ["快速连点", "短按压"])
            self._增加勾选项("启用自动配兵玩法", "是否自动配兵", getattr(self._设置, "是否自动配兵", False))
            self._增加下拉项("自动配兵玩法", "自动配兵玩法", getattr(self._设置, "自动配兵玩法", "资源优先"), ["资源优先", "稳健三星", "快速速刷"])
            ttk.Label(self._参数内容, text="高速下兵仅用于数量不少于8个的普通兵种；英雄、攻城器械和药水仍逐点确认。", foreground="#2563eb", wraplength=560).pack(anchor=tk.W, pady=5)
            ttk.Label(self._参数内容, text="战斗结果统计：强制启用（胜负、星数、摧毁率和战利品分析）", foreground="#2563eb", wraplength=560).pack(anchor=tk.W, pady=5)
            self._增加勾选项("采集进攻界面图像", "是否采集进攻界面图像", getattr(self._设置, "是否采集进攻界面图像", False))
            ttk.Label(self._参数内容, text="这些开关会直接影响主世界和夜世界的进攻流程，修改后立即保存。", wraplength=560, foreground="#6b7280").pack(anchor=tk.W, pady=5)
        elif 任务名称 == "通知与状态上报" or 任务名称 == "notification":
            self._增加输入项("企业微信 Webhook", "企业微信webhook", getattr(self._设置, "企业微信webhook", ""), 46)
            self._增加输入项("状态上报间隔（分钟）", "状态上报间隔分钟", getattr(self._设置, "状态上报间隔分钟", 30))
        else:
            ttk.Label(self._参数内容, text="该任务没有额外参数；修改左侧勾选即可。", foreground="#6b7280").pack(anchor=tk.W, pady=5)

    def _从编辑器写回设置(self):
        if not self._设置:
            return
        for 字段, 控件 in self._编辑控件.items():
            值 = 控件.get()
            if 字段 in ("是否快速刷资源", "是否启用高速下兵", "是否自动配兵", "是否采集进攻界面图像"):
                setattr(self._设置, 字段, bool(值))
            elif 字段 == "欲升级的英雄或建筑":
                项目 = str(值).replace("\n", "、").replace(",", "、").split("、")
                setattr(self._设置, 字段, [项.strip() for 项 in 项目 if 项.strip()])
            elif 字段 in ("欲进攻的最小资源", "刷墙起始金币", "刷墙起始圣水", "漏下兵种检测格数", "状态上报间隔分钟", "下兵间隔毫秒"):
                setattr(self._设置, 字段, int(str(值).strip()))
            elif 字段 in ("欲进攻资源建筑靠近地图边缘最小比例", "建筑升级检查间隔", "战宠升级检查间隔", "研究升级检查间隔"):
                数值 = float(str(值).strip())
                if 字段 == "欲进攻资源建筑靠近地图边缘最小比例" and not 0 <= 数值 <= 1:
                    raise ValueError("资源边缘比例必须在 0 到 1 之间")
                if 字段 != "欲进攻资源建筑靠近地图边缘最小比例" and 数值 < 0:
                    raise ValueError("检查间隔不能小于 0")
                setattr(self._设置, 字段, 数值)
            else:
                setattr(self._设置, 字段, str(值).strip())

    def _安排自动保存(self):
        if self._载入中 or not self.当前机器人ID:
            return
        if self._自动保存计时器:
            self.after_cancel(self._自动保存计时器)
        self._自动保存计时器 = self.after(250, self._自动保存)

    def _自动保存(self):
        self._自动保存计时器 = None
        self._保存内部()

    def _保存内部(self):
        if not self.当前机器人ID or not self._设置:
            return False
        try:
            self._从编辑器写回设置()
            self._设置.服务器 = self.服务器变量.get() or "国际服"
            for _, 名称, 字段, 类型 in self._任务定义:
                变量值 = self._任务变量.get(名称, tk.BooleanVar(value=False)).get()
                if 类型 == "bool":
                    setattr(self._设置, 字段, bool(变量值))
                elif 类型 == "list" and not 变量值:
                    setattr(self._设置, 字段, [])
                elif 类型 == "string" and not 变量值:
                    setattr(self._设置, 字段, "")
            self._设置.__post_init__()
            self.数据库.保存机器人设置(self.当前机器人ID, self._设置)
            self.状态.set("已自动保存")
            if self.操作日志回调:
                self.操作日志回调(f"{self.当前机器人ID}：任务设置已自动保存")
            return True
        except (TypeError, ValueError) as 异常:
            self.状态.set(f"未保存：{异常}")
            return False
        except Exception as 异常:
            # 数据库锁定、权限或迁移异常不能让 Tk 回调静默失败。
            self.状态.set(f"保存失败：{异常}")
            if self.操作日志回调:
                try:
                    self.操作日志回调(f"{self.当前机器人ID}：任务设置保存失败：{异常}")
                except Exception:
                    pass
            return False
