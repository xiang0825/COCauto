"""点击前后的轻量页面识别。

该模块只使用少量、限定区域的模板匹配，不做 OCR/YOLO，不在每次点击时
重复加载模型。调用方负责缓存截图和结果，使高频下兵仍然流畅。
"""

from dataclasses import dataclass
import time
from typing import Optional

import cv2
import numpy as np

_奖励候选单调时间 = time.monotonic

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
    # 测试服/活动战斗进行中也会显示“选择一项奖励！”横幅，
    # 倒计时与左下角按钮仍可见。不能因此放行普通下兵点击，
    # 否则可能误触覆盖在地图上的奖励卡片。
    奖励选择页阈值 = 0.90
    奖励选择确认间隔秒 = 0.50
    奖励选择确认最大间隔秒 = 10.0
    奖励候选挂起最长秒 = 3.0

    def __init__(self, 模板识别):
        self.模板识别 = 模板识别
        self.世界识别 = 世界识别器(模板识别)
        self._奖励选择候选时间 = None
        self._奖励选择候选帧 = None
        self._奖励候选开始时间 = None

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

    @staticmethod
    def 定位主世界战斗模式普通按钮(图像: np.ndarray) -> tuple[int, int] | None:
        """只在“普通战斗橙色按钮 + 排位蓝色按钮”同时出现时确认模式页。

        CoC 新版会在重启后保留多人游戏选择层。单独的橙色块可能是
        主世界装饰或别的按钮，因此两侧 CTA 必须同时落在对应卡片和同一
        高度带内；返回的坐标只指向左侧普通对战，不会触碰排位报名。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim != 3 or 图像.shape[2] < 3:
            return None
        if 图像.size == 0:
            return None
        try:
            if 图像.shape[1] != 800 or 图像.shape[0] != 600:
                图像 = cv2.resize(图像, (800, 600), interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)

            def 最大按钮(遮罩, 区域, x范围):
                左, 上, 右, 下 = 区域
                区域遮罩 = 遮罩[上:下, 左:右]
                轮廓列表, _ = cv2.findContours(
                    区域遮罩, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                )
                候选 = []
                for 轮廓 in 轮廓列表:
                    x, y, 宽, 高 = cv2.boundingRect(轮廓)
                    中心x = 左 + x + 宽 // 2
                    中心y = 上 + y + 高 // 2
                    if not (x范围[0] <= 中心x <= x范围[1]):
                        continue
                    if not (390 <= 中心y <= 495):
                        continue
                    if not (115 <= 宽 <= 225 and 38 <= 高 <= 96):
                        continue
                    if not (1.8 <= 宽 / max(1, 高) <= 5.0):
                        continue
                    密度 = float(np.count_nonzero(区域遮罩[y:y + 高, x:x + 宽])) / max(1, 宽 * 高)
                    if 密度 < 0.36:
                        continue
                    候选.append((宽 * 高, 中心x, 中心y))
                return max(候选, default=None)

            橙色 = cv2.inRange(
                hsv,
                np.array([6, 105, 130], dtype=np.uint8),
                np.array([40, 255, 255], dtype=np.uint8),
            )
            蓝色 = cv2.inRange(
                hsv,
                np.array([82, 80, 115], dtype=np.uint8),
                np.array([135, 255, 255], dtype=np.uint8),
            )
            核心 = np.ones((3, 3), dtype=np.uint8)
            橙色 = cv2.morphologyEx(橙色, cv2.MORPH_CLOSE, 核心, iterations=2)
            蓝色 = cv2.morphologyEx(蓝色, cv2.MORPH_CLOSE, 核心, iterations=2)
            左按钮 = 最大按钮(橙色, (30, 375, 265, 510), (45, 245))
            右按钮 = 最大按钮(蓝色, (255, 375, 565, 510), (270, 550))
            if 左按钮 is None or 右按钮 is None:
                return None
            _, 左x, 左y = 左按钮
            _, 右x, 右y = 右按钮
            if abs(左y - 右y) > 22:
                return None
            if not 0.55 <= 右按钮[0] / max(1, 左按钮[0]) <= 1.80:
                # 面积允许略有差异，但不应是地图中的微小蓝/橙色装饰。
                return None
            return 左x, 左y
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def _系统维护分数(self, 图像: np.ndarray) -> float:
        """识别维护页的顶部警示带与中央维护弹窗组合。

        维护页会在中间保留一个深色弹窗，旧规则容易把它误判成断线弹窗，
        随后重复点击“再试一次”。顶部警示带单独出现也可能来自战斗 HUD；
        因此还要求中央弹窗同时具有标题、正文和操作区，不扫描地图按钮。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim < 2 or 图像.size == 0:
            return 0.0
        try:
            高, 宽 = 图像.shape[:2]
            顶部 = 图像[:max(1, int(高 * 0.12))]
            hsv = cv2.cvtColor(顶部, cv2.COLOR_BGR2HSV)
            黄色 = (
                (hsv[:, :, 0] >= 18)
                & (hsv[:, :, 0] <= 40)
                & (hsv[:, :, 1] >= 100)
                & (hsv[:, :, 2] >= 120)
            )
            行覆盖率 = 黄色.mean(axis=1)
            有效行数 = int(np.count_nonzero(行覆盖率 >= 0.55))
            # 维护横幅在 1280×720 原图约 20 行，在 800×600 逻辑图约
            # 17 行；要求连续横幅覆盖顶部约五分之一即可，避免因缩放
            # 插值把横幅压薄后漏检。
            if 有效行数 >= max(4, int(顶部.shape[0] * 0.18)):
                if self._断线弹窗分数(图像) >= 0.90:
                    return 0.98
        except (AttributeError, TypeError, ValueError, cv2.error):
            return 0.0
        return 0.0

    @staticmethod
    def 定位军队配置页攻击按钮(图像: np.ndarray) -> tuple[int, int] | None:
        """识别军队配置页右下的攻击按钮，供页面识别与任务流程共用。"""
        if not isinstance(图像, np.ndarray) or 图像.ndim != 3 or 图像.shape[2] < 3:
            return None
        if 图像.size == 0:
            return None
        参考宽度, 参考高度 = 800, 600
        if 图像.shape[1] != 参考宽度 or 图像.shape[0] != 参考高度:
            try:
                图像 = cv2.resize(图像, (参考宽度, 参考高度), interpolation=cv2.INTER_AREA)
            except (AttributeError, TypeError, ValueError, cv2.error):
                return None

        图像高度, 图像宽度 = 图像.shape[:2]
        hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
        面板 = hsv[
            int(图像高度 * 0.13):int(图像高度 * 0.88),
            int(图像宽度 * 0.12):int(图像宽度 * 0.88),
        ]
        浅色面板比例 = float(
            ((面板[:, :, 1] <= 130) & (面板[:, :, 2] >= 130)).mean()
        ) if 面板.size else 0.0
        棕色配置面板比例 = float(
            (
                (面板[:, :, 0] <= 30)
                & (面板[:, :, 1] >= 50)
                & (面板[:, :, 2] >= 60)
            ).mean()
        ) if 面板.size else 0.0
        if 浅色面板比例 < 0.35 and 棕色配置面板比例 < 0.35:
            return None

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
            全局x, 全局y = x + x起点, y + y起点
            中心x, 中心y = 全局x + 宽 // 2, 全局y + 高 // 2
            if 中心x < 图像宽度 * 0.68 or 中心y < 图像高度 * 0.79:
                continue
            候选.append((中心y, 宽 * 高, 中心x, 中心y))

        if not 候选:
            return None
        _, _, 中心x, 中心y = max(候选, key=lambda 项: (项[0], 项[1]))
        return (
            round(中心x * 参考宽度 / 图像宽度),
            round(中心y * 参考高度 / 图像高度),
        )

    def _最佳分数(self, 图像: np.ndarray, 模板路径: str) -> float:
        if 图像.size == 0:
            return 0.0
        路径列表 = 模板路径.split("|")
        评分接口 = getattr(self.模板识别, "执行最佳匹配", None)
        if callable(评分接口):
            try:
                # 先尝试最常见版本；只有分数已经足够高时才跳过备用图。
                # 旧逻辑只在 0.78..0.92 之间扫描备用图，导致实际命中
                # 第3/4个版本而第1个版本分数偏低时永远返回低分。
                结果 = 评分接口(图像, 路径列表[0])
                分数 = float(结果[0])
                if len(路径列表) > 1 and 分数 < 0.92:
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

    def _红色放弃按钮分数(self, 图像: np.ndarray) -> float:
        """用按钮的颜色和几何形状兜底识别战斗页。

        不同 CoC 版本的“放弃”文字模板变化很大，但左下角红色横向
        按钮位置稳定。只看该区域上方的横向红色连通块，避免把兵栏
        卡牌边框或地图装饰误判成战斗按钮。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim < 2 or 图像.size == 0:
            return 0.0
        try:
            高, 宽 = 图像.shape[:2]
            # ADB 截图可能是 800x600、1280x720 等尺寸。这里不能沿用
            # 800x600 的固定 y=390..600，否则 1280x720 的放弃按钮会被
            # 截在区域外，随后倒计时/红色地图元素就可能触发错误页面判断。
            左 = 0
            右 = max(1, int(宽 * 0.22))
            上 = int(高 * 0.67)
            下 = 高
            区域 = 图像[上:下, 左:右]
            if 区域.size == 0:
                return 0.0
            # 新版 16:9 战斗界面的左下红色按钮更靠下；扩大上方扫描高度
            # 覆盖其 y≈78%..85% 区间，同时仍排除贴近底边的兵栏。
            上方高度 = min(max(1, int(高 * 0.22)), 区域.shape[0])
            上方 = 区域[:上方高度]
            hsv = cv2.cvtColor(上方, cv2.COLOR_BGR2HSV)
            色相 = hsv[:, :, 0]
            掩码 = (
                ((色相 <= 12) | (色相 >= 170))
                & (hsv[:, :, 1] >= 90)
                & (hsv[:, :, 2] >= 80)
            ).astype(np.uint8)
            _, _, 统计, _ = cv2.connectedComponentsWithStats(掩码, 8)
            区域宽度 = 上方.shape[1]
            for x, y, 宽, 高, 面积 in 统计[1:]:
                if (
                    面积 >= 600
                    and 宽 >= max(55, int(区域宽度 * 0.28))
                    # 新版联赛概况页有大面积红色内容面板，会横跨整个
                    # 左下角裁剪区；不能把这块背景当成战斗中的放弃按钮。
                    # 实机放弃按钮仍明显窄于裁剪区宽度的82%。
                    and 宽 <= max(55, int(区域宽度 * 0.82))
                    and 高 >= 20
                    and 宽 / max(1, 高) >= 1.5
                    and x <= max(40, int(区域宽度 * 0.25))
                    and y <= int(上方.shape[0] * 0.75)
                ):
                    return 0.93
        except Exception:
            return 0.0
        return 0.0

    @staticmethod
    def 定位联赛概况关闭按钮(图像: np.ndarray) -> tuple[int, int] | None:
        """识别新版联赛概况面板，返回顶部右侧关闭 X。"""
        if not isinstance(图像, np.ndarray) or 图像.ndim != 3 or 图像.size == 0:
            return None
        try:
            原高, 原宽 = 图像.shape[:2]
            if 原高 < 300 or 原宽 < 400:
                return None
            if (原宽, 原高) != (800, 600):
                参考图 = cv2.resize(图像, (800, 600), interpolation=cv2.INTER_AREA)
            else:
                参考图 = 图像
            hsv = cv2.cvtColor(参考图, cv2.COLOR_BGR2HSV)
            红色 = (
                ((hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 170))
                & (hsv[:, :, 1] >= 90)
                & (hsv[:, :, 2] >= 80)
            ).astype(np.uint8)

            # 联赛页面主体是占据画面下半部的大型红色内容板；战场的
            # 红色地图/按钮不会在这一区域形成同等覆盖率。
            主体 = 红色[int(600 * 0.36):int(600 * 0.95), int(800 * 0.03):int(800 * 0.97)]
            if 主体.size == 0 or float(np.mean(主体)) < 0.40:
                return None

            # 面板顶部有三块浅色分页标签，分别复核，避免仅凭红色背景
            # 将结算或其它红色活动面板误当成联赛页。
            中性浅色 = (hsv[:, :, 1] < 120) & (hsv[:, :, 2] > 130)
            分页区域 = ((0.10, 0.37), (0.38, 0.62), (0.63, 0.90))
            for 左比例, 右比例 in 分页区域:
                区域 = 中性浅色[
                    int(600 * 0.10):int(600 * 0.22),
                    int(800 * 左比例):int(800 * 右比例),
                ]
                if 区域.size == 0 or float(np.mean(区域)) < 0.55:
                    return None

            # 只取最右上角红色 X 的连通区域；它是安全关闭目标，返回
            # 点按原始截图尺寸缩放，调用方仍须双帧确认页面后才能点击。
            x0, x1 = int(800 * 0.94), int(800 * 0.99)
            y0, y1 = int(600 * 0.04), int(600 * 0.18)
            _, _, 统计, 重心 = cv2.connectedComponentsWithStats(
                红色[y0:y1, x0:x1], 8
            )
            候选 = []
            for 索引 in range(1, len(统计)):
                x, y, 宽, 高, 面积 = 统计[索引]
                cx, cy = 重心[索引]
                if (
                    面积 >= 120
                    and 宽 >= 16
                    and 高 >= 20
                    and x0 + cx >= 800 * 0.945
                ):
                    候选.append((int(面积), x0 + cx, y0 + cy))
            if not 候选:
                return None
            _, 中心x, 中心y = max(候选)
            return (
                int(round(中心x * 原宽 / 800)),
                int(round(中心y * 原高 / 600)),
            )
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def _奖励卡片结构数量(self, 图像: np.ndarray) -> int:
        """统计奖励弹窗中央的竖向卡片，过滤普通页面的红色物体误报。"""
        if not isinstance(图像, np.ndarray) or 图像.ndim < 2 or 图像.size == 0:
            return 0
        try:
            高, 宽 = 图像.shape[:2]
            灰度 = cv2.cvtColor(图像, cv2.COLOR_BGR2GRAY)
            边缘 = cv2.Canny(灰度, 80, 180)
            _, _, 统计, _ = cv2.connectedComponentsWithStats(
                (边缘 > 0).astype(np.uint8), 8
            )
            最小面积 = max(250, int(宽 * 高 * 0.0008))
            最小宽度 = max(80, int(宽 * 0.10))
            最小高度 = max(160, int(高 * 0.28))
            中心x列表 = []
            for x, y, 连通宽, 连通高, 面积 in 统计[1:]:
                if not (
                    面积 >= 最小面积
                    and 连通宽 >= 最小宽度
                    and 连通高 >= 最小高度
                    and 0.30 <= 连通宽 / max(1, 连通高) <= 0.85
                    and int(高 * 0.18) <= y <= int(高 * 0.50)
                    and int(宽 * 0.12) <= x <= int(宽 * 0.88)
                ):
                    continue
                # 同一张卡片的内外边框可能被分成两个连通块，只计一个。
                中心x列表.append(int(x + 连通宽 / 2))
            中心x列表.sort()
            去重中心x = []
            最小卡间距 = max(40, int(宽 * 0.08))
            for 中心x in 中心x列表:
                if not 去重中心x or 中心x - 去重中心x[-1] >= 最小卡间距:
                    去重中心x.append(中心x)
            return len(去重中心x)
        except Exception:
            return 0

    def _选择卡片弹窗关闭点(self, 图像: np.ndarray) -> tuple[int, int] | None:
        """识别覆盖主页的兵种/活动卡片弹窗右上角关闭按钮。

        测试服会弹出“超级部队”卡片页：底层主世界 HUD 仍然可见，
        但中央有多张横向排列的红色卡片，右上角有一个红色 X。旧版
        页面识别只看 HUD，因此会把这张弹窗误判成主世界，资源 OCR
        读到边缘残留数字后继续执行任务。这里仅使用卡片排列、关闭
        按钮几何和白色 X 三重证据定位，不调用 OCR，也不授权任何
        购买/确认按钮。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim != 3 or 图像.size == 0:
            return None
        try:
            高, 宽 = 图像.shape[:2]
            if 高 < 300 or 宽 < 500:
                return None
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
            色相 = hsv[:, :, 0]
            红色 = (
                ((色相 <= 12) | (色相 >= 170))
                & (hsv[:, :, 1] >= 90)
                & (hsv[:, :, 2] >= 80)
            ).astype(np.uint8)

            # 真实选择卡片在画面中央成一排；战斗兵栏则位于底部。
            # 旧版扫描到 96% 高度，把兵栏和地图红色建筑当成卡片，
            # 即使战斗倒计时还在，也持续误报弹窗并禁止下兵。
            左 = int(宽 * 0.08)
            右 = int(宽 * 0.92)
            上 = int(高 * 0.28)
            下 = int(高 * 0.65)
            卡片区 = cv2.morphologyEx(
                红色[上:下, 左:右],
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)),
            )
            _, _, 统计, _ = cv2.connectedComponentsWithStats(卡片区, 8)
            卡片候选 = []
            for x, y, 方宽, 方高, 面积 in 统计[1:]:
                if not (
                    面积 >= max(900, int(宽 * 高 * 0.0012))
                    and 方宽 >= int(宽 * 0.10)
                    and 方高 >= int(高 * 0.06)
                    and x + 方宽 >= int(宽 * 0.10) - 左
                    and x <= int(宽 * 0.90) - 左
                ):
                    continue
                卡片候选.append((int(左 + x + 方宽 / 2), int(上 + y)))
            最小间距 = max(45, int(宽 * 0.08))
            # 卡片顶部应大致同高，不能把分散的红色建筑拼成一排。
            存在卡片排 = False
            for _, 基准上沿 in 卡片候选:
                对齐中心 = sorted(
                    中心x for 中心x, 上沿 in 卡片候选
                    if abs(上沿 - 基准上沿) <= int(高 * 0.08)
                )
                去重中心 = []
                for 中心x in 对齐中心:
                    if not 去重中心 or 中心x - 去重中心[-1] >= 最小间距:
                        去重中心.append(中心x)
                if len(去重中心) >= 3:
                    存在卡片排 = True
                    break
            if not 存在卡片排:
                return None

            # 右上角关闭按钮必须是独立红色方块，并且内部有明显白色 X。
            顶部左 = int(宽 * 0.76)
            顶部下 = int(高 * 0.22)
            顶部红色 = 红色[:顶部下, 顶部左:]
            _, _, 顶部统计, _ = cv2.connectedComponentsWithStats(顶部红色, 8)
            灰度 = cv2.cvtColor(图像, cv2.COLOR_BGR2GRAY)
            for x, y, 方宽, 方高, 面积 in 顶部统计[1:]:
                中心x = 顶部左 + x + 方宽 / 2
                中心y = y + 方高 / 2
                if not (
                    宽 * 0.80 <= 中心x <= 宽 * 0.98
                    and 高 * 0.02 <= 中心y <= 高 * 0.20
                    and 宽 * 0.025 <= 方宽 <= 宽 * 0.10
                    and 高 * 0.035 <= 方高 <= 高 * 0.16
                    and 面积 >= 方宽 * 方高 * 0.20
                ):
                    continue
                左x = max(0, 顶部左 + x)
                上y = max(0, y)
                右x = min(宽, 左x + 方宽)
                下y = min(高, 上y + 方高)
                白色X = (
                    (hsv[上y:下y, 左x:右x, 1] < 110)
                    & (灰度[上y:下y, 左x:右x] > 175)
                )
                if int(np.count_nonzero(白色X)) >= max(10, int(方宽 * 方高 * 0.02)):
                    return (int(round(中心x)), int(round(中心y)))
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None
        return None

    def _选择卡片弹窗分数(self, 图像: np.ndarray) -> float:
        """返回覆盖式卡片弹窗的页级置信度。"""
        return 0.97 if self._选择卡片弹窗关闭点(图像) is not None else 0.0

    def 定位选择卡片弹窗关闭按钮(self, 图像: np.ndarray):
        """仅在已确认卡片弹窗时返回右上角关闭点。"""
        return self._选择卡片弹窗关闭点(图像)

    @staticmethod
    def _查找顶部红色关闭X(
        图像: np.ndarray,
        hsv: np.ndarray,
        *,
        x最小比例: float = 0.80,
        x最大比例: float = 0.95,
        y最小比例: float = 0.02,
        y最大比例: float = 0.16,
    ) -> tuple[int, int] | None:
        """定位弹窗右上角带白色 X 的红色关闭按钮。"""
        高, 宽 = 图像.shape[:2]
        色相 = hsv[:, :, 0]
        红色 = (
            ((色相 <= 15) | (色相 >= 165))
            & (hsv[:, :, 1] >= 100)
            & (hsv[:, :, 2] >= 100)
        ).astype(np.uint8)
        x起点 = max(0, int(宽 * (x最小比例 - 0.03)))
        x终点 = min(宽, int(宽 * (x最大比例 + 0.03)))
        y终点 = min(高, int(高 * (y最大比例 + 0.05)))
        区域 = cv2.morphologyEx(
            红色[:y终点, x起点:x终点],
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        )
        if 区域.size == 0:
            return None
        _, _, 统计, 重心 = cv2.connectedComponentsWithStats(区域, 8)
        灰度 = cv2.cvtColor(图像, cv2.COLOR_BGR2GRAY)
        候选 = []
        for 序号 in range(1, len(统计)):
            x, y, 方宽, 方高, 面积 = [int(值) for 值 in 统计[序号]]
            中心x, 中心y = [float(值) for 值 in 重心[序号]]
            全局中心x = 中心x + x起点
            全局中心y = 中心y
            if not (
                宽 * x最小比例 <= 全局中心x <= 宽 * x最大比例
                and 高 * y最小比例 <= 全局中心y <= 高 * y最大比例
                and 宽 * 0.025 <= 方宽 <= 宽 * 0.10
                and 高 * 0.035 <= 方高 <= 高 * 0.16
                and 面积 >= max(12, int(方宽 * 方高 * 0.20))
            ):
                continue
            左x = max(0, x起点 + x)
            上y = max(0, y)
            右x = min(宽, 左x + 方宽)
            下y = min(高, 上y + 方高)
            白色X = (
                (hsv[上y:下y, 左x:右x, 1] < 110)
                & (灰度[上y:下y, 左x:右x] > 175)
            )
            if int(np.count_nonzero(白色X)) < max(10, int(方宽 * 方高 * 0.02)):
                continue
            候选.append((面积, 全局中心x, 全局中心y))
        if not 候选:
            return None
        _, 中心x, 中心y = max(候选, key=lambda 项: 项[0])
        return int(round(中心x)), int(round(中心y))

    @staticmethod
    def _存在部落竞赛详情框(hsv: np.ndarray, 宽: int, 高: int) -> bool:
        """检测部落竞赛面板中展开的任务详情金色外框 + 浅色内底。"""
        左 = int(宽 * 0.15)
        上 = int(高 * 0.15)
        右 = int(宽 * 0.875)
        下 = int(高 * 0.80)
        区域 = hsv[上:下, 左:右]
        if 区域.size == 0:
            return False
        金色框 = (
            (区域[:, :, 0] >= 14)
            & (区域[:, :, 0] <= 34)
            & (区域[:, :, 1] >= 75)
            & (区域[:, :, 2] >= 120)
        ).astype(np.uint8)
        金色框 = cv2.morphologyEx(
            金色框,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
        )
        _, _, 统计, _ = cv2.connectedComponentsWithStats(金色框, 8)
        最小面积 = max(2000, int(宽 * 高 * 0.012))
        for 序号 in range(1, len(统计)):
            x, y, 方宽, 方高, 面积 = [int(值) for 值 in 统计[序号]]
            if not (
                宽 * 0.23 <= 方宽 <= 宽 * 0.45
                and 高 * 0.28 <= 方高 <= 高 * 0.65
                and 面积 >= 最小面积
            ):
                continue
            内区 = 区域[
                y + int(方高 * 0.15):y + int(方高 * 0.85),
                x + int(方宽 * 0.10):x + int(方宽 * 0.90),
            ]
            if 内区.size == 0:
                continue
            浅色比例 = float(np.mean((内区[:, :, 1] <= 35) & (内区[:, :, 2] >= 205)))
            if 浅色比例 >= 0.35:
                return True
        return False

    def _检测部落竞赛面板状态(
        self, 图像: np.ndarray
    ) -> tuple[str, tuple[int, int]] | None:
        """识别部落竞赛主面板与任务详情弹窗，防止误判为升级详情弹窗。"""
        if not isinstance(图像, np.ndarray) or 图像.ndim != 3 or 图像.size == 0:
            return None
        try:
            高, 宽 = 图像.shape[:2]
            if 高 < 120 or 宽 < 240:
                return None
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
            旗帜区 = hsv[
                int(高 * 0.025):int(高 * 0.292),
                int(宽 * 0.106):int(宽 * 0.275),
            ]
            进度条区 = hsv[
                int(高 * 0.742):int(高 * 0.900),
                int(宽 * 0.275):int(宽 * 0.900),
            ]
            卡片白底区 = hsv[
                int(高 * 0.158):int(高 * 0.733),
                int(宽 * 0.275):int(宽 * 0.888),
            ]
            if 旗帜区.size == 0 or 进度条区.size == 0 or 卡片白底区.size == 0:
                return None
            蓝旗比例 = float(np.mean(
                (旗帜区[:, :, 0] >= 95)
                & (旗帜区[:, :, 0] <= 130)
                & (旗帜区[:, :, 1] >= 120)
                & (旗帜区[:, :, 2] >= 110)
            ))
            蓝条比例 = float(np.mean(
                (进度条区[:, :, 0] >= 95)
                & (进度条区[:, :, 0] <= 130)
                & (进度条区[:, :, 1] >= 100)
                & (进度条区[:, :, 2] >= 100)
            ))
            白卡比例 = float(np.mean(
                (卡片白底区[:, :, 1] <= 35) & (卡片白底区[:, :, 2] >= 205)
            ))
            if 蓝旗比例 < 0.35 or 蓝条比例 < 0.22 or 白卡比例 < 0.25:
                return None
            关闭点 = self._查找顶部红色关闭X(
                图像, hsv, x最小比例=0.82, x最大比例=0.95, y最小比例=0.02, y最大比例=0.16
            )
            if 关闭点 is None:
                return None
            页面 = (
                "部落竞赛任务详情"
                if self._存在部落竞赛详情框(hsv, 宽, 高)
                else "部落竞赛面板"
            )
            return 页面, 关闭点
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def 定位部落竞赛关闭按钮(self, 图像: np.ndarray) -> tuple[int, int] | None:
        """仅在已确认部落竞赛面板或任务详情时返回右上角关闭点。"""
        结果 = self._检测部落竞赛面板状态(图像)
        return 结果[1] if 结果 is not None else None

    def _检测活动弹窗关闭点(self, 图像: np.ndarray) -> tuple[int, int] | None:
        """识别主世界活动列表/活动弹窗，避免白亮活动内容+红X误触发升级详情。"""
        if not isinstance(图像, np.ndarray) or 图像.ndim != 3 or 图像.size == 0:
            return None
        if self._检测部落竞赛面板状态(图像) is not None:
            return None
        try:
            高, 宽 = 图像.shape[:2]
            if 高 < 120 or 宽 < 240:
                return None
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
            关闭点 = self._查找顶部红色关闭X(
                图像, hsv, x最小比例=0.78, x最大比例=0.87, y最小比例=0.02, y最大比例=0.16
            )
            if 关闭点 is None:
                return None
            左暗区 = hsv[int(高 * 0.18):int(高 * 0.85), :int(宽 * 0.14), 2]
            右暗区 = hsv[int(高 * 0.18):int(高 * 0.85), int(宽 * 0.86):, 2]
            中间面板 = hsv[int(高 * 0.15):int(高 * 0.88), int(宽 * 0.17):int(宽 * 0.83), 2]
            if 左暗区.size == 0 or 右暗区.size == 0 or 中间面板.size == 0:
                return None
            左暗均亮 = float(np.mean(左暗区))
            右暗均亮 = float(np.mean(右暗区))
            面板均亮 = float(np.mean(中间面板))
            if (
                左暗均亮 > 95.0
                or 右暗均亮 > 95.0
                or 面板均亮 < 145.0
                or 面板均亮 - max(左暗均亮, 右暗均亮) < 50.0
            ):
                return None
            动作区 = hsv[
                int(高 * 0.20):int(高 * 0.90),
                int(宽 * 0.63):int(宽 * 0.83),
            ]
            if 动作区.size == 0:
                return None
            绿色 = (
                (动作区[:, :, 0] >= 35)
                & (动作区[:, :, 0] <= 80)
                & (动作区[:, :, 1] >= 100)
                & (动作区[:, :, 2] >= 100)
            ).astype(np.uint8)
            绿色 = cv2.morphologyEx(
                绿色,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
            )
            _, _, 绿统计, _ = cv2.connectedComponentsWithStats(绿色, 8)
            最小绿面积 = max(800, int(宽 * 高 * 0.004))
            if not any(int(项[4]) >= 最小绿面积 for 项 in 绿统计[1:]):
                return None
            return 关闭点
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def 定位活动弹窗关闭按钮(self, 图像: np.ndarray) -> tuple[int, int] | None:
        """仅在已确认活动弹窗时返回右上角关闭点。"""
        return self._检测活动弹窗关闭点(图像)

    def _升级详情弹窗关闭点(self, 图像: np.ndarray) -> tuple[int, int] | None:
        """识别升级详情面板的安全右上角关闭 X。

        英雄/建筑升级面板会保留主世界资源栏和等级徽章，不能等到
        主页识别之后再处理；否则资源 OCR 只会读到屏幕边缘残留数字，
        后续进攻入口也可能把绿色“立即完成/宝石”按钮当成普通输入。
        这里只做几何页级识别，不点击任何按钮；具体是否关闭以及
        是否属于英雄详情，交给任务上下文的 OCR 安全护栏复核。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim != 3 or 图像.size == 0:
            return None
        if (
            self._检测部落竞赛面板状态(图像) is not None
            or self._检测活动弹窗关闭点(图像) is not None
            or self._检测圣水车弹窗按钮(图像) is not None
        ):
            return None
        try:
            高, 宽 = 图像.shape[:2]
            if 高 < 120 or 宽 < 240:
                return None
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
            标题栏 = hsv[
                int(高 * 0.035):int(高 * 0.14),
                int(宽 * 0.08):int(宽 * 0.82),
            ]
            if 标题栏.size == 0:
                return None
            低饱和明亮像素 = cv2.inRange(
                标题栏, (0, 0, 55), (180, 105, 235)
            )
            支持度 = cv2.countNonZero(低饱和明亮像素) / float(
                标题栏.shape[0] * 标题栏.shape[1]
            )
            if 支持度 < 0.60:
                return None

            return self._查找顶部红色关闭X(
                图像, hsv, x最小比例=0.83, x最大比例=0.95, y最小比例=0.02, y最大比例=0.16
            )
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    @staticmethod
    def _最大连通框(掩码: np.ndarray):
        """返回掩码中面积最大的连通域 (x, y, 宽, 高, 面积)，无则 None。"""
        数量, _, 统计, _ = cv2.connectedComponentsWithStats(掩码, 8)
        if 数量 <= 1:
            return None
        序号 = 1 + int(np.argmax(统计[1:, cv2.CC_STAT_AREA]))
        return tuple(int(值) for 值 in 统计[序号])

    def _检测圣水车弹窗按钮(
        self, 图像: np.ndarray
    ) -> dict[str, tuple[int, int, int, int]] | None:
        """识别夜世界“聖水車/圣水车”弹窗，返回收集按钮与关闭 X 的点击框。

        圣水车弹窗与升级详情共用灰色标题栏和右上角红色 X，旧识别器
        只看这两项，会把它误判为升级详情并拒绝点击“收集”。圣水车
        弹窗独有的视觉结构是：底部横贯的橙色木质横幅、横幅右侧绿色
        “收集”按钮、横幅中部紫色圣水进度条/圣水滴。三者都必须同时
        存在；升级详情页底部只有灰色面板和绿色升级/宝石按钮，没有
        木质横幅与紫色进度条。这里只做几何识别，不授权其它按钮。
        返回值：{"收集": (左, 上, 右, 下), "关闭": (左, 上, 右, 下)}。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim != 3 or 图像.size == 0:
            return None
        try:
            高, 宽 = 图像.shape[:2]
            if 高 < 120 or 宽 < 240:
                return None
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)

            # 1. 底部木质横幅：橙棕色、高饱和，横跨弹窗宽度。
            横幅 = hsv[int(高 * 0.76):int(高 * 0.93), int(宽 * 0.15):int(宽 * 0.82)]
            if 横幅.size == 0:
                return None
            木色 = cv2.inRange(横幅, (8, 150, 90), (25, 255, 235))
            木色比例 = cv2.countNonZero(木色) / float(横幅.shape[0] * 横幅.shape[1])
            if 木色比例 < 0.40:
                return None
            # 木色必须横向铺满：左右两端都要有足够木色，排除局部橙色建筑。
            半宽 = 木色.shape[1] // 2
            for 部分 in (木色[:, :半宽], 木色[:, 半宽:]):
                if cv2.countNonZero(部分) < 部分.size * 0.25:
                    return None

            # 2. 横幅右侧绿色“收集”按钮。
            按钮左, 按钮上 = int(宽 * 0.62), int(高 * 0.76)
            按钮区 = hsv[按钮上:int(高 * 0.94), 按钮左:int(宽 * 0.84)]
            绿色 = cv2.inRange(按钮区, (35, 90, 140), (62, 255, 255))
            绿色 = cv2.morphologyEx(
                绿色, cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
            )
            按钮 = self._最大连通框(绿色)
            if 按钮 is None:
                return None
            bx, by, bw, bh, 面积 = 按钮
            if not (
                宽 * 0.08 <= bw <= 宽 * 0.20
                and 高 * 0.06 <= bh <= 高 * 0.15
                and 面积 >= bw * bh * 0.55
            ):
                return None
            收集框 = (按钮左 + bx, 按钮上 + by, 按钮左 + bx + bw, 按钮上 + by + bh)

            # 3. 横幅中部紫色圣水进度条/圣水滴。
            进度区 = hsv[int(高 * 0.80):int(高 * 0.91), int(宽 * 0.35):int(宽 * 0.66)]
            紫色 = cv2.inRange(进度区, (125, 100, 110), (165, 255, 255))
            if cv2.countNonZero(紫色) < max(40, int(宽 * 高 * 0.00012)):
                return None

            # 4. 右上角红色关闭 X（与升级详情同一几何约束）。
            关闭点 = self._查找顶部红色关闭X(
                图像, hsv, x最小比例=0.78, x最大比例=0.95,
                y最小比例=0.02, y最大比例=0.16,
            )
            if 关闭点 is None:
                return None
            半边 = max(10, int(宽 * 0.025))
            关闭框 = (
                关闭点[0] - 半边, 关闭点[1] - 半边,
                关闭点[0] + 半边, 关闭点[1] + 半边,
            )
            return {"收集": 收集框, "关闭": 关闭框}
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def _圣水车弹窗分数(self, 图像: np.ndarray) -> float:
        """返回圣水车弹窗几何置信度，不授权输入。"""
        return 0.97 if self._检测圣水车弹窗按钮(图像) is not None else 0.0

    def 定位圣水车弹窗按钮(self, 图像: np.ndarray):
        """仅在已确认圣水车弹窗时返回 {"收集": 框, "关闭": 框}。"""
        return self._检测圣水车弹窗按钮(图像)

    def _升级详情弹窗分数(self, 图像: np.ndarray) -> float:
        """返回升级详情页的几何置信度，不授权输入。"""
        return 0.96 if self._升级详情弹窗关闭点(图像) is not None else 0.0

    def 定位升级详情弹窗关闭按钮(self, 图像: np.ndarray):
        """仅在已确认升级详情页时返回右上角关闭点。"""
        return self._升级详情弹窗关闭点(图像)

    @staticmethod
    def 定位哥布林宝石提示关闭按钮(图像: np.ndarray) -> tuple[int, int] | None:
        """识别覆盖在升级页上的哥布林宝石提示，只返回红色 X。

        底层的资源栏和进攻图标仍可见，不能用它们证明主页可操作。
        同时要求白色对话框、右上红 X 和中央绿色宝石按钮，避免把
        主世界草地或一般绿色按钮误当成此提示。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim != 3 or 图像.size == 0:
            return None
        高, 宽 = 图像.shape[:2]
        if 高 < 300 or 宽 < 400:
            return None
        try:
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)

            def 区域(左, 上, 右, 下):
                return hsv[int(高 * 上):int(高 * 下), int(宽 * 左):int(宽 * 右)]

            for 范围 in ((0.49, 0.20, 0.82, 0.28), (0.49, 0.45, 0.82, 0.52)):
                面板 = 区域(*范围)
                白色比例 = np.mean((面板[:, :, 1] < 70) & (面板[:, :, 2] > 150))
                if 白色比例 < 0.75:
                    return None
            关闭区域 = 区域(0.86, 0.16, 0.93, 0.27)
            红色比例 = np.mean(
                ((关闭区域[:, :, 0] <= 15) | (关闭区域[:, :, 0] >= 165))
                & (关闭区域[:, :, 1] > 120)
                & (关闭区域[:, :, 2] > 80)
            )
            if 红色比例 < 0.08:
                return None
            按钮区域 = 区域(0.60, 0.53, 0.78, 0.67)
            绿色比例 = np.mean(
                (按钮区域[:, :, 0] >= 30)
                & (按钮区域[:, :, 0] <= 85)
                & (按钮区域[:, :, 1] > 90)
                & (按钮区域[:, :, 2] > 85)
            )
            if 绿色比例 < 0.30:
                return None
            return (int(round(宽 * 0.895)), int(round(高 * 0.214)))
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def _战斗倒计时分数(self, 图像: np.ndarray) -> float:
        """识别战斗页顶部的白色倒计时数字。

        测试服战斗画面会在顶部显示“剩余 45 秒”等白色数字。战场
        建筑也可能形成竖向边缘，不能只靠奖励卡片数量判断；出现两个
        相邻的大号白色字符时，优先保留战斗页，避免把战场误判为奖励
        选择页。倒计时进入最后阶段时，CoC 会把“离战斗结束剩下”和
        数字改成红色；这一帧不能被奖励横幅/兵栏结构误报覆盖。因此
        白色和红色都在同一个轻量连通域检测里处理，不调用 OCR。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim < 2 or 图像.size == 0:
            return 0.0
        try:
            高, 宽 = 图像.shape[:2]
            左 = int(宽 * 0.32)
            右 = int(宽 * 0.72)
            下 = int(高 * 0.18)
            区域 = 图像[0:下, 左:右]
            hsv = cv2.cvtColor(区域, cv2.COLOR_BGR2HSV)
            白色掩码 = (
                (hsv[:, :, 1] <= 95)
                & (hsv[:, :, 2] >= 165)
            ).astype(np.uint8)
            红色掩码 = (
                ((hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 170))
                & (hsv[:, :, 1] >= 90)
                & (hsv[:, :, 2] >= 100)
            ).astype(np.uint8)

            def 有相邻大号字符(掩码: np.ndarray) -> bool:
                处理掩码 = cv2.morphologyEx(
                    掩码,
                    cv2.MORPH_OPEN,
                    cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
                )
                _, _, 统计, _ = cv2.connectedComponentsWithStats(处理掩码, 8)
                字符 = []
                for x, y, 连通宽, 连通高, 面积 in 统计[1:]:
                    if (
                        面积 >= 20
                        and 连通高 >= max(12, int(高 * 0.018))
                        and 连通高 <= int(高 * 0.14)
                        and 连通宽 >= 3
                        and y <= int(高 * 0.14)
                    ):
                        字符.append((x + 左, y, 连通宽, 连通高))
                字符.sort(key=lambda 项: 项[0])

                # 实机国际服/测试服的倒计时通常是两行：上面是“离战斗
                # 结束剩下”，下面才是“27 秒”。上行字符会插入按 x 排序
                # 的列表，导致下面两个数字不再相邻。先单独提取下方的
                # 大号数字行，避免结算视觉误报覆盖真实战斗状态。
                大号字符 = [
                    项 for 项 in 字符
                    if 项[3] >= max(20, int(高 * 0.030))
                    and 项[1] >= int(高 * 0.035)
                ]
                for 前, 后 in zip(大号字符, 大号字符[1:]):
                    前中心y = 前[1] + 前[3] / 2
                    后中心y = 后[1] + 后[3] / 2
                    水平间距 = 后[0] - (前[0] + 前[2])
                    if (
                        -max(2, int(宽 * 0.005)) <= 水平间距 <= max(24, int(宽 * 0.04))
                        and abs(前中心y - 后中心y) <= max(12, int(高 * 0.022))
                    ):
                        return True

                for 前, 后 in zip(字符, 字符[1:]):
                    前中心y = 前[1] + 前[3] / 2
                    后中心y = 后[1] + 后[3] / 2
                    水平间距 = 后[0] - (前[0] + 前[2])
                    if (
                        -max(2, int(宽 * 0.005)) <= 水平间距 <= max(28, int(宽 * 0.05))
                        and abs(前中心y - 后中心y) <= max(14, int(高 * 0.025))
                    ):
                        return True
                return False

            if 有相邻大号字符(白色掩码):
                return 0.96

            # 最后几秒的红色倒计时有两层特征：上方一串较小的提示字，
            # 下方紧邻一个较高的数字。奖励横幅通常在更低的位置，是
            # 一条宽红色横条，不满足这个上下两层结构。
            红色处理 = cv2.morphologyEx(
                红色掩码,
                cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
            )
            _, _, 统计, _ = cv2.connectedComponentsWithStats(红色处理, 8)
            红色字符 = []
            for x, y, 连通宽, 连通高, 面积 in 统计[1:]:
                if (
                    面积 >= 20
                    and 连通高 >= max(12, int(高 * 0.018))
                    and 连通高 <= int(高 * 0.14)
                    and 连通宽 >= 3
                    and y <= int(高 * 0.14)
                ):
                    红色字符.append((x + 左, y, 连通宽, 连通高, 面积))
            提示字 = [项 for 项 in 红色字符 if 项[1] <= int(高 * 0.08)]
            大号数字 = [
                项 for 项 in 红色字符
                if int(高 * 0.045) <= 项[1] <= int(高 * 0.13)
                and 项[3] >= max(17, int(高 * 0.028))
            ]
            if len(提示字) >= 3 and 大号数字:
                return 0.96
        except Exception:
            return 0.0
        return 0.0

    @staticmethod
    def _断线弹窗分数(图像: np.ndarray, 多按钮: bool = False) -> float:
        """识别 CoC 中央的“连接中断/重新登入”遮罩。

        断线弹窗会保留主世界或战斗画面在底下，若只依赖主页/战斗
        模板，输入护栏可能把恢复按钮当成普通页面点击。这里使用
        弹窗主体的几何范围和三段亮色文字作轻量兜底，不调用 OCR，
        也不会把结算页底部的绿色“回营”按钮当成断线弹窗。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim != 3 or 图像.size == 0:
            return 0.0
        try:
            高, 宽 = 图像.shape[:2]
            if 高 < 300 or 宽 < 400:
                return 0.0
            参考点 = 图像[高 // 2, 宽 // 2].astype(np.int16)
            差异 = np.max(
                np.abs(图像.astype(np.int16) - 参考点), axis=2
            )
            区域左, 区域上 = int(宽 * 0.08), int(高 * 0.16)
            区域右, 区域下 = int(宽 * 0.92), int(高 * 0.86)
            近似面板 = (差异[区域上:区域下, 区域左:区域右] <= 3).astype(np.uint8) * 255
            近似面板 = cv2.morphologyEx(
                近似面板, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8)
            )
            轮廓列表, _ = cv2.findContours(
                近似面板, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            灰度 = cv2.cvtColor(图像, cv2.COLOR_BGR2GRAY)

            for 轮廓 in sorted(轮廓列表, key=cv2.contourArea, reverse=True):
                x, y, w, h = cv2.boundingRect(轮廓)
                x += 区域左
                y += 区域上
                面积 = cv2.contourArea(轮廓)
                # 国际服/测试服的横向布局会把断线面板锚在右侧，面板
                # 左边约为 0.39W 且右边贴近屏幕边缘；旧版只接受居中
                # 面板（x <= 0.30W），因此实机画面会被返回为“未知”。
                居中面板 = 宽 * 0.14 <= x <= 宽 * 0.30
                右锚面板 = (
                    宽 * 0.32 <= x <= 宽 * 0.48
                    and x + w >= 宽 * 0.88
                )
                if not (
                    面积 >= 宽 * 高 * 0.15
                    and 宽 * 0.42 <= w <= 宽 * 0.75
                    and 高 * 0.25 <= h <= 高 * 0.55
                    and (居中面板 or 右锚面板)
                    and 高 * 0.22 <= y <= 高 * 0.45
                ):
                    continue
                面板灰度 = 灰度[y:y + h, x:x + w]
                if 面板灰度.size == 0:
                    continue

                def 亮像素(上比例, 下比例, 左比例=0.04, 右比例=0.92):
                    上边 = max(0, min(h - 1, int(h * 上比例)))
                    下边 = max(上边 + 1, min(h, int(h * 下比例)))
                    左边 = max(0, min(w - 1, int(w * 左比例)))
                    右边 = max(左边 + 1, min(w, int(w * 右比例)))
                    return 面板灰度[上边:下边, 左边:右边] > 120

                if (
                    int(np.count_nonzero(亮像素(0.10, 0.35))) < 180
                    or int(np.count_nonzero(亮像素(0.35, 0.72))) < 120
                    or int(np.count_nonzero(亮像素(0.72, 0.95, 0.04, 0.58))) < 120
                ):
                    continue
                # 评分等多按钮弹窗也有标题、正文和左侧操作文字。
                # 同一操作行右侧仍有独立按钮时，不能推断为“重新登入”。
                右侧有按钮 = int(np.count_nonzero(
                    亮像素(0.72, 0.95, 0.64, 0.96)
                )) >= max(60, int(w * h * 0.0005))
                if 右侧有按钮 == 多按钮:
                    return 0.98
        except (AttributeError, TypeError, ValueError, cv2.error):
            return 0.0
        return 0.0

    def _奖励选择横幅分数(self, 图像: np.ndarray) -> float:
        """识别战斗结束后的奖励选择横幅。

        这个弹窗没有稳定的文字模板，且不同测试服版本的奖励卡片会变；
        但横幅始终位于画面上方中央，是一个较长的红色连通区域。使用
        相对坐标而不是固定像素，兼容 ``ADB屏幕`` 的任意设备分辨率。
        这里只返回视觉证据，不执行任何点击。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim < 2 or 图像.size == 0:
            return 0.0
        try:
            高, 宽 = 图像.shape[:2]
            # 只看上方中央带状区域，排除左下角放弃按钮、兵栏和地图红色建筑。
            左 = int(宽 * 0.12)
            右 = int(宽 * 0.88)
            上 = int(高 * 0.035)
            下 = int(高 * 0.30)
            if 右 <= 左 or 下 <= 上:
                return 0.0
            区域 = 图像[上:下, 左:右]
            hsv = cv2.cvtColor(区域, cv2.COLOR_BGR2HSV)
            色相 = hsv[:, :, 0]
            掩码 = (
                ((色相 <= 12) | (色相 >= 170))
                & (hsv[:, :, 1] >= 70)
                & (hsv[:, :, 2] >= 70)
            ).astype(np.uint8)
            # 把抗锯齿造成的细小断点连起来，但不扩大到整张地图。
            掩码 = cv2.morphologyEx(
                掩码,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)),
            )
            _, _, 统计, _ = cv2.connectedComponentsWithStats(掩码, 8)
            最小面积 = max(1800, int(宽 * 高 * 0.006))
            最小宽度 = max(160, int(宽 * 0.25))
            最小高度 = max(20, int(高 * 0.035))
            for x, y, 连通宽, 连通高, 面积 in 统计[1:]:
                全局x = x + 左
                全局y = y + 上
                if (
                    面积 >= 最小面积
                    and 连通宽 >= 最小宽度
                    and 连通高 >= 最小高度
                    and 连通宽 / max(1, 连通高) >= 3.0
                    and 全局x >= int(宽 * 0.16)
                    and 全局x + 连通宽 <= int(宽 * 0.84)
                    and 全局y <= int(高 * 0.24)
                ):
                    # 仅有红色长条不足以确认奖励页；主世界/军队配置页
                    # 也可能出现类似颜色。奖励页必须同时拥有至少两张
                    # 位于中央的竖向卡片。
                    if self._奖励卡片结构数量(图像) >= 2:
                        return 0.96
        except Exception:
            return 0.0
        return 0.0

    def _结算结果视觉分数(self, 图像: np.ndarray) -> float:
        """模板失配时识别“结果横幅 + 回营按钮”的结算页。"""
        if not isinstance(图像, np.ndarray) or 图像.ndim < 2 or 图像.size == 0:
            return 0.0
        try:
            高, 宽 = 图像.shape[:2]
            if 高 < 300 or 宽 < 400:
                return 0.0
            if self._宝箱领奖页分数(图像) >= 0.90:
                return 0.0
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)

            # 回营按钮只看底部中央，排除右侧战斗速度按钮和兵栏药水。
            # 这里和下方的安全点击定位共用同一套几何条件，避免“识别
            # 成功但点击时又找不到按钮”的分叉。
            if self._定位绿色回营按钮(图像) is None:
                return 0.0

            # 结果横幅必须是中央上半区的宽金色结构。
            rx1, rx2 = int(宽 * 0.22), int(宽 * 0.78)
            ry1, ry2 = int(高 * 0.16), int(高 * 0.58)
            区域 = hsv[ry1:ry2, rx1:rx2]
            金色 = (
                (区域[:, :, 0] <= 38)
                & (区域[:, :, 1] >= 75)
                & (区域[:, :, 2] >= 100)
            ).astype(np.uint8)
            金色 = cv2.morphologyEx(
                金色,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5)),
            )
            轮廓列表, _ = cv2.findContours(
                金色 * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for 轮廓 in 轮廓列表:
                _, _, w, h = cv2.boundingRect(轮廓)
                if (
                    w >= int(宽 * 0.36)
                    and h >= int(高 * 0.08)
                    and w / max(1, h) >= 2.0
                ):
                    return 0.96

            # 夜世界/测试服的结算页有时使用蓝紫结果背景，不再绘制旧版
            # 金色结果横幅。底部大绿色回营按钮仍然稳定存在，同时中央
            # 会出现星级和“0%/xx%”等大号亮色结构。该组合比单独找颜色
            # 安全，且不会把普通主页当成结算页。
            中央 = hsv[
                int(高 * 0.12):int(高 * 0.60),
                int(宽 * 0.20):int(宽 * 0.80),
            ]
            亮色结构 = (
                (中央[:, :, 1] < 90)
                & (中央[:, :, 2] > 175)
            ).astype(np.uint8)
            亮色结构 = cv2.morphologyEx(
                亮色结构,
                cv2.MORPH_OPEN,
                np.ones((3, 3), dtype=np.uint8),
            )
            _, _, 亮色统计, _ = cv2.connectedComponentsWithStats(亮色结构, 8)
            最小亮块面积 = max(80, int(中央.shape[0] * 中央.shape[1] * 0.00025))
            大亮块数量 = sum(
                1
                for _, _, 亮块宽, 亮块高, 亮块面积 in 亮色统计[1:]
                if 亮块面积 >= 最小亮块面积
                and 亮块宽 >= max(8, int(宽 * 0.01))
                and 亮块高 >= max(8, int(高 * 0.01))
            )
            if float(np.mean(亮色结构)) >= 0.014 and 大亮块数量 >= 3:
                return 0.94

            # 某些测试服结算动画会把星级/百分比压暗，亮色连通块会低于
            # 上面的阈值，但底部绿色“回营”按钮和中央暗色结果遮罩仍
            # 稳定存在。绿色按钮已经限定在底部中央；再要求中央区域有
            # 明显暗化和少量白色结果文字，避免把主页的普通绿色控件当
            # 成结算页。
            灰度 = cv2.cvtColor(图像, cv2.COLOR_BGR2GRAY)
            结果区 = 灰度[
                int(高 * 0.10):int(高 * 0.65),
                int(宽 * 0.15):int(宽 * 0.85),
            ]
            if (
                float(np.mean(结果区)) < 90.0
                and float(np.mean(结果区 < 80)) >= 0.45
                and float(np.mean(结果区 > 180)) >= 0.004
            ):
                return 0.92
        except (AttributeError, TypeError, ValueError, cv2.error):
            return 0.0
        return 0.0

    def _定位绿色回营按钮(self, 图像: np.ndarray):
        """返回结算页回营按钮中心，未找到则返回 ``None``。

        夜世界/部分测试服使用底部中央横向绿色按钮；主世界国际服的
        结算页则常把“回营”放在左下角竖向角色卡片里。两种布局都必须
        先通过结果页结构确认，不能把普通战场兵栏或主世界控件授权为
        回营点击目标。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim < 2 or 图像.size == 0:
            return None
        try:
            if self._宝箱领奖页分数(图像) >= 0.90:
                return None
            高, 宽 = 图像.shape[:2]
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
            左, 右 = int(宽 * 0.38), int(宽 * 0.62)
            上, 下 = int(高 * 0.76), int(高 * 0.99)
            绿色 = (
                (hsv[上:下, 左:右, 0] >= 30)
                & (hsv[上:下, 左:右, 0] <= 100)
                & (hsv[上:下, 左:右, 1] >= 70)
                & (hsv[上:下, 左:右, 2] >= 100)
            ).astype(np.uint8)
            if not 绿色.size:
                return None
            候选 = []
            if float(np.mean(绿色)) >= 0.08:
                最小按钮面积 = max(3500, int(宽 * 高 * 0.008))

                def 收集按钮候选(掩码: np.ndarray, 最低填充率: float = 0.0):
                    _, _, 统计, _ = cv2.connectedComponentsWithStats(掩码, 8)
                    结果列表 = []
                    for x, y, 按钮宽, 按钮高, 按钮面积 in 统计[1:]:
                        if (
                            按钮面积 >= 最小按钮面积
                            and 按钮宽 >= int(宽 * 0.12)
                            and 按钮高 >= int(高 * 0.06)
                            # 战斗底部的兵栏/部署区域在测试服会连成一块
                            # 绿色矩形；它通常比真实回营按钮更宽、更高。
                            # 夜世界实机的绿色按钮约为 104x54（宽高比约
                            # 1.93），不能再用过高的 2.0 比例把它排除；同时
                            # 加上最大宽高约束，排除战场兵栏的大片绿色区域。
                            and 按钮宽 / max(1, 按钮高) >= 1.70
                            and 按钮宽 <= int(宽 * 0.22)
                            and 按钮高 <= int(高 * 0.14)
                            and (
                                最低填充率 <= 0.0
                                or 按钮面积 >= 按钮宽 * 按钮高 * 最低填充率
                            )
                        ):
                            结果列表.append((按钮面积, x, y, 按钮宽, 按钮高))
                    return 结果列表

                绿色连通 = cv2.morphologyEx(
                    绿色,
                    cv2.MORPH_CLOSE,
                    cv2.getStructuringElement(cv2.MORPH_RECT, (7, 5)),
                )
                候选 = 收集按钮候选(绿色连通)
                if not 候选:
                    # 实机结算页若按钮周边紧邻暗色草地，(7, 5) 闭运算会跨过
                    # 按钮黑边把草地粘连成超高连通域；先尝试不带闭运算的实心
                    # 按钮轮廓，再尝试高亮绿色核心以剥离暗色背景草地。
                    候选 = 收集按钮候选(绿色, 最低填充率=0.65)
                if not 候选:
                    高亮绿色 = (
                        (hsv[上:下, 左:右, 0] >= 30)
                        & (hsv[上:下, 左:右, 0] <= 100)
                        & (hsv[上:下, 左:右, 1] >= 85)
                        & (hsv[上:下, 左:右, 2] >= 140)
                    ).astype(np.uint8)
                    高亮连通 = cv2.morphologyEx(
                        高亮绿色,
                        cv2.MORPH_CLOSE,
                        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)),
                    )
                    候选 = 收集按钮候选(高亮连通, 最低填充率=0.65)
            if not 候选:
                # 主世界结算页的回营卡片位于左下角，通常是浅灰/浅绿
                # 外框加角色图，不满足“绿色横向按钮”条件。只在限定的
                # 左下区域寻找一个竖向浅色卡片，避免扫描整张地图。
                左区 = 0
                右区 = int(宽 * 0.20)
                上区 = int(高 * 0.76)
                下区 = int(高 * 0.995)
                左下 = hsv[上区:下区, 左区:右区]
                if 左下.size == 0:
                    return None
                浅色 = (
                    (左下[:, :, 1] <= 120)
                    & (左下[:, :, 2] >= 145)
                ).astype(np.uint8)
                浅色 = cv2.morphologyEx(
                    浅色,
                    cv2.MORPH_CLOSE,
                    cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)),
                )
                _, _, 浅色统计, _ = cv2.connectedComponentsWithStats(浅色, 8)
                左下候选 = []
                for x, y, 卡片宽, 卡片高, 卡片面积 in 浅色统计[1:]:
                    if not (
                        卡片面积 >= max(1200, int(宽 * 高 * 0.006))
                        and 卡片宽 >= int(宽 * 0.07)
                        and 卡片宽 <= int(宽 * 0.20)
                        and 卡片高 >= int(高 * 0.12)
                        and 卡片高 <= int(高 * 0.28)
                        and 0.40 <= 卡片宽 / max(1, 卡片高) <= 1.30
                        and x <= int(宽 * 0.04)
                        and y + 卡片高 >= int(高 * 0.88) - 上区
                    ):
                        continue
                    左下候选.append((int(卡片面积), int(x), int(y), int(卡片宽), int(卡片高)))
                if not 左下候选:
                    return None
                _, x, y, 卡片宽, 卡片高 = max(左下候选)
                return (
                    int(x + 卡片宽 // 2),
                    int(上区 + y + 卡片高 // 2),
                )
            _, x, y, 按钮宽, 按钮高 = max(候选)
            return (左 + x + 按钮宽 // 2, 上 + y + 按钮高 // 2)
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def 定位结算回营按钮(
        self,
        图像: np.ndarray,
        允许单帧战斗信号: bool = False,
    ):
        """仅在视觉确认结算页后返回安全的回营按钮坐标。

        正常页面识别始终把放弃按钮或倒计时当作战斗信号。回营状态机
        已连续复核过结算页和按钮后，可在最终帧容忍单个残留信号；
        两项战斗信号同时出现时仍然拒绝，防止活动战斗的伪结算输入。
        """
        放弃按钮分数 = self._红色放弃按钮分数(图像)
        倒计时分数 = self._战斗倒计时分数(图像)
        if 放弃按钮分数 >= 0.90 and 倒计时分数 >= 0.90:
            return None
        if self._结算结果视觉分数(图像) < 0.90:
            return None
        if (
            not 允许单帧战斗信号
            and (放弃按钮分数 >= 0.90 or 倒计时分数 >= 0.90)
        ):
            return None
        return self._定位绿色回营按钮(图像)

    def _定位战斗星级奖励确定按钮(self, 图像: np.ndarray):
        """定位夜世界“胜利之星奖励”中央确定按钮。

        该弹窗会覆盖在已回营的主页上，底层资源栏仍然可见，不能仅凭
        世界 HUD 判断已经回到可操作主页。按钮位于中央偏下且明显高于
        结算页的底部“回营”按钮；同时要求中央存在大面积蓝紫奖励面板，
        避免把普通主页绿色控件当成确认目标。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim < 2 or 图像.size == 0:
            return None
        try:
            高, 宽 = 图像.shape[:2]
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
            左, 右 = int(宽 * 0.28), int(宽 * 0.72)
            上, 下 = int(高 * 0.65), int(高 * 0.92)
            区域 = hsv[上:下, 左:右]
            绿色 = (
                (区域[:, :, 0] >= 30)
                & (区域[:, :, 0] <= 100)
                & (区域[:, :, 1] >= 70)
                & (区域[:, :, 2] >= 100)
            ).astype(np.uint8)
            if not 绿色.size:
                return None
            绿色 = cv2.morphologyEx(
                绿色,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (7, 5)),
            )
            _, _, 统计, _ = cv2.connectedComponentsWithStats(绿色, 8)
            候选 = []
            for x, y, 按钮宽, 按钮高, 面积 in 统计[1:]:
                中心y = 上 + y + 按钮高 / 2
                if (
                    面积 >= max(500, int(宽 * 高 * 0.005))
                    and 按钮宽 >= int(宽 * 0.12)
                    and 按钮高 >= int(高 * 0.07)
                    # 夜世界主页左下“攻击/星数”组合按钮也会形成一块
                    # 绿色连通区域，但它明显比中央奖励确认按钮更宽；
                    # 不得仅凭绿色和 y 坐标把主页误判成奖励弹窗。
                    and 按钮宽 <= int(宽 * 0.24)
                    and 按钮高 <= int(高 * 0.18)
                    # 国际服当前 1280×720 画面缩放到 800×600 后，
                    # 实机“确定”按钮中心约在 y=510；旧的 0.84 上限
                    # 会把真实奖励页漏掉。结算页仍需同时满足蓝紫面板，
                    # 因此扩大垂直范围不会授权普通底部回营按钮。
                    and 高 * 0.70 <= 中心y <= 高 * 0.90
                ):
                    候选.append((面积, 左 + x + 按钮宽 // 2, int(round(中心y))))
            if not 候选:
                return None

            中央 = hsv[
                int(高 * 0.10):int(高 * 0.90),
                int(宽 * 0.12):int(宽 * 0.88),
            ]
            蓝紫面板 = (
                (中央[:, :, 0] >= 88)
                & (中央[:, :, 0] <= 125)
                & (中央[:, :, 1] >= 45)
                & (中央[:, :, 2] >= 70)
            )
            # 主页夜世界地图本身含有大量蓝紫地形，均值约0.45~0.60；
            # 奖励弹窗会用连续的蓝紫遮罩覆盖中央区域，必须达到更高
            # 的连续覆盖率，不能把地图背景当作弹窗面板。
            # 实机奖励遮罩底部包含半透明灰色区域，连续蓝紫覆盖率约
            # 0.68，而夜世界主页通常低于0.60；0.64保留页面版本余量。
            if float(np.mean(蓝紫面板)) < 0.64:
                return None
            _, x, y = max(候选)
            return (x, y)
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def _战斗星级奖励视觉分数(self, 图像: np.ndarray) -> float:
        """识别覆盖主页的夜世界星级奖励确认弹窗。"""
        return 0.96 if self._定位战斗星级奖励确定按钮(图像) is not None else 0.0

    def 定位战斗星级奖励确定按钮(self, 图像: np.ndarray):
        """仅在视觉确认星级奖励弹窗后返回中央确定按钮。"""
        if self._战斗星级奖励视觉分数(图像) < 0.90:
            return None
        return self._定位战斗星级奖励确定按钮(图像)

    @staticmethod
    def _定位宝箱领奖继续按钮(图像: np.ndarray) -> tuple[int, int] | None:
        """定位宝箱/魔法零食领奖全屏页的底部居中绿色“继续/繼續”按钮。

        要求同时满足：
        1. 归一化到 800×600 后左右下角均为 3D 暖橙木桌纹理，排除草地/主夜世界/结算/商店。
        2. 顶部左右为暗色木桌暗角，排除主世界草地与高亮顶部 HUD。
        3. 右上角无高饱和资源条与图标，中央无大面积浅白商店/宝石弹窗背景。
        4. 底部居中区域存在规范尺寸与高填充率的绿色矩形按钮，返回 800×600 中心点。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim != 3 or 图像.shape[2] < 3:
            return None
        if 图像.size == 0 or 图像.shape[0] < 300 or 图像.shape[1] < 400:
            return None
        try:
            if 图像.shape[1] != 800 or 图像.shape[0] != 600:
                参考图 = cv2.resize(图像, (800, 600), interpolation=cv2.INTER_AREA)
            else:
                参考图 = 图像
            hsv = cv2.cvtColor(参考图, cv2.COLOR_BGR2HSV)

            def 木桌比例(区: np.ndarray) -> float:
                return float(
                    (
                        (区[:, :, 0] >= 11)
                        & (区[:, :, 0] <= 21)
                        & (区[:, :, 1] >= 110)
                        & (区[:, :, 1] <= 235)
                        & (区[:, :, 2] >= 80)
                        & (区[:, :, 2] <= 220)
                    ).mean()
                )

            左木 = hsv[360:570, 40:256]
            右木 = hsv[360:570, 544:760]
            if 木桌比例(左木) < 0.40 or 木桌比例(右木) < 0.40:
                return None

            上左 = hsv[12:108, 16:256]
            上右 = hsv[12:108, 544:784]
            if (
                float((上左[:, :, 2] < 135).mean()) < 0.70
                or float((上右[:, :, 2] < 135).mean()) < 0.70
            ):
                return None
            上左草地 = float(
                ((上左[:, :, 0] >= 22) & (上左[:, :, 0] <= 48) & (上左[:, :, 1] >= 70)).mean()
            )
            上右草地 = float(
                ((上右[:, :, 0] >= 22) & (上右[:, :, 0] <= 48) & (上右[:, :, 1] >= 70)).mean()
            )
            if 上左草地 > 0.15 or 上右草地 > 0.15:
                return None

            右上HUD = hsv[0:150, 624:800]
            if float(((右上HUD[:, :, 1] >= 80) & (右上HUD[:, :, 2] >= 160)).mean()) > 0.03:
                return None

            中央面板 = hsv[150:390, 200:600]
            if float(((中央面板[:, :, 1] <= 40) & (中央面板[:, :, 2] >= 170)).mean()) >= 0.30:
                return None

            x1, y1, x2, y2 = 288, 468, 512, 564
            按钮区 = hsv[y1:y2, x1:x2]
            绿色 = cv2.inRange(
                按钮区,
                np.array([34, 80, 100], dtype=np.uint8),
                np.array([85, 255, 255], dtype=np.uint8),
            )
            绿色 = cv2.morphologyEx(
                绿色,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
            )
            _, _, 统计, _ = cv2.connectedComponentsWithStats(绿色, 8)
            最小面积 = max(1500, int(800 * 600 * 0.008))
            候选 = []
            for x, y, 按钮宽, 按钮高, 面积 in 统计[1:]:
                if not (
                    面积 >= 最小面积
                    and 96 <= 按钮宽 <= 192
                    and 36 <= 按钮高 <= 84
                    and 1.6 <= 按钮宽 / max(1, 按钮高) <= 3.2
                    and 面积 >= 按钮宽 * 按钮高 * 0.65
                ):
                    continue
                中心x = x1 + x + 按钮宽 / 2.0
                中心y = y1 + y + 按钮高 / 2.0
                if abs(中心x - 400.0) > 48.0:
                    continue
                候选.append((int(面积), (int(round(中心x)), int(round(中心y)))))
            if not 候选:
                return None
            return max(候选, key=lambda 项: 项[0])[1]
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def _宝箱领奖页分数(self, 图像: np.ndarray) -> float:
        """结合强负例护栏返回宝箱/魔法零食领奖全屏页置信度。"""
        if self._定位宝箱领奖继续按钮(图像) is None:
            return 0.0
        try:
            if (
                self.定位哥布林宝石提示关闭按钮(图像) is not None
                or self._系统维护分数(图像) >= 0.90
                or self._选择卡片弹窗分数(图像) >= 0.90
                or self._升级详情弹窗分数(图像) >= 0.90
                or self._断线弹窗分数(图像, 多按钮=True) >= 0.90
                or self._断线弹窗分数(图像) >= 0.90
                or self.定位联赛概况关闭按钮(图像) is not None
                or self.定位主世界战斗模式普通按钮(图像) is not None
                or self._红色放弃按钮分数(图像) >= 0.90
                or self._战斗倒计时分数(图像) >= 0.90
                or self.定位军队配置页攻击按钮(图像) is not None
            ):
                return 0.0
            return 0.96
        except Exception:
            return 0.0

    def 定位宝箱领奖继续按钮(self, 图像: np.ndarray) -> tuple[int, int] | None:
        """仅在确认宝箱领奖全屏页且无负例遮罩时返回 800×600 居中继续按钮坐标。"""
        if self._宝箱领奖页分数(图像) < 0.90:
            return None
        return self._定位宝箱领奖继续按钮(图像)

    @staticmethod
    def _规范战后奖励文字(文字) -> str:
        """统一新版繁简混排奖励弹窗的常见 OCR 字形。"""
        转换 = str.maketrans({
            "勝": "胜", "寶": "宝", "動": "动", "將": "将",
            "獲": "获", "會": "会", "過": "过", "領": "领",
            "畫": "画", "實": "实",
        })
        return "".join(str(文字 or "").translate(转换).split())

    @staticmethod
    def _OCR框中心(识别项) -> tuple[int, int] | None:
        try:
            框 = np.asarray(识别项[0], dtype=np.float32).reshape(-1, 2)
            if 框.shape[0] < 4:
                return None
            x, y = np.mean(框, axis=0)
            return round(float(x)), round(float(y))
        except (IndexError, TypeError, ValueError):
            return None

    @staticmethod
    def _定位跳过确认绿色按钮(图像: np.ndarray) -> tuple[int, int] | None:
        """在跳过确认文字成立后，只找中央偏右的绿色“是”按钮。"""
        if not isinstance(图像, np.ndarray) or 图像.ndim < 3 or not 图像.size:
            return None
        try:
            高, 宽 = 图像.shape[:2]
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
            x1, x2 = round(宽 * 0.42), round(宽 * 0.78)
            y1, y2 = round(高 * 0.54), round(高 * 0.80)
            区域 = hsv[y1:y2, x1:x2]
            绿色 = (
                (区域[:, :, 0] >= 35)
                & (区域[:, :, 0] <= 100)
                & (区域[:, :, 1] >= 75)
                & (区域[:, :, 2] >= 110)
            ).astype(np.uint8)
            绿色 = cv2.morphologyEx(
                绿色,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
            )
            _, _, 统计, _ = cv2.connectedComponentsWithStats(绿色, 8)
            最低面积 = max(250, int(宽 * 高 * 0.003))
            候选 = []
            for x, y, 按钮宽, 按钮高, 面积 in 统计[1:]:
                中心x = x1 + x + 按钮宽 / 2
                中心y = y1 + y + 按钮高 / 2
                if (
                    面积 >= 最低面积
                    and 按钮宽 >= int(宽 * 0.12)
                    and 按钮高 >= int(高 * 0.06)
                    and 按钮宽 <= int(宽 * 0.30)
                    and 按钮高 <= int(高 * 0.20)
                    and 中心x >= 宽 * 0.54
                    and 中心y >= 高 * 0.57
                ):
                    候选.append((面积, (round(中心x), round(中心y))))
            return max(候选)[1] if 候选 else None
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def 识别战后奖励按钮(
        self,
        图像: np.ndarray,
        OCR结果,
        奖励动画处理中: bool = False,
    ) -> tuple[str, tuple[int, int]] | None:
        """仅按战后奖励文案与按钮位置定位新奖励页的安全操作点。"""
        if not isinstance(图像, np.ndarray) or 图像.ndim < 2 or not 图像.size:
            return None
        项目 = [
            项 for 项 in (OCR结果 or [])
            if isinstance(项, (list, tuple)) and len(项) >= 2
        ]
        文字 = [self._规范战后奖励文字(项[1]) for 项 in 项目]
        合并文字 = "".join(文字)
        高, 宽 = 图像.shape[:2]

        if "跳过宝箱动画" in 合并文字 and "仍要跳过" in 合并文字:
            确认点 = self._定位跳过确认绿色按钮(图像)
            if 确认点 is not None:
                return "确认跳过", 确认点
            return None

        if "已收到" in 合并文字 and "胜利之星" in 合并文字:
            for 项, 文本 in zip(项目, 文字):
                if "领取" not in 文本:
                    continue
                中心 = self._OCR框中心(项)
                if 中心 is None:
                    continue
                x, y = 中心
                if 宽 * 0.35 <= x <= 宽 * 0.70 and 高 * 0.68 <= y <= 高 * 0.90:
                    return "领取", 中心
            return None

        if 奖励动画处理中:
            for 项, 文本 in zip(项目, 文字):
                if 文本 not in {"跳过", "跳过动画", "跳过宝箱动画"}:
                    continue
                中心 = self._OCR框中心(项)
                if 中心 is None:
                    continue
                x, y = 中心
                if x >= 宽 * 0.82 and y >= 高 * 0.80:
                    return "跳过动画", 中心
        return None

    @staticmethod
    def _搜索对手页分数(图像: np.ndarray) -> float:
        """识别“正在搜寻对手…”匹配等待页（白色径向背景+底部居中红色取消）。

        该页没有资源栏、HUD 或战斗特征，旧识别只能返回“未知”。实机
        1280×720 上游戏端匹配常需 70~80 秒。所有区域按画面比例计算，
        横向以中线为锚，任意分辨率/长宽比都适用；只读、不触发输入。
        """
        if not isinstance(图像, np.ndarray) or 图像.ndim != 3 or 图像.size == 0:
            return 0.0
        try:
            高, 宽 = 图像.shape[:2]
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
            亮白 = (hsv[:, :, 1] <= 40) & (hsv[:, :, 2] >= 215)
            # 中央大面积近白背景；以中线为锚，宽度取画面高度的比例。
            半宽 = int(高 * 0.42)
            中x = 宽 // 2
            中央 = 亮白[int(高 * 0.18):int(高 * 0.52), max(0, 中x - 半宽):min(宽, 中x + 半宽)]
            if 中央.size == 0 or float(中央.mean()) < 0.55:
                return 0.0
            # 四角明显更暗（径向渐暗），排除白色全屏面板。
            角宽, 角高 = max(1, int(宽 * 0.06)), max(1, int(高 * 0.10))
            角落 = [
                hsv[:角高, :角宽, 2], hsv[:角高, -角宽:, 2],
                hsv[-角高:, :角宽, 2], hsv[-角高:, -角宽:, 2],
            ]
            角亮度 = float(np.mean([float(角.mean()) for 角 in 角落]))
            if 角亮度 >= 185:
                return 0.0
            # 底部居中红色横向按钮。
            按钮半宽 = int(高 * 0.22)
            上, 下 = int(高 * 0.78), int(高 * 0.95)
            左 = max(0, 中x - 按钮半宽)
            区域 = hsv[上:下, 左:min(宽, 中x + 按钮半宽)]
            红 = (
                ((区域[:, :, 0] <= 10) | (区域[:, :, 0] >= 170))
                & (区域[:, :, 1] >= 110)
                & (区域[:, :, 2] >= 120)
            ).astype(np.uint8)
            数量, _, 统计, 重心 = cv2.connectedComponentsWithStats(红, 8)
            for 序号 in range(1, 数量):
                x, y, 方宽, 方高, 面积 = [int(v) for v in 统计[序号]]
                中心x = float(重心[序号][0]) + 左
                if (
                    方宽 >= 高 * 0.12
                    and 方高 >= 高 * 0.035
                    and 方宽 / max(1, 方高) >= 1.8
                    and 面积 >= 方宽 * 方高 * 0.45
                    and abs(中心x - 中x) <= 宽 * 0.04
                ):
                    return 0.92
        except Exception:
            return 0.0
        return 0.0

    def 识别(self, 屏幕图像: np.ndarray, 战斗中: bool = False) -> 页面识别结果:
        """识别当前页面；奖励选择需由两张间隔足够的新帧确认。"""
        结果 = self._识别单帧(屏幕图像, 战斗中=战斗中)
        上次候选帧 = getattr(self, "_奖励选择候选帧", None)
        上次时间 = getattr(self, "_奖励选择候选时间", None)
        最小间隔秒 = max(
            0.5, float(getattr(self, "奖励选择确认间隔秒", 0.5) or 0.5)
        )
        最大间隔秒 = max(
            最小间隔秒,
            float(getattr(self, "奖励选择确认最大间隔秒", 10.0) or 10.0),
        )
        挂起上限秒 = max(
            0.5, float(getattr(self, "奖励候选挂起最长秒", 3.0) or 3.0)
        )
        开始时间 = getattr(self, "_奖励候选开始时间", None)

        if 结果.页面 == "战斗奖励候选":
            # 候选帧即使仍有放弃按钮或倒计时，也必须先挂起输入。
            # 搜敌过渡特征会在下一张新帧复核时排除奖励页。
            当前时间 = _奖励候选单调时间()
            搜敌分数 = self._奖励候选搜敌分数(结果)
            if 开始时间 is not None and 搜敌分数 >= 0.90:
                self._清除奖励选择候选()
                return 页面识别结果(
                    页面="搜索对手中",
                    世界=None,
                    可信度=搜敌分数,
                    依据=("奖励候选跨帧复核确认搜敌过渡",),
                )
            if 开始时间 is None:
                开始时间 = 当前时间
                self._奖励候选开始时间 = 当前时间
            已挂起秒 = max(0.0, 当前时间 - float(开始时间))
            if 已挂起秒 >= 挂起上限秒:
                self._清除奖励选择候选()
                return self._奖励候选超时结果(结果, 已挂起秒, 挂起上限秒)
            if 屏幕图像 is 上次候选帧:
                return self._待确认奖励选择结果(结果, 最小间隔秒)
            if 上次时间 is not None:
                间隔 = 当前时间 - float(上次时间)
                if 最小间隔秒 <= 间隔 <= 最大间隔秒:
                    self._清除奖励选择候选()
                    return 页面识别结果(
                        页面="战斗奖励选择",
                        世界=None,
                        可信度=结果.可信度,
                        依据=结果.依据 + (f"两张新帧间隔{间隔:.2f}秒确认奖励页",),
                    )
            # 太近或超出复核窗口的帧重新开始计时，不能作为确认帧。
            self._奖励选择候选时间 = 当前时间
            self._奖励选择候选帧 = 屏幕图像
            return self._待确认奖励选择结果(结果, 最小间隔秒)

        if 上次候选帧 is not None:
            # 候选消失后，明确战斗或搜敌页可以恢复原流程；不明确的帧继续挂起。
            if 结果.页面 not in {"未知", "战斗过渡"}:
                self._清除奖励选择候选()
                return 结果
            当前时间 = _奖励候选单调时间()
            已挂起秒 = max(
                0.0,
                当前时间 - float(开始时间 if 开始时间 is not None else 当前时间),
            )
            if 已挂起秒 >= 挂起上限秒:
                self._清除奖励选择候选()
                return self._奖励候选超时结果(结果, 已挂起秒, 挂起上限秒)
            return self._待确认奖励选择结果(结果, 最小间隔秒)

        self._清除奖励选择候选()
        return 结果

    def _清除奖励选择候选(self) -> None:
        self._奖励选择候选时间 = None
        self._奖励选择候选帧 = None
        self._奖励候选开始时间 = None

    @staticmethod
    def _奖励候选超时结果(
        结果: 页面识别结果, 已挂起秒: float, 挂起上限秒: float
    ) -> 页面识别结果:
        return 页面识别结果(
            页面="战斗奖励候选超时",
            世界=None,
            可信度=结果.可信度,
            依据=(
                f"奖励候选挂起{已挂起秒:.1f}秒仍未确认战斗或搜敌，超过{挂起上限秒:.1f}秒上限",
            ),
        )

    @staticmethod
    def _奖励候选搜敌分数(结果: 页面识别结果) -> float:
        for 项 in 结果.依据:
            if 项.startswith("搜敌特征"):
                try:
                    return float(项.removeprefix("搜敌特征"))
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    @staticmethod
    def _待确认奖励选择结果(
        结果: 页面识别结果, 最小间隔秒: float = 0.5
    ) -> 页面识别结果:
        return 页面识别结果(
            页面="战斗过渡",
            世界=None,
            可信度=结果.可信度,
            依据=结果.依据 + (f"奖励选择候选需间隔至少{最小间隔秒:.1f}秒的新帧复核",),
        )

    def _识别单帧(self, 屏幕图像: np.ndarray, 战斗中: bool = False) -> 页面识别结果:
        """识别当前页面；不确定时返回 ``页面=未知``，不触发任何输入。"""
        维护分数 = self._系统维护分数(屏幕图像)
        if 维护分数 >= 0.90:
            return 页面识别结果(
                页面="系统维护",
                世界=None,
                可信度=维护分数,
                依据=(f"顶部黄黑维护警示带{维护分数:.2f}",),
            )
        if self.定位哥布林宝石提示关闭按钮(屏幕图像) is not None:
            return 页面识别结果(
                页面="哥布林宝石提示",
                世界=None,
                可信度=0.98,
                依据=("中央白色哥布林对话框+红色关闭X+绿色宝石按钮",),
            )
        选择卡片分数 = self._选择卡片弹窗分数(屏幕图像)
        # 战斗中的红色兵栏/地图可能同时拼出卡片与 X。进入进攻状态前，
        # 通用点击护栏会先检查画面，此时上下文标志仍可能为 False；因此
        # 只要倒计时和放弃按钮两项独立战斗视觉证据都强，就交给战斗识别，
        # 不让尚未初始化的状态标志把真实战场误判成卡片弹窗。
        if 选择卡片分数 >= 0.90:
            强战斗证据 = (
                self._红色放弃按钮分数(屏幕图像) >= 0.90
                and self._战斗倒计时分数(屏幕图像) >= 0.90
            )
            if not 强战斗证据:
                return 页面识别结果(
                    页面="选择卡片弹窗",
                    世界=None,
                    可信度=选择卡片分数,
                    依据=(f"中央红色卡片+右上角关闭X{选择卡片分数:.2f}",),
                )
        竞赛识别 = self._检测部落竞赛面板状态(屏幕图像)
        if 竞赛识别 is not None:
            竞赛页面, _ = 竞赛识别
            try:
                世界结果 = self.世界识别.识别(屏幕图像)
                当前世界 = getattr(世界结果, "当前世界", None) or "主世界"
            except Exception:
                当前世界 = "主世界"
            依据 = (
                "部落竞赛蓝色旗帜与底部进度条",
                "金色任务详情框" if 竞赛页面 == "部落竞赛任务详情" else "右上角红色关闭X",
            )
            return 页面识别结果(
                页面=竞赛页面,
                世界=当前世界,
                可信度=0.97,
                依据=依据,
            )
        if self._检测活动弹窗关闭点(屏幕图像) is not None:
            强战斗证据 = (
                self._红色放弃按钮分数(屏幕图像) >= 0.90
                and self._战斗倒计时分数(屏幕图像) >= 0.90
            )
            if not 强战斗证据:
                return 页面识别结果(
                    页面="活动弹窗",
                    世界=None,
                    可信度=0.95,
                    依据=("居中高亮度活动列表", "右侧绿色入口", "右上角红色关闭X"),
                )
        # 夜世界圣水车弹窗与升级详情共用标题栏+红色 X，必须先用木质
        # 横幅、绿色收集按钮和紫色进度条区分，否则“收集”会被升级详情
        # 护栏拒绝。圣水车页只放行收集按钮与关闭 X（见输入护栏）。
        if not 战斗中:
            圣水车分数 = self._圣水车弹窗分数(屏幕图像)
            if 圣水车分数 >= 0.90:
                return 页面识别结果(
                    页面="圣水车弹窗",
                    世界="夜世界",
                    可信度=圣水车分数,
                    依据=(
                        "底部木质横幅+绿色收集按钮",
                        "紫色圣水进度条",
                        "右上角红色关闭X",
                    ),
                )
        升级详情分数 = self._升级详情弹窗分数(屏幕图像)
        if 升级详情分数 >= 0.90:
            # 战场顶部/右侧偶尔拼出灰色横条和红白图案，不能仅凭面板
            # 几何形状压过明确的战斗 HUD，否则进攻开始前会等满超时停机。
            # 两个独立战斗标志必须同时存在；单一红色块仍按弹窗保护。
            # 视觉战场证据不能依赖上下文标志，否则战斗开始的首帧会被
            # 保守页序提前当成弹窗，后面的流程就无法建立 _战斗中 状态。
            强战斗证据 = (
                self._红色放弃按钮分数(屏幕图像) >= 0.90
                and self._战斗倒计时分数(屏幕图像) >= 0.90
            )
            if not 强战斗证据:
                return 页面识别结果(
                    页面="升级详情弹窗",
                    世界=None,
                    可信度=升级详情分数,
                    依据=(f"中央升级标题栏+右上角关闭X{升级详情分数:.2f}",),
                )
        多按钮分数 = self._断线弹窗分数(屏幕图像, 多按钮=True)
        if 多按钮分数 >= 0.90:
            return 页面识别结果(
                页面="多按钮弹窗", 世界=None, 可信度=多按钮分数,
                依据=("中央面板操作行左右均有按钮，需文字确认",),
            )
        断线分数 = self._断线弹窗分数(屏幕图像)
        if 断线分数 >= 0.90:
            return 页面识别结果(
                页面="断线弹窗",
                世界=None,
                可信度=断线分数,
                依据=(f"中央断线弹窗{断线分数:.2f}",),
            )
        联赛关闭点 = self.定位联赛概况关闭按钮(屏幕图像)
        if 联赛关闭点 is not None:
            return 页面识别结果(
                页面="联赛概况弹窗",
                世界=None,
                可信度=0.98,
                依据=("下半部红色联赛面板", "顶部三分页标签", "右上角红色关闭X"),
            )
        普通战斗按钮 = self.定位主世界战斗模式普通按钮(屏幕图像)
        if 普通战斗按钮 is not None:
            return 页面识别结果(
                页面="主世界战斗模式选择",
                世界="主世界",
                可信度=0.96,
                依据=(
                    "左侧橙色普通战斗按钮",
                    "右侧蓝色排位报名按钮",
                ),
            )
        模板战斗分数 = self._最佳分数(
            self._裁剪(屏幕图像, self.放弃战斗区域),
            self.放弃战斗模板,
        )
        视觉战斗分数 = self._红色放弃按钮分数(屏幕图像)
        战斗分数 = max(模板战斗分数, 视觉战斗分数)
        战斗依据 = (
            f"红色放弃按钮{视觉战斗分数:.2f}"
            if 视觉战斗分数 >= 模板战斗分数
            else f"放弃按钮{模板战斗分数:.2f}"
        )
        模板结算分数 = self._最佳分数(
            self._裁剪(屏幕图像, self.结算区域),
            self.结算模板,
        )
        视觉结算分数 = self._结算结果视觉分数(屏幕图像)
        # 主世界的草地和建筑在“全屏缩放到 800×600”后，可能形成一块
        # 大绿色区域和金色建筑带，单独看会像“结果横幅+回营按钮”。
        # 先用独立的世界 HUD 信号复核：已经确认是主/夜世界主页时，
        # 不能把它当成结算页拦截正常任务点击。真正结算页的资源栏会被
        # 结果遮罩覆盖，世界识别应返回未知。
        世界结果 = None
        if 视觉结算分数 >= 0.90:
            try:
                世界结果 = self.世界识别.识别(屏幕图像)
                依据列表 = getattr(世界结果, "依据", ()) or ()
                仅结算兜底 = any("结算" in str(项) for 项 in 依据列表)
                if 世界结果.当前世界 and not 仅结算兜底:
                    视觉结算分数 = 0.0
            except Exception:
                世界结果 = None
        结算分数 = max(模板结算分数, 视觉结算分数)

        倒计时分数 = self._战斗倒计时分数(屏幕图像)
        奖励选择分数 = self._奖励选择横幅分数(屏幕图像)
        搜索分数 = self._搜索对手页分数(屏幕图像)
        明确结算页 = (
            模板结算分数 >= self.结算阈值 or 视觉结算分数 >= 0.90
        )
        # 横幅和至少两张竖向卡片是奖励候选。先返回内部候选状态，避免
        # 同帧的战斗倒计时/放弃按钮把输入直接放行；外层会等待新帧复核。
        # 明确的回营/结算按钮仍优先交给结算流程。
        if 奖励选择分数 >= self.奖励选择页阈值 and not 明确结算页:
            依据 = [
                f"奖励选择红色横幅{奖励选择分数:.2f}",
                f"奖励卡片结构{self._奖励卡片结构数量(屏幕图像)}张",
                f"搜敌特征{搜索分数:.2f}",
            ]
            if 战斗分数 >= 0.90:
                依据.append(f"红色放弃按钮{战斗分数:.2f}")
            if 倒计时分数 >= 0.90:
                依据.append(f"战斗倒计时{倒计时分数:.2f}")
            return 页面识别结果(
                页面="战斗奖励候选",
                世界=None,
                可信度=奖励选择分数,
                依据=tuple(依据),
            )
        # 倒计时和左下角“放弃”按钮都是战场证据。必须先处理它们，
        # 再看宽松的“结果横幅+回营视觉”：战斗中的地图/兵栏可能拼出
        # 伪结算，不能让它抢在仍运行的倒计时之前中断进攻或写入假结果。
        if (
            (倒计时分数 >= 0.90 and (战斗中 or 战斗分数 >= self.战斗阈值))
            or (战斗中 and 视觉战斗分数 >= 0.90)
        ):
            return 页面识别结果(
                页面="战斗中",
                世界=None,
                可信度=max(战斗分数, 倒计时分数),
                依据=tuple(
                    项 for 项 in (战斗依据 if 战斗分数 else None, f"战斗倒计时{倒计时分数:.2f}")
                    if 项
                ),
            )

        if (
            not 战斗中
            and 视觉战斗分数 < 0.90
            and 倒计时分数 < 0.90
            and 奖励选择分数 < self.奖励选择页阈值
            and 模板结算分数 < self.结算阈值
        ):
            领奖分数 = self._宝箱领奖页分数(屏幕图像)
            if 领奖分数 >= 0.90:
                return 页面识别结果(
                    页面="宝箱领奖页",
                    世界=None,
                    可信度=领奖分数,
                    依据=(
                        "3D木桌领奖背景",
                        f"底部居中绿色继续按钮{领奖分数:.2f}",
                    ),
                )

        # 只有排除有效倒计时与战斗 HUD 后，才允许视觉结算候选盖过
        # 弱模板；否则它可能把实际仍在倒数的战场直接送入结算 OCR。
        if 视觉结算分数 >= 0.90 and 视觉战斗分数 < 0.90:
            return 页面识别结果(
                页面="战斗结算",
                世界=None,
                可信度=视觉结算分数,
                依据=(
                    f"结果横幅+回营视觉{视觉结算分数:.2f}",
                    f"已排除战斗倒计时{倒计时分数:.2f}",
                ),
            )

        if 结算分数 >= self.结算阈值:
            return 页面识别结果(
                页面="战斗结算",
                世界=None,
                可信度=结算分数,
                依据=(
                    f"结算按钮{模板结算分数:.2f}"
                    if 模板结算分数 >= 视觉结算分数
                    else f"结果横幅+回营视觉{视觉结算分数:.2f}"
                ,),
            )
        # 搜敌页特征优先于普通页面分类；奖励候选帧由外层跨帧状态机处理。
        if 搜索分数 >= 0.90:
            return 页面识别结果(
                页面="搜索对手中",
                世界=None,
                可信度=搜索分数,
                依据=("中央白色径向背景+底部居中红色取消按钮（游戏端匹配中）",),
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

        # 星级奖励确认框只会出现在回营后的覆盖层。必须在战斗倒计时、
        # 放弃按钮和“战斗中过渡”全部排除后再判断；实机战斗底部的
        # 兵栏/技能高亮也可能命中中央蓝紫结构，不能因此提前停止下兵。
        星级奖励分数 = self._战斗星级奖励视觉分数(屏幕图像)
        if 星级奖励分数 >= 0.90:
            return 页面识别结果(
                页面="战斗星级奖励",
                世界=None,
                可信度=星级奖励分数,
                依据=(f"蓝紫星级奖励面板+中央确定按钮{星级奖励分数:.2f}",),
            )

        # 军队配置页检测包含宽松的颜色/几何候选，战场草地和资源结构
        # 可能拼出同样的候选。必须先处理红色放弃按钮、战斗倒计时、
        # 结算和奖励等高优先级状态；若战斗已标记但 HUD 暂时不清晰，
        # 上面的“战斗过渡”也会先安全阻断，不能退回配置页误分类。
        军队攻击按钮 = self.定位军队配置页攻击按钮(屏幕图像)
        if 军队攻击按钮 is not None:
            return 页面识别结果(
                页面="军队配置页",
                世界=None,
                可信度=0.98,
                依据=(
                    "中央军队配置面板",
                    f"右下攻击按钮{军队攻击按钮[0]},{军队攻击按钮[1]}",
                ),
            )

        # 单独一个红色图块不足以认定为战斗：新版军队配置页也会在
        # 左下区域产生相似红色候选。若配置页联合候选缺席，才使用
        # 红色放弃按钮模板作为最后兜底；战斗中的状态由上面的强 HUD
        # 或“战斗过渡”分支优先保护。
        if 战斗分数 >= self.战斗阈值:
            return 页面识别结果(
                页面="战斗中",
                世界=None,
                可信度=战斗分数,
                依据=(战斗依据,)
                + ((f"战斗倒计时{倒计时分数:.2f}",) if 倒计时分数 else ()),
            )

        if 世界结果 is None:
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

        if 搜索分数 >= 0.90:
            return 页面识别结果(
                页面="搜索对手中",
                世界=None,
                可信度=搜索分数,
                依据=("中央白色径向背景+底部居中红色取消按钮（游戏端匹配中）",),
            )

        return 页面识别结果(
            页面="未知",
            世界=None,
            可信度=max(世界结果.主世界分数, 世界结果.夜世界分数),
            依据=世界结果.依据,
        )


from 工具包.识别参数 import 应用识别参数 as _应用识别参数

_应用识别参数(页面识别器, "主页")
