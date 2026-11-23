"""MAA 式模拟器一键检测：找到模拟器 → 用它自带的 adb → 连接端口 → 选中游戏所在实例。

检测流程（全部只读，除了 ``adb connect``）：

1. 从 Windows 卸载注册表和正在运行的进程里找到已安装的模拟器及安装目录；
2. 每种模拟器用自己安装目录里的 adb（不同 adb 版本混用容易互相踢掉）；
3. 收集候选地址：
   - MuMu：``MuMuManager.exe info -v all``（运行中实例的真实端口）
     + 每个实例 ``vms/*/configs/vm_config.json`` 里的 adb 转发端口
     + 默认端口 16384 + 32×n；
   - 蓝叠：``bluestacks.conf`` 里每个实例的 ``adb_port``；
   - 雷电 5555 + 2×n、夜神 62001/62025+、逍遥 21503 + 10×n；
4. 先用 0.3 秒 TCP 探测筛掉没监听的端口，再 ``adb connect``；
5. ``adb devices`` 后排除实体手机，逐台检查 CoC 是否安装、是否在前台；
6. 只有唯一最高分且分数 > 0 时才“推荐”，并列时交给用户选择。

本模块不启动、不关闭任何模拟器或应用，也不读写模拟器窗口。
"""
from __future__ import annotations

import concurrent.futures
import ctypes
import json
import os
import re
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from 模块.ADB设备操作类 import ADB设备操作类, ADB设备信息, ADB错误, 游戏设备评估

默认游戏包名 = "com.supercell.clashofclans"
本机 = "127.0.0.1"


# ======================================================================== 定义
@dataclass(frozen=True)
class 模拟器定义:
    名称: str
    进程名: tuple[str, ...]
    注册表关键字: tuple[str, ...]
    adb相对路径: tuple[str, ...]
    默认端口: tuple[int, ...]
    根目录标记: str = ""  # 安装根目录下一定存在的子目录，用于从进程路径回溯


模拟器定义列表: tuple[模拟器定义, ...] = (
    模拟器定义(
        "MuMu",
        ("MuMuNxDevice.exe", "MuMuPlayer.exe", "MuMuNxMain.exe", "MuMuVMMHeadless.exe", "NemuHeadless.exe"),
        ("MuMu",),
        ("nx_main/adb.exe", "shell/adb.exe", "nx_device/12.0/shell/adb.exe", "emulator/nemu/vmonitor/bin/adb_server.exe"),
        tuple(16384 + 32 * 序号 for 序号 in range(8)),
        根目录标记="vms",
    ),
    模拟器定义(
        "雷电",
        ("dnplayer.exe", "Ld9BoxHeadless.exe", "LdVBoxHeadless.exe", "LdBoxHeadless.exe"),
        ("LDPlayer", "雷电"),
        ("adb.exe",),
        tuple(5555 + 2 * 序号 for 序号 in range(4)),
    ),
    模拟器定义(
        "蓝叠",
        ("HD-Player.exe",),
        ("BlueStacks",),
        ("HD-Adb.exe",),
        (5555, 5565, 5575, 5585),
    ),
    模拟器定义(
        "夜神",
        ("Nox.exe", "NoxVMHandle.exe"),
        ("Nox", "夜神"),
        ("bin/nox_adb.exe", "bin/adb.exe", "nox_adb.exe"),
        (62001,) + tuple(62025 + 序号 for 序号 in range(4)),
    ),
    模拟器定义(
        "逍遥",
        ("MEmu.exe", "MEmuHeadless.exe"),
        ("MEmu", "逍遥"),
        ("adb.exe",),
        tuple(21503 + 10 * 序号 for 序号 in range(4)),
    ),
)
_按名称 = {项.名称: 项 for 项 in 模拟器定义列表}


@dataclass
class 模拟器安装:
    类型: str
    安装目录: Path
    adb路径: str | None = None
    运行中: bool = False


