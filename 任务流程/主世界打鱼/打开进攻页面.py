from __future__ import annotations

import time

import cv2
import numpy as np

from 任务流程.基础任务框架 import 基础任务, 任务上下文
from 任务流程.检测游戏登录状态 import 检测游戏登录状态任务
from 任务流程.主世界打鱼.搜索页面识别 import 搜索页面识别器


class 打开进攻页面任务(基础任务):
    """从主世界进入敌方搜索页。

    这里不能再依赖固定的第三次坐标点击。MuMu/其他模拟器的实际画布
    可能是 1280×720，而任务坐标是 800×600；固定点会落在军队页的空白
    区域，随后搜索任务就会一直等待“下一个”按钮。改为从归一化画面中
    找右下角绿色“攻击!”按钮，并在点击后确认搜索页已经出现。
    """

    _参考宽度 = 800
    _参考高度 = 600


    def 执行(self) -> bool:
        上下文 = self.上下文
        上下文.置脚本状态("开始进攻,打开进攻页面")
        if not 上下文.点击(62, 546, 1000):
            上下文.置脚本状态("打开进攻页面失败：主世界进攻入口未点击")
            return False
        if not 上下文.点击(156, 426, 500):
            上下文.置脚本状态("打开进攻页面失败：军队入口未点击")
            return False
        return self._等待并点击攻击按钮(上下文)

    def _检测攻击按钮(self, 屏幕图像: np.ndarray) -> tuple[int, int] | None:
        """在 800×600 参考画布中找右下角绿色攻击按钮中心。"""
        if not isinstance(屏幕图像, np.ndarray) or 屏幕图像.size == 0:
            return None
        if len(屏幕图像.shape) != 3 or 屏幕图像.shape[2] < 3:
            return None

        图像高度, 图像宽度 = 屏幕图像.shape[:2]
        hsv = cv2.cvtColor(屏幕图像, cv2.COLOR_BGR2HSV)
        # 当前 CoC 的攻击按钮为高亮黄绿色；只看画面右下区域，避免把
        # 资源按钮、强化按钮或地图内容当成攻击按钮。
        x起点 = max(0, int(图像宽度 * 0.58))
        y起点 = max(0, int(图像高度 * 0.72))
        区域 = hsv[y起点:, x起点:]
        绿色遮罩 = cv2.inRange(
            区域,
            np.array([32, 55, 90], dtype=np.uint8),
            np.array([92, 255, 255], dtype=np.uint8),
        )
        核心 = np.ones((3, 3), dtype=np.uint8)
        绿色遮罩 = cv2.morphologyEx(绿色遮罩, cv2.MORPH_CLOSE, 核心, iterations=2)
        绿色遮罩 = cv2.morphologyEx(绿色遮罩, cv2.MORPH_OPEN, 核心, iterations=1)

        轮廓列表, _ = cv2.findContours(
            绿色遮罩, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        候选 = []
        for 轮廓 in 轮廓列表:
            x, y, 宽, 高 = cv2.boundingRect(轮廓)
            if 宽 < 图像宽度 * 0.12 or 高 < 图像高度 * 0.035:
                continue
            if 宽 / max(高, 1) < 2.0 or 宽 / max(高, 1) > 9.0:
                continue
            全局x = x + x起点
            全局y = y + y起点
            中心x = 全局x + 宽 // 2
            中心y = 全局y + 高 // 2
            # 攻击按钮应位于最下方；同时保留右侧限制，避免误识别地图。
            if 中心x < 图像宽度 * 0.68 or 中心y < 图像高度 * 0.79:
                continue
            候选.append((中心y, 宽 * 高, 中心x, 中心y))

        if not 候选:
            return None
        _, _, 中心x, 中心y = max(候选, key=lambda 项: (项[0], 项[1]))
        # 转回任务统一使用的 800×600 参考坐标。
        return (
            round(中心x * self._参考宽度 / 图像宽度),
            round(中心y * self._参考高度 / 图像高度),
        )

    def _是否出现下一个(self, 上下文: 任务上下文, 屏幕图像: np.ndarray) -> bool:
        try:
            命中, _, 依据, 分数 = 搜索页面识别器.查找下一个按钮(
                屏幕图像, self.模板识别
            )
            if 命中:
                self._最近搜索页识别依据 = 依据
                self._最近搜索页识别分数 = 分数
            return bool(命中)
        except Exception as 异常:
            上下文.置脚本状态(f"搜索页面识别失败：{异常}")
            return False

    def _等待并点击攻击按钮(self, 上下文: 任务上下文) -> bool:
        """点击动态攻击按钮，并确认已经切换到敌方搜索页面。"""
        截止时间 = time.monotonic() + 20.0
        已点击 = False
        断线恢复次数 = 0
        上次提示时间 = 0.0
        连续搜索页命中 = 0
        while time.monotonic() < 截止时间:
            try:
                屏幕图像 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            except Exception as 异常:
                上下文.置脚本状态(f"进入进攻页面截图失败：{异常}")
                上下文.脚本延时(500)
                continue

            # 断线弹窗会遮住军队页，但底层绿色按钮仍然可见；必须先
            # 处理弹窗，否则视觉检测会误把弹窗后的按钮当成可点击目标。
            断线弹窗, 断线按钮点 = 检测游戏登录状态任务._检测断线弹窗(屏幕图像)
            if 断线弹窗:
                断线恢复次数 += 1
                if 断线恢复次数 > 2:
                    上下文.置脚本状态(
                        "进攻入口连续两次检测到连接中断，停止点击并保留CoC前台"
                    )
                    return False
                上下文.置脚本状态(
                    f"进攻入口检测到连接中断，第{断线恢复次数}次尝试游戏内重新登入"
                )
                if not 上下文.点击已确认安全按钮(
                    断线按钮点[0], 断线按钮点[1], 延时=180
                ):
                    上下文.置脚本状态("连接中断恢复按钮点击失败，停止进攻入口")
                    return False
                已点击 = False
                上下文.脚本延时(5000)
                continue

            if self._是否出现下一个(上下文, 屏幕图像):
                连续搜索页命中 += 1
                if 连续搜索页命中 >= 2:
                    依据 = getattr(self, "_最近搜索页识别依据", "按钮区域")
                    分数 = getattr(self, "_最近搜索页识别分数", 0.0)
                    上下文.置脚本状态(
                        f"已确认进入敌方搜索页面：{依据}，评分{分数:.2f}"
                    )
                    return True
            else:
                连续搜索页命中 = 0

            if not 已点击:
                攻击点 = self._检测攻击按钮(屏幕图像)
                if 攻击点 is not None:
                    上下文.置脚本状态(
                        f"识别到军队配置页攻击按钮，动态点击{攻击点[0]},{攻击点[1]}"
                    )
                    if not 上下文.点击(
                        攻击点[0], 攻击点[1], 延时=700, 是否精确点击=True
                    ):
                        上下文.置脚本状态("攻击按钮点击被安全护栏拒绝")
                        return False
                    已点击 = True
                    continue

            当前时间 = time.monotonic()
            if 当前时间 - 上次提示时间 >= 3.0:
                上下文.置脚本状态(
                    "等待军队配置页攻击按钮或敌方搜索页面，避免误点击其他页面"
                )
                上次提示时间 = 当前时间
            上下文.脚本延时(350)

        上下文.置脚本状态("进入进攻页面失败：20秒内未确认敌方搜索页面")
        return False

