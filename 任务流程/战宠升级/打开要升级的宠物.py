import random

import cv2
import numpy as np

from 任务流程.基础任务框架 import 基础任务, 任务上下文
from 任务流程.战宠升级.图像算法 import 从内部点获取黑框坐标, 是否包含指定颜色_HSV


class 无法定位目标宠物错误(Exception):
    def __init__(self, 错误信息):
        super().__init__(错误信息)
        self.错误信息 = 错误信息

    def __str__(self):
        return f"发生了：{self.错误信息}"


class 打开要升级的宠物任务(基础任务):

    def __init__(self, 上下文: '任务上下文',欲打开的宠物):
        super().__init__(上下文)
        self.欲打开的宠物=欲打开的宠物
        self.宠物模板列表={
            "莱希":"莱希.bmp",
            "闪枭":"闪枭.bmp",
            "大耗":"大耗.bmp",
            "独角":"独角.bmp",
            "冰牙":"冰牙.bmp",
            "地兽":"地兽.bmp",
            "猛蜥":"猛蜥.bmp",
            "凤凰":"凤凰.bmp",
            "灵狐":"灵狐.bmp",
            "愤怒水母":"愤怒水母.bmp",
            "阿啾":"阿啾.bmp"}

    def 执行(self) -> bool:

        try:

            # if self.是否出现图片("战宠小屋_立即完成升级.bmp",(450,122,764,297),相似度阈值=0.98):
            #     print(123)
            #     self.上下文.置脚本状态("战宠升级：当前有宠物正在升级中")
            #     self.关闭战宠小屋页面()
            #     return False

            ocr结果=self.执行OCR识别((566,139,753,296))
            print(ocr结果)
            if "完成升级" in ocr结果.__str__() or "级" in ocr结果.__str__():
                self.上下文.置脚本状态("战宠升级：当前有宠物正在升级中")

                self.关闭战宠小屋页面()
                return False


            if not self.当前是否存在目标宠物():
                self.滑动到目标宠物位置()

            if not self.检测可打开条件():
                return False

            _, (x, y) = self.是否出现图片(self.宠物模板列表[self.欲打开的宠物])
            if self.上下文.点击(x,y) is False:#打开要升级的宠物界面
                self.上下文.置脚本状态(
                    f"战宠升级：{self.欲打开的宠物} 入口点击未被安全输入层接受"
                )
                self.关闭战宠小屋页面()
                return False
            return True

        except 无法定位目标宠物错误 as e:
            self.上下文.置脚本状态(e.__str__())
            self.关闭战宠小屋页面()
            return False
        except Exception as e:
            self.异常处理(e)
            return False


    def 滑动到目标宠物位置(self):
        随机半径=20
        start_x = 734 + 随机半径
        start_y = 429 + 随机半径
        self.上下文.鼠标.移动到(start_x, start_y)
        self.上下文.鼠标.左键按下()

        for x in range(200):
            self.上下文.鼠标.移动相对位置(-random.randint(5,8),0)
            self.上下文.脚本延时(0)

            if self.当前是否存在目标宠物():
                self.上下文.鼠标.左键抬起()
                self.上下文.脚本延时(random.randint(800, 1000))
                return

        self.上下文.鼠标.左键抬起()
        raise 无法定位目标宠物错误(f"战宠升级：滑动列表后仍未找到 {self.欲打开的宠物}，可能该宠物没解锁")

    def 检测可打开条件(self):

        _, (x, y) = self.是否出现图片(self.宠物模板列表[self.欲打开的宠物])
        屏幕图像 = self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)
        # 获取宠物区域
        (x1,y1),(x2,y2)=从内部点获取黑框坐标(屏幕图像,x,y,调试=False)

        #判断是否最高等级
        ocr结果=self.执行OCR识别((x1,y1,x2,y2))
        if "最高等级" in ocr结果.__str__():
            self.上下文.置脚本状态(f"战宠升级：{self.欲打开的宠物} 已满级")
            self.关闭战宠小屋页面()
            return False

        #判断是否够资源升级
        区域图像=self.上下文.op.获取屏幕图像cv(x1,y1,x2,y2)
        是否有红色调偏粉色块 = 是否包含指定颜色_HSV(
            区域图像, (250, 135, 124),
            色差H=10, 色差S=10, 色差V=10,
            最少像素数=150
        )
        if 是否有红色调偏粉色块:  # 根据实际情况调整阈值
            self.上下文.置脚本状态(f"战宠升级：{self.欲打开的宠物} 资源不足")
            self.关闭战宠小屋页面()
            return False

        self.上下文.置脚本状态(f"战宠升级：正在升级 {self.欲打开的宠物}")
        return True

    def 关闭战宠小屋页面(self):
        """关闭战宠小屋，并在回到主世界后清理底层选中卡片。"""
        安全返回键 = getattr(self.上下文, "安全返回键", None)
        关闭结果 = True
        if callable(安全返回键):
            关闭结果 = bool(
                安全返回键("关闭战宠小屋页面", 已确认可关闭面板=True)
            )
        else:
            self.上下文.置脚本状态(
                "未提供战宠小屋安全关闭器，禁止发送ESC；保留当前页面等待人工确认"
            )
            return False

        # 战宠小屋是从主世界建筑上打开的：关闭顶部小屋页后，测试服
        # 可能仍留下底层“战宠小屋”选中卡片。只有重新确认已经回到
        # 主世界主页时才点击右侧林地空白点；未知页、战斗页和弹窗页
        # 一律不发送额外输入，避免把收尾动作变成误触。
        识别页面 = getattr(self.上下文, "识别点击画面", None)
        点击 = getattr(self.上下文, "点击", None)
        if 关闭结果 and callable(识别页面) and callable(点击):
            try:
                结果 = 识别页面()
                if (
                    getattr(结果, "页面", "") == "主世界主页"
                    and getattr(结果, "世界", "主世界") in {"主世界", "未知", ""}
                ):
                    if 点击(700, 300, 延时=700, 是否精确点击=True):
                        self.上下文.置脚本状态(
                            "战宠小屋已关闭，并通过主世界空白区域清理底层选中卡片"
                        )
            except Exception as 异常:
                self.上下文.置脚本状态(
                    f"战宠小屋底层选中卡片清理失败，保留当前页面：{异常}"
                )
        return 关闭结果



    def 当前是否存在目标宠物(self):
        是否存在,(x,y)=self.是否出现图片(self.宠物模板列表[self.欲打开的宠物], 区域=(26,312,641,533))

        return 是否存在

