"""scripts/macos 下 bash 脚本的静态检查 + （有 bash 时）语法检查与 dry-run。

bash（macOS 自带 3.2、brew 5.x 都一样）不接受非 ASCII 变量名：``仓库根=...`` 会被当成
命令执行，``for 候选 in`` 会报 not a valid identifier。这类错误属于运行时错误，
``bash -n`` 查不出来，所以先做静态扫描。
"""

import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

仓库根 = Path(__file__).resolve().parent.parent
脚本目录 = 仓库根 / "scripts" / "macos"
启动脚本 = "scripts/macos/运行城控.command"
采集脚本 = "scripts/macos/采集BlueStacks信息.sh"

_非ASCII = r"[^\x00-\x7f]"
_引号串 = re.compile(r'"(?:\\.|[^"\\])*"|\'[^\']*\'')
_违规规则 = (
    ("非 ASCII 变量赋值", re.compile(rf"(?:^|[\s;(&|])(?:export\s+|local\s+|readonly\s+)?[^\s=#;'\"()$]*{_非ASCII}[^\s=#;'\"()$]*\+?=")),
    ("for 循环使用非 ASCII 变量", re.compile(rf"\bfor\s+[^\s;]*{_非ASCII}")),
    ("read/local 声明非 ASCII 变量", re.compile(rf"\b(?:read(?:\s+-\w+)*|local|declare(?:\s+-\w+)*)\s+(?:\w+\s+)*[^\s;=]*{_非ASCII}")),
)
_非ASCII展开 = re.compile(rf"\$\{{?{_非ASCII}")


def 扫描违规(文本: str) -> list[str]:
    问题 = []
    for 行号, 行 in enumerate(文本.splitlines(), 1):
        if 行.lstrip().startswith("#"):
            continue
        if _非ASCII展开.search(行):
            问题.append(f"{行号}: 展开非 ASCII 变量：{行.strip()}")
        去引号 = _引号串.sub('""', 行)
        去引号 = re.sub(r"\s#.*$", "", 去引号)
        for 名称, 规则 in _违规规则:
            if 规则.search(去引号):
                问题.append(f"{行号}: {名称}：{行.strip()}")
    return 问题


def _查找bash() -> str | None:
    指定 = os.environ.get("COC_TEST_BASH", "").strip()
    if 指定:
        return 指定
    候选 = []
    if sys.platform == "win32":
        git = shutil.which("git")
        if git:
            根 = Path(git).resolve().parent.parent
            候选 += [根 / "usr" / "bin" / "bash.exe", 根 / "bin" / "bash.exe"]
    which = shutil.which("bash")
    if which:
        候选.append(Path(which))
    for 路径 in 候选:
        # Windows 的 System32\bash.exe 是 WSL 入口，可能未安装发行版，不用。
        if 路径.is_file() and "system32" not in str(路径).lower():
            return str(路径)
    return None


class macOS脚本静态检查(unittest.TestCase):
    def test_所有脚本变量名都是ASCII(self):
        脚本列表 = sorted(list(脚本目录.glob("*.sh")) + list(脚本目录.glob("*.command")))
        self.assertGreaterEqual(len(脚本列表), 2)
        for 脚本 in 脚本列表:
            问题 = 扫描违规(脚本.read_text(encoding="utf-8"))
            self.assertEqual(问题, [], f"{脚本.name} 含非 ASCII bash 变量：\n" + "\n".join(问题))

    def test_扫描器能识别旧版本的错误写法(self):
        坏样本 = "\n".join([
            '仓库根="$(pwd)"',
            "for 候选 in a b; do :; done",
            '  地址="${1:-x}"',
            'echo "$输出"',
            "read -r 答案",
            "local 标签=1",
        ])
        违规行 = {项.split(":", 1)[0] for 项 in 扫描违规(坏样本)}
        self.assertEqual(违规行, {"1", "2", "3", "4", "5", "6"})
        好样本 = "\n".join([
            '# 中文注释：仓库根=xx',
            'echo "使用 ADB=$ADB；地址=$ADDR"',
            'REPO_ROOT="$(pwd)"  # 仓库根',
            'section() { echo "===== $* ====="; }',
            'for cand in a b; do :; done',
        ])
        self.assertEqual(扫描违规(好样本), [])

    def test_脚本必须是LF换行(self):
        for 脚本 in list(脚本目录.glob("*.sh")) + list(脚本目录.glob("*.command")):
            self.assertNotIn(b"\r\n", 脚本.read_bytes(), 脚本.name)


@unittest.skipUnless(_查找bash(), "本机没有可用的 bash")
class macOS脚本bash运行检查(unittest.TestCase):
    def _运行(self, *参数, 环境=None):
        env = os.environ.copy()
        env.update(环境 or {})
        return subprocess.run(
            [_查找bash(), *参数], cwd=仓库根, env=env,
            capture_output=True, timeout=60, check=False,
        )

    def test_bash语法检查(self):
        for 脚本 in (启动脚本, 采集脚本):
            结果 = self._运行("-n", 脚本)
            self.assertEqual(结果.returncode, 0, 结果.stderr.decode("utf-8", "replace"))

    def test_启动脚本dry_run不安装不启动_且不继承offscreen(self):
        结果 = self._运行(启动脚本, "--dry-run", "--cli", "x", 环境={
            "PYTHON": Path(sys.executable).as_posix(),
            "QT_QPA_PLATFORM": "offscreen",
            "COC_EMULATOR_TYPE": "",
        })
        输出 = 结果.stdout.decode("utf-8", "replace")
        self.assertEqual(结果.returncode, 0, 结果.stderr.decode("utf-8", "replace"))
        self.assertIn("DRY-RUN python=", 输出)
        self.assertIn("qt_platform=<default>", 输出)
        self.assertIn("emulator=bluestacks", 输出)
        self.assertIn("主入口.py x", 输出)
        self.assertNotIn("command not found", 结果.stderr.decode("utf-8", "replace"))

    def test_采集脚本dry_run(self):
        结果 = self._运行(采集脚本, "--dry-run", "127.0.0.1:5565")
        输出 = 结果.stdout.decode("utf-8", "replace")
        self.assertEqual(结果.returncode, 0, 结果.stderr.decode("utf-8", "replace"))
        self.assertIn("addr=127.0.0.1:5565", 输出)
        self.assertRegex(输出, r"out=bluestacks_info_\d{8}_\d{6}\.txt")
        self.assertNotIn("not a valid identifier", 结果.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
