"""macOS frozen .app 数据目录路由与打包配置单测。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings

from 应用 import 异常留证
from 工具包 import 运行路径
from 数据库.任务数据库 import 任务数据库
from 模块.运行节流与复盘 import 低星战局复盘记录器
from 应用.现场图服务 import 现场图服务
from 界面 import 主窗口 as 主窗口模块


class macOS数据目录路由测试(unittest.TestCase):
    def test_macOS打包态全部可写目录路由到ApplicationSupport且不写app内部(self):
        with tempfile.TemporaryDirectory(prefix="coc-mac-home-") as 临时家目录, \
                tempfile.TemporaryDirectory(prefix="coc-mac-app-") as 临时包目录:
            假家目录 = Path(临时家目录)
            假App可执行 = Path(临时包目录) / "COCauto.app" / "Contents" / "MacOS" / "COCauto"
            假App可执行.parent.mkdir(parents=True)
            假App可执行.write_bytes(b"")
            期望数据根 = 假家目录 / "Library" / "Application Support" / "COCauto"

            with patch.object(sys, "platform", "darwin"), \
                    patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "executable", str(假App可执行)), \
                    patch("工具包.运行路径.Path.home", return_value=假家目录), \
                    patch.dict(os.environ, {"COCAUTO_DB_PATH": ""}, clear=False):
                self.assertTrue(运行路径.是macOS打包环境())
                self.assertEqual(运行路径.可写数据根目录(), 期望数据根)
                self.assertTrue(期望数据根.is_dir())

                数据库路径 = Path(任务数据库.默认数据库路径())
                self.assertEqual(数据库路径, 期望数据根 / "数据库" / "任务系统.db")
                self.assertTrue(数据库路径.parent.is_dir())

                self.assertEqual(异常留证.程序目录(), 期望数据根)
                self.assertEqual(异常留证.异常现场根目录(), 期望数据根 / "异常现场")

                设置 = 主窗口模块.界面设置()
                self.assertEqual(设置.format(), QSettings.IniFormat)
                self.assertEqual(Path(设置.fileName()), 期望数据根 / "settings.ini")

                复盘记录器 = 低星战局复盘记录器()
                self.assertEqual(复盘记录器.输出目录, 期望数据根 / "数据集" / "低星复盘")

                现场服务 = 现场图服务()
                self.assertEqual(
                    现场服务._目录映射,
                    (
                        ("待命现场", 期望数据根 / "数据集" / "待命现场"),
                        ("低星复盘", 期望数据根 / "数据集" / "低星复盘"),
                    ),
                )

                self.assertEqual(
                    运行路径.解析数据子路径("自检报告.txt"),
                    期望数据根 / "自检报告.txt",
                )

            # .app 包内部不能产生任何新目录或文件
            self.assertEqual(
                [项.name for 项 in 假App可执行.parent.iterdir()],
                ["COCauto"],
            )

    def test_macOS打包态显式数据库环境变量仍优先(self):
        with tempfile.TemporaryDirectory(prefix="coc-mac-env-") as 临时目录:
            根 = Path(临时目录)
            显式库 = 根 / "custom" / "任务系统.db"
            假App可执行 = 根 / "COCauto.app" / "Contents" / "MacOS" / "COCauto"
            with patch.object(sys, "platform", "darwin"), \
                    patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "executable", str(假App可执行)), \
                    patch.dict(os.environ, {"COCAUTO_DB_PATH": str(显式库)}, clear=False):
                self.assertEqual(Path(任务数据库.默认数据库路径()), 显式库.resolve())

    def test_Windows打包态与非frozen开发态行为保持不变(self):
        with tempfile.TemporaryDirectory(prefix="coc-win-exe-") as 临时目录:
            假Exe = Path(临时目录) / "部落冲突.exe"
            with patch.object(sys, "platform", "win32"), \
                    patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "executable", str(假Exe)), \
                    patch.dict(os.environ, {"COCAUTO_DB_PATH": ""}, clear=False):
                self.assertFalse(运行路径.是macOS打包环境())
                self.assertIsNone(运行路径.可写数据根目录())
                self.assertEqual(
                    Path(任务数据库.默认数据库路径()),
                    Path(临时目录) / "数据库" / "任务系统.db",
                )
                self.assertEqual(异常留证.程序目录(), Path(临时目录))
                self.assertEqual(低星战局复盘记录器().输出目录, Path("数据集") / "低星复盘")
                self.assertEqual(运行路径.解析数据子路径("自检报告.txt"), Path("自检报告.txt"))
                self.assertEqual(主窗口模块.界面设置().format(), QSettings.NativeFormat)

        # macOS 非 frozen 开发态不受影响
        with patch.object(sys, "platform", "darwin"), \
                patch.object(sys, "frozen", False, create=True):
            self.assertFalse(运行路径.是macOS打包环境())
            self.assertIsNone(运行路径.可写数据根目录())
            self.assertEqual(异常留证.程序目录(), Path(__file__).resolve().parents[1])
            self.assertEqual(低星战局复盘记录器().输出目录, Path("数据集") / "低星复盘")
            self.assertEqual(运行路径.解析数据子路径("自检报告.txt"), Path("自检报告.txt"))

    def test_mac打包spec包含必需元数据与配置(self):
        项目根 = Path(__file__).resolve().parents[1]
        spec内容 = (项目根 / "自动脚本_mac.spec").read_text(encoding="utf-8")
        self.assertIn('name="COCauto.app"', spec内容)
        self.assertIn('bundle_identifier="com.xiang0825.cocauto"', spec内容)
        self.assertIn('target_arch="arm64"', spec内容)
        self.assertIn("版本号.txt", spec内容)
        self.assertIn("打包运行时.py", spec内容)
        self.assertIn("certifi", spec内容)
        脚本内容 = (项目根 / "打包Mac应用.sh").read_text(encoding="utf-8")
        self.assertIn("codesign --force --deep --sign -", 脚本内容)
        self.assertIn("codesign --verify --deep --strict", 脚本内容)


if __name__ == "__main__":
    unittest.main()
