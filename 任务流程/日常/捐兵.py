"""B. 自动捐兵（任务键 donate_troops）—— 骨架，必须实机校准后才运行。

流程：主页点聊天按钮 → OCR 确认部落聊天面板 → 在请求列表里找「增援」按钮
（逐个）→ 点开后 OCR 确认捐兵弹窗 → 只在弹窗兵种区域里按模板找配置的
兵种/法术格子，读格子数量，满足保留规则才点 → 关闭弹窗 → 最后关闭聊天。

护栏（不论是否校准都生效）：
- 资源/日常/捐兵.json 里 calibrated 不是 true → 拒绝运行，只写日志。
- 只点三类东西：聊天按钮、请求上的「增援」按钮、捐兵弹窗里的兵种格子；
  另外两个关闭点由 JSON 指定、只在已确认的面板上使用。
- 任何要点的按钮/格子区域出现宝石图标或「宝石/购买/跳过/重置/加速」等
  文字 → 拒绝点击；兵种格子必须落在 JSON 的弹窗格子区域内。
- 没有模板的兵种、数量读不出来的格子一律不点。
- 主力兵（兵种选择里勾选的兵种/法术 + 阵容预设里的兵种/法术）至少保留
  「捐兵主力保留数量」个，其余兵种不保留。
"""
from __future__ import annotations

import time

from 任务流程.日常 import 日常公共

任务键 = "donate_troops"

默认参数 = {
    "calibrated": False,
    "点击后等待毫秒": 700,
    # 主页左侧聊天按钮（800x600）；校准前是参考值。
    "聊天按钮": [45, 310],
    "聊天面板确认区域": [0, 0, 400, 80],
    "聊天面板关键词": ["部落", "聊天"],
    "请求列表区域": [0, 60, 400, 600],
    "增援按钮关键词": ["增援", "捐兵", "捐赠"],
    "增援按钮半宽": 45,
    "增援按钮半高": 16,
    "捐兵弹窗确认区域": [380, 0, 800, 120],
    "捐兵弹窗关键词": ["增援", "捐赠", "捐兵"],
    "捐兵弹窗格子区域": [380, 80, 800, 560],
    "格子半宽": 32,
    "格子半高": 36,
    # 数量文字相对格子中心的 OCR 偏移 [dx1, dy1, dx2, dy2]。
    "格子数量偏移": [-30, -40, 30, -18],
    "兵种模板阈值": 0.85,
    # 兵种/法术名 → 资源/ 下的模板相对路径，例如 "日常/捐兵模板/野蛮人.png"。
    "兵种模板": {},
    "每个请求最多点击": 5,
    "关闭捐兵弹窗点": [200, 300],
    "关闭聊天点": [420, 300],
}


def 读取参数() -> dict:
    return 日常公共.加载日常参数("捐兵", 默认参数)


def 主力单位(设置) -> set[str]:
    单位 = set(getattr(设置, "配兵兵种", None) or []) | set(getattr(设置, "配兵法术", None) or [])
    预设名 = getattr(设置, "阵容预设", "")
    try:
        from 任务流程.军队配置.阵容预设 import 预设映射

        预设 = 预设映射.get(预设名)
    except Exception:
        预设 = None
    if 预设 is not None:
        单位 |= set(预设.兵种权重) | set(预设.法术个数)
    return 单位


def 可捐(名称: str, 当前数量: int | None, 设置) -> bool:
    """数量读不出来不捐；主力单位捐完后至少保留配置数量。"""
    if 当前数量 is None or 当前数量 <= 0:
        return False
    保留 = int(getattr(设置, "捐兵主力保留数量", 0) or 0) if 名称 in 主力单位(设置) else 0
    return 当前数量 - 1 >= 保留


