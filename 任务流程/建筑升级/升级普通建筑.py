import cv2
import numpy as np

from 任务流程.基础任务框架 import 任务上下文, 基础任务

class 升级按钮定位失败错误(Exception):
    """当英雄不可升级时抛出的异常"""
    def __init__(self):
        super().__init__(f"升级按钮定位失败")
        # self.英雄名称 = 英雄名称

    # def __str__(self):
    #     return f"英雄[{self.英雄名称}]不可升级"

class 升级普通建筑任务(基础任务):
    """自动检测并升级指定英雄"""

    # 只检查固定确认点击点周围，排除右侧同屏的“防御概况”绿色按钮。
    升级确认区域 = (520, 465, 605, 517)

    def __init__(self, 上下文: '任务上下文',要升级的建筑):
        super().__init__(上下文)
        # 升级相似度阈值
        self.相似度阈值 = 0.8
        self.要升级的建筑= 要升级的建筑

    def 执行(self) -> bool:
        """检查"""
        try:

            self.上下文.置脚本状态(f"正在尝试升级[{self.要升级的建筑}] ")

            可升级, 坐标 = self.是否出现图片(
                "建筑升级界面锤子.bmp|建筑升级界面锤子[1].bmp",
                (0,0,800,600),
                self.相似度阈值
            )

            if 可升级:
                self.上下文.置脚本状态(f"定位到升级按钮")

                # 第一次点击只会进入升级/详情操作区，不能据此判定已经升级。
                x, y = 坐标
                self.上下文.点击(x, y, )

                # 资源不足时，详情页仍然会显示锤子图标，但确认按钮是灰色。
                # 先检查确认区的绿色可用状态，避免把打开详情页误报成成功。
                if not self._升级确认按钮可用():
                    self.上下文.置脚本状态("升级确认按钮不可用，可能资源不足或建筑已在升级")
                    self.关闭建筑升级页面()
                    return False

                self.上下文.点击(561, 482, 延时=1000, 是否精确点击=True)

                # 点击后再次验证：按钮仍在表示点击没有提交升级。
                if self._升级确认按钮可用():
                    self.上下文.置脚本状态("点击升级后确认按钮仍可用，未检测到升级提交")
                    self.关闭建筑升级页面()
                    return False

                return True
            else:
                # 抛出不可升级异常
                raise 升级按钮定位失败错误()

        except 升级按钮定位失败错误 as e:
            # 统一处理不可升级情况：关闭页面 + 状态记录
            #self.关闭建筑升级页面()
            self.上下文.置脚本状态(str(e))
            return False

        except Exception as e:
            # 其他异常统一处理
            self.异常处理(e)
            return False

    def _升级确认按钮可用(self) -> bool:
        """检查普通建筑升级确认区是否呈现可点击的绿色按钮。"""
        图像 = self.上下文.op.获取屏幕图像cv(*self.升级确认区域)
        if 图像 is None or 图像.size == 0:
            return False
        hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
        下限 = np.array([35, 70, 70], dtype=np.uint8)
        上限 = np.array([95, 255, 255], dtype=np.uint8)
        绿色像素数 = cv2.countNonZero(cv2.inRange(hsv, 下限, 上限))
        return 绿色像素数 >= 100

    def 关闭建筑升级页面(self):
        """关闭升级界面"""
        安全返回键 = getattr(self.上下文, "安全返回键", None)
        if callable(安全返回键):
            安全返回键("关闭建筑升级页面")
        else:
            self.上下文.键盘.按字符按压("esc")




from typing import Sequence, List, Optional, Tuple


def 提取建议升级建筑名称(
        ocr结果: Sequence[Tuple[list, str, float]],
        最低置信度: float = 0.8,
        排除城墙: bool = True
) -> Optional[List[str]]:
    """
    从 OCR 识别结果中，提取“建议升级”与“其他升级”之间的建筑名称列表。

    处理流程：
    1. 按文本框的 y 坐标自上而下排序
    2. 定位“建议升级”起始位置与“其他升级”结束位置
    3. 过滤低置信度、非建筑文本
    4. 可选排除“城墙”

    :param ocr结果: OCR 识别结果序列，格式为 (坐标框, 文本, 置信度)
    :param 最低置信度: 建筑文本可接受的最低置信度阈值
    :param 排除城墙: 是否排除城墙
    :return: 建筑名称列表，若未找到有效建筑则返回 None
    """

    if not ocr结果:
        return None

    # 1. 按文本框顶部 y 坐标排序
    排序后结果 = sorted(
        ocr结果,
        key=lambda 项: min(点[1] for 点 in 项[0])
    )

    # 2. 定位“建议升级”和“其他升级”的索引
    起始索引, 结束索引 = _定位升级区间(排序后结果)
    if 起始索引 is None or 结束索引 is None:
        return None

    # 3. 提取建筑名称
    建筑名称列表: List[str] = []

    for _, 原始文本, 置信度 in 排序后结果[起始索引 + 1:结束索引]:
        文本 = 原始文本.strip()

        if 置信度 < 最低置信度:
            continue

        if not 看起来像建筑(文本):
            continue

        if 排除城墙 and "城墙" in 文本:
            continue

        建筑名称列表.append(文本)

    return 建筑名称列表 or None