@dataclass(frozen=True)
class 候选地址:
    地址: str
    类型: str
    说明: str           # 例如 “MuMu 实例 1”“默认端口”
    运行中: bool | None  # None 表示未知


@dataclass(frozen=True)
class 检测条目:
    设备: ADB设备信息
    类型: str
    说明: str
    已安装游戏: bool
    游戏在前台: bool
    推荐: bool = False

    @property
    def 序列号(self) -> str:
        return self.设备.序列号

    @property
    def 显示文本(self) -> str:
        状态 = "CoC 在前台" if self.游戏在前台 else ("已安装 CoC" if self.已安装游戏 else "未发现 CoC")
        标记 = "  ★ 推荐" if self.推荐 else ""
        return f"{self.类型} · {self.序列号} · {状态}{标记}"


@dataclass
class 检测结果:
    adb路径: str
    条目: list[检测条目] = field(default_factory=list)
    已发现模拟器: list[模拟器安装] = field(default_factory=list)
    日志: list[str] = field(default_factory=list)

    @property
    def 推荐(self) -> 检测条目 | None:
        return next((项 for 项 in self.条目 if 项.推荐), None)


# ======================================================================== 发现
def _注册表安装目录() -> list[tuple[str, Path]]:
    """读取卸载注册表，返回 (模拟器类型, 安装目录)。"""
    if os.name != "nt":
        return []
    import winreg

    结果: list[tuple[str, Path]] = []
    根键 = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for 根, 路径 in 根键:
        try:
            父 = winreg.OpenKey(根, 路径)
        except OSError:
            continue
        with 父:
            序号 = 0
            while True:
                try:
                    子名 = winreg.EnumKey(父, 序号)
                except OSError:
                    break
                序号 += 1
                try:
                    with winreg.OpenKey(父, 子名) as 子:
                        def 取(名称):
                            try:
                                return str(winreg.QueryValueEx(子, 名称)[0] or "")
                            except OSError:
                                return ""
                        显示名 = 取("DisplayName")
                        目录 = 取("InstallLocation") or os.path.dirname(取("DisplayIcon").strip('"').split(",")[0])
                except OSError:
                    continue
                if not 显示名 or not 目录:
                    continue
                for 定义 in 模拟器定义列表:
                    if any(关键字.lower() in 显示名.lower() for 关键字 in 定义.注册表关键字):
                        结果.append((定义.名称, Path(目录)))
                        break
    return 结果


