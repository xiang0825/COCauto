def 战斗记录可用于策略学习(战斗记录) -> bool:
    """根据有效标记和投兵数量判断策略样本，并兼容缺少投兵字段的旧记录。"""
    if not isinstance(战斗记录, dict):
        return False

    def 转换数量(值):
        try:
            return float(值) if 值 is not None else None
        except (TypeError, ValueError, OverflowError):
            return None

    可部署数量 = 转换数量(战斗记录.get("可部署单位数量"))
    实际投放数量 = 转换数量(战斗记录.get("实际投放数量"))
    if (
        可部署数量 is None
        and 实际投放数量 is not None
        and 实际投放数量 < 30
    ):
        return False

    明确有效 = 战斗记录.get("策略样本有效")
    if 明确有效 is not None:
        return bool(明确有效)
    if 实际投放数量 is None:
        return 可部署数量 is None
    if 可部署数量 is None or 可部署数量 < 8:
        return True
    return 实际投放数量 >= 可部署数量 * 0.5


def 统计连续低表现次数(近期记录, 记录有效判断=None) -> int:
    """统计最近最多三场、从最新一场向前连续的低表现记录。

    任意已确认胜利都会中断低表现序列；它不会因低星或低摧毁率被
    误算成失败。无效记录同样中断序列，避免跨过缺失样本拼接失败数。
    """
    try:
        记录列表 = list(近期记录 or [])[-3:]
    except (TypeError, ValueError):
        return 0

    连续次数 = 0
    for 记录 in reversed(记录列表):
        if not isinstance(记录, dict):
            break
        if 记录.get("结果") == "胜利":
            break
        if callable(记录有效判断):
            try:
                if not 记录有效判断(记录):
                    break
            except Exception:
                break

        结果 = 记录.get("结果")
        if 结果 == "失败":
            低表现 = True
        else:
            try:
                星数 = float(记录["星数"]) if 记录.get("星数") is not None else None
            except (TypeError, ValueError, OverflowError):
                星数 = None
            try:
                摧毁率 = (
                    float(记录["摧毁率"])
                    if 记录.get("摧毁率") is not None
                    else None
                )
            except (TypeError, ValueError, OverflowError):
                摧毁率 = None
            低表现 = (
                (星数 is not None and 星数 <= 1)
                or (摧毁率 is not None and 摧毁率 < 50)
            )

        if not 低表现:
            break
        连续次数 += 1
    return 连续次数
