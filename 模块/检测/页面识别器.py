"""点击前后的轻量页面识别。

该模块只使用少量、限定区域的模板匹配，不做 OCR/YOLO，不在每次点击时
重复加载模型。调用方负责缓存截图和结果，使高频下兵仍然流畅。
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np

from 任务流程.世界跳转.世界识别器 import 世界识别器


@dataclass(frozen=True)
class 页面识别结果:
    页面: str
    世界: Optional[str]
    可信度: float
    依据: tuple[str, ...]

    def 摘要(self) -> str:
        依据 = "、".join(self.依据) if self.依据 else "无可靠页面特征"
        世界 = self.世界 or "未知"
        return f"页面={self.页面}，世界={世界}，置信度={self.可信度:.2f}，依据={依据}"


class 页面识别器:
    """用游戏内 UI 锚点区分主页、战斗和结算页。"""

    放弃战斗区域 = (0, 390, 190, 600)
    结算区域 = (0, 350, 800, 600)
    放弃战斗模板 = "放弃战斗4.bmp|放弃战斗3.bmp|放弃战斗2.bmp|放弃战斗1.bmp"
    结算模板 = "回营.bmp|回营3.bmp|回营1.bmp|回营2.bmp|回营_领取奖励.bmp"
    战斗阈值 = 0.88
    结算阈值 = 0.80

    def __init__(self, 模板识别):
        self.模板识别 = 模板识别
        self.世界识别 = 世界识别器(模板识别)

    @staticmethod
    def _裁剪(图像: np.ndarray, 区域: tuple[int, int, int, int]) -> np.ndarray:
        if not isinstance(图像, np.ndarray) or 图像.ndim < 2:
            return np.empty((0, 0, 3), dtype=np.uint8)
        高, 宽 = 图像.shape[:2]
        左, 上, 右, 下 = 区域
        左 = max(0, min(宽, 左))
        右 = max(左, min(宽, 右))
        上 = max(0, min(高, 上))
        下 = max(上, min(高, 下))
        return 图像[上:下, 左:右]

    def _最佳分数(self, 图像: np.ndarray, 模板路径: str) -> float:
        if 图像.size == 0:
            return 0.0
        路径列表 = 模板路径.split("|")
        评分接口 = getattr(self.模板识别, "执行最佳匹配", None)
        if callable(评分接口):
            try:
                # 先尝试最常见版本；只有分数接近有效阈值时才扫描
                # 备用图，避免每次点击无条件做 4~5 次匹配。
                结果 = 评分接口(图像, 路径列表[0])
                分数 = float(结果[0])
                if len(路径列表) > 1 and 0.78 <= 分数 < 0.92:
                    备用结果 = 评分接口(图像, "|".join(路径列表[1:]))
                    分数 = max(分数, float(备用结果[0]))
                return max(0.0, min(1.0, 分数))
            except Exception:
                return 0.0
        try:
            命中, _, _ = self.模板识别.执行匹配(图像, 路径列表[0], 0.80)
            if not 命中 and len(路径列表) > 1:
                命中, _, _ = self.模板识别.执行匹配(
                    图像, "|".join(路径列表[1:]), 0.80
                )
            return 1.0 if 命中 else 0.0
        except Exception:
            return 0.0

    def 识别(self, 屏幕图像: np.ndarray, 战斗中: bool = False) -> 页面识别结果:
        """识别当前页面；不确定时返回 ``页面=未知``，不触发任何输入。"""
        战斗分数 = self._最佳分数(
            self._裁剪(屏幕图像, self.放弃战斗区域),
            self.放弃战斗模板,
        )
        结算分数 = self._最佳分数(
            self._裁剪(屏幕图像, self.结算区域),
            self.结算模板,
        )

        if 结算分数 >= self.结算阈值:
            return 页面识别结果(
                页面="战斗结算",
                世界=None,
                可信度=结算分数,
                依据=(f"结算按钮{结算分数:.2f}",),
            )
        if 战斗分数 >= self.战斗阈值:
            return 页面识别结果(
                页面="战斗中",
                世界=None,
                可信度=战斗分数,
                依据=(f"放弃按钮{战斗分数:.2f}",),
            )

        # 战斗中不再额外匹配资源栏，避免高频下兵时多做三次大区域匹配；
        # 若战斗标记暂时不清晰，返回未知而不是猜测世界。
        if 战斗中:
            return 页面识别结果(
                页面="战斗过渡",
                世界=None,
                可信度=0.0,
                依据=(),
            )

        世界结果 = self.世界识别.识别(屏幕图像)
        if 世界结果.当前世界:
            return 页面识别结果(
                页面=f"{世界结果.当前世界}主页",
                世界=世界结果.当前世界,
                可信度=世界结果.主世界分数
                if 世界结果.当前世界 == "主世界"
                else 世界结果.夜世界分数,
                依据=世界结果.依据,
            )

        return 页面识别结果(
            页面="未知",
            世界=None,
            可信度=max(世界结果.主世界分数, 世界结果.夜世界分数),
            依据=世界结果.依据,
        )
