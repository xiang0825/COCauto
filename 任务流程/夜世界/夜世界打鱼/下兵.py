from 任务流程.基础任务框架 import 任务上下文
from 任务流程.夜世界.夜世界打鱼.夜世界基础任务类 import 夜世界基础任务
import random
import threading
import time

class 下兵(夜世界基础任务):
    # 夜世界新版兵栏的第 2 格可能是灰色/空槽；其余槽位按 800×600
    # 逻辑画布排列。这里只选择普通兵种槽，不把左侧英雄槽误当兵种。
    兵种槽位 = ((150, 520), (278, 520), (340, 520), (402, 520), (465, 520))
    # 这些点位位于基地外沿，避开兵栏、放弃按钮和基地内部；每个槽位
    # 只执行有限批次，防止旧模板失配时随机点击拖满整场战斗。
    可下兵点 = ((45, 250), (400, 80), (755, 250), (45, 500), (755, 500))

    def __init__(self ,上下文: '任务上下文'):
        super().__init__(上下文)


    def 执行(self) -> bool:

        try:
            self.上下文._战斗中 = True
            self.上下文.脚本延时(random.randint(300, 600))
            if not self._等待真实战斗画面():
                self.上下文.页面恢复失败 = True
                self.上下文.置脚本状态(
                    "夜世界战斗仍在过渡或已结束，禁止向非战斗画面下兵"
                )
                return False
            if not self.执行下兵操作():
                self.上下文.页面恢复失败 = True
                self.上下文.置脚本状态(
                    "夜世界未确认完成下兵，停止后续英雄/技能点击"
                )
                return False

            # 选择英雄
            if self.上下文.点击(80, 520) is False:
                self.上下文.页面恢复失败 = True
                self.上下文.置脚本状态("夜世界英雄槽点击未确认成功，停止本场操作")
                return False

            # 出英雄
            点击序列 = [
                (55, 299),
                (408, 119),
                (640, 232)
            ]
            random.shuffle(点击序列)
            for 坐标 in 点击序列:
                x, y = 坐标
                if self.上下文.点击(x, y) is False:
                    self.上下文.页面恢复失败 = True
                    self.上下文.置脚本状态("夜世界英雄下兵点击未确认成功，停止本场操作")
                    return False
                self.上下文.脚本延时(random.randint(100, 300))

            # 把英雄技能提取到后台循环执行
            self.上下文.置脚本状态("后台循环释放英雄技能")
            self.启动后台放英雄技能()

            技能次数=0
            while self.尝试点击放兵种技能():
                技能次数 += 1
                self.上下文.脚本延时(random.randint(20, 60))
                self.上下文.置脚本状态("放兵种技能")
                if 技能次数>=40:
                    raise RuntimeError(f"一直在放兵种技能,超过{技能次数}次")

            self.上下文.置脚本状态("兵种技能已放完，等待战斗结束",3*60)
            return True

        except Exception as e:
            self.异常处理(e)
            return False

    def _等待真实战斗画面(self) -> bool:
        """等待战斗过渡结束，避免把过渡页误当成可下兵画面。"""
        识别 = getattr(self.上下文, "识别点击画面", None)
        if not callable(识别):
            # 旧测试替身没有页面识别接口；真实运行时由基础上下文提供。
            return True
        截止时间 = time.monotonic() + 20
        while time.monotonic() < 截止时间:
            if getattr(self.上下文, "停止事件", None) is not None and self.上下文.停止事件.is_set():
                return False
            结果 = 识别()
            页面 = str(getattr(结果, "页面", "") or "") if 结果 is not None else ""
            if 页面 == "战斗中":
                self.上下文.置脚本状态("夜世界战斗过渡完成，允许开始下兵")
                return True
            if 页面 in {"断线弹窗", "战斗结算", "系统维护"}:
                return False
            self.上下文.脚本延时(250)
        return False

    def 执行下兵操作(self) -> bool:
        # 旧版依赖“请选择其它兵种”模板作为结束条件。测试服更新后该
        # 模板可能永远不出现，导致程序在战斗中随机点击几十秒。改为
        # 固定少量安全槽位和边缘点，点击是否被战斗护栏接受作为反馈。
        总成功点击 = 0
        有效槽位 = 0
        for 槽位, (槽位x, 槽位y) in enumerate(self.兵种槽位, start=1):
            if getattr(self.上下文, "停止事件", None) is not None and self.上下文.停止事件.is_set():
                break
            选中 = self.上下文.点击(槽位x, 槽位y, 80, 是否精确点击=True)
            if 选中 is False:
                break
            本槽成功 = 0
            for 重复次数 in range(12):
                点位 = self.可下兵点[重复次数 % len(self.可下兵点)]
                if self.上下文.点击(*点位, 80, 是否精确点击=True) is False:
                    break
                本槽成功 += 1
            if 本槽成功:
                有效槽位 += 1
                总成功点击 += 本槽成功
                self.上下文.置脚本状态(
                    f"夜世界第{槽位}格完成边缘下兵{本槽成功}次"
                )
            if 本槽成功 == 0:
                break

        if 总成功点击:
            self.上下文.置脚本状态(
                f"夜世界已完成有限批次下兵：{有效槽位}个兵种槽，共{总成功点击}次；"
                "不再依赖旧版请选择其它兵种模板"
            )
            return True
        return False

    def 尝试在区域内完成下兵(self, 左上角: tuple, 右下角: tuple) -> bool:
        """在指定区域内尝试完成下兵操作，若提示下满兵则返回 True"""
        坐标列表 = self.生成随机坐标点(左上角, 右下角, random.randint(10, 20))

        for 坐标 in 坐标列表:
            if self.下兵并检测是否完成下兵(坐标):
                return True
        return False

    def 下兵并检测是否完成下兵(self, 坐标: tuple) -> bool:
        """点击指定坐标，并判断是否出现下兵完成提示"""
        self.上下文.点击(坐标[0], 坐标[1], random.randint(80, 180))
        是否匹配, _ = self.是否出现图片("夜世界_请选择其它兵种.bmp")
        #
        return 是否匹配


    def 尝试点击放兵种技能(self):
        """验证是否已开始战斗"""
        是否匹配, (x, y) = self.是否出现图片("夜世界_兵种技能色块.bmp")
        if 是否匹配:
            self.上下文.点击(x-21, y+49)
            return True
        else:
            return False

    @staticmethod
    def 生成随机坐标点(起点, 终点, 点数量=1, 最大扰动=5):
        起点x, 起点y = 起点
        终点x, 终点y = 终点
        随机点列表 = []

        for i in range(点数量):
            t = random.uniform(0, 1)  # 插值比例
            x = 起点x + (终点x - 起点x) * t
            y = 起点y + (终点y - 起点y) * t

            # 加一点扰动，模拟人类随机操作
            x += random.uniform(-最大扰动, 最大扰动)
            y += random.uniform(-最大扰动, 最大扰动)

            随机点列表.append((int(x), int(y)))

        return 随机点列表

    def 启动后台放英雄技能(self):
        if hasattr(self.上下文, '英雄技能标志'):
            return

        标志 = self.上下文.英雄技能标志 = threading.Event()

        def _工作线程():
            while not 标志.wait(random.randint(8, 15)):
                try:
                    self.上下文.点击(42, 554)
                except: pass
            try: delattr(self.上下文, '英雄技能标志')
            except: pass

        threading.Thread(target=_工作线程, daemon=True).start()
