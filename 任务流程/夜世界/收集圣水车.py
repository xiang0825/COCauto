from dataclasses import dataclass

import cv2
import numpy as np
from 任务流程.基础任务框架 import 任务上下文
from 任务流程.夜世界.夜世界打鱼.夜世界基础任务类 import 夜世界基础任务
from 任务流程.世界跳转.世界识别器 import 世界识别器


@dataclass
class 滑动配置:
    起点: tuple[int, int]
    终点: tuple[int, int]


class 收集圣水车任务(夜世界基础任务):
    MAX_连续失败次数 = 5  # 定义最大允许失败次数常量
    收集圣水连续出错次数 = 0  # 初始化计数器
    船模板路径 = (
        "夜世界的船1.bmp|夜世界的船2.bmp|夜世界的船3.bmp|"
        "夜世界的船4.bmp|夜世界的船5.bmp|夜世界的船6.bmp|"
        "夜世界的船7.bmp|夜世界的船8.bmp|夜世界的船9.bmp|"
        "夜世界的船10.bmp|夜世界的船11.bmp|夜世界的船12.bmp"
    )

    # 新版夜世界（16:9 实拍）圣水车+紫色可收集气泡模板。只有车上有可收集
    # 圣水时才显示气泡，因此命中即代表“有圣水可收”。实拍自身 1.00，
    # 其它画面（含圣水收集器气泡）最高 0.56；阈值留足余量。
    圣水车模板路径 = "夜世界圣水车_16比9.bmp"
    圣水车模板最低分数 = 0.78
    # 模板中心（气泡与车之间）到车体可点击位置的偏移（逻辑画布）。
    圣水车点击偏移 = (2, 18)
    # 默认拉远镜头下圣水车在画面上方之外；只允许沿地图边缘的有限拖动，
    # 每次拖动后都重新确认仍在夜世界、未误开详情。
    最大边缘拖动次数 = 4
    圣水车搜索拖动路径 = (
        # 右侧地图边缘向下：把右上码头/圣水车带入画面。
        滑动配置((670, 150), (670, 400)),
        # 顶部地图边缘向左：把右侧岸边带入画面。
        滑动配置((650, 160), (250, 160)),
        滑动配置((670, 150), (670, 400)),
        # 反向恢复，避免镜头长期停在角落。
        滑动配置((670, 400), (670, 150)),
    )

    def __init__(self, 上下文: '任务上下文'):
        super().__init__(上下文)
        self._世界识别器 = 世界识别器(self.模板识别)
        # 已确认仍在夜世界但本轮没有找到可安全确认的圣水车，
        # 与页面/输入异常区分开；前者可以由外层跳过收集继续战斗。
        self._本轮未发现可收集圣水车 = False

    def 执行(self) -> bool:
        try:
            self._输入已拒绝 = False
            self._本轮未发现可收集圣水车 = False
            self._收集已点击 = False
            找不到夜世界船的次数 = 0
            最大扫描次数 = 5
            已拖动次数 = 0

            while 找不到夜世界船的次数 < 最大扫描次数:
                if getattr(self.上下文, "停止事件", None) is not None and self.上下文.停止事件.is_set():
                    self.上下文.置脚本状态("收到停止请求，停止圣水车扫描")
                    return False
                if not self._夜世界仍在前台():
                    self.上下文.置脚本状态(
                        "收集圣水车前未确认仍在夜世界，停止所有候选点击",
                        级别="警告",
                    )
                    return False

                # 新版：直接定位“圣水车+可收集气泡”。命中后点击车体并
                # 必须通过“聖水車”标题 OCR 才会点收集按钮。
                车命中, 车坐标, 车分数 = self._查找圣水车模板()
                if 车命中:
                    点击x, 点击y = 车坐标
                    self.上下文.置脚本状态(
                        f"已定位圣水车（模板分数{车分数:.2f}），点击车体{点击x},{点击y}并用标题 OCR 确认"
                    )
                    if self.上下文.点击(点击x, 点击y) is False:
                        self.上下文.置脚本状态(
                            "圣水车点击被安全输入层拒绝，停止本次收集",
                            级别="警告",
                        )
                        return False
                    self.上下文.脚本延时(600)
                    if self.尝试收集圣水():
                        self.上下文.置脚本状态(f"已确认圣水车面板并完成收集：{点击x},{点击y}")
                        return True
                    if self._输入已拒绝 or getattr(self, "_收集已点击", False):
                        return False
                    self._关闭候选详情面板()
                    if self._输入已拒绝 or not self._夜世界仍在前台():
                        return False
                    self._本轮未发现可收集圣水车 = True
                    self.上下文.置脚本状态(
                        "圣水车模板命中但未确认圣水车面板；本周期跳过，不再尝试其它点",
                        级别="警告",
                    )
                    return False

                是否匹配, (x, y), 船分数 = self._查找海岸船锚点()

                if 是否匹配:
                    if self.是否在危险区域内(x, y):
                        self.上下文.置脚本状态("圣水车位于危险区域，跳过收集")
                        self._处理失败()
                        return False

                    self.上下文.置脚本状态(
                        f"定位到海岸船锚点（模板分数{船分数:.2f}），"
                        "点击船旁圣水车候选点并用标题 OCR 确认"
                    )
                    候选点 = self._生成圣水车候选点(x, y)
                    for 序号, (点击x, 点击y, 来源) in enumerate(候选点, 1):
                        self.上下文.置脚本状态(
                            f"尝试打开圣水车：第{序号}个候选点{点击x},{点击y}（{来源}）"
                        )
                        if self.上下文.点击(点击x, 点击y) is False:
                            self.上下文.置脚本状态(
                                "圣水车候选点点击被安全输入层拒绝，停止剩余候选点击",
                                级别="警告",
                            )
                            return False
                        if self.尝试收集圣水():
                            self.上下文.置脚本状态(
                                f"已确认圣水车面板并完成收集：{点击x},{点击y}"
                            )
                            return True
                        if self._输入已拒绝 or getattr(self, "_收集已点击", False):
                            # 收集已点下但未确认回到主页：不再点击其它候选。
                            return False
                        # 点击候选点可能打开了普通建筑详情页。不能把下一
                        # 个地图坐标继续点在详情页上，否则会把后续输入带到
                        # 错误页面。只在右上角明确识别到红色关闭按钮时关闭，
                        # 不发送无条件 ESC，避免退回主世界或模拟器桌面。
                        self._关闭候选详情面板()
                        if self._输入已拒绝:
                            return False
                        if not self._夜世界仍在前台():
                            self.上下文.置脚本状态(
                                "圣水车候选点击后已回到主世界，停止剩余候选点击",
                                级别="警告",
                            )
                            return False

                    self.上下文.置脚本状态(
                        "未成功打开圣水车界面，已尝试动态气泡和全部安全备用点；"
                        "不点击宝石或商店，保留当前夜世界画面",
                        级别="警告",
                    )
                    if not self._夜世界仍在前台():
                        self.上下文.置脚本状态(
                            "圣水车候选全部未命中且无法再次确认夜世界，停止后续输入",
                            级别="警告",
                        )
                        return False
                    # 点击被接受但未打开圣水车面板属于可重试漏检：本
                    # 周期跳过收集，让外层继续资源流程；下一次周期再
                    # 重新定位，不把一次漏点升级为整个夜世界任务失败。
                    self._本轮未发现可收集圣水车 = True
                    self.上下文.置脚本状态(
                        "圣水车候选均未打开面板，确认仍在夜世界；跳过本周期并留待下次重试",
                        级别="警告",
                    )
                    return False

                else:
                    # 新版夜世界主页可能没有旧版“船”局部素材，但可
                    # 收集的圣水车仍会显示紫色资源气泡。旧流程只有在
                    # 船模板命中后才扫描气泡，结果会在实机上无意义地
                    # 滑动五轮。动态候选同样必须逐点经过标题 OCR 和
                    # 夜世界复核，不能把颜色命中直接当成圣水车。
                    动态候选点 = self._生成动态紫色候选点()
                    if 动态候选点:
                        self.上下文.置脚本状态(
                            f"旧版船模板未命中，发现{len(动态候选点)}个动态资源气泡；"
                            "仅用于定位后拖动地图，不直接点击，避免误开资源建筑或离开夜世界"
                        )
                        # 紫色气泡也可能属于储存罐、建筑或升级提示。当前
                        # 版本无法仅凭颜色证明它就是圣水车；若在此直接点
                        # 击，错误坐标可能把输入送到世界切换入口/系统边
                        # 缘。真正可点击的圣水车必须先由船模板命中并在
                        # 面板 OCR 中确认，动态候选只用于决定下一次拖动。
                        self.上下文.置脚本状态(
                            "动态资源气泡未达到可点击置信度，继续安全搜索；禁止误点"
                        )
                    找不到夜世界船的次数 += 1
                    self.上下文.置脚本状态(
                        f"定位圣水车位置中... ({找不到夜世界船的次数}/{最大扫描次数})"
                    )
                    # 这里曾在每次未命中后无条件发送一指拖动。MuMu 的
                    # organized display 在触摸设备短暂失去响应时会把这次
                    # ADB 输入拖到超时，任务线程因此长时间没有心跳，表现
                    # 为“卡在夜世界主页”。圣水车未被可靠定位时，继续盲目
                    # 拖图也不能证明下一帧仍是夜世界；达到有限次数后安全
                    # 返回，由外层停止后续进攻并保留当前画面。
                    if 找不到夜世界船的次数 >= 最大扫描次数:
                        self.上下文.置脚本状态(
                            "有限扫描仍未确认圣水车；已连续确认仍在夜世界，"
                            "本轮跳过圣水车收集，不再发送拖动或其它点击",
                            级别="警告",
                        )
                        self._本轮未发现可收集圣水车 = True
                        return False

                    if 已拖动次数 < self.最大边缘拖动次数:
                        路径 = self.圣水车搜索拖动路径[已拖动次数 % len(self.圣水车搜索拖动路径)]
                        已拖动次数 += 1
                        self.上下文.置脚本状态(
                            f"未确认圣水车，沿地图边缘拖动搜索（{已拖动次数}/{self.最大边缘拖动次数}）"
                        )
                        if not self._边缘拖动(路径):
                            return False
                        continue
                    self.上下文.置脚本状态("未确认圣水车，边缘拖动次数已用完，短暂等待后重试")
                    self.上下文.脚本延时(250)
            self.上下文.置脚本状态(
                "圣水车扫描已达到安全上限，保留当前夜世界画面",
                级别="警告",
            )
            return False
        except RuntimeError as e:
            self.异常处理(e)
            return False

    def _查找海岸船锚点(self):
        """在已确认的夜世界地图区寻找船，只返回安全的海岸锚点。

        旧实现对整张画面调用 ``是否出现图片``。船模板很小，资源栏和
        建筑纹理也能得到相似分数，且船移动到顶部时会被 UI 遮挡。这里
        限制到游戏地图区，再用最佳模板分数和几何范围确认；返回的船坐标
        只用于推导船旁圣水车位置，绝不把船本身当作收集按钮。
        """
        try:
            屏幕 = self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            if not isinstance(屏幕, np.ndarray) or 屏幕.ndim < 2 or not 屏幕.size:
                return False, (0, 0), 0.0
            高, 宽 = 屏幕.shape[:2]
            左, 上 = max(0, int(宽 * 0.10)), max(0, int(高 * 0.08))
            右, 下 = min(宽, int(宽 * 0.94)), min(高, int(高 * 0.94))
            区域 = 屏幕[上:下, 左:右]
            最佳匹配 = getattr(self.模板识别, "执行最佳匹配", None)
            if not callable(最佳匹配) or 区域.size == 0:
                return False, (0, 0), 0.0
            分数, 中心, _ = 最佳匹配(区域, self.船模板路径)
            分数 = float(分数)
            全局x = int(round(float(中心[0]))) + 左
            全局y = int(round(float(中心[1]))) + 上
            # 船是海岸地图物体；顶部资源栏和左右固定 UI 不得成为锚点。
            # 实机复测发现右上资源栏纹理可得到约 0.68 的低分假匹配；
            # 真实可见船锚点通常在 0.90 以上，因此提高最低分并抬高
            # 地图顶部边界，避免把资源栏当成船旁圣水车的参考点。
            if (
                分数 < 0.78
                or not (100 <= 全局x <= 730 and int(高 * 0.17) <= 全局y <= 560)
            ):
                return False, (0, 0), 分数
            return True, (全局x, 全局y), 分数
        except (AttributeError, TypeError, ValueError, cv2.error):
            return False, (0, 0), 0.0

    def _查找圣水车模板(self):
        """在地图区查找“圣水车+可收集气泡”，返回可点击车体坐标。

        原尺度优先；非 16:9 设备再按几何尺度回退。命中中心或点击点落在
        主页 HUD（资源栏、商店、战斗/建造入口等）内一律拒绝。
        """
        try:
            from 模块.画面几何 import 点在主页HUD内, 区域与主页HUD重叠

            屏幕 = self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            if not isinstance(屏幕, np.ndarray) or 屏幕.ndim < 3 or not 屏幕.size:
                return False, (0, 0), 0.0
            # 原尺度优先；原尺度未达阈值才按设备几何尺度回退，阈值不变。
            匹配 = getattr(self.模板识别, "执行原尺度优先匹配", None)
            if not callable(匹配):
                return False, (0, 0), 0.0
            命中, 分数, 中心, _, _, 命中框 = 匹配(
                屏幕, self.圣水车模板路径, self.圣水车模板最低分数
            )
            分数 = float(分数)
            if not 命中 or 命中框 is None:
                return False, (0, 0), 分数
            中心x, 中心y = int(中心[0]), int(中心[1])
            点击x = max(12, min(788, 中心x + self.圣水车点击偏移[0]))
            点击y = max(12, min(588, 中心y + self.圣水车点击偏移[1]))
            if 区域与主页HUD重叠(命中框) or 点在主页HUD内(点击x, 点击y):
                self.上下文.置脚本状态(
                    f"圣水车候选{点击x},{点击y}与 HUD 重叠，禁止点击，改为拖动地图"
                )
                return False, (0, 0), 分数
            return True, (点击x, 点击y), 分数
        except (AttributeError, TypeError, ValueError, cv2.error):
            return False, (0, 0), 0.0

    def _边缘拖动(self, 路径: 滑动配置) -> bool:
        """沿地图边缘做一次直线拖动；完成后复核夜世界与误开详情。"""
        try:
            鼠标 = self.上下文.鼠标
            起x, 起y = 路径.起点
            终x, 终y = 路径.终点
            步数 = 24
            鼠标.移动到(起x, 起y)
            鼠标.左键按下()
            for 序号 in range(1, 步数 + 1):
                比例 = 序号 / 步数
                鼠标.移动到(
                    int(round(起x + (终x - 起x) * 比例)),
                    int(round(起y + (终y - 起y) * 比例)),
                )
                self.上下文.脚本延时(16)
            鼠标.左键抬起()
        except Exception as 异常:
            self.上下文.置脚本状态(f"圣水车边缘拖动失败，停止搜索：{异常}", 级别="警告")
            return False
        self.上下文.脚本延时(700)
        关闭意外详情 = getattr(self.上下文, "关闭意外英雄升级详情弹窗", None)
        if callable(关闭意外详情):
            try:
                if 关闭意外详情():
                    self.上下文.置脚本状态("拖动误开详情已安全关闭，停止本轮圣水车搜索")
                    return False
            except Exception:
                return False
            if getattr(self.上下文, "_意外英雄详情已检测", False):
                return False
        if not self._夜世界仍在前台():
            self.上下文.置脚本状态(
                "圣水车拖动后未确认仍在夜世界，停止搜索", 级别="警告"
            )
            return False
        return True

    def _夜世界仍在前台(self) -> bool:
        """在每个候选点击边界确认仍处于夜世界。"""
        try:
            屏幕 = self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            结果 = self._世界识别器.识别(屏幕)
            if 结果.当前世界 == "夜世界":
                return True
            self.上下文.置脚本状态(
                f"圣水车流程页面复核失败：当前={结果.当前世界 or '未知'}；禁止继续点击"
            )
            return False
        except (AttributeError, TypeError, ValueError, cv2.error) as 异常:
            self.上下文.置脚本状态(f"圣水车流程页面复核异常，禁止继续点击：{异常}")
            return False

    def _生成圣水车候选点(self, 船x: int, 船y: int):
        """返回按安全顺序排列的圣水车点击点。

        旧实现只尝试一个偏移，而且只识别简体标题。当前 MuMu 实机的
        圣水车面板标题是“聖水車”，并且已确认船模板偏移1可以打开面板。
        现在只尝试船锚点附近的三个安全车位；动态紫色气泡仅作搜索提示，
        不加入点击队列，避免把建筑气泡或世界切换船误当成收集入口。
        """
        候选: list[tuple[int, int, str]] = []
        # 实机验证过的船模板相对位置必须优先，不能让地图中的紫色建筑
        # 气泡抢先被点击；紫色气泡不是圣水车，可能只会打开建筑详情页。
        for 备用x, 备用y, 来源 in (
            (船x - 118, 船y + 46, "船模板兼容偏移1"),
            (船x - 104, 船y + 58, "船模板兼容偏移2"),
            (船x - 132, 船y + 34, "船模板兼容偏移3"),
        ):
            候选.append((备用x, 备用y, 来源))

        已有 = set()
        安全候选 = []
        for 候选x, 候选y, 来源 in 候选:
            候选x = max(12, min(788, int(候选x)))
            候选y = max(12, min(588, int(候选y)))
            关键 = (round(候选x / 8), round(候选y / 8))
            if 关键 in 已有:
                continue
            已有.add(关键)
            安全候选.append((候选x, 候选y, 来源))
        return 安全候选

    def _生成动态紫色候选点(self):
        """只扫描当前画面的紫色资源气泡，不依赖旧船模板。"""
        try:
            屏幕 = self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            if not isinstance(屏幕, np.ndarray) or 屏幕.ndim < 2 or not 屏幕.size:
                return []
            高, 宽 = 屏幕.shape[:2]
            x左, x右 = max(0, int(宽 * 0.09)), min(宽, int(宽 * 0.91))
            y上, y下 = max(0, int(高 * 0.25)), min(高, int(高 * 0.90))
            地图 = 屏幕[y上:y下, x左:x右]
            if not 地图.size:
                return []
            hsv = cv2.cvtColor(地图, cv2.COLOR_BGR2HSV)
            遮罩 = cv2.inRange(
                hsv,
                np.array((125, 80, 70), dtype=np.uint8),
                np.array((175, 255, 255), dtype=np.uint8),
            )
            遮罩 = cv2.morphologyEx(
                遮罩,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
            )
            数量, _, 统计, 重心 = cv2.connectedComponentsWithStats(遮罩, 8)
            气泡 = []
            最小面积 = max(120, int(宽 * 高 * 0.00018))
            for 索引 in range(1, 数量):
                _, _, 方宽, 方高, 面积 = [int(v) for v in 统计[索引]]
                if 面积 < 最小面积:
                    continue
                if 方宽 < 8 or 方高 < 8 or 方宽 > 宽 * 0.16 or 方高 > 高 * 0.16:
                    continue
                if not 0.35 <= 方宽 / max(1, 方高) <= 2.8:
                    continue
                中心x, 中心y = 重心[索引]
                气泡.append((int(面积), int(round(中心x + x左)), int(round(中心y + y上))))
            已有 = set()
            安全候选 = []
            for _, 气泡x, 气泡y in sorted(气泡, reverse=True)[:4]:
                气泡x = max(12, min(788, int(气泡x)))
                气泡y = max(12, min(588, int(气泡y)))
                关键 = (round(气泡x / 8), round(气泡y / 8))
                if 关键 in 已有:
                    continue
                已有.add(关键)
                安全候选.append((气泡x, 气泡y, "动态紫色资源气泡"))
            return 安全候选
        except (AttributeError, TypeError, ValueError, cv2.error) as 异常:
            self.上下文.置脚本状态(f"圣水气泡扫描失败，跳过动态候选：{异常}")
            return []

    def _关闭候选详情面板(self) -> bool:
        """关闭候选点击误打开的游戏内详情面板，不触碰宝石/商店。"""
        try:
            屏幕 = self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            关闭点 = self._检测详情面板关闭点(屏幕)
            if 关闭点 is None:
                return False
            self.上下文.置脚本状态(
                f"候选点打开了非圣水车面板，安全点击右上角关闭：{关闭点[0]},{关闭点[1]}"
            )
            点击安全 = getattr(self.上下文, "点击已确认安全按钮", None)
            if callable(点击安全):
                成功 = 点击安全(*关闭点, 延时=180)
            else:
                成功 = self.上下文.点击(*关闭点, 延时=180, 是否精确点击=True)
            if 成功 is False:
                self._输入已拒绝 = True
                self.上下文.置脚本状态("候选详情面板关闭被拒绝，停止剩余候选点击")
                return False
            return True
        except (AttributeError, TypeError, ValueError, cv2.error) as 异常:
            self.上下文.置脚本状态(f"详情面板关闭预检失败，停止候选尝试：{异常}")
            return False

    @staticmethod
    def _检测详情面板关闭点(屏幕) -> tuple[int, int] | None:
        """识别游戏内右上角红色 X，排除夜世界主页的常驻控件。"""
        if not isinstance(屏幕, np.ndarray) or 屏幕.ndim < 3:
            return None
        高, 宽 = 屏幕.shape[:2]
        if 高 < 100 or 宽 < 240:
            return None
        hsv = cv2.cvtColor(屏幕, cv2.COLOR_BGR2HSV)
        x左, x右 = int(宽 * 0.76), int(宽 * 0.98)
        y下 = int(高 * 0.18)
        区域 = hsv[:y下, x左:x右]
        红色 = cv2.inRange(
            区域,
            np.array((0, 105, 105), dtype=np.uint8),
            np.array((15, 255, 255), dtype=np.uint8),
        )
        红色 |= cv2.inRange(
            区域,
            np.array((165, 105, 105), dtype=np.uint8),
            np.array((180, 255, 255), dtype=np.uint8),
        )
        红色 = cv2.morphologyEx(
            红色, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        )
        数量, _, 统计, 重心 = cv2.connectedComponentsWithStats(红色, 8)
        候选 = []
        for 索引 in range(1, 数量):
            _, _, 方宽, 方高, 面积 = [int(v) for v in 统计[索引]]
            中心x, 中心y = 重心[索引]
            中心x += x左
            if (
                面积 >= max(120, int(宽 * 高 * 0.00025))
                # 使用整数下限，避免 800*0.035 的浮点舍入把 28 像素
                # 的真实关闭按钮误判为 27.999...
                and 方宽 >= max(12, int(宽 * 0.035))
                and 方高 >= max(12, int(高 * 0.035))
                and 0.55 <= 方宽 / max(1, 方高) <= 1.8
                and 中心x >= 宽 * 0.80
                # y<28 的红色像素可能来自 Android 状态栏/截图边缘，
                # 点击它会把输入送出游戏画面；详情面板关闭按钮必须完整
                # 位于游戏画布内。
                and 高 * 0.045 <= 中心y <= 高 * 0.14
            ):
                候选.append((面积, int(round(中心x)), int(round(中心y))))
        if not 候选:
            return None
        _, x, y = max(候选, key=lambda 项: 项[0])
        return x, y

    def 尝试收集圣水(self):
        识别结果 = self.执行OCR识别((328, 92, 489, 131))
        if not self._是否圣水车标题(识别结果):
            识别结果 = self.执行OCR识别((220, 55, 580, 190))
        if not self._是否圣水车标题(识别结果):
            return False

        # 面板标题已经确认后才允许找“收集”按钮；按钮中心优先取 OCR
        # 文本框，窗口比例或语言变化时仍使用参考画布坐标作为安全兜底。
        按钮OCR = self.执行OCR识别((420, 390, 680, 560))
        收集点 = self._查找OCR文本中心(按钮OCR, ("收集",), 最小y=350)
        # 页面识别器给出的绿色收集按钮框是输入护栏放行的唯一区域；
        # OCR 点落在框外（或 OCR 未命中）时改用按钮框中心。
        按钮框 = self._圣水车收集按钮框()
        if 按钮框 is not None:
            左, 上, 右, 下 = 按钮框
            if 收集点 is None or not (左 <= 收集点[0] <= 右 and 上 <= 收集点[1] <= 下):
                收集点 = ((左 + 右) // 2, (上 + 下) // 2)
        if 收集点 is None:
            收集点 = (588, 507)
        if self.上下文.点击(*收集点) is False:
            self._输入已拒绝 = True
            self.上下文.置脚本状态(
                "圣水车收集按钮点击被安全输入层拒绝，停止本次收集",
                级别="警告",
            )
            return False
        # 收集已点下：此后无论关闭结果如何都不能再去点其它候选点。
        self._收集已点击 = True
        self.上下文.脚本延时(1000)

        if not self._关闭圣水车面板并确认主页():
            return False
        self.收集圣水连续出错次数 = 0
        return True

    def _圣水车收集按钮框(self):
        """用页面识别器在当前帧定位收集按钮框（800×600 逻辑坐标）。"""
        try:
            获取识别器 = getattr(self.上下文, "_获取点击页面识别器", None)
            if not callable(获取识别器):
                return None
            屏幕 = self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            按钮 = 获取识别器().定位圣水车弹窗按钮(屏幕)
            if not 按钮 or 按钮.get("收集") is None:
                return None
            高, 宽 = 屏幕.shape[:2]
            左, 上, 右, 下 = 按钮["收集"]
            return (
                int(左 * 800 / 宽), int(上 * 600 / 高),
                int(右 * 800 / 宽), int(下 * 600 / 高),
            )
        except Exception:
            return None

    def _关闭圣水车面板并确认主页(self) -> bool:
        """收集后关闭圣水车面板（若仍在）并确认回到夜世界主页。

        只在页面识别器仍确认圣水车弹窗时点击其右上角 X；最多三轮，
        每轮重新截图。其它弹窗、未知页均停止，不借用通用红色 X。
        """
        获取识别器 = getattr(self.上下文, "_获取点击页面识别器", None)
        if not callable(获取识别器):
            self._输入已拒绝 = True
            self.上下文.置脚本状态("圣水车关闭后缺少页面识别器，停止后续输入", 级别="警告")
            return False
        for _ in range(3):
            try:
                屏幕 = self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)
                识别器 = 获取识别器()
                页面 = 识别器.识别(屏幕, 战斗中=False)
            except Exception as 异常:
                self._输入已拒绝 = True
                self.上下文.置脚本状态(
                    f"圣水车关闭后页面复核失败，停止后续输入：{异常}", 级别="警告"
                )
                return False
            当前页 = getattr(页面, "页面", "")
            if 当前页 == "夜世界主页":
                self.上下文.置脚本状态("圣水车已收集，已确认回到夜世界主页")
                return True
            if 当前页 != "圣水车弹窗":
                self._输入已拒绝 = True
                self.上下文.置脚本状态(
                    f"圣水车收集后当前页面为{当前页 or '未知'}，不点击其它弹窗；停止后续输入",
                    级别="警告",
                )
                return False
            try:
                按钮 = 识别器.定位圣水车弹窗按钮(屏幕)
                关闭框 = 按钮.get("关闭") if 按钮 else None
                if 关闭框 is None:
                    self._输入已拒绝 = True
                    self.上下文.置脚本状态(
                        "圣水车弹窗关闭按钮无法在当前帧定位，停止后续输入",
                        级别="警告",
                    )
                    return False
                高, 宽 = 屏幕.shape[:2]
                左, 上, 右, 下 = 关闭框
                关闭点 = (
                    int(round((左 + 右) / 2 * 800.0 / 宽)),
                    int(round((上 + 下) / 2 * 600.0 / 高)),
                )
            except Exception as 异常:
                self._输入已拒绝 = True
                self.上下文.置脚本状态(
                    f"圣水车关闭按钮定位失败，停止后续输入：{异常}", 级别="警告"
                )
                return False
            self.上下文.置脚本状态(
                f"安全点击已确认圣水车弹窗关闭X：{关闭点[0]},{关闭点[1]}"
            )
            点击安全 = getattr(self.上下文, "点击已确认安全按钮", None)
            if callable(点击安全):
                关闭成功 = 点击安全(*关闭点, 延时=180)
            else:
                关闭成功 = self.上下文.点击(
                    *关闭点, 延时=180, 是否精确点击=True
                )
            if 关闭成功 is False:
                self._输入已拒绝 = True
                self.上下文.置脚本状态(
                    "圣水车面板关闭点击被安全输入层拒绝，保留当前面板",
                    级别="警告",
                )
                return False
            self.上下文.脚本延时(500)
        self.上下文.置脚本状态(
            "圣水车已点击收集，但关闭面板后未确认回到夜世界主页，停止后续点击",
            级别="警告",
        )
        self._输入已拒绝 = True
        return False

    # 标题 OCR 低于该置信度视为“没认出”，不点击收集按钮。
    标题OCR最低置信度 = 0.60

    @staticmethod
    def _是否圣水车标题(识别结果) -> bool:
        可信结果 = []
        for 项 in 识别结果 or []:
            try:
                置信度 = float(项[2]) if len(项) > 2 else 0.0
            except (TypeError, ValueError):
                置信度 = 0.0
            if 置信度 >= 收集圣水车任务.标题OCR最低置信度:
                可信结果.append(项)
        return 收集圣水车任务._是否包含任一文本(
            可信结果, ("圣水车", "聖水車")
        )

    @staticmethod
    def _是否包含任一文本(识别结果, 目标文本) -> bool:
        for 项 in 识别结果 or []:
            if len(项) > 1:
                文本 = str(项[1]).replace(" ", "").replace("\n", "")
                if any(str(目标).replace(" ", "") in 文本 for 目标 in 目标文本):
                    return True
        return False

    @staticmethod
    def _查找OCR文本中心(识别结果, 目标文本, 最小y: int = 0):
        for 项 in 识别结果 or []:
            if len(项) < 2:
                continue
            文本 = str(项[1]).replace(" ", "").replace("\n", "")
            if not any(str(目标).replace(" ", "") in 文本 for 目标 in 目标文本):
                continue
            try:
                框 = 项[0]
                点列表 = [(float(点[0]), float(点[1])) for 点 in 框]
                if len(点列表) < 2:
                    continue
                x = int(round(sum(点[0] for 点 in 点列表) / len(点列表)))
                y = int(round(sum(点[1] for 点 in 点列表) / len(点列表)))
                if y >= 最小y:
                    return x, y
            except (TypeError, ValueError, IndexError):
                continue
        return None

    @staticmethod
    def 是否在危险区域内(x, y) -> bool:
        """检查坐标是否在宝石购买按钮区域"""
        return 744 <= x <= 794 and 225 <= y <= 274

    def _处理失败(self):
        """处理收集失败的情况"""
        self.收集圣水连续出错次数 += 1
        self.上下文.置脚本状态(f"收集失败次数: {self.收集圣水连续出错次数}/{self.MAX_连续失败次数}")
        # 检查是否超过最大失败次数
        if self.收集圣水连续出错次数 >= self.MAX_连续失败次数:
            raise RuntimeError(f"收集圣水连续失败超过{self.MAX_连续失败次数}次")

    def 是否包含文本(self, result: list, target: str) -> bool:
        for item in result:
            if len(item) > 1 and target in str(item[1]):
                return True
        return False
