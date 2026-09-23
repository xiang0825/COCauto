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
                return None
            _, 中心x, 中心y = max(候选, key=lambda 项: 项[0])
            return (
                int(round(中心x * 800 / 宽)),
                int(round(中心y * 600 / 高)),
            )
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

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
                self.上下文.点击(x, y, )
                self.关闭英雄升级页面()
                return True
            else:
                # 抛出不可升级异常
                raise 英雄不可升级错误(self.要升级的英雄)

        except 英雄不可升级错误 as e:
            # 统一处理不可升级情况：关闭页面 + 状态记录
            self.关闭英雄升级页面()
            self.上下文.置脚本状态(str(e))
            return False

        except Exception as e:
            # 其他异常统一处理
            self.异常处理(e)
            return False

    def 关闭英雄升级页面(self):
        """安全关闭英雄升级界面，禁止使用返回键退出游戏。"""
        关闭升级面板 = getattr(self.上下文, "关闭升级详情弹窗", None)
        if callable(关闭升级面板):
            try:
                关闭升级面板()
            except Exception as 异常:
                self.上下文.置脚本状态(f"英雄升级详情面板关闭失败：{异常}")
            if getattr(self.上下文, "页面恢复失败", False):
                return False

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
                                return False
                        else:
                            点击(关闭点[0], 关闭点[1], 延时=350, 是否精确点击=True)
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
                        点击(700, 300, 延时=700, 是否精确点击=True)
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
                点击(700, 300, 延时=700, 是否精确点击=True)
                return True
            except Exception as 异常:
                self.上下文.置脚本状态(f"英雄升级详情空白区域关闭失败：{异常}")

        # 仅保留给没有新版点击护栏的旧测试/兼容上下文；真实运行上下文
        # 一定具备上面的点击方法，因此不会走到这里。
        安全返回键 = getattr(self.上下文, "安全返回键", None)
        if callable(安全返回键):
            安全返回键("关闭英雄升级页面", 已确认可关闭面板=True)
        else:
            self.上下文.键盘.按字符按压("esc")
        return True

