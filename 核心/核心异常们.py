from 核心.异常 import ADB异常


class 图像获取失败(ADB异常):
    """截图失败；属于安全锁异常，禁止自动恢复。"""

    def __init__(self, 错误信息):
        super().__init__(错误信息)
        self.错误信息 = 错误信息

    def __str__(self):
        return f"发生了：{self.错误信息}"
