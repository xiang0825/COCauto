"""校验发布包包含所需入口和延迟模块，且项目字节码与当前源码一致。"""

import ast
import hashlib
import marshal
import re
import sys
from pathlib import Path
from types import CodeType

from PyInstaller.archive.readers import (
    CArchiveReader,
    PKG_ITEM_PYZ,
    pkg_archive_contents,
)
from PyInstaller.utils.hooks.setuptools import setuptools_info


def 延迟模块名(源码: Path) -> set[str]:
    语法树 = ast.parse(源码.read_text(encoding="utf-8"))
    return {
        调用.args[0].value
        for 调用 in ast.walk(语法树)
        if isinstance(调用, ast.Call)
        and isinstance(调用.func, ast.Name)
        and 调用.func.id == "_延迟导入对象"
        and 调用.args
        and isinstance(调用.args[0], ast.Constant)
        and isinstance(调用.args[0].value, str)
    }


def 所需打包模块(机器人源码: Path) -> set[str]:
    return 延迟模块名(机器人源码) | {
        "线程.自动化机器人",
        "界面.主窗口",
        "应用.控制器",
        "PySide6",
    }


def 缺失入口脚本(归档脚本名: set[str]) -> set[str]:
    return {"UI入口", "打包运行时"} - set(归档脚本名)


def 所需启动依赖模块() -> set[str]:
    """按当前 setuptools 的打包布局检查 pkg_resources 启动依赖。"""
    if setuptools_info.version and setuptools_info.version >= (71, 0):
        return {
            "pkg_resources",
            "setuptools._vendor.jaraco.text",
            "setuptools._vendor.jaraco.context",
            "setuptools._vendor.jaraco.functools",
            "setuptools._vendor.packaging",
        }
    return {
        "pkg_resources",
        "pkg_resources._vendor.jaraco.text",
        "pkg_resources._vendor.jaraco.context",
        "pkg_resources._vendor.jaraco.functools",
        "pkg_resources._vendor.appdirs",
        "pkg_resources._vendor.packaging",
    }


def 解析源码模块路径(项目根: Path, 模块名: str) -> Path:
    模块路径 = 项目根.joinpath(*模块名.split("."))
    普通模块 = 模块路径.with_suffix(".py")
    if 普通模块.is_file():
        return 普通模块
    包入口 = 模块路径 / "__init__.py"
    if 包入口.is_file():
        return 包入口
    raise FileNotFoundError(f"找不到模块 {模块名} 的源码：{普通模块} 或 {包入口}")


def 项目源码包内模块(项目根: Path, 打包模块名: set[str]) -> set[str]:
    项目模块 = set()
    for 模块名 in 打包模块名:
        try:
            解析源码模块路径(项目根, 模块名)
        except FileNotFoundError:
            continue
        项目模块.add(模块名)
    return 项目模块


def 项目归档源码模块(
    项目根: Path,
    PYZ模块名: set[str],
    归档脚本名: set[str],
) -> set[str]:
    return 项目源码包内模块(
        项目根,
        set(PYZ模块名) | set(归档脚本名),
    )


def _规范化常量(常量):
    if isinstance(常量, CodeType):
        return _规范化代码对象(常量)
    if isinstance(常量, tuple):
        return tuple(_规范化常量(项目) for 项目 in 常量)
    if isinstance(常量, frozenset):
        return frozenset(_规范化常量(项目) for 项目 in 常量)
    return 常量


def _规范化代码对象(代码: CodeType) -> CodeType:
    """去掉路径和行号信息，保留可执行字节码、常量及控制流。"""
    return 代码.replace(
        co_filename="<module>",
        co_firstlineno=1,
        co_linetable=b"",
        co_consts=tuple(_规范化常量(常量) for 常量 in 代码.co_consts),
    )


def 计算代码签名(代码: CodeType) -> str:
    return hashlib.sha256(marshal.dumps(_规范化代码对象(代码))).hexdigest()


def 模块源码匹配(源码路径: Path, 打包代码: CodeType) -> bool:
    源码代码 = compile(
        源码路径.read_bytes(),
        打包代码.co_filename,
        "exec",
        optimize=0,
        dont_inherit=True,
    )
    return 计算代码签名(源码代码) == 计算代码签名(打包代码)


def 读取包内Python版本(exe路径: Path) -> tuple[int, int]:
    内部目录 = Path(exe路径).resolve().parent / "_internal"
    匹配版本 = set()
    for dll in 内部目录.glob("python*.dll"):
        匹配 = re.fullmatch(r"python(?P<主版本>\d)(?P<次版本>\d+)\.dll", dll.name.lower())
        if 匹配:
            匹配版本.add((int(匹配["主版本"]), int(匹配["次版本"])))
    if len(匹配版本) != 1:
        raise RuntimeError(
            f"无法从 {内部目录} 唯一确定包内 Python 版本：{sorted(匹配版本)}"
        )
    return next(iter(匹配版本))


def 校验解释器版本(exe路径: Path, 当前版本=None) -> tuple[bool, str]:
    包内版本 = 读取包内Python版本(exe路径)
    校验器版本 = tuple(当前版本 or sys.version_info[:2])
    if 包内版本 != 校验器版本:
        return False, (
            f"包内 Python {包内版本[0]}.{包内版本[1]}，但当前校验器运行于 "
            f"Python {校验器版本[0]}.{校验器版本[1]}；请使用相同版本的 Python 校验"
        )
    return True, f"Python 版本匹配：{包内版本[0]}.{包内版本[1]}"


