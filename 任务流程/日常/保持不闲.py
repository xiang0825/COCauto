"""D. 实验室和建筑工人不闲（任务键 keep_busy）。

- 研究：按「不闲研究优先级」逐个尝试；实验室忙 → 本轮不再试；资源不足/
  未找到/满级 → 试下一个；提交成功一个就停（实验室同时只能研究一个）。
- 工人：复用 建筑升级任务，用「不闲建筑优先级」作指定列表，可选按游戏
  建议升级兜底；不改用户在 building/hero 里的配置。
- 全程复用原有安全护栏：红色价格=资源不足不点、确认按钮必须 OCR 到
  「确认」、宝石/立即完成入口不点、关闭面板走已确认面板的安全返回。

研究和工人两段之间由调度器（线程/自动化机器人.py）重新确认主世界。
"""
from __future__ import annotations

import time

from 任务流程.基础任务框架 import 基础任务
from 任务流程.日常 import 日常公共

任务键 = "keep_busy"
最多研究尝试数 = 10


def 规范目标列表(值) -> list[str]:
    if isinstance(值, str):
        值 = [值]
    结果: list[str] = []
    for 项 in 值 or []:
        文本 = str(项).strip()
        if 文本 and 文本 not in 结果:
            结果.append(文本)
    return 结果


class 保持不闲任务(基础任务):
    """keep_busy 的两段：``执行研究段()`` 与 ``执行工人段()``。"""

    # 测试可替换为假实现；真实运行时延迟导入原有研究/建筑任务。
    研究面板任务类 = None
    目标任务类 = None
    确认任务类 = None
    建筑任务类 = None

    def __init__(self, 上下文):
        super().__init__(上下文)
        self.本轮已提交研究: str | None = None

    # ------------------------------------------------------------ 冷却
    def 冷却中(self) -> bool:
        记录 = 日常公共.读取任务记录(self.数据库, self.机器人标志, 任务键)
        剩余 = 日常公共.冷却剩余秒(记录)
        if 剩余 > 0:
            self.上下文.置脚本状态(f"实验室/工人不闲：冷却中，{int(剩余 // 60)} 分钟后再检查")
            日常公共.请求等待(self.上下文, 剩余, "实验室/工人不闲冷却")
            return True
        return False

    def 记录完成(self) -> None:
        间隔分钟 = int(getattr(self.上下文.设置, "不闲检查间隔分钟", 60) or 60)
        间隔秒 = max(600, 间隔分钟 * 60)
        记录 = 日常公共.读取任务记录(self.数据库, self.机器人标志, 任务键)
        记录.update({
            "下次检查时间": time.time() + 间隔秒,
            "上次研究": self.本轮已提交研究 or 记录.get("上次研究"),
            "上次检查": time.time(),
        })
        日常公共.写入任务记录(self.数据库, self.机器人标志, 任务键, 记录)
        日常公共.请求等待(self.上下文, 间隔秒, "实验室/工人不闲检查间隔")

    # ------------------------------------------------------------ 研究
    def _类(self):
        if self.研究面板任务类 is None:
            from 任务流程.兵种或法术升级.打开研究面板 import 打开研究面板任务
            from 任务流程.兵种或法术升级.打开要升级的兵种或法术 import 打开要升级的兵种或法术任务
            from 任务流程.兵种或法术升级.完成兵种或法术升级 import 完成兵种或法术升级任务
            return 打开研究面板任务, 打开要升级的兵种或法术任务, 完成兵种或法术升级任务
        return self.研究面板任务类, self.目标任务类, self.确认任务类

    def 执行研究段(self) -> bool:
        """返回 False 仅表示页面状态不可信（调度器会进入安全待命）。"""
        目标列表 = 规范目标列表(getattr(self.上下文.设置, "不闲研究优先级", []))[:最多研究尝试数]
        if not 目标列表:
            self.上下文.置脚本状态("实验室不闲：未配置研究优先级，跳过研究")
            return True
        面板类, 目标类, 确认类 = self._类()
        for 序号, 目标 in enumerate(目标列表, start=1):
            if self._已停止():
                return True
            self.上下文.置脚本状态(f"实验室不闲：尝试第{序号}个研究目标 {目标}")
            if not 面板类(self.上下文).执行():
                if self._页面不可信():
                    return False
                self.上下文.置脚本状态("实验室不闲：实验室不可用或正在研究，本轮不再尝试")
                return True
            目标任务 = 目标类(self.上下文, 目标)
            if not 目标任务.执行():
                if self._页面不可信():
                    return False
                原因 = getattr(目标任务, "失败原因", None)
                if 原因 == "实验室忙":
                    self.上下文.置脚本状态("实验室不闲：实验室正在研究，跳过研究段")
                    return True
                if 原因 in ("异常", "点击失败"):
                    # 页面可能停在研究面板外的未知位置，不继续点下一个目标。
                    return False
                self.上下文.置脚本状态(f"实验室不闲：{目标} 不可研究（{原因 or '未知'}），试下一个")
                continue
            if 确认类(self.上下文).执行():
                self.本轮已提交研究 = 目标
                self.上下文.置脚本状态(f"实验室不闲：已提交研究 {目标}")
                return True
            if self._页面不可信():
                return False
            self.上下文.置脚本状态(f"实验室不闲：{目标} 资源不足或未确认，试下一个")
        self.上下文.置脚本状态("实验室不闲：优先级列表里没有可研究的目标")
        return True

    # ------------------------------------------------------------ 工人
    def 执行工人段(self) -> bool:
        设置 = self.上下文.设置
        优先级 = 规范目标列表(getattr(设置, "不闲建筑优先级", []))
        建议兜底 = bool(getattr(设置, "不闲建筑使用建议兜底", True))
        if not 优先级 and not 建议兜底:
            self.上下文.置脚本状态("工人不闲：未配置建筑优先级且未开启建议兜底，跳过")
            return True
        建筑类 = self.建筑任务类
        if 建筑类 is None:
            from 任务流程.建筑升级 import 建筑升级任务 as 建筑类
        # building/hero 同轮已经跑过时共用入口会跳过；keep_busy 是独立
        # 任务，清掉本轮标记再调用（工人状态每次都会重新 OCR）。
        self.上下文._建筑英雄升级本轮已执行 = False
        结果 = 建筑类(self.上下文, 指定建筑覆盖=优先级, 启用建议覆盖=建议兜底).执行()
        # 与 building 任务一致：True=已处理或安全跳过，False=页面不可信。
        return bool(结果)

    # ------------------------------------------------------------ 工具
    def _页面不可信(self) -> bool:
        return bool(getattr(self.上下文, "页面恢复失败", False))

    def _已停止(self) -> bool:
        停止 = getattr(self.上下文, "停止事件", None)
        return bool(停止 is not None and 停止.is_set())

    def 执行(self) -> bool:  # 供单独调用/测试；调度器分段调用
        if self.冷却中():
            return True
        if not self.执行研究段():
            return False
        if not self.执行工人段():
            return False
        self.记录完成()
        return True
