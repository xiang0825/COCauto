"""夜世界进攻关键步骤失败时保存现场帧，便于以后做回放样本。

只读当前截图并写入 ``数据集/待命现场/night_*.png``；不发送任何游戏输入，
达到上限后不再新增，也绝不删除已有截图。任何异常都只记日志，不影响
调用方的失败处理。
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

夜世界现场截图上限 = 50


def _清理文件名片段(文本: str) -> str:
    片段 = re.sub(r"[\\/:*?\"<>|\s]+", "_", str(文本 or "未知")).strip("_")
    return 片段[:40] or "未知"


def 保存夜世界现场截图(
    上下文,
    步骤: str,
    屏幕图像=None,
    *,
    截图目录=None,
    最大留图数: int = 夜世界现场截图上限,
) -> Optional[Path]:
    """保存当前帧到 night_<步骤>_<时间>.png，返回保存路径或 None。"""
    try:
        if getattr(上下文, "_内存保护已触发", False):
            return None
        if 屏幕图像 is None:
            取图 = getattr(getattr(上下文, "op", None), "获取屏幕图像cv", None)
            if callable(取图):
                try:
                    try:
                        屏幕图像 = 取图(0, 0, 800, 600, 强制刷新=True)
                    except TypeError:
                        屏幕图像 = 取图(0, 0, 800, 600)
                except Exception:
                    屏幕图像 = None
        if 屏幕图像 is None:
            屏幕图像 = getattr(上下文, "_点击识别截图", None)
        if 屏幕图像 is None or not hasattr(屏幕图像, "shape"):
            return None

        目录 = 截图目录 or getattr(上下文, "_夜世界现场截图目录", None)
        目标目录 = Path(目录) if 目录 else Path("数据集") / "待命现场"
        目标目录.mkdir(parents=True, exist_ok=True)
        上限 = max(1, int(最大留图数))
        if sum(1 for _ in 目标目录.glob("night_*.png")) >= 上限:
            _记录(上下文, f"夜世界现场截图已达上限{上限}张，本次不再保存（不会自动删除旧图）")
            return None

        import cv2

        编码成功, 数据 = cv2.imencode(".png", 屏幕图像)
        if not 编码成功:
            return None
        时间戳 = time.strftime("%Y%m%d_%H%M%S")
        毫秒 = int((time.time() % 1) * 1000)
        路径 = 目标目录 / f"night_{_清理文件名片段(步骤)}_{时间戳}_{毫秒:03d}.png"
        路径.write_bytes(数据.tobytes())
        _记录(上下文, f"夜世界{步骤}失败，已保存现场截图：{路径}")
        return 路径
    except Exception as 异常:
        _记录(上下文, f"夜世界现场截图保存失败（不影响后续处理）：{异常}")
        return None


def _记录(上下文, 文本: str) -> None:
    置状态 = getattr(上下文, "置脚本状态", None)
    if callable(置状态):
        try:
            置状态(文本)
        except Exception:
            pass
