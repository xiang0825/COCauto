"""通过明确指定的 ADB 序列号访问 Android 模拟器。

所有设备命令均使用 ``adb -s <serial>``，不使用桌面鼠标、窗口消息或全局键盘输入。
"""
from __future__ import annotations

import os
import ipaddress
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


class ADB错误(RuntimeError):
    pass


@dataclass(frozen=True)
class ADB设备信息:
    序列号: str
    状态: str
    描述: str = ""

    @property
    def 显示文本(self) -> str:
        return f"{self.序列号}  [{self.状态}]" + (f"  {self.描述}" if self.描述 else "")

    @property
    def 疑似实体设备(self) -> bool:
        描述 = self.描述.lower().replace("_", "-")
        模拟器标记 = ("ldplayer", "mumu", "bluestacks", "nox", "genymotion", "sdk-gphone", "android-sdk")
        if any(标记 in 描述 for 标记 in 模拟器标记):
            return False
        实体标记 = ("samsung", "model:sm-", "model:sm", "pixel", "xiaomi", "redmi", "oneplus",
                    "huawei", "honor", "oppo", "vivo", "motorola", "sony", "realme")
        return any(标记 in 描述 for 标记 in 实体标记)


def 解析ADB设备列表(文本: str) -> list[ADB设备信息]:
    设备列表 = []
    for 行 in 文本.splitlines():
        行 = 行.strip()
        if not 行 or 行.startswith("List of devices") or 行.startswith("* daemon"):
            continue
        匹配 = re.match(r"^(\S+)\s+(\S+)(?:\s+(.*))?$", 行)
        if 匹配:
            设备列表.append(ADB设备信息(匹配.group(1), 匹配.group(2), 匹配.group(3) or ""))
    return 设备列表


