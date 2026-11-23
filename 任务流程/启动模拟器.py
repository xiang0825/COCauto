from 任务流程.基础任务框架 import 基础任务, 任务上下文


class 模拟器等待超时错误(Exception):
    pass


class 启动模拟器任务(基础任务):
    """MAA “开始唤醒”的第一步：确认设备在线，游戏没开就通过 ADB 启动它。

    - 游戏已在前台：直接复用，不重启、不关闭；
    - 游戏没开且允许自动启动：``am start`` 启动并等待进入前台（冷启动最多 60 秒）；
    - 游戏没安装或不允许自动启动：安全停止并说明原因。

    整个过程只用 ADB，不启动或关闭模拟器本身。
    """

    前台等待秒 = 60

    def 执行(self) -> bool:
        try:
            上下文 = self.上下文
            设置 = 上下文.数据库.获取机器人设置(上下文.机器人标志)
            包名 = 设置.部落冲突包名
            设备 = 上下文.设备
            设备.确认在线()
            if not 设备.是否已启动():
                raise 模拟器等待超时错误("ADB 已连接，但 Android 系统尚未完成启动；请在模拟器中等待启动完成。")

            获取前台包名 = getattr(设备, "获取当前前台包名", None)
            当前包名 = 获取前台包名() if callable(获取前台包名) else ""
            if 当前包名 == 包名:
                上下文.置脚本状态("游戏已在运行，直接接管")
            else:
                if not getattr(设置, "自动启动游戏", True):
                    上下文.置脚本状态(
                        "[警告] 游戏未在前台，且已关闭“自动启动游戏”；请先手动打开部落冲突", 30,
                    )
                    return False
                if not self._已安装(设备, 包名):
                    上下文.置脚本状态(f"[错误] 模拟器中没有安装部落冲突（{包名}）", 30)
                    return False
                上下文.置脚本状态("游戏未运行，正在启动部落冲突…", 30)
                设备.打开应用(包名)
                if not self._等待前台(上下文, 获取前台包名, 包名):
                    return False
                上下文.置脚本状态("部落冲突已启动，等待进入主界面", 60)

            获取目标显示ID = getattr(设备, "获取目标显示ID", None)
            if callable(获取目标显示ID):
                目标显示ID = 获取目标显示ID()
                if 目标显示ID:
                    上下文.置脚本状态(f"已绑定游戏显示层 display {目标显示ID}")
            return True

        except Exception as e:
            self.异常处理(e, 是否重启游戏=False)
            return False

    @staticmethod
    def _已安装(设备, 包名: str) -> bool:
        try:
            输出 = 设备.执行(["shell", "pm", "list", "packages", 包名], timeout=10)
        except Exception:
            # 查询失败时不阻止启动，交给 am start 的结果判断。
            return True
        if isinstance(输出, bytes):
            输出 = 输出.decode("utf-8", errors="replace")
        return f"package:{包名}" in str(输出)

    def _等待前台(self, 上下文, 获取前台包名, 包名: str) -> bool:
        if not callable(获取前台包名):
            return True
        当前包名 = ""
        for 秒 in range(self.前台等待秒):
            当前包名 = 获取前台包名()
            if 当前包名 == 包名:
                return True
            if 秒 and 秒 % 10 == 0:
                上下文.置脚本状态(f"等待游戏进入前台…已等待 {秒} 秒", 30)
            上下文.脚本延时(1000)
        # 不发送返回键，也不 force-stop；保留现场交给用户确认。
        上下文.置脚本状态(
            f"[错误] 启动部落冲突后 {self.前台等待秒} 秒仍未进入前台（当前={当前包名 or '未知'}），已停止", 30,
        )
        return False
