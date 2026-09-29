"""敌方搜索页面的轻量识别。

CoC 国际服的界面语言可能是简体或繁体，同一个“下一個/下一个”按钮
不能只依赖一张文字模板。这里优先识别按钮的稳定颜色、尺寸和位置，
再用已有文字模板作为兼容兜底。整个识别过程只读截图，不发送输入。
"""

from __future__ import annotations

import cv2
import numpy as np


class 搜索页面识别器:
    """识别敌方搜索页右下角的“下一個/下一个”按钮。"""

    # 参考画布是 800×600；模板名称按繁体、简体和可能的旧资源命名顺序尝试。
    下一个模板 = (
        "下一個.bmp",
        "下一个.bmp",
        "下一個按钮.bmp",
        "下一个按钮.bmp",
    )
    模板最低相似度 = 0.60
    颜色最低可信分 = 0.70
    点击安全最左x = 672  # 800×600 参考画布；实机真按钮位于 x≈725

    @classmethod
    def 按钮证据可信(cls, 依据: str, 分数: float) -> bool:
        """入口和点击复核共用门槛，避免两处判定互相矛盾。"""
        if str(依据).startswith("模板"):
            return 分数 >= cls.模板最低相似度
        return 分数 >= cls.颜色最低可信分

    @staticmethod
    def _画面有效(屏幕图像: np.ndarray) -> bool:
        return (
            isinstance(屏幕图像, np.ndarray)
            and 屏幕图像.ndim == 3
            and 屏幕图像.shape[2] >= 3
            and 屏幕图像.size > 0
        )

    @classmethod
    def _按颜色查找(
        cls, 屏幕图像: np.ndarray
    ) -> tuple[bool, tuple[int, int], str, float]:
        """按按钮的高饱和颜色和矩形轮廓识别。

        搜索页按钮位于右下区域，当前繁体界面为橙黄色；部分版本/主题
        会显示绿色，因此同时保留绿色候选，但限制了高度和矩形比例，
        不会把军队页底部的“攻擊!”按钮当成搜索按钮。
        """

        高度, 宽度 = 屏幕图像.shape[:2]
        hsv = cv2.cvtColor(屏幕图像, cv2.COLOR_BGR2HSV)
        x起点 = max(0, int(宽度 * 0.64))
        y起点 = max(0, int(高度 * 0.52))
        y终点 = min(高度, int(高度 * 0.90))
        区域 = hsv[y起点:y终点, x起点:]
        if 区域.size == 0:
            return False, (0, 0), "无搜索按钮候选区域", 0.0

        # 橙黄色是当前国际服“下一個”按钮的主体颜色；绿色是部分
        # 版本的替代色。两者都要求较高饱和度，减少地图背景误检。
        颜色范围 = (
            ("橙黄色按钮", (0, 70, 100), (38, 255, 255)),
            ("绿色按钮", (35, 70, 90), (95, 255, 255)),
        )
        核心 = np.ones((3, 3), dtype=np.uint8)
        候选 = []

        for 颜色名称, 下限, 上限 in 颜色范围:
            遮罩 = cv2.inRange(
                区域,
                np.array(下限, dtype=np.uint8),
                np.array(上限, dtype=np.uint8),
            )
            遮罩 = cv2.morphologyEx(遮罩, cv2.MORPH_CLOSE, 核心, iterations=2)
            遮罩 = cv2.morphologyEx(遮罩, cv2.MORPH_OPEN, 核心, iterations=1)
            轮廓列表, _ = cv2.findContours(
                遮罩, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            for 轮廓 in 轮廓列表:
                x, y, 宽, 高 = cv2.boundingRect(轮廓)
                全局x = x + x起点
                全局y = y + y起点
                中心x = 全局x + 宽 / 2
                中心y = 全局y + 高 / 2
                填充率 = cv2.contourArea(轮廓) / max(1.0, float(宽 * 高))
                长宽比 = 宽 / max(1.0, float(高))

                # 当前实机按钮约为 x=664..793、y=389..466（800×600
                # 参考画布）。放宽边界以兼容不同分辨率/主题，但保留
                # 右下位置和矩形形状，排除军队卡牌及底部攻击按钮。
                if 宽 < 宽度 * 0.10 or 高 < 高度 * 0.045:
                    continue
                if not 1.35 <= 长宽比 <= 4.8:
                    continue
                if 中心x < 宽度 * 0.74:
                    continue
                if not 高度 * 0.56 <= 中心y <= 高度 * 0.84:
                    continue
                if 填充率 < 0.30:
                    continue

                评分 = min(1.0, 填充率) * min(1.0, 宽 / (宽度 * 0.16))
                候选.append((评分, int(round(中心x)), int(round(中心y)), 颜色名称))

        if not 候选:
            return False, (0, 0), "未找到右下角搜索按钮颜色区域", 0.0

        评分, 中心x, 中心y, 颜色名称 = max(候选, key=lambda 项: 项[0])
        return True, (中心x, 中心y), 颜色名称, float(评分)

    @classmethod
    def _按模板查找(
        cls, 屏幕图像: np.ndarray, 模板识别器
    ) -> tuple[bool, tuple[int, int], str, float]:
        if 模板识别器 is None:
            return False, (0, 0), "未提供模板识别器", 0.0

        最佳匹配 = getattr(模板识别器, "执行最佳匹配", None)
        if not callable(最佳匹配):
            return False, (0, 0), "模板识别器不支持评分接口", 0.0

        高度, 宽度 = 屏幕图像.shape[:2]
        for 模板路径 in cls.下一个模板:
            try:
                分数, 中心, 实际模板 = 最佳匹配(屏幕图像, 模板路径)
                分数 = float(分数)
                中心x, 中心y = int(中心[0]), int(中心[1])
            except Exception:
                continue

            # 文字模板可能因繁简字体不同而分数降低；位置仍必须落在
            # 搜索按钮区域，避免把主世界文字的偶然相似当成搜索页。
            if 分数 < cls.模板最低相似度:
                continue
            if 中心x < 宽度 * 0.68:
                continue
            if not 高度 * 0.50 <= 中心y <= 高度 * 0.86:
                continue
            名称 = 实际模板 or 模板路径
            return True, (中心x, 中心y), f"模板{名称}", 分数

        return False, (0, 0), "搜索按钮模板未命中", 0.0

    @classmethod
    def 查找下一个按钮(
        cls, 屏幕图像: np.ndarray, 模板识别器=None
    ) -> tuple[bool, tuple[int, int], str, float]:
        """返回 ``(是否命中, 按钮中心, 识别依据, 分数)``。"""

        if not cls._画面有效(屏幕图像):
            return False, (0, 0), "搜索页截图无效", 0.0

        # 颜色/轮廓对繁简字体、缩放和抗锯齿不敏感，优先使用。
        颜色结果 = cls._按颜色查找(屏幕图像)
        if 颜色结果[0] and cls.按钮证据可信(颜色结果[2], 颜色结果[3]):
            return 颜色结果

        # 低分绿色地图可能遮住真正的文字模板，先尝试模板；若模板
        # 也未命中，仍把弱颜色候选交给入口状态机等待，绝不直接点击。
        模板结果 = cls._按模板查找(屏幕图像, 模板识别器)
        if 模板结果[0]:
            return 模板结果
        return 颜色结果 if 颜色结果[0] else 模板结果
