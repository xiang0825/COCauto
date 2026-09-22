"""点击前后的轻量页面识别。

该模块只使用少量、限定区域的模板匹配，不做 OCR/YOLO，不在每次点击时
重复加载模型。调用方负责缓存截图和结果，使高频下兵仍然流畅。
"""

from dataclasses import dataclass
from typing import Optional

import cv2
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
    # 测试服/活动战斗结束后可能在战场上方显示“选择一项奖励！”横幅，
    # 此时左下角的“放弃”按钮仍然可见。它不能被当成普通战斗页，
    # 否则下兵线程会继续点击兵栏和地图上的奖励卡片。
    奖励选择页阈值 = 0.90

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

    def _系统维护分数(self, 图像: np.ndarray) -> float:
        """识别测试服/国际服的系统维护页顶部黄黑警示带。

        维护页会在中间保留一个深色弹窗，旧规则容易把它误判成断线弹窗，
        随后重复点击“再试一次”。顶部横跨画面的黄黑警示带是更稳定的页级
        特征；只检查顶部 12% 的多行黄色覆盖率，不扫描地图或按钮区域。
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
                return 0.98
        except (AttributeError, TypeError, ValueError, cv2.error):
            return 0.0
        return 0.0

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
            上方高度 = min(max(1, int(高 * 0.14)), 区域.shape[0])
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
                    and 高 >= 20
                    and 宽 / max(1, 高) >= 1.5
                    and x <= max(40, int(区域宽度 * 0.25))
                    and y <= int(上方.shape[0] * 0.75)
                ):
                    return 0.93
        except Exception:
            return 0.0
        return 0.0

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
                    if (
                        后[0] - (前[0] + 前[2]) <= max(24, int(宽 * 0.04))
                        and abs(前中心y - 后中心y) <= max(12, int(高 * 0.022))
                    ):
                        return True

                for 前, 后 in zip(字符, 字符[1:]):
                    前中心y = 前[1] + 前[3] / 2
                    后中心y = 后[1] + 后[3] / 2
                    if (
                        后[0] - (前[0] + 前[2]) <= max(28, int(宽 * 0.05))
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
    def _断线弹窗分数(图像: np.ndarray) -> float:
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
        except (AttributeError, TypeError, ValueError, cv2.error):
            return 0.0
        return 0.0

    def _定位绿色回营按钮(self, 图像: np.ndarray):
        """返回结算页底部绿色回营按钮中心，未找到则返回 ``None``。"""
        if not isinstance(图像, np.ndarray) or 图像.ndim < 2 or 图像.size == 0:
            return None
        try:
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
            if not 绿色.size or float(np.mean(绿色)) < 0.08:
                return None
            绿色连通 = cv2.morphologyEx(
                绿色,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (7, 5)),
            )
            _, _, 绿色统计, _ = cv2.connectedComponentsWithStats(绿色连通, 8)
            最小按钮面积 = max(3500, int(宽 * 高 * 0.008))
            候选 = []
            for x, y, 按钮宽, 按钮高, 按钮面积 in 绿色统计[1:]:
                if (
                    按钮面积 >= 最小按钮面积
                    and 按钮宽 >= int(宽 * 0.12)
                    and 按钮高 >= int(高 * 0.06)
                ):
                    候选.append((按钮面积, x, y, 按钮宽, 按钮高))
            if not 候选:
                return None
            _, x, y, 按钮宽, 按钮高 = max(候选)
            return (左 + x + 按钮宽 // 2, 上 + y + 按钮高 // 2)
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def 定位结算回营按钮(self, 图像: np.ndarray):
        """仅在视觉确认结算页后返回安全的回营按钮坐标。"""
        if self._结算结果视觉分数(图像) < 0.90:
            return None
        return self._定位绿色回营按钮(图像)

    def 识别(self, 屏幕图像: np.ndarray, 战斗中: bool = False) -> 页面识别结果:
        """识别当前页面；不确定时返回 ``页面=未知``，不触发任何输入。"""
        维护分数 = self._系统维护分数(屏幕图像)
        if 维护分数 >= 0.90:
            return 页面识别结果(
                页面="系统维护",
                世界=None,
                可信度=维护分数,
                依据=(f"顶部黄黑维护警示带{维护分数:.2f}",),
            )
        断线分数 = self._断线弹窗分数(屏幕图像)
        if 断线分数 >= 0.90:
            return 页面识别结果(
                页面="断线弹窗",
                世界=None,
                可信度=断线分数,
                依据=(f"中央断线弹窗{断线分数:.2f}",),
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
                if 世界结果.当前世界:
                    视觉结算分数 = 0.0
            except Exception:
                世界结果 = None
        结算分数 = max(模板结算分数, 视觉结算分数)

        倒计时分数 = self._战斗倒计时分数(屏幕图像)
        # 倒计时是战场独有的强证据。不同分辨率/皮肤下左下角“放弃”
        # 按钮模板可能暂时失配，但只要顶部倒计时仍在，就必须继续识别
        # 为战斗中；奖励页没有倒计时，不能让结算按钮或奖励卡片规则
        # 抢先停掉下兵。这个判断必须位于结算分数之前：实机第二场战斗
        # 曾在仍有 27 秒倒计时时被底部绿色区域的结算视觉规则误判为
        # “战斗结束”，导致提前停止继续下兵。
        if (
            倒计时分数 >= 0.90
            and (战斗中 or 战斗分数 >= self.战斗阈值)
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
        # 结算动画中可能先出现红色横幅和三张资源/兵种卡片，回营按钮
        # 要晚几百毫秒才渲染出来。只有已经排除结算按钮后才判定奖励
        # 选择，避免把“败战/胜利”结果页误报成奖励选择并停掉任务。
        奖励选择分数 = self._奖励选择横幅分数(屏幕图像)
        # 战场顶部的倒计时和左下角放弃按钮是更强的战斗证据。奖励
        # 选择页没有倒计时；两者同时出现时，不能让地图建筑/红色文字
        # 造成的“卡片结构”误报中断下兵。
        if (
            奖励选择分数 >= self.奖励选择页阈值
            and not (
                战斗分数 >= self.战斗阈值
                and 倒计时分数 >= 0.90
            )
        ):
            return 页面识别结果(
                页面="战斗奖励选择",
                世界=None,
                可信度=奖励选择分数,
                依据=(
                    f"奖励选择红色横幅{奖励选择分数:.2f}",
                    f"奖励卡片结构{self._奖励卡片结构数量(屏幕图像)}张",
                ),
            )

        if 战斗分数 >= self.战斗阈值:
            return 页面识别结果(
                页面="战斗中",
                世界=None,
                可信度=战斗分数,
                依据=(战斗依据,)
                + ((f"战斗倒计时{倒计时分数:.2f}",) if 倒计时分数 else ()),
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

        return 页面识别结果(
            页面="未知",
            世界=None,
            可信度=max(世界结果.主世界分数, 世界结果.夜世界分数),
            依据=世界结果.依据,
        )
