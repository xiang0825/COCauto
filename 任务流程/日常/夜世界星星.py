"""A. 夜世界每天打满星星奖励场次（任务键 night_star_bonus）。

判断“今日已领满”有两道依据：
1. 计数（默认、离线可验证）：每次安全确认夜世界「星级奖励」弹窗，
   上下文 ``_夜世界星级奖励确认次数`` +1（基础任务框架里计数）。今日确认
   次数达到「每日星级奖励次数」即完成。
2. 主页 OCR（可选）：资源/日常/夜世界星星.json 校准后（calibrated=true），
   每场前 OCR 夜世界主页的星级奖励区域，命中「已领满关键词」即完成。
   未校准时不使用 OCR，只靠计数。

另有每日最多场次保护，防止奖励弹窗漏识别时无限打下去。
复用原夜世界打鱼任务链（打开进攻→等待→下兵→第二场→回营），不花宝石。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from 任务流程.基础任务框架 import 基础任务
from 任务流程.日常 import 日常公共

任务键 = "night_star_bonus"

默认参数 = {
    "calibrated": False,
    # 星星奖励每天按服务器时间重置；未确认前按本地 0 点。
    "每日重置本地小时": 0,
    # 夜世界主页上显示星级奖励进度/冷却的区域（800x600 逻辑坐标）。
    "主页星级OCR区域": [0, 470, 200, 600],
    "已领满关键词": ["已领取", "已領取", "明天", "明日", "下次奖励", "下次獎勵"],
}


def 读取参数() -> dict:
    return 日常公共.加载日常参数("夜世界星星", 默认参数)


def 奖励日(现在: float | None = None, 重置小时: int = 0) -> str:
    """按重置小时划分“今天”：重置前算前一天。"""
    时刻 = datetime.fromtimestamp(time.time() if 现在 is None else 现在)
    return (时刻 - timedelta(hours=max(0, min(23, int(重置小时))))).strftime("%Y-%m-%d")


def 距下次重置秒(现在: float | None = None, 重置小时: int = 0) -> float:
    时刻 = datetime.fromtimestamp(time.time() if 现在 is None else 现在)
    小时 = max(0, min(23, int(重置小时)))
    下次 = 时刻.replace(hour=小时, minute=0, second=0, microsecond=0)
    if 下次 <= 时刻:
        下次 += timedelta(days=1)
    return (下次 - 时刻).total_seconds()


class 夜世界星星任务(基础任务):
    """调度器调用顺序：今日已完成() → 进入夜世界 → 循环 打一场()。"""

    夜世界打鱼任务类 = None  # 测试可替换

    def __init__(self, 上下文, 参数: dict | None = None):
        super().__init__(上下文)
        self.参数 = 参数 if 参数 is not None else 读取参数()
        self.重置小时 = int(self.参数.get("每日重置本地小时", 0) or 0)

    # ------------------------------------------------------------ 记录
    def 读取今日记录(self) -> dict:
        记录 = 日常公共.读取任务记录(self.数据库, self.机器人标志, 任务键)
        今天 = 奖励日(重置小时=self.重置小时)
        if 记录.get("日期") != 今天:
            记录 = {"日期": 今天, "场次": 0, "星级奖励": 0, "已领满": False}
        return 记录

    def 保存记录(self, 记录: dict) -> None:
        日常公共.写入任务记录(self.数据库, self.机器人标志, 任务键, 记录)

    def 每日奖励次数(self) -> int:
        return max(1, int(getattr(self.上下文.设置, "夜世界每日星级奖励次数", 1) or 1))

    def 每日最多场次(self) -> int:
        return max(1, int(getattr(self.上下文.设置, "夜世界星星每日最多场次", 12) or 12))

    def 今日已完成(self) -> bool:
        记录 = self.读取今日记录()
        原因 = None
        if 记录.get("已领满"):
            原因 = "今日星星奖励已领满"
        elif int(记录.get("场次", 0)) >= self.每日最多场次():
            原因 = f"今日已打 {记录.get('场次')} 场，达到每日上限"
        if 原因 is None:
            return False
        剩余 = 距下次重置秒(重置小时=self.重置小时)
        self.上下文.置脚本状态(f"夜世界星星：{原因}，{int(剩余 // 3600)} 小时后重置")
        日常公共.请求等待(self.上下文, 剩余, "夜世界星星今日已完成")
        return True

    # ------------------------------------------------------------ OCR
    def 主页显示已领满(self) -> bool:
        if not 日常公共.已校准(self.参数):
            return False
        try:
            区域 = tuple(int(v) for v in self.参数["主页星级OCR区域"])
            结果 = self.执行OCR识别(区域)
        except Exception as 异常:
            self.上下文.置脚本状态(f"夜世界星星：主页星级 OCR 失败，改用计数：{异常}")
            return False
        关键词 = [str(词) for 词 in self.参数.get("已领满关键词", [])]
        for 文本, _ in 日常公共.OCR文本列表(结果):
            if any(词 and 词 in 文本 for 词 in 关键词):
                self.上下文.置脚本状态(f"夜世界星星：主页显示「{文本}」，今日奖励已领满")
                return True
        return False

    # ------------------------------------------------------------ 页面
    def 确认夜世界主页(self, 最多尝试: int = 3) -> bool:
        识别 = getattr(self.上下文, "识别点击画面", None)
        if not callable(识别):
            return False
        for _ in range(最多尝试):
            结果 = 识别(强制=True)
            页面 = str(getattr(结果, "页面", "") or "")
            if 页面 == "夜世界主页":
                return True
            if 页面 == "战斗星级奖励":
                处理 = getattr(self.上下文, "处理战斗星级奖励弹窗", None)
                if callable(处理):
                    处理(强制=True)
            延时 = getattr(self.上下文, "脚本延时", None)
            if callable(延时):
                延时(800)
        self.上下文.置脚本状态("夜世界星星：未确认夜世界主页，禁止点击进攻")
        return False

    def 执行(self) -> bool:
        """已在夜世界主页时连续打到完成；进入夜世界由调度器负责。"""
        if self.今日已完成():
            return True
        while True:
            停止 = getattr(self.上下文, "停止事件", None)
            if 停止 is not None and 停止.is_set():
                return True
            结果 = self.打一场()
            if 结果 != "继续":
                return 结果 == "完成"

    # ------------------------------------------------------------ 一场
    def 打一场(self) -> str:
        """返回 "完成"（今日已领满/到上限）、"继续" 或 "失败"（页面不可信）。"""
        记录 = self.读取今日记录()
        if 记录.get("已领满") or int(记录.get("场次", 0)) >= self.每日最多场次():
            return "完成"
        if not self.确认夜世界主页():
            return "失败"
        if self.主页显示已领满():
            记录["已领满"] = True
            self.保存记录(记录)
            return "完成"
        打鱼类 = self.夜世界打鱼任务类
        if 打鱼类 is None:
            from 任务流程.夜世界.夜世界打鱼 import 夜世界打鱼任务 as 打鱼类
        前 = int(getattr(self.上下文, "_夜世界星级奖励确认次数", 0) or 0)
        成功 = 打鱼类(self.上下文).执行()
        # 回营后奖励弹窗可能在下一帧才出现：再确认一次主页（会顺手处理弹窗）。
        if 成功:
            self.确认夜世界主页(最多尝试=2)
        后 = int(getattr(self.上下文, "_夜世界星级奖励确认次数", 0) or 0)
        记录 = self.读取今日记录()
        记录["场次"] = int(记录.get("场次", 0)) + 1
        记录["星级奖励"] = int(记录.get("星级奖励", 0)) + max(0, 后 - 前)
        if 记录["星级奖励"] >= self.每日奖励次数():
            记录["已领满"] = True
        记录["上次战斗"] = time.time()
        self.保存记录(记录)
        self.上下文.置脚本状态(
            f"夜世界星星：今日第{记录['场次']}场，星级奖励 {记录['星级奖励']}/{self.每日奖励次数()}"
        )
        if not 成功:
            return "失败"
        return "完成" if 记录["已领满"] or 记录["场次"] >= self.每日最多场次() else "继续"
