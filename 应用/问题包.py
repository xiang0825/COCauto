"""一键导出问题包：把排查需要的东西打成一个 zip 放到 EXE 同级。

内容：
- ``日志/最近日志.txt``：数据库里每个机器人最近的任务日志；
- ``日志/上次日志.bak.jsonl``、``日志/robot-error.log*``：上次会话日志和错误日志（只取尾部）；
- ``异常现场/``：自动留证的摘要；截图默认不带（画面里可能有玩家名/部落名），
  用户确认后才带；
- ``运行时状态.json``：只导出排查需要的状态类型（资源、工人、升级失败记录、
  部落竞赛检查记录等），官方账号数据等其余类型只列名称；
- ``配置.json``：机器人设置（去掉账号、令牌、Webhook、设备序列号等字段）；
- ``版本.txt``、``系统信息.txt``。

所有写进 zip 的文本统一脱敏：已知的玩家名/标签、部落名/标签、设备序列号、
令牌、Windows 用户名/计算机名逐字替换；再按规则打码 ``#标签``、IP、模拟器
序列号、用户目录里的用户名、Webhook key 和 Bearer 令牌。只读取、不修改源文件。
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
from typing import Any, Iterable, Optional

from 应用 import 异常留证

最近日志条数 = 3000
单文件尾部字节 = 5 * 1024 * 1024
已去除 = "<已去除>"

# 键名命中任一片段即视为账号/密钥/身份类字段（大小写不敏感），值整体去除。
_敏感键片段 = (
    "令牌", "token", "密钥", "secret", "key", "webhook", "密码", "password",
    "账号", "帐号", "标签", "cookie", "授权", "auth", "邮箱", "email",
    "序列号", "serial", "玩家", "名字", "昵称", "部落名", "name", "tag", "ip地址", "公网ip",
)
# 这些键的值是需要逐字从所有文本里抹掉的身份信息。
_身份键片段 = ("标签", "名字", "昵称", "玩家", "部落名", "序列号", "令牌", "webhook", "name", "tag")

# 运行时状态只导出这些类型（排查资源/升级/竞赛问题所需），其余只列类型名。
导出状态类型 = frozenset({
    "家乡资源", "夜世界资源", "工人状态", "部落竞赛检查记录",
    "研究升级失败记录", "建筑升级失败记录", "战宠升级失败记录",
    "战斗胜率", "今日统计",
})

_规则脱敏 = (
    (re.compile(r"(?i)(key=)[0-9a-z\-]{6,}"), r"\1" + 已去除),
    (re.compile(r"(?i)(bearer\s+)[0-9a-z._\-]{8,}"), r"\1" + 已去除),
    (re.compile(r"(?i)(token[\"']?\s*[:=]\s*[\"']?)[0-9a-z._\-]{8,}"), r"\1" + 已去除),
    # 部落冲突玩家/部落标签
    (re.compile(r"#[0289PYLQGRJCUVpylqgrjcuv]{4,12}\b"), "#<标签>"),
    # IPv4（含端口），覆盖 127.0.0.1:16384 这类模拟器序列号
    (re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?![\d.])"), "<IP>"),
    (re.compile(r"(?i)\bemulator-\d+\b"), "<设备>"),
    # 用户目录里的用户名
    (re.compile(r"(?i)([a-z]:[\\/]+(?:users|documents and settings)[\\/]+)[^\\/\s\"'<>|]+"), r"\1<用户>"),
    (re.compile(r"(/home/)[^/\s\"']+"), r"\1<用户>"),
)


def 是敏感键(键: Any) -> bool:
    文本 = str(键).lower()
    return any(片段 in 文本 for 片段 in _敏感键片段)


def _是身份键(键: Any) -> bool:
    文本 = str(键).lower()
    return any(片段 in 文本 for 片段 in _身份键片段)


def 收集身份值(*数据: Any) -> set[str]:
    """递归收集身份类键的取值（玩家名、标签、部落名、序列号、令牌…）。"""
    结果: set[str] = set()

    def 走(值, 身份=False):
        if isinstance(值, dict):
            for 键, 子 in 值.items():
                走(子, 身份 or _是身份键(键))
        elif isinstance(值, (list, tuple)):
            for 子 in 值:
                走(子, 身份)
        elif 身份 and isinstance(值, (str, int)) and not isinstance(值, bool):
            文本 = str(值).strip()
            if len(文本) >= 2:
                结果.add(文本)

    for 项 in 数据:
        走(项)
    return 结果


def 本机身份值() -> set[str]:
    结果 = set()
    for 值 in (
        os.environ.get("USERNAME"), os.environ.get("USER"),
        os.environ.get("COMPUTERNAME"), Path.home().name, platform.node(),
    ):
        if 值 and len(str(值).strip()) >= 2:
            结果.add(str(值).strip())
    return 结果


class 脱敏器:
    def __init__(self, 已知值: Iterable[str] = ()):
        # 长的先替换，避免短值把长值切碎。
        self._已知值 = sorted({str(值) for 值 in 已知值 if 值 and len(str(值)) >= 2}, key=len, reverse=True)

    def 文本(self, 文本: str) -> str:
        文本 = str(文本)
        for 值 in self._已知值:
            if 值 in 文本:
                文本 = 文本.replace(值, 已去除)
        for 规则, 替换 in _规则脱敏:
            文本 = 规则.sub(替换, 文本)
        return 文本

    def 数据(self, 数据: Any) -> Any:
        """递归：敏感键的值整体去除，其余字符串过一遍文本脱敏。"""
        if isinstance(数据, dict):
            return {
                self.文本(键): (
                    已去除 if 是敏感键(键) and 值 not in (None, "", [], {}) else self.数据(值)
                )
                for 键, 值 in 数据.items()
            }
        if isinstance(数据, (list, tuple)):
            return [self.数据(项) for 项 in 数据]
        if isinstance(数据, str):
            return self.文本(数据)
        return 数据


def 脱敏数据(数据: Any) -> Any:
    return 脱敏器().数据(数据)


def 脱敏文本(文本: str) -> str:
    return 脱敏器().文本(文本)


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


def 导出问题包(
    数据库,
    根目录: Optional[Path] = None,
    现在: Optional[float] = None,
    *,
    包含截图: bool = False,
) -> Path:
    """生成问题包 zip 并返回路径；失败抛异常交给界面提示。"""
    根 = Path(根目录 or 异常留证.程序目录())
    现在 = float(time.time() if 现在 is None else 现在)
    名称 = f"问题包_{time.strftime('%Y%m%d_%H%M%S', time.localtime(现在))}.zip"
    目标 = 根 / 名称
    临时 = 目标.with_suffix(".zip.tmp")
    数据库路径 = Path(getattr(数据库, "文件路径", "") or "")
    数据库目录 = 数据库路径.parent if str(数据库路径) else None

    try:
        设置表 = {标志: _转字典(设置) for 标志, 设置 in 数据库.查询所有机器人设置().items()}
        设置异常 = ""
    except Exception as 异常:
        设置表 = {}
        设置异常 = str(异常)
    状态表: dict[str, dict] = {}
    for 标志 in 设置表:
        try:
            状态 = 数据库.获取最新完整状态(标志).状态数据
            状态表[标志] = 状态 if isinstance(状态, dict) else {}
        except Exception as 异常:
            状态表[标志] = {"_读取失败": str(异常)}
    # 已知身份值来自全部设置和全部状态（含不导出的官方账号数据），用于抹掉日志里的残留。
    脱敏 = 脱敏器(收集身份值(设置表, 状态表) | 本机身份值())

    try:
        _写入问题包(临时, 数据库, 根, 现在, 设置表, 设置异常, 状态表, 数据库目录, 脱敏, 包含截图)
    except BaseException:
        # 只清理本次自己写了一半的临时文件。
        try:
            临时.unlink()
        except OSError:
            pass
        raise
    os.replace(临时, 目标)
    return 目标


def _写入问题包(临时: Path, 数据库, 根: Path, 现在: float, 设置表: dict, 设置异常: str,
               状态表: dict, 数据库目录: Optional[Path], 脱敏: 脱敏器, 包含截图: bool) -> None:
    清单: list[str] = []
    省略截图 = 0

    def 写文本(包: zipfile.ZipFile, 名称: str, 内容: str) -> None:
        包.writestr(名称, 脱敏.文本(内容))

    with zipfile.ZipFile(临时, "w", compression=zipfile.ZIP_DEFLATED) as 包:
        版本 = 异常留证.读取版本号(根)
        写文本(包, "版本.txt", 版本 + "\n")
        写文本(包, "系统信息.txt", "\n".join([
            f"导出时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(现在))}",
            f"版本：{版本}",
            f"系统：{platform.system()} {platform.release()} {platform.version()}",
            f"Python：{sys.version.split()[0]}",
            f"打包版：{bool(getattr(sys, 'frozen', False))}",
            f"机器人：{'、'.join(设置表) or '无'}",
        ]) + "\n")

        配置 = {标志: 脱敏.数据(设置) for 标志, 设置 in 设置表.items()}
        if 设置异常:
            配置["_读取失败"] = 设置异常
        写文本(包, "配置.json", json.dumps(配置, ensure_ascii=False, indent=2, default=str))

        状态导出: dict[str, Any] = {}
        日志行: list[str] = []
        for 标志, 状态 in 状态表.items():
            保留 = {类型: 值 for 类型, 值 in 状态.items() if 类型 in 导出状态类型 or 类型 == "_读取失败"}
            省略 = sorted(类型 for 类型 in 状态 if 类型 not in 保留)
            状态导出[标志] = {**脱敏.数据(保留), "_未导出的状态类型": 省略}
            try:
                for 日志 in reversed(数据库.查询日志历史(标志, 最大条数=最近日志条数)):
                    时间 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(日志.记录时间)))
                    日志行.append(f"{时间} [{标志}] {日志.日志内容}")
            except Exception as 异常:
                日志行.append(f"[{标志}] 读取日志失败：{异常}")
        写文本(包, "运行时状态.json", json.dumps(状态导出, ensure_ascii=False, indent=2, default=str))
        写文本(包, "日志/最近日志.txt", "\n".join(日志行) + "\n")

        if 数据库目录 is not None and 数据库目录.is_dir():
            候选 = [数据库目录 / "上次日志.bak.jsonl", 数据库目录 / "robot-error.log",
                    数据库目录 / "robot-error.log.bak"]
            候选 += sorted(数据库目录.glob("robot-error.*.log"))[-2:]
            for 路径 in 候选:
                try:
                    if 路径.is_file():
                        写文本(包, f"日志/{路径.name}", _读取尾部(路径).decode("utf-8", errors="replace"))
                        清单.append(路径.name)
                except OSError:
                    continue

        for 目录 in 异常留证.列出留证目录(根):
            for 文件 in sorted(目录.iterdir()):
                try:
                    if not 文件.is_file():
                        continue
                    相对 = f"异常现场/{目录.name}/{文件.name}"
                    if 文件.suffix.lower() == ".txt":
                        写文本(包, 相对, 文件.read_text(encoding="utf-8", errors="replace"))
                    elif 包含截图:
                        包.write(文件, 相对)
                    else:
                        省略截图 += 1
                except OSError:
                    continue
        写文本(包, "说明.txt", (
            "城控问题包：请把这个 zip 发给维护者。\n"
            "配置里的令牌、Webhook、账号/玩家标签、设备序列号等字段已去除；日志里的玩家名/标签、"
            "部落名/标签、IP、用户目录用户名已打码。\n"
            + (f"异常现场截图：已附带（画面里可能有玩家名/部落名）\n" if 包含截图
               else f"异常现场截图：未附带（{省略截图} 张；画面里可能有玩家名，需要时在导出时选择附带）\n")
            + f"附带日志文件：{'、'.join(清单) or '无'}\n"
        ))
