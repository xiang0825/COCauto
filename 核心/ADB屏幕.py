"""兼容任务流程接口的 ADB 截图提供器。"""
from 核心.核心异常们 import 图像获取失败
from 模块.ADB设备操作类 import ADB错误, ADB设备操作类


class ADB屏幕:
    def __init__(self, 设备: ADB设备操作类):
        self.设备 = 设备
        self.是否已绑定 = True

    def 获取屏幕图像cv(self, 左边=0, 顶边=0, 右边=2000, 底边=2000):
        try:
            return self.设备.获取屏幕图像cv(左边, 顶边, 右边, 底边)
        except ADB错误 as 异常:
            raise 图像获取失败(f"ADB 截图失败：{异常}") from 异常

    def 安全清理(self):
        self.是否已绑定 = False

    def 绑定(self, 设备, *args, **kwargs):
        if not isinstance(设备, ADB设备操作类):
            raise RuntimeError("ADB 模式只能绑定到已选择的 ADB 设备。")
        self.设备 = 设备
        self.是否已绑定 = True
        return 1
