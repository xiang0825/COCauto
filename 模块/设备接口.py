"""游戏设备抽象层：任务流程只依赖这里列出的能力。

现有实现：
- ``模块.ADB设备操作类.ADB设备操作类``：通用 ADB + MuMu 专用分支（Windows 现网路径，
  MuMu 渲染器高速截图、多显示层、Xiaomi Touchscreen 双指缩放）。
- ``模块.BlueStacks设备.BlueStacks设备``：纯 ADB 实现（BlueStacks Air / macOS），
  不走任何 MuMu 探测与 IPC。

``选择设备类``/``创建游戏设备`` 按设置“模拟器类型”（macOS 上可用环境变量
``COC_EMULATOR_TYPE`` 覆盖）选择实现。Windows 上默认 auto → 现有 ``ADB设备操作类``，
行为不变；macOS 上 auto → ``BlueStacks设备``。
"""
from __future__ import annotations

from typing import Any, Iterable, Protocol, runtime_checkable

模拟器_自动 = "auto"
模拟器_MUMU = "mumu"
模拟器_蓝叠 = "bluestacks"
支持的模拟器类型 = (模拟器_自动, 模拟器_MUMU, 模拟器_蓝叠)


@runtime_checkable
class 游戏设备(Protocol):
    """截图、点击、拖动、缩放、启动游戏、检测前台。坐标均为 800×600 参考坐标。"""

    设备序列号: str

    def 设置目标包名(self, 包名: str) -> None: ...

    def 确认在线(self) -> Any: ...

    def 获取屏幕图像cv(self, 左边: int = 0, 顶边: int = 0, 右边: int = 2000, 底边: int = 2000): ...

    def 取屏幕尺寸(self) -> tuple[int, int]: ...

    def 触控(self, x: int, y: int) -> bool: ...

    def 连续触控(self, 位置列表: Iterable[tuple[int, int]], 间隔毫秒: int = 0) -> bool: ...

    def 长按触控(self, x: int, y: int, 时长毫秒: int = 220) -> bool: ...

    def 滑动(self, 起点: tuple[int, int], 终点: tuple[int, int], 时长毫秒: int = 350) -> bool: ...

    def 按键(self, 按键码: int | str) -> bool: ...

    def 游戏内拉远视距(self, 次数: int = 5, 间隔毫秒: int = 180) -> bool: ...

    def 打开应用(self, 包名: str) -> None: ...

    def 获取当前前台包名(self) -> str: ...


def 规范化模拟器类型(类型: object) -> str:
    文本 = str(类型 or "").strip().lower()
    别名 = {
        "": 模拟器_自动, "auto": 模拟器_自动, "自动": 模拟器_自动,
        "mumu": 模拟器_MUMU, "网易mumu": 模拟器_MUMU,
        "bluestacks": 模拟器_蓝叠, "bluestacks air": 模拟器_蓝叠, "蓝叠": 模拟器_蓝叠,
    }
    if 文本 in 别名:
        return 别名[文本]
    raise ValueError(f"不支持的模拟器类型：{类型!r}（可选：{', '.join(支持的模拟器类型)}）")


def 解析生效模拟器类型(模拟器类型: object = 模拟器_自动, 平台名称: str | None = None) -> str:
    """设置值 + 环境变量 ``COC_EMULATOR_TYPE`` → 实际使用的实现类型。

    - 环境变量仅在 macOS 生效且优先（便于 Mac 调试；Windows 忽略）；非法值回退为 auto，不让启动崩溃；
    - auto 在 Windows 上保持原行为（ADB设备操作类，MuMu 自动走专用通道），
      在 macOS 上等同 bluestacks（Mac 没有 MuMu）。
    """
    import os
    import sys

    平台 = sys.platform if 平台名称 is None else str(平台名称)
    原始 = 模拟器类型
    if 平台 == "darwin":
        # 环境变量只在 macOS 生效：Windows 现网残留的 COC_EMULATOR_TYPE 不能把 MuMu 误切成纯 ADB。
        原始 = os.environ.get("COC_EMULATOR_TYPE", "").strip() or 模拟器类型
    try:
        类型 = 规范化模拟器类型(原始)
    except ValueError:
        类型 = 模拟器_自动
    if 类型 == 模拟器_自动:
        return 模拟器_蓝叠 if 平台 == "darwin" else 模拟器_MUMU
    return 类型


def 选择设备类(模拟器类型: object = 模拟器_自动, 默认类: type | None = None,
               平台名称: str | None = None) -> type:
    """返回设备实现类；``默认类`` 让调用方传入自己模块里的 ADB设备操作类（兼容测试 patch）。"""
    if 解析生效模拟器类型(模拟器类型, 平台名称) == 模拟器_蓝叠:
        from 模块.BlueStacks设备 import BlueStacks设备
        return BlueStacks设备
    if 默认类 is not None:
        return 默认类
    from 模块.ADB设备操作类 import ADB设备操作类
    return ADB设备操作类


def 创建游戏设备(模拟器类型: object = 模拟器_自动, *参数, **关键字) -> 游戏设备:
    """按模拟器类型创建设备；Windows 上 ``auto``/``mumu`` 保持现有 ADB设备操作类 行为。"""
    return 选择设备类(模拟器类型)(*参数, **关键字)
