"""部落竞赛动态配兵的纯规则：只调整已确认可用的单位，并保留基准阵容。"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Iterable


# 只开放已有编辑卡片模板、战斗兵栏模板且下兵流程可识别的指定单位。
# 游戏里显示“亡灵”，本项目军队配置名为“苍蝇”；“攻城车”按明确 OCR 别名
# 映射到攻城战车。其它名称一律不猜。
指定单位映射 = {
    "亡灵": ("苍蝇", "兵种"),
    "苍蝇": ("苍蝇", "兵种"),
    "气球兵": ("气球兵", "兵种"),
    "攻城车": ("攻城战车", "攻城"),
    "攻城战车": ("攻城战车", "攻城"),
}

拆墙单位 = "炸弹人"


def 解析指定单位(文本: str, 配置: dict | None = None) -> tuple[str, str] | None:
    """从竞赛详情中解析唯一支持的要求单位，返回 (配置名, 分区)。"""
    原文 = str(文本 or "")
    if 配置 is not None:
        # 延迟导入，避免与部落竞赛模块顶层互相导入。
        from 任务流程.活动.部落竞赛 import 纠正OCR文本
        原文 = 纠正OCR文本(原文, 配置)
    else:
        原文 = re.sub(r"\s+", "", 原文).replace("×", "x").replace("X", "x")

    标记列表 = ("至少需要使用", "至少需使用", "至少使用", "需要使用", "需使用", "使用")
    结束位置 = max(
        (原文.rfind(标记) + len(标记) for 标记 in 标记列表 if 原文.rfind(标记) >= 0),
        default=-1,
    )
    if 结束位置 < 0:
        return None
    尾部 = 原文[结束位置:].lstrip("：:，,、")
    匹配 = re.match(r"([^x×\d,，。；;]+)[x×]\s*\d+", 尾部)
    if not 匹配:
        return None
    要求名 = 匹配.group(1).strip("：:，,、")
    return 指定单位映射.get(要求名)


def _复制配置(配置: dict) -> dict:
    return {
        str(分区): dict(单位)
        for 分区, 单位 in deepcopy(配置).items()
        if isinstance(单位, dict) and 单位
    }


def 构建任务配兵(
    任务类型: str,
    任务文本: str,
    基准配置: dict | None,
    已解锁单位: Iterable[str],
) -> tuple[dict | None, str]:
    """以基准配置生成临时竞赛阵容；None 表示保持基准配置。"""
    if 任务类型 not in {"拆墙", "指定兵种"}:
        return None, "保持原配兵"
    if not isinstance(基准配置, dict) or not any(
        isinstance(单位, dict) and 单位 for 单位 in 基准配置.values()
    ):
        return None, "未启用自动配兵或没有可恢复的原配兵配置"

    可用 = {str(名) for 名 in (已解锁单位 or ())}
    配置 = _复制配置(基准配置)
    if 任务类型 == "拆墙":
        if 拆墙单位 not in 可用:
            return None, "炸弹人未解锁或编辑页未识别，不能安全接拆墙任务"
        兵种 = 配置.setdefault("兵种", {})
        总权重 = sum(max(0.0, float(值 or 0)) for 值 in 兵种.values())
        # 约给炸弹人五分之一军营空间（相对基准权重 25%），通常可带 25+ 个，
        # 覆盖 25 墙任务；下兵流程会优先部署并从靠近阵营中心的进攻边放下。
        兵种[拆墙单位] = max(float(兵种.get(拆墙单位, 0) or 0), max(0.5, 总权重 * 0.25))
        return 配置, ""

    解析结果 = 解析指定单位(任务文本)
    if not 解析结果:
        return None, "指定兵种要求不支持或名称/数量无法可靠识别"
    名称, 分区 = 解析结果
    if 名称 not in 可用:
        return None, f"{名称}未解锁或编辑页未识别，不能安全接指定兵种任务"
    if 分区 == "攻城":
        # 军队只有一个攻城器械位，临时替换即可；完成任务后由基准配置恢复。
        配置["攻城"] = {名称: 1}
        return 配置, ""

    兵种 = 配置.setdefault("兵种", {})
    总权重 = sum(max(0.0, float(值 or 0)) for 值 in 兵种.values())
    最低权重 = max(0.5, 总权重 * 0.08)
    兵种[名称] = max(float(兵种.get(名称, 0) or 0), 最低权重)
    return 配置, ""
