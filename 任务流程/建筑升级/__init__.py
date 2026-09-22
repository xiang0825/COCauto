from datetime import datetime, timedelta
from 任务流程.夜世界.夜世界打鱼.夜世界基础任务类 import 夜世界基础任务
from 任务流程.建筑升级.升级普通建筑 import 升级普通建筑任务
from 任务流程.建筑升级.升级英雄 import 升级英雄任务

from 任务流程.建筑升级.寻找建筑 import 寻找建筑, 建筑查找模式
from 任务流程.建筑升级.更新工人状态 import 更新工人状态任务


class 建筑升级任务(夜世界基础任务):
    """循环执行建筑升级，直到没有空闲工人为止；失败记录并一天内不重试"""

    def __init__(self, 上下文):
        super().__init__(上下文)
        self.空闲工人: bool = False
        self.当前建筑: str | None = None

    def 执行(self) -> bool:
        try:
            指定建筑 = self.上下文.设置.欲升级的英雄或建筑
            启用建议建筑 = self.上下文.设置.是否升级建议升级的建筑

            if not 指定建筑 and not 启用建议建筑:
                self.上下文.置脚本状态("建筑升级任务,要升级的建筑列表为空,并且没有启用升级建议建筑,跳过升级建筑任务")
                # building 和 hero 共用这个任务入口；未配置目标时是正常
                # 跳过，不能被调度器当成页面恢复失败，从而阻断后面的
                # 刷资源、战宠和研究任务。
                return True

            # 先检查上次失败时间
            完整状态 = self.数据库.获取最新完整状态(self.机器人标志).状态数据
            上次失败 = 完整状态.get("建筑升级失败记录")
            if 上次失败:
                失败时间 = datetime.fromtimestamp(上次失败.get("时间", 0))
                if datetime.now() - 失败时间 < timedelta(hours=self.上下文.设置.建筑升级检查间隔):
                    self.上下文.置脚本状态( F"建筑升级任务：上次失败距离现在不到 {self.上下文.设置.建筑升级检查间隔} 小时，暂不重试，等间隔过去后将再次尝试")
                    # 冷却期是正常的本轮跳过，不应触发任务计划的页面
                    # 故障保护。
                    return True


            self.上下文.置脚本状态("开始执行循环建筑升级任务")

            if 指定建筑:
                self.上下文.置脚本状态(f"设置了要升级的固定建筑，将优先升级: {指定建筑}")
                升级列表 = 指定建筑
                查找模式 = 建筑查找模式.指定建筑
            elif 启用建议建筑:
                self.上下文.置脚本状态("没有指定固定建筑，将升级建议列表中的第一个可用建筑")
                升级列表 = None  # 在寻找任务里动态确定，将会设置为升级建议列表中的建筑
                查找模式 = 建筑查找模式.建议升级中的第一个可用建筑

            本轮已提交建筑: set[str] = set()
            while True:
                # 1. 更新工人状态
                工人任务 = 更新工人状态任务(self.上下文)
                成功 = 工人任务.执行()
                if not 成功:
                    self.记录失败("更新工人状态任务失败")
                    return False

                self.空闲工人 = 工人任务.是否有空闲工人()
                if not self.空闲工人:
                    self.上下文.置脚本状态("无空闲工人，建筑升级结束")
                    return True

                # 2. 寻找可升级建筑
                寻找任务 = 寻找建筑(
                    self.上下文,
                    升级列表,
                    查找模式,
                    排除建筑名称=(本轮已提交建筑 if 查找模式 == 建筑查找模式.建议升级中的第一个可用建筑 else None),
                )

                成功 = 寻找任务.执行()
                if not 成功:
                    self.记录失败("寻找建筑任务执行失败")
                    return False

                self.当前建筑 = 寻找任务.当前建筑
                if not self.当前建筑:
                    self.上下文.置脚本状态("未找到可升级建筑")
                    return True

                # 3. 升级找到的建筑
                if self.当前建筑 in ["野蛮人之王", "弓箭女皇", "亡灵王子", "飞盾战神", "大守护者","飞龙公爵"]:
                   升级任务 = 升级英雄任务(self.上下文, self.当前建筑)
                else:
                    升级任务 = 升级普通建筑任务(self.上下文, self.当前建筑)


                成功 = 升级任务.执行()
                if not 成功:
                    self.记录失败(f"升级建筑 {self.当前建筑} 失败")
                    return False

                self.上下文.置脚本状态(f"已完成建筑升级: {self.当前建筑}")
                本轮已提交建筑.add(self.当前建筑)
                # 升级确认后 CoC 会停留在“正在进行升级/立即完成”详情面板。
                # 不能马上读取工人状态或开始下一轮，否则下一轮会把面板当成
                # 建筑列表，甚至把“立即完成/宝石”区域当成可用按钮。
                # 这里只允许专用关闭检测器处理右上角 X，并连续确认主世界；
                # 绝不发送 Android BACK/ESC。
                if not self._升级提交后确认主世界():
                    self.记录失败("升级提交后未确认回到主世界，阻止下一轮点击")
                    return False

        except Exception as e:
            self.异常处理(e, 是否重启机器人=False)
            self.记录失败(f"任务异常: {str(e)}")
            return False

    def 记录失败(self, 原因: str):
        """将失败状态记录到数据库"""
        失败记录 = {
            "时间": datetime.now().timestamp(),
            "原因": 原因
        }
        self.数据库.更新状态(self.机器人标志, "建筑升级失败记录", 失败记录)
        self.上下文.置脚本状态(f"建筑升级失败记录已写入数据库: {原因}")

    def _升级提交后确认主世界(self) -> bool:
        """升级提交后关闭详情面板，并用两帧识别确认主世界。

        这是建筑/英雄共用的收尾护栏。关闭器返回 False 只代表没有检测到
        升级详情面板；仍需继续做主页识别，不能把“没有检测到”当成主页。
        """
        关闭器 = getattr(self.上下文, "关闭升级详情弹窗", None)
        if callable(关闭器):
            try:
                关闭器()
            except Exception as 异常:
                self.上下文.置脚本状态(f"升级详情面板收尾失败：{异常}")
                return False
            if getattr(self.上下文, "页面恢复失败", False):
                self.上下文.置脚本状态(
                    "升级详情面板已处理但未确认主世界，禁止开始下一轮建筑操作"
                )
                return False

        识别 = getattr(self.上下文, "识别点击画面", None)
        if not callable(识别):
            self.上下文.置脚本状态("升级收尾无法执行主页复核，禁止继续点击")
            return False

        连续确认 = 0
        for _ in range(2):
            try:
                try:
                    结果 = 识别(强制=True)
                except TypeError:
                    结果 = 识别()
            except Exception as 异常:
                self.上下文.置脚本状态(f"升级收尾主页复核失败：{异常}")
                return False
            if (
                getattr(结果, "页面", "") == "主世界主页"
                and getattr(结果, "世界", "") == "主世界"
                and float(getattr(结果, "可信度", 0.0) or 0.0) >= 0.70
            ):
                连续确认 += 1
                if 连续确认 >= 2:
                    self.上下文.置脚本状态("升级详情已关闭，连续确认回到主世界主页")
                    return True
            else:
                连续确认 = 0
            延时 = getattr(self.上下文, "脚本延时", None)
            if callable(延时):
                延时(250)

        self.上下文.置脚本状态("升级收尾未连续确认主世界，保留画面并停止后续操作")
        return False
