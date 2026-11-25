"""主世界/夜世界识别。

世界入口的旧实现把一个很小的圣水图标放到整张截图上匹配。地图上的
建筑、动画和缩放后的资源图标都可能产生相似结果，因此会出现“当前在
主世界却反复切换”或“夜世界被判成主世界”的问题。

这里使用固定的 800×600 逻辑画布，把特征限制在它应该出现的区域，再用
两个互相独立的信号交叉确认：右上角资源栏和左下角世界入口。官网图片
只作为视觉参考，不直接拿宣传图做模板匹配；宣传图没有游戏 UI，直接匹配
会比现有游戏内模板更不稳定。
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import cv2


@dataclass(frozen=True)
class 世界识别结果:
    """一次截图的世界判断及可审计依据。"""

    当前世界: Optional[str]
    主世界分数: float
    夜世界分数: float
    主世界资源图标分数: float
    夜世界资源图标分数: float
    主世界入口分数: float
    依据: tuple[str, ...]

    @property
    def 可靠(self) -> bool:
        return self.当前世界 is not None

    def 摘要(self) -> str:
        世界 = self.当前世界 or "未知"
        依据 = "、".join(self.依据) if self.依据 else "无独立特征达到阈值"
        return (
            f"当前={世界}，主世界={self.主世界分数:.2f}，"
            f"夜世界={self.夜世界分数:.2f}，依据={依据}"
        )


class 世界识别器:
    """使用游戏内 UI 特征识别当前世界。

    ADB屏幕会把设备截图转换到 800×600 逻辑画布，所以这里不依赖窗口的
    实际像素尺寸。资源栏特征使用较宽的区域来容纳客户端版本的小幅偏移，
    世界入口特征则限制在左下角，避免地图内容参与匹配。
    """

    逻辑宽度 = 800
    逻辑高度 = 600
    资源栏区域 = (650, 0, 800, 190)
    主世界入口区域 = (0, 430, 180, 600)
    # 夜世界新版主页的左上角使用红色等级徽章，旧模板资源图标在部分
    # 测试服/客户端版本中会因缩放和素材更新失配。这里只扫描固定 HUD
    # 区域，不把地图上的红色建筑参与判断。
    世界徽章区域 = (0, 0, 90, 105)

    主世界资源模板 = "主世界圣水图标.bmp"
    夜世界资源模板 = "夜世界圣水图标.bmp|夜世界圣水图标1.bmp"
    主世界入口模板 = (
        "家乡进攻图标3.bmp|家乡进攻图标1.bmp|"
        "家乡进攻图标2.bmp|家乡进攻图标.bmp"
    )

    # 这些阈值是在现有 800×600 实机截图上校准的：主世界圣水模板在
    # 主世界约为 1.00，夜世界模板在主世界约为 0.87~0.90；反过来在
    # 自己的页面会明显更高。保留余量但拒绝“两个世界都很像”的画面。
    资源图标阈值 = 0.92
    主世界入口阈值 = 0.86
    最低世界分数 = 0.42
    最低分差 = 0.12

    def __init__(self, 模板识别):
        self.模板识别 = 模板识别

    @staticmethod
    def _裁剪(图像: np.ndarray, 区域: tuple[int, int, int, int]) -> np.ndarray:
        """从逻辑画布裁剪区域；异常输入返回空数组而不是抛出。"""
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
    def _支持度(分数: float, 阈值: float) -> float:
        """把模板相似度映射为 0~1 的证据强度。"""
        if 分数 is None:
            return 0.0
        try:
            分数 = float(分数)
        except (TypeError, ValueError):
            return 0.0
        if 分数 <= 阈值:
            return 0.0
        return max(0.0, min(1.0, (分数 - 阈值) / (1.0 - 阈值)))

    def _徽章颜色证据(self, 图像: np.ndarray) -> tuple[float, float]:
        """返回 (主世界蓝色徽章证据, 夜世界红色徽章证据)。

        夜世界主页的等级徽章和主世界徽章属于固定 HUD 锚点，位置比
        资源图标更稳定。仅用颜色覆盖率作为备用证据，并要求徽章区域
        同时具备足够的彩色像素，避免过渡帧或普通地图纹理触发切换。
        """
        区域 = self._裁剪(图像, self.世界徽章区域)
        if 区域.size == 0:
            return 0.0, 0.0
        try:
            import cv2

            hsv = cv2.cvtColor(区域, cv2.COLOR_BGR2HSV)
            红色 = (
                ((hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 170))
                & (hsv[:, :, 1] >= 105)
                & (hsv[:, :, 2] >= 85)
            )
            蓝色 = (
                (hsv[:, :, 0] >= 82)
                & (hsv[:, :, 0] <= 125)
                & (hsv[:, :, 1] >= 75)
                & (hsv[:, :, 2] >= 85)
            )
            红覆盖率 = float(红色.mean())
            蓝覆盖率 = float(蓝色.mean())

            def 是局部徽章(掩码, 覆盖率: float) -> bool:
                """拒绝铺满左上区域的面板背景，只保留局部徽章形状。"""
                if 覆盖率 < 0.08:
                    return False
                数量, _, 统计, _ = cv2.connectedComponentsWithStats(
                    掩码.astype("uint8"), 8
                )
                if 数量 <= 1:
                    return False
                最大 = max(统计[1:], key=lambda 行: int(行[4]))
                x, y, 宽, 高, 面积 = [int(值) for 值 in 最大]
                # 真实等级徽章位于左上角、宽度约半个区域；军队/详情
                # 面板则从较低位置铺开并接近整个区域宽度。
                return (
                    面积 >= 80
                    and x <= int(区域.shape[1] * 0.30)
                    and y <= int(区域.shape[0] * 0.30)
                    and 宽 <= int(区域.shape[1] * 0.78)
                )

            # 实机 800x600 逻辑画布中，夜世界红徽章和主世界蓝徽章
            # 都是局部 HUD；几何约束比单纯覆盖率更能排除军队面板。
            红证据 = 1.0 if 是局部徽章(红色, 红覆盖率) else 0.0
            蓝证据 = 1.0 if 是局部徽章(蓝色, 蓝覆盖率) else 0.0
            return 蓝证据, 红证据
        except (AttributeError, TypeError, ValueError, cv2.error):
            return 0.0, 0.0

    def _最佳分数(
        self,
        图像: np.ndarray,
        模板路径: str,
        备用触发分数: float = 0.82,
    ) -> float:
        """读取模板匹配最佳分数，兼容旧的自定义识图引擎。

        多模板先试最常见的一张；只有首张落在“可能是缩放/版本差异”
        的区间才扫描备用模板。这样主世界每次点击通常只需三次匹配，
        又保留了旧素材的兼容性。
        """
        if 图像.size == 0:
            return 0.0

        路径列表 = 模板路径.split("|") if isinstance(模板路径, str) else list(模板路径)
        if not 路径列表:
            return 0.0

        最佳匹配 = getattr(self.模板识别, "执行最佳匹配", None)
        if callable(最佳匹配):
            try:
                结果 = 最佳匹配(图像, 路径列表[0])
                if isinstance(结果, tuple) and 结果:
                    分数 = float(结果[0])
                    if len(路径列表) == 1 or 分数 >= 备用触发分数:
                        return 分数
                    备用结果 = 最佳匹配(图像, "|".join(路径列表[1:]))
                    return max(分数, float(备用结果[0]))
            except Exception:
                # 识别失败按无证据处理；由外层任务继续执行回退逻辑。
                return 0.0

        # 旧版/测试替身只有执行匹配时，仍然使用区域限制后的布尔结果。
        try:
            命中, _, _ = self.模板识别.执行匹配(
                图像, 路径列表[0], 相似度阈值=self.资源图标阈值
            )
            if 命中 or len(路径列表) == 1:
                return 1.0 if 命中 else 0.0
            命中, _, _ = self.模板识别.执行匹配(
                图像, "|".join(路径列表[1:]), 相似度阈值=self.资源图标阈值
            )
            return 1.0 if 命中 else 0.0
        except Exception:
            return 0.0

    @classmethod
    def _新版战斗入口分数(cls, 图像: np.ndarray) -> float:
        """识别新版主页左下角的黄色“战斗”入口卡片。

        新版 HUD 将旧剑盾图标改为底部的大型黄色卡片。只检查原入口
        所在的左下角，并要求按钮尺寸、横向比例和足够的黄色填充率；
        地图中的黄色建筑/资源不满足此组合。主页资源栏和等级徽章仍
        优先交叉验证；没有模板命中的新版本只返回中等主页置信度，由
        登录/任务入口的连续多帧页面复核再决定是否发送输入。
        """
        # 18.647.5 把旧剑盾入口换成贴近屏幕底部的纵向黄色卡片；
        # 紧邻其上方的星级条也含大量黄色像素。把两者放进同一宽 ROI
        # 会由闭运算连成覆盖整个左下角的色块，随后又因尺寸过大被拒绝。
        # 只检查最底部左侧的战斗卡片，避免星级条和地图一起参与轮廓。
        高度, 宽度 = 图像.shape[:2]
        区域 = cls._裁剪(
            图像,
            (
                0, int(高度 * 0.80),
                int(宽度 * 0.18), int(高度 * 0.985),
            ),
        )
        if 区域.size == 0 or 区域.ndim != 3 or 区域.shape[2] < 3:
            return 0.0
        try:
            高度, 宽度 = 区域.shape[:2]
            hsv = cv2.cvtColor(区域, cv2.COLOR_BGR2HSV)
            # 3D 宝箱/魔法零食领奖界面的木桌边缘在左下角 ROI 右上方也会形成暖橙棕色块
            # （H≈16、饱和度与亮度均明显偏低，且贴近 ROI 右上边界）；新版黄色“战斗”入口
            # 卡片锚定在左下边缘内侧，且拥有高饱和、高亮度的纯金黄核心。
            黄色 = cv2.inRange(
                hsv,
                np.array([19, 115, 100], dtype=np.uint8),
                np.array([33, 255, 255], dtype=np.uint8),
            )
            # 卡片内的剑图标会挖出空洞，但外轮廓本身连续。闭运算会将
            # 邻近的星级条/底部棕框连成大轮廓，再因尺寸过大拒绝入口。
            轮廓, _ = cv2.findContours(
                黄色, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for 项 in 轮廓:
                x, y, w, h = cv2.boundingRect(项)
                比例 = w / max(1.0, float(h))
                if w < max(35, int(宽度 * 0.30)) or h < max(22, int(高度 * 0.12)):
                    continue
                # 新版“战斗”是纵向大卡片：在 800×600 参考画布上宽高比约 0.5~0.8
                # （弹窗遮罩压暗后轮廓会略微收窄到 ~0.50），且左边界锚定在屏幕左下内侧；
                # 排除紧贴 ROI 右边界的木桌/草地边缘色块。
                if (
                    x > 宽度 * 0.30
                    or x + w > 宽度 * 0.96
                    or w > 宽度 * 0.98
                    or h > 高度
                    or not 0.45 <= 比例 <= 3.8
                ):
                    continue
                填充率 = cv2.contourArea(项) / max(1.0, float(w * h))
                if 填充率 < 0.55:
                    continue
                框hsv = hsv[y:y + h, x:x + w]
                纯金核心 = (
                    (框hsv[:, :, 0] >= 19)
                    & (框hsv[:, :, 0] <= 33)
                    & (框hsv[:, :, 1] >= 130)
                    & (框hsv[:, :, 2] >= 100)
                )
                if float(纯金核心.mean()) >= 0.45:
                    return min(0.99, 0.90 + 0.09 * 填充率)
        except (AttributeError, TypeError, ValueError, cv2.error):
            return 0.0
        return 0.0

    _结算主资源下限 = 0.905
    _结算主夜最小分差 = 0.035

    @classmethod
    def _主世界三栏资源证据(cls, 资源栏: np.ndarray) -> bool:
        """确认右上角同时存在主世界独有的三栏资源图标（金币、紫色圣水、黑油）。

        夜世界右上角只有两栏（建筑金币、建筑圣水），且没有黑油栏。
        结合主世界圣水模板高置信度与明显主/夜分差，可排除黑屏、
        空图、过渡帧和夜世界画面。
        """
        if not isinstance(资源栏, np.ndarray) or 资源栏.ndim != 3 or 资源栏.shape[2] < 3:
            return False
        if 资源栏.shape[0] < 120 or 资源栏.shape[1] < 100:
            return False
        try:
            if 资源栏.shape[:2] != (190, 150):
                区域 = cv2.resize(资源栏, (150, 190), interpolation=cv2.INTER_AREA)
            else:
                区域 = 资源栏
            hsv = cv2.cvtColor(区域, cv2.COLOR_BGR2HSV)
            金币区 = hsv[18:48, 120:146]
            圣水区 = hsv[60:92, 120:146]
            黑油区 = hsv[102:136, 120:146]
            黑油条 = hsv[104:134, 25:138]

            金币比例 = float(
                (
                    (金币区[:, :, 0] >= 14)
                    & (金币区[:, :, 0] <= 36)
                    & (金币区[:, :, 1] >= 80)
                    & (金币区[:, :, 2] >= 90)
                ).mean()
            )
            圣水比例 = float(
                (
                    (圣水区[:, :, 0] >= 130)
                    & (圣水区[:, :, 0] <= 168)
                    & (圣水区[:, :, 1] >= 70)
                    & (圣水区[:, :, 2] >= 70)
                ).mean()
            )
            黑油暗色 = float((黑油区[:, :, 2] < 85).mean())
            黑油非金 = float(
                (
                    (黑油区[:, :, 0] >= 14)
                    & (黑油区[:, :, 0] <= 36)
                    & (黑油区[:, :, 1] >= 80)
                    & (黑油区[:, :, 2] >= 90)
                ).mean()
            )
            黑油非紫 = float(
                (
                    (黑油区[:, :, 0] >= 130)
                    & (黑油区[:, :, 0] <= 168)
                    & (黑油区[:, :, 1] >= 70)
                    & (黑油区[:, :, 2] >= 70)
                ).mean()
            )
            黑油条明暗差 = int(黑油条[:, :, 2].max()) - int(黑油条[:, :, 2].min())
            return (
                金币比例 >= 0.30
                and 圣水比例 >= 0.25
                and 黑油暗色 >= 0.35
                and 黑油非金 < 0.15
                and 黑油非紫 < 0.15
                and 黑油条明暗差 >= 40
            )
        except (AttributeError, TypeError, ValueError, cv2.error):
            return False

    @staticmethod
    def _是宝箱领奖背景(hsv: np.ndarray) -> bool:
        """识别 3D 木桌宝箱/魔法零食领奖背景（双侧暗角木桌、无草地）。"""
        高, 宽 = hsv.shape[:2]
        if 高 < 300 or 宽 < 400:
            return False
        左木 = hsv[int(高 * 0.60):int(高 * 0.95), int(宽 * 0.05):int(宽 * 0.32)]
        右木 = hsv[int(高 * 0.60):int(高 * 0.95), int(宽 * 0.68):int(宽 * 0.95)]
        if 左木.size == 0 or 右木.size == 0:
            return False

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

        if 木桌比例(左木) < 0.40 or 木桌比例(右木) < 0.40:
            return False

        上左 = hsv[int(高 * 0.02):int(高 * 0.18), int(宽 * 0.02):int(宽 * 0.32)]
        上右 = hsv[int(高 * 0.02):int(高 * 0.18), int(宽 * 0.68):int(宽 * 0.98)]
        if 上左.size == 0 or 上右.size == 0:
            return False
        暗度 = min(float((上左[:, :, 2] < 135).mean()), float((上右[:, :, 2] < 135).mean()))
        if 暗度 < 0.70:
            return False
        草地 = max(
            float(((上左[:, :, 0] >= 22) & (上左[:, :, 0] <= 48) & (上左[:, :, 1] >= 70)).mean()),
            float(((上右[:, :, 0] >= 22) & (上右[:, :, 0] <= 48) & (上右[:, :, 1] >= 70)).mean()),
        )
        return 草地 <= 0.15

    @classmethod
    def _结算页上下文确认(cls, 图像: np.ndarray) -> bool:
        """仅在非战斗、且具备结算结果结构与底部绿色回营按钮时确认结算上下文。"""
        if not isinstance(图像, np.ndarray) or 图像.ndim != 3 or 图像.shape[2] < 3:
            return False
        高, 宽 = 图像.shape[:2]
        if 高 < 300 or 宽 < 400:
            return False
        try:
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
            if cls._是宝箱领奖背景(hsv):
                return False

            # 1) 排除战斗左下红色放弃按钮
            放弃上 = int(高 * 0.67)
            放弃高 = max(1, int(高 * 0.22))
            放弃区 = hsv[放弃上:min(高, 放弃上 + 放弃高), 0:max(1, int(宽 * 0.22))]
            if 放弃区.size:
                放弃红 = (
                    ((放弃区[:, :, 0] <= 12) | (放弃区[:, :, 0] >= 170))
                    & (放弃区[:, :, 1] >= 90)
                    & (放弃区[:, :, 2] >= 80)
                ).astype(np.uint8)
                _, _, 放弃统计, _ = cv2.connectedComponentsWithStats(放弃红, 8)
                区宽 = 放弃区.shape[1]
                for x, y, w, h, area in 放弃统计[1:]:
                    if (
                        area >= 600
                        and w >= max(55, int(区宽 * 0.28))
                        and w <= max(55, int(区宽 * 0.82))
                        and h >= 20
                        and w / max(1, h) >= 1.5
                        and x <= max(40, int(区宽 * 0.25))
                        and y <= int(放弃区.shape[0] * 0.75)
                    ):
                        return False

            # 2) 排除战斗顶部倒计时（白色或红字倒计时）
            倒计时区 = hsv[0:int(高 * 0.18), int(宽 * 0.32):int(宽 * 0.72)]
            if 倒计时区.size:
                开核 = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                白字 = cv2.morphologyEx(
                    ((倒计时区[:, :, 1] <= 95) & (倒计时区[:, :, 2] >= 165)).astype(np.uint8),
                    cv2.MORPH_OPEN,
                    开核,
                )
                _, _, 字统计, _ = cv2.connectedComponentsWithStats(白字, 8)
                字符 = [
                    (x, y, w, h)
                    for x, y, w, h, area in 字统计[1:]
                    if area >= 20
                    and h >= max(12, int(高 * 0.018))
                    and h <= int(高 * 0.14)
                    and w >= 3
                    and y <= int(高 * 0.14)
                ]
                字符.sort(key=lambda 项: 项[0])
                大字 = [
                    项 for 项 in 字符
                    if 项[3] >= max(20, int(高 * 0.030))
                    and 项[1] >= int(高 * 0.035)
                ]
                for 序列, 间距上限, y容差 in (
                    (大字, max(24, int(宽 * 0.04)), max(12, int(高 * 0.022))),
                    (字符, max(28, int(宽 * 0.05)), max(14, int(高 * 0.025))),
                ):
                    for 前, 后 in zip(序列, 序列[1:]):
                        前y = 前[1] + 前[3] / 2
                        后y = 后[1] + 后[3] / 2
                        间距 = 后[0] - (前[0] + 前[2])
                        if (
                            -max(2, int(宽 * 0.005)) <= 间距 <= 间距上限
                            and abs(前y - 后y) <= y容差
                        ):
                            return False
                红字 = cv2.morphologyEx(
                    (
                        ((倒计时区[:, :, 0] <= 12) | (倒计时区[:, :, 0] >= 170))
                        & (倒计时区[:, :, 1] >= 90)
                        & (倒计时区[:, :, 2] >= 100)
                    ).astype(np.uint8),
                    cv2.MORPH_OPEN,
                    开核,
                )
                _, _, 红统计, _ = cv2.connectedComponentsWithStats(红字, 8)
                红字符 = [
                    (x, y, w, h)
                    for x, y, w, h, area in 红统计[1:]
                    if area >= 20
                    and h >= max(12, int(高 * 0.018))
                    and h <= int(高 * 0.14)
                    and w >= 3
                    and y <= int(高 * 0.14)
                ]
                红提示 = [项 for 项 in 红字符 if 项[1] <= int(高 * 0.08)]
                红数字 = [
                    项 for 项 in 红字符
                    if int(高 * 0.045) <= 项[1] <= int(高 * 0.13)
                    and 项[3] >= max(17, int(高 * 0.028))
                ]
                if len(红提示) >= 3 and 红数字:
                    return False

            # 3) 底部中央绿色回营按钮
            左, 右 = int(宽 * 0.38), int(宽 * 0.62)
            上, 下 = int(高 * 0.76), int(高 * 0.99)
            按钮区 = hsv[上:下, 左:右]
            if not 按钮区.size:
                return False
            绿色 = (
                (按钮区[:, :, 0] >= 30)
                & (按钮区[:, :, 0] <= 100)
                & (按钮区[:, :, 1] >= 70)
                & (按钮区[:, :, 2] >= 100)
            ).astype(np.uint8)
            if float(np.mean(绿色)) < 0.08:
                return False
            最小按钮面积 = max(3500, int(宽 * 高 * 0.008))

            def 存在回营按钮(掩码: np.ndarray, 最低填充: float = 0.0) -> bool:
                _, _, 统计, _ = cv2.connectedComponentsWithStats(掩码, 8)
                for _, _, bw, bh, area in 统计[1:]:
                    if (
                        area >= 最小按钮面积
                        and bw >= int(宽 * 0.12)
                        and bh >= int(高 * 0.06)
                        and bw / max(1, bh) >= 1.70
                        and bw <= int(宽 * 0.22)
                        and bh <= int(高 * 0.14)
                        and (最低填充 <= 0.0 or area >= bw * bh * 最低填充)
                    ):
                        return True
                return False

            绿色闭 = cv2.morphologyEx(
                绿色, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 5))
            )
            有回营按钮 = 存在回营按钮(绿色闭) or 存在回营按钮(绿色, 0.65)
            if not 有回营按钮:
                高亮绿 = (
                    (按钮区[:, :, 0] >= 30)
                    & (按钮区[:, :, 0] <= 100)
                    & (按钮区[:, :, 1] >= 85)
                    & (按钮区[:, :, 2] >= 140)
                ).astype(np.uint8)
                高亮闭 = cv2.morphologyEx(
                    高亮绿, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
                )
                有回营按钮 = 存在回营按钮(高亮闭, 0.65)
            if not 有回营按钮:
                return False

            # 4) 中央结算结果结构（宽金色横幅 或 星数/摧毁率亮色结构）
            横幅区 = hsv[int(高 * 0.16):int(高 * 0.58), int(宽 * 0.22):int(宽 * 0.78)]
            金色 = (
                (横幅区[:, :, 0] <= 38)
                & (横幅区[:, :, 1] >= 75)
                & (横幅区[:, :, 2] >= 100)
            ).astype(np.uint8)
            金色 = cv2.morphologyEx(
                金色, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5))
            )
            轮廓列表, _ = cv2.findContours(金色 * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for 轮廓 in 轮廓列表:
                _, _, w, h = cv2.boundingRect(轮廓)
                if w >= int(宽 * 0.36) and h >= int(高 * 0.08) and w / max(1, h) >= 2.0:
                    return True

            中央 = hsv[int(高 * 0.12):int(高 * 0.60), int(宽 * 0.20):int(宽 * 0.80)]
            亮色 = cv2.morphologyEx(
                ((中央[:, :, 1] < 90) & (中央[:, :, 2] > 175)).astype(np.uint8),
                cv2.MORPH_OPEN,
                np.ones((3, 3), dtype=np.uint8),
            )
            _, _, 亮统计, _ = cv2.connectedComponentsWithStats(亮色, 8)
            最小亮块 = max(80, int(中央.shape[0] * 中央.shape[1] * 0.00025))
            大亮块数 = sum(
                1
                for _, _, bw, bh, area in 亮统计[1:]
                if area >= 最小亮块 and bw >= max(8, int(宽 * 0.01)) and bh >= max(8, int(高 * 0.01))
            )
            return float(np.mean(亮色)) >= 0.014 and 大亮块数 >= 3
        except (AttributeError, TypeError, ValueError, cv2.error):
            return False

    def 识别(self, 屏幕图像: np.ndarray) -> 世界识别结果:
        """识别一张 800×600 逻辑截图，无法确认时返回 ``当前世界=None``。"""
        资源栏 = self._裁剪(屏幕图像, self.资源栏区域)
        主入口区域 = self._裁剪(屏幕图像, self.主世界入口区域)

        主资源分数 = self._最佳分数(资源栏, self.主世界资源模板)
        # 夜世界当前客户端的首个旧模板在实机截图上可能得到 0.89 左右，
        # 仍高于普通备用触发阈值，但新版模板才是明确的 0.95+ 命中。
        # 这里提高备用扫描触发点，避免只取首个模板而把夜世界误判为
        # 主世界蓝色徽章页面；额外扫描只涉及右上角小资源栏。
        夜资源分数 = self._最佳分数(
            资源栏,
            self.夜世界资源模板,
            备用触发分数=0.98,
        )
        主入口模板分数 = self._最佳分数(主入口区域, self.主世界入口模板)
        新版入口分数 = self._新版战斗入口分数(屏幕图像)
        主入口分数 = max(主入口模板分数, 新版入口分数)
        主徽章证据, 夜徽章证据 = self._徽章颜色证据(屏幕图像)

        # 某些 MuMu 测试服夜世界主页会保留蓝色的主账号等级徽章，
        # 但右上角夜世界资源栏已经是强证据。此时蓝色徽章不能再把
        # 主世界分数抬高，否则两套证据会被错误判成“未知”。反向同理，
        # 主世界资源栏高分时忽略残留的红色过渡徽章。
        主徽章证据 = 主徽章证据 and not (
            夜资源分数 >= 0.95 and 主资源分数 < self.资源图标阈值
        )
        夜徽章证据 = 夜徽章证据 and not (
            主资源分数 >= 0.95 and 夜资源分数 < self.资源图标阈值
        )
        # 新版主世界头像通知红点会落入左上角旧徽章扫描区。只有当
        # 主世界资源栏与新版左下战斗入口两个独立锚点都强命中，且
        # 夜世界资源栏没有命中时，红色小徽章才按通知标记处理。
        夜徽章证据 = 夜徽章证据 and not (
            主资源分数 >= self.资源图标阈值
            and 新版入口分数 >= 0.90
            and 夜资源分数 < self.资源图标阈值
        )

        主资源证据 = self._支持度(主资源分数, self.资源图标阈值)
        夜资源证据 = self._支持度(夜资源分数, self.资源图标阈值)
        主入口证据 = self._支持度(主入口分数, self.主世界入口阈值)

        # 入口是主世界的第二个独立 UI 信号。资源栏和入口都命中时，
        # 主世界得分最高；只有资源栏命中时仍可识别，但会降低置信度。
        主世界总分 = min(1.0, 0.68 * 主资源证据 + 0.32 * 主入口证据)
        夜世界总分 = 夜资源证据
        依据: list[str] = []
        if 主资源证据 > 0:
            依据.append(f"主世界资源栏{主资源分数:.2f}")
        if 夜资源证据 > 0:
            依据.append(f"夜世界资源栏{夜资源分数:.2f}")
        if 主入口证据 > 0:
            入口名称 = "新版战斗入口" if 新版入口分数 >= 主入口模板分数 else "主世界入口"
            依据.append(f"{入口名称}{主入口分数:.2f}")
        if 主徽章证据:
            主世界总分 = max(主世界总分, 0.78)
            依据.append("主世界蓝色等级徽章")
        if 夜徽章证据:
            夜世界总分 = max(夜世界总分, 0.78)
            依据.append("夜世界红色等级徽章")

        # 新版左下战斗卡片本身是受位置/尺寸约束的主页锚点。实机新版
        # 客户端上右上资源模板可稳定落在 0.94 左右，虽已越过模板阈值，
        # 原线性加权却只给出 0.56，低于所有主页入口的 0.70 安全复核门槛，
        # 使任务在真实主世界反复恢复失败。两项独立锚点同时强命中，且
        # 没有夜世界资源证据时，提升到可进入“两帧连续确认”的最低值；
        # 只有战斗卡片、资源栏弱命中时仍保持中等分，不放宽单帧安全门。
        if 新版入口分数 >= 0.90 and 夜资源分数 < 0.95:
            if 主资源分数 >= self.资源图标阈值:
                主世界总分 = max(主世界总分, 0.70)
            else:
                主世界总分 = max(主世界总分, 0.56)

        # 两个资源模板都很小，存在相互误匹配的可能；如果两套模板都在
        # 高分区，哪怕加权分数因主世界入口存在而略有偏差，也必须视为
        # 歧义。否则在资源栏动画/过渡帧上会把错误世界当成已确认。
        资源栏歧义 = (
            主资源分数 >= self.资源图标阈值
            and 夜资源分数 >= self.资源图标阈值
        )

        # 必须有足够分差，否则交给上层 ESC/船入口恢复，禁止在未知页面
        # 继续点按。
        if (
            not 资源栏歧义
            and
            主世界总分 >= self.最低世界分数
            and 主世界总分 - 夜世界总分 >= self.最低分差
        ):
            当前世界 = "主世界"
        elif (
            not 资源栏歧义
            and
            夜世界总分 >= self.最低世界分数
            and 夜世界总分 - 主世界总分 >= self.最低分差
        ):
            当前世界 = "夜世界"
        elif (
            not 资源栏歧义
            and not 夜徽章证据
            and 夜资源分数 < self.资源图标阈值
            and self._结算主资源下限 <= 主资源分数 < self.资源图标阈值
            and 主资源分数 - 夜资源分数 >= self._结算主夜最小分差
            and self._主世界三栏资源证据(资源栏)
            and self._结算页上下文确认(屏幕图像)
        ):
            # 结算页左下世界入口被遮挡、右上圣水图标因暗角/压缩仅略低于
            # 0.92 时，不放宽全局阈值，仅在同时确认“结算页上下文 + 主世界
            # 三栏资源栏（含黑油） + 明确主/夜模板分差”后判为主世界。
            主世界总分 = max(主世界总分, 0.58)
            依据.append(f"结算页主世界三栏资源栏{主资源分数:.2f}")
            依据.append("结算页回营结构")
            当前世界 = "主世界"
        else:
            当前世界 = None

        return 世界识别结果(
            当前世界=当前世界,
            主世界分数=主世界总分,
            夜世界分数=夜世界总分,
            主世界资源图标分数=主资源分数,
            夜世界资源图标分数=夜资源分数,
            主世界入口分数=主入口分数,
            依据=tuple(依据),
        )


from 工具包.识别参数 import 应用识别参数 as _应用识别参数

_应用识别参数(世界识别器, "主页")
