import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from 工具包 import 版本管理
from 工具包.版本管理 import 获取本地版本号, 准备版本号生成环境


class 打包版本号环境测试(unittest.TestCase):
    def test_源码版本文件优先于旧git标签(self):
        with tempfile.TemporaryDirectory(prefix="coc-version-source-") as 临时目录:
            根目录 = Path(临时目录)
            模块目录 = 根目录 / "工具包"
            模块目录.mkdir()
            (根目录 / "版本号.txt").write_text("rc118\n", encoding="utf-8")
            模块路径 = 模块目录 / "版本管理.py"

            with patch.object(版本管理, "__file__", str(模块路径)), patch.object(
                版本管理.subprocess,
                "check_output",
                return_value="v2026.11.18-rc110",
            ):
                self.assertEqual(获取本地版本号(), "rc118")
                self.assertEqual(版本管理.获取本地易读版本号(), "版本 rc118")

    def _生成版本(self, 项目根, 环境变量):
        生成脚本 = (
            Path(__file__).resolve().parents[1]
            / "工具包"
            / "生成版本号文件.py"
        )
        结果 = subprocess.run(
            [sys.executable, str(生成脚本)],
            cwd=项目根,
            env=环境变量,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(结果.returncode, 0, 结果.stderr.decode(errors="replace"))
        return Path(项目根, "版本号.txt").read_text(encoding="utf-8")

    def test_打包默认保留文件中的候选版本(self):
        with tempfile.TemporaryDirectory(prefix="coc-version-test-") as 临时目录:
            Path(临时目录, "版本号.txt").write_text("rc83", encoding="utf-8")
            with patch.dict(os.environ, {"COC_RELEASE_VERSION": ""}):
                环境变量 = 准备版本号生成环境(临时目录)
            self.assertEqual(环境变量["COC_RELEASE_VERSION"], "rc83")
            self.assertEqual(self._生成版本(临时目录, 环境变量), "rc83")

    def test_显式发布版本仍优先于文件版本(self):
        with tempfile.TemporaryDirectory(prefix="coc-version-test-") as 临时目录:
            Path(临时目录, "版本号.txt").write_text("rc83", encoding="utf-8")
            with patch.dict(os.environ, {"COC_RELEASE_VERSION": "rc84"}):
                环境变量 = 准备版本号生成环境(临时目录)

            self.assertEqual(环境变量["COC_RELEASE_VERSION"], "rc84")
            self.assertEqual(self._生成版本(临时目录, 环境变量), "rc84")

    def test_打包版本显示运行中exe的短哈希(self):
        with tempfile.TemporaryDirectory(prefix="coc-version-display-") as 临时目录:
            根目录 = Path(临时目录)
            (根目录 / "版本号.txt").write_text("rc83", encoding="utf-8")
            可执行文件 = 根目录 / "部落冲突.exe"
            可执行文件.write_bytes(b"current executable bytes")
            短哈希 = hashlib.sha256(可执行文件.read_bytes()).hexdigest()[:8]

            with patch.object(sys, "_MEIPASS", str(根目录), create=True), patch.object(
                sys, "executable", str(可执行文件)
            ):
                版本号 = 获取本地版本号()

            self.assertEqual(版本号, f"rc83 · {短哈希}")


if __name__ == "__main__":
    unittest.main()
