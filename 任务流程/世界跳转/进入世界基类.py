import random
import time
from dataclasses import dataclass

from 任务流程.基础任务框架 import 基础任务, 任务上下文
from 工具包.工具函数 import 生成贝塞尔轨迹
from 模块.检测.模板匹配器 import 模板匹配引擎
from 任务流程.世界跳转.世界识别器 import 世界识别器

@dataclass
class 滑动配置:
    起点: tuple[int, int]
    终点: tuple[int, int]

class 进入世界任务基类(基础任务):
    def __init__(self, 上下文: 任务上下文, 判断图标路径: str, 船模板路径: str, 状态文本: str,滑动参数: 滑动配置):
        super().__init__(上下文)
        self.判断图标路径 = 判断图标路径
        self.船模板路径 = 船模板路径
        self.状态文本 = 状态文本
        self.滑动配置 = 滑动参数
        self.世界识别 = 世界识别器(self.模板识别)
        self._上次世界识别日志 = None
        self._上次世界识别日志时间 = 0.0

    def 执行(self) -> bool:
        try:
            上下文 = self.上下文
            if self.是否在目标世界():
                上下文.置脚本状态(f"已经在{self.状态文本}")
                return True
            else:
                上下文.置脚本状态(f"开始尝试进入{self.状态文本}")

            按钮区域 = (0, 0, 800, 600)
            超时时间 = 30
            开始时间 = time.time()
            上次超时恢复时间 = 0.0
            超时恢复次数 = 0

            while time.time() - 开始时间 < 超时时间:
                屏幕图像 = 上下文.op.获取屏幕图像cv(*按钮区域)
                是否匹配, (x, y), _ = self.模板识别.执行匹配(屏幕图像, self.船模板路径, 相似度阈值=0.8)

                if 是否匹配:
                    上下文.点击(x, y)
                    上下文.脚本延时(500)

                if self.是否在目标世界():
                    上下文.置脚本状态(f"成功进入{self.状态文本}")
                    return True

                self.滑动屏幕(上下文, self.滑动配置.起点, self.滑动配置.终点)
                上下文.脚本延时(1000)

                if (
                    time.time() - 开始时间 > 3
                    and 超时恢复次数 < 3
                    and time.time() - 上次超时恢复时间 >= 3
                ):
                    超时恢复次数 += 1
                    上次超时恢复时间 = time.time()
                    页面名称 = "主世界主页" if self.状态文本 == "主世界" else self.状态文本
                    上下文.置脚本状态(
                        f"切换世界超过三秒,尝试第{超时恢复次数}次ESC关闭误触页面并回到{页面名称}"
                    )
                    # 一次只关闭最上层误触页面；若仍未切换成功，下一轮
                    # 重新识别后再决定是否需要一次 ESC。连续 BACK/F5
                    # 可能把游戏退到 Android 启动器，因此这里不再发送。
                    安全返回键 = getattr(上下文, "安全返回键", None)
                    if callable(安全返回键):
                        if not 安全返回键("世界切换超时恢复"):
                            return False
                    else:
                        上下文.键盘.按字符按压("esc")
                    上下文.脚本延时(150)

            raise RuntimeError(f"操作超时：未找到{self.状态文本}入口")
        except Exception as e:
            self.异常处理(e)
            return False


    def 是否在目标世界(self) -> bool:
        """用资源栏和世界入口共同确认当前世界。

        旧实现把一个 15~19 像素的小图标放在整屏搜索，地图动画很容易
        误命中。现在世界识别器只搜索右上角资源栏和左下角入口，并记录
        主/夜两套分数；分数接近时返回 False，让执行流程先恢复页面，
        不在未知页面继续点击。
        """
        识别结果 = self.识别当前世界()
        return 识别结果.当前世界 == self.状态文本

    def 识别当前世界(self):
        """返回当前截图的完整世界识别结果，供任务和日志复用。"""
        屏幕图像 = self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)
        识别结果 = self.世界识别.识别(屏幕图像)
        self._最近世界识别结果 = 识别结果
        self._记录世界识别结果(识别结果)
        return 识别结果

    def _记录世界识别结果(self, 识别结果):
        """节流记录识别依据，便于从运行日志定位误判。"""
        摘要 = 识别结果.摘要()
        现在 = time.monotonic()
        日志键 = (识别结果.当前世界, 摘要)
        if (
            日志键 != self._上次世界识别日志
            or 现在 - self._上次世界识别日志时间 >= 3.0
        ):
            self.上下文.置脚本状态(f"世界识别：{摘要}")
            self._上次世界识别日志 = 日志键
            self._上次世界识别日志时间 = 现在

    def 滑动屏幕(self, 上下文, 起点坐标, 终点坐标):
        """使用贝塞尔曲线模拟人类滑动操作"""
        起点x, 起点y = 起点坐标
        终点x, 终点y = 终点坐标

        # 随机偏移增强人类行为模拟
        起点x += random.randint(-5, 5)
        起点y += random.randint(-5, 5)
        终点x += random.randint(-5, 5)
        终点y += random.randint(-5, 5)

        # 控制点随机生成在起点和终点附近
        控制点1 = (
            起点x + (终点x - 起点x) * 0.3 + random.randint(-30, 30),
            起点y + (终点y - 起点y) * 0.3 + random.randint(-30, 30),
        )
        控制点2 = (
            起点x + (终点x - 起点x) * 0.6 + random.randint(-30, 30),
            起点y + (终点y - 起点y) * 0.6 + random.randint(-30, 30),
        )

        路径点 = 生成贝塞尔轨迹((起点x, 起点y), 控制点1, 控制点2, (终点x, 终点y), 步数=random.randint(25, 40))

        上下文.鼠标.移动到(路径点[0][0], 路径点[0][1])
        上下文.鼠标.左键按下()

        for 当前点 in 路径点[1:]:
            上下文.鼠标.移动到(当前点[0], 当前点[1])
            上下文.脚本延时(random.randint(5, 15))  # 模拟人类微小不规律移动

        上下文.鼠标.左键抬起()
        上下文.脚本延时(random.randint(500, 1000))

