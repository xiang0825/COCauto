import functools
import time
import unicodedata

import cv2
import tkinter as tk

import os
import subprocess

def 打印运行耗时(函数):
    @functools.wraps(函数)
    def 包装器(*参数, **关键字参数):
        开始时间 = time.time()
        结果 = 函数(*参数, **关键字参数)
        结束时间 = time.time()
        耗时 = 结束时间 - 开始时间
        print(f"函数「{函数.__name__}」运行耗时：{耗时:.4f} 秒")
        return 结果
    return 包装器


def 生成贝塞尔轨迹(起点, 控制点1, 控制点2, 终点, 步数=30):
    """生成三阶贝塞尔曲线路径"""
    轨迹 = []
    for i in range(步数 + 1):
        t = i / 步数
        x = (1 - t) ** 3 * 起点[0] + 3 * (1 - t) ** 2 * t * 控制点1[0] + 3 * (1 - t) * t ** 2 * 控制点2[
            0] + t ** 3 * 终点[0]
        y = (1 - t) ** 3 * 起点[1] + 3 * (1 - t) ** 2 * t * 控制点1[1] + 3 * (1 - t) * t ** 2 * 控制点2[
            1] + t ** 3 * 终点[1]
        轨迹.append((int(x), int(y)))
    return 轨迹

def 显示图像(屏幕图像):
    cv2.imshow("test",屏幕图像)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

def 是否家乡资源打满(资源字典: dict) -> bool:
    """根据资源字典判断是否资源打满，低本无黑油时也视为打满"""

    def 是打满(数值: int) -> bool:
        return str(数值).endswith("000") or str(数值).endswith("00000")

    金币 = 资源字典.get("金币", 0)
    圣水 = 资源字典.get("圣水", 0)
    黑油 = 资源字典.get("黑油", 0)

    return (
        是打满(金币) and
        是打满(圣水) and
        是打满(黑油)
        #(黑油 == 0 or 是打满(黑油))
    )



def 是否夜世界资源打满(资源字典: dict) -> bool:
    """根据已确认的金币和圣水判断夜世界资源是否打满。"""

    # 单项资源打满阈值，例如末尾 ≥ 4 个 0（十万级别）
    def 是打满(数值: int) -> bool:
        return str(数值).endswith("000") or str(数值).endswith("00000")

    return (
            是打满(资源字典.get("金币", 0)) and
            是打满(资源字典.get("圣水", 0))
    )

def 单行资源识别(ocr引擎, img):
    """识别已裁剪好的单行资源数字。

    右上角资源图在调用前已经按行裁剪；再运行文字检测和方向分类会额外
    加载/执行两个 ONNX 模型，并在分页文件较小的设备上触发 bad allocation。
    这里直接交给文字识别模型，既更轻量也更符合输入形态。
    """
    高, 宽 = img.shape[:2]
    # 资源栏一行高度约 53px，但数字本身只有约 18px 高；直接把整行
    # 缩放会让识别模型把图标和背景一起当成文字。先裁掉上下空白和右侧
    # 资源图标，把数字放大到更接近模型训练尺寸。
    if 高 >= 35:
        上 = max(0, int(round(高 * 0.12)))
        下 = min(高, int(round(高 * 0.82)))
        img = img[上:下, :]
    if 宽 >= 180:
        img = img[:, int(round(宽 * 0.28)):int(round(宽 * 0.82))]
    img = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

    灰度 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    二值图 = cv2.adaptiveThreshold(
        灰度,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        5
    )

    def 提取数字(结果):
        if not 结果:
            return 0
        # OCR 偶尔会把资源图标或阴影识别成额外的一项；取最长的数字
        # 串，而不是固定使用 result[0]，提高不同主题/分辨率下的稳定性。
        候选 = []
        for 项 in 结果:
            # 完整 OCR 返回 [坐标, 文字, 置信度]；轻量单行模式返回
            # [文字, 置信度]。两种格式都只提取真正的文字字段。
            if len(项) >= 3:
                原始文本 = 项[1]
            elif len(项) >= 2 and isinstance(项[0], str):
                原始文本 = 项[0]
            else:
                continue
            # OCR 可能返回全角/圈号数字；先做兼容性归一化，再只保留
            # ASCII 数字，避免 str.isdigit() 接受“①”却无法 int() 转换。
            清理文本 = unicodedata.normalize("NFKC", str(原始文本))
            清理文本 = 清理文本.replace('O', '0').replace('o', '0').replace(' ', '')
            数字 = ''.join(字符 for 字符 in 清理文本 if 字符 in "0123456789")
            if 数字:
                候选.append(数字)
        return int(max(候选, key=len)) if 候选 else 0

    # 彩色原图保留浅色数字的边缘；二值图作为不同主题下的备用输入。
    for 输入图 in (img, 二值图):
        result, _ = ocr引擎(输入图, use_det=False, use_cls=False)
        数值 = 提取数字(result)
        if 数值:
            return 数值
    return 0


from tkinter import ttk
import tkinter as tk

class 工具提示:
    def __init__(self, 控件, 文本):
        self.控件 = 控件
        self.文本 = 文本
        self.提示框 = None
        self.定时器 = None
        self.控件.bind("<Enter>", self.进入)
        self.控件.bind("<Leave>", self.离开)

    def 进入(self, 事件):
        self.定时器 = self.控件.after(500, self._显示提示框)

    def _显示提示框(self):
        if self.提示框:
            return
        x = self.控件.winfo_rootx() + 20
        y = self.控件.winfo_rooty() + self.控件.winfo_height() + 10
        self.提示框 = tk.Toplevel(self.控件)
        self.提示框.wm_overrideredirect(True)
        self.提示框.wm_geometry(f"+{x}+{y}")
        标签 = tk.Label(self.提示框, text=self.文本, background="#ffffe0", relief="solid", borderwidth=1, font=("微软雅黑", 12),wraplength=300)
        标签.pack(ipadx=1)

    def 离开(self, 事件):
        if self.定时器:
            self.控件.after_cancel(self.定时器)
            self.定时器 = None
        if self.提示框:
            self.提示框.destroy()
            self.提示框 = None
