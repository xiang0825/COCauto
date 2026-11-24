"""模拟器 ADB 连接服务：扫描、连接、保存与测试截图。

这些操作都会执行 adb 子进程，耗时不定；界面必须在后台线程调用。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from 核心.ADB屏幕 import 检查分辨率比例告警
from 模块.ADB设备操作类 import ADB设备操作类, ADB错误

_LOGGER = logging.getLogger(__name__)

默认游戏包名 = "com.supercell.clashofclans"
_本机地址 = re.compile(r"(?:127\.0\.0\.1|localhost):(\d{1,5})")


@dataclass(frozen=True)
class 连接表单:
    adb路径: str
    自动检测路径: bool
    设备序列号: str
    已确认模拟器: bool


@dataclass(frozen=True)
class 扫描结果:
    adb路径: str
    设备: tuple  # tuple[ADB设备信息, ...]


class 设备服务:
    def __init__(self, 数据库):
        self.数据库 = 数据库

    def 读取表单(self, 机器人ID: str) -> 连接表单:
        设置 = self.数据库.获取机器人设置(机器人ID)
        return 连接表单(
            adb路径=设置.ADB路径 or "",
            自动检测路径=bool(getattr(设置, "ADB自动检测路径", True)),
            设备序列号=设置.ADB设备序列号 or "",
            已确认模拟器=bool(设置.ADB已确认模拟器),
        )

    @staticmethod
    def 检测ADB路径() -> str:
        return ADB设备操作类.解析ADB路径("", 自动检测=True)

    @staticmethod
    def 扫描(adb路径: str, 自动检测: bool, 已保存序列号: str = "") -> 扫描结果:
        已解析 = ADB设备操作类.解析ADB路径(adb路径, 自动检测=自动检测)
        匹配 = _本机地址.fullmatch(已保存序列号.strip())
        if 匹配 and 1 <= int(匹配.group(1)) <= 65535:
            # 独立 ADB server 不继承模拟器在默认 server 中的连接缓存；
            # 仅恢复已保存的 localhost serial，不自动挑选其他设备。
            try:
                ADB设备操作类.连接网络设备(已解析, 已保存序列号.strip(), 自动检测路径=False)
            except ADB错误:
                pass
        设备 = ADB设备操作类.扫描设备(已解析, 自动检测路径=False)
        return 扫描结果(已解析, tuple(设备))

    @staticmethod
    def 连接网络地址(adb路径: str, 自动检测: bool, 地址: str) -> tuple[str, str]:
        地址 = str(地址 or "").strip()
        if not 地址:
            raise ADB错误("请填写 host:port 地址")
        已解析 = ADB设备操作类.解析ADB路径(adb路径, 自动检测=自动检测)
        return 已解析, ADB设备操作类.连接网络设备(已解析, 地址, 自动检测路径=False)

    def _已确认设备(self, 机器人ID: str | None, 表单: 连接表单) -> ADB设备操作类:
        if not 表单.设备序列号.strip():
            raise ADB错误("请先扫描并选择设备。")
        if not 表单.已确认模拟器:
            raise ADB错误("请确认目标是 Android 模拟器，不是实体手机。")
        设备 = ADB设备操作类(
            表单.adb路径.strip(), 表单.设备序列号.strip(),
            自动检测路径=表单.自动检测路径,
        )
        # 多显示模拟器需要 CoC 包名才能选中真实游戏层，测试截图与正式运行一致。
        包名 = 默认游戏包名
        if 机器人ID:
            设置 = self.数据库.获取机器人设置(机器人ID)
            包名 = getattr(设置, "部落冲突包名", None) or 默认游戏包名
        设备.设置目标包名(包名)
        设备.确认在线()
        return 设备

    def 保存(self, 机器人ID: str, 表单: 连接表单) -> str:
        """保存连接配置，返回最终使用的 ADB 路径。"""
        if not 机器人ID:
            raise ValueError("请先选择机器人")
        adb路径 = 表单.adb路径.strip()
        if 表单.已确认模拟器:
            if not 表单.设备序列号.strip():
                raise ADB错误("请先扫描并选择设备。")
            adb路径 = ADB设备操作类.解析ADB路径(adb路径, 自动检测=表单.自动检测路径)
        设置 = self.数据库.获取机器人设置(机器人ID)
        设置.ADB路径 = adb路径
        设置.ADB自动检测路径 = 表单.自动检测路径
        设置.ADB设备序列号 = 表单.设备序列号.strip()
        设置.ADB已确认模拟器 = bool(表单.已确认模拟器 and 设置.ADB设备序列号)
        self.数据库.保存机器人设置(机器人ID, 设置)
        return adb路径

    def 测试截图(self, 机器人ID: str | None, 表单: 连接表单):
        """返回 BGR 图像（numpy 数组）。"""
        设备 = self._已确认设备(机器人ID, 表单)
        图像 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
        shape = getattr(图像, "shape", None)
        if isinstance(shape, (tuple, list)) and len(shape) >= 2:
            告警 = 检查分辨率比例告警(shape[1], shape[0])
            if 告警:
                _LOGGER.warning(告警)
        return 图像


# ---------------------------------------------------------------- 一键检测
def _游戏包名(数据库, 机器人ID: str | None) -> str:
    if not 机器人ID:
        return 默认游戏包名
    设置 = 数据库.获取机器人设置(机器人ID)
    return getattr(设置, "部落冲突包名", None) or 默认游戏包名


def 一键检测(数据库, 机器人ID: str | None, 进度=None):
    """MAA 式检测：返回 模块.模拟器探测.检测结果。"""
    from 模块.模拟器探测 import 检测

    已保存路径 = ""
    if 机器人ID:
        已保存路径 = 数据库.获取机器人设置(机器人ID).ADB路径 or ""
    return 检测(_游戏包名(数据库, 机器人ID), 已保存路径, 进度=进度)


def 使用检测结果(数据库, 机器人ID: str, adb路径: str, 序列号: str) -> None:
    """保存检测到的设备。检测只返回已排除实体手机的模拟器端口，因此直接视为已确认。"""
    设置 = 数据库.获取机器人设置(机器人ID)
    设置.ADB路径 = adb路径
    设置.ADB设备序列号 = 序列号
    设置.ADB已确认模拟器 = True
    数据库.保存机器人设置(机器人ID, 设置)


def 设置自动检测(数据库, 机器人ID: str, 开启: bool) -> None:
    设置 = 数据库.获取机器人设置(机器人ID)
    设置.ADB自动检测路径 = bool(开启)
    数据库.保存机器人设置(机器人ID, 设置)


def 重启ADB(adb路径: str) -> str:
    from 模块.模拟器探测 import 重启ADB服务

    if not adb路径:
        adb路径 = ADB设备操作类.解析ADB路径("", 自动检测=True)
    return 重启ADB服务(adb路径)
