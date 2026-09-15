from 任务流程.基础任务框架 import 基础任务, 任务上下文
from datetime import datetime, timedelta

from 任务流程.战宠升级.完成宠物升级 import 完成宠物升级任务
from 任务流程.战宠升级.寻找战宠小屋 import 寻找战宠小屋任务
from 任务流程.战宠升级.打开要升级的宠物 import 打开要升级的宠物任务


class 战宠升级任务(基础任务):

    def __init__(self, 上下文: '任务上下文'):
        super().__init__(上下文)

    def 执行(self) -> bool:
        欲升级战宠 = self.上下文.设置.欲升级的战宠

        if not 欲升级战宠:
            self.上下文.置脚本状态("战宠升级：未配置要升级的战宠，跳过")
            return False

        # 检查冷却时间
        完整状态 = self.数据库.获取最新完整状态(self.机器人标志).状态数据
        上次记录 = 完整状态.get("战宠升级失败记录")
        if 上次记录:
            记录时间 = datetime.fromtimestamp(上次记录.get("时间", 0))
            冷却时间 = timedelta(hours=self.上下文.设置.战宠升级检查间隔)
            if datetime.now() - 记录时间 < 冷却时间:
                剩余分钟 = int((冷却时间 - (datetime.now() - 记录时间)).total_seconds() / 60)
                self.上下文.置脚本状态(f"战宠升级：冷却中，{剩余分钟}分钟后再试")
                return False

        self.上下文.置脚本状态(f"战宠升级：开始升级 {欲升级战宠}")

        if not 寻找战宠小屋任务(self.上下文).执行():
            self.记录状态("未找到战宠小屋")
            return False

        if not 打开要升级的宠物任务(self.上下文, 欲升级战宠).执行():
            self.记录状态("无法打开宠物界面")
            return False

        if not 完成宠物升级任务(self.上下文).执行():
            self.记录状态("升级操作未完成")
            return False

        # 成功后清除失败记录
        self.数据库.更新状态(self.机器人标志, "战宠升级失败记录", None)
        self.上下文.置脚本状态(f"战宠升级：{欲升级战宠} 升级完成")
        return True

    def 记录状态(self, 原因: str):
        """记录状态到数据库，用于冷却判断"""
        状态记录 = {
            "时间": datetime.now().timestamp(),
            "原因": 原因
        }
        self.数据库.更新状态(self.机器人标志, "战宠升级失败记录", 状态记录)
