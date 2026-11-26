"""一键导出问题包：把排查需要的东西打成一个 zip 放到 EXE 同级。

内容：
- ``日志/最近日志.txt``：数据库里每个机器人最近的任务日志；
- ``日志/上次日志.bak.jsonl``、``日志/robot-error.log*``：上次会话日志和错误日志（只取尾部）；
- ``异常现场/``：自动留证目录；
- ``运行时状态.json``：每个机器人的最新运行时状态摘要；
- ``配置.json``：机器人设置（去掉账号、令牌、Webhook 等字段）；
- ``版本.txt``、``系统信息.txt``。

只读取、不修改任何源文件；所有文本都过一遍脱敏（Webhook key、Bearer 令牌）。
"""
from __future__ import annotations

import json
import os
import platform
import re
import sys
import time
import zipfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Optional

from 应用 import 异常留证

最近日志条数 = 3000
单文件尾部字节 = 5 * 1024 * 1024
已去除 = "<已去除>"

# 键名命中任一片段即视为账号/密钥类字段（大小写不敏感）。
_敏感键片段 = (
    "令牌", "token", "密钥", "secret", "key", "webhook", "密码", "password",
    "账号", "帐号", "标签", "cookie", "授权", "auth", "邮箱", "email",
)
_脱敏规则 = (
    (re.compile(r"(?i)(key=)[0-9a-z\-]{6,}"), r"\1" + 已去除),
    (re.compile(r"(?i)(bearer\s+)[0-9a-z._\-]{8,}"), r"\1" + 已去除),
    (re.compile(r"(?i)(token[\"']?\s*[:=]\s*[\"']?)[0-9a-z._\-]{8,}"), r"\1" + 已去除),
)


def 是敏感键(键: Any) -> bool:
    文本 = str(键).lower()
    return any(片段 in 文本 for 片段 in _敏感键片段)


def 脱敏数据(数据: Any) -> Any:
    """递归去掉敏感键的值；字符串里的 Webhook key / Bearer 令牌也打码。"""
    if isinstance(数据, dict):
        return {
            键: (已去除 if 是敏感键(键) and 值 not in (None, "", [], {}) else 脱敏数据(值))
            for 键, 值 in 数据.items()
        }
    if isinstance(数据, (list, tuple)):
        return [脱敏数据(项) for 项 in 数据]
    if isinstance(数据, str):
        return 脱敏文本(数据)
    return 数据


def 脱敏文本(文本: str) -> str:
    for 规则, 替换 in _脱敏规则:
        文本 = 规则.sub(替换, 文本)
    return 文本


def _读取尾部(路径: Path, 字节数: int = 单文件尾部字节) -> bytes:
    大小 = 路径.stat().st_size
    with open(路径, "rb") as 文件:
        if 大小 > 字节数:
            文件.seek(大小 - 字节数)
            文件.readline()
        return 文件.read()


def _转字典(对象: Any) -> dict:
    if is_dataclass(对象):
        return asdict(对象)
    return dict(getattr(对象, "__dict__", {}) or {})


def _写文本(包: zipfile.ZipFile, 名称: str, 内容: str) -> None:
    包.writestr(名称, 脱敏文本(内容))


def 导出问题包(数据库, 根目录: Optional[Path] = None, 现在: Optional[float] = None) -> Path:
    """生成问题包 zip 并返回路径；失败抛异常交给界面提示。"""
    根 = Path(根目录 or 异常留证.程序目录())
    现在 = float(time.time() if 现在 is None else 现在)
    名称 = f"问题包_{time.strftime('%Y%m%d_%H%M%S', time.localtime(现在))}.zip"
    目标 = 根 / 名称
    临时 = 目标.with_suffix(".zip.tmp")
    数据库路径 = Path(getattr(数据库, "文件路径", "") or "")
    数据库目录 = 数据库路径.parent if str(数据库路径) else None

    try:
        设置表 = 数据库.查询所有机器人设置()
    except Exception as 异常:
        设置表 = {}
        设置异常 = str(异常)
    else:
        设置异常 = ""

    try:
        _写入问题包(临时, 数据库, 根, 现在, 设置表, 设置异常, 数据库目录)
    except BaseException:
        # 只清理本次自己写了一半的临时文件。
        try:
            临时.unlink()
        except OSError:
            pass
        raise
    os.replace(临时, 目标)
    return 目标


