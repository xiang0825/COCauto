import time
from 任务流程.基础任务框架 import 任务上下文
from 任务流程.夜世界.夜世界打鱼.夜世界基础任务类 import 夜世界基础任务


class 等待进入战斗(夜世界基础任务):
    """注释字符"""
    def __init__(self,上下文: 任务上下文):
        super().__init__(上下文)


    def 执行(self) -> bool:
        """执行进入夜世界的主逻辑"""
        try:
            超时时间 = 200  # 秒
            开始时间 = time.time()

            while time.time() - 开始时间 < 超时时间:

                if self.是否出现换兵种箭头():
                    self.上下文.置脚本状态("已进入战斗")
                    return True
                if self._页面已确认夜世界战斗():
                    # 当前测试服的箭头素材在自适应画布中会降到约 0.57，
                    # 但顶部倒计时和左下“放弃”按钮是稳定的战斗证据。
                    # 选中第一个普通兵槽后再交给下兵流程，避免在真实
                    # 战斗页一直等待过时模板。
                    if self.上下文.点击(145, 545, 是否精确点击=True) is False:
                        self.上下文.页面恢复失败 = True
                        self.上下文.置脚本状态(
                            "已确认夜世界战斗，但首个兵槽输入被拒绝，停止本场操作"
                        )
                        return False
                    self.上下文.置脚本状态(
                        "已通过战斗倒计时和放弃按钮确认夜世界战斗，选中首个普通兵槽"
                    )
                    return True
                self.上下文.脚本延时(50)

            raise RuntimeError(f"操作超时：一直卡白云或者某处,导致一直没能进入战斗！已经等待了{超时时间}")
        except Exception as e:
            self.异常处理(e)
            return False

    def _页面已确认夜世界战斗(self) -> bool:
        """使用共享轻量页面识别器确认夜世界战斗页。"""
        try:
            屏幕 = self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            获取识别器 = getattr(self.上下文, "_获取点击页面识别器", None)
            if not callable(获取识别器):
                return False
            结果 = 获取识别器().识别(屏幕, 战斗中=True)
            return getattr(结果, "页面", "") == "战斗中"
        except Exception:
            return False

    def 是否出现换兵种箭头(self):
        """验证是否已开始战斗"""
        是否匹配, (x, y) = self.是否出现图片(
            "更换兵种箭头[1].bmp|更换兵种箭头[2].bmp",
            (100, 480, 550, 600),
            相似度阈值=0.50,
        )
        if 是否匹配:
            self.上下文.点击(x-18, y-28)#选中对应兵种
            return True
        else:
            return False
