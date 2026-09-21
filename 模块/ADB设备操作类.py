"""通过明确指定的 ADB 序列号访问 Android 模拟器。

所有设备命令均使用 ``adb -s <serial>``，不使用桌面鼠标、窗口消息或全局键盘输入。
"""
from __future__ import annotations

import os
import ctypes
import ipaddress
import re
import shutil
import subprocess
import threading
import time
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
        # MuMu Android 15 的 ADB 设备描述会伪装成手机型号（例如
        # product:a55x model:SM_A5560），但其连接仍是本机 MuMu 的
        # 16384-16499 端口。仅放行这个明确的本机模拟器端口范围，
        # 不放宽普通 USB/网络真机的安全拦截。
        if self.序列号.startswith(("127.0.0.1:", "localhost:")):
            try:
                端口 = int(self.序列号.rsplit(":", 1)[1])
            except (ValueError, IndexError):
                端口 = -1
            if 16384 <= 端口 <= 16499:
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
    # Android 的系统/电视功能键不能用于 CoC 的画面操作；误发时可能
    # 离开游戏、切换到启动器或打开模拟器的其他应用。底层再次拦截，
    # 防止绕过键盘控制器的调用把这类按键发送出去。
    禁止系统按键码 = frozenset({3, 82, 187, *range(131, 143)})
    # 同一个模拟器的 ADB server/transport 不适合被多个线程同时执行
    # screencap、dumpsys 和 input。使用按设备共享的可重入锁，既兼容
    # UI 连接检测和机器人线程并存，也避免多个 adb.exe 同时抢占通道。
    _设备命令锁容器: dict[tuple[str, str], threading.RLock] = {}
    _设备命令锁容器锁 = threading.Lock()

    @staticmethod
    def _获取主机内存状态() -> dict[str, int] | None:
        """读取 Windows 的实际可用内存和提交额度，不依赖额外第三方库。"""
        if os.name != "nt":
            return None

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        状态 = MEMORYSTATUSEX()
        状态.dwLength = ctypes.sizeof(状态)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(状态)):
            return None
        return {
            "内存负载": int(状态.dwMemoryLoad),
            "可用物理内存": int(状态.ullAvailPhys),
            "可用提交额度": int(状态.ullAvailPageFile),
        }

    def __init__(
            self,
            adb路径: str = "",
            设备序列号: str = "",
            runner: Callable = subprocess.run,
            自动检测路径: bool = True,
    ):
        self.自动检测路径 = bool(自动检测路径)
        self.adb路径 = self.解析ADB路径(adb路径, 自动检测=self.自动检测路径)
        self.设备序列号 = (设备序列号 or "").strip()
        self._runner = runner
        self._屏幕尺寸: tuple[int, int] | None = None
        self._截图显示ID: str | None = None
        self._截图显示ID更新时间 = 0.0
        self._目标已验证 = False
        # 运行期输入只能发给这个包所在的前台窗口。空值表示兼容仅做
        # ADB/截图的工具调用；正式机器人启动时会立即设置为 CoC 包名。
        self._目标包名 = ""
        self._前台包名缓存 = ""
        self._前台包名缓存时间 = 0.0
        self._前台包名缓存有效秒数 = 0.20
        self._连续传输失败次数 = 0
        self._ADB熔断截止时间 = 0.0
        self._最近恢复时间 = 0.0
        self._恢复冷却秒数 = 8.0
        self._最近ADB服务重置时间 = 0.0
        self._ADB服务重置冷却秒数 = 20.0
        self._ADB熔断秒数 = 30.0
        self._主机内存状态缓存: dict[str, int] | None = None
        self._主机内存检查时间 = 0.0
        # 截图失败时采用有限重试，而不是把一次短暂的模拟器画面抖动
        # 直接升级成机器人线程死亡。这里刻意比 MAA 的 20 次上限更保守，
        # 因为本项目每次 ADB 调用都会创建 adb.exe 子进程；重试必须有界，
        # 避免在雷电卡顿时继续堆积进程拖垮宿主机。
        self._截图重试上限 = 3
        锁键 = (os.path.normcase(os.path.abspath(self.adb路径)), self.设备序列号)
        with self._设备命令锁容器锁:
            self._命令锁 = self._设备命令锁容器.setdefault(锁键, threading.RLock())

    @staticmethod
    def _候选ADB路径() -> list[Path]:
        """返回常见模拟器和 Android SDK 的 adb 客户端位置。"""
        程序文件目录 = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        程序文件目录x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        本地应用目录 = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        用户应用目录 = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        候选 = [
            # BlueStacks
            程序文件目录 / "BlueStacks_nxt" / "HD-Adb.exe",
            程序文件目录x86 / "BlueStacks_nxt" / "HD-Adb.exe",
            程序文件目录 / "BlueStacks" / "HD-Adb.exe",
            # MuMu
            程序文件目录 / "Netease" / "MuMuPlayer" / "nx_main" / "adb.exe",
            程序文件目录 / "Netease" / "MuMuPlayer-12.0" / "shell" / "adb.exe",
            程序文件目录x86 / "Netease" / "MuMuPlayer" / "nx_main" / "adb.exe",
            本地应用目录 / "Netease" / "MuMuPlayer-12.0" / "shell" / "adb.exe",
            用户应用目录 / "Netease" / "MuMuPlayer-12.0" / "shell" / "adb.exe",
            # 雷电
            Path(r"E:\LDPlayer\LDPlayer14\adb.exe"),
            Path(r"E:\LDPlayer\LDPlayer9\adb.exe"),
            Path(r"C:\LDPlayer\LDPlayer14\adb.exe"),
            Path(r"C:\LDPlayer\LDPlayer9\adb.exe"),
            Path(r"C:\leidian\LDPlayer9\adb.exe"),
            程序文件目录 / "LDPlayer" / "LDPlayer9" / "adb.exe",
            程序文件目录x86 / "LDPlayer" / "LDPlayer9" / "adb.exe",
            # 夜神、逍遥和 Genymotion
            程序文件目录 / "Nox" / "bin" / "nox_adb.exe",
            程序文件目录x86 / "Nox" / "bin" / "nox_adb.exe",
            程序文件目录 / "Microvirt" / "MEmu" / "adb.exe",
            程序文件目录x86 / "Microvirt" / "MEmu" / "adb.exe",
            程序文件目录 / "Genymobile" / "Genymotion" / "tools" / "adb.exe",
            # Android SDK / PATH
            本地应用目录 / "Android" / "Sdk" / "platform-tools" / "adb.exe",
            Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb.exe"
            if os.environ.get("ANDROID_HOME") else Path(),
            Path(os.environ.get("ANDROID_SDK_ROOT", "")) / "platform-tools" / "adb.exe"
            if os.environ.get("ANDROID_SDK_ROOT") else Path(),
        ]
        雷电目录 = os.environ.get("COC_LDPLAYER_DIR", "").strip()
        if 雷电目录:
            候选.insert(0, Path(雷电目录) / ("adb.exe" if os.name == "nt" else "adb"))

        去重 = []
        已见 = set()
        for 路径 in 候选:
            if not str(路径) or str(路径) == ".":
                continue
            标准路径 = os.path.normcase(os.path.abspath(str(路径)))
            if 标准路径 not in 已见:
                已见.add(标准路径)
                去重.append(路径)
        return 去重

    @classmethod
    def 查找ADB路径(cls, adb路径: str = "", 自动检测: bool = True) -> list[str]:
        """查找可用的 adb.exe；显式路径优先，自动检测时再查常见模拟器目录。"""
        候选 = (adb路径 or os.environ.get("ANDROID_ADB", "")).strip().strip('"')
        if 候选:
            路径 = Path(候选)
            if 路径.is_dir():
                路径 = 路径 / ("adb.exe" if os.name == "nt" else "adb")
            if 路径.is_file():
                return [str(路径.resolve())]
            系统候选 = shutil.which(候选)
            if 系统候选:
                return [str(Path(系统候选).resolve())]
            raise ADB错误(f"ADB 路径不存在：{候选}")
        if not 自动检测:
            raise ADB错误("未启用 ADB 自动检测，请填写模拟器自带的 adb.exe 路径。")
        可执行路径 = []
        for 路径 in cls._候选ADB路径():
            if 路径.is_file():
                可执行路径.append(str(路径.resolve()))
        系统路径 = shutil.which("adb")
        if 系统路径:
            可执行路径.append(str(Path(系统路径).resolve()))
        去重 = list(dict.fromkeys(可执行路径))
        if 去重:
            return 去重
        raise ADB错误("找不到 adb.exe。请在“模拟器连接”页选择模拟器自带的 adb.exe。")

    @classmethod
    def 解析ADB路径(cls, adb路径: str = "", 自动检测: bool = True) -> str:
        return cls.查找ADB路径(adb路径, 自动检测=自动检测)[0]

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
        参数 = list(参数)
        self._拒绝危险结束命令(参数)
        命令 = self.构造设备命令(self.adb路径, self.设备序列号, 参数)
        with self._命令锁:
            当前时间 = time.monotonic()
            if 当前时间 < self._ADB熔断截止时间:
                剩余 = max(1, int(self._ADB熔断截止时间 - 当前时间))
                raise ADB错误(
                    f"ADB 传输连续失败，已进入{剩余}秒安全冷却；"
                    "不会继续创建 adb 进程，避免电脑和模拟器被拖垮。"
                )

            for 尝试次数 in range(2):
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
                    # 截图超时意味着底层 transport 可能已经卡住。最多恢复
                    # 一次；第二次失败立即熔断，避免长时间运行时不断创建
                    # adb.exe、reconnect 和 screencap 进程，把整台电脑拖死。
                    self._记录传输失败()
                    if 尝试次数 == 0:
                        self._尝试恢复ADB连接()
                        continue
                    raise ADB错误(f"ADB 命令超时：{' '.join(命令[1:])}") from 异常

                stdout = 结果.stdout or (b"" if binary else "")
                stderr = 结果.stderr or (b"" if binary else "")
                if not 结果.returncode:
                    self._连续传输失败次数 = 0
                    self._ADB熔断截止时间 = 0.0
                    return stdout

                if isinstance(stderr, bytes):
                    错误文本 = stderr.decode("utf-8", errors="replace").strip()
                else:
                    错误文本 = str(stderr).strip()
                if (
                    尝试次数 == 0
                    and self._是ADB传输错误(错误文本)
                ):
                    self._记录传输失败()
                    self._尝试恢复ADB连接(
                        重置ADB服务=self._需要重置ADB服务(错误文本)
                    )
                    continue
                if self._是ADB传输错误(错误文本):
                    self._记录传输失败()
                raise ADB错误(错误文本 or f"ADB 命令失败，退出码 {结果.returncode}")

        raise ADB错误(f"ADB 命令失败：{' '.join(命令[1:])}")

    @staticmethod
    def _是ADB传输错误(错误文本: str) -> bool:
        """判断是否为模拟器 ADB 通道短暂断线，而非业务命令错误。"""
        文本 = str(错误文本 or "").lower()
        return any(
            标记 in 文本
            for 标记 in (
                "device offline",
                "device not found",
                "protocol fault",
                "connection reset",
                "cannot connect",
                "closed",
            )
        )

    @staticmethod
    def _需要重置ADB服务(错误文本: str) -> bool:
        """设备从列表消失时，单纯 reconnect 往往无法唤醒 adb server。"""
        文本 = str(错误文本 or "").lower()
        return any(
            标记 in 文本
            for 标记 in (
                "device not found",
                "no devices/emulators found",
                "cannot connect",
                "adb server",
            )
        )

    def _运行ADB服务命令(self, 子命令: str, *, timeout: float = 8) -> None:
        """运行 adb server 控制命令；不向 Android 发送任何输入。"""
        命令 = [self.adb路径, 子命令]
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._runner(
            命令,
            capture_output=True,
            timeout=timeout,
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )

    def _重置ADB服务(self) -> None:
        """仅重启本机 adb server，不关闭游戏、不重启模拟器。"""
        当前时间 = time.monotonic()
        if 当前时间 - self._最近ADB服务重置时间 < self._ADB服务重置冷却秒数:
            return
        self._最近ADB服务重置时间 = 当前时间
        try:
            self._运行ADB服务命令("kill-server")
            self._运行ADB服务命令("start-server")
        except Exception:
            # 后续的 devices 查询会给出更准确的最终错误；这里不吞掉查询结果。
            pass
        time.sleep(0.35)

    def _连接已保存网络设备(self) -> None:
        """MuMu 网络 ADB 从设备列表消失时，仅重连保存的本机地址。"""
        if not self._是MuMu连接() or not re.fullmatch(r"(?:127\.0\.0\.1|localhost):\d+", self.设备序列号):
            return
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._runner(
                [self.adb路径, "connect", self.设备序列号],
                capture_output=True,
                timeout=8,
                check=False,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _尝试恢复ADB连接(self, *, 重置ADB服务: bool = False) -> None:
        """优先恢复 transport；设备消失时再重置 adb server，不动游戏或模拟器。"""
        当前时间 = time.monotonic()
        if 当前时间 - self._最近恢复时间 < self._恢复冷却秒数:
            return
        self._最近恢复时间 = 当前时间
        命令 = [self.adb路径, "reconnect", "offline"]
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            if 重置ADB服务:
                self._重置ADB服务()
            else:
                self._runner(
                    命令,
                    capture_output=True,
                    timeout=5,
                    check=False,
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                )
        except Exception:
            # 恢复命令失败时让原始命令的第二次尝试给出最终错误。
            pass
        time.sleep(0.35)

    def _记录传输失败(self) -> None:
        """记录 ADB transport 失败，并在连续失败时短暂熔断。"""
        self._连续传输失败次数 += 1
        if self._连续传输失败次数 >= 2:
            self._ADB熔断截止时间 = time.monotonic() + self._ADB熔断秒数

    @staticmethod
    def _拒绝危险结束命令(参数: Iterable[str]) -> None:
        """阻止任务流程意外结束游戏、清空数据或关闭 Android。"""
        参数 = [str(项).lower() for 项 in 参数]
        if "shell" not in 参数:
            return
        shell参数 = 参数[参数.index("shell") + 1:]
        危险序列 = (("am", "force-stop"), ("am", "kill"), ("pm", "clear"), ("reboot",))
        for 序列 in 危险序列:
            if all(项 in shell参数 for 项 in 序列):
                raise ADB错误(
                    f"安全保护已拦截 ADB 结束命令：{' '.join(shell参数)}；"
                    "当前模式不会主动关闭游戏或模拟器。"
                )

    @classmethod
    def 扫描设备(
            cls,
            adb路径: str = "",
            runner: Callable = subprocess.run,
            自动检测路径: bool = True,
    ) -> list[ADB设备信息]:
        临时适配器 = cls(
            adb路径,
            "_scan_placeholder",
            runner=runner,
            自动检测路径=自动检测路径,
        )
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
    def 连接网络设备(
            cls,
            adb路径: str,
            地址: str,
            runner: Callable = subprocess.run,
            自动检测路径: bool = True,
    ) -> str:
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
        可执行文件 = cls.解析ADB路径(adb路径, 自动检测=自动检测路径)
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
        设备列表 = self.扫描设备(
            self.adb路径,
            runner=self._runner,
            自动检测路径=self.自动检测路径,
        )
        当前设备 = next((设备 for 设备 in 设备列表 if 设备.序列号 == self.设备序列号), None)
        if 当前设备 is None:
            # 雷电运行时偶发会保留虚拟机但让 adb server 丢失设备记录。
            # 只重启本机 server，再扫描一次；绝不重启模拟器或关闭 CoC。
            self._重置ADB服务()
            self._连接已保存网络设备()
            设备列表 = self.扫描设备(
                self.adb路径,
                runner=self._runner,
                自动检测路径=self.自动检测路径,
            )
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

    def 设置目标包名(self, 包名: str) -> None:
        """绑定运行期输入目标；不执行启动、切换或关闭应用。"""
        self._目标包名 = str(包名 or "").strip()
        self._前台包名缓存 = ""
        self._前台包名缓存时间 = 0.0

    def _是MuMu连接(self) -> bool:
        """识别 MuMu ADB；不把普通网络/USB Android 设备当成模拟器。"""
        路径 = str(self.adb路径 or "").lower().replace("\\", "/")
        if "mumuplayer" in 路径:
            return True
        if self.设备序列号.startswith(("127.0.0.1:", "localhost:")):
            try:
                端口 = int(self.设备序列号.rsplit(":", 1)[1])
            except (ValueError, IndexError):
                端口 = -1
            return 16384 <= 端口 <= 16499
        return False

    def _获取MuMu截图显示ID(self) -> str | None:
        """返回当前前台应用所在 MuMu 虚拟显示的 SurfaceFlinger ID。"""
        当前时间 = time.monotonic()
        if 当前时间 - self._截图显示ID更新时间 < 3.0:
            return self._截图显示ID
        self._截图显示ID更新时间 = 当前时间
        try:
            窗口输出 = self.执行(["shell", "dumpsys", "window", "displays"], timeout=8)
            if isinstance(窗口输出, bytes):
                窗口输出 = 窗口输出.decode("utf-8", errors="replace")
            选中逻辑ID = None
            候选逻辑ID = []
            分块 = re.split(r"\n\s*Display:\s*mDisplayId=", "\n" + str(窗口输出))
            for 块 in 分块[1:]:
                匹配 = re.match(r"(\d+)", 块)
                if not 匹配:
                    continue
                逻辑ID = 匹配.group(1)
                if "mCurrentFocus=" in 块 and "mCurrentFocus=null" not in 块:
                    候选逻辑ID.append(逻辑ID)
                    if self._目标包名 and self._目标包名 in 块:
                        选中逻辑ID = 逻辑ID
            if 选中逻辑ID is None and 候选逻辑ID:
                选中逻辑ID = 候选逻辑ID[-1]
            if 选中逻辑ID is None:
                return None

            显示输出 = self.执行(["shell", "dumpsys", "display"], timeout=8)
            if isinstance(显示输出, bytes):
                显示输出 = 显示输出.decode("utf-8", errors="replace")
            模式 = rf"mDisplayId={re.escape(选中逻辑ID)}\b.*?mPrimaryDisplayDevice=.*?\(local:(\d+)\)"
            匹配 = re.search(模式, str(显示输出), flags=re.S)
            self._截图显示ID = 匹配.group(1) if 匹配 else None
            return self._截图显示ID
        except (ADB错误, ValueError, TypeError, re.error):
            self._截图显示ID = None
            return None

    def _验证输入前台(self) -> None:
        """拒绝把触控/按键发给启动器或其他 Android 应用。"""
        目标包名 = str(getattr(self, "_目标包名", "") or "")
        if not 目标包名:
            return
        当前时间 = time.monotonic()
        if 当前时间 - self._前台包名缓存时间 <= self._前台包名缓存有效秒数:
            当前包名 = self._前台包名缓存
        else:
            当前包名 = self.获取当前前台包名()
            self._前台包名缓存 = 当前包名
            self._前台包名缓存时间 = 当前时间
        if 当前包名 != 目标包名:
            raise ADB错误(
                f"安全保护已拒绝输入：CoC不在前台（当前={当前包名 or '未知'}，"
                f"目标={目标包名}）；不会点击其他应用或发送返回键。"
            )

    def 获取屏幕图像cv(self, 左边: int = 0, 顶边: int = 0, 右边: int = 2000, 底边: int = 2000):
        import cv2
        import numpy as np

        # 先验证目标设备，再读取主机内存。这样在实体手机、未授权设备等
        # 不应被触碰的目标上，始终返回明确的设备安全错误，而不会被主机
        # 当前内存状态遮蔽；通过验证后才允许创建截图缓冲。
        self._验证目标()
        最后错误 = None
        图像 = None
        for 尝试次数 in range(self._截图重试上限):
            # 内存保护必须在每一次重试前重新检查；不能为了等待模拟器
            # 恢复而绕过宿主机保护。
            self._检查主机内存预算()
            try:
                截图参数 = ["exec-out", "screencap"]
                if self._是MuMu连接():
                    显示ID = self._获取MuMu截图显示ID()
                    if 显示ID:
                        截图参数.extend(["-d", 显示ID])
                截图参数.append("-p")
                原始PNG = self.执行(截图参数, timeout=15, binary=True)
                if len(原始PNG) > 20 * 1024 * 1024:
                    raise ADB错误("ADB 截图数据异常过大，已拒绝继续解码以保护内存。")
                # MuMu Android 15 的 adb.exe 在 exec-out 输出 PNG 前会把
                # “Multiple displays were found...” 警告写到 stdout，导致
                # OpenCV 无法解码。只丢弃 PNG 签名以前的这段诊断文本，
                # 不放宽大小限制，也不吞掉真正的空响应。
                PNG签名 = b"\x89PNG\r\n\x1a\n"
                PNG起点 = 原始PNG.find(PNG签名)
                if PNG起点 > 0:
                    原始PNG = 原始PNG[PNG起点:]
                图像 = cv2.imdecode(np.frombuffer(原始PNG, dtype=np.uint8), cv2.IMREAD_COLOR)
                if 图像 is None or 图像.size == 0:
                    raise ADB错误("ADB 截图无法解码；请确认设备已启动并允许 ADB 调试。")
                break
            except ADB错误 as 异常:
                最后错误 = 异常
            except (cv2.error, ValueError, TypeError) as 异常:
                最后错误 = ADB错误(f"ADB 截图解码失败：{异常}")

            if 尝试次数 + 1 < self._截图重试上限:
                # 参考 MAA 的“重新连接后重试原命令”语义，但等待和次数
                # 受控；不会重启模拟器、结束游戏或切换 Android 前台。
                self._尝试恢复ADB连接()
                time.sleep(0.35 * (尝试次数 + 1))

        if 图像 is None:
            raise 最后错误 or ADB错误("ADB 截图失败。")
        高, 宽 = 图像.shape[:2]
        self._屏幕尺寸 = (宽, 高)
        左边, 顶边 = max(0, int(左边)), max(0, int(顶边))
        右边, 底边 = min(int(右边), 宽), min(int(底边), 高)
        if 右边 <= 左边 or 底边 <= 顶边:
            raise ADB错误(f"截图区域超出设备屏幕 {宽}×{高}：{左边},{顶边},{右边},{底边}")
        return 图像[顶边:底边, 左边:右边].copy()

    def _检查主机内存预算(self) -> None:
        """在创建 screencap/OCR 临时缓冲前拒绝低内存状态。

        雷电发生低虚拟内存时继续发起截图会让 ADB 客户端堆积，最终连
        模拟器主进程也可能被拖垮。这里每两秒检查一次；若接近耗尽，只
        停止本次自动化，不关闭 Android、CoC 或模拟器。
        """
        当前时间 = time.monotonic()
        if 当前时间 - self._主机内存检查时间 >= 2.0:
            self._主机内存状态缓存 = self._获取主机内存状态()
            self._主机内存检查时间 = 当前时间
        状态 = self._主机内存状态缓存
        if not 状态:
            return
        MB = 1024 * 1024
        物理内存不足 = 状态["可用物理内存"] < 900 * MB
        提交额度不足 = 状态["可用提交额度"] < 1536 * MB
        负载过高 = 状态["内存负载"] >= 92
        if 物理内存不足 or 提交额度不足 or 负载过高:
            raise ADB错误(
                "主机内存保护已触发："
                f"负载{状态['内存负载']}%，"
                f"可用物理内存{状态['可用物理内存'] // MB}MB，"
                f"可用提交额度{状态['可用提交额度'] // MB}MB；"
                "禁止继续截图/OCR，已保留模拟器和游戏进程。"
            )

    def 取屏幕尺寸(self) -> tuple[int, int]:
        if self._屏幕尺寸 is None:
            self._验证目标()
            try:
                self._屏幕尺寸 = self.查询屏幕尺寸()
            except ADB错误:
                self._屏幕尺寸 = None
            if not self._屏幕尺寸:
                # 测试/兼容设备的安全默认值；真实截图成功后会更新为实际尺寸。
                self._屏幕尺寸 = (self.参考宽度, self.参考高度)
        return self._屏幕尺寸

    def 参考坐标转设备坐标(self, x: int | float, y: int | float) -> tuple[int, int]:
        """把任务使用的 800×600 参考坐标映射到实际 ADB 屏幕。"""
        宽度, 高度 = self.取屏幕尺寸()
        设备x = round(float(x) * 宽度 / self.参考宽度)
        设备y = round(float(y) * 高度 / self.参考高度)
        return max(0, min(宽度 - 1, 设备x)), max(0, min(高度 - 1, 设备y))

    def 触控(self, x: int, y: int) -> bool:
        self._验证目标()
        self._验证输入前台()
        x, y = self.参考坐标转设备坐标(x, y)
        self.执行(["shell", "input", "tap", str(x), str(y)], timeout=8)
        return True

    def 连续触控(self, 位置列表: Iterable[tuple[int, int]], 间隔毫秒: int = 0) -> bool:
        """在一次 ADB shell 会话内连续点击多个位置，减少逐次启动 adb 的开销。"""
        self._验证目标()
        self._验证输入前台()
        try:
            点位 = [(int(位置[0]), int(位置[1])) for 位置 in 位置列表]
        except (TypeError, ValueError, IndexError) as 异常:
            raise ADB错误("连续触控坐标非法。") from 异常
        if not 点位:
            return True
        if len(点位) > 32:
            raise ADB错误("单次连续触控最多支持 32 个点。")

        # 雷电 Android 14 在短时间内连续 fork ``input tap`` 会把 guest
        # 标记为无响应，LMKD 随后可能直接杀掉正在前台的 CoC。多点输入
        # 统一保留至少 40ms 的呼吸间隔；单点不额外延迟。
        间隔毫秒 = max(0, min(80, int(间隔毫秒)))
        if len(点位) > 1:
            间隔毫秒 = max(40, 间隔毫秒)
        点位 = [self.参考坐标转设备坐标(x, y) for x, y in 点位]
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
        self._验证输入前台()
        时长毫秒 = max(120, min(1500, int(时长毫秒)))
        x, y = self.参考坐标转设备坐标(x, y)
        self.执行([
            "shell", "input", "swipe", str(int(x)), str(int(y)),
            str(int(x)), str(int(y)), str(时长毫秒),
        ], timeout=max(8, 时长毫秒 / 1000 + 5))
        return True

    def 滑动(self, 起点: tuple[int, int], 终点: tuple[int, int], 时长毫秒: int = 350) -> bool:
        self._验证目标()
        self._验证输入前台()
        起点 = self.参考坐标转设备坐标(*起点)
        终点 = self.参考坐标转设备坐标(*终点)
        self.执行(["shell", "input", "swipe", str(起点[0]), str(起点[1]),
                    str(终点[0]), str(终点[1]), str(max(1, int(时长毫秒)))], timeout=10)
        return True

    def 按键(self, 按键码: int | str) -> bool:
        self._验证目标()
        try:
            数字按键码 = int(按键码)
        except (TypeError, ValueError) as 异常:
            raise ADB错误(f"ADB 输入按键非法：{按键码}") from 异常
        if 数字按键码 in self.禁止系统按键码:
            # 这是安全拒绝，不抛异常，避免把一次无效的缩放请求升级成
            # 任务重启；调用方会自然继续当前识别流程。
            return False
        self._验证输入前台()
        self.执行(["shell", "input", "keyevent", str(数字按键码)], timeout=8)
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
        宽度, 高度 = int(宽度), int(高度)
        if not 320 <= 宽度 <= 4096 or not 240 <= 高度 <= 4096:
            raise ADB错误("分辨率超出安全范围：宽度 320–4096，高度 240–4096。")
        self.执行(["shell", "wm", "size", f"{宽度}x{高度}"], timeout=8)
        self._屏幕尺寸 = (宽度, 高度)

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
            (
                行.strip()
                for 行 in str(解析输出).splitlines()
                if "/" in 行
                and not 行.strip().startswith("priority=")
                # resolve-activity 的输出必须属于目标包名；不能因为
                # 厂商 ROM 返回额外组件行就把其他应用切到前台。
                and 行.strip().split("/", 1)[0] == 包名
            ),
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

    def 获取当前前台包名(self) -> str:
        """读取当前前台 Activity 所属包名，不执行任何切换操作。"""
        当前前台 = self.执行(["shell", "dumpsys", "activity", "activities"], timeout=12)
        if isinstance(当前前台, bytes):
            当前前台 = 当前前台.decode("utf-8", errors="replace")
        for 行 in str(当前前台).splitlines():
            if "mResumedActivity" not in 行 and "topResumedActivity" not in 行:
                continue
            # 兼容：ActivityRecord{... u0 package/activity ...}
            匹配 = re.search(r"\bu\d+\s+([A-Za-z0-9_.$-]+)/", 行)
            if 匹配:
                return 匹配.group(1)
        return ""

    def 关闭模拟器中的应用(self, 包名: str) -> None:
        raise ADB错误(
            f"安全保护已阻止结束应用：{包名 or '未知包名'}。"
            "ADB 模式不会主动关闭游戏，请从模拟器界面手动退出。"
        )

    def 修改分辨率(self, 宽度: int = 800, 高度: int = 600, dpi: int = 160) -> None:
        self.设置屏幕尺寸(宽度, 高度)

    def 启动模拟器并打开应用(self, 包名: str) -> None:
        raise ADB错误("ADB 目标未在线。请手动启动模拟器、打开 ADB 调试并重新扫描；不会操作桌面或启动其他实例。")

    def 关闭雷电模拟器(self) -> None:
        raise ADB错误("ADB 模式不会关闭模拟器窗口。请从模拟器自身界面退出。")
