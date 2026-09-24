import random
import time

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

    # 目标宠物未解锁或列表转场异常时，扫描必须有界；期间持续写入
    # 心跳，避免监控器把正常 OCR/滑动误判成死线程。
    滑动扫描最长秒数 = 45.0

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
        停止事件 = getattr(self.上下文, "停止事件", None)
        if 停止事件 is not None and 停止事件.is_set():
            raise SystemExit("收到外部停止请求，停止战宠列表扫描")

        截止时间 = time.monotonic() + float(self.滑动扫描最长秒数)
        上次心跳 = time.monotonic()
        self.上下文.鼠标.移动到(start_x, start_y)
        self.上下文.鼠标.左键按下()
        try:
            for x in range(200):
                if 停止事件 is not None and 停止事件.is_set():
                    raise SystemExit("收到外部停止请求，停止战宠列表扫描")
                if time.monotonic() >= 截止时间:
                    raise 无法定位目标宠物错误(
                        f"战宠升级：滑动列表扫描超时，仍未找到 {self.欲打开的宠物}"
                    )

                self.上下文.鼠标.移动相对位置(-random.randint(5,8),0)
                self.上下文.脚本延时(20)

                if self.当前是否存在目标宠物():
                    self.上下文.脚本延时(random.randint(800, 1000))
                    return

                # OCR/模板匹配本身可能持续数秒；每隔几秒刷新一次心跳，
                # 同时保留当前进度，便于区分“未解锁”与真的卡死。
                现在 = time.monotonic()
                if 现在 - 上次心跳 >= 4.0:
                    self.上下文.置脚本状态(
                        f"战宠升级：正在扫描 {self.欲打开的宠物}，已尝试{x + 1}个列表位置"
                    )
                    上次心跳 = 现在
        finally:
            # 无论成功、超时还是外部停止，都不能把按下状态留在模拟器里。
            self.上下文.鼠标.左键抬起()

        raise 无法定位目标宠物错误(
            f"战宠升级：滑动列表后仍未找到 {self.欲打开的宠物}，可能该宠物没解锁"
        )

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
        识别页面 = getattr(self.上下文, "识别点击画面", None)
        关闭结果 = True

        # 安全返回键在主世界会触发“确认退出游戏”。战宠列表扫描超时、
        # 转场漏识别或外部停止后，画面可能已经回到主世界，不能只依赖
        # 调用方传入的“已确认面板”标记。先做页级复核：主世界只点空白
        # 清理选中卡片；未知/普通多按钮弹窗禁止发送返回键，除非 OCR
        # 明确看到战宠面板文字。
        if callable(识别页面):
            try:
                页面结果 = 识别页面()
                页面 = str(getattr(页面结果, "页面", "") or "")
                if 页面 == "主世界主页":
                    点击 = getattr(self.上下文, "点击", None)
                    if callable(点击) and 点击(700, 300, 延时=700, 是否精确点击=True):
                        self.上下文.置脚本状态(
                            "战宠页面已回到主世界，仅清理选中卡片；禁止发送返回键"
                        )
                        return True
                    self.上下文.页面恢复失败 = True
                    self.上下文.置脚本状态(
                        "战宠页面已回到主世界，但安全空白清理被拒绝，禁止发送返回键"
                    )
                    return False
                if 页面 not in {"多按钮弹窗", "未知", ""}:
                    self.上下文.页面恢复失败 = True
                    self.上下文.置脚本状态(
                        f"当前页面为{页面}，不是已确认战宠面板，禁止发送返回键"
                    )
                    return False

                OCR结果 = self.执行OCR识别((180, 250, 760, 590))
                文本 = "".join(
                    str(项[1]) for 项 in (OCR结果 or [])
                    if isinstance(项, (list, tuple)) and len(项) >= 2
                )
                if not any(关键词 in 文本 for 关键词 in ("战宠", "戰寵")):
                    self.上下文.页面恢复失败 = True
                    self.上下文.置脚本状态(
                        "未确认战宠面板文字，禁止发送返回键以避免退出游戏"
                    )
                    return False
            except Exception as 异常:
                self.上下文.页面恢复失败 = True
                self.上下文.置脚本状态(
                    f"战宠页面复核失败，禁止发送返回键：{异常}"
                )
                return False

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
                    else:
                        关闭结果 = False
                        self.上下文.页面恢复失败 = True
                        self.上下文.置脚本状态(
                            "战宠小屋底层选中卡片清理点击被安全层拒绝，停止后续操作"
                        )
            except Exception as 异常:
                self.上下文.页面恢复失败 = True
                self.上下文.置脚本状态(
                    f"战宠小屋底层选中卡片清理失败，保留当前页面：{异常}"
                )
        return 关闭结果



    def 当前是否存在目标宠物(self):
        是否存在,(x,y)=self.是否出现图片(self.宠物模板列表[self.欲打开的宠物], 区域=(26,312,641,533))

        return 是否存在

