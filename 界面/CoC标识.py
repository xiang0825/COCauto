"""部落冲突风格的轻量级应用标识（纯 Tk 绘制，不依赖外部图片文件）。"""
import tkinter as tk
from tkinter import font as tkfont


def 创建CoC标识(父容器, 大小=58):
    """创建一个可随界面一起打包的盾牌标识。"""
    画布 = tk.Canvas(
        父容器,
        width=大小,
        height=大小,
        highlightthickness=0,
        bd=0,
        bg="#eef4ff",
    )
    边距 = max(3, 大小 // 14)
    左 = 边距
    右 = 大小 - 边距
    顶 = 边距
    底 = 大小 - 边距
    中 = 大小 // 2

    # 金色外盾、深红内盾，保留 CoC 主题辨识度但不复制第三方素材。
    画布.create_polygon(
        中, 顶, 右 - 5, 顶 + 8, 右 - 8, 大小 * 0.62,
        中, 底, 左 + 8, 大小 * 0.62, 左 + 5, 顶 + 8,
        fill="#f2b84b", outline="#9b5b1d", width=2,
    )
    画布.create_polygon(
        中, 顶 + 7, 右 - 12, 顶 + 12, 右 - 15, 大小 * 0.59,
        中, 底 - 7, 左 + 15, 大小 * 0.59, 左 + 12, 顶 + 12,
        fill="#c94132", outline="#7c241f", width=1,
    )
    画布.create_text(
        中, 大小 * 0.43, text="CoC", fill="#fff4d7",
        font=tkfont.Font(family="Segoe UI", size=max(10, 大小 // 5), weight="bold"),
    )
    return 画布
