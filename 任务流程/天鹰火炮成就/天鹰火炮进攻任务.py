"""
天鹰火炮进攻任务 - 搜索敌人并检测天鹰火炮，使用雷电法术攻击
"""
import random
import time
from typing import Tuple, Optional

import cv2
import numpy as np

from 任务流程.基础任务框架 import 基础任务, 任务上下文
from .天鹰火炮检测器 import 天鹰火炮检测器


class 天鹰火炮进攻任务(基础任务):
    """搜索敌人并检测天鹰火炮，存在则使用雷电法术攻击，否则点击下一个"""

    def __init__(self, 上下文: '任务上下文'):
        super().__init__(上下文)
        # 注意：不重复初始化 self.模板识别，基类已初始化

        # 初始化天鹰火炮检测器
        try:
            self.天鹰检测器 = 天鹰火炮检测器()  # 使用默认路径
            self.置信度阈值 = 0.20
        except Exception as e:
            self.上下文.置脚本状态(f"天鹰火炮检测器初始化失败: {e}")
            self.天鹰检测器 = None

    def 执行(self) -> bool:
        """主执行流程"""
        上下文 = self.上下文

        if self.天鹰检测器 is None:
            上下文.置脚本状态("天鹰火炮检测器未初始化，跳过任务")
            return False

        try:
            for 搜索次数 in range(1, 51):  # 最多搜索50次
                上下文.置脚本状态(f"第{搜索次数}次搜索敌人...")

                # 等待搜索界面
                if not self.等待下一个按钮出现():
                    上下文.置脚本状态("未找到下一个按钮")
                    return False

                # 检测天鹰火炮
                上下文.置脚本状态("正在检测天鹰火炮...")
                天鹰坐标 = self.检测天鹰火炮位置()

                if 天鹰坐标:
                    x, y = 天鹰坐标
                    上下文.置脚本状态(f"检测到天鹰火炮，坐标: ({x},{y})")

                    self.使用雷电法术攻击(天鹰坐标)
                    return True

                上下文.置脚本状态(f"第{搜索次数}次未检测到天鹰火炮，点击下一个...")
                self.点击下一个按钮()
                上下文.脚本延时(1000)

            上下文.置脚本状态("搜索50次未找到天鹰火炮")
            return False

        except Exception as e:
            上下文.置脚本状态(f"天鹰火炮任务异常: {e}")
            return False

    def 检测天鹰火炮位置(self) -> Optional[Tuple[int, int]]:
        """检测天鹰火炮位置"""
        上下文 = self.上下文

        if self.天鹰检测器 is None:
            return None

        try:
            # 获取屏幕图像
            屏幕图像 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            if 屏幕图像 is None:
                return None

            # 执行检测
            检测结果 = self.天鹰检测器.检测(屏幕图像, self.置信度阈值)

            if not 检测结果:
                return None

            # 过滤掉太小的目标（可能是误检）
            有效结果 = []
            for 目标 in 检测结果:
                宽度 = 目标['宽度']
                高度 = 目标['高度']
                面积 = 目标['面积']

                # 天鹰火炮通常比较大
                if 宽度 >= 20 and 高度 >= 20 and 面积 >= 400:
                    有效结果.append(目标)

            if not 有效结果:
                return None

            # 取置信度最高的目标
            最佳目标 = max(有效结果, key=lambda x: x['置信度'])
            中心x, 中心y = 最佳目标['中心']

            return (中心x, 中心y)

        except Exception as e:
            return None

    def 使用雷电法术攻击(self, 目标坐标: Tuple[int, int]):
        """使用雷电法术攻击 - 点击11下模拟人类操作"""
        上下文 = self.上下文

        # 选中雷电法术
        if not self.选中雷电法术():
            上下文.置脚本状态("雷电法术不可用")
            return

        目标x, 目标y = 目标坐标
        攻击次数 = 11

        上下文.置脚本状态(f"开始使用雷电法术攻击 ({攻击次数}次)...")

        for 次数 in range(1, 攻击次数 + 1):
            # 每次点击都有轻微抖动
            抖动x = random.randint(-5, 5)
            抖动y = random.randint(-5, 5)

            攻击x = max(10, min(790, 目标x + 抖动x))
            攻击y = max(10, min(590, 目标y + 抖动y))

            # 随机延迟，模拟人类点击
            点击延迟 = random.randint(50, 200)  # 50-200ms随机延迟
            上下文.点击(攻击x, 攻击y, 延时=点击延迟)

            # 点击间隔时间随机化
            if 次数 < 攻击次数:  # 最后一次不需要间隔
                间隔时间 = random.randint(100, 220)  # 100-220ms随机间隔
                上下文.脚本延时(间隔时间)

        上下文.置脚本状态(f"雷电法术攻击完成 ({攻击次数}次)")
        上下文.脚本延时(800)  # 最终等待

    def 选中雷电法术(self) -> bool:
        """选中雷电法术"""
        上下文 = self.上下文

        # 法术区域 (屏幕底部)
        检测区域 = (10, 500, 780, 590)
        屏幕图像 = 上下文.op.获取屏幕图像cv(*检测区域)

        if 屏幕图像 is None:
            return False

        # 尝试多种模板名称
        模板列表 = ["法术_闪电法术.bmp", "闪电法术.bmp", "雷电法术.bmp",
                  "闪电.bmp", "thunder_spell.bmp", "lightning_spell.bmp"]

        是否匹配 = False
        偏移 = (0, 0)

        for 模板 in 模板列表:
            是否匹配, 偏移, _ = self.模板识别.执行匹配(屏幕图像, 模板, 0.65)
            if 是否匹配:
                break

        if not 是否匹配:
            return False

        偏移x, 偏移y = 偏移
        法术位置 = (检测区域[0] + 偏移x, 检测区域[1] + 偏移y)

        # 检查是否已用完（检查图标区域是否为灰色）
        图标区域 = 上下文.op.获取屏幕图像cv(
            法术位置[0]-10, 法术位置[1]-10,
            法术位置[0]+30, 法术位置[1]+30
        )

        if self.是否为灰色图片(图标区域):
            return False

        # 添加轻微抖动点击
        抖动x = random.randint(-3, 3)
        抖动y = random.randint(-3, 3)
        实际位置 = (法术位置[0] + 抖动x, 法术位置[1] + 抖动y)

        # 模拟人类点击：延迟+轻微抖动
        上下文.点击(*实际位置, 延时=random.randint(150, 300))
        上下文.脚本延时(random.randint(300, 600))  # 等待选中效果

        return True

    def 等待下一个按钮出现(self) -> bool:
        """等待下一个按钮出现"""
        上下文 = self.上下文
        超时时间 = 30
        开始时间 = time.time()

        while time.time() - 开始时间 < 超时时间:
            屏幕图像 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            是否匹配, _, _ = self.模板识别.执行匹配(屏幕图像, "下一个.bmp", 0.8)

            if 是否匹配:
                return True

            上下文.脚本延时(500)

        上下文.置脚本状态("等待下一个按钮超时")
        return False

    def 点击下一个按钮(self):
        """点击下一个按钮 - 添加轻微抖动"""
        上下文 = self.上下文
        抖动x = random.randint(-4, 4)
        抖动y = random.randint(-4, 4)
        实际位置 = (694 + 抖动x, 461 + 抖动y)

        上下文.点击(*实际位置, 延时=random.randint(100, 250))

    @staticmethod
    def 是否为灰色图片(图像: np.ndarray, 偏差阈值: int = 15, 灰色比例阈值: float = 0.85) -> bool:
        """判断图片是否为灰色（表示法术已用完）"""
        if 图像 is None or len(图像.shape) != 3:
            return False

        # 转换为HSV色彩空间更容易判断饱和度
        hsv图像 = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
        饱和度 = hsv图像[:, :, 1]

        # 计算低饱和度像素的比例
        低饱和像素 = np.sum(饱和度 < 30)
        总像素 = 图像.shape[0] * 图像.shape[1]
        低饱和比例 = 低饱和像素 / 总像素

        # 计算颜色通道差异
        B, G, R = cv2.split(图像)
        差异RG = np.abs(R.astype(int) - G.astype(int))
        差异RB = np.abs(R.astype(int) - B.astype(int))
        差异GB = np.abs(G.astype(int) - B.astype(int))

        灰色像素 = np.logical_and(
            np.logical_and(差异RG < 偏差阈值, 差异RB < 偏差阈值),
            差异GB < 偏差阈值
        )
        灰色比例 = np.sum(灰色像素) / 总像素

        # 同时满足低饱和度和颜色相似
        return 低饱和比例 > 灰色比例阈值 and 灰色比例 > 灰色比例阈值
