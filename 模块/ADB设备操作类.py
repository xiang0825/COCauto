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
        # Android Emulator、MuMu 某些版本以及部分兼容层会使用
        # ``emulator-<port>`` 作为 serial，但描述可能伪装成手机型号。
        # serial 本身是 ADB 的虚拟设备标识，不能再被后面的 Samsung/SM
        # 型号规则误判为实体手机。
        if re.fullmatch(r"emulator-\d+", self.序列号.strip().lower()):
            return False
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
    # 不同的 ADB 适配器可能绑定同一服务（例如机器人线程和 UI 连接检测）。
    # kill-server/start-server 不是设备级操作，不能让多个适配器并发执行，
    # 否则容易把正在恢复的 transport 再次打断，造成设备反复掉线。
    _ADB服务重置锁 = threading.Lock()
    _全局最近ADB服务重置时间 = 0.0

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
        # MuMu 转场期间 dumpsys window/display 可能短暂返回空内容。
        # 保留最近一次已确认的映射用于有限时间的重试；真实 transport
        # 失败、设备变化或目标包变化时会显式清空，绝不回退到 display 0。
        self._最近有效截图显示ID: str | None = None
        self._最近有效截图显示ID时间 = 0.0
        # MuMu Android 15 可能同时存在启动器 display 0 和游戏 display 7。
        # screencap 使用的是 SurfaceFlinger 物理 ID，而 input -d 使用的是
        # dumpsys window 的逻辑 display ID；两者必须分别缓存，不能混用。
        self._输入显示ID: str | None = None
        self._输入显示ID更新时间 = 0.0
        # 前台校验和 MuMu display 映射通常在同一个操作前连续发生；短时
        # 复用同一份 window displays 输出，避免重复 ADB 查询和状态错位。
        self._MuMu窗口状态缓存 = ""
        self._MuMu窗口状态缓存时间 = 0.0
        self._最近有效输入显示ID: str | None = None
        self._最近有效输入显示ID时间 = 0.0
        self._显示层缓存有效秒数 = 30.0
        # MuMu 的 display/window 服务失效时，旧的 display ID 不能继续用于
        # screencap。否则会反复创建超时 adb.exe，拖垮宿主机和模拟器。
        self._MuMu显示服务缺失时间 = 0.0
        self._MuMu显示服务缺失冷却秒数 = 10.0
        self._触摸事件设备: str | None = None
        self._触摸事件原始尺寸: tuple[int, int] | None = None
        self._触摸事件更新时间 = 0.0
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
    def _终止ADB进程树(进程ID: int) -> None:
        """超时后清理 adb 客户端及其可能残留的子进程。"""
        if not 进程ID:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(int(进程ID)), "/T", "/F"],
                    capture_output=True,
                    timeout=3,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                os.kill(int(进程ID), 9)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass

    def _运行ADB命令(self, 命令: list[str], timeout: float, *, binary: bool,
                   startupinfo, creationflags):
        """运行默认 ADB 时显式回收超时进程；测试 runner 保持原有注入行为。"""
        if self._runner is not subprocess.run:
            return self._runner(
                命令,
                capture_output=True,
                timeout=timeout,
                check=False,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
        进程 = subprocess.Popen(
            命令,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        try:
            标准输出, 标准错误 = 进程.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._终止ADB进程树(进程.pid)
            try:
                标准输出, 标准错误 = 进程.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                进程.kill()
                标准输出, 标准错误 = 进程.communicate()
            raise
        return subprocess.CompletedProcess(
            命令, 进程.returncode, 标准输出, 标准错误
        )

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
                # transport 失败后，第一次重试先重新确认原来选择的
                # 设备仍在线；不能只 reconnect 后继续使用失效 serial。
                if 尝试次数 > 0 and not self._目标已验证:
                    self.确认在线()
                startupinfo = None
                creationflags = 0
                if os.name == "nt":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                try:
                    结果 = self._运行ADB命令(
                        命令,
                        timeout,
                        binary=binary,
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
                    # MuMu 的 cmd/dumpsys 在 Android 服务缺失时可能退出码仍
                    # 为 0，却把诊断写到 stdout 或 stderr。必须把这类明确的
                    # 系统故障继续向上抛出，避免启动流程把空输出当成“应用
                    # 尚未前台”并反复尝试打开 CoC。
                    if not binary:
                        for 服务诊断 in (stdout, stderr):
                            if self._是Android系统服务缺失错误(服务诊断):
                                if isinstance(服务诊断, bytes):
                                    服务诊断 = 服务诊断.decode("utf-8", errors="replace")
                                raise ADB错误(str(服务诊断).strip())
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
                    # 先走 reconnect，再由下一轮的确认在线决定是否需要
                    # 重置 server。这样已有其他设备在线时不会被 stale
                    # serial 的错误连带断开。
                    self._尝试恢复ADB连接()
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
    def _是Android系统服务缺失错误(错误文本) -> bool:
        """识别 Android cmd/dumpsys 的明确 Binder 服务缺失诊断。"""
        文本 = str(错误文本 or "").lower()
        return "can't find service:" in 文本

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
        # 冷却时间必须是进程级的：每个适配器各自记录时间会让多个
        # 适配器在同一秒内重复 kill-server，正是长期运行时 ADB 抖动的
        # 常见来源。锁内再次检查，避免等待锁期间重复重置。
        with self._ADB服务重置锁:
            当前时间 = time.monotonic()
            if 当前时间 - self._最近ADB服务重置时间 < self._ADB服务重置冷却秒数:
                return
            if 当前时间 - type(self)._全局最近ADB服务重置时间 < self._ADB服务重置冷却秒数:
                self._最近ADB服务重置时间 = 当前时间
                return
            self._最近ADB服务重置时间 = 当前时间
            type(self)._全局最近ADB服务重置时间 = 当前时间
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
        self._标记目标未验证()
        # transport 失败可能意味着 MuMu 实例或显示层已经变化，不能把
        # 旧 display 映射带到另一条 ADB 通道。
        self._最近有效截图显示ID = None
        self._最近有效截图显示ID时间 = 0.0
        self._最近有效输入显示ID = None
        self._最近有效输入显示ID时间 = 0.0
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
    def 自动选择游戏设备(
            cls,
            adb路径: str = "",
            包名: str = "com.supercell.clashofclans",
            runner: Callable = subprocess.run,
            自动检测路径: bool = True,
    ) -> ADB设备信息:
        """在未保存 serial 时安全选择当前运行目标游戏的模拟器。

        只允许状态为 ``device`` 且不像实体手机的设备参与候选。候选评分
        依次考虑目标包是否已安装、目标包是否在前台。若最高分并列则
        拒绝自动选择，避免把输入发到另一台
        模拟器；调用方可以让用户在连接页手动确认。
        """
        已解析路径 = cls.解析ADB路径(adb路径, 自动检测=自动检测路径)
        设备列表 = cls.扫描设备(
            已解析路径,
            runner=runner,
            自动检测路径=False,
        )
        候选 = [
            设备 for 设备 in 设备列表
            if 设备.状态 == "device" and not 设备.疑似实体设备
        ]
        if not 候选:
            可用 = "、".join(设备.显示文本 for 设备 in 设备列表) or "无"
            raise ADB错误(
                f"没有可自动绑定的模拟器；当前 ADB 设备：{可用}。"
                "请在连接页确认模拟器已启动并开启 ADB 调试。"
            )

        def 解码(值) -> str:
            if isinstance(值, bytes):
                return 值.decode("utf-8", errors="replace")
            return str(值 or "")

        评分结果 = []
        for 设备 in 候选:
            适配器 = cls(
                已解析路径,
                设备.序列号,
                runner=runner,
                自动检测路径=False,
            )
            try:
                已安装 = 包名 in 解码(
                    适配器.执行(
                        ["shell", "pm", "list", "packages", 包名],
                        timeout=5,
                    )
                )
                前台文本 = 解码(
                    适配器.执行(
                        ["shell", "dumpsys", "activity", "activities"],
                        timeout=5,
                    )
                )
            except (ADB错误, OSError, subprocess.TimeoutExpired):
                continue
            当前前台 = cls._前台是否为包名(前台文本, 包名)
            评分 = (100 if 当前前台 else 0) + (10 if 已安装 else 0)
            # MuMu 有时会同时把同一实例暴露为网络 serial 和
            # emulator-* serial。读取 guest 唯一标识后再去重，避免同一
            # 台模拟器的两个别名被错误当成“两台设备”而拒绝启动。
            身份输出 = 解码(
                适配器.执行(["shell", "getprop", "ro.serialno"], timeout=5)
            ).strip().splitlines()
            身份 = 身份输出[0].strip() if 身份输出 else ""
            if not 身份 or 身份.startswith("package:") or 身份 in {"unknown", "null"}:
                # MuMu Android 15 的 ro.serialno 可能为空；android_id
                # 仍能稳定标识同一 guest，用于合并网络 serial 与
                # emulator-* serial 两个 ADB 别名。
                身份输出 = 解码(
                    适配器.执行(
                        ["shell", "settings", "get", "secure", "android_id"],
                        timeout=5,
                    )
                ).strip().splitlines()
                身份 = 身份输出[0].strip() if 身份输出 else ""
            if not 身份 or 身份.startswith("package:") or 身份 in {"unknown", "null"}:
                身份 = ""
            评分结果.append((评分, 设备, 身份))

        if not 评分结果:
            raise ADB错误(
                f"无法在候选模拟器上确认游戏包 {包名}；"
                "请在连接页手动扫描并选择设备。"
            )
        去重结果: dict[str, tuple[int, ADB设备信息]] = {}
        for 分数, 设备, 身份 in 评分结果:
            分组键 = f"identity:{身份}" if 身份 else f"serial:{设备.序列号}"
            现有 = 去重结果.get(分组键)
            if 现有 is None:
                去重结果[分组键] = (分数, 设备)
                continue
            现有分数, 现有设备 = 现有
            def 序列号优先级(序列号: str) -> int:
                if re.fullmatch(r"(?:127\.0\.0\.1|localhost):\d+", 序列号):
                    try:
                        端口 = int(序列号.rsplit(":", 1)[1])
                    except (ValueError, IndexError):
                        端口 = -1
                    if 16384 <= 端口 <= 16499:
                        return 2
                if re.fullmatch(r"emulator-\d+", 序列号.lower()):
                    return 1
                return 0
            if (
                分数 > 现有分数
                or (
                    分数 == 现有分数
                    and 序列号优先级(设备.序列号) > 序列号优先级(现有设备.序列号)
                )
            ):
                去重结果[分组键] = (分数, 设备)

        评分结果 = list(去重结果.values())
        评分结果.sort(key=lambda 项: 项[0], reverse=True)
        最高分 = 评分结果[0][0]
        最佳 = [设备 for 分数, 设备 in 评分结果 if 分数 == 最高分]
        if len(最佳) != 1 or 最高分 <= 0:
            并列 = "、".join(设备.显示文本 for 设备 in 最佳)
            raise ADB错误(
                f"自动检测到多个可能的 CoC 模拟器，无法安全选择：{并列}。"
                "请在连接页手动选择并确认目标。"
            )
        return 最佳[0]

    @staticmethod
    def _前台是否为包名(窗口状态文本: str, 包名: str) -> bool:
        """只按当前焦点字段判断前台应用，不扫描整个 dumpsys 历史。"""
        包名 = str(包名 or "").strip()
        if not 包名:
            return False
        # dumpsys activity/window 会同时列出后台任务栈、最近任务和历史
        # Activity。仅在当前焦点字段中匹配，避免“后台曾打开过 CoC”把
        # 模拟器错误打成前台候选。
        当前字段 = re.compile(
            r"(?:mCurrentFocus|mFocusedApp|mResumedActivity|ResumedActivity)\s*[:=].*"
        )
        return any(
            包名 in 行 and 当前字段.search(行)
            for 行 in str(窗口状态文本 or "").splitlines()
        )

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
        # 每次重新确认都从当前 ADB 列表开始，不能沿用上一次成功的
        # transport 状态；模拟器重启后旧 serial 可能已经失效。
        self._标记目标未验证()
        设备列表 = self.扫描设备(
            self.adb路径,
            runner=self._runner,
            自动检测路径=self.自动检测路径,
        )
        当前设备 = next((设备 for 设备 in 设备列表 if 设备.序列号 == self.设备序列号), None)
        if 当前设备 is None:
            # 只有完全没有设备时才重置 adb server。若列表中已有其他设备，
            # 说明当前 serial 已失效；重置 server 会无谓断开仍在线的 MuMu
            # 或其他设备，必须直接报告并禁止误切换。
            if not 设备列表:
                self._重置ADB服务()
                self._连接已保存网络设备()
                设备列表 = self.扫描设备(
                    self.adb路径,
                    runner=self._runner,
                    自动检测路径=self.自动检测路径,
                )
                当前设备 = next((设备 for 设备 in 设备列表 if 设备.序列号 == self.设备序列号), None)
            elif re.fullmatch(r"(?:127\.0\.0\.1|localhost):\d+", self.设备序列号):
                # 已有其他设备在线时，网络 MuMu 只尝试连接保存的本机地址，
                # 不重启共享的 adb server。
                self._连接已保存网络设备()
                设备列表 = self.扫描设备(
                    self.adb路径,
                    runner=self._runner,
                    自动检测路径=self.自动检测路径,
                )
                当前设备 = next((设备 for 设备 in 设备列表 if 设备.序列号 == self.设备序列号), None)
        if (
            当前设备 is None
            and self.自动检测路径
            and self._目标包名
        ):
            # 模拟器重启、版本升级或端口转发变化后，MuMu 可能把同一台
            # 实例重新登记成 emulator-5556 等 serial。只有在包名/前台
            # 评分能够唯一选出一台模拟器时才自动切换，绝不按列表第一项
            # 猜测，也不触碰实体 Android 设备。
            try:
                新设备 = self.自动选择游戏设备(
                    self.adb路径,
                    self._目标包名,
                    runner=self._runner,
                    自动检测路径=False,
                )
            except (ADB错误, OSError, subprocess.TimeoutExpired):
                新设备 = None
            if 新设备 is not None:
                self.设备序列号 = 新设备.序列号
                self._最近有效截图显示ID = None
                self._最近有效截图显示ID时间 = 0.0
                self._最近有效输入显示ID = None
                self._最近有效输入显示ID时间 = 0.0
                锁键 = (os.path.normcase(os.path.abspath(self.adb路径)), self.设备序列号)
                with self._设备命令锁容器锁:
                    self._命令锁 = self._设备命令锁容器.setdefault(锁键, threading.RLock())
                当前设备 = 新设备
        if 当前设备 is None:
            可用设备 = "、".join(设备.显示文本 for 设备 in 设备列表) or "无"
            raise ADB错误(
                f"所选设备 {self.设备序列号} 未出现在当前 ADB 设备列表中；"
                f"当前可用设备：{可用设备}。请重新扫描并选择 MuMu 模拟器，"
                "程序不会把操作发送到其他设备。"
            )
        if 当前设备.状态 != "device":
            raise ADB错误(f"所选设备状态为“{当前设备.状态}”；请检查模拟器 ADB 调试授权。")
        if 当前设备.疑似实体设备:
            raise ADB错误(
                f"目标 {当前设备.序列号} 报告为实体 Android 设备（{当前设备.描述}），"
                "为避免触碰真实手机，已阻止截图和控制。请连接 MuMu、雷电或 BlueStacks 模拟器。"
            )
        self._目标已验证 = True
        return 当前设备

    def _标记目标未验证(self) -> None:
        """使下一次重试先重新扫描设备，避免复用掉线的旧 transport。"""
        self._目标已验证 = False
        self._屏幕尺寸 = None
        self._截图显示ID = None
        self._截图显示ID更新时间 = 0.0
        self._输入显示ID = None
        self._输入显示ID更新时间 = 0.0
        self._触摸事件设备 = None
        self._触摸事件原始尺寸 = None
        self._触摸事件更新时间 = 0.0

    def _验证目标(self) -> None:
        if not self._目标已验证:
            self.确认在线()

    def 设置目标包名(self, 包名: str) -> None:
        """绑定运行期输入目标；不执行启动、切换或关闭应用。"""
        self._目标包名 = str(包名 or "").strip()
        self._前台包名缓存 = ""
        self._前台包名缓存时间 = 0.0
        self._截图显示ID = None
        self._截图显示ID更新时间 = 0.0
        self._最近有效截图显示ID = None
        self._最近有效截图显示ID时间 = 0.0
        self._输入显示ID = None
        self._输入显示ID更新时间 = 0.0
        self._MuMu窗口状态缓存 = ""
        self._MuMu窗口状态缓存时间 = 0.0
        self._最近有效输入显示ID = None
        self._最近有效输入显示ID时间 = 0.0
        self._触摸事件设备 = None
        self._触摸事件原始尺寸 = None
        self._触摸事件更新时间 = 0.0

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

    @staticmethod
    def _解析MuMu物理显示ID(显示输出: str, 逻辑显示ID: str) -> str | None:
        """把 Android logical display 映射为 MuMu ``screencap -d`` 的 ID。

        Android 15 的 ``dumpsys display`` 格式和旧版不同：旧版通常有
        ``mPrimaryDisplayDevice=...(local:...)``，新版则把映射放在
        ``mViewports`` 的 ``DisplayViewport`` 中。两种格式都支持，避免
        在多显示 MuMu 中误截到启动器的主屏。
        """
        文本 = str(显示输出 or "")
        逻辑显示ID = str(逻辑显示ID or "").strip()
        if not 逻辑显示ID:
            return None

        # Android 15/MuMu 当前格式，例如：
        # DisplayViewport{..., displayId=6, uniqueId='local:4619827203584079877', ...}
        for 匹配 in re.finditer(r"DisplayViewport\{([^}]*)\}", 文本, flags=re.S):
            内容 = 匹配.group(1)
            逻辑匹配 = re.search(r"\bdisplayId\s*=\s*(\d+)", 内容)
            物理匹配 = re.search(r"\buniqueId\s*=\s*['\"]local:(\d+)", 内容)
            if 逻辑匹配 and 物理匹配 and 逻辑匹配.group(1) == 逻辑显示ID:
                return 物理匹配.group(1)

        # 兼容旧版 dumpsys display 输出。
        模式 = rf"mDisplayId={re.escape(逻辑显示ID)}\b.*?mPrimaryDisplayDevice=.*?\(local:(\d+)\)"
        匹配 = re.search(模式, 文本, flags=re.S)
        return 匹配.group(1) if 匹配 else None

    def _获取MuMu截图显示ID(self) -> str | None:
        """返回当前前台应用所在 MuMu 虚拟显示的 SurfaceFlinger ID。"""
        当前时间 = time.monotonic()
        # 已明确收到 ``Can't find service: display/window`` 时，不能因为
        # 最近一次缓存尚未过期而把截图发到失效层。
        if self._MuMu显示服务仍缺失():
            self._截图显示ID = None
            return None
        # 失败结果不能在3秒缓存；MuMu 战斗过渡时 dumpsys window/display
        # 可能短暂返回空内容，缓存 None 会让这一帧之后的所有截图都失败。
        if self._截图显示ID and 当前时间 - self._截图显示ID更新时间 < 3.0:
            return self._截图显示ID
        上次有效显示ID = self._截图显示ID or self._最近有效截图显示ID
        上次有效时间 = (
            self._截图显示ID更新时间
            if self._截图显示ID
            else self._最近有效截图显示ID时间
        )
        for 尝试次数 in range(3):
            self._截图显示ID更新时间 = time.monotonic()
            try:
                选中逻辑ID = self._获取MuMu输入显示ID()
                if 选中逻辑ID is None:
                    self._输入显示ID更新时间 = 0.0
                    raise ADB错误("暂未确认 CoC 的 MuMu 逻辑显示层")

                显示输出 = self.执行(["shell", "dumpsys", "display"], timeout=8)
                if isinstance(显示输出, bytes):
                    显示输出 = 显示输出.decode("utf-8", errors="replace")
                if self._是MuMu显示服务缺失错误(显示输出):
                    raise ADB错误(str(显示输出).strip())
                self._MuMu显示服务缺失时间 = 0.0
                物理ID = self._解析MuMu物理显示ID(str(显示输出), 选中逻辑ID)
                if 物理ID:
                    self._截图显示ID = 物理ID
                    self._最近有效截图显示ID = 物理ID
                    self._最近有效截图显示ID时间 = time.monotonic()
                    return 物理ID
                raise ADB错误(f"MuMu display {选中逻辑ID} 暂无可用物理显示层")
            except (ADB错误, ValueError, TypeError, re.error) as 异常:
                # 仅截图允许短暂沿用上一次已确认的物理 display；它不参与
                # input 坐标。这样窗口 dumpsys 抖动不会把战斗流程直接打死，
                # 但新建连接/长期失效时仍然 fail-closed，不回退到 display 0。
                self._截图显示ID = 上次有效显示ID
                self._输入显示ID更新时间 = 0.0
                if self._是MuMu显示服务缺失错误(异常):
                    self._MuMu显示服务缺失时间 = time.monotonic()
                    self._最近有效截图显示ID = None
                    self._最近有效截图显示ID时间 = 0.0
                if self._MuMu显示服务仍缺失():
                    self._最近有效截图显示ID = None
                    self._最近有效截图显示ID时间 = 0.0
                    break
                if 尝试次数 < 2:
                    time.sleep(0.12 * (尝试次数 + 1))
        if self._MuMu显示服务仍缺失():
            self._截图显示ID = None
            return None
        if (
            上次有效显示ID
            and 上次有效时间
            and time.monotonic() - 上次有效时间 <= self._显示层缓存有效秒数
        ):
            self._截图显示ID = 上次有效显示ID
            self._截图显示ID更新时间 = 上次有效时间
            return 上次有效显示ID
        self._截图显示ID = None
        return None

    @staticmethod
    def _解析MuMu逻辑显示ID(窗口输出: str, 目标包名: str = "") -> str | None:
        """从 MuMu 多显示窗口状态中选出目标应用所在的逻辑 display ID。"""
        目标包名 = str(目标包名 or "").strip()
        目标逻辑ID = None
        候选逻辑ID = []
        分块 = re.split(r"\n\s*Display:\s*mDisplayId=", "\n" + str(窗口输出 or ""))
        for 块 in 分块[1:]:
            匹配 = re.match(r"(\d+)", 块)
            if not 匹配:
                continue
            逻辑ID = 匹配.group(1)
            # 游戏 display 可能没有 mCurrentFocus，但 mFocusedApp 会指向
            # CoC；两者都不看会错误选中 MuMu 启动器 display 0。
            有窗口焦点 = bool(re.search(r"mCurrentFocus=(?!null\b)", 块))
            有应用焦点 = bool(re.search(r"mFocusedApp=(?!null\b)", 块))
            if 有窗口焦点 or 有应用焦点:
                候选逻辑ID.append(逻辑ID)
                if 目标包名 and 目标包名 in 块:
                    目标逻辑ID = 逻辑ID
        return 目标逻辑ID or (候选逻辑ID[-1] if 候选逻辑ID else None)

    def _获取MuMu输入显示ID(self) -> str | None:
        """返回 ``input -d`` 使用的逻辑 display ID。"""
        当前时间 = time.monotonic()
        if self._MuMu显示服务仍缺失():
            self._输入显示ID = None
            return None
        if self._输入显示ID and 当前时间 - self._输入显示ID更新时间 < 3.0:
            return self._输入显示ID
        self._输入显示ID更新时间 = 当前时间
        try:
            窗口输出 = self._获取MuMu窗口状态()
            if 窗口输出 is None:
                raise ADB错误("暂未取得 MuMu 窗口显示状态")
            if self._是MuMu显示服务缺失错误(窗口输出):
                raise ADB错误(str(窗口输出).strip())
            self._MuMu显示服务缺失时间 = 0.0
            self._输入显示ID = self._解析MuMu逻辑显示ID(窗口输出, self._目标包名)
            if self._输入显示ID:
                self._最近有效输入显示ID = self._输入显示ID
                self._最近有效输入显示ID时间 = time.monotonic()
                return self._输入显示ID
        except (ADB错误, ValueError, TypeError, re.error) as 异常:
            self._输入显示ID = None
            if self._是MuMu显示服务缺失错误(异常):
                self._MuMu显示服务缺失时间 = time.monotonic()
                self._最近有效输入显示ID = None
                self._最近有效输入显示ID时间 = 0.0
        # MuMu 转场时窗口焦点字段可能暂时为空。输入路径仍会通过
        # _验证输入前台 检查目标包名，因此在短时窗口内复用最近映射不
        # 会把触控发送到启动器；超过窗口则继续 fail-closed。
        if (
            self._最近有效输入显示ID
            and self._最近有效输入显示ID时间
            and 当前时间 - self._最近有效输入显示ID时间 <= self._显示层缓存有效秒数
        ):
            self._输入显示ID = self._最近有效输入显示ID
            self._输入显示ID更新时间 = self._最近有效输入显示ID时间
            return self._输入显示ID
        return None

    @staticmethod
    def _是MuMu显示服务缺失错误(异常: BaseException) -> bool:
        """判断 dumpsys 明确报告 Android display/window 服务不存在。"""
        文本 = str(异常 or "").lower()
        return "can't find service: display" in 文本 or "can't find service: window" in 文本

    def _MuMu显示服务仍缺失(self) -> bool:
        时间 = float(getattr(self, "_MuMu显示服务缺失时间", 0.0) or 0.0)
        return bool(
            时间
            and time.monotonic() - 时间 < float(self._MuMu显示服务缺失冷却秒数)
        )

    def 获取目标显示ID(self) -> str | None:
        """返回当前 CoC 输入/点击使用的逻辑 display ID，供状态日志使用。"""
        if not self._是MuMu连接():
            return None
        return self._获取MuMu输入显示ID()

    def _输入显示参数(self) -> list[str]:
        """生成 ``input`` 的 display 参数；非 MuMu 保持系统默认行为。"""
        if not self._是MuMu连接():
            return []
        显示ID = self._获取MuMu输入显示ID()
        if not 显示ID:
            raise ADB错误(
                "未确认 CoC 所在的 MuMu 输入显示层，已拒绝发送无 display 输入。"
            )
        return ["-d", 显示ID]

    @staticmethod
    def _解析MuMu触摸事件设备(输入状态: str, 逻辑显示ID: str) -> str | None:
        """从 ``dumpsys input`` 找到指定 MuMu display 对应的触摸 event。"""
        文本 = str(输入状态 or "")
        逻辑显示ID = str(逻辑显示ID or "").strip()
        if not 文本 or not 逻辑显示ID:
            return None

        # Event Hub State 先给出 hub id 到 /dev/input/eventN 的映射。
        hub到路径: dict[str, str] = {}
        行列表 = 文本.splitlines()
        for 索引, 行 in enumerate(行列表):
            匹配 = re.match(r"^\s*(\d+):\s+Xiaomi Touchscreen\s*$", 行)
            if not 匹配:
                continue
            for 后续 in 行列表[索引 + 1:索引 + 12]:
                路径匹配 = re.match(r"^\s*Path:\s+(/dev/input/event\d+)\s*$", 后续)
                if 路径匹配:
                    hub到路径[匹配.group(1)] = 路径匹配.group(1)
                    break

        # Input Reader State 把 hub id 和逻辑 display 关联起来。
        设备块列表 = re.finditer(
            r"(?ms)^\s*Device\s+\d+:\s+Xiaomi Touchscreen.*?"
            r"(?=^\s*Device\s+\d+:|\Z)",
            文本,
        )
        for 设备块 in 设备块列表:
            内容 = 设备块.group(0)
            显示匹配 = re.search(
                r"Viewport INTERNAL:\s*displayId=(\d+)", 内容
            )
            hub匹配 = re.search(
                r"EventHub Devices:\s*\[\s*(\d+)\s*\]", 内容
            )
            if (
                显示匹配
                and hub匹配
                and 显示匹配.group(1) == 逻辑显示ID
                and hub匹配.group(1) in hub到路径
            ):
                return hub到路径[hub匹配.group(1)]
        return None

    def _获取MuMu触摸事件设备(self) -> tuple[str, int, int] | None:
        """返回 CoC display 对应的触摸设备和原始轴尺寸。"""
        当前时间 = time.monotonic()
        if (
            self._触摸事件设备
            and self._触摸事件原始尺寸
            and 当前时间 - self._触摸事件更新时间 < 30.0
        ):
            return (
                self._触摸事件设备,
                self._触摸事件原始尺寸[0],
                self._触摸事件原始尺寸[1],
            )
        try:
            逻辑显示ID = self._获取MuMu输入显示ID()
            if not 逻辑显示ID:
                return None
            输入状态 = self.执行(["shell", "dumpsys", "input"], timeout=10)
            if isinstance(输入状态, bytes):
                输入状态 = 输入状态.decode("utf-8", errors="replace")
            事件设备 = self._解析MuMu触摸事件设备(str(输入状态), 逻辑显示ID)
            if not 事件设备:
                return None
            轴状态 = self.执行(["shell", "getevent", "-lp", 事件设备], timeout=8)
            if isinstance(轴状态, bytes):
                轴状态 = 轴状态.decode("utf-8", errors="replace")
            x匹配 = re.search(
                r"ABS_MT_POSITION_X\s*:.*?\bmax\s+(\d+)", str(轴状态)
            )
            y匹配 = re.search(
                r"ABS_MT_POSITION_Y\s*:.*?\bmax\s+(\d+)", str(轴状态)
            )
            if not x匹配 or not y匹配:
                return None
            原始尺寸 = (int(x匹配.group(1)), int(y匹配.group(1)))
            if 原始尺寸[0] <= 0 or 原始尺寸[1] <= 0:
                return None
            self._触摸事件设备 = 事件设备
            self._触摸事件原始尺寸 = 原始尺寸
            self._触摸事件更新时间 = 当前时间
            return 事件设备, 原始尺寸[0], 原始尺寸[1]
        except (ADB错误, ValueError, TypeError, re.error):
            return None

    @staticmethod
    def _生成MuMu缩放脚本(
            事件设备: str,
            原始宽度: int,
            原始高度: int,
            屏幕宽度: int,
            屏幕高度: int,
            次数: int,
    ) -> str:
        """生成 MuMu 触摸屏 protocol-B 的双指向内手势。"""
        # CoC 在模拟器中使用双指捏合缩小视野；MuMu 的触摸轴通常是
        # 720×1280 竖向，而游戏 display 是 1280×720 横向，需要按
        # Rotation270 做坐标转换。非该布局时退回线性缩放。
        def 转原始坐标(x: float, y: float) -> tuple[int, int]:
            if 原始宽度 == 屏幕高度 and 原始高度 == 屏幕宽度:
                原始x = 原始宽度 - round(y * 原始宽度 / max(1, 屏幕高度))
                原始y = round(x * 原始高度 / max(1, 屏幕宽度))
            else:
                原始x = round(x * 原始宽度 / max(1, 屏幕宽度))
                原始y = round(y * 原始高度 / max(1, 屏幕高度))
            return (
                max(0, min(原始宽度, 原始x)),
                max(0, min(原始高度, 原始y)),
            )

        def 事件(类型: int, 代码: int, 值: int):
            命令列表.append(f"sendevent {事件设备} {类型} {代码} {值}")

        def 同步():
            命令列表.append(f"sendevent {事件设备} 0 0 0")

        命令列表: list[str] = []
        中心x, 中心y = 屏幕宽度 / 2, 屏幕高度 / 2
        # 起点较远、终点靠近中心，保证一次手势就能明显拉远。
        起点1 = 转原始坐标(中心x - 屏幕宽度 * 0.15, 中心y - 屏幕高度 * 0.15)
        起点2 = 转原始坐标(中心x + 屏幕宽度 * 0.15, 中心y + 屏幕高度 * 0.15)
        终点1 = 转原始坐标(中心x - 屏幕宽度 * 0.055, 中心y - 屏幕高度 * 0.055)
        终点2 = 转原始坐标(中心x + 屏幕宽度 * 0.055, 中心y + 屏幕高度 * 0.055)
        步数 = 16
        手势次数 = max(1, min(3, int(次数)))

        for 手势序号 in range(手势次数):
            追踪ID1, 追踪ID2 = 100 + 手势序号 * 2, 101 + 手势序号 * 2
            事件(1, 330, 1)  # BTN_TOUCH down
            事件(1, 325, 1)  # BTN_TOOL_FINGER down
            事件(3, 47, 0)  # ABS_MT_SLOT 0
            事件(3, 57, 追踪ID1)
            事件(3, 53, 起点1[0])
            事件(3, 54, 起点1[1])
            事件(3, 47, 1)  # ABS_MT_SLOT 1
            事件(3, 57, 追踪ID2)
            事件(3, 53, 起点2[0])
            事件(3, 54, 起点2[1])
            同步()

            for 步 in range(1, 步数 + 1):
                比例 = 步 / 步数
                点1 = (
                    round(起点1[0] + (终点1[0] - 起点1[0]) * 比例),
                    round(起点1[1] + (终点1[1] - 起点1[1]) * 比例),
                )
                点2 = (
                    round(起点2[0] + (终点2[0] - 起点2[0]) * 比例),
                    round(起点2[1] + (终点2[1] - 起点2[1]) * 比例),
                )
                事件(3, 47, 0)
                事件(3, 53, 点1[0])
                事件(3, 54, 点1[1])
                事件(3, 47, 1)
                事件(3, 53, 点2[0])
                事件(3, 54, 点2[1])
                同步()
                命令列表.append("sleep 0.02")

            事件(3, 47, 0)
            事件(3, 57, -1)
            事件(3, 47, 1)
            事件(3, 57, -1)
            事件(1, 325, 0)
            事件(1, 330, 0)
            同步()
            if 手势序号 + 1 < 手势次数:
                命令列表.append("sleep 0.08")
        return "; ".join(命令列表)

    @staticmethod
    def _MuMu原始触摸坐标(
            x: float,
            y: float,
            屏幕宽度: int,
            屏幕高度: int,
            原始宽度: int,
            原始高度: int,
    ) -> tuple[int, int]:
        """把 CoC 画布坐标转换为 MuMu 触摸 event 的原始坐标。

        MuMu 当前多显示实例的截图是横向 1280×720，但 Xiaomi
        Touchscreen event 仍报告为旋转后的 720×1280。直接执行
        ``input -d`` 在这类 organized display 上不会把触摸送进游戏；
        这里沿用拉远视距已经验证过的 protocol-B 坐标变换。
        """
        if 原始宽度 == 屏幕高度 and 原始高度 == 屏幕宽度:
            原始x = 原始宽度 - round(float(y) * 原始宽度 / max(1, 屏幕高度))
            原始y = round(float(x) * 原始高度 / max(1, 屏幕宽度))
        else:
            原始x = round(float(x) * 原始宽度 / max(1, 屏幕宽度))
            原始y = round(float(y) * 原始高度 / max(1, 屏幕高度))
        return (
            max(0, min(原始宽度, 原始x)),
            max(0, min(原始高度, 原始y)),
        )

    @staticmethod
    def _生成MuMu单指触控脚本(
            事件设备: str,
            原始宽度: int,
            原始高度: int,
            屏幕宽度: int,
            屏幕高度: int,
            点位: Iterable[tuple[int, int]],
            间隔毫秒: int = 0,
            长按毫秒: int = 0,
    ) -> str:
        """生成 MuMu display 专属的单指点击/长按脚本。"""
        坐标列表 = [
            ADB设备操作类._MuMu原始触摸坐标(
                x, y, 屏幕宽度, 屏幕高度, 原始宽度, 原始高度
            )
            for x, y in 点位
        ]
        命令列表: list[str] = []
        间隔毫秒 = max(0, min(80, int(间隔毫秒)))
        if len(坐标列表) > 1:
            间隔毫秒 = max(40, 间隔毫秒)
        长按毫秒 = max(0, min(1500, int(长按毫秒)))

        for 序号, (x, y) in enumerate(坐标列表):
            追踪ID = 100 + 序号
            命令列表.extend([
                f"sendevent {事件设备} 1 330 1",
                f"sendevent {事件设备} 1 325 1",
                f"sendevent {事件设备} 3 47 0",
                f"sendevent {事件设备} 3 57 {追踪ID}",
                f"sendevent {事件设备} 3 53 {x}",
                f"sendevent {事件设备} 3 54 {y}",
                f"sendevent {事件设备} 0 0 0",
            ])
            if 长按毫秒:
                命令列表.append(f"sleep {长按毫秒 / 1000:.3f}")
            命令列表.extend([
                f"sendevent {事件设备} 3 57 -1",
                f"sendevent {事件设备} 1 325 0",
                f"sendevent {事件设备} 1 330 0",
                f"sendevent {事件设备} 0 0 0",
            ])
            if 序号 + 1 < len(坐标列表) and 间隔毫秒:
                命令列表.append(f"sleep {间隔毫秒 / 1000:.3f}")
        return "; ".join(命令列表)

    @staticmethod
    def _生成MuMu滑动脚本(
            事件设备: str,
            原始宽度: int,
            原始高度: int,
            屏幕宽度: int,
            屏幕高度: int,
            起点: tuple[int, int],
            终点: tuple[int, int],
            时长毫秒: int,
    ) -> str:
        """生成 MuMu display 专属的一指滑动脚本。"""
        步数 = max(4, min(16, round(max(1, int(时长毫秒)) / 35)))
        点位 = []
        for 序号 in range(步数 + 1):
            比例 = 序号 / 步数
            点位.append((
                round(起点[0] + (终点[0] - 起点[0]) * 比例),
                round(起点[1] + (终点[1] - 起点[1]) * 比例),
            ))
        命令列表: list[str] = []
        原始点位 = [
            ADB设备操作类._MuMu原始触摸坐标(
                x, y, 屏幕宽度, 屏幕高度, 原始宽度, 原始高度
            )
            for x, y in 点位
        ]
        起始x, 起始y = 原始点位[0]
        命令列表.extend([
            f"sendevent {事件设备} 1 330 1",
            f"sendevent {事件设备} 1 325 1",
            f"sendevent {事件设备} 3 47 0",
            f"sendevent {事件设备} 3 57 100",
            f"sendevent {事件设备} 3 53 {起始x}",
            f"sendevent {事件设备} 3 54 {起始y}",
            f"sendevent {事件设备} 0 0 0",
        ])
        每步毫秒 = max(8, min(80, int(max(1, int(时长毫秒)) / 步数)))
        for x, y in 原始点位[1:]:
            命令列表.extend([
                f"sendevent {事件设备} 3 53 {x}",
                f"sendevent {事件设备} 3 54 {y}",
                f"sendevent {事件设备} 0 0 0",
                f"sleep {每步毫秒 / 1000:.3f}",
            ])
        命令列表.extend([
            f"sendevent {事件设备} 3 57 -1",
            f"sendevent {事件设备} 1 325 0",
            f"sendevent {事件设备} 1 330 0",
            f"sendevent {事件设备} 0 0 0",
        ])
        return "; ".join(命令列表)

    def _执行MuMu触控脚本(self, 脚本: str, timeout: float = 8) -> None:
        """执行已通过前台校验的 MuMu display 专属触摸脚本。"""
        if not 脚本:
            return
        self.执行(["shell", "sh", "-c", 脚本], timeout=timeout)

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
            if 尝试次数 > 0 and not self._目标已验证:
                self.确认在线()
            # 内存保护必须在每一次重试前重新检查；不能为了等待模拟器
            # 恢复而绕过宿主机保护。
            self._检查主机内存预算()
            try:
                截图参数 = ["exec-out", "screencap"]
                if self._是MuMu连接():
                    显示ID = self._获取MuMu截图显示ID()
                    # MuMu 可能同时存在启动器 display 0 和 CoC 游戏 display。
                    # 解析不到游戏 display 时不能退回默认截图：默认层可能是
                    # 模拟器桌面，后续页面识别会把桌面当成未知/过渡页，造成
                    # 任务状态机误判。输入路径本来就会拒绝无 display 的操作，
                    # 截图也必须同样 fail-closed，等待下一次在线复核。
                    if not 显示ID:
                        raise ADB错误(
                            "未确认 CoC 所在的 MuMu 游戏显示层，已拒绝使用默认 display 截图"
                        )
                    截图参数.extend(["-d", 显示ID])
                截图参数.append("-p")
                原始PNG = self.执行(截图参数, timeout=15, binary=True)
                if len(原始PNG) > 20 * 1024 * 1024:
                    raise ADB错误("ADB 截图数据异常过大，已拒绝继续解码以保护内存。")
                if not 原始PNG:
                    raise ADB错误(
                        "ADB 截图返回空数据；设备可能刚刚断开，已停止解码并准备重新验证。"
                    )
                # MuMu Android 15 的 adb.exe 在 exec-out 输出 PNG 前会把
                # “Multiple displays were found...” 警告写到 stdout，导致
                # OpenCV 无法解码。只丢弃 PNG 签名以前的这段诊断文本，
                # 不放宽大小限制，也不吞掉真正的空响应。
                PNG签名 = b"\x89PNG\r\n\x1a\n"
                PNG起点 = 原始PNG.find(PNG签名)
                if PNG起点 < 0:
                    raise ADB错误("ADB 截图返回的内容不是有效 PNG，已停止解码并准备重试。")
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

            # MuMu 已明确报告 display/window 服务不存在时，继续 reconnect
            # 或重复 screencap 没有恢复意义，只会制造更多 adb 进程。
            if self._MuMu显示服务仍缺失():
                break
            if 尝试次数 + 1 < self._截图重试上限:
                self._标记目标未验证()
                # 参考 MAA 的“重新连接后重试原命令”语义，但等待和次数
                # 受控；不会重启模拟器、结束游戏或切换 Android 前台。
                self._尝试恢复ADB连接()
                time.sleep(0.35 * (尝试次数 + 1))

        if 图像 is None:
            raise 最后错误 or ADB错误("ADB 截图失败。")
        高, 宽 = 图像.shape[:2]
        self._屏幕尺寸 = (宽, 高)
        # 2000×2000 是上层“请求完整截图”的兼容哨兵，而不是裁剪上限。
        # screencap 已经返回了完整 PNG；设备超过 2000 像素时必须保留整张，
        # 否则后续自适应映射会丢失右侧画面。
        if int(左边) == 0 and int(顶边) == 0 and int(右边) >= 2000 and int(底边) >= 2000:
            return 图像.copy()
        # 任务坐标统一使用 800×600 参考画布。点击路径已经通过
        # ``参考坐标转设备坐标`` 映射到真实分辨率；截图也必须走同一套
        # 映射，否则在 MuMu 的 1280×720 画面上请求 (0,0,800,600)
        # 会只裁出左上角 800×600，右侧攻击按钮/资源栏直接消失。
        # 裁剪后缩放回请求区域尺寸，让模板和几何阈值继续使用参考坐标。
        原始左, 原始上 = int(左边), int(顶边)
        原始右, 原始下 = int(右边), int(底边)
        请求宽度 = 原始右 - 原始左
        请求高度 = 原始下 - 原始上
        if 请求宽度 <= 0 or 请求高度 <= 0:
            raise ADB错误(f"截图区域超出设备屏幕 {宽}×{高}：{左边},{顶边},{右边},{底边}")
        参考宽度 = max(1, int(self.参考宽度))
        参考高度 = max(1, int(self.参考高度))
        左边 = round(原始左 * 宽 / 参考宽度)
        顶边 = round(原始上 * 高 / 参考高度)
        右边 = round(原始右 * 宽 / 参考宽度)
        底边 = round(原始下 * 高 / 参考高度)
        左边, 顶边 = max(0, min(宽, 左边)), max(0, min(高, 顶边))
        右边, 底边 = max(左边, min(宽, 右边)), max(顶边, min(高, 底边))
        if 右边 <= 左边 or 底边 <= 顶边:
            raise ADB错误(
                f"截图参考区域超出设备屏幕 {宽}×{高}："
                f"{原始左},{原始上},{原始右},{原始下}"
            )
        裁剪 = 图像[顶边:底边, 左边:右边]
        if 裁剪.shape[1] == 请求宽度 and 裁剪.shape[0] == 请求高度:
            return 裁剪.copy()
        return cv2.resize(
            裁剪,
            (请求宽度, 请求高度),
            interpolation=cv2.INTER_AREA,
        )

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
        """把任务参考坐标映射到实际 ADB 屏幕；实际尺寸由截图自动更新。"""
        宽度, 高度 = self.取屏幕尺寸()
        设备x = round(float(x) * 宽度 / self.参考宽度)
        设备y = round(float(y) * 高度 / self.参考高度)
        return max(0, min(宽度 - 1, 设备x)), max(0, min(高度 - 1, 设备y))

    def 触控(self, x: int, y: int) -> bool:
        self._验证目标()
        self._验证输入前台()
        if self._是MuMu连接():
            事件设备, 原始宽度, 原始高度 = self._获取MuMu触摸事件设备() or (None, 0, 0)
            if not 事件设备:
                raise ADB错误(
                    "无法定位 CoC display 对应的 MuMu 触摸设备；"
                    "已拒绝发送无 display 目标的点击输入。"
                )
            屏幕宽度, 屏幕高度 = self.取屏幕尺寸()
            设备x, 设备y = self.参考坐标转设备坐标(x, y)
            脚本 = self._生成MuMu单指触控脚本(
                事件设备, 原始宽度, 原始高度, 屏幕宽度, 屏幕高度,
                [(设备x, 设备y)]
            )
            self._执行MuMu触控脚本(脚本)
            return True
        x, y = self.参考坐标转设备坐标(x, y)
        self.执行(["shell", "input", *self._输入显示参数(), "tap", str(x), str(y)], timeout=8)
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
        if self._是MuMu连接():
            事件信息 = self._获取MuMu触摸事件设备()
            if not 事件信息:
                raise ADB错误(
                    "无法定位 CoC display 对应的 MuMu 触摸设备；"
                    "已拒绝发送无 display 目标的连续点击输入。"
                )
            事件设备, 原始宽度, 原始高度 = 事件信息
            屏幕宽度, 屏幕高度 = self.取屏幕尺寸()
            设备点位 = [self.参考坐标转设备坐标(x, y) for x, y in 点位]
            脚本 = self._生成MuMu单指触控脚本(
                事件设备, 原始宽度, 原始高度, 屏幕宽度, 屏幕高度,
                设备点位, 间隔毫秒=间隔毫秒,
            )
            self._执行MuMu触控脚本(
                脚本, timeout=max(8, len(点位) * 2)
            )
            return True
        点位 = [self.参考坐标转设备坐标(x, y) for x, y in 点位]
        间隔命令 = f"; sleep {间隔毫秒 / 1000:.3f}" if 间隔毫秒 else ""
        显示参数 = " ".join(self._输入显示参数())
        输入前缀 = f"input {显示参数} " if 显示参数 else "input "
        脚本 = "; ".join(
            f"{输入前缀}tap {x} {y}{间隔命令 if 序号 < len(点位) - 1 else ''}"
            for 序号, (x, y) in enumerate(点位)
        )
        self.执行(["shell", "sh", "-c", 脚本], timeout=max(8, len(点位) * 2))
        return True

    def 长按触控(self, x: int, y: int, 时长毫秒: int = 220) -> bool:
        """通过同点 swipe 发送一次短长按，供游戏的按住连续部署手势使用。"""
        self._验证目标()
        self._验证输入前台()
        时长毫秒 = max(120, min(1500, int(时长毫秒)))
        if self._是MuMu连接():
            事件信息 = self._获取MuMu触摸事件设备()
            if not 事件信息:
                raise ADB错误(
                    "无法定位 CoC display 对应的 MuMu 触摸设备；"
                    "已拒绝发送无 display 目标的长按输入。"
                )
            事件设备, 原始宽度, 原始高度 = 事件信息
            屏幕宽度, 屏幕高度 = self.取屏幕尺寸()
            设备x, 设备y = self.参考坐标转设备坐标(x, y)
            脚本 = self._生成MuMu单指触控脚本(
                事件设备, 原始宽度, 原始高度, 屏幕宽度, 屏幕高度,
                [(设备x, 设备y)], 长按毫秒=时长毫秒,
            )
            self._执行MuMu触控脚本(脚本, timeout=max(8, 时长毫秒 / 1000 + 5))
            return True
        x, y = self.参考坐标转设备坐标(x, y)
        self.执行([
            "shell", "input", *self._输入显示参数(), "swipe", str(int(x)), str(int(y)),
            str(int(x)), str(int(y)), str(时长毫秒),
        ], timeout=max(8, 时长毫秒 / 1000 + 5))
        return True

    def 滑动(self, 起点: tuple[int, int], 终点: tuple[int, int], 时长毫秒: int = 350) -> bool:
        self._验证目标()
        self._验证输入前台()
        if self._是MuMu连接():
            # MuMu organized display 的 Xiaomi Touchscreen event 轴是旋转
            # 后的 720×1280。旧的 protocol-B sendevent 坐标变换在实机上
            # 会把地图拖动投到左下 HUD，实际打开军队/星级页面；点击和
            # 双指缩放仍使用各自已验证的专用路径，单指地图滑动改用
            # Android input display 坐标，和 screenshot 的 1280×720 方向
            # 一致，并由 ADB 子进程超时保护。
            起点 = self.参考坐标转设备坐标(*起点)
            终点 = self.参考坐标转设备坐标(*终点)
            self.执行([
                "shell", "input", *self._输入显示参数(), "swipe",
                str(int(起点[0])), str(int(起点[1])),
                str(int(终点[0])), str(int(终点[1])),
                str(max(1, int(时长毫秒))),
            ], timeout=10)
            return True
        起点 = self.参考坐标转设备坐标(*起点)
        终点 = self.参考坐标转设备坐标(*终点)
        self.执行(["shell", "input", *self._输入显示参数(), "swipe", str(起点[0]), str(起点[1]),
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
        self.执行(["shell", "input", *self._输入显示参数(), "keyevent", str(数字按键码)], timeout=8)
        return True

    def 获取属性(self, 属性名: str) -> str:
        输出 = self.执行(["shell", "getprop", 属性名], timeout=8)
        return 输出.decode("utf-8", errors="replace").strip() if isinstance(输出, bytes) else str(输出).strip()

    def 查询屏幕尺寸(self) -> tuple[int, int] | None:
        if self._是MuMu连接():
            # MuMu organized display 的 ``wm size`` 可能只返回竖向物理
            # 尺寸 720×1280，而 CoC 实际所在 display 的窗口已经是
            # 横向 1280×720。输入坐标必须跟当前逻辑 display 一致，优先
            # 读取 dumpsys window displays 的 ``cur=`` 尺寸。
            try:
                逻辑显示ID = self._获取MuMu输入显示ID()
                if 逻辑显示ID:
                    输出 = self.执行(["shell", "dumpsys", "window", "displays"], timeout=8)
                    if isinstance(输出, bytes):
                        输出 = 输出.decode("utf-8", errors="replace")
                    分块 = re.split(r"\n\s*Display:\s*mDisplayId=", "\n" + str(输出))
                    for 块 in 分块[1:]:
                        if not re.match(rf"{re.escape(逻辑显示ID)}\b", 块):
                            continue
                        匹配 = re.search(r"\bcur=(\d+)x(\d+)\b", 块)
                        if 匹配:
                            宽, 高 = map(int, 匹配.groups())
                            if 宽 > 0 and 高 > 0:
                                return 宽, 高
            except (ADB错误, ValueError, TypeError, re.error):
                pass
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
        # MuMu 多显示会同时返回 CoC 和启动器两条 topResumedActivity。
        # 仅扫描 activity 列表会把“游戏在另一层运行、启动器在当前焦点层”
        # 误判成已经前台，导致不切回游戏。先用窗口显示层的焦点确认；
        # 查询失败时才回退旧逻辑，兼容没有 window displays 的旧 Android。
        if self._是MuMu连接():
            MuMu前台 = self._获取MuMu焦点包名()
            if MuMu前台 is not None:
                if MuMu前台 == 包名:
                    return
            else:
                前台包名列表 = self._解析前台包名列表(当前前台)
                if 包名 in 前台包名列表:
                    return
        else:
            前台包名列表 = self._解析前台包名列表(当前前台)
            if 包名 in 前台包名列表:
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
        # 先保留 activity 查询，兼容没有 window displays 的旧 Android 和
        # 已有调用方；MuMu 再用窗口显示层焦点覆盖多显示历史任务误判。
        if self._是MuMu连接():
            MuMu前台 = self._获取MuMu焦点包名()
            if MuMu前台 is not None:
                return MuMu前台
        前台包名列表 = self._解析前台包名列表(当前前台)
        # 多显示下优先返回当前任务的目标包名，避免把 MuMu 启动器的
        # 辅助显示层当成真实前台，进而误拒绝 CoC 输入。
        if self._目标包名 and self._目标包名 in 前台包名列表:
            return self._目标包名
        return 前台包名列表[0] if 前台包名列表 else ""

    def _获取MuMu焦点包名(self) -> str | None:
        """按 MuMu 的显示层焦点读取当前应用包名。

        ``dumpsys activity activities`` 在多显示 MuMu 中会同时列出多个
        ``topResumedActivity``，其中可能包含隐藏游戏层和可见启动器层。
        ``dumpsys window displays`` 才包含每个 display 的
        ``mCurrentFocus``/``mFocusedApp``，因此这里优先使用它来避免把
        后台 CoC 当成当前前台。返回 ``None`` 表示查询格式/服务不可用，
        调用方可以安全回退旧 Android 逻辑。
        """
        try:
            输出 = self._获取MuMu窗口状态()
            if 输出 is None:
                return None
            return self._解析MuMu焦点包名(输出, self._目标包名)
        except (ADB错误, OSError, subprocess.TimeoutExpired):
            return None

    def _获取MuMu窗口状态(self) -> str | None:
        """读取并短暂缓存 MuMu ``dumpsys window displays`` 输出。"""
        当前时间 = time.monotonic()
        if (
            self._MuMu窗口状态缓存
            and 当前时间 - self._MuMu窗口状态缓存时间 <= 0.20
        ):
            return self._MuMu窗口状态缓存
        输出 = self.执行(["shell", "dumpsys", "window", "displays"], timeout=8)
        if isinstance(输出, bytes):
            输出 = 输出.decode("utf-8", errors="replace")
        self._MuMu窗口状态缓存 = str(输出)
        self._MuMu窗口状态缓存时间 = 当前时间
        return self._MuMu窗口状态缓存

    @staticmethod
    def _解析MuMu焦点包名(窗口输出: str, 目标包名: str = "") -> str | None:
        """从 MuMu 多显示窗口焦点中选出当前应用包名。

        目标包在任一显示层的 ``mCurrentFocus`` 优先；没有窗口焦点时，
        ``mFocusedApp`` 仍是 MuMu 游戏层的有效绑定证据。只有确认了至少
        一个 display 块，才返回非目标包；完全无法解析时返回 ``None``。
        """
        文本 = str(窗口输出 or "")
        目标包名 = str(目标包名 or "").strip()
        分块 = re.split(r"\n\s*Display:\s*mDisplayId=", "\n" + 文本)
        if len(分块) <= 1:
            return None

        当前焦点包名: list[str] = []
        应用焦点包名: list[str] = []

        def 提取包名(行: str) -> str:
            if "=null" in 行 or "= null" in 行:
                return ""
            匹配 = re.search(r"\bu\d+\s+([A-Za-z0-9_.$-]+)/", 行)
            return 匹配.group(1) if 匹配 else ""

        for 块 in 分块[1:]:
            for 行 in 块.splitlines():
                行 = 行.strip()
                if 行.startswith("mCurrentFocus="):
                    包名 = 提取包名(行)
                    if 包名 and 包名 not in 当前焦点包名:
                        当前焦点包名.append(包名)
                elif 行.startswith("mFocusedApp="):
                    包名 = 提取包名(行)
                    if 包名 and 包名 not in 应用焦点包名:
                        应用焦点包名.append(包名)

        if 目标包名 and 目标包名 in 当前焦点包名:
            return 目标包名
        if 目标包名 and 目标包名 in 应用焦点包名:
            return 目标包名
        if 当前焦点包名:
            return 当前焦点包名[0]
        if 应用焦点包名:
            return 应用焦点包名[0]
        return ""

    @staticmethod
    def _解析前台包名列表(文本: str) -> list[str]:
        """从多显示 dumpsys 输出中提取所有 resumed Activity 的包名。"""
        结果 = []
        for 行 in str(文本 or "").splitlines():
            if "mResumedActivity" not in 行 and "topResumedActivity" not in 行:
                continue
            # 兼容 ActivityRecord{... u0 package/activity ...}，并保留
            # 不带 uN 的旧 Android 输出格式。
            匹配 = re.search(r"(?:\bu\d+\s+)?([A-Za-z0-9_.$-]+)/", 行)
            if 匹配 and 匹配.group(1) not in 结果:
                结果.append(匹配.group(1))
        return 结果

    def 游戏内拉远视距(self, 次数: int = 5, 间隔毫秒: int = 180) -> bool:
        """向已确认在前台的 CoC 发送真实双指捏合以拉远视距。

        CoC 的缩放是多点触控手势，MuMu 的 ``input keyevent F5`` 虽然返回
        成功，但不会改变游戏画面。MuMu 多显示下先定位 CoC 对应的
        ``/dev/input/eventN``，再注入 protocol-B 双指事件；找不到明确的
        触摸设备时不发送任何猜测输入，避免误触启动器或其他显示层。
        """
        self._验证目标()
        次数 = max(1, min(3, int(次数)))

        if self._是MuMu连接():
            self._验证输入前台()
            触摸设备 = self._获取MuMu触摸事件设备()
            if not 触摸设备:
                raise ADB错误(
                    "无法定位 CoC display 对应的 MuMu 触摸设备；"
                    "已禁止发送无 display 目标的缩放输入。"
                )
            事件设备, 原始宽度, 原始高度 = 触摸设备
            屏幕宽度, 屏幕高度 = self.取屏幕尺寸()
            脚本 = self._生成MuMu缩放脚本(
                事件设备,
                原始宽度,
                原始高度,
                屏幕宽度,
                屏幕高度,
                次数,
            )
            self.执行(["shell", "sh", "-c", 脚本], timeout=max(15, 次数 * 15))
            return True

        # 非 MuMu 设备保留旧兼容路径；当前项目的 MuMu 会走上面的真实
        # 多点触控实现，不再把无效 F5 当成成功的拉远视距。
        间隔毫秒 = max(80, min(500, int(间隔毫秒)))
        for 序号 in range(次数):
            self._验证输入前台()
            self.执行(["shell", "input", "keyevent", "135"], timeout=8)
            if 序号 + 1 < 次数:
                time.sleep(间隔毫秒 / 1000)
        return True

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