def _运行中进程路径() -> list[Path]:
    """枚举正在运行进程的可执行文件路径（无权限读取的进程跳过）。"""
    if os.name != "nt":
        return []
    psapi = ctypes.WinDLL("psapi")
    kernel32 = ctypes.WinDLL("kernel32")
    数组 = (ctypes.c_ulong * 4096)()
    返回字节 = ctypes.c_ulong()
    if not psapi.EnumProcesses(ctypes.byref(数组), ctypes.sizeof(数组), ctypes.byref(返回字节)):
        return []
    路径列表 = []
    for 进程ID in 数组[: 返回字节.value // ctypes.sizeof(ctypes.c_ulong)]:
        句柄 = kernel32.OpenProcess(0x1000, False, 进程ID)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not 句柄:
            continue
        try:
            缓冲 = ctypes.create_unicode_buffer(1024)
            长度 = ctypes.c_ulong(len(缓冲))
            if kernel32.QueryFullProcessImageNameW(句柄, 0, 缓冲, ctypes.byref(长度)):
                路径列表.append(Path(缓冲.value))
        finally:
            kernel32.CloseHandle(句柄)
    return 路径列表


def _查找adb(定义: 模拟器定义, 目录: Path) -> str | None:
    """从安装目录及其上两级查找模拟器自带 adb。"""
    for 基准 in (目录, 目录.parent, 目录.parent.parent):
        for 相对 in 定义.adb相对路径:
            候选 = 基准 / 相对
            if 候选.is_file():
                return str(候选)
    return None


def 发现模拟器(
    注册表来源: Callable[[], list[tuple[str, Path]]] = _注册表安装目录,
    进程来源: Callable[[], list[Path]] = _运行中进程路径,
) -> list[模拟器安装]:
    """合并注册表与运行中进程，返回去重后的模拟器安装（运行中的排前面）。"""
    安装: dict[str, 模拟器安装] = {}

    def 加入(类型: str, 目录: Path, 运行中: bool):
        定义 = _按名称[类型]
        adb = _查找adb(定义, 目录)
        键 = os.path.normcase(str(目录.resolve() if 目录.exists() else 目录))
        已有 = 安装.get(键)
        if 已有 is None:
            安装[键] = 模拟器安装(类型, 目录, adb, 运行中)
        else:
            已有.运行中 = 已有.运行中 or 运行中
            已有.adb路径 = 已有.adb路径 or adb

    注册表 = [(类型, 目录) for 类型, 目录 in 注册表来源() if 目录.exists()]
    注册表键 = {os.path.normcase(str(目录.resolve())) for _类型, 目录 in 注册表}
    for 路径 in 进程来源():
        for 定义 in 模拟器定义列表:
            if 路径.name.lower() not in (名.lower() for 名 in 定义.进程名):
                continue
            祖先 = list(路径.parents)[:5]
            # 进程通常在安装目录的子目录里，回溯到安装根目录：优先注册表
            # 记录的目录，其次含根目录标记的目录，最后是直接含 adb 的目录。
            目录 = next(
                (上级 for 上级 in 祖先 if os.path.normcase(str(上级.resolve())) in 注册表键), None,
            )
            if 目录 is None and 定义.根目录标记:
                目录 = next((上级 for 上级 in 祖先 if (上级 / 定义.根目录标记).is_dir()), None)
            if 目录 is None:
                目录 = next(
                    (上级 for 上级 in 祖先 if any((上级 / 相对).is_file() for 相对 in 定义.adb相对路径)),
                    路径.parent,
                )
            加入(定义.名称, 目录, True)
            break
    for 类型, 目录 in 注册表:
        加入(类型, 目录, False)
    return sorted(安装.values(), key=lambda 项: (not 项.运行中, 项.类型))


# ======================================================================== 端口
def _MuMu管理器信息(安装目录: Path, runner=subprocess.run) -> dict:
    for 相对 in ("nx_main/MuMuManager.exe", "shell/MuMuManager.exe"):
        路径 = 安装目录 / 相对
        if not 路径.is_file():
            continue
        try:
            结果 = runner(
                [str(路径), "info", "-v", "all"], capture_output=True, timeout=8, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            return {}
        文本 = 结果.stdout.decode("utf-8", "replace") if isinstance(结果.stdout, bytes) else str(结果.stdout or "")
        try:
            数据 = json.loads(文本)
        except ValueError:
            return {}
        # 单实例时 MuMuManager 直接返回实例对象，多实例时返回 {序号: 实例}。
        if isinstance(数据, dict) and "index" in 数据:
            return {str(数据.get("index")): 数据}
        return 数据 if isinstance(数据, dict) else {}
    return {}


def MuMu候选地址(安装目录: Path, runner=subprocess.run) -> list[候选地址]:
    地址: dict[str, 候选地址] = {}
    for 序号, 实例 in _MuMu管理器信息(安装目录, runner).items():
        if not isinstance(实例, dict):
            continue
        名称 = 实例.get("name") or f"实例 {序号}"
        运行中 = bool(实例.get("is_android_started"))
        端口 = 实例.get("adb_port")
        if 端口:
            # adb_host_ip 是模拟器内部的 guest 地址（如 10.0.2.15），宿主机
            # 只能通过 127.0.0.1 上的转发端口连接。
            键 = f"{本机}:{int(端口)}"
            地址[键] = 候选地址(键, "MuMu", f"MuMu {名称}", 运行中)
    for 配置 in sorted((安装目录 / "vms").glob("*/configs/vm_config.json")):
        try:
            数据 = json.loads(配置.read_text(encoding="utf-8"))
            端口 = 数据["vm"]["nat"]["port_forward"]["adb"]["host_port"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        键 = f"{本机}:{int(端口)}"
        if 键 not in 地址:
            地址[键] = 候选地址(键, "MuMu", f"MuMu {配置.parent.parent.name}", None)
    return list(地址.values())


def 蓝叠候选地址(配置路径: Iterable[Path] | None = None) -> list[候选地址]:
    if 配置路径 is None:
        数据目录 = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        配置路径 = (数据目录 / "BlueStacks_nxt" / "bluestacks.conf", 数据目录 / "BlueStacks" / "bluestacks.conf")
    结果 = []
    for 路径 in 配置路径:
        try:
            文本 = Path(路径).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for 实例, 端口 in re.findall(r'bst\.instance\.([^.]+)\.status\.adb_port="(\d+)"', 文本):
            结果.append(候选地址(f"{本机}:{端口}", "蓝叠", f"蓝叠 {实例}", None))
    return 结果


def 收集候选地址(已发现: list[模拟器安装], runner=subprocess.run) -> list[候选地址]:
    """按“配置读出的真实端口 → 默认端口”的顺序合并候选，去重。"""
    结果: dict[str, 候选地址] = {}

    def 加入(项: 候选地址):
        结果.setdefault(项.地址, 项)

    类型集合 = {项.类型 for 项 in 已发现}
    for 安装 in 已发现:
        if 安装.类型 == "MuMu":
            for 项 in MuMu候选地址(安装.安装目录, runner):
                加入(项)
    if "蓝叠" in 类型集合:
        for 项 in 蓝叠候选地址():
            加入(项)
    for 定义 in 模拟器定义列表:
        if 类型集合 and 定义.名称 not in 类型集合:
            continue
        for 端口 in 定义.默认端口:
            加入(候选地址(f"{本机}:{端口}", 定义.名称, f"{定义.名称} 默认端口", None))
    return list(结果.values())


def 端口在监听(地址: str, 超时秒: float = 0.3) -> bool:
    主机, _, 端口 = 地址.rpartition(":")
    try:
        with socket.create_connection((主机, int(端口)), timeout=超时秒):
            return True
    except (OSError, ValueError):
        return False


# ======================================================================== 检测
def 选择adb路径(已发现: list[模拟器安装], 已保存: str = "") -> str:
    """优先用正在运行的模拟器自带 adb，其次已安装的，最后回退到常见目录。"""
    for 只看运行中 in (True, False):
        for 安装 in 已发现:
            if 安装.adb路径 and (安装.运行中 or not 只看运行中):
                return 安装.adb路径
    if 已保存:
        try:
            return ADB设备操作类.解析ADB路径(已保存, 自动检测=False)
        except ADB错误:
            pass
    return ADB设备操作类.解析ADB路径("", 自动检测=True)


def _推断类型(序列号: str, 地址表: dict[str, 候选地址]) -> tuple[str, str]:
    if 序列号 in 地址表:
        项 = 地址表[序列号]
        return 项.类型, 项.说明
    if re.fullmatch(r"emulator-\d+", 序列号):
        return "模拟器", "ADB 自动发现"
    return "设备", "ADB 已连接"


def 检测(
    包名: str = 默认游戏包名,
    已保存adb路径: str = "",
    *,
    发现: Callable[[], list[模拟器安装]] = 发现模拟器,
    端口探测: Callable[[str], bool] = 端口在监听,
    runner=subprocess.run,
    进度: Callable[[str], None] | None = None,
) -> 检测结果:
    """一键检测。返回所有可用的模拟器设备，并在可以唯一确定时标记推荐。"""
    日志: list[str] = []

    def 记(文本: str):
        日志.append(文本)
        if 进度:
            进度(文本)

    已发现 = 发现()
    if 已发现:
        记("发现模拟器：" + "、".join(
            f"{项.类型}{'（运行中）' if 项.运行中 else ''}" for 项 in 已发现
        ))
    else:
        记("未在注册表或进程中发现已知模拟器，将尝试所有常见端口")
    adb路径 = 选择adb路径(已发现, 已保存adb路径)
    记(f"使用 ADB：{adb路径}")

    候选 = 收集候选地址(已发现, runner)
    地址表 = {项.地址: 项 for 项 in 候选}
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as 池:
        监听 = [项 for 项, 开 in zip(候选, 池.map(lambda 项: 端口探测(项.地址), 候选)) if 开]
    记(f"候选端口 {len(候选)} 个，正在监听 {len(监听)} 个" + (
        "：" + "、".join(项.地址 for 项 in 监听) if 监听 else ""
    ))
    for 项 in 监听:
        try:
            文本 = ADB设备操作类.连接网络设备(adb路径, 项.地址, runner=runner, 自动检测路径=False)
            if "cannot" in 文本.lower():
                记(f"{项.地址} 连接失败：{文本}")
        except ADB错误 as 异常:
            记(f"{项.地址} 连接失败：{异常}")

    设备列表 = ADB设备操作类.扫描设备(adb路径, runner=runner, 自动检测路径=False)
    可用 = [设备 for 设备 in 设备列表 if 设备.状态 == "device" and not 设备.疑似实体设备]
    for 设备 in 设备列表:
        if 设备.疑似实体设备:
            记(f"已排除疑似实体手机：{设备.显示文本}")
        elif 设备.状态 != "device":
            记(f"设备不可用（{设备.状态}）：{设备.序列号}")
    评估: list[游戏设备评估] = ADB设备操作类.评估游戏设备(adb路径, 可用, 包名, runner) if 可用 else []

    最高分 = 评估[0].评分 if 评估 else 0
    唯一最高 = 最高分 > 0 and sum(1 for 项 in 评估 if 项.评分 == 最高分) == 1
    条目 = []
    for 项 in 评估:
        类型, 说明 = _推断类型(项.设备.序列号, 地址表)
        条目.append(检测条目(
            设备=项.设备, 类型=类型, 说明=说明,
            已安装游戏=项.已安装, 游戏在前台=项.前台,
            推荐=唯一最高 and 项.评分 == 最高分,
        ))
    if not 条目:
        记("没有找到可用的模拟器。请先启动模拟器，并在模拟器设置里开启 ADB 调试。")
    elif not 唯一最高:
        记("找到多台模拟器，无法自动确定游戏在哪台，请手动选择。")
    else:
        记(f"推荐：{next(项 for 项 in 条目 if 项.推荐).显示文本}")
    return 检测结果(adb路径=adb路径, 条目=条目, 已发现模拟器=已发现, 日志=日志)


def 检测并选择(包名: str = 默认游戏包名, 已保存adb路径: str = "", **参数) -> tuple[str, ADB设备信息]:
    """启动任务时使用：唯一推荐才返回，否则抛 ADB错误 让用户手动确认。"""
    结果 = 检测(包名, 已保存adb路径, **参数)
    推荐 = 结果.推荐
    if 推荐 is None:
        raise ADB错误(结果.日志[-1] if 结果.日志 else "没有找到可用的模拟器")
    return 结果.adb路径, 推荐.设备


def 重启ADB服务(adb路径: str) -> str:
    """kill-server + start-server（只影响本程序专用的 ADB 服务端口）。"""
    环境 = ADB设备操作类._ADB子进程环境()
    参数 = dict(capture_output=True, timeout=15, check=False, env=环境,
              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    subprocess.run([adb路径, "kill-server"], **参数)
    结果 = subprocess.run([adb路径, "start-server"], **参数)
    if 结果.returncode:
        错误 = 结果.stderr.decode("utf-8", "replace") if isinstance(结果.stderr, bytes) else str(结果.stderr)
        raise ADB错误(错误.strip() or "ADB 服务启动失败")
    return f"ADB 服务已重启（端口 {ADB设备操作类.ADB服务器端口}）"