from typing import List, Optional, Sequence, Tuple


def 提取建议升级建筑(
    ocr结果: Sequence[Tuple[list, str, float]],
    最低置信度: float = 0.8,
    排除城墙: bool = True
) -> Optional[List[Tuple[list, str, float]]]:
    """
    从 OCR 识别结果中，提取“建议升级”与“其他升级”之间的建筑条目。

    处理流程：
    1. 按文本框的 y 坐标进行自上而下排序
    2. 定位“建议升级”起始位置与“其他升级”结束位置
    3. 过滤低置信度、非建筑文本
    4. 可选排除“城墙”

    :param ocr结果: OCR 识别结果序列，格式为 (坐标框, 文本, 置信度)
    :param 最低置信度: 建筑文本可接受的最低置信度阈值
    :param 排除城墙: 是否在结果中排除“城墙”
    :return: 建筑条目列表，若未找到有效区间则返回 None
    """

    if not ocr结果:
        return None

    # 1. 按文本框顶部 y 坐标排序（从上到下）
    排序后结果 = sorted(
        ocr结果,
        key=lambda 项: min(点[1] for 点 in 项[0])
    )

    # 2. 定位区间边界
    起始索引, 结束索引 = _定位升级区间(排序后结果)
    if 起始索引 is None or 结束索引 is None:
        return None

    # 3. 提取并过滤建筑文本
    建筑列表: List[Tuple[list, str, float]] = []

    for 坐标框, 原始文本, 置信度 in 排序后结果[起始索引 + 1: 结束索引]:
        文本 = 原始文本.strip()

        if 置信度 < 最低置信度:
            continue

        if not 看起来像建筑(文本):
            continue

        if 排除城墙 and "城墙" in 文本:
            continue

        建筑列表.append((坐标框, 文本, 置信度))

    return 建筑列表 or None

from typing import Optional, Sequence, Tuple


def _定位升级区间(
    ocr结果: Sequence[Tuple[list, str, float]]
) -> Tuple[Optional[int], Optional[int]]:
    """
    在 OCR 结果中定位“建议升级”与“其他升级”文本所在的索引区间。

    :param ocr结果: 已按 y 坐标排序的 OCR 结果
    :return: (起始索引, 结束索引)，若未找到则为 (None, None)
    """

    起始索引: Optional[int] = None
    结束索引: Optional[int] = None

    for 索引, (_, 文本, _) in enumerate(ocr结果):
        if "建议升级" in 文本:
            起始索引 = 索引
        elif "其他升级" in 文本 and 起始索引 is not None:
            结束索引 = 索引
            break

    return 起始索引, 结束索引

import re


def 看起来像建筑(文本: str) -> bool:
    """
    判断一段文本是否“语义上可能是建筑名称”。

    过滤规则包括：
    - 长度过短
    - 纯数字 / 金额 / 时间
    - OCR 常见噪声词

    :param 文本: OCR 识别出的文本
    :return: 是否可能是建筑名称
    """

    文本 = 文本.strip()

    # 1. 长度过短（如单字噪声）
    if len(文本) < 2:
        return False

    # 2. 纯数字（价格、数量），包括空格、逗号、点
    if re.fullmatch(r"[\d\s.,]+", 文本):
        return False

    # 3. 时间描述
    if any(单位 in 文本 for 单位 in ("分钟", "秒")):
        return False

    # 4. 金额或数值格式（如 7.000 / 1,500）
    if re.fullmatch(r"[\d.,]+", 文本):
        return False

    # 5. OCR 已知噪声
    噪声词集合 = {"DRDDY", "批究"}
    if 文本 in 噪声词集合:
        return False

    return True
