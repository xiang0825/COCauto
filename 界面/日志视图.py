"""MAA 式日志视图：左侧时间、右侧消息，按级别着色（主页面与悬浮窗共用）。"""
from __future__ import annotations

import html

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTextBrowser

from 应用.日志模型 import 渲染结果, 展示文本, 展示级别
from 界面.主题 import 是暗色, 配色, 级别颜色

# 胶囊类别：(关键词, 类别)，按顺序匹配；错误/警告级别一律归为“异常”。
_类别关键词 = (
    (("竞赛",), "竞赛"),
    (("搜敌", "搜索", "找鱼", "下一个", "跳过"), "搜敌"),
    (("进攻", "战斗", "部署", "下兵", "星", "摧毁", "回营"), "进攻"),
    (("护盾", "保护", "休眠", "待命", "等待"), "保护"),
)
# 胶囊配色（文字色, 深色底, 浅色底）；QTextBrowser 不支持圆角与半透明，用实色近似。
_胶囊色 = {
    "搜敌": ("#93C5FD", "#1B2433", "#E8F0FE"),
    "进攻": ("#FCD34D", "#2A2316", "#FEF3D7"),
    "竞赛": ("#C4B5FD", "#231F33", "#EFEAFE"),
    "保护": ("#86EFAC", "#17271E", "#E3F7EA"),
    "异常": ("#FCA5A5", "#2D1A1C", "#FDE7E7"),
    "系统": ("#D1D5DB", "#1F2228", "#EEF0F3"),
}
_浅色字 = {"搜敌": "#1D4ED8", "进攻": "#B45309", "竞赛": "#6D28D9", "保护": "#15803D", "异常": "#B91C1C", "系统": "#4B5563"}


def 日志类别(内容: str, 级别: str) -> str:
    if 级别 in ("错误", "警告"):
        return "异常"
    for 关键词, 类别 in _类别关键词:
        if any(词 in 内容 for 词 in 关键词):
            return 类别
    return "系统"

_空提示 = {
    "异常": "当前没有异常记录。",
    "重点": "开始任务后，运行过程会显示在这里。",
    "全部": "当前没有运行日志。",
}


class 日志视图(QTextBrowser):
    # 点击异常行的“现场图”链接：(时间戳, 日志文本)
    请求现场图 = Signal(float, str)

    def __init__(self, 色: 配色, 父=None):
        super().__init__(父)
        self.setObjectName("日志")
        self.setOpenLinks(False)
        self.setLineWrapMode(QTextBrowser.WidgetWidth)
        self._色 = 色
        self.跟随 = True
        # 自动跟随：滚动条在底部时跟随新日志，用户往上翻看时保持位置。
        self.自动跟随 = False
        self._上次签名 = None
        self.胶囊 = True
        # 返回现场截图条目或 None；为 None 时不显示“现场图”链接。
        self.现场图查找: Callable[[float], object] | None = None
        self.现场图版本 = 0
        self._链接 = {}
        self.anchorClicked.connect(self._点击链接)

    def _点击链接(self, 地址):
        键 = 地址.toString()
        if 键 in self._链接:
            self.请求现场图.emit(*self._链接[键])

    def 应用配色(self, 色: 配色):
        self._色 = 色
        self._上次签名 = None

    def 显示(self, 结果: 渲染结果, 色: 配色 | None = None) -> None:
        色 = 色 or self._色
        签名 = (结果.条目[-1:] if 结果.条目 else (), len(结果.条目), 结果.模式, 色.名称, id(色), self.现场图版本)
        if 签名 == self._上次签名:
            return
        self._上次签名 = 签名
        if not 结果.条目:
            self.setHtml(f'<span style="color:{色.弱文字}">{_空提示.get(结果.模式, "")}</span>')
            return
        行 = []
        self._链接 = {}
        暗 = 是暗色(色)
        for 序号, 项 in enumerate(结果.条目):
            级别 = 展示级别(项.内容, 项.级别)
            颜色 = 级别颜色(色, 级别)
            文本 = 展示文本(项.内容)
            重复 = f'<span style="color:{色.弱文字}">　×{项.重复次数}</span>' if 项.重复次数 > 1 else ""
            类别 = 日志类别(文本, 级别)
            胶囊 = ""
            if self.胶囊:
                字, 深底, 浅底 = _胶囊色[类别]
                胶囊 = (f'<td style="padding:3px 8px 3px 0; white-space:nowrap; vertical-align:top;">'
                      f'<span style="color:{字 if 暗 else _浅色字[类别]}; background-color:{深底 if 暗 else 浅底};'
                      f' font-size:11px; font-weight:600;">&nbsp;{类别}&nbsp;</span></td>')
            链接 = ""
            if 类别 == "异常" and self.现场图查找 is not None:
                try:
                    条目 = self.现场图查找(项.时间戳)
                except Exception:
                    条目 = None
                if 条目 is not None:
                    键 = f"scene:{序号}"
                    self._链接[键] = (float(项.时间戳), 文本)
                    链接 = f'　<a href="{键}" style="color:{色.强调}; text-decoration:none;">现场图 ›</a>'
            行.append(
                "<tr>"
                f'<td style="color:{色.弱文字}; padding:3px 10px 3px 0; white-space:nowrap;'
                f' vertical-align:top; font-family:Consolas, monospace;">{项.时间文本}</td>'
                f"{胶囊}"
                f'<td style="color:{颜色}; padding:3px 0;">{html.escape(文本)}{重复}{链接}</td>'
                "</tr>"
            )
        滚动条 = self.verticalScrollBar()
        原位置 = 滚动条.value()
        在底部 = 原位置 >= 滚动条.maximum() - 4
        self.setHtml(
            '<table cellspacing="0" cellpadding="0" width="100%">' + "".join(行) + "</table>"
        )
        跟随 = 在底部 if self.自动跟随 else self.跟随
        滚动条.setValue(滚动条.maximum() if 跟随 else 原位置)
