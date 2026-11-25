"""OCR checks shared by the normal-building and hero upgrade submit buttons."""

import re


_危险词 = ("宝石", "寶石", "立即完成", "马上完成", "立刻完成", "使用宝石", "购买")
_货币词 = {
    "dark_elixir": ("暗黑重油", "黑暗重油", "暗黑油", "黑油", "darkelixir"),
    "elixir": ("圣水", "聖水", "elixir"),
    "gold": ("金币", "金幣", "gold"),
}


def _规范文本(文本) -> str:
    return re.sub(r"[\s，,。．.!！?？:：;；/\\|()（）\[\]【】]", "", str(文本 or "")).lower()


def _解析框(识别项):
    try:
        框 = 识别项[0]
        xs = [float(点[0]) for 点 in 框]
        ys = [float(点[1]) for 点 in 框]
        if not xs or not ys:
            return None
        return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    except (TypeError, ValueError, IndexError):
        return None


def _在区域(中心, 区域) -> bool:
    return bool(
        中心
        and 区域[0] <= 中心[0] <= 区域[2]
        and 区域[1] <= 中心[1] <= 区域[3]
    )


def 定位安全升级按钮(
    OCR结果,
    按钮区域: tuple[int, int, int, int],
    费用区域: tuple[int, int, int, int],
    按钮标签: set[str] | frozenset[str],
) -> tuple[int, int] | None:
    """只返回带明确资源货币、金额和非宝石按钮文字的 OCR 坐标。

    费用框必须与按钮处在同一张资源卡片内。若 OCR 只读到数字或只读到
    按钮文字，或者卡片同时像多种货币，都按不安全处理。
    """
    项目 = []
    for 项 in OCR结果 or []:
        if not isinstance(项, (list, tuple)) or len(项) < 2:
            continue
        中心 = _解析框(项)
        if 中心 is None:
            continue
        文本 = _规范文本(项[1])
        项目.append((中心, 文本))

    # 宝石/立即完成文字落在拟点击资源卡片内时，不能让邻近的短 OCR
    # 结果掩盖它。另一张独立的宝石卡片位于安全区域之外，不影响资源卡。
    if any(
        _在区域(中心, 按钮区域) and any(词 in 文本 for 词 in _危险词)
        for 中心, 文本 in 项目
    ):
        return None

    标签 = {_规范文本(文本) for 文本 in 按钮标签}
    按钮候选 = [
        中心 for 中心, 文本 in 项目
        if 文本 in 标签 and _在区域(中心, 按钮区域)
    ]
    if len(按钮候选) != 1:
        return None
    按钮中心 = 按钮候选[0]

    货币证据 = []
    金额证据 = []
    for 中心, 文本 in 项目:
        if not _在区域(中心, 费用区域):
            continue
        if any(词 in 文本 for 词 in _危险词):
            return None
        命中货币 = {
            类型
            for 类型, 词组 in _货币词.items()
            if any(词 in 文本 for 词 in 词组)
        }
        if 命中货币:
            货币证据.append((中心, 命中货币))
        数字 = re.sub(r"\D", "", 文本)
        if len(数字) >= 3:
            金额证据.append((中心, 数字))

    货币类型 = {类型 for _, 类型组 in 货币证据 for 类型 in 类型组}
    if len(货币类型) != 1:
        return None
    if not any(
        abs(金额中心[0] - 货币中心[0]) <= 180
        and abs(金额中心[1] - 货币中心[1]) <= 90
        for 货币中心, _ in 货币证据
        for 金额中心, _ in 金额证据
    ):
        return None

    return round(按钮中心[0]), round(按钮中心[1])