def 校验包版本(exe路径: Path, 项目根: Path) -> tuple[bool, str]:
    """发布包内版本标记必须与当前源码版本一致。"""
    源码版本路径 = Path(项目根) / "版本号.txt"
    包版本路径 = Path(exe路径).resolve().parent / "_internal" / "版本号.txt"
    try:
        源码版本 = 源码版本路径.read_text(encoding="utf-8").strip()
    except OSError as 异常:
        return False, f"无法读取源码版本文件 {源码版本路径}：{异常}"
    try:
        包版本 = 包版本路径.read_text(encoding="utf-8").strip()
    except OSError as 异常:
        return False, f"无法读取候选包版本文件 {包版本路径}：{异常}"
    if not 源码版本:
        return False, f"源码版本文件为空：{源码版本路径}"
    if not 包版本:
        return False, f"候选包版本文件为空：{包版本路径}"
    if 包版本 != 源码版本:
        return False, f"版本不一致：候选包 {包版本}，当前源码 {源码版本}"
    return True, f"版本匹配：{源码版本}"


def 校验识别参数文件(exe路径: Path, 项目根: Path) -> list[str]:
    """发布包 _internal/资源/识别/*.json 必须齐全且与源码一致。"""
    问题 = []
    内部目录 = Path(exe路径).resolve().parent / "_internal" / "资源" / "识别"
    for 源文件 in sorted((Path(项目根) / "资源" / "识别").glob("*.json")):
        包文件 = 内部目录 / 源文件.name
        if not 包文件.is_file():
            问题.append(f"缺少 {包文件}")
        elif 包文件.read_bytes() != 源文件.read_bytes():
            问题.append(f"{包文件} 与源码不一致")
    return 问题


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        print("用法：verify_packaged_modules.py <部落冲突.exe>", file=sys.stderr)
        return 2
    根目录 = Path(__file__).resolve().parents[1]
    exe路径 = Path(sys.argv[1]).resolve()
    包版本匹配, 包版本说明 = 校验包版本(exe路径, 根目录)
    if not 包版本匹配:
        print(f"发布包版本校验失败：{包版本说明}", file=sys.stderr)
        return 2
    try:
        版本匹配, 版本说明 = 校验解释器版本(exe路径)
    except Exception as 异常:
        print(f"发布包 Python 运行时校验失败：{异常}", file=sys.stderr)
        return 2
    if not 版本匹配:
        print(版本说明, file=sys.stderr)
        return 2

    所需模块 = (
        所需打包模块(根目录 / "线程" / "自动化机器人.py")
        | 所需启动依赖模块()
    )
    已打包模块 = set(pkg_archive_contents(str(exe路径)))
    缺失模块 = sorted(所需模块 - 已打包模块)
    if 缺失模块:
        print("发布包缺少延迟导入模块：", file=sys.stderr)
        for 模块名 in 缺失模块:
            print(f"  {模块名}", file=sys.stderr)
        return 1

    程序包 = CArchiveReader(str(exe路径))
    PYZ名称 = next(
        (名称 for 名称, 条目 in 程序包.toc.items() if 条目[-1] == PKG_ITEM_PYZ),
        None,
    )
    if PYZ名称 is None:
        print("发布包没有 PYZ Python 模块归档", file=sys.stderr)
        return 1
    PYZ = 程序包.open_embedded_archive(PYZ名称)
    已打包入口脚本 = {
        名称 for 名称, 条目 in 程序包.toc.items() if 条目[-1] == "s"
    }
    缺失脚本 = 缺失入口脚本(已打包入口脚本)
    if 缺失脚本:
        print("发布包缺少入口脚本：", file=sys.stderr)
        for 名称 in sorted(缺失脚本):
            print(f"  {名称}", file=sys.stderr)
        return 1

    项目模块 = 项目归档源码模块(
        根目录,
        set(PYZ.toc),
        已打包入口脚本,
    )
    不匹配模块 = []
    for 模块名 in sorted(项目模块):
        try:
            源码路径 = 解析源码模块路径(根目录, 模块名)
            打包代码 = (
                marshal.loads(程序包.extract(模块名))
                if 模块名 in 已打包入口脚本
                else PYZ.extract(模块名)
            )
            if not isinstance(打包代码, CodeType) or not 模块源码匹配(源码路径, 打包代码):
                不匹配模块.append(模块名)
        except Exception as 异常:
            print(f"无法校验模块 {模块名}：{异常}", file=sys.stderr)
            不匹配模块.append(模块名)
    if 不匹配模块:
        print("发布包代码与当前源码不一致：", file=sys.stderr)
        for 模块名 in 不匹配模块:
            print(f"  {模块名}", file=sys.stderr)
        return 1

    参数问题 = 校验识别参数文件(exe路径, 根目录)
    if 参数问题:
        print("发布包识别参数文件有问题：", file=sys.stderr)
        for 文本 in 参数问题:
            print(f"  {文本}", file=sys.stderr)
        return 1

    print(
        f"发布包校验通过：{包版本说明}；"
        f"Python {sys.version_info.major}.{sys.version_info.minor}，"
        f"{len(所需模块)} 个延迟模块存在，{len(项目模块)} 个项目模块与当前源码一致"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