class 捐兵任务(日常公共.日常面板任务基类):
    日志前缀 = "自动捐兵"

    def __init__(self, 上下文, 参数: dict | None = None):
        self.上下文 = 上下文
        self.数据库 = 上下文.数据库
        self.机器人标志 = 上下文.机器人标志
        self.参数 = 参数 if 参数 is not None else 读取参数()
        self.本轮捐出 = 0
        self.已开聊天 = False

    # ------------------------------------------------------------ 前置
    def 捐赠目标(self) -> list[str]:
        设置 = self.上下文.设置
        return list(getattr(设置, "捐兵兵种", None) or []) + list(getattr(设置, "捐兵法术", None) or [])

    def 可以运行(self) -> bool:
        """未配置/未校准/冷却中返回 False（均为安全跳过，不点击）。"""
        if not self.捐赠目标():
            self.日志("未配置要捐的兵种或法术，跳过")
            日常公共.请求等待(self.上下文, 3600, "捐兵未配置")
            return False
        if not 日常公共.已校准(self.参数):
            self.日志(
                "资源/日常/捐兵.json 尚未实机校准（calibrated=false），拒绝运行；"
                "请先截聊天面板/捐兵弹窗校准坐标后再开启"
            )
            日常公共.请求等待(self.上下文, 3600, "捐兵未校准")
            return False
        记录 = 日常公共.今日记录(self.数据库, self.机器人标志, 任务键)
        剩余 = 日常公共.冷却剩余秒(记录)
        if 剩余 > 0:
            日常公共.请求等待(self.上下文, 剩余, "捐兵检查间隔")
            return False
        return True

    # ------------------------------------------------------------ 主流程
    def 执行(self) -> bool:
        """True=完成或安全跳过；False=页面状态不可信（调度器安全待命）。"""
        if not self.可以运行():
            return True
        try:
            结果 = self._执行聊天流程()
        except Exception as 异常:
            self.日志(f"异常：{异常}")
            self.上下文.页面恢复失败 = True
            return False
        if self.已停止():
            # 停止后不再发任何点击（包括关闭聊天），也不记完成，保留画面。
            return True
        if 结果:
            self.记录完成()
        return 结果

    def _执行聊天流程(self) -> bool:
        图 = self.截图()
        x, y = self.参数["聊天按钮"]
        if not self.点击前护栏(图, 日常公共.扩展区域((x, y), 30, 30), "聊天按钮"):
            return True
        if not self.点击(x, y, "打开聊天"):
            return True
        self.已开聊天 = True
        图 = self.截图()
        if not self.区域有关键词(图, self.参数["聊天面板确认区域"], self.参数["聊天面板关键词"]):
            self.日志("点了聊天按钮但未确认部落聊天面板，停止并保留画面")
            self.上下文.页面恢复失败 = True
            return False
        已处理 = []
        for _ in range(int(getattr(self.上下文.设置, "捐兵每轮最多请求数", 5) or 5)):
            if self.已停止():
                return True
            结果 = self._处理一个请求(已处理)
            if 结果 is None:
                break
            if 结果 is False:
                return False
        if self.已停止():
            return True
        return self._关闭聊天()

    def _处理一个请求(self, 已处理: list) -> bool | None:
        """None=没有更多请求；False=页面不可信；True=已处理一个。"""
        图 = self.截图()
        按钮 = self._找增援按钮(图, 已处理)
        if 按钮 is None:
            return None
        已处理.append(按钮)
        区域 = 日常公共.扩展区域(按钮, int(self.参数["增援按钮半宽"]), int(self.参数["增援按钮半高"]))
        if not self.点击前护栏(图, 区域, "增援按钮"):
            return True
        if not self.点击(*按钮, "打开捐兵弹窗"):
            return True
        图 = self.截图()
        if not self.区域有关键词(图, self.参数["捐兵弹窗确认区域"], self.参数["捐兵弹窗关键词"]):
            self.日志("点了增援但未确认捐兵弹窗，停止并保留画面")
            self.上下文.页面恢复失败 = True
            return False
        self._在弹窗里捐兵()
        return self._关闭弹窗()

    def _找增援按钮(self, 图, 已处理: list):
        关键词 = [日常公共.规范文本(词) for 词 in self.参数["增援按钮关键词"]]
        for 文本, 中心 in self.OCR或空(图, self.参数["请求列表区域"]):
            if 中心 is None or 日常公共.含危险词(文本):
                continue
            if not any(词 in 文本 for 词 in 关键词):
                continue
            if any(abs(中心[1] - 旧[1]) < 20 for 旧 in 已处理):
                continue
            return int(中心[0]), int(中心[1])
        return None

    def _在弹窗里捐兵(self) -> None:
        设置 = self.上下文.设置
        剩余点击 = int(self.参数["每个请求最多点击"])
        for 名称 in self.捐赠目标():
            while 剩余点击 > 0 and not self.已停止():
                图 = self.截图()
                格子 = self._找格子(图, 名称)
                if 格子 is None:
                    break
                格区 = 日常公共.扩展区域(格子, int(self.参数["格子半宽"]), int(self.参数["格子半高"]))
                if not self.点击前护栏(图, 格区, f"{名称}格子"):
                    break
                数量 = self._读格子数量(图, 格子)
                if not 可捐(名称, 数量, 设置):
                    self.日志(f"{名称} 数量 {数量} 不满足保留规则，不捐")
                    break
                if not self.点击(*格子, f"捐 {名称}"):
                    return
                self.本轮捐出 += 1
                剩余点击 -= 1
            if 剩余点击 <= 0:
                return

    def _找格子(self, 图, 名称: str):
        路径 = (self.参数.get("兵种模板") or {}).get(名称)
        if not 路径:
            return None
        模板 = 日常公共.读取图片(str(路径))
        if 模板 is None:
            self.日志(f"{名称} 模板 {路径} 不存在，跳过")
            return None
        区域 = self.参数["捐兵弹窗格子区域"]
        命中 = 日常公共.匹配模板(图, 模板, 区域, float(self.参数["兵种模板阈值"]))
        if 命中 is None:
            return None
        x, y = 命中[0], 命中[1]
        x1, y1, x2, y2 = 区域
        if not (x1 <= x <= x2 and y1 <= y <= y2):
            return None
        return x, y

    def _读格子数量(self, 图, 格子) -> int | None:
        dx1, dy1, dx2, dy2 = [int(v) for v in self.参数["格子数量偏移"]]
        区域 = (max(0, 格子[0] + dx1), max(0, 格子[1] + dy1), min(800, 格子[0] + dx2), min(600, 格子[1] + dy2))
        if 区域[2] <= 区域[0] or 区域[3] <= 区域[1]:
            return None
        for 文本, _ in self.OCR或空(图, 区域):
            数量 = 日常公共.解析数量(文本)
            if 数量 is not None:
                return 数量
        return None

    def _聊天面板在(self, 图) -> bool:
        return self.区域有关键词(图, self.参数["聊天面板确认区域"], self.参数["聊天面板关键词"]) is not None

    def _关闭弹窗(self) -> bool:
        """捐满后游戏会自动收起弹窗：此时只要确认回到聊天面板就不点。"""
        if self.安全关闭(
            self.参数["关闭捐兵弹窗点"], self.参数["捐兵弹窗确认区域"],
            self.参数["捐兵弹窗关键词"], "关闭捐兵弹窗", 已关闭判定=self._聊天面板在,
        ):
            return True
        return self._标记失败("关闭捐兵弹窗前未确认页面或关闭点不安全")

    def _关闭聊天(self) -> bool:
        if not self.安全关闭(
            self.参数["关闭聊天点"], self.参数["聊天面板确认区域"],
            self.参数["聊天面板关键词"], "关闭聊天",
        ):
            return self._标记失败("关闭聊天前未确认聊天面板或关闭点不安全")
        self.已开聊天 = False
        return True

    def _标记失败(self, 原因: str) -> bool:
        self.日志(原因)
        self.上下文.页面恢复失败 = True
        return False

    def 记录完成(self) -> None:
        间隔 = max(5, int(getattr(self.上下文.设置, "捐兵检查间隔分钟", 15) or 15)) * 60
        记录 = 日常公共.今日记录(self.数据库, self.机器人标志, 任务键)
        记录["今日捐出"] = int(记录.get("今日捐出", 0)) + self.本轮捐出
        记录["下次检查时间"] = time.time() + 间隔
        日常公共.写入任务记录(self.数据库, self.机器人标志, 任务键, 记录)
        self.日志(f"本轮捐出 {self.本轮捐出} 个，今日累计 {记录['今日捐出']}")
        日常公共.请求等待(self.上下文, 间隔, "捐兵检查间隔")
