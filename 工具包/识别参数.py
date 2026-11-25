"""识别参数配置化：把常变的坐标/阈值/模板路径/OCR 关键词放到 资源/识别/*.json。

用法（模块末尾、类定义之后）::

    应用识别参数(页面识别器, "主页")

规则：
- 类里写的值是代码默认值；JSON 同名键覆盖它，JSON 缺键/缺文件/格式错误时
  保留代码默认值，绝不让脚本因资源文件问题崩溃。
- 每个 JSON 顶层按类名分节：``{"页面识别器": {"结算阈值": 0.8, ...}}``。
- JSON 里只能写类上已有的属性；未知键忽略并记录，防止拼写错误悄悄失效。
- 类型跟随默认值：tuple 默认值把 JSON 列表转成（嵌套）tuple，int 默认值
  只接受整数，float 接受数字，dict/str/bool 原样校验。类型不符的键忽略。
- 查找顺序同部落竞赛：EXE 同级 资源/ → _internal/资源 → 源码根 资源/。
  改 EXE 同级的 JSON 后重启生效，不用重新打包。
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, Iterable

资源子目录 = Path("资源") / "识别"
_缓存: dict[str, dict] = {}
_锁 = threading.Lock()
问题记录: list[str] = []


def 资源候选目录() -> list[Path]:
    候选: list[Path] = []

    def 加入(目录):
        if 目录:
            路径 = Path(目录).resolve()
            if 路径 not in 候选:
                候选.append(路径)

    if getattr(sys, "frozen", False):
        程序目录 = Path(sys.executable).resolve().parent
        加入(程序目录)
        加入(getattr(sys, "_MEIPASS", None))
        加入(程序目录 / "_internal")
    加入(Path(__file__).resolve().parents[1])
    return 候选


def 查找参数文件(名称: str, 候选目录: Iterable[Path] | None = None) -> Path | None:
    for 目录 in (候选目录 if 候选目录 is not None else 资源候选目录()):
        路径 = Path(目录) / 资源子目录 / f"{名称}.json"
        if 路径.is_file():
            return 路径
    return None


def _记录问题(文本: str) -> None:
    问题记录.append(文本)
    try:
        print(f"[识别参数] {文本}")
    except Exception:
        pass


def 加载识别参数(名称: str, 路径: str | Path | None = None) -> dict:
    """读取一个参数文件（带缓存）；找不到或格式错误返回空字典。"""
    键 = str(路径) if 路径 is not None else 名称
    with _锁:
        if 键 in _缓存:
            return _缓存[键]
    文件 = Path(路径) if 路径 is not None else 查找参数文件(名称)
    数据: dict = {}
    if 文件 is None:
        _记录问题(f"找不到 {资源子目录 / (名称 + '.json')}，使用代码默认值")
    else:
        try:
            with open(文件, encoding="utf-8") as 句柄:
                读取 = json.load(句柄)
            if isinstance(读取, dict):
                数据 = 读取
            else:
                _记录问题(f"{文件} 顶层必须是对象，使用代码默认值")
        except (OSError, ValueError) as 异常:
            _记录问题(f"{文件} 读取失败（{异常}），使用代码默认值")
    with _锁:
        _缓存[键] = 数据
    return 数据


def 清空缓存() -> None:
    with _锁:
        _缓存.clear()


def _转元组(值: Any) -> Any:
    if isinstance(值, list):
        return tuple(_转元组(项) for 项 in 值)
    return 值


def 转换为默认类型(默认: Any, 值: Any) -> tuple[bool, Any]:
    """按默认值类型校验/转换 JSON 值；返回 (是否可用, 转换后的值)。"""
    if isinstance(默认, bool):
        return (True, 值) if isinstance(值, bool) else (False, None)
    if isinstance(默认, int):
        if isinstance(值, bool) or not isinstance(值, (int, float)):
            return False, None
        if isinstance(值, float) and not 值.is_integer():
            return False, None
        return True, int(值)
    if isinstance(默认, float):
        if isinstance(值, bool) or not isinstance(值, (int, float)):
            return False, None
        return True, float(值)
    if isinstance(默认, str):
        return (True, 值) if isinstance(值, str) else (False, None)
    if isinstance(默认, tuple):
        if not isinstance(值, list):
            return False, None
        return True, _转元组(值)
    if isinstance(默认, dict):
        return (True, dict(值)) if isinstance(值, dict) else (False, None)
    if isinstance(默认, (set, frozenset)):
        return (True, type(默认)(值)) if isinstance(值, list) else (False, None)
    return False, None


def 转为JSON值(值: Any) -> Any:
    """代码默认值 → JSON 可写形式（tuple/set 写成列表），用于生成与比对。"""
    if isinstance(值, (tuple, list)):
        return [转为JSON值(项) for 项 in 值]
    if isinstance(值, (set, frozenset)):
        return sorted(转为JSON值(项) for 项 in 值)
    if isinstance(值, dict):
        return {键: 转为JSON值(项) for 键, 项 in 值.items()}
    return 值


def 应用识别参数(类: type, 名称: str, 节: str | None = None, 路径=None) -> dict[str, Any]:
    """用 资源/识别/<名称>.json 的 <节>（默认类名）覆盖类属性；返回实际覆盖的键值。"""
    节 = 节 or 类.__name__
    默认值 = getattr(类, "_识别参数默认值", None)
    if 默认值 is None or 默认值.get("_类") is not 类:
        默认值 = {"_类": 类}
        类._识别参数默认值 = 默认值
    参数 = 加载识别参数(名称, 路径).get(节) or {}
    if not isinstance(参数, dict):
        _记录问题(f"{名称}.json 的 {节} 必须是对象，忽略")
        return {}
    已应用: dict[str, Any] = {}
    for 键, 值 in 参数.items():
        if 键.startswith("_") or 键 in ("说明",):
            continue
        if 键 not in 默认值:
            if not hasattr(类, 键) or callable(getattr(类, 键)):
                _记录问题(f"{名称}.json 的 {节}.{键} 不是已知参数，忽略")
                continue
            默认值[键] = getattr(类, 键)
        可用, 转换值 = 转换为默认类型(默认值[键], 值)
        if not 可用:
            _记录问题(f"{名称}.json 的 {节}.{键} 类型与默认值 {默认值[键]!r} 不符，忽略")
            continue
        setattr(类, 键, 转换值)
        已应用[键] = 转换值
    return 已应用
