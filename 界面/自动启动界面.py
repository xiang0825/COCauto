"""
自动启动界面 - 用户友好的自动启动设置界面
用户可以在这里轻松设置机器人的自动启动时间，无需关心计划任务和bat文件
"""
import tkinter as tk
from tkinter import ttk, messagebox
import sys
from pathlib import Path

# 添加项目根目录到路径
项目根目录 = Path(__file__).parent.parent
sys.path.insert(0, str(项目根目录))

from 模块.自动启动管理器 import 自动启动管理器


class 自动启动界面(ttk.Frame):
    """自动启动设置界面"""

    def __init__(self, 父容器, 监控中心=None):
        """
        初始化界面
        :param 父容器: 父容器控件
        :param 监控中心: 机器人监控中心实例，用于获取机器人列表
        """
        super().__init__(父容器)
        self.监控中心 = 监控中心
        self.管理器 = 自动启动管理器()
        self.机器人配置项 = {}  # 存储每个机器人的UI控件

        self._创建界面()
        self._加载现有配置()

    def _创建界面(self):
        """创建界面布局"""
        # 主容器
        主容器 = ttk.Frame(self)
        主容器.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 标题和说明
        标题框架 = ttk.Frame(主容器)
        标题框架.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(
            标题框架,
            text="自动启动设置",
            font=("微软雅黑", 14, "bold")
        ).pack(anchor=tk.W)

        ttk.Label(
            标题框架,
            text="在这里设置机器人的每日自动启动时间，系统会自动创建Windows计划任务",
            font=("微软雅黑", 9),
            foreground="#666"
        ).pack(anchor=tk.W, pady=(5, 0))

        # 分隔线
        ttk.Separator(主容器, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # 机器人列表区域（带滚动条）
        列表容器 = ttk.Frame(主容器)
        列表容器.pack(fill=tk.BOTH, expand=True)

        # 创建Canvas和滚动条
        self.画布 = tk.Canvas(列表容器, highlightthickness=0)
        滚动条 = ttk.Scrollbar(列表容器, orient=tk.VERTICAL, command=self.画布.yview)
        self.机器人列表框架 = ttk.Frame(self.画布)

        self.机器人列表框架.bind(
            "<Configure>",
            lambda e: self.画布.configure(scrollregion=self.画布.bbox("all"))
        )

        self.画布.create_window((0, 0), window=self.机器人列表框架, anchor=tk.NW)
        self.画布.configure(yscrollcommand=滚动条.set)

        self.画布.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        滚动条.pack(side=tk.RIGHT, fill=tk.Y)

        # 鼠标滚轮支持
        self.画布.bind_all("<MouseWheel>", self._鼠标滚轮)

        # 底部按钮区
        按钮框架 = ttk.Frame(主容器)
        按钮框架.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(
            按钮框架,
            text="刷新机器人列表",
            command=self._刷新机器人列表
        ).pack(side=tk.LEFT, padx=5)

        ttk.Button(
            按钮框架,
            text="保存所有设置",
            command=self._保存所有设置
        ).pack(side=tk.LEFT, padx=5)

        ttk.Button(
            按钮框架,
            text="清理无效配置",
            command=self._清理无效配置
        ).pack(side=tk.LEFT, padx=5)

    def _鼠标滚轮(self, event):
        """处理鼠标滚轮事件"""
        self.画布.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _创建机器人配置项(self, 机器人标识: str, 行号: int):
        """
        创建单个机器人的配置项
        :param 机器人标识: 机器人标识
        :param 行号: 在列表中的行号
        """
        # 外框
        外框 = ttk.LabelFrame(self.机器人列表框架, text=f"机器人: {机器人标识}", padding=10)
        外框.grid(row=行号, column=0, sticky=tk.EW, padx=5, pady=5)

        # 配置网格权重
        外框.columnconfigure(1, weight=1)

        # 启用开关
        启用变量 = tk.BooleanVar(value=False)
        启用开关 = ttk.Checkbutton(
            外框,
            text="启用自动启动",
            variable=启用变量,
            command=lambda: self._切换启用状态(机器人标识, 启用变量.get())
        )
        启用开关.grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 10))

        # 时间设置
        ttk.Label(外框, text="启动时间:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5))

        时间框架 = ttk.Frame(外框)
        时间框架.grid(row=1, column=1, sticky=tk.W)

        # 小时选择
        小时变量 = tk.StringVar(value="09")
        小时选择器 = ttk.Spinbox(
            时间框架,
            from_=0,
            to=23,
            width=5,
            textvariable=小时变量,
            format="%02.0f"
        )
        小时选择器.pack(side=tk.LEFT)

        ttk.Label(时间框架, text=":").pack(side=tk.LEFT, padx=2)

        # 分钟选择
        分钟变量 = tk.StringVar(value="00")
        分钟选择器 = ttk.Spinbox(
            时间框架,
            from_=0,
            to=59,
            width=5,
            textvariable=分钟变量,
            format="%02.0f"
        )
        分钟选择器.pack(side=tk.LEFT)

        # 虚拟环境选项
        虚拟环境变量 = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            外框,
            text="使用虚拟环境",
            variable=虚拟环境变量
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))

        # 状态显示
        状态标签 = ttk.Label(外框, text="未配置", foreground="#999")
        状态标签.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(10, 0))

        # 操作按钮
        按钮框架 = ttk.Frame(外框)
        按钮框架.grid(row=1, column=2, sticky=tk.E, padx=(10, 0))

        应用按钮 = ttk.Button(
            按钮框架,
            text="应用",
            command=lambda: self._应用单个配置(机器人标识),
            width=8
        )
        应用按钮.pack(side=tk.LEFT, padx=2)

        删除按钮 = ttk.Button(
            按钮框架,
            text="删除",
            command=lambda: self._删除单个配置(机器人标识),
            width=8
        )
        删除按钮.pack(side=tk.LEFT, padx=2)

        # 保存控件引用
        self.机器人配置项[机器人标识] = {
            "外框": 外框,
            "启用变量": 启用变量,
            "小时变量": 小时变量,
            "分钟变量": 分钟变量,
            "虚拟环境变量": 虚拟环境变量,
            "状态标签": 状态标签,
            "启用开关": 启用开关,
            "应用按钮": 应用按钮,
            "删除按钮": 删除按钮
        }

    def _切换启用状态(self, 机器人标识: str, 启用: bool):
        """
        切换机器人的启用状态
        :param 机器人标识: 机器人标识
        :param 启用: 是否启用
        """
        if 机器人标识 not in self.机器人配置项:
            return

        配置项 = self.机器人配置项[机器人标识]

        # 根据启用状态更新UI
        if 启用:
            配置项["状态标签"].config(text="已启用（未保存）", foreground="#ff9800")
        else:
            配置项["状态标签"].config(text="已禁用（未保存）", foreground="#999")

    def _应用单个配置(self, 机器人标识: str):
        """
        应用单个机器人的配置
        :param 机器人标识: 机器人标识
        """
        if 机器人标识 not in self.机器人配置项:
            return

        配置项 = self.机器人配置项[机器人标识]
        启用 = 配置项["启用变量"].get()

        try:
            if 启用:
                # 设置自动启动
                小时 = 配置项["小时变量"].get()
                分钟 = 配置项["分钟变量"].get()
                启动时间 = f"{小时}:{分钟}"
                使用虚拟环境 = 配置项["虚拟环境变量"].get()

                成功 = self.管理器.设置机器人自动启动(机器人标识, 启动时间, 使用虚拟环境)

                if 成功:
                    配置项["状态标签"].config(
                        text=f"✓ 已设置自动启动 ({启动时间})",
                        foreground="#4caf50"
                    )
                    messagebox.showinfo("成功", f"已为 {机器人标识} 设置自动启动")
                else:
                    配置项["状态标签"].config(text="✗ 设置失败", foreground="#f44336")
                    messagebox.showerror("失败", f"设置 {机器人标识} 自动启动失败")
            else:
                # 取消自动启动
                成功 = self.管理器.取消机器人自动启动(机器人标识)

                if 成功:
                    配置项["状态标签"].config(text="已取消自动启动", foreground="#999")
                    messagebox.showinfo("成功", f"已取消 {机器人标识} 的自动启动")
                else:
                    配置项["状态标签"].config(text="✗ 取消失败", foreground="#f44336")
                    messagebox.showerror("失败", f"取消 {机器人标识} 自动启动失败")

        except Exception as e:
            配置项["状态标签"].config(text=f"✗ 错误: {str(e)}", foreground="#f44336")
            messagebox.showerror("错误", f"操作失败: {str(e)}")

    def _删除单个配置(self, 机器人标识: str):
        """
        删除单个机器人的自动启动配置
        :param 机器人标识: 机器人标识
        """
        if not messagebox.askyesno("确认", f"确定要删除 {机器人标识} 的自动启动配置吗？"):
            return

        try:
            成功 = self.管理器.取消机器人自动启动(机器人标识)

            if 成功:
                if 机器人标识 in self.机器人配置项:
                    配置项 = self.机器人配置项[机器人标识]
                    配置项["启用变量"].set(False)
                    配置项["状态标签"].config(text="已删除配置", foreground="#999")
                messagebox.showinfo("成功", f"已删除 {机器人标识} 的自动启动配置")
            else:
                messagebox.showerror("失败", "删除配置失败")

        except Exception as e:
            messagebox.showerror("错误", f"删除失败: {str(e)}")

    def _保存所有设置(self):
        """保存所有机器人的设置"""
        成功数量 = 0
        失败数量 = 0

        for 机器人标识, 配置项 in self.机器人配置项.items():
            启用 = 配置项["启用变量"].get()

            try:
                if 启用:
                    小时 = 配置项["小时变量"].get()
                    分钟 = 配置项["分钟变量"].get()
                    启动时间 = f"{小时}:{分钟}"
                    使用虚拟环境 = 配置项["虚拟环境变量"].get()

                    if self.管理器.设置机器人自动启动(机器人标识, 启动时间, 使用虚拟环境):
                        配置项["状态标签"].config(
                            text=f"✓ 已设置自动启动 ({启动时间})",
                            foreground="#4caf50"
                        )
                        成功数量 += 1
                    else:
                        配置项["状态标签"].config(text="✗ 设置失败", foreground="#f44336")
                        失败数量 += 1
                else:
                    if self.管理器.取消机器人自动启动(机器人标识):
                        配置项["状态标签"].config(text="已取消自动启动", foreground="#999")
                        成功数量 += 1
                    else:
                        失败数量 += 1

            except Exception as e:
                配置项["状态标签"].config(text=f"✗ 错误", foreground="#f44336")
                失败数量 += 1

        messagebox.showinfo(
            "保存完成",
            f"成功: {成功数量} 个\n失败: {失败数量} 个"
        )

    def _刷新机器人列表(self):
        """刷新机器人列表"""
        # 清空现有配置项
        for 配置项 in self.机器人配置项.values():
            配置项["外框"].destroy()
        self.机器人配置项.clear()

        # 重新加载
        self._加载现有配置()

    def _加载现有配置(self):
        """加载现有的机器人和配置"""
        # 获取所有机器人
        机器人列表 = []

        if self.监控中心:
            # 从监控中心获取机器人列表
            机器人列表 = list(self.监控中心.机器人池.keys())
        else:
            # 从配置文件获取
            所有配置 = self.管理器.获取所有自动启动配置()
            机器人列表 = list(所有配置.keys())

        if not 机器人列表:
            # 显示提示信息
            提示标签 = ttk.Label(
                self.机器人列表框架,
                text="暂无机器人，请先在配置管理中创建机器人",
                font=("微软雅黑", 10),
                foreground="#999"
            )
            提示标签.grid(row=0, column=0, pady=50)
            return

        # 获取现有配置
        所有配置 = self.管理器.获取所有自动启动配置()

        # 为每个机器人创建配置项
        for 行号, 机器人标识 in enumerate(机器人列表):
            self._创建机器人配置项(机器人标识, 行号)

            # 如果有现有配置，加载它
            if 机器人标识 in 所有配置:
                配置 = 所有配置[机器人标识]
                配置项 = self.机器人配置项[机器人标识]

                # 设置启用状态
                配置项["启用变量"].set(配置.get("启用", False))

                # 设置时间
                时间 = 配置.get("时间", "09:00")
                小时, 分钟 = 时间.split(":")
                配置项["小时变量"].set(小时)
                配置项["分钟变量"].set(分钟)

                # 设置虚拟环境
                配置项["虚拟环境变量"].set(配置.get("使用虚拟环境", True))

                # 更新状态显示
                if 配置.get("启用", False):
                    # 检查计划任务是否真的存在
                    任务名称 = 配置.get("任务名称")
                    if 任务名称 and self.管理器.检查计划任务是否存在(任务名称):
                        配置项["状态标签"].config(
                            text=f"✓ 已设置自动启动 ({时间})",
                            foreground="#4caf50"
                        )
                    else:
                        配置项["状态标签"].config(
                            text="⚠ 配置存在但计划任务丢失",
                            foreground="#ff9800"
                        )
                else:
                    配置项["状态标签"].config(text="未启用", foreground="#999")

    def _清理无效配置(self):
        """清理无效的配置"""
        if not messagebox.askyesno("确认", "确定要清理所有无效的配置吗？"):
            return

        try:
            self.管理器.清理无效配置()
            messagebox.showinfo("成功", "已清理无效配置")
            self._刷新机器人列表()
        except Exception as e:
            messagebox.showerror("错误", f"清理失败: {str(e)}")


def 测试界面():
    """测试界面"""
    root = tk.Tk()
    root.title("自动启动设置测试")
    root.geometry("800x600")

    界面 = 自动启动界面(root)
    界面.pack(fill=tk.BOTH, expand=True)

    root.mainloop()


if __name__ == "__main__":
    测试界面()
