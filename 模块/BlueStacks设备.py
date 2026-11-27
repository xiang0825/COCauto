"""BlueStacks（含 macOS 上的 BlueStacks Air）纯 ADB 设备实现。

与 ``ADB设备操作类`` 的区别：
- 永远不当作 MuMu：不跑 ``dumpsys display`` 的 mumuscreen 探测、不加载 MuMu
  渲染器截图库（macOS 上也不存在），截图只在 ADB raw / raw|gzip / PNG 中测速择优；
- 双指缩放（拉远视距）改为：``getevent -lp`` 找到支持 multi-touch protocol B 的
  触摸设备 → ``sendevent`` 注入双指捏合；找不到或无写权限时明确报错，绝不发送
  猜测输入；
- 点击/长按/滑动/启动游戏/前台检测直接复用父类的通用 ADB 路径（``input tap/swipe``、
  ``am start``、``dumpsys activity top-resumed``）。

BlueStacks Air 在“设置 → 高级 → Android 调试桥(ADB)”开启后，会显示
``127.0.0.1:<端口>``（通常 5555）；用 ``adb connect 127.0.0.1:<端口>`` 即可。
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from 模块.ADB设备操作类 import ADB设备信息, ADB设备操作类, ADB错误

BlueStacks默认地址 = "127.0.0.1:5555"


@dataclass(frozen=True)
class 触摸设备信息:
    路径: str
    名称: str
    最大x: int
    最大y: int
    支持多点槽位: bool
    直接触摸: bool


def 解析触摸设备列表(getevent输出: str) -> list[触摸设备信息]:
    """解析 ``getevent -lp`` 输出，返回含 ABS_MT_POSITION_X/Y 的设备（好的排前面）。"""
    文本 = str(getevent输出 or "")
    设备块 = re.split(r"(?m)^add device \d+:\s*", 文本)
    结果: list[触摸设备信息] = []
    for 块 in 设备块[1:]:
        行列表 = 块.splitlines()
        if not 行列表:
            continue
        路径 = 行列表[0].strip()
        if not re.fullmatch(r"/dev/input/event\d+", 路径):
            continue
        名称匹配 = re.search(r'name:\s*"([^"]*)"', 块)
        x匹配 = re.search(r"ABS_MT_POSITION_X\s*:.*?\bmax\s+(\d+)", 块)
        y匹配 = re.search(r"ABS_MT_POSITION_Y\s*:.*?\bmax\s+(\d+)", 块)
        if not x匹配 or not y匹配:
            continue
        最大x, 最大y = int(x匹配.group(1)), int(y匹配.group(1))
        if 最大x <= 0 or 最大y <= 0:
            continue
        结果.append(触摸设备信息(
            路径=路径,
            名称=名称匹配.group(1) if 名称匹配 else "",
            最大x=最大x,
            最大y=最大y,
            支持多点槽位="ABS_MT_SLOT" in 块,
            直接触摸="INPUT_PROP_DIRECT" in 块,
        ))
    结果.sort(key=lambda 项: (
        not 项.支持多点槽位,
        not 项.直接触摸,
        "touch" not in 项.名称.lower(),
        项.路径,
    ))
    return 结果


def 原始触摸坐标(x: float, y: float, 屏幕宽度: int, 屏幕高度: int,
                 最大x: int, 最大y: int, 旋转: int = 0) -> tuple[int, int]:
    """屏幕坐标 → 触摸设备原始坐标；旋转为触摸轴相对显示的顺时针角度（0/90/180/270）。"""
    宽 = max(1, int(屏幕宽度))
    高 = max(1, int(屏幕高度))
    旋转 = int(旋转) % 360
    if 旋转 == 90:
        u, v = y / 高, 1 - x / 宽
    elif 旋转 == 180:
        u, v = 1 - x / 宽, 1 - y / 高
    elif 旋转 == 270:
        u, v = 1 - y / 高, x / 宽
    else:
        u, v = x / 宽, y / 高
    原始x = round(u * 最大x)
    原始y = round(v * 最大y)
    return max(0, min(最大x, 原始x)), max(0, min(最大y, 原始y))


def 生成双指捏合脚本(事件设备: str, 最大x: int, 最大y: int, 屏幕宽度: int, 屏幕高度: int,
                     次数: int = 1, 旋转: int = 0, 步数: int = 16) -> str:
    """生成 multi-touch protocol B 的双指向内捏合（CoC 中即“拉远视距”）。"""
    if not re.fullmatch(r"/dev/input/event\d+", str(事件设备)):
        raise ValueError(f"非法触摸设备路径：{事件设备!r}")
    命令: list[str] = []

    def 事件(类型: int, 代码: int, 值: int) -> None:
        命令.append(f"sendevent {事件设备} {类型} {代码} {值}")

    def 同步() -> None:
        命令.append(f"sendevent {事件设备} 0 0 0")

    def 转换(x: float, y: float) -> tuple[int, int]:
        return 原始触摸坐标(x, y, 屏幕宽度, 屏幕高度, 最大x, 最大y, 旋转)

    中心x, 中心y = 屏幕宽度 / 2, 屏幕高度 / 2
    起点1 = 转换(中心x - 屏幕宽度 * 0.15, 中心y - 屏幕高度 * 0.15)
    起点2 = 转换(中心x + 屏幕宽度 * 0.15, 中心y + 屏幕高度 * 0.15)
    终点1 = 转换(中心x - 屏幕宽度 * 0.055, 中心y - 屏幕高度 * 0.055)
    终点2 = 转换(中心x + 屏幕宽度 * 0.055, 中心y + 屏幕高度 * 0.055)
    步数 = max(4, min(40, int(步数)))
    手势次数 = max(1, min(3, int(次数)))
    for 序号 in range(手势次数):
        追踪1, 追踪2 = 200 + 序号 * 2, 201 + 序号 * 2
        事件(3, 47, 0)  # ABS_MT_SLOT 0
        事件(3, 57, 追踪1)  # ABS_MT_TRACKING_ID
        事件(3, 53, 起点1[0])  # ABS_MT_POSITION_X
        事件(3, 54, 起点1[1])  # ABS_MT_POSITION_Y
        事件(3, 47, 1)
        事件(3, 57, 追踪2)
        事件(3, 53, 起点2[0])
        事件(3, 54, 起点2[1])
        事件(1, 330, 1)  # BTN_TOUCH down
        同步()
        for 步 in range(1, 步数 + 1):
            比例 = 步 / 步数
            点1 = (round(起点1[0] + (终点1[0] - 起点1[0]) * 比例), round(起点1[1] + (终点1[1] - 起点1[1]) * 比例))
            点2 = (round(起点2[0] + (终点2[0] - 起点2[0]) * 比例), round(起点2[1] + (终点2[1] - 起点2[1]) * 比例))
            事件(3, 47, 0)
            事件(3, 53, 点1[0])
            事件(3, 54, 点1[1])
            事件(3, 47, 1)
            事件(3, 53, 点2[0])
            事件(3, 54, 点2[1])
            同步()
            命令.append("sleep 0.02")
        事件(3, 47, 0)
        事件(3, 57, -1)
        事件(3, 47, 1)
        事件(3, 57, -1)
        事件(1, 330, 0)  # BTN_TOUCH up
        同步()
        if 序号 + 1 < 手势次数:
            命令.append("sleep 0.08")
    return "; ".join(命令)


_本机序列号 = re.compile(r"(?:127\.0\.0\.1|localhost):\d{1,5}|emulator-\d+", re.IGNORECASE)
本机蓝叠标记 = "bluestacks-local"


def 标注本机蓝叠(设备: ADB设备信息) -> ADB设备信息:
    """BlueStacks 会把设备描述伪装成真实手机型号（如 SM-S908E / OnePlus）。

    只有在用户明确选择 BlueStacks（或 macOS 默认）时调用：本机回环地址/
    emulator-* 不可能是 USB 实体手机，给描述加上模拟器标记以通过实体机拦截；
    局域网 IP、USB 序列号一律保持原判断，绝不放宽。
    """
    if not 设备.疑似实体设备 or not _本机序列号.fullmatch(设备.序列号.strip()):
        return 设备
    return ADB设备信息(设备.序列号, 设备.状态, f"{设备.描述} {本机蓝叠标记}".strip())


def _读取环境旋转() -> int:
    值 = os.environ.get("COC_BLUESTACKS_TOUCH_ROTATION", "").strip()
    try:
        旋转 = int(值) if 值 else 0
    except ValueError:
        return 0
    return 旋转 if 旋转 in (0, 90, 180, 270) else 0


class BlueStacks设备(ADB设备操作类):
    """BlueStacks / BlueStacks Air 的纯 ADB 实现。"""

    模拟器类型 = "bluestacks"
    触摸设备缓存秒数 = 60.0

    def __init__(self, *参数, 触摸旋转: int | None = None, **关键字):
        super().__init__(*参数, **关键字)
        self.触摸旋转 = _读取环境旋转() if 触摸旋转 is None else int(触摸旋转) % 360
        self._蓝叠触摸设备: 触摸设备信息 | None = None
        self._蓝叠触摸设备时间 = 0.0
        self._蓝叠触摸可写: bool | None = None

    @classmethod
    def 扫描设备(cls, *参数, **关键字) -> list[ADB设备信息]:
        return [标注本机蓝叠(项) for 项 in super().扫描设备(*参数, **关键字)]

    # ---------------------------------------------------------- 不走 MuMu
    def _是MuMu连接(self) -> bool:
        return False

    def _获取高速截图器(self):
        return None

    # ---------------------------------------------------------- 双指缩放
    def _文本(self, 输出) -> str:
        if isinstance(输出, bytes):
            return 输出.decode("utf-8", errors="replace")
        return str(输出 or "")

    def 获取触摸设备(self, 强制刷新: bool = False) -> 触摸设备信息 | None:
        现在 = time.monotonic()
        if (
            not 强制刷新
            and self._蓝叠触摸设备 is not None
            and 现在 - self._蓝叠触摸设备时间 < self.触摸设备缓存秒数
        ):
            return self._蓝叠触摸设备
        输出 = self._文本(self.执行(["shell", "getevent", "-lp"], timeout=10))
        候选 = [项 for 项 in 解析触摸设备列表(输出) if 项.支持多点槽位]
        设备 = 候选[0] if 候选 else None
        if 设备 is None or 设备 != self._蓝叠触摸设备:
            self._蓝叠触摸可写 = None
        self._蓝叠触摸设备 = 设备
        self._蓝叠触摸设备时间 = 现在
        return 设备

    def _确认触摸设备可写(self, 设备: 触摸设备信息) -> None:
        if self._蓝叠触摸可写:
            return
        # 只发一个空 SYN_REPORT 探测写权限，不构成任何触摸。
        输出 = self._文本(self.执行(
            ["shell", "sh", "-c", f"sendevent {设备.路径} 0 0 0 && echo COC_SENDEVENT_OK"],
            timeout=8,
        ))
        self._蓝叠触摸可写 = "COC_SENDEVENT_OK" in 输出
        if not self._蓝叠触摸可写:
            raise ADB错误(
                f"BlueStacks 触摸设备 {设备.路径} 不可写（sendevent 失败），无法双指缩放："
                f"{输出.strip()[:200] or '无输出'}"
            )

    def 游戏内拉远视距(self, 次数: int = 5, 间隔毫秒: int = 180) -> bool:
        self._验证目标()
        self._验证输入前台()
        设备 = self.获取触摸设备()
        if 设备 is None:
            raise ADB错误(
                "未找到支持多点触控(protocol B)的 BlueStacks 触摸设备；"
                "已禁止发送猜测的缩放输入。请提供 `adb shell getevent -lp` 输出。"
            )
        self._确认触摸设备可写(设备)
        屏幕宽度, 屏幕高度 = self.取屏幕尺寸()
        脚本 = 生成双指捏合脚本(
            设备.路径, 设备.最大x, 设备.最大y, 屏幕宽度, 屏幕高度,
            次数=max(1, min(3, int(次数))), 旋转=self.触摸旋转,
        )
        self.执行(["shell", "sh", "-c", 脚本], timeout=max(15, 次数 * 15))
        return True
