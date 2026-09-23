import time
from 任务流程.基础任务框架 import 任务上下文
from 任务流程.夜世界.夜世界打鱼 import 下兵
from 任务流程.夜世界.夜世界打鱼.夜世界基础任务类 import 夜世界基础任务


class 等待回营或第二次战斗(夜世界基础任务):
    """注释字符"""
    def __init__(self,上下文: 任务上下文):
        super().__init__(上下文)



    def 执行(self) -> bool:
        """执行进入夜世界的主逻辑"""
        try:
            # 测试服夜世界即使已经 100%/3 星，也可能继续播放到倒计时
            # 结束；实测曾在 180 秒时仍剩 15 秒，过短会把正常结算误报
            # 为卡死并停止机器人。保留有限上限，给完整战斗和结算动画
            # 留出余量，但仍避免无限等待。
            超时时间 = 60*5  # 秒
            开始时间 = time.time()

            while time.time() - 开始时间 < 超时时间:
                页面结果, 有页面识别 = self._读取页面状态()
                页面 = str(getattr(页面结果, "页面", "") or "")

                # 结算后的星级奖励遮罩可能先于回营页渲染。它不是第二
                # 场战斗证据，先安全确认并重新读取页面，避免旧兵种箭头
                # 模板透过遮罩误触发第二次下兵。
                if 页面 == "战斗星级奖励":
                    self.上下文._战斗中 = False
                    处理奖励 = getattr(
                        self.上下文, "处理战斗星级奖励弹窗", None
                    )
                    if callable(处理奖励):
                        处理奖励()
                    self.上下文.置脚本状态(
                        "夜世界回营阶段识别到星级奖励过渡，已阻止第二场下兵"
                    )
                    self.上下文.脚本延时(350)
                    continue

                if 页面 in {"断线弹窗", "系统维护"}:
                    self.上下文.页面恢复失败 = True
                    self.上下文.置脚本状态(
                        f"夜世界回营阶段识别到{页面}，禁止开始第二场战斗"
                    )
                    return False

                if (
                    页面 == "战斗中" and self.是否出现换兵种箭头()
                ) or (
                    not 有页面识别 and self.是否出现换兵种箭头()
                ):

                    if hasattr(self.上下文, '英雄技能标志'):
                        self.上下文.英雄技能标志.set()

                    self.上下文.置脚本状态("第二次战斗")
                    self.上下文.置脚本状态("开始下兵逻辑",3*60)
                    if not 下兵(self.上下文).执行():
                        self.上下文.页面恢复失败 = True
                        self.上下文.置脚本状态(
                            "夜世界第二场下兵未完成，停止继续等待或点击"
                        )
                        return False

                self.上下文.脚本延时(50)

                if self.尝试点击回营按钮():
                    return True

            raise RuntimeError(
                f"操作超时：{超时时间}秒内未确认战斗结束或回营按钮，保留当前游戏画面"
            )
        except Exception as e:
            self.异常处理(e)
            return False
        finally:
            if hasattr(self.上下文, '英雄技能标志'):
                self.上下文.英雄技能标志.set()
                try: delattr(self.上下文, '英雄技能标志')
                except Exception: pass

    def _读取页面状态(self):
        """返回页面识别结果和“是否有真实页面识别器”标志。"""
        识别 = getattr(self.上下文, "识别点击画面", None)
        if not callable(识别):
            return None, False
        try:
            return 识别(), True
        except Exception:
            return None, True

    def 是否出现换兵种箭头(self):
        """验证是否已开始战斗"""
        是否匹配, (x, y)=self.是否出现图片("更换兵种箭头[1].bmp|更换兵种箭头[2].bmp|更换兵种箭头[3].bmp|更换兵种箭头[4].bmp|更换兵种箭头[5].bmp",(163,495,800,600))
        if 是否匹配:
            if self.上下文.点击(x-18, y-28) is False:
                self.上下文.置脚本状态(
                    "夜世界第二场换兵箭头点击被安全输入层拒绝，停止继续下兵"
                )
                return False
            return True
        else:
            return False

    def _记录结算统计(self, 屏幕图像=None) -> bool:
        """夜世界回营前复用统一结算统计，阻止未记录就开启下一场。"""
        # 轻量单元测试上下文可能只验证回营坐标，没有完整数据库；真实
        # 机器人上下文始终具备这两个字段，不能在真实路径跳过强制统计。
        if not hasattr(self.上下文, "数据库") or not hasattr(self.上下文, "机器人标志"):
            return True
        try:
            from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务

            统计任务 = 等待战斗结束并回营任务(self.上下文)
            完整 = bool(统计任务.记录战斗结果(self.上下文, 屏幕图像))
            if not 完整:
                self.上下文.置脚本状态(
                    "夜世界结算结果未完整确认，保留结算页并禁止进入下一场"
                )
            return 完整
        except Exception as 异常:
            self.上下文.置脚本状态(f"夜世界结算统计失败，保留当前画面：{异常}")
            return False


    def 尝试点击回营按钮(self):
        """验证是否已开始战斗"""
        # 先用共享页面识别确认结算，再用已经确认的绿色按钮坐标输入。
        # 普通“点击”会经过战斗护栏；若仍保留 _战斗中=True，护栏会正确
        # 阻止结算页输入，旧实现因此一直卡在结算页。安全恢复按钮只
        # 绕过重复护栏，不接受未识别坐标。
        try:
            获取识别器 = getattr(self.上下文, "_获取点击页面识别器", None)
            if callable(获取识别器):
                识别器 = 获取识别器()
                屏幕图像 = self.上下文.op.获取屏幕图像cv(
                    0, 0, 800, 600, 强制刷新=True
                )
                页面结果 = 识别器.识别(屏幕图像, 战斗中=True)
                if getattr(页面结果, "页面", "") == "战斗结算":
                    坐标 = 识别器.定位结算回营按钮(屏幕图像)
                    if 坐标 is not None:
                        if not self._记录结算统计(屏幕图像):
                            self.上下文._战斗中 = True
                            return False
                        self.上下文._战斗中 = False
                        安全点击 = getattr(self.上下文, "点击已确认安全按钮", None)
                        if callable(安全点击):
                            点击成功 = 安全点击(*坐标, 延时=300)
                        else:
                            点击成功 = self.上下文.点击(*坐标)
                        if 点击成功 is not False:
                            self.上下文.置脚本状态(
                                f"视觉确认夜世界结算页，安全点击回营按钮：{坐标[0]},{坐标[1]}"
                            )
                            return True
                        self.上下文._战斗中 = True
        except Exception as 异常:
            self.上下文.置脚本状态(f"视觉定位夜世界回营按钮失败，继续等待：{异常}")

        # 结算页的回营按钮实际位于画面下方中央。全屏搜索会在夜世界主页
        # 的资源栏/建筑上产生低分误匹配，而默认 0.9 又会漏掉不同缩放下
        # 的按钮。限制区域并使用已验证的安全阈值，避免结算后无限等待。
        是否匹配, (x, y) = self.是否出现图片(
            "夜世界_回营.bmp|夜世界_回营[1].bmp",
            (300, 450, 500, 560),
            0.58,
        )
        if 是否匹配:
            if not self._记录结算统计():
                self.上下文._战斗中 = True
                return False
            self.上下文._战斗中 = False
            安全点击 = getattr(self.上下文, "点击已确认安全按钮", None)
            点击成功 = 安全点击(x, y, 延时=300) if callable(安全点击) else self.上下文.点击(x, y)
            if 点击成功 is not False:
                self.上下文.置脚本状态(f"模板确认夜世界回营按钮，安全点击：{x},{y}")
                return True
            self.上下文._战斗中 = True

        # 测试服/夜世界结算页的按钮文字和旧模板可能变化，但页面结构
        # 仍有稳定的“中央结果 + 底部绿色回营按钮”。只有共享页面识别器
        # 明确确认结算页时才允许使用这个视觉坐标，避免误点主页或宝石。
        try:
            获取识别器 = getattr(self.上下文, "_获取点击页面识别器", None)
            if callable(获取识别器):
                识别器 = 获取识别器()
            else:
                from 模块.检测.页面识别器 import 页面识别器
                识别器 = 页面识别器(self.模板识别)
            try:
                屏幕图像 = self.上下文.op.获取屏幕图像cv(
                    0, 0, 800, 600, 强制刷新=True
                )
            except TypeError:
                屏幕图像 = self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            页面结果 = 识别器.识别(屏幕图像, 战斗中=True)
            if getattr(页面结果, "页面", "") == "战斗结算":
                坐标 = 识别器.定位结算回营按钮(屏幕图像)
                if 坐标 is not None:
                    if not self._记录结算统计(屏幕图像):
                        self.上下文._战斗中 = True
                        return False
                    self.上下文._战斗中 = False
                    安全点击 = getattr(self.上下文, "点击已确认安全按钮", None)
                    点击成功 = (
                        安全点击(*坐标, 延时=300)
                        if callable(安全点击)
                        else self.上下文.点击(*坐标)
                    )
                    if 点击成功 is not False:
                        self.上下文.置脚本状态(
                            f"视觉确认夜世界结算页，安全点击回营按钮：{坐标[0]},{坐标[1]}"
                        )
                        return True
                    self.上下文._战斗中 = True
        except Exception as 异常:
            self.上下文.置脚本状态(f"视觉定位夜世界回营按钮失败，继续等待：{异常}")
        else:
            return False
        return False
