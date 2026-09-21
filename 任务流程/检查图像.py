from 任务流程.基础任务框架 import 基础任务, 任务上下文


class 检查图像任务(基础任务):
    """检查模拟器图像是否可以正常获取"""

    def 执行(self) -> bool:
        try:
            上下文 = self.上下文
            图像 = 上下文.op.获取屏幕图像cv(0, 0, 2000, 2000)
            高度, 宽度 = 图像.shape[:2]
            if 宽度 <= 0 or 高度 <= 0:
                raise RuntimeError("ADB 返回了空的模拟器截图。")

            上下文.置脚本状态(
                f"模拟器图像获取正常，已自动识别 {宽度}×{高度}；"
                "任务坐标会自动映射到当前显示尺寸"
            )
            return True

        except Exception as e:
            self.异常处理(e, 是否重启游戏=False)
            return False

