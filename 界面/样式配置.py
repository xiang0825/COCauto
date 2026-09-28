"""统一的浅色桌面工作台样式。"""
from tkinter import ttk


背景 = "#f7f8fa"
白色 = "#ffffff"
文字 = "#253142"
次要 = "#697788"
边框 = "#e4e8ed"
强调 = "#bd6536"


def 配置现代化样式():
    样式 = ttk.Style()
    样式.configure("TFrame", background=背景)
    样式.configure("TLabel", background=背景, foreground=文字,
                   font=("Microsoft YaHei UI", 10))
    样式.configure("TButton", padding=(12, 7),
                   font=("Microsoft YaHei UI", 10))
    样式.configure("TCheckbutton", background=背景,
                   font=("Microsoft YaHei UI", 10))
    样式.configure("TLabelframe", background=背景, bordercolor=边框, padding=8)
    样式.configure("TLabelframe.Label", background=背景, foreground=文字,
                   font=("Microsoft YaHei UI", 10, "bold"))
    样式.configure("TEntry", padding=6)
    样式.configure("TCombobox", padding=5)
    样式.configure("Treeview", rowheight=33, font=("Microsoft YaHei UI", 10),
                   background=白色, fieldbackground=白色, foreground=文字,
                   borderwidth=0)
    样式.configure("Treeview.Heading", padding=8,
                   font=("Microsoft YaHei UI", 10, "bold"))
    样式.map("Treeview", background=[("selected", "#fbe7d9")],
              foreground=[("selected", 文字)])
    样式.configure("App.TFrame", background=背景)
    样式.configure("Bar.TFrame", background=白色)
    样式.configure("Bar.TLabel", background=白色, foreground=文字,
                   font=("Microsoft YaHei UI", 10))
    样式.configure("PageTitle.TLabel", background=背景, foreground=文字,
                   font=("Microsoft YaHei UI", 19, "bold"))
    样式.configure("PageHint.TLabel", background=背景, foreground=次要,
                   font=("Microsoft YaHei UI", 10))
    样式.configure("Card.TFrame", background=白色, relief="solid", borderwidth=1)
    样式.configure("CardBody.TFrame", background=白色)
    样式.configure("Card.TLabel", background=白色, foreground=文字,
                   font=("Microsoft YaHei UI", 11))
    样式.configure("CardMuted.TLabel", background=白色, foreground=次要,
                   font=("Microsoft YaHei UI", 9))
    样式.configure("Status.TLabel", background=白色, foreground=强调,
                   font=("Microsoft YaHei UI", 10, "bold"))