class ADB设备操作类:
    """一个固定绑定到指定 ADB 序列号的设备适配器。"""

    参考宽度 = 800
    参考高度 = 600

    def __init__(self, adb路径: str = "", 设备序列号: str = "", runner: Callable = subprocess.run):
        self.adb路径 = self.解析ADB路径(adb路径)
        self.设备序列号 = (设备序列号 or "").strip()
        self._runner = runner
        self._屏幕尺寸: tuple[int, int] | None = None
        self._目标已验证 = False

    @staticmethod
    def 解析ADB路径(adb路径: str = "") -> str:
        候选 = (adb路径 or os.environ.get("ANDROID_ADB", "")).strip().strip('"')
        if 候选:
            路径 = Path(候选)
            if 路径.is_dir():
                路径 = 路径 / ("adb.exe" if os.name == "nt" else "adb")
            if 路径.is_file():
                return str(路径.resolve())
            系统候选 = shutil.which(候选)
            if 系统候选:
                return 系统候选
            raise ADB错误(f"ADB 路径不存在：{候选}")
        # 常见 Windows 模拟器安装位置；也可在“设备连接”页手动选择 adb.exe。
        雷电目录 = os.environ.get("COC_LDPLAYER_DIR", "")
        程序文件目录 = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        常见位置 = [
            程序文件目录 / "BlueStacks_nxt" / "HD-Adb.exe",
            程序文件目录 / "Netease" / "MuMuPlayer" / "nx_main" / "adb.exe",
            程序文件目录 / "Netease" / "MuMuPlayer-12.0" / "shell" / "adb.exe",
            Path(r"E:\LDPlayer\LDPlayer14\adb.exe"),
            Path(r"C:\LDPlayer\LDPlayer9\adb.exe"),
        ]
        if 雷电目录:
            常见位置.insert(3, Path(雷电目录) / ("adb.exe" if os.name == "nt" else "adb"))
        for 路径 in 常见位置:
            if 路径.is_file():
                return str(路径.resolve())
        系统路径 = shutil.which("adb")
        if 系统路径:
            return 系统路径
        raise ADB错误("找不到 adb.exe。请在“模拟器连接”页选择模拟器自带的 adb.exe。")

    @staticmethod
    def 构造设备命令(adb路径: str, 序列号: str, 参数: Iterable[str]) -> list[str]:
        if not 序列号 or not 序列号.strip():
            raise ADB错误("尚未选择 ADB 设备；请先扫描并明确选择 Android 模拟器。")
        return [adb路径, "-s", 序列号.strip(), *map(str, 参数)]

    @staticmethod
    def 解析屏幕尺寸(文本: str) -> tuple[int, int] | None:
        # 兼容 wm size 输出中的 Physical size 与 Override size。
        匹配项 = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", 文本)
        if not 匹配项:
            匹配项 = re.findall(r"(\d+)x(\d+)", 文本)
        if not 匹配项:
            return None
        宽, 高 = map(int, 匹配项[-1])
        return (宽, 高) if 宽 > 0 and 高 > 0 else None

    def 执行(self, 参数: Iterable[str], *, timeout: float = 10, binary: bool = False):
        命令 = self.构造设备命令(self.adb路径, self.设备序列号, 参数)
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            结果 = self._runner(
                命令,
                capture_output=True,
                timeout=timeout,
                check=False,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
        except FileNotFoundError as 异常:
            raise ADB错误(f"无法启动 ADB：{self.adb路径}") from 异常
        except subprocess.TimeoutExpired as 异常:
            raise ADB错误(f"ADB 命令超时：{' '.join(命令[1:])}") from 异常

        stdout = 结果.stdout or (b"" if binary else "")
        stderr = 结果.stderr or (b"" if binary else "")
        if 结果.returncode:
            if isinstance(stderr, bytes):
                错误文本 = stderr.decode("utf-8", errors="replace").strip()
            else:
                错误文本 = str(stderr).strip()
            raise ADB错误(错误文本 or f"ADB 命令失败，退出码 {结果.returncode}")
        return stdout

    @classmethod
    def 扫描设备(cls, adb路径: str = "", runner: Callable = subprocess.run) -> list[ADB设备信息]:
        临时适配器 = cls(adb路径, "_scan_placeholder", runner=runner)
        命令 = [临时适配器.adb路径, "devices", "-l"]
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            结果 = runner(命令, capture_output=True, timeout=10, check=False,
                          startupinfo=startupinfo, creationflags=creationflags)
        except (FileNotFoundError, subprocess.TimeoutExpired) as 异常:
            raise ADB错误(f"扫描 ADB 设备失败：{异常}") from 异常
        if 结果.returncode:
            错误 = (结果.stderr or b"")
            if isinstance(错误, bytes):
                错误 = 错误.decode("utf-8", errors="replace")
            raise ADB错误(str(错误).strip() or "扫描 ADB 设备失败")
        输出 = 结果.stdout or ""
        if isinstance(输出, bytes):
            输出 = 输出.decode("utf-8", errors="replace")
        return 解析ADB设备列表(输出)

    @classmethod
    def 连接网络设备(cls, adb路径: str, 地址: str, runner: Callable = subprocess.run) -> str:
        地址 = (地址 or "").strip()
        匹配 = re.fullmatch(r"([^:\s]+):(\d{1,5})", 地址)
        if not 匹配 or not 1 <= int(匹配.group(2)) <= 65535:
            raise ADB错误("地址格式应为 host:port，例如 127.0.0.1:5555。")
        主机 = 匹配.group(1)
        try:
            ipaddress.ip_address(主机)
        except ValueError:
            if not re.fullmatch(r"[A-Za-z0-9.-]+", 主机):
                raise ADB错误("地址格式应为 host:port，例如 127.0.0.1:5555。")
        可执行文件 = cls.解析ADB路径(adb路径)
        命令 = [可执行文件, "connect", 地址]
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            结果 = runner(命令, capture_output=True, timeout=10, check=False,
                          startupinfo=startupinfo, creationflags=creationflags)
        except (FileNotFoundError, subprocess.TimeoutExpired) as 异常:
            raise ADB错误(f"ADB 网络连接失败：{异常}") from 异常
        输出 = 结果.stdout or b""
        错误 = 结果.stderr or b""
        if isinstance(输出, bytes):
            输出 = 输出.decode("utf-8", errors="replace")
        if isinstance(错误, bytes):
            错误 = 错误.decode("utf-8", errors="replace")
        文本 = str(输出).strip() or str(错误).strip()
        if 结果.returncode or "unable" in 文本.lower() or "failed" in 文本.lower():
            raise ADB错误(文本 or "ADB 网络连接失败。")
        return 文本 or f"已连接 {地址}"

    def 确认在线(self) -> ADB设备信息:
        if not self.设备序列号:
            raise ADB错误("尚未选择设备序列号。")
        设备列表 = self.扫描设备(self.adb路径, runner=self._runner)
        当前设备 = next((设备 for 设备 in 设备列表 if 设备.序列号 == self.设备序列号), None)
        if 当前设备 is None:
            raise ADB错误(f"所选设备 {self.设备序列号} 未出现在 ADB 设备列表中。")
        if 当前设备.状态 != "device":
            raise ADB错误(f"所选设备状态为“{当前设备.状态}”；请检查模拟器 ADB 调试授权。")
        if 当前设备.疑似实体设备:
            raise ADB错误(
                f"目标 {当前设备.序列号} 报告为实体 Android 设备（{当前设备.描述}），"
                "为避免触碰真实手机，已阻止截图和控制。请连接 MuMu、雷电或 BlueStacks 模拟器。"
            )
        self._目标已验证 = True
        return 当前设备

    def _验证目标(self) -> None:
        if not self._目标已验证:
            self.确认在线()

    def 获取屏幕图像cv(self, 左边: int = 0, 顶边: int = 0, 右边: int = 2000, 底边: int = 2000):
        import cv2
        import numpy as np

        self._验证目标()
        原始PNG = self.执行(["exec-out", "screencap", "-p"], timeout=15, binary=True)
        图像 = cv2.imdecode(np.frombuffer(原始PNG, dtype=np.uint8), cv2.IMREAD_COLOR)
        if 图像 is None or 图像.size == 0:
            raise ADB错误("ADB 截图无法解码；请确认设备已启动并允许 ADB 调试。")
        高, 宽 = 图像.shape[:2]
        self._屏幕尺寸 = (宽, 高)
        左边, 顶边 = max(0, int(左边)), max(0, int(顶边))
        右边, 底边 = min(int(右边), 宽), min(int(底边), 高)
        if 右边 <= 左边 or 底边 <= 顶边:
            raise ADB错误(f"截图区域超出设备屏幕 {宽}×{高}：{左边},{顶边},{右边},{底边}")
        return 图像[顶边:底边, 左边:右边].copy()

    def 取屏幕尺寸(self) -> tuple[int, int]:
        if self._屏幕尺寸 is None:
            self.获取屏幕图像cv(0, 0, self.参考宽度, self.参考高度)
        return self._屏幕尺寸

    def 触控(self, x: int, y: int) -> bool:
        self._验证目标()
        self.执行(["shell", "input", "tap", str(int(x)), str(int(y))], timeout=8)
        return True

    def 连续触控(self, 位置列表: Iterable[tuple[int, int]], 间隔毫秒: int = 0) -> bool:
        """在一次 ADB shell 会话内连续点击多个位置，减少逐次启动 adb 的开销。"""
        self._验证目标()
        try:
            点位 = [(int(位置[0]), int(位置[1])) for 位置 in 位置列表]
        except (TypeError, ValueError, IndexError) as 异常:
            raise ADB错误("连续触控坐标非法。") from 异常
        if not 点位:
            return True
        if len(点位) > 32:
            raise ADB错误("单次连续触控最多支持 32 个点。")

        间隔毫秒 = max(0, min(80, int(间隔毫秒)))
        间隔命令 = f"; sleep {间隔毫秒 / 1000:.3f}" if 间隔毫秒 else ""
        脚本 = "; ".join(
            f"input tap {x} {y}{间隔命令 if 序号 < len(点位) - 1 else ''}"
            for 序号, (x, y) in enumerate(点位)
        )
        self.执行(["shell", "sh", "-c", 脚本], timeout=max(8, len(点位) * 2))
        return True

    def 长按触控(self, x: int, y: int, 时长毫秒: int = 220) -> bool:
        """通过同点 swipe 发送一次短长按，供游戏的按住连续部署手势使用。"""
        self._验证目标()
        时长毫秒 = max(120, min(1500, int(时长毫秒)))
        self.执行([
            "shell", "input", "swipe", str(int(x)), str(int(y)),
            str(int(x)), str(int(y)), str(时长毫秒),
        ], timeout=max(8, 时长毫秒 / 1000 + 5))
        return True

    def 滑动(self, 起点: tuple[int, int], 终点: tuple[int, int], 时长毫秒: int = 350) -> bool:
        self._验证目标()
        self.执行(["shell", "input", "swipe", str(int(起点[0])), str(int(起点[1])),
                    str(int(终点[0])), str(int(终点[1])), str(max(1, int(时长毫秒)))], timeout=10)
        return True

    def 按键(self, 按键码: int | str) -> bool:
        self._验证目标()
        self.执行(["shell", "input", "keyevent", str(按键码)], timeout=8)
        return True

    def 获取属性(self, 属性名: str) -> str:
        输出 = self.执行(["shell", "getprop", 属性名], timeout=8)
        return 输出.decode("utf-8", errors="replace").strip() if isinstance(输出, bytes) else str(输出).strip()

    def 查询屏幕尺寸(self) -> tuple[int, int] | None:
        输出 = self.执行(["shell", "wm", "size"], timeout=8)
        if isinstance(输出, bytes):
            输出 = 输出.decode("utf-8", errors="replace")
        return self.解析屏幕尺寸(输出)

    def 设置屏幕尺寸(self, 宽度: int = 800, 高度: int = 600) -> None:
        self._验证目标()
        if (宽度, 高度) != (800, 600):
            raise ADB错误("当前任务流程只支持 800×600；拒绝应用未验证的分辨率。")
        self.执行(["shell", "wm", "size", f"{宽度}x{高度}"], timeout=8)
        self._屏幕尺寸 = None

    def 恢复屏幕尺寸(self) -> None:
        self._验证目标()
        self.执行(["shell", "wm", "size", "reset"], timeout=8)
        self._屏幕尺寸 = None

    def 是否已启动(self) -> bool:
        return self.获取属性("sys.boot_completed") == "1"

    def 是否进入安卓(self) -> bool:
        return self.是否已启动()

    def 打开应用(self, 包名: str) -> None:
        self._验证目标()
        if not 包名:
            raise ADB错误("游戏包名为空。")
        当前前台 = self.执行(["shell", "dumpsys", "activity", "activities"], timeout=12)
        if isinstance(当前前台, bytes):
            当前前台 = 当前前台.decode("utf-8", errors="replace")
        前台行 = next((行 for 行 in 当前前台.splitlines()
                       if "mResumedActivity" in 行 or "topResumedActivity" in 行), "")
        if 包名 in 前台行:
            return
        # 不 force-stop：已运行的游戏进程不会被反复杀掉重启。
        # 部分雷电镜像没有 monkey 命令，先解析 MAIN/LAUNCHER Activity，
        # 再用系统自带的 am start 启动，兼容精简 Android 镜像。
        解析输出 = self.执行([
            "shell", "cmd", "package", "resolve-activity", "--brief",
            "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.LAUNCHER", 包名
        ], timeout=15)
        if isinstance(解析输出, bytes):
            解析输出 = 解析输出.decode("utf-8", errors="replace")
        组件 = next(
            (行.strip() for 行 in str(解析输出).splitlines()
             if "/" in 行 and not 行.strip().startswith("priority=")),
            "",
        )
        if 组件:
            self.执行(["shell", "am", "start", "-n", 组件], timeout=20)
            return
        # 某些旧系统没有 resolve-activity 子命令，但仍支持按包名启动。
        self.执行([
            "shell", "am", "start", "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.LAUNCHER", "-p", 包名
        ], timeout=20)

    def 关闭模拟器中的应用(self, 包名: str) -> None:
        self._验证目标()
        self.执行(["shell", "am", "force-stop", 包名], timeout=10)

    def 修改分辨率(self, 宽度: int = 800, 高度: int = 600, dpi: int = 160) -> None:
        self.设置屏幕尺寸(宽度, 高度)

    def 启动模拟器并打开应用(self, 包名: str) -> None:
        raise ADB错误("ADB 目标未在线。请手动启动模拟器、打开 ADB 调试并重新扫描；不会操作桌面或启动其他实例。")

    def 关闭雷电模拟器(self) -> None:
        raise ADB错误("ADB 模式不会关闭模拟器窗口。请从模拟器自身界面退出。")
