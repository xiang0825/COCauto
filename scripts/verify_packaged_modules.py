"""拒绝发布缺少机器人延迟导入模块的 PyInstaller EXE。"""

import ast
import sys
from pathlib import Path

from PyInstaller.archive.readers import pkg_archive_contents


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


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        print("用法：verify_packaged_modules.py <部落冲突.exe>", file=sys.stderr)
        return 2
    根目录 = Path(__file__).resolve().parents[1]
    所需模块 = 延迟模块名(根目录 / "线程" / "自动化机器人.py")
    已打包模块 = set(pkg_archive_contents(sys.argv[1]))
    缺失模块 = sorted(所需模块 - 已打包模块)
    if 缺失模块:
        print("发布包缺少延迟导入模块：", file=sys.stderr)
        for 模块名 in 缺失模块:
            print(f"  {模块名}", file=sys.stderr)
        return 1
    print(f"发布包延迟导入校验通过：{len(所需模块)} 个模块")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
