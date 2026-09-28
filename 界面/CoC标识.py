"""独立绘制的城控标志：圆底和抽象城垛，不依赖第三方素材。"""
import tkinter as tk


def 创建CoC标识(父容器, 大小=48, 背景="#ffffff"):
    画布 = tk.Canvas(父容器, width=大小, height=大小, bg=背景,
                   bd=0, highlightthickness=0)
    比例 = 大小 / 64

    def 坐标(点):
        return [值 * 比例 for 值 in 点]

    画布.create_oval(*坐标((2, 2, 62, 62)), fill="#fff0e1", outline="")
    画布.create_polygon(*坐标((15, 46, 15, 23, 23, 23, 23, 17,
                             30, 17, 30, 23, 36, 23, 36, 17,
                             43, 17, 43, 23, 50, 23, 50, 46)),
                          fill="#c86c39", outline="")
    画布.create_rectangle(*坐标((28, 33, 37, 46)), fill="#fff0e1", outline="")
    画布.create_line(*坐标((14, 47, 51, 47)), fill="#8f4c2d",
                      width=max(1, round(比例 * 2)))
    return 画布