def _写入问题包(临时: Path, 数据库, 根: Path, 现在: float, 设置表: dict,
               设置异常: str, 数据库目录: Optional[Path]) -> None:
    清单: list[str] = []
    with zipfile.ZipFile(临时, "w", compression=zipfile.ZIP_DEFLATED) as 包:
        # 版本与系统信息
        版本 = 异常留证.读取版本号(根)
        _写文本(包, "版本.txt", 版本 + "\n")
        _写文本(包, "系统信息.txt", "\n".join([
            f"导出时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(现在))}",
            f"版本：{版本}",
            f"系统：{platform.platform()}",
            f"Python：{sys.version.split()[0]}",
            f"打包版：{bool(getattr(sys, 'frozen', False))}",
            f"机器人：{'、'.join(设置表) or '无'}",
        ]) + "\n")

        # 配置（去掉账号/密钥类字段）
        配置 = {标志: 脱敏数据(_转字典(设置)) for 标志, 设置 in 设置表.items()}
        if 设置异常:
            配置["_读取失败"] = 设置异常
        _写文本(包, "配置.json", json.dumps(配置, ensure_ascii=False, indent=2, default=str))

        # 运行时状态摘要 + 最近日志
        状态: dict[str, Any] = {}
        日志行: list[str] = []
        for 标志 in 设置表:
            try:
                状态[标志] = 脱敏数据(数据库.获取最新完整状态(标志).状态数据)
            except Exception as 异常:
                状态[标志] = {"_读取失败": str(异常)}
            try:
                for 日志 in reversed(数据库.查询日志历史(标志, 最大条数=最近日志条数)):
                    时间 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(日志.记录时间)))
                    日志行.append(f"{时间} [{标志}] {日志.日志内容}")
            except Exception as 异常:
                日志行.append(f"[{标志}] 读取日志失败：{异常}")
        _写文本(包, "运行时状态.json", json.dumps(状态, ensure_ascii=False, indent=2, default=str))
        _写文本(包, "日志/最近日志.txt", "\n".join(日志行) + "\n")

        # 上次日志备份与错误日志（只取尾部，避免问题包过大）
        if 数据库目录 is not None and 数据库目录.is_dir():
            候选 = [数据库目录 / "上次日志.bak.jsonl", 数据库目录 / "robot-error.log",
                    数据库目录 / "robot-error.log.bak"]
            候选 += sorted(数据库目录.glob("robot-error.*.log"))[-2:]
            for 路径 in 候选:
                try:
                    if 路径.is_file():
                        数据 = _读取尾部(路径).decode("utf-8", errors="replace")
                        _写文本(包, f"日志/{路径.name}", 数据)
                        清单.append(路径.name)
                except OSError:
                    continue

        # 异常现场
        现场根 = 异常留证.异常现场根目录(根)
        for 目录 in 异常留证.列出留证目录(根):
            for 文件 in sorted(目录.iterdir()):
                try:
                    if not 文件.is_file():
                        continue
                    相对 = f"异常现场/{目录.name}/{文件.name}"
                    if 文件.suffix.lower() == ".txt":
                        _写文本(包, 相对, 文件.read_text(encoding="utf-8", errors="replace"))
                    else:
                        包.write(文件, 相对)
                except OSError:
                    continue
        _写文本(包, "说明.txt", (
            "城控问题包：请把这个 zip 发给维护者。\n"
            "配置里的令牌、Webhook、账号/玩家标签等字段已去除。\n"
            f"异常现场目录：{现场根}\n"
            f"附带日志文件：{'、'.join(清单) or '无'}\n"
        ))
