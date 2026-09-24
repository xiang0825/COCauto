import re
import math
import time

import cv2
import numpy as np

from 任务流程.基础任务框架 import 基础任务


class 打开研究面板任务(基础任务):
    """检查实验室状态并打开研究面板"""

    # ==================== 界面坐标常量 ====================
    实验室状态区域 = (268, 9, 332, 48)
    全屏区域 = (0, 0, 800, 600)
    # 研究入口不是顶部的活动/奖励图标。旧坐标会打开“活动特惠”，
    # 随后研究 OCR 在主世界上无限重试。现在先通过 OCR 找到地图上的
    # “研究”标签，选中实验室，再点击选中卡片中的“研究”按钮。
    # 拉远视距后实验室标签很小；只在地图下半区做局部放大 OCR。
    # 研究入口不能使用固定建筑坐标：同一坐标在镜头轻微移动后可能落到
    # 城墙、迫击炮或陷阱。任何候选点都必须先选中并 OCR 确认“实验室”。
    # 拉远视距后实验室标签会落到地图下半区；不同宽高比和镜头位置
    # 可能把它推到 y=450 左右，旧区域下边界 430 会稳定漏检。
    建筑标签搜索区域 = (200, 300, 700, 520)
    # MuMu 800×600 拉远画面中，实验室底部的“研究”标签有时会落在
    # x≈417、y≈485；窄裁剪在该位置可能被地图纹理吞掉。只有首轮
    # 没有任何候选时才使用这块更大的下半区回退，避免每次正常运行
    # 都增加一次 4 倍 OCR；候选仍必须经过选中卡片的“研究”按钮复核。
    建筑标签搜索回退区域 = (160, 240, 760, 570)
    研究按钮搜索区域 = (300, 360, 700, 580)
    局部OCR放大倍数 = 4
    实验室标题关键词 = ("实验室", "實驗室")
    # OCR 框是飘在建筑上方的标签，不一定落在建筑实体上；不同缩放下
    # 实验室相对标签会向右下或右上偏移。每个候选最多尝试这一组有限
    # 偏移，并且每次都用“实验室”标题复核，禁止无限扫图或误点升级。
    研究入口偏移候选 = (
        (0, 13), (0, 20), (15, 0), (25, -7),
        (25, 0), (15, 8), (-10, 13),
    )
    最大入口等待秒 = 6.0

    def 执行(self) -> bool:
        try:
            # 每次重新进入研究任务都先撤销上一轮授权；只有本轮实际
            # 识别到目标选择页后才重新放行研究面板内的点击。
            setattr(self.上下文, "_研究面板已确认", False)
            if not self._清理残留研究面板():
                self.上下文.置脚本状态(
                    "研究任务开始前未能清理残留研究面板，禁止扫描实验室"
                )
                return False
            if not self._清理普通建筑详情():
                self.上下文.置脚本状态(
                    "研究任务开始前未能安全关闭普通建筑详情，禁止扫描实验室"
                )
                return False
            if self._检查实验室是否空闲():
                return self._打开研究入口()
            return False
        except Exception as e:
            # 转场帧可能只有单个数字或 OCR 为空；无法确认实验室状态
            # 时必须安全跳过，不能把页面上的任何坐标当作研究入口。
            self.上下文.置脚本状态(f"研究面板状态暂时无法确认，已安全跳过：{e}")
            return False

    def _清理残留研究面板(self) -> bool:
        """清理上一次中断遗留的研究目标页，并确认回到主世界。

        研究目标页会保留主世界资源栏，通用页识别器因此可能把它误判为
        主世界。若测试中途停止，下一轮就会在目标页上扫描实验室并被点击
        护栏拒绝。这里仅在 OCR 已确认“选择升级目标”时点击研究页自己的
        红色 X；随后点击地图空白处取消实验室详情卡，绝不发送 ESC，避免
        从实验室详情页触发 CoC 的“确认退出游戏”对话框。
        """
        # 没有截图/OCR适配器的单元测试上下文不需要清理。
        if not callable(getattr(self.上下文, "点击", None)):
            return True
        if not callable(getattr(self.上下文, "op", None)) and not hasattr(
            self.上下文, "op"
        ):
            return True
        try:
            if not self._研究面板已确认():
                return True
        except Exception as 异常:
            self.上下文.置脚本状态(f"残留研究面板识别失败，禁止继续：{异常}")
            self.上下文.页面恢复失败 = True
            return False

        setattr(self.上下文, "_研究面板已确认", True)
        self.上下文.置脚本状态("检测到残留研究目标页，先安全关闭并返回主世界")
        try:
            if self.上下文.点击(668, 32, 是否精确点击=True) is False:
                self.上下文.页面恢复失败 = True
                return False
            self.上下文.脚本延时(300)
            # 关闭目标页后通常会回到实验室详情卡；地图空白点只用于取消
            # 已选中的建筑，不会进入商店、宝石或其它功能页。
            if self.上下文.点击(100, 300, 是否精确点击=True) is False:
                self.上下文.页面恢复失败 = True
                return False
            self.上下文.脚本延时(300)
            setattr(self.上下文, "_研究面板已确认", False)
            识别 = getattr(self.上下文, "识别点击画面", None)
            if callable(识别):
                try:
                    结果 = 识别(强制=True)
                except TypeError:
                    结果 = 识别()
                if not (
                    getattr(结果, "页面", "") == "主世界主页"
                    and getattr(结果, "世界", "") == "主世界"
                ):
                    self.上下文.页面恢复失败 = True
                    self.上下文.置脚本状态(
                        f"残留研究面板关闭后未确认主世界（当前={getattr(结果, '页面', '未知')}）"
                    )
                    return False
            self.上下文.置脚本状态("残留研究面板已清理，确认回到主世界")
            return True
        except Exception as 异常:
            setattr(self.上下文, "_研究面板已确认", False)
            self.上下文.页面恢复失败 = True
            self.上下文.置脚本状态(f"清理残留研究面板失败：{异常}")
            return False

    @staticmethod
    def _规范化文本(文本) -> str:
        文本 = str(文本 or "").replace(" ", "").replace("\n", "")
        # 拉远后的浅色“研究”标签会被 RapidOCR 偶尔读成“环究/妍究”；
        # 这些别名只用于产生候选，后面仍必须选中实验室并确认研究按钮，
        # 因此不会单独授权任何点击。
        for 错误, 正确 in (
            ("环究", "研究"),
            ("妍究", "研究"),
            ("研宄", "研究"),
            ("研充", "研究"),
        ):
            文本 = 文本.replace(错误, 正确)
        return 文本

    @classmethod
    def _查找研究文字(cls, 识别结果, 区域: tuple[int, int, int, int]):
        """在指定参考区域中找“研究”文字并返回其中心点。"""
        x最小, y最小, x最大, y最大 = 区域
        候选 = []
        for 项 in 识别结果 or []:
            if not isinstance(项, (list, tuple)) or len(项) < 2:
                continue
            框, 文本 = 项[0], cls._规范化文本(项[1])
            if "研究" not in 文本 or not 框:
                continue
            try:
                x坐标 = [float(点[0]) for 点 in 框]
                y坐标 = [float(点[1]) for 点 in 框]
                中心 = (sum(x坐标) / len(x坐标), sum(y坐标) / len(y坐标))
            except (TypeError, ValueError, IndexError, ZeroDivisionError):
                continue
            if not (x最小 <= 中心[0] <= x最大 and y最小 <= 中心[1] <= y最大):
                continue
            置信度 = float(项[2]) if len(项) >= 3 else 0.0
            候选.append((置信度, 中心[0], 中心[1]))
        if not 候选:
            return None
        # 地图布局在缩放后仍可能出现多个“研究”字样；优先靠近当前
        # 实验室标签/研究按钮的参考位置，并用 OCR 置信度打破平局。
        目标x = 450 if y最大 <= 460 else 460
        目标y = 375 if y最大 <= 460 else 445
        return min(
            候选,
            key=lambda 项: (
                math.hypot(项[1] - 目标x, 项[2] - 目标y),
                -项[0],
            ),
        )[1:]

    def _读取研究文字(self, 区域):
        try:
            识别结果 = self.执行OCR识别(self.全屏区域)
        except Exception:
            return None
        return self._查找研究文字(识别结果, 区域)

    def _执行局部放大OCR(self, 区域, 颜色通道=None):
        """对小型建筑标签做一次放大 OCR，并保留参考画布坐标。"""
        try:
            获取图像 = self.上下文.op.获取屏幕图像cv
            try:
                # 点击建筑后必须绕过 ADB 屏幕的短缓存，否则会把点击前
                # 的主世界旧帧当成“未选中”，继续误试其它建筑。
                图像 = 获取图像(*区域, 强制刷新=True)
            except TypeError:
                # 兼容旧的测试/模拟截图适配器。
                图像 = 获取图像(*区域)
            if 图像 is None or getattr(图像, "size", 0) == 0:
                return []
            放大图像 = cv2.resize(
                图像,
                None,
                fx=self.局部OCR放大倍数,
                fy=self.局部OCR放大倍数,
                interpolation=cv2.INTER_CUBIC,
            )
            if 颜色通道 == "蓝色":
                # 实机标签的白字在地图绿色纹理上容易被彩色 OCR
                # 合并；蓝色通道能把“研究”字形从背景中分离出来。
                # 这只作为候选召回，不改变后面的实验室按钮复核。
                放大图像 = 放大图像[:, :, 0]
            结果, _ = self.ocr引擎(放大图像)
            return 结果 or []
        except Exception as 异常:
            self.上下文.置脚本状态(f"研究局部OCR暂不可用，安全跳过：{异常}")
            return []

    @classmethod
    def _查找放大文字(cls, 识别结果, 区域, 关键词, 最低置信度=0.70):
        """把局部放大 OCR 框还原到 800×600 参考画布坐标。"""
        x最小, y最小, x最大, y最大 = 区域
        候选 = []
        倍数 = cls.局部OCR放大倍数
        for 项 in 识别结果 or []:
            if not isinstance(项, (list, tuple)) or len(项) < 2:
                continue
            文本 = cls._规范化文本(项[1])
            if not any(词 in 文本 for 词 in 关键词):
                continue
            try:
                框 = 项[0]
                中心x = sum(float(点[0]) for 点 in 框) / len(框) / 倍数 + x最小
                中心y = sum(float(点[1]) for 点 in 框) / len(框) / 倍数 + y最小
                置信度 = float(项[2]) if len(项) >= 3 else 0.0
            except (TypeError, ValueError, IndexError, ZeroDivisionError):
                continue
            if 置信度 < 最低置信度:
                continue
            if not (x最小 <= 中心x <= x最大 and y最小 <= 中心y <= y最大):
                continue
            候选.append((置信度, 中心x, 中心y, 文本))
        # 同一标签可能被检测成相邻的两个框，只保留置信度较高者。
        去重 = []
        for 项 in sorted(候选, key=lambda 值: -值[0]):
            if any(
                math.hypot(项[1] - 已有[1], 项[2] - 已有[2]) < 18
                for 已有 in 去重
            ):
                continue
            去重.append(项)
        return [(项[1], 项[2], 项[0], 项[3]) for 项 in 去重]

    def _查找实验室标签候选(self):
        识别结果 = self._执行局部放大OCR(self.建筑标签搜索区域)
        候选 = self._查找放大文字(
            识别结果,
            self.建筑标签搜索区域,
            ("研究",),
            # 放大后的建筑标签在测试服地图纹理上置信度通常为
            # 0.65~0.75；点击后仍有实验室研究按钮和研究面板双重确认，
            # 因此这里扩大召回但不放宽后续安全点击条件。
            最低置信度=0.60,
        )
        if 候选:
            return 候选

        回退区域 = self.建筑标签搜索回退区域
        # 实机窄裁剪的彩色 OCR 会漏掉底部标签；直接对扩大后的下半区
        # 做一次蓝色通道 OCR，可以同时召回画面中的多个“研究”候选，
        # 不能只返回第一个，否则普通建筑附近的背景字可能抢先通过。
        回退结果 = self._执行局部放大OCR(
            回退区域,
            颜色通道="蓝色",
        )
        回退候选 = self._查找放大文字(
            回退结果,
            回退区域,
            ("研究",),
            最低置信度=0.80,
        )
        if 回退候选 and hasattr(self, "上下文"):
            self.上下文.置脚本状态(
                "研究标签彩色OCR未命中，已用下半区蓝色通道定位候选"
            )
        return 回退候选

    def _选中后是否为实验室(self) -> bool:
        # 测试服选中卡片的“实验室(等级)”标题字体带阴影，RapidOCR
        # 经常读不到；底部“研究”操作按钮反而稳定。只有确认这个按钮
        # 存在才允许继续，普通建筑的卡片只会出现“升级”。
        return self._查找选中实验室研究按钮() is not None

    @classmethod
    def _结果存在详情信息按钮(cls, 识别结果, 区域) -> bool:
        """识别普通建筑详情卡的“信息”按钮，排除地图上的升级标签。"""
        x最小, y最小, x最大, y最大 = 区域
        for 项 in 识别结果 or []:
            if not isinstance(项, (list, tuple)) or len(项) < 2:
                continue
            文本 = cls._规范化文本(项[1])
            if not any(词 in 文本 for 词 in ("资讯", "資訊", "信息", "情報")):
                continue
            try:
                框 = 项[0]
                中心x = sum(float(点[0]) for 点 in 框) / len(框) / cls.局部OCR放大倍数 + x最小
                中心y = sum(float(点[1]) for 点 in 框) / len(框) / cls.局部OCR放大倍数 + y最小
                置信度 = float(项[2]) if len(项) >= 3 else 0.0
            except (TypeError, ValueError, IndexError, ZeroDivisionError):
                continue
            if 置信度 >= 0.55 and 300 <= 中心x <= 430 and 470 <= 中心y <= 545:
                return True
        return False

    def _清理普通建筑详情(self) -> bool:
        """研究任务入口清除残留普通建筑卡，不发送 ESC/BACK。"""
        识别结果 = self._执行局部放大OCR(
            self.研究按钮搜索区域,
            颜色通道="蓝色",
        )
        if not (
            self._结果存在普通升级按钮(
                识别结果,
                self.研究按钮搜索区域,
            )
            and self._结果存在详情信息按钮(
                识别结果,
                self.研究按钮搜索区域,
            )
        ):
            return True
        self.上下文.置脚本状态(
            "检测到残留普通建筑详情卡，点击主世界空白区域关闭；"
            "禁止点击升级、宝石和商店"
        )
        if self.上下文.点击(700, 300, 是否精确点击=True) is False:
            self.上下文.页面恢复失败 = True
            return False
        self.上下文.脚本延时(350)
        return True

    @classmethod
    def _结果存在普通升级按钮(cls, 识别结果, 区域) -> bool:
        """详情卡明确出现普通“升级”时，拒绝背景中的“研究”字。"""
        x最小, y最小, x最大, y最大 = 区域
        for 项 in 识别结果 or []:
            if not isinstance(项, (list, tuple)) or len(项) < 2:
                continue
            文本 = cls._规范化文本(项[1])
            if not any(词 in 文本 for 词 in ("升级", "升級")):
                continue
            try:
                框 = 项[0]
                中心x = sum(float(点[0]) for 点 in 框) / len(框) / cls.局部OCR放大倍数 + x最小
                中心y = sum(float(点[1]) for 点 in 框) / len(框) / cls.局部OCR放大倍数 + y最小
                置信度 = float(项[2]) if len(项) >= 3 else 0.0
            except (TypeError, ValueError, IndexError, ZeroDivisionError):
                continue
            # 只把详情卡右下操作按钮区域作为冲突证据，地图上的
            # 其它“升级中”文字不应误否决实验室。
            if (
                0.75 <= 置信度
                and 420 <= 中心x <= 520
                and 470 <= 中心y <= 545
            ):
                return True
        return False

    def _查找选中实验室研究按钮(self):
        识别结果 = self._执行局部放大OCR(self.研究按钮搜索区域)
        候选 = self._查找放大文字(
            识别结果,
            self.研究按钮搜索区域,
            ("研究",),
            最低置信度=0.85,
        )
        if self._结果存在普通升级按钮(
            识别结果,
            self.研究按钮搜索区域,
        ):
            return None
        if not 候选:
            蓝色结果 = self._执行局部放大OCR(
                self.研究按钮搜索区域,
                颜色通道="蓝色",
            )
            候选 = self._查找放大文字(
                蓝色结果,
                self.研究按钮搜索区域,
                ("研究",),
                最低置信度=0.80,
            )
            if self._结果存在普通升级按钮(
                蓝色结果,
                self.研究按钮搜索区域,
            ):
                return None
        if not 候选:
            return None
        _, x, y, _ = max(候选, key=lambda 项: 项[2])
        return x, y

    def _安全取消建筑选中(self) -> bool:
        """只在已知主世界选中态时点水面空白，清除错误候选。"""
        try:
            成功 = self.上下文.点击(100, 300, 是否精确点击=True)
        except Exception as 异常:
            成功 = False
            self.上下文.置脚本状态(f"清理实验室候选详情失败，停止研究入口：{异常}")
        if 成功 is False:
            setattr(self.上下文, "页面恢复失败", True)
            self.上下文.置脚本状态("清理实验室候选详情未被安全输入层接受")
            return False
        return True

    def _等待研究文字(self, 区域, 截止时间):
        while time.monotonic() < 截止时间:
            位置 = self._读取研究文字(区域)
            if 位置 is not None:
                return 位置
            self.上下文.脚本延时(250)
        return None

    def _打开研究入口(self) -> bool:
        """通过视觉候选和建筑标题确认后打开研究面板。"""
        self.上下文.置脚本状态("正在定位实验室研究入口")
        截止时间 = time.monotonic() + self.最大入口等待秒
        候选 = []
        while time.monotonic() < 截止时间 and not 候选:
            候选 = self._查找实验室标签候选()
            if not 候选:
                self.上下文.脚本延时(250)
        for x, y, _, _ in 候选:
            for 偏移x, 偏移y in self.研究入口偏移候选:
                    if self.上下文.点击(
                        round(x + 偏移x), round(y + 偏移y), 是否精确点击=True
                    ) is False:
                        self.上下文.置脚本状态("实验室候选点击未被安全输入层接受")
                        return False
                    self.上下文.脚本延时(450)
                    if not self._选中后是否为实验室():
                        if not self._安全取消建筑选中():
                            self.上下文.置脚本状态(
                                "实验室候选不是实验室且无法安全取消选中，停止研究入口"
                            )
                            return False
                        continue
                    self.上下文.置脚本状态("已确认选中实验室，定位研究按钮")
                    研究位置 = self._查找选中实验室研究按钮()
                    if 研究位置 is None:
                        setattr(self.上下文, "_研究面板已确认", False)
                        if not self._安全取消建筑选中():
                            self.上下文.置脚本状态(
                                "研究按钮未确认且无法安全取消选中，停止研究入口"
                            )
                            return False
                        self.上下文.置脚本状态("实验室研究按钮未确认，安全跳过研究升级")
                        return False
                    # 实验室详情页和后续目标页都会被通用页面识别器
                    # 归类为“多按钮弹窗”。研究按钮已经由实验室标题/研究
                    # OCR 双重确认，因此从这里开始临时放行研究流程点击。
                    setattr(self.上下文, "_研究面板已确认", True)
                    研究前画面 = self._获取全屏画面()
                    if self.上下文.点击(*map(round, 研究位置), 是否精确点击=True) is False:
                        setattr(self.上下文, "_研究面板已确认", False)
                        self.上下文.置脚本状态("研究按钮未被安全输入层接受，停止研究操作")
                        return False
                    self.上下文.脚本延时(350)
                    if not self._研究面板已确认():
                        setattr(self.上下文, "_研究面板已确认", False)
                        self.上下文.置脚本状态(
                            "研究按钮点击后未确认研究面板，安全停止，禁止点击兵种"
                        )
                        return False
                    self.上下文.置脚本状态("研究面板已打开")
                    return True
        self.上下文.置脚本状态("实验室标签或建筑名称未确认，安全跳过研究升级")
        return False

    def _研究面板已确认(self) -> bool:
        识别结果 = self._执行局部放大OCR((80, 0, 720, 590))
        文本 = "".join(
            self._规范化文本(项[1])
            for 项 in 识别结果
            if isinstance(项, (list, tuple)) and len(项) >= 2
        )
        # RapidOCR 在传统中文测试服上可能把“請選擇”读成“請選選”，
        # 或把“目標”读成“對象”。不能要求整句连续匹配，否则实际已
        # 打开的目标页会被误判为失败；仍要求同时出现“升级”“目标/对象”
        # 和选择语义，避免把实验室详情页或普通主世界 OCR 当成研究页。
        有升级词 = any(词 in 文本 for 词 in ("升级", "升級"))
        有目标词 = any(词 in 文本 for 词 in ("目标", "目標", "对象", "對象"))
        有选择词 = any(词 in 文本 for 词 in ("选择", "選擇", "選選", "选"))
        已确认 = 有升级词 and 有目标词 and 有选择词
        if 已确认 and getattr(self, "上下文", None) is not None:
            setattr(self.上下文, "_研究面板已确认", True)
        return 已确认

    def _获取全屏画面(self):
        操作 = getattr(self.上下文, "op", None)
        获取 = getattr(操作, "获取屏幕图像cv", None)
        if not callable(获取):
            return None
        try:
            return 获取(*self.全屏区域)
        except Exception:
            return None

    def _画面变化明显(self, 旧画面) -> bool:
        if 旧画面 is None:
            # 兼容无截图适配器的单元测试；正式 ADB 上一定会有基准画面。
            return True
        try:
            新画面 = self._获取全屏画面()
            if 新画面 is None or getattr(旧画面, "shape", None) != getattr(新画面, "shape", None):
                return False
            差异 = np.abs(
                新画面.astype(np.int16) - 旧画面.astype(np.int16)
            )
            return float(np.mean(差异)) >= 4.0
        except (AttributeError, TypeError, ValueError):
            return False

    @staticmethod
    def 解析实验室计数(识别结果) -> tuple[int, int]:
        """从 OCR 结果中提取合法的 ``空闲/总数`` 研究槽位。

        研究面板入口在转场或缩放后的首帧偶尔会只返回 ``1``，旧代码
        直接对第一条文本 split('/') 并解包，产生 ``not enough values``。
        这里遍历全部 OCR 项，只接受 0..2 的合法计数。
        """
        候选 = []
        for 项 in 识别结果 or []:
            if not isinstance(项, (list, tuple)) or len(项) < 2:
                continue
            文本 = str(项[1] or "").strip().replace(" ", "")
            文本 = (
                文本.replace("O", "0")
                .replace("o", "0")
                .replace("／", "/")
                .replace("I", "/")
                .replace("l", "/")
                .replace("|", "/")
            )
            匹配 = re.search(r"(?<!\d)([0-2])\s*/\s*([0-2])(?!\d)", 文本)
            if not 匹配:
                continue
            空闲位置 = int(匹配.group(1))
            可同时研究总数 = int(匹配.group(2))
            if 可同时研究总数 <= 0 or 空闲位置 > 可同时研究总数:
                continue
            置信度 = float(项[2]) if len(项) >= 3 else 0.0
            候选.append((置信度, 空闲位置, 可同时研究总数))
        if not 候选:
            raise ValueError("未识别到合法实验室计数")
        _, 空闲位置, 可同时研究总数 = max(候选, key=lambda 项: 项[0])
        return 空闲位置, 可同时研究总数

    def _检查实验室是否空闲(self) -> bool:
        """检查实验室是否有空闲位置"""
        识别结果 = self.执行OCR识别(self.实验室状态区域)
        try:
            空闲位置, 可同时研究总数 = self.解析实验室计数(识别结果)
        except ValueError:
            # 首帧 OCR 可能只截到数字左半边；扩大同一顶部区域重试，
            # 不改变点击位置，也不把其它页面文本当成实验室状态。
            回退区域 = (240, 0, 380, 80)
            回退结果 = self.执行OCR识别(回退区域)
            空闲位置, 可同时研究总数 = self.解析实验室计数(回退结果)
            self.上下文.置脚本状态(
                f"实验室窄区域OCR未命中，已用顶部宽区域回退识别：{空闲位置}/{可同时研究总数}"
            )

        # 无空闲位置
        if 空闲位置 == 0:
            self.上下文.置脚本状态(f"实验室有东西在升级：({空闲位置}/{可同时研究总数})")
            return False

        # 哥布林活动特殊情况
        if 可同时研究总数 == 2 and 空闲位置 == 1:
            self.上下文.置脚本状态("当前为哥布林活动，显示1位置但实际不可用")
            return False

        # 正常可用
        if 0 <= 空闲位置 <= 可同时研究总数 <= 2:
            self.上下文.置脚本状态(f"实验室可用：{空闲位置}/{可同时研究总数}")
            return True

        # 异常情况
        self.上下文.置脚本状态(f"实验室状态异常：OCR结果为 {识别结果}")
        return False
