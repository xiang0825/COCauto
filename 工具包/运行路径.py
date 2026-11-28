"""跨平台可写数据目录辅助。

当且仅当运行在 macOS 打包版（``sys.platform == "darwin"`` 且 ``sys.frozen`` 为真）
时，把所有运行时可写目录路由到 ``~/Library/Application Support/COCauto``，
确保绝不向 ``.app`` 包内部写入任何文件。Windows 打包版与源码开发态保持原有行为。
"""
from __future__ import annotations

import sys
from pathlib import Path

MACOS_应用目录名 = "COCauto"


def 是macOS打包环境() -> bool:
    return sys.platform == "darwin" and bool(getattr(sys, "frozen", False))


def 获取macOS数据根目录(创建: bool = True) -> Path:
    目录 = Path.home() / "Library" / "Application Support" / MACOS_应用目录名
    if 创建:
        目录.mkdir(parents=True, exist_ok=True)
    return 目录


def 可写数据根目录(创建: bool = True) -> Path | None:
    """仅在 macOS frozen ``.app`` 下返回用户数据目录，其余环境返回 ``None``。"""
    if 是macOS打包环境():
        return 获取macOS数据根目录(创建=创建)
    return None


def 解析数据子路径(
    *片段: str,
    默认基准: str | Path | None = None,
    创建父目录: bool = False,
) -> Path:
    """macOS frozen ``.app`` 下基于用户数据目录解析，其余环境保持原相对/基准路径。"""
    根 = 可写数据根目录(创建=True)
    if 根 is not None:
        路径 = 根.joinpath(*片段)
    elif 默认基准 is not None:
        路径 = Path(默认基准).joinpath(*片段)
    else:
        路径 = Path(*片段)
    if 创建父目录:
        路径.parent.mkdir(parents=True, exist_ok=True)
    return 路径
