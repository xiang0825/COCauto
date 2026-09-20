"""兼容任务流程接口的 ADB 截图提供器。"""
from 核心.核心异常们 import 图像获取失败
from 模块.ADB设备操作类 import ADB错误, ADB设备操作类


class ADB屏幕:
    def __init__(self, 设备: ADB设备操作类):
        self.设备 = 设备
        self.是否已绑定 = True
        self._原始截图缓存 = None
        self._原始截图缓存时间 = 0.0
        # 一张 800×600 画面足以覆盖同一批点击护栏检测。限制为每秒
        # 最多约两帧，避免高频 screencap 把雷电 ADB transport 和提交额度
        # 堵死；战斗页面需要更快刷新时由上层识别节流单独控制。
        self._最短截图间隔秒 = 0.50

    def 获取屏幕图像cv(self, 左边=0, 顶边=0, 右边=2000, 底边=2000, *, 强制刷新=False):
        try:
            import cv2

            # 任务模板和检测区域使用 800×600 逻辑画布；设备截图可以是任意尺寸。
            参考宽度 = self.设备.参考宽度
            参考高度 = self.设备.参考高度
            if int(右边) >= 2000 or int(底边) >= 2000:
                左边, 顶边, 右边, 底边 = 0, 0, 参考宽度, 参考高度
            else:
                左边 = max(0, min(参考宽度, int(左边)))
                顶边 = max(0, min(参考高度, int(顶边)))
                右边 = max(左边 + 1, min(参考宽度, int(右边)))
                底边 = max(顶边 + 1, min(参考高度, int(底边)))

            设备宽度, 设备高度 = self.设备.取屏幕尺寸()
            import time
            当前时间 = time.monotonic()
            可复用缓存 = (
                not 强制刷新
                and self._原始截图缓存 is not None
                and 当前时间 - self._原始截图缓存时间 <= self._最短截图间隔秒
            )
            if 可复用缓存:
                原图 = self._原始截图缓存
            else:
                原图 = self.设备.获取屏幕图像cv(0, 0, 设备宽度, 设备高度)
                self._原始截图缓存 = 原图
                self._原始截图缓存时间 = 当前时间
            设备左边 = round(左边 * 设备宽度 / 参考宽度)
            设备顶边 = round(顶边 * 设备高度 / 参考高度)
            设备右边 = round(右边 * 设备宽度 / 参考宽度)
            设备底边 = round(底边 * 设备高度 / 参考高度)
            裁剪 = 原图[设备顶边:设备底边, 设备左边:设备右边]
            目标尺寸 = (右边 - 左边, 底边 - 顶边)
            if 裁剪.size == 0:
                raise ADB错误("ADB 截图缩放后区域为空。")
            if 裁剪.shape[1] != 目标尺寸[0] or 裁剪.shape[0] != 目标尺寸[1]:
                裁剪 = cv2.resize(裁剪, 目标尺寸, interpolation=cv2.INTER_AREA)
            return 裁剪
        except ADB错误 as 异常:
            raise 图像获取失败(f"ADB 截图失败：{异常}") from 异常

    def 安全清理(self):
        self.是否已绑定 = False
        self._原始截图缓存 = None

    def 绑定(self, 设备, *args, **kwargs):
        if not isinstance(设备, ADB设备操作类):
            raise RuntimeError("ADB 模式只能绑定到已选择的 ADB 设备。")
        self.设备 = 设备
        self.是否已绑定 = True
        return 1
