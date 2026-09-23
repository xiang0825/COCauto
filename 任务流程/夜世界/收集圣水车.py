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

    def __init__(self, 上下文: '任务上下文'):
        super().__init__(上下文)
        self._世界识别器 = 世界识别器(self.模板识别)

    def 执行(self) -> bool:
        try:
            self._输入已拒绝 = False
            找不到夜世界船的次数 = 0

            while True:
                if not self._夜世界仍在前台():
                    self.上下文.置脚本状态(
                        "收集圣水车前未确认仍在夜世界，停止所有候选点击",
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
                        if self._输入已拒绝:
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
                    self.上下文.置脚本状态("未成功打开圣水车界面，收集失败, 拉远视距尝试")
                    self.上下文.游戏内拉远视距(次数=1)
                    self.上下文.脚本延时(200)
                    self._处理失败()
                    # self.上下文.键盘.按字符按压("esc")
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
                    self.上下文.置脚本状态(f"定位圣水车位置中... ({找不到夜世界船的次数},最大重试5次)")
                    self.上下文.滑动屏幕((595, 182), (135, 250))  # 滑动屏幕寻找


                    if 找不到夜世界船的次数 > 5:
                        raise RuntimeError("无法定位圣水车位置")
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
        if 收集点 is None:
            收集点 = (588, 507)
        if self.上下文.点击(*收集点) is False:
            self._输入已拒绝 = True
            self.上下文.置脚本状态(
                "圣水车收集按钮点击被安全输入层拒绝，停止本次收集",
                级别="警告",
            )
            return False
        self.上下文.脚本延时(1000)

        # 只识别并点击面板右上角红色 X；不使用旧固定关闭坐标，避免
        # 坐标漂移时点到资源栏或宝石区域。
        try:
            屏幕 = self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            关闭点 = self._检测详情面板关闭点(屏幕)
        except (AttributeError, TypeError, ValueError, cv2.error):
            关闭点 = None
        if 关闭点 is not None:
            点击安全 = getattr(self.上下文, "点击已确认安全按钮", None)
            if callable(点击安全):
                关闭成功 = 点击安全(*关闭点, 延时=180)
            else:
                关闭成功 = self.上下文.点击(*关闭点, 延时=180, 是否精确点击=True)
            if 关闭成功 is False:
                self._输入已拒绝 = True
                self.上下文.置脚本状态(
                    "圣水车面板关闭点击被安全输入层拒绝，保留当前面板",
                    级别="警告",
                )
                return False
        self.收集圣水连续出错次数 = 0
        return True

    @staticmethod
    def _是否圣水车标题(识别结果) -> bool:
        return 收集圣水车任务._是否包含任一文本(
            识别结果, ("圣水车", "聖水車")
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
