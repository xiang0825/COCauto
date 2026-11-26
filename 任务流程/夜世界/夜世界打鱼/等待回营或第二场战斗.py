import time
from 任务流程.基础任务框架 import 任务上下文
from 任务流程.夜世界.夜世界打鱼 import 下兵
from 任务流程.夜世界.夜世界打鱼.下兵 import 停止并等待英雄技能线程
from 任务流程.夜世界.夜世界打鱼.夜世界基础任务类 import 夜世界基础任务


class 等待回营或第二次战斗(夜世界基础任务):
    """注释字符"""
    def __init__(self,上下文: 任务上下文, 只等待回营: bool = False):
        super().__init__(上下文)
        # 只等待回营：本场首兵槽已多次被安全护栏拒绝、重试已用尽。
        # 此模式在结算前绝不点换兵种箭头、兵槽或执行下兵，只等本场
        # 结束后经新截图复核结算页再安全回营。
        self.只等待回营 = bool(只等待回营)



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
                    if not 停止并等待英雄技能线程(self.上下文, 超时秒=5.0):
                        self.上下文.置脚本状态(
                            "夜世界英雄技能线程未退出，禁止点击结算奖励遮罩"
                        )
                        return False
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

                if not getattr(self, "只等待回营", False) and (
                    (页面 == "战斗中" and (
                        self.是否出现换兵种箭头()
                        or self._第二场开始倒计时已出现()
                    ))
                    or (not 有页面识别 and self.是否出现换兵种箭头())
                ):

                    if not 停止并等待英雄技能线程(self.上下文, 超时秒=5.0):
                        self.上下文.页面恢复失败 = True
                        self.上下文.置脚本状态(
                            "上一场夜世界英雄技能线程未退出，禁止开始第二场下兵"
                        )
                        return False

                    self.上下文.置脚本状态("第二次战斗")
                    self.上下文.置脚本状态("开始下兵逻辑",3*60)
                    self._夜世界结算统计已记录 = False
                    if not 下兵(self.上下文).执行():
                        self.上下文.页面恢复失败 = True
                        self.上下文.置脚本状态(
                            "夜世界第二场下兵未完成，停止继续等待或点击"
                        )
                        return False

                self.上下文.脚本延时(50)

                if self.尝试点击回营按钮():
                    return True

            self.上下文.置脚本状态(
                f"夜世界回营等待超时{超时时间}秒；保留当前游戏画面并结束本轮，不触发关机异常"
            )
            return False
        except Exception as e:
            self.异常处理(e)
            return False
        finally:
            停止并等待英雄技能线程(self.上下文, 超时秒=5.0)

    def _读取页面状态(self):
        """返回页面识别结果和“是否有真实页面识别器”标志。"""
        识别 = getattr(self.上下文, "识别点击画面", None)
        if not callable(识别):
            return None, False
        try:
            return 识别(), True
        except Exception:
            return None, True

    # 第二场开始前顶部显示“離戰鬥開始剩下 / 离战斗开始剩下”，第一场进行中
    # 显示“结束剩下”。OCR 只作箭头模板漏检时的辅助证据，并节流调用。
    第二场倒计时OCR区域 = (280, 0, 520, 42)
    第二场倒计时OCR间隔秒 = 2.0

    def _第二场开始倒计时已出现(self) -> bool:
        """只读 OCR 顶部倒计时标题，确认第二场（开始前倒计时）已出现。"""
        现在 = time.monotonic()
        上次 = float(getattr(self, "_上次第二场OCR时间", 0.0) or 0.0)
        if 上次 and 现在 - 上次 < self.第二场倒计时OCR间隔秒:
            return False
        self._上次第二场OCR时间 = 现在
        识别 = getattr(self, "执行OCR识别", None)
        if not callable(识别):
            return False
        try:
            结果 = 识别(self.第二场倒计时OCR区域) or []
        except Exception:
            return False
        文字列表 = []
        for 项 in 结果:
            try:
                文字列表.append(str(项[1][0] if isinstance(项[1], (list, tuple)) else 项[1]))
            except (TypeError, IndexError, KeyError):
                文字 = 项.get("文字") if isinstance(项, dict) else None
                if 文字:
                    文字列表.append(str(文字))
        return self.是第二场开始倒计时文字("".join(文字列表))

    @staticmethod
    def 是第二场开始倒计时文字(文字: str) -> bool:
        文字 = str(文字 or "").replace(" ", "")
        if not 文字 or "结束" in 文字 or "結束" in 文字:
            return False
        return ("开始" in 文字 or "開始" in 文字) and "剩" in 文字

    def 是否出现换兵种箭头(self):
        """验证是否已开始战斗"""
        # 箭头素材来自早期 4:3 客户端；16:9 实机上原尺度仅 0.66~0.78，
        # 需要按设备几何缩放模板（1280×720 为 sx≈0.9、sy≈1.2）才能达到
        # 0.92 以上。阈值保持 0.9，800×600 参考尺寸不做额外尺度。
        是否匹配, (x, y)=self.是否出现图片(
            "更换兵种箭头[1].bmp|更换兵种箭头[2].bmp|更换兵种箭头[3].bmp|更换兵种箭头[4].bmp|更换兵种箭头[5].bmp",
            (163,495,800,600),
            几何多尺度=True,
        )
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
            完整 = bool(
                统计任务.记录战斗结果(
                    self.上下文,
                    屏幕图像,
                    结算页已复核=True,
                    战斗世界="夜世界",
                )
            )
            if not 完整:
                self.上下文.置脚本状态(
                    "夜世界结算结果未完整确认，保留结算页并禁止进入下一场"
                )
            return 完整
        except Exception as 异常:
            self.上下文.置脚本状态(f"夜世界结算统计失败，保留当前画面：{异常}")
            return False

    def _回营后清除结算保护(self):
        """回营按钮确认点击后清除结算状态，避免下一轮入口被拦截。"""
        清理 = getattr(self.上下文, "清除战斗结算保护状态", None)
        if callable(清理):
            清理()


    def 尝试点击回营按钮(self):
        """只用新抓取且复核为结算页的画面记录结果并点击回营。"""
        try:
            当前结算 = self._捕获已确认结算画面()
            if 当前结算 is None:
                return False
            屏幕图像, _坐标 = 当前结算

            if not getattr(self, "_夜世界结算统计已记录", False):
                if not self._记录结算统计(屏幕图像):
                    self.上下文._战斗中 = True
                    return False
                self._夜世界结算统计已记录 = True

            # 安全点击会暂时清空共享输入回调；后台英雄技能线程必须先
            # 收到停止信号并 join 成功，不能与这段无护栏窗口并发输入。
            if not 停止并等待英雄技能线程(self.上下文, 超时秒=5.0):
                self.上下文._战斗中 = True
                self.上下文.置脚本状态(
                    "夜世界英雄技能线程未确认退出，保留安全点击回调并继续等待"
                )
                return False

            # 统计可能触发补拍/等待动画；点击坐标必须来自统计结束后的
            # 最新结算截图，不能继续使用旧帧上的模板坐标。
            最新结算 = self._捕获已确认结算画面()
            if 最新结算 is None:
                self.上下文._战斗中 = True
                self.上下文.置脚本状态(
                    "结算补拍未再确认回营按钮，保留画面并继续等待"
                )
                return False
            _, 坐标 = 最新结算

            self.上下文._战斗中 = False
            安全点击 = getattr(self.上下文, "点击已确认安全按钮", None)
            if callable(安全点击):
                点击成功 = 安全点击(*坐标, 延时=300)
            else:
                点击成功 = self.上下文.点击(*坐标)
            if 点击成功 is not False:
                self.上下文.置脚本状态(
                    f"新截图再次确认夜世界结算页，安全点击回营按钮：{坐标[0]},{坐标[1]}"
                )
                self._回营后清除结算保护()
                return True
            self.上下文._战斗中 = True
            return False
        except Exception as 异常:
            self.上下文._战斗中 = True
            self.上下文.置脚本状态(f"夜世界回营复核失败，保留当前画面：{异常}")
            return False

    def _捕获已确认结算画面(self):
        """强制抓取当前屏幕，仅在页面识别和按钮定位都通过时返回。"""
        try:
            获取图像 = getattr(getattr(self.上下文, "op", None), "获取屏幕图像cv", None)
            if not callable(获取图像):
                return None
            try:
                屏幕图像 = 获取图像(0, 0, 800, 600, 强制刷新=True)
            except TypeError:
                屏幕图像 = 获取图像(0, 0, 800, 600)
            获取识别器 = getattr(self.上下文, "_获取点击页面识别器", None)
            if callable(获取识别器):
                识别器 = 获取识别器()
            else:
                from 模块.检测.页面识别器 import 页面识别器
                识别器 = 页面识别器(self.模板识别)
            页面结果 = 识别器.识别(屏幕图像, 战斗中=True)
            if getattr(页面结果, "页面", "") != "战斗结算":
                return None
            坐标 = 识别器.定位结算回营按钮(屏幕图像)
            if 坐标 is None:
                return None
            return 屏幕图像, 坐标
        except Exception as 异常:
            self.上下文.置脚本状态(f"当前截图未能确认夜世界结算页：{异常}")
            return None
