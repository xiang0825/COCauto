"""胜利之星奖励宝箱：回营后出现的敲宝箱页面。

实机流程（2026-11-24 rc135 截图校准）：
1. 点“回营”后出现宝箱页：宝箱在画面中央，下方一条深色底栏里有 4 根黄色擀面杖
   （用户说的“类似锤子”）；右下角有“跳過”。
2. 每敲一下宝箱，最左边一根黄色变暗。用户规则：黄色减少到 3 根 → 再敲 3 次 →
   等 3 秒 → 再点一次 → 确认回到主世界。
3. 宝箱打开后是奖励页（例如“4倍戰鬥糕點 / 物品已運送到臨時倉庫”），点中间没反应，
   “再点一次”要点下方绿色“繼續”按钮。

识别不到宝箱页、敲了没变化、找不到“繼續”或最后没回主世界时返回 False，
调用方照旧按原流程等待/待命。每一步都存截图到 ``数据集/奖励宝箱``。
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

宝箱点击点 = (390, 300)                 # 800×600 画面中央的宝箱
擀面杖区域 = (318, 478, 478, 530)        # 左, 上, 右, 下
擀面杖槽位x = (17, 52, 88, 123)          # 区域内 4 根擀面杖的左边界
槽位容差 = 6
底栏最大平均亮度 = 95                     # 底栏是深色半透明条
目标根数 = 3
最多敲击次数 = 8
敲击间隔毫秒 = 600
开箱等待毫秒 = 3000
继续按钮文字 = ("繼續", "继续")
继续按钮默认点 = (392, 513)
继续按钮等待秒 = 10.0
回主世界等待秒 = 15.0
危险文字 = (
    "寶石", "宝石", "購買", "购买", "商店", "立即完成",
    "充值", "儲值", "特惠", "禮包", "礼包",
    "gem", "gems", "shop", "buy", "store",
)


def 识别宝箱页(图像) -> int | None:
    """是宝箱页时返回剩余黄色擀面杖根数（1–4），否则 None。"""
    try:
        if 图像 is None or not hasattr(图像, "shape") or 图像.ndim != 3 or 图像.shape[2] < 3:
            return None
        if 图像.size == 0 or 图像.shape[0] < 300 or 图像.shape[1] < 400:
            return None
        if 图像.shape[1] != 800 or 图像.shape[0] != 600:
            图像 = cv2.resize(图像, (800, 600), interpolation=cv2.INTER_AREA)
        左, 上, 右, 下 = 擀面杖区域
        区域 = 图像[上:下, 左:右]
        if 区域.size == 0 or float(区域.mean()) > 底栏最大平均亮度:
            return None
        遮罩 = cv2.inRange(
            cv2.cvtColor(区域, cv2.COLOR_BGR2HSV),
            np.array([18, 120, 150], np.uint8), np.array([35, 255, 255], np.uint8),
        )
        轮廓, _ = cv2.findContours(遮罩, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    except (cv2.error, TypeError, AttributeError, IndexError, ValueError):
        return None
    命中槽位 = set()
    for 项 in 轮廓:
        if cv2.contourArea(项) < 25:
            continue
        x, _y, 宽, 高 = cv2.boundingRect(项)
        if not (12 <= 宽 <= 22 and 16 <= 高 <= 26):
            return None
        槽 = next((i for i, 槽x in enumerate(擀面杖槽位x) if abs(x - 槽x) <= 槽位容差), None)
        if 槽 is None:
            return None
        命中槽位.add(槽)
    if not 命中槽位:
        return None
    # 暗下去的总是左边的：剩下的必须是连续的右侧槽位
    if 命中槽位 != set(range(4 - len(命中槽位), 4)):
        return None
    return len(命中槽位)


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


def _停止已置位(上下文) -> bool:
    事件 = getattr(上下文, "停止事件", None)
    is_set = getattr(事件, "is_set", None)
    return bool(callable(is_set) and is_set())


def 定位继续按钮(OCR结果) -> tuple[int, int] | None:
    """在奖励页 OCR 结果里找“繼續”按钮中心；画面有宝石/购买/商店字样时不返回。"""
    有效项 = [
        项 for 项 in (OCR结果 or [])
        if isinstance(项, (list, tuple)) and len(项) >= 2
    ]
    if any(字 in str(项[1]).lower() for 项 in 有效项 for 字 in 危险文字):
        return None
    for 项 in 有效项:
        if any(字 in str(项[1]) for 字 in 继续按钮文字):
            try:
                点 = np.asarray(项[0], dtype=float)
                return int(点[:, 0].mean()), int(点[:, 1].mean())
            except (TypeError, ValueError, IndexError):
                return 继续按钮默认点
    return None


def 开启奖励宝箱(上下文, 等待出现秒: float = 0.0) -> bool:
    """敲开宝箱。``等待出现秒`` > 0 时先等宝箱页出现（领取奖励后有一段过场）。"""
    置状态 = getattr(上下文, "置脚本状态", lambda *_a, **_k: None)
    if _停止已置位(上下文):
        置状态("奖励宝箱：收到停止请求，取消开箱")
        return False
    if getattr(上下文, "_正在开启奖励宝箱", False):
        return False

    def 截图():
        try:
            return 上下文.op.获取屏幕图像cv(0, 0, 800, 600, 强制刷新=True)
        except TypeError:
            return 上下文.op.获取屏幕图像cv(0, 0, 800, 600)

    def 敲() -> bool:
        if _停止已置位(上下文):
            return False
        return bool(上下文.点击已确认安全按钮(*宝箱点击点, 延时=敲击间隔毫秒))

    上下文._正在开启奖励宝箱 = True
    try:
        截止 = time.time() + max(0.0, 等待出现秒)
        图像 = None
        根数 = None
        while True:
            if _停止已置位(上下文):
                return False
            图像 = 截图()
            if _停止已置位(上下文):
                return False
            根数 = 识别宝箱页(图像)
            if 根数 is not None or time.time() >= 截止:
                break
            上下文.脚本延时(500)
        if _停止已置位(上下文) or 根数 is None:
            return False
        _保存截图(图像, f"宝箱页_{根数}根")
        置状态(f"奖励宝箱：识别到宝箱页，黄色擀面杖 {根数} 根，开始敲宝箱")

        # 1. 敲到黄色擀面杖剩 3 根
        次数 = 0
        while 根数 is not None and 根数 > 目标根数:
            if _停止已置位(上下文):
                return False
            if 次数 >= 最多敲击次数:
                置状态(f"奖励宝箱：敲了 {次数} 次擀面杖仍是 {根数} 根，停止")
                return False
            if not 敲():
                return False
            if _停止已置位(上下文):
                return False
            次数 += 1
            图像 = 截图()
            if _停止已置位(上下文):
                return False
            新根数 = 识别宝箱页(图像)
            _保存截图(图像, f"敲{次数}后_{新根数}根")
            根数 = 新根数
        if _停止已置位(上下文):
            return False
        置状态(f"奖励宝箱：擀面杖剩 {根数 if 根数 is not None else '?'} 根，继续敲 3 次后等待 3 秒")

        # 2. 再敲 3 次 → 等 3 秒
        for _ in range(3):
            if _停止已置位(上下文) or not 敲():
                return False
        if _停止已置位(上下文):
            return False
        上下文.脚本延时(开箱等待毫秒)
        if _停止已置位(上下文):
            return False

        # 3. 再点一次：奖励页的“繼續”按钮（优先衔接上下文.清理宝箱领奖页，支持多张领奖页）
        清理领奖 = getattr(上下文, "清理宝箱领奖页", None)
        已通过清理领奖收起 = False
        截止 = time.time() + 继续按钮等待秒
        按钮 = None
        图像 = None
        while time.time() < 截止:
            if _停止已置位(上下文):
                return False
            图像 = 截图()
            if _停止已置位(上下文):
                return False
            if callable(清理领奖) and not getattr(上下文, "_宝石保护已触发", False):
                原页面恢复失败 = bool(getattr(上下文, "页面恢复失败", False))
                if 原页面恢复失败:
                    上下文.页面恢复失败 = False
                try:
                    if 清理领奖(图像):
                        已通过清理领奖收起 = True
                        break
                except Exception as 异常:
                    if 原页面恢复失败:
                        上下文.页面恢复失败 = True
                    置状态(f"奖励宝箱：宝箱领奖页安全清理异常，停止后续点击：{异常}")
                    return False
                新页面恢复失败 = bool(getattr(上下文, "页面恢复失败", False))
                if 原页面恢复失败 and not 新页面恢复失败:
                    上下文.页面恢复失败 = True
                if (
                    _停止已置位(上下文)
                    or 新页面恢复失败
                    or getattr(上下文, "_宝石保护已触发", False)
                ):
                    _保存截图(图像, "奖励页安全拦截")
                    return False
            OCR结果 = _OCR(上下文, 图像)
            if _停止已置位(上下文):
                return False
            按钮 = 定位继续按钮(OCR结果)
            if 按钮 is not None:
                宝石检测 = getattr(上下文, "_存在中央宝石危险模板", None)
                if callable(宝石检测):
                    宝石命中, 命中说明 = 宝石检测(图像)
                    if 宝石命中:
                        置状态(f"奖励宝箱：奖励页命中中央宝石危险模板（{命中说明}），禁止点击")
                        _保存截图(图像, "奖励页宝石拦截")
                        return False
                break
            if _停止已置位(上下文):
                return False
            上下文.脚本延时(800)
        if _停止已置位(上下文):
            return False
        if 图像 is not None:
            _保存截图(图像, "奖励页")
        if not 已通过清理领奖收起:
            if 按钮 is None:
                置状态("奖励宝箱：开箱后没找到“繼續”按钮，交给原流程处理")
                return False
            if _停止已置位(上下文):
                return False
            if not 上下文.点击已确认安全按钮(*按钮, 延时=800):
                return False
            if _停止已置位(上下文):
                return False

        if 已通过清理领奖收起:
            最近页 = str(getattr(getattr(上下文, "_最近点击页面结果", None), "页面", "") or "")
            if 最近页 == "主世界主页":
                置状态("奖励宝箱：已开箱、收起全部奖励页并确认回到主世界")
                return True
            if 最近页 in {"断线弹窗", "系统维护", "选择卡片弹窗", "升级详情弹窗", "战斗星级奖励", "多按钮弹窗"}:
                置状态(f"奖励宝箱：领奖页已收起，后续页面为{最近页}，交给主流程处理")
                return False

        # 4. 确认回到主世界（兼容多张连续宝箱领奖页）
        截止 = time.time() + 回主世界等待秒
        while time.time() < 截止:
            if _停止已置位(上下文):
                return False
            上下文.脚本延时(1000)
            if _停止已置位(上下文):
                return False
            识别 = getattr(上下文, "识别点击画面", None)
            try:
                结果 = 识别(强制=True) if callable(识别) else None
            except Exception:
                结果 = None
            if _停止已置位(上下文):
                return False
            页面名 = getattr(结果, "页面", "")
            if 页面名 == "主世界主页":
                置状态("奖励宝箱：已开箱、点击繼續并确认回到主世界")
                return True
            if (
                页面名 == "宝箱领奖页"
                and callable(清理领奖)
                and not getattr(上下文, "_宝石保护已触发", False)
            ):
                try:
                    if 清理领奖():
                        最近页 = str(getattr(getattr(上下文, "_最近点击页面结果", None), "页面", "") or "")
                        if 最近页 == "主世界主页":
                            置状态("奖励宝箱：已开箱、连续收起领奖页并确认回到主世界")
                            return True
                    else:
                        _保存截图(截图(), "连续领奖页未收起")
                        return False
                except Exception as 异常:
                    置状态(f"奖励宝箱：连续领奖页安全清理异常：{异常}")
                    return False
        if _停止已置位(上下文):
            return False
        _保存截图(截图(), "未回主世界")
        置状态("奖励宝箱：点击繼續后未确认回到主世界，交给原流程继续处理")
        return False
    finally:
        上下文._正在开启奖励宝箱 = False

