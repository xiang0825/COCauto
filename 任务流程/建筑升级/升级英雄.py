import random
import time

import cv2
import numpy as np

from 任务流程.基础任务框架 import 任务上下文
from 任务流程.夜世界.夜世界打鱼.夜世界基础任务类 import 夜世界基础任务

class 英雄不可升级错误(Exception):
    """当英雄不可升级时抛出的异常"""
    def __init__(self, 英雄名称):
        super().__init__(f"英雄[{英雄名称}]不可升级")
        self.英雄名称 = 英雄名称

    def __str__(self):
        return f"英雄[{self.英雄名称}]不可升级"

class 升级英雄任务(夜世界基础任务):
    """自动检测并升级指定英雄"""

    def __init__(self, 上下文: '任务上下文', 要升级的英雄: str):
        super().__init__(上下文)
        self.要升级的英雄 = 要升级的英雄
        # “当前不可升级”是可恢复的正常状态；真正的 OCR/ADB/页面
        # 异常仍返回 False 并由上层记录失败。
        self.安全跳过 = False

        # # 英雄及其所在区域映射
        # self.英雄区域映射 = {
        #     "野蛮人之王": (54, 362, 174, 405),
        #     "弓箭女皇": (191, 371, 319, 407),
        #     "亡灵王子": (336, 373, 461, 406),
        #     "大守护者": (493, 361, 594, 401),
        #     "飞盾战神": (629, 375, 741, 404),
        #     "飞龙公爵": (629, 375, 741, 404),
        # }

        # 升级相似度阈值
        self.相似度阈值 = 0.85

    @staticmethod
    def _规范英雄文本(文本: str) -> str:
        return (
            str(文本 or "")
            .replace("蠻", "蛮")
            .replace("靈", "灵")
            .replace("飛", "飞")
            .replace("戰", "战")
            .replace("護", "护")
            .replace("龍", "龙")
            .replace(" ", "")
            .replace("\n", "")
        )

    @classmethod
    def _英雄名称匹配(cls, 目标: str, 文本: str) -> bool:
        目标文本 = cls._规范英雄文本(目标)
        当前文本 = cls._规范英雄文本(文本)
        if 目标文本 in 当前文本:
            return True
        关键词 = {
            "野蛮人之王": ("野", "人", "王"),
            "弓箭女皇": ("弓", "箭", "女", "皇"),
            "大守护者": ("大", "守", "护", "者"),
            "飞盾战神": ("飞", "盾", "战", "神"),
            "亡灵王子": ("亡", "灵", "王", "子"),
            "飞龙公爵": ("飞", "龙", "公", "爵"),
        }.get(目标文本)
        return bool(关键词 and all(字符 in 当前文本 for 字符 in 关键词))

    @staticmethod
    def _检测英雄殿堂关闭点(屏幕图像) -> tuple[int, int] | None:
        """识别英雄殿堂/英雄列表右上角的红色 X。

        英雄升级详情的 X 由任务上下文专用检测器处理；不可升级时画面
        往往仍停在英雄殿堂列表，旧的固定空白点会落到某张英雄卡片，
        重新打开详情甚至暴露“立即完成/宝石”。这里只接受最右上方的
        红色方形 X 和白色交叉线，并转换到 800×600 参考坐标。
        """
        if 屏幕图像 is None or not hasattr(屏幕图像, "shape"):
            return None
        try:
            高, 宽 = 屏幕图像.shape[:2]
            if len(屏幕图像.shape) < 3 or 高 < 240 or 宽 < 500:
                return None
            hsv = cv2.cvtColor(屏幕图像, cv2.COLOR_BGR2HSV)
            红色 = (
                ((hsv[:, :, 0] <= 15) | (hsv[:, :, 0] >= 165))
                & (hsv[:, :, 1] >= 120)
                & (hsv[:, :, 2] >= 120)
            ).astype("uint8")
            x起点, x终点 = int(宽 * 0.88), int(宽 * 0.995)
            y终点 = int(高 * 0.22)
            区域 = 红色[:y终点, x起点:x终点]
            区域 = cv2.morphologyEx(
                区域, cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            )
            轮廓列表, _ = cv2.findContours(
                区域, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            候选 = []
            灰度 = cv2.cvtColor(屏幕图像, cv2.COLOR_BGR2GRAY)
            for 轮廓 in 轮廓列表:
                x, y, 方宽, 方高 = cv2.boundingRect(轮廓)
                中心x = x + x起点 + 方宽 / 2
                中心y = y + 方高 / 2
                if not (
                    宽 * 0.90 <= 中心x <= 宽 * 0.98
                    and 高 * 0.05 <= 中心y <= 高 * 0.18
                    and 宽 * 0.02 <= 方宽 <= 宽 * 0.08
                    and 高 * 0.035 <= 方高 <= 高 * 0.12
                    and 0.55 <= 方宽 / max(1, 方高) <= 1.8
                ):
                    continue
                左, 上 = max(0, x + x起点), max(0, y)
                右, 下 = min(宽, 左 + 方宽), min(高, 上 + 方高)
                白色交叉 = (
                    (hsv[上:下, 左:右, 1] < 100)
                    & (灰度[上:下, 左:右] > 180)
                )
                if int(np.count_nonzero(白色交叉)) < max(8, int(方宽 * 方高 * 0.015)):
                    continue
                候选.append((方宽 * 方高, 中心x, 中心y))
            if not 候选:
                # 英雄详情页与普通升级详情页共用同一套 1280×720
                # 右上角关闭按钮。英雄专用检测器的严格范围主要用于
                # 英雄殿堂列表，但在高分辨率测试服中详情 X 的中心会
                # 落在约 0.884W；不能因为它不是“最右侧”就把面板留在
                # 原地。通用检测器仍要求中央标题栏、红色方形按钮和
                # 尺寸约束，只返回 X，不会返回底部绿色确认/宝石按钮。
                return 任务上下文._检测升级详情弹窗关闭点(屏幕图像)
            _, 中心x, 中心y = max(候选, key=lambda 项: 项[0])
            return (
                int(round(中心x * 800 / 宽)),
                int(round(中心y * 600 / 高)),
            )
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def _英雄殿堂文本仍在(self) -> bool:
        """用新 OCR 帧确认英雄殿堂列表是否仍覆盖主世界。"""
        # 详情 X 关闭后，测试服可能先露出一帧“主世界主页”再重新绘制
        # 英雄殿堂列表。只读重试几帧，不能在首帧 OCR 为空时立刻退回
        # 旧的右上角红色候选点，否则会误点 HUD。
        延时 = getattr(self.上下文, "脚本延时", None)
        for 尝试序号 in range(3):
            try:
                OCR结果 = self.执行OCR识别((250, 55, 710, 590))
            except Exception:
                OCR结果 = []
            文本 = "".join(
                str(项[1]) for 项 in (OCR结果 or [])
                if isinstance(项, (list, tuple)) and len(项) > 1
            ).replace(" ", "").replace("\n", "")
            规范文本 = 文本
            # 英雄详情底层卡也会显示“英雄殿堂[等级]”；只有列表中的
            # “建议升级/可使用”段存在时，才授权顶部入口收尾。
            if (
                "英雄殿堂" in 规范文本
                and ("建议升级" in 规范文本 or "可使用" in 规范文本)
            ):
                return True
            if 尝试序号 < 2 and callable(延时):
                延时(250)
        return False

    def _安全关闭英雄殿堂入口(self) -> bool:
        """通过已确认的顶部英雄入口关闭列表，不猜测右上角 HUD 坐标。"""
        点击 = getattr(self.上下文, "点击", None)
        if not callable(点击):
            self.上下文.页面恢复失败 = True
            self.上下文.置脚本状态(
                "缺少英雄殿堂入口关闭能力，禁止发送ESC或盲点输入"
            )
            return False
        for 尝试序号 in range(2):
            if 点击(
                356, 33,
                延时=700,
                是否精确点击=True,
            ) is False:
                self.上下文.页面恢复失败 = True
                self.上下文.置脚本状态(
                    "英雄殿堂入口关闭点击被安全层拒绝，停止后续操作"
                )
                return False
            self.上下文.脚本延时(450)
            if self._英雄殿堂文本仍在():
                if 尝试序号 == 0:
                    self.上下文.置脚本状态(
                        "英雄殿堂入口点击后列表仍在，精确重试一次"
                    )
                    continue
                self.上下文.页面恢复失败 = True
                self.上下文.置脚本状态(
                    "英雄殿堂入口重试后列表仍在，禁止继续任务输入"
                )
                return False

            识别 = getattr(self.上下文, "识别点击画面", None)
            if callable(识别):
                try:
                    try:
                        结果 = 识别(强制=True)
                    except TypeError:
                        结果 = 识别()
                except Exception as 异常:
                    self.上下文.页面恢复失败 = True
                    self.上下文.置脚本状态(
                        f"英雄殿堂关闭后主页复核失败：{异常}"
                    )
                    return False
                if not (
                    getattr(结果, "页面", "") == "主世界主页"
                    and getattr(结果, "世界", "") == "主世界"
                ):
                    self.上下文.页面恢复失败 = True
                    self.上下文.置脚本状态(
                        "英雄殿堂已点击关闭但未确认主世界，禁止后续输入"
                    )
                    return False
            self.上下文.置脚本状态(
                "英雄殿堂列表已通过顶部入口安全关闭并确认回到主世界"
            )
            return True
        self.上下文.页面恢复失败 = True
        return False

    @classmethod
    def _识别英雄升级确认页(cls, OCR结果, 屏幕图像, 目标英雄: str) -> bool:
        """用标题、目标英雄和绿色资源按钮确认升级页。"""
        if 屏幕图像 is None or not hasattr(屏幕图像, "shape"):
            return False
        文本项 = [
            cls._规范英雄文本(项[1])
            for 项 in (OCR结果 or [])
            if isinstance(项, (list, tuple)) and len(项) > 1
        ]
        全部文本 = "".join(文本项)
        if any(词 in 全部文本 for 词 in ("宝石", "立即完成", "使用宝石", "购买")):
            return False
        if not cls._英雄名称匹配(目标英雄, 全部文本):
            return False
        if not any(词 in 全部文本 for 词 in ("升至", "升级", "提升")):
            return False
        try:
            高, 宽 = 屏幕图像.shape[:2]
            左, 上 = max(0, int(宽 * 0.58)), max(0, int(高 * 0.77))
            右, 下 = min(宽, int(宽 * 0.80)), min(高, int(高 * 0.95))
            区域 = 屏幕图像[上:下, 左:右]
            if 区域.size == 0:
                return False
            HSV = cv2.cvtColor(区域, cv2.COLOR_BGR2HSV)
            绿色 = cv2.inRange(HSV, np.array([35, 55, 70]), np.array([95, 255, 255]))
            return float(np.count_nonzero(绿色)) / float(绿色.size) >= 0.08
        except (cv2.error, ValueError, TypeError):
            return False

    def 执行(self) -> bool:
        """检查英雄殿堂界面中指定英雄是否可升级，并执行升级"""

        try:
            # self.上下文.脚本延时(500)
            # self.上下文.键盘.按字符按压("esc")
            #
            # if self.要升级的英雄=="飞龙公爵":
            #     随机半径 = 20
            #     start_x = 734 + 随机半径
            #     start_y = 290 + 随机半径
            #     self.上下文.鼠标.移动到(start_x, start_y)
            #     self.上下文.鼠标.左键按下()
            #
            #     for x in range(50):
            #         self.上下文.鼠标.移动相对位置(-random.randint(5, 8), 0)
            #         self.上下文.脚本延时(2)
            #
            #     self.上下文.鼠标.左键抬起()
            #     self.上下文.脚本延时(random.randint(200, 500))
            #
            #
            # self.上下文.置脚本状态(f"正在尝试升级{self.要升级的英雄} ")
            #
            # 可升级, 坐标 = self.是否出现图片(
            #     "英雄殿堂界面_升级.bmp",
            #     self.英雄区域映射[self.要升级的英雄],
            #     self.相似度阈值
            # )
            #
            #
            # 当前国际服的繁体字体在自适应画布上会让旧的“确认”小图
            # 模板严重失配；改为标题/英雄/绿色资源按钮三重确认。
            屏幕图像 = self.上下文.op.获取屏幕图像cv(
                0, 0, 800, 600, 强制刷新=True
            )
            OCR结果 = self.执行OCR识别((250, 0, 710, 590))
            可升级 = self._识别英雄升级确认页(
                OCR结果, 屏幕图像, self.要升级的英雄
            )
            坐标 = (560, 525)


            if 可升级:
                self.上下文.置脚本状态(f"{self.要升级的英雄} 可升级")

                # 点击升级
                x, y = 坐标
                if self.上下文.点击(x, y, ) is False:
                    self.上下文.置脚本状态(
                        f"{self.要升级的英雄}确认按钮点击被安全层拒绝，未报告升级成功"
                    )
                    self.安全跳过 = True
                    self.关闭英雄升级页面()
                    return False
                self.关闭英雄升级页面()
                return True
            else:
                # 抛出不可升级异常
                raise 英雄不可升级错误(self.要升级的英雄)

        except 英雄不可升级错误 as e:
            # 统一处理不可升级情况：关闭页面 + 状态记录
            self.安全跳过 = True
            self.关闭英雄升级页面()
            self.上下文.置脚本状态(f"{e}，已安全跳过当前目标")
            return False

        except Exception as e:
            # 其他异常统一处理
            self.异常处理(e)
            return False

    def 关闭英雄升级页面(self):
        """安全关闭英雄升级界面，禁止使用返回键退出游戏。"""
        关闭升级面板 = getattr(self.上下文, "关闭升级详情弹窗", None)
        # 普通升级护栏会主动跳过已确认的英雄详情，避免把它当成普通
        # 建筑页误关。英雄专用收尾在此情况下必须直接继续识别英雄页的
        # 关闭点，不能把“普通关闭器返回 False”当成安全失败。
        当前是英雄详情 = False
        try:
            获取图像 = getattr(getattr(self.上下文, "op", None), "获取屏幕图像cv", None)
            识别英雄详情 = getattr(self.上下文, "_当前画面是英雄升级详情", None)
            if callable(获取图像) and callable(识别英雄详情):
                try:
                    当前画面 = 获取图像(0, 0, 800, 600, 强制刷新=True)
                except TypeError:
                    当前画面 = 获取图像(0, 0, 800, 600)
                当前是英雄详情 = bool(识别英雄详情(当前画面))
        except Exception as 异常:
            self.上下文.置脚本状态(f"英雄详情页面预检失败：{异常}")

        if callable(关闭升级面板) and not 当前是英雄详情:
            try:
                if 关闭升级面板() is False:
                    self.上下文.页面恢复失败 = True
                    self.上下文.置脚本状态(
                        "英雄升级详情面板关闭未被安全层接受，停止后续操作"
                    )
                    return False
            except Exception as 异常:
                self.上下文.页面恢复失败 = True
                self.上下文.置脚本状态(f"英雄升级详情面板关闭失败：{异常}")
                return False
            if getattr(self.上下文, "页面恢复失败", False):
                return False
        elif 当前是英雄详情:
            self.上下文.置脚本状态(
                "已确认英雄升级详情，跳过普通升级关闭器，交由英雄专用关闭点处理"
            )

        # 当前国际服测试服的英雄详情 X 关闭后，英雄殿堂列表仍可能留在
        # 主世界上方。旧逻辑继续寻找屏幕最右侧红色 X，实机已证明会把
        # HUD 相似图标当成关闭点；先用本任务已确认的顶部英雄入口关闭，
        # 再用 OCR 和主页识别双重复核。
        if self._英雄殿堂文本仍在():
            return self._安全关闭英雄殿堂入口()

        # 英雄列表/详情页没有专用关闭按钮时，只点已知的主世界空白区域；
        # 不再用 Android BACK，避免过渡帧把它解释为退出游戏。
        获取图像 = getattr(getattr(self.上下文, "op", None), "获取屏幕图像cv", None)
        点击 = getattr(self.上下文, "点击", None)
        if callable(获取图像) and callable(点击):
            for _ in range(3):
                try:
                    try:
                        画面 = 获取图像(0, 0, 800, 600, 强制刷新=True)
                    except TypeError:
                        画面 = 获取图像(0, 0, 800, 600)
                    关闭点 = self._检测英雄殿堂关闭点(画面)
                    if 关闭点 is not None:
                        self.上下文.置脚本状态(
                            f"识别英雄殿堂关闭X，安全点击{关闭点[0]},{关闭点[1]}；"
                            "禁止点击立即完成和宝石"
                        )
                        点击安全 = getattr(self.上下文, "点击已确认安全按钮", None)
                        if callable(点击安全):
                            if not 点击安全(关闭点[0], 关闭点[1], 延时=350):
                                self.上下文.页面恢复失败 = True
                                return False
                        else:
                            if 点击(关闭点[0], 关闭点[1], 延时=350, 是否精确点击=True) is False:
                                self.上下文.页面恢复失败 = True
                                self.上下文.置脚本状态(
                                    "英雄殿堂关闭按钮点击被安全层拒绝，停止后续操作"
                                )
                                return False
                        self.上下文.脚本延时(350)
                        # 关闭英雄殿堂后测试服可能先露出“升级中/建议升级”
                        # 的主世界浮层；只有确认英雄殿堂 X 已消失，才用
                        # 右侧林地空白点清理这一层，避免在列表仍在时点卡片。
                        try:
                            try:
                                新画面 = 获取图像(0, 0, 800, 600, 强制刷新=True)
                            except TypeError:
                                新画面 = 获取图像(0, 0, 800, 600)
                            if self._检测英雄殿堂关闭点(新画面) is not None:
                                continue
                        except Exception:
                            continue
                        if 点击(700, 300, 延时=700, 是否精确点击=True) is False:
                            self.上下文.页面恢复失败 = True
                            self.上下文.置脚本状态(
                                "清除英雄升级浮层点击被安全层拒绝，停止后续操作"
                            )
                            return False
                        识别页面 = getattr(self.上下文, "识别点击画面", None)
                        if callable(识别页面):
                            try:
                                try:
                                    页面结果 = 识别页面(强制=True)
                                except TypeError:
                                    页面结果 = 识别页面()
                            except Exception as 异常:
                                self.上下文.页面恢复失败 = True
                                self.上下文.置脚本状态(
                                    f"英雄殿堂关闭后主页复核失败：{异常}"
                                )
                                return False
                            if not (
                                getattr(页面结果, "页面", "") == "主世界主页"
                                and getattr(页面结果, "世界", "") == "主世界"
                            ):
                                self.上下文.页面恢复失败 = True
                                self.上下文.置脚本状态(
                                    "英雄殿堂关闭后未确认主世界主页，禁止继续点击"
                                )
                                return False
                        self.上下文.页面恢复失败 = False
                        return True

                    self.上下文.置脚本状态(
                        "英雄殿堂关闭点未确认，禁止点击地图或英雄卡片"
                    )
                    return False
                except Exception as 异常:
                    self.上下文.置脚本状态(f"英雄升级详情收尾失败：{异常}")
                    return False
        if callable(点击):
            try:
                if 点击(700, 300, 延时=700, 是否精确点击=True) is False:
                    self.上下文.页面恢复失败 = True
                    self.上下文.置脚本状态(
                        "英雄升级详情空白区域点击被安全层拒绝，停止后续操作"
                    )
                    return False
                return True
            except Exception as 异常:
                self.上下文.页面恢复失败 = True
                self.上下文.置脚本状态(f"英雄升级详情空白区域关闭失败：{异常}")

        # 缺少安全关闭器时不能用原始 ESC 兜底；CoC 根页面会把 ESC/BACK
        # 解释为退出游戏。若调用方提供了已确认面板的受限关闭器，仍可
        # 使用该安全通道完成兼容收尾。
        安全返回键 = getattr(self.上下文, "安全返回键", None)
        if callable(安全返回键):
            return bool(
                安全返回键("关闭英雄升级页面", 已确认可关闭面板=True)
            )
        self.上下文.置脚本状态(
            "未提供英雄升级安全关闭器，禁止发送ESC；保留当前页面等待人工确认"
        )
        return False

