import re
import math
import time

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
    建筑标签搜索区域 = (160, 250, 700, 460)
    研究按钮搜索区域 = (260, 400, 700, 560)
    # 测试服当前 800×600 主世界布局中，实验室标签过小且经常被装饰物
    # 遮挡，OCR 可能完全漏掉。这个点只作为“主世界已确认且 OCR 漏检”
    # 时的单次候选，不作为研究按钮直接点击；后续仍必须识别到“研究”
    # 按钮，避免把其它建筑的升级按钮误当成研究入口。
    实验室备用建筑点击 = (487, 370)
    实验室备用研究按钮 = (490, 470)
    最大入口等待秒 = 6.0

    def 执行(self) -> bool:
        try:
            if self._检查实验室是否空闲():
                return self._打开研究入口()
            return False
        except Exception as e:
            # 转场帧可能只有单个数字或 OCR 为空；无法确认实验室状态
            # 时必须安全跳过，不能把页面上的任何坐标当作研究入口。
            self.上下文.置脚本状态(f"研究面板状态暂时无法确认，已安全跳过：{e}")
            return False

    @staticmethod
    def _规范化文本(文本) -> str:
        return str(文本 or "").replace(" ", "").replace("\n", "")

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
        目标x = 450 if y最大 <= 460 else 490
        目标y = 375 if y最大 <= 460 else 470
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

    def _等待研究文字(self, 区域, 截止时间):
        while time.monotonic() < 截止时间:
            位置 = self._读取研究文字(区域)
            if 位置 is not None:
                return 位置
            self.上下文.脚本延时(250)
        return None

    def _打开研究入口(self) -> bool:
        """通过已识别的实验室和研究按钮打开研究面板。"""
        self.上下文.置脚本状态("正在定位实验室研究入口")
        标签位置 = self._等待研究文字(
            self.建筑标签搜索区域,
            time.monotonic() + self.最大入口等待秒,
        )
        使用备用实验室点 = 标签位置 is None
        if 使用备用实验室点:
            标签位置 = self.实验室备用建筑点击
            self.上下文.置脚本状态(
                "实验室标签OCR漏检，使用已验证的主世界实验室候选点"
            )
        if self.上下文.点击(*map(round, 标签位置), 是否精确点击=True) is False:
            self.上下文.置脚本状态("实验室选择未被安全输入层接受，停止研究操作")
            return False

        # 研究按钮点击前保留“实验室已选中”的基准画面；研究面板会
        # 覆盖大部分地图。如果点击后画面几乎没有变化，就不能把一次
        # 普通地图点击误报成“研究面板已打开”。
        研究前画面 = self._获取全屏画面()

        if 使用备用实验室点:
            # 当前测试服的研究按钮文字尺寸很小，面板已由上面的实验室
            # 候选点确定后，使用同一 800×600 参考布局中的已验证按钮点。
            # 这一步只在实验室候选点路径触发，不对未确认的普通建筑生效。
            研究位置 = self.实验室备用研究按钮
        else:
            研究位置 = self._等待研究文字(
                self.研究按钮搜索区域,
                time.monotonic() + self.最大入口等待秒,
            )
        if 研究位置 is None:
            self.上下文.置脚本状态("实验室已选中但未识别到研究按钮，安全跳过研究升级")
            return False
        if self.上下文.点击(*map(round, 研究位置), 是否精确点击=True) is False:
            self.上下文.置脚本状态("研究按钮未被安全输入层接受，停止研究操作")
            return False
        if not self._画面变化明显(研究前画面):
            self.上下文.置脚本状态(
                "研究按钮点击后画面未切换到研究面板，安全停止，禁止在主世界滑动"
            )
            return False
        self.上下文.置脚本状态("研究面板已打开")
        return True

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
