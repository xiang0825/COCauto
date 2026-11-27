"""跨平台小工具：识别当前系统、adb 可执行名、macOS 下的常见安装路径。

本模块只做“查表/拼路径”，不启动任何进程、不读写模拟器。Windows 上的
行为由调用方原有代码负责，这里提供的 macOS 分支只在 ``sys.platform ==
"darwin"`` 时生效，保证 Windows 发布版行为不变。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

平台_WINDOWS = "windows"
平台_MACOS = "macos"
平台_LINUX = "linux"


def 当前平台(平台名称: str | None = None) -> str:
    名称 = sys.platform if 平台名称 is None else str(平台名称)
    if 名称 == "win32" or 名称 == "cygwin":
        return 平台_WINDOWS
    if 名称 == "darwin":
        return 平台_MACOS
    return 平台_LINUX


def 是Windows(平台名称: str | None = None) -> bool:
    return 当前平台(平台名称) == 平台_WINDOWS


def 是macOS(平台名称: str | None = None) -> bool:
    return 当前平台(平台名称) == 平台_MACOS


def adb可执行名(平台名称: str | None = None) -> str:
    return "adb.exe" if 是Windows(平台名称) else "adb"


# BlueStacks Air（Apple Silicon）把 adb 客户端放在 .app 包内；不同版本的
# 包名/文件名并不统一（BlueStacks.app / BlueStacks Air.app，hd-adb /
# HD-Adb / adb），逐个列出，以实际存在者为准。
_macOS蓝叠应用名 = ("BlueStacks.app", "BlueStacks Air.app", "BlueStacksAir.app")
_macOS蓝叠adb名 = ("hd-adb", "HD-Adb", "adb")


def macOS候选ADB路径(用户目录: Path | None = None, 环境: dict | None = None) -> list[Path]:
    """返回 macOS 上 BlueStacks Air、Homebrew、Android SDK 的 adb 候选。"""
    家 = Path(用户目录) if 用户目录 is not None else Path.home()
    环境 = os.environ if 环境 is None else 环境
    候选: list[Path] = []
    for 应用目录 in (Path("/Applications"), 家 / "Applications"):
        for 应用名 in _macOS蓝叠应用名:
            for adb名 in _macOS蓝叠adb名:
                候选.append(应用目录 / 应用名 / "Contents" / "MacOS" / adb名)
    候选 += [
        Path("/opt/homebrew/bin/adb"),  # Homebrew（Apple Silicon）
        Path("/usr/local/bin/adb"),  # Homebrew（Intel）/手动安装
        家 / "Library" / "Android" / "sdk" / "platform-tools" / "adb",
    ]
    for 变量 in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        值 = str(环境.get(变量, "") or "").strip()
        if 值:
            候选.append(Path(值) / "platform-tools" / "adb")
    return 候选


def macOS蓝叠配置路径() -> tuple[Path, ...]:
    """BlueStacks（macOS）的 bluestacks.conf 常见位置；以实际存在者为准。"""
    return (
        Path("/Users/Shared/Library/Application Support/BlueStacks/bluestacks.conf"),
        Path("/Users/Shared/Library/Application Support/BlueStacks Air/bluestacks.conf"),
        Path.home() / "Library" / "Application Support" / "BlueStacks" / "bluestacks.conf",
    )


def 用户数据目录(应用名: str = "COCauto", 平台名称: str | None = None,
                 用户目录: Path | None = None, 环境: dict | None = None) -> Path:
    """返回适合存放数据库/日志的可写目录（第二阶段接入；当前不改变 Windows 行为）。

    - Windows：%LOCALAPPDATA%/<应用名>
    - macOS：~/Library/Application Support/<应用名>（.app 包内不可写）
    - Linux：$XDG_DATA_HOME/<应用名> 或 ~/.local/share/<应用名>
    """
    家 = Path(用户目录) if 用户目录 is not None else Path.home()
    环境 = os.environ if 环境 is None else 环境
    平台 = 当前平台(平台名称)
    if 平台 == 平台_WINDOWS:
        根 = 环境.get("LOCALAPPDATA") or str(家 / "AppData" / "Local")
        return Path(根) / 应用名
    if 平台 == 平台_MACOS:
        return 家 / "Library" / "Application Support" / 应用名
    根 = 环境.get("XDG_DATA_HOME") or str(家 / ".local" / "share")
    return Path(根) / 应用名
