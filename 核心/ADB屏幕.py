"""兼容任务流程接口的 ADB 截图提供器。"""
import logging

from 核心.核心异常们 import 图像获取失败
from 模块.ADB设备操作类 import ADB错误, ADB设备操作类

_LOGGER = logging.getLogger(__name__)


def 检查分辨率比例告警(宽度: int, 高度: int, 允许误差比例: float = 0.05) -> str | None:
    """返回分辨率提示；已验证配置（任意 16:9、800×600 参考尺寸）返回 None。

    坐标与模板主要在 16:9 拉伸画布上校准，任意尺寸的 16:9 与 1280×720
    等价。其它长宽比会启用 HUD 锚点换算与模板多尺度回退（实验性）。
    ``允许误差比例`` 仅为兼容旧调用签名保留。
    """
    from 模块.画面几何 import 分辨率提示

    return 分辨率提示(宽度, 高度)


class ADB屏幕:
    def __init__(self, 设备: ADB设备操作类, 日志回调=None):
        self.设备 = 设备
        self.是否已绑定 = True
        self._原始截图缓存 = None
        self._原始截图缓存时间 = 0.0
        self._日志回调 = 日志回调
        self._已告警分辨率: set[tuple[int, int]] = set()
        # 一张逻辑画面足以覆盖同一批点击护栏检测。限制为每秒
        # 最多约两帧，避免高频 screencap 把雷电 ADB transport 和提交额度
        # 堵死；低频场景（待机/战斗观察）可由上层动态下调采样频率节能。
        self._默认最短截图间隔秒 = 0.50
        self._最短截图间隔秒 = self._默认最短截图间隔秒
        self._当前节流场景 = "活跃"
        if 日志回调 is not None:
            设置回调 = getattr(设备, "设置日志回调", None)
            if callable(设置回调):
                设置回调(日志回调)

    def 设置截图节流场景(self, 场景: str, *, 间隔秒: float | None = None) -> float:
        """按运行场景动态调整最小截图间隔，默认保持 0.50 秒活跃采样。"""
        from 模块.运行节流与复盘 import 解析截图节流配置

        规范场景, 目标间隔, _ = 解析截图节流配置(场景, 间隔秒=间隔秒)
        self._当前节流场景 = 规范场景
        self._最短截图间隔秒 = 目标间隔
        return self._最短截图间隔秒

    def 获取最短截图间隔秒(self) -> float:
        return float(getattr(self, "_最短截图间隔秒", 0.50))

    def 获取当前节流场景(self) -> str:
        return str(getattr(self, "_当前节流场景", "活跃"))

    def 测速选择截图后端(self, *, 采样帧数: int = 2, 强制重测: bool = False):
        """转发底层设备的截图后端自动测速入口。"""
        测速方法 = getattr(self.设备, "测速选择截图后端", None)
        if callable(测速方法):
            return 测速方法(采样帧数=采样帧数, 强制重测=强制重测)
        return None

    def 检查主机内存预算(self, 强制刷新: bool = True) -> tuple[bool, str]:
        """将恢复等待所需的宿主机内存检查转发给实际 ADB 设备。"""
        return self.设备.检查主机内存预算(强制刷新=强制刷新)

    def _按需记录分辨率告警(self, 宽度: int, 高度: int) -> str | None:
        """每个未验证分辨率只提示一次，避免高频截图刷屏。"""
        告警文本 = 检查分辨率比例告警(宽度, 高度)
        if not 告警文本:
            return None
        键 = (int(宽度), int(高度))
        已记录 = getattr(self, "_已告警分辨率", None)
        if 已记录 is None:
            已记录 = set()
            self._已告警分辨率 = 已记录
        if 键 not in 已记录:
            已记录.add(键)
            _LOGGER.warning(告警文本)
            日志回调 = getattr(self, "_日志回调", None)
            if callable(日志回调):
                try:
                    日志回调(告警文本)
                except Exception:
                    pass
        return 告警文本

    def 获取屏幕图像cv(self, 左边=0, 顶边=0, 右边=2000, 底边=2000, *, 强制刷新=False):
        try:
            import cv2

            # 任务模板和检测区域使用逻辑画布；设备截图可以是任意尺寸。
            参考宽度 = self.设备.参考宽度
            参考高度 = self.设备.参考高度
            if int(右边) >= 2000 or int(底边) >= 2000:
                左边, 顶边, 右边, 底边 = 0, 0, 参考宽度, 参考高度
            else:
                左边 = max(0, min(参考宽度, int(左边)))
                顶边 = max(0, min(参考高度, int(顶边)))
                右边 = max(左边 + 1, min(参考宽度, int(右边)))
                底边 = max(顶边 + 1, min(参考高度, int(底边)))

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
                # 直接读取完整截图，以返回图像的真实宽高为准；不要依赖
                # wm size，因为不同模拟器/旋转显示可能报告另一套逻辑尺寸。
                原图 = self.设备.获取屏幕图像cv(0, 0, 2000, 2000)
                self._原始截图缓存 = 原图
                self._原始截图缓存时间 = 当前时间
            设备高度, 设备宽度 = 原图.shape[:2]
            from 模块.画面几何 import 记录设备尺寸

            记录设备尺寸(设备宽度, 设备高度)
            self._按需记录分辨率告警(设备宽度, 设备高度)
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
            else:
                # 防止调用方原地画框/修改返回值时污染 _原始截图缓存。
                裁剪 = 裁剪.copy()
            return 裁剪
        except ADB错误 as 异常:
            raise 图像获取失败(f"ADB 截图失败：{异常}") from 异常

    def 安全清理(self):
        self.是否已绑定 = False
        self._原始截图缓存 = None
        关闭 = getattr(self.设备, "关闭高速截图", None)
        if callable(关闭):
            关闭()

    def 绑定(self, 设备, *args, **kwargs):
        if not isinstance(设备, ADB设备操作类):
            raise RuntimeError("ADB 模式只能绑定到已选择的 ADB 设备。")
        self.设备 = 设备
        self.是否已绑定 = True
        self._原始截图缓存 = None
        self._原始截图缓存时间 = 0.0
        if self._日志回调 is not None:
            设置回调 = getattr(设备, "设置日志回调", None)
            if callable(设置回调):
                设置回调(self._日志回调)
        return 1
