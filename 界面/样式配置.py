"""
样式配置模块 - 配置全局 ttk 样式
"""
from tkinter import ttk


def 配置现代化样式():
    """配置现代化控件样式"""
    style = ttk.Style()

    # 统一的浅色工作台配色：顶部为蓝色状态条，内容区保持高对比度。
    style.configure("Header.TFrame", background="#eef4ff")
    style.configure("Title.TLabel", background="#eef4ff", foreground="#173b6c",
                    font=("Segoe UI", 20, "bold"))
    style.configure("Subtitle.TLabel", background="#eef4ff", foreground="#607089",
                    font=("Segoe UI", 9))
    style.configure("Status.TLabel", background="#eef4ff", foreground="#16724a",
                    font=("Segoe UI", 10, "bold"))

    # 配置圆角按钮
    style.configure("TButton", padding=(8, 6), relief="flat",
                    font=("Segoe UI", 10))
    style.map("TButton",
              relief=[("active", "sunken"), ("!active", "flat")],
              background=[("active", "#e5e5e5"), ("!active", "white")]
              )

    # 状态按钮颜色
    style.configure("success.TButton", foreground="white", background="#2ea44f")
    style.map("success.TButton",
              background=[("active", "#22863a"), ("!active", "#2ea44f")])
    style.configure("danger.TButton", foreground="white", background="#cb2431")
    style.map("danger.TButton",
              background=[("active", "#9f1c23"), ("!active", "#cb2431")])
    style.configure("primary.TButton", foreground="white", background="#0366d6")
    style.map("primary.TButton",
              background=[("active", "#0256b5"), ("!active", "#0366d6")])

    # 列表样式
    style.configure("TListbox", font=("Segoe UI", 10), relief="flat")

    # 标签框样式
    style.configure("TLabelframe", font=("Segoe UI", 10, "bold"))
    style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))

    # 输入控件
    style.configure("TEntry", padding=5, relief="flat")

    # 机器人管理专用列表样式
    style.configure("Robot.Treeview", rowheight=36, font=("Segoe UI", 10))
    style.configure("TNotebook", tabmargins=(4, 4, 4, 0))
    style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI", 10))
    style.configure("TPanedwindow", background="#e7edf6")

