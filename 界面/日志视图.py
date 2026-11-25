"""MAA 式日志视图：左侧时间、右侧消息，按级别着色（主页面与悬浮窗共用）。"""
from __future__ import annotations

import html

from PySide6.QtWidgets import QTextBrowser

from 应用.日志模型 import 渲染结果, 展示文本, 展示级别
from 界面.主题 import 配色, 级别颜色

_空提示 = {
    "异常": "当前没有异常记录。",
    "重点": "开始任务后，运行过程会显示在这里。",
    "全部": "当前没有运行日志。",
}


class 日志视图(QTextBrowser):
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

    def 应用配色(self, 色: 配色):
        self._色 = 色
        self._上次签名 = None

    def 显示(self, 结果: 渲染结果, 色: 配色 | None = None) -> None:
        色 = 色 or self._色
        签名 = (结果.条目[-1:] if 结果.条目 else (), len(结果.条目), 结果.模式, 色.名称, id(色))
        if 签名 == self._上次签名:
            return
        self._上次签名 = 签名
        if not 结果.条目:
            self.setHtml(f'<span style="color:{色.弱文字}">{_空提示.get(结果.模式, "")}</span>')
            return
        行 = []
        for 项 in 结果.条目:
            颜色 = 级别颜色(色, 展示级别(项.内容, 项.级别))
            重复 = f'<span style="color:{色.弱文字}">　×{项.重复次数}</span>' if 项.重复次数 > 1 else ""
            行.append(
                "<tr>"
                f'<td style="color:{色.弱文字}; padding:3px 12px 3px 0; white-space:nowrap;'
                f' vertical-align:top;">{项.时间文本}</td>'
                f'<td style="color:{颜色}; padding:3px 0;">{html.escape(展示文本(项.内容))}{重复}</td>'
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
