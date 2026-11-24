"""胜利之星奖励宝箱：领取后手动敲开宝箱，而不是跳过动画。

用户描述的实机流程（2026-11-24）：领取奖励后出现宝箱 → 点击宝箱；点击成功后
宝箱下方出现类似锤子的计数，计数减少到 3 → 再连续点击 3 次 → 等待 3 秒 →
再点击 1 次 → 确认回到主世界。

这个页面机器人之前从未实际走过（一直点“跳过动画”），所以：
- 每一步都保存截图到 ``数据集/奖励宝箱``，用于之后校准位置；
- 每次点击前用 OCR 检查画面上没有宝石/购买字样；
- 读不到锤子计数、计数一直不下降、或最后没回到主世界时返回 False，
  调用方照旧走“跳过动画”的兜底流程。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import cv2

宝箱点击点 = (400, 300)               # 800×600 画面中央的宝箱
锤子计数OCR区域 = (200, 360, 600, 580)  # 宝箱下方
目标计数 = 3
最多敲击次数 = 12
敲击间隔毫秒 = 600
开箱等待毫秒 = 3000
回主世界等待秒 = 15.0
危险文字 = ("寶石", "宝石", "購買", "购买")


def _保存截图(图像, 步骤: str) -> None:
    try:
        目录 = Path("数据集") / "奖励宝箱"
        目录.mkdir(parents=True, exist_ok=True)
        成功, 数据 = cv2.imencode(".png", 图像)
        if 成功:
            (目录 / f"{int(time.time() * 1000)}_{步骤}.png").write_bytes(数据.tobytes())
    except Exception:
        pass


def _OCR(上下文, 图像) -> list:
    try:
        返回 = 上下文.获取OCR引擎()(图像, use_cls=False)
    except TypeError:
        返回 = 上下文.获取OCR引擎()(图像)
    except Exception:
        return []
    结果 = 返回[0] if isinstance(返回, tuple) else 返回
    return [项 for 项 in (结果 or []) if isinstance(项, (list, tuple)) and len(项) >= 2]


def 读取锤子计数(OCR结果) -> int | None:
    """从宝箱下方区域的 OCR 结果里取单独的个位数（如 “3”“x3”“×3”）。"""
    候选 = []
    for 项 in OCR结果:
        文本 = str(项[1]).strip().replace(" ", "")
        匹配 = re.fullmatch(r"[xX×]?(\d)", 文本)
        if 匹配:
            候选.append(int(匹配.group(1)))
    return min(候选) if 候选 else None


def 开启奖励宝箱(上下文) -> bool:
    """按用户描述敲开宝箱并确认回到主世界；任何一步确认不了返回 False。"""
    置状态 = getattr(上下文, "置脚本状态", lambda *_a, **_k: None)

    def 截图():
        return 上下文.op.获取屏幕图像cv(0, 0, 800, 600, 强制刷新=True)

    def 画面安全(图像) -> bool:
        文字 = "".join(str(项[1]) for 项 in _OCR(上下文, 图像))
        return not any(字 in 文字 for 字 in 危险文字)

    def 敲一下(步骤: str) -> bool:
        图像 = 截图()
        if not 画面安全(图像):
            _保存截图(图像, f"{步骤}_宝石字样")
            置状态("奖励宝箱：画面出现宝石/购买字样，停止敲宝箱")
            return False
        return bool(上下文.点击已确认安全按钮(*宝箱点击点, 延时=敲击间隔毫秒))

    # 1. 点宝箱，直到下方锤子计数降到 3
    计数 = None
    for 次 in range(最多敲击次数):
        if not 敲一下(f"敲{次 + 1}"):
            return False
        图像 = 截图()
        _保存截图(图像, f"敲{次 + 1}后")
        x1, y1, x2, y2 = 锤子计数OCR区域
        计数 = 读取锤子计数(_OCR(上下文, 图像[y1:y2, x1:x2]))
        if 计数 is not None and 计数 <= 目标计数:
            break
    else:
        置状态(f"奖励宝箱：敲了 {最多敲击次数} 次仍未读到锤子计数降到 {目标计数}（最后读数 {计数}），改走跳过动画")
        return False
    置状态(f"奖励宝箱：锤子计数 {计数}，继续敲 3 次后等待 3 秒")

    # 2. 再敲 3 次 → 等 3 秒 → 再敲 1 次
    for 次 in range(3):
        if not 敲一下(f"补敲{次 + 1}"):
            return False
    上下文.脚本延时(开箱等待毫秒)
    _保存截图(截图(), "等待后")
    if not 敲一下("收尾"):
        return False

    # 3. 确认回到主世界
    截止 = time.time() + 回主世界等待秒
    while time.time() < 截止:
        上下文.脚本延时(1000)
        识别 = getattr(上下文, "识别点击画面", None)
        try:
            结果 = 识别(强制=True) if callable(识别) else None
        except Exception:
            结果 = None
        if getattr(结果, "页面", "") == "主世界主页":
            置状态("奖励宝箱：已敲开宝箱并确认回到主世界")
            return True
    _保存截图(截图(), "未回主世界")
    置状态("奖励宝箱：敲完后未确认回到主世界，交给原有奖励流程继续处理")
    return False
