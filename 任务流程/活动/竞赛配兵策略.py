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
    """生成临时竞赛阵容方案（可行性判断）；None 表示保持原阵容。

    基准配置可以为空（未开启“按设置自动配兵”）：实际换兵时由编辑页按换兵前
    读到的实际阵容快照重新计算确切个数（见 按快照构建临时阵容），并按快照恢复。
    """
    if 任务类型 not in {"拆墙", "指定兵种"}:
        return None, "保持原配兵"
    if not isinstance(基准配置, dict):
        基准配置 = {}

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


# ---- 快照换兵：以编辑页实际阵容（确切个数）为基准，只改要求单位所在分区 ----
拆墙空间比例 = 0.20   # 约五分之一军营给炸弹人，覆盖 25 墙任务
指定兵种空间比例 = 0.08


def 解析要求数量(文本: str) -> int:
    原文 = re.sub(r"\s+", "", str(文本 or "")).replace("×", "x").replace("X", "x")
    匹配 = re.findall(r"x(\d{1,3})", 原文)
    try:
        return max(1, int(匹配[-1])) if 匹配 else 1
    except ValueError:
        return 1


def 按快照构建临时阵容(
    任务类型: str,
    任务文本: str,
    关键单位: dict,
    分区快照: dict,
) -> tuple[dict | None, str]:
    """返回 ({分区: {单位: 确切个数}}, "")，只含需要改动的分区。

    不需要改动时返回 (None, "已满足…")；不能安全构建时返回 (None, 原因)。
    兵种区：从占用最多的非要求单位里逐个腾出空间给要求单位，其余单位个数保持不变；
    攻城区：只有一个攻城器械会被带入战斗，直接换成要求的攻城器械 1 个。
    """
    from 任务流程.军队配置 import 兵种资料

    结果: dict[str, dict[str, int]] = {}
    for 区, 名单 in (关键单位 or {}).items():
        快照 = (分区快照 or {}).get(区)
        if not isinstance(快照, dict) or not 名单:
            return None, f"{区}没有原阵容快照"
        原单位 = {str(名): int(数) for 名, 数 in (快照.get("单位") or {}).items()}
        try:
            上限 = int((快照.get("容量") or [0, 0])[1])
        except (TypeError, ValueError, IndexError):
            上限 = 0
        if 上限 <= 0:
            return None, f"{区}容量未知"
        if 区 == "攻城":
            名 = str(名单[0])
            if 原单位.get(名, 0) > 0:
                continue
            结果[区] = {名: 1}
            continue
        if 区 != "兵种" or len(名单) != 1:
            return None, f"{区}临时换兵不支持"
        名 = str(名单[0])
        单人口 = 兵种资料.人口(名)
        if 单人口 <= 0:
            return None, f"{名}人口未知"
        要求 = 解析要求数量(任务文本) if 任务类型 == "指定兵种" else 1
        比例 = 拆墙空间比例 if 任务类型 == "拆墙" else 指定兵种空间比例
        目标个数 = max(要求, -(-int(上限 * 比例) // 单人口))
        已有 = 原单位.get(名, 0)
        if 已有 >= (目标个数 if 任务类型 == "拆墙" else 要求):
            continue
        单位 = dict(原单位)
        人口表 = {单: 兵种资料.人口(单) for 单 in 单位}
        if any(值 <= 0 for 值 in 人口表.values()):
            return None, "原阵容中有人口未知的单位"
        已用 = sum(人口表[单] * 数 for 单, 数 in 单位.items())
        需要 = (目标个数 - 已有) * 单人口 - (上限 - 已用)
        while 需要 > 0:
            候选 = [单 for 单, 数 in 单位.items() if 单 != 名 and 数 > 0]
            if not 候选:
                break
            移除 = max(候选, key=lambda 单: (人口表[单] * 单位[单], 人口表[单]))
            单位[移除] -= 1
            需要 -= 人口表[移除]
            已用 -= 人口表[移除]
        单位 = {单: 数 for 单, 数 in 单位.items() if 数 > 0}
        新增 = (上限 - 已用) // 单人口
        if 已有 + 新增 < 要求:
            return None, f"原阵容腾不出足够空间放{名}"
        单位[名] = 已有 + 新增
        已用 += 新增 * 单人口
        # 剩下不够一个要求单位的零头，用原阵容里人口最小的单位补上，尽量保持满营。
        for 单 in sorted((单 for 单 in 单位 if 单 != 名), key=lambda 单: 人口表[单]):
            if 上限 - 已用 >= 人口表[单]:
                加 = (上限 - 已用) // 人口表[单]
                单位[单] += 加
                已用 += 加 * 人口表[单]
        结果[区] = 单位
    if not 结果:
        return None, "已满足：现有阵容已包含任务要求单位"
    return 结果, ""
