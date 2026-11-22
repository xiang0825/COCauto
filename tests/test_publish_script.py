"""Release script checks for isolated, version-matched candidate packages."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import verify_packaged_modules as 模块校验


def _当前启动依赖模块():
    return 模块校验.所需启动依赖模块()


class 发布脚本测试(unittest.TestCase):
    def test_发布目录切换前后复核exe与全部运行时文件哈希(self):
        根目录 = Path(__file__).resolve().parents[1]
        脚本 = (根目录 / "发布EXE.ps1").read_text(encoding="utf-8")
        exe_move = 脚本.index(
            "Move-Item -LiteralPath $sourceExe -Destination $targetExe"
        )
        exe_hash_check = 脚本.index(
            "$actualExeHash = (Get-FileHash -LiteralPath $targetExe",
            exe_move,
        )
        manifest_check = 脚本.index(
            "Compare-Object `\n            -ReferenceObject $expectedInternalManifest",
            exe_hash_check,
        )
        deployed_verifier = 脚本.index(
            'verify_packaged_modules.py") $targetExe', manifest_check
        )
        old_package_cleanup = 脚本.index(
            "if (Test-Path -LiteralPath $oldInternal) { Remove-Item",
            deployed_verifier,
        )

        self.assertIn("$expectedExeHash", 脚本)
        self.assertIn("$expectedInternalManifest", 脚本)
        self.assertIn("Get-FileHash", 脚本)
        self.assertIn("Compare-Object", 脚本)
        self.assertIn("切换后的 _internal 文件清单或 SHA-256", 脚本)
        self.assertIn("发布目录中的 EXE 未通过模块", 脚本)
        self.assertLess(exe_move, exe_hash_check)
        self.assertLess(exe_hash_check, manifest_check)
        self.assertLess(manifest_check, deployed_verifier)
        self.assertLess(deployed_verifier, old_package_cleanup)

    def test_候选包版本必须与当前源码版本一致(self):
        with tempfile.TemporaryDirectory(prefix="coc-package-version-") as 临时目录:
            根目录 = Path(临时目录) / "source"
            内部目录 = Path(临时目录) / "package" / "_internal"
            根目录.mkdir()
            内部目录.mkdir(parents=True)
            exe = 内部目录.parent / "部落冲突.exe"
            exe.write_bytes(b"placeholder")
            (根目录 / "版本号.txt").write_text("rc116\n", encoding="utf-8")
            包版本 = 内部目录 / "版本号.txt"
            包版本.write_text("rc115\n", encoding="utf-8")

            一致, 说明 = 模块校验.校验包版本(exe, 根目录)

            self.assertFalse(一致)
            self.assertIn("rc115", 说明)
            self.assertIn("rc116", 说明)

            包版本.write_text("rc116\n", encoding="utf-8")
            一致, 说明 = 模块校验.校验包版本(exe, 根目录)

            self.assertTrue(一致)
            self.assertIn("版本匹配", 说明)

    def test_候选包缺失版本文件时拒绝发布(self):
        with tempfile.TemporaryDirectory(prefix="coc-package-version-missing-") as 临时目录:
            根目录 = Path(临时目录) / "source"
            内部目录 = Path(临时目录) / "package" / "_internal"
            根目录.mkdir()
            内部目录.mkdir(parents=True)
            exe = 内部目录.parent / "部落冲突.exe"
            exe.write_bytes(b"placeholder")
            (根目录 / "版本号.txt").write_text("rc116", encoding="utf-8")

            一致, 说明 = 模块校验.校验包版本(exe, 根目录)

            self.assertFalse(一致)
            self.assertIn("版本文件", 说明)

    def test_发布校验按当前setuptools版本选择启动钩子模块(self):
        所需模块 = _当前启动依赖模块()
        当前版本 = 模块校验.setuptools_info.version

        self.assertIn("pkg_resources", 所需模块)
        if 当前版本 and 当前版本 >= (71, 0):
            self.assertTrue(
                {
                    "setuptools._vendor.jaraco.text",
                    "setuptools._vendor.jaraco.context",
                    "setuptools._vendor.jaraco.functools",
                    "setuptools._vendor.packaging",
                }
                <= 所需模块
            )
        else:
            self.assertTrue(
                {
                    "pkg_resources._vendor.jaraco.text",
                    "pkg_resources._vendor.jaraco.context",
                    "pkg_resources._vendor.jaraco.functools",
                    "pkg_resources._vendor.appdirs",
                    "pkg_resources._vendor.packaging",
                }
                <= 所需模块
            )

    def test_发布校验支持setuptools_71及更新版本的启动钩子(self):
        with patch(
            "scripts.verify_packaged_modules.setuptools_info",
            SimpleNamespace(version=(71, 0)),
        ):
            所需模块 = _当前启动依赖模块()

        self.assertIn("pkg_resources", 所需模块)
        self.assertTrue(
            {
                "setuptools._vendor.jaraco.text",
                "setuptools._vendor.jaraco.context",
                "setuptools._vendor.jaraco.functools",
                "setuptools._vendor.packaging",
            }
            <= 所需模块
        )

    def test_发布校验支持旧版pkg_resources_vendor启动钩子(self):
        with patch(
            "scripts.verify_packaged_modules.setuptools_info",
            SimpleNamespace(version=(70, 9)),
        ):
            所需模块 = _当前启动依赖模块()

        self.assertIn("pkg_resources", 所需模块)
        self.assertTrue(
            {
                "pkg_resources._vendor.jaraco.text",
                "pkg_resources._vendor.jaraco.context",
                "pkg_resources._vendor.jaraco.functools",
                "pkg_resources._vendor.appdirs",
                "pkg_resources._vendor.packaging",
            }
            <= 所需模块
        )

    def test_worktree发布必须显式指定目标目录(self):
        PowerShell = shutil.which("pwsh") or shutil.which("powershell")
        if not PowerShell:
            self.skipTest("需要 PowerShell 才能验证 Windows 发布脚本")

        根目录 = Path(__file__).resolve().parents[1]
        if not (根目录 / ".git").is_file():
            self.skipTest("当前 checkout 不是 Git worktree")

        with tempfile.TemporaryDirectory(prefix="coc-release-target-") as 临时目录:
            结果 = subprocess.run(
                [
                    PowerShell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(根目录 / "发布EXE.ps1"),
                    "-PackageDirectory",
                    临时目录,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )

            self.assertNotEqual(结果.returncode, 0)
            self.assertIn(
                "必须显式指定 ReleaseDirectory",
                结果.stdout + 结果.stderr,
            )

    def test_可指定隔离解释器且校验失败不碰发布目录(self):
        PowerShell = shutil.which("pwsh") or shutil.which("powershell")
        if not PowerShell:
            self.skipTest("需要 PowerShell 才能验证 Windows 发布脚本")

        根目录 = Path(__file__).resolve().parents[1]
        发布脚本 = 根目录 / "发布EXE.ps1"

        with tempfile.TemporaryDirectory(prefix="coc-release-isolation-") as 临时目录:
            临时根目录 = Path(临时目录)
            软件包 = 临时根目录 / "package"
            发布目录 = 临时根目录 / "release"
            内部目录 = 软件包 / "部落冲突" / "_internal"
            内部目录.mkdir(parents=True)
            发布目录.mkdir()
            (软件包 / "部落冲突" / "部落冲突.exe").write_bytes(b"not an executable archive")
            运行时版本 = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
            (内部目录 / 运行时版本).write_bytes(b"\0" * 5_000_001)
            哨兵 = 发布目录 / "keep.txt"
            哨兵.write_text("existing release files stay untouched", encoding="utf-8")

            结果 = subprocess.run(
                [
                    PowerShell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(发布脚本),
                    "-PackageDirectory",
                    str(软件包),
                    "-ReleaseDirectory",
                    str(发布目录),
                    "-VerifierPython",
                    sys.executable,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )

            self.assertNotEqual(结果.returncode, 0)
            self.assertIn(
                "发布包模块或源码一致性校验失败",
                结果.stdout + 结果.stderr,
            )
            self.assertTrue(哨兵.is_file())
            self.assertFalse((发布目录 / "部落冲突.exe").exists())
            self.assertFalse((发布目录 / "_internal").exists())


if __name__ == "__main__":
    unittest.main()
