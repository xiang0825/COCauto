from 任务流程.基础任务框架 import 基础任务, 任务上下文

class 模拟器等待超时错误(Exception):
    pass


class 启动模拟器任务(基础任务):
    """验证已连接的 Android 设备并在需要时将游戏切到前台。"""

    def 执行(self) -> bool:
        try:
            上下文 = self.上下文
            包名 = 上下文.数据库.获取机器人设置(上下文.机器人标志).部落冲突包名
            模拟器 = 上下文.雷电模拟器
            模拟器.确认在线()
            if not 模拟器.是否已启动():
                raise 模拟器等待超时错误("ADB 已连接，但 Android 系统尚未完成启动；请在模拟器中等待启动完成。")
            上下文.置脚本状态("ADB 模拟器已连接，检查游戏前台状态")
            模拟器.打开应用(包名)
            return True

        except Exception as e:
            self.异常处理(e, 是否重启游戏=False)
            return False


