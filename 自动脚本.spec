# -*- mode: python ; coding: utf-8 -*-
import glob
import os
import subprocess
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.hooks.setuptools import setuptools_info


项目根 = os.path.abspath(SPECPATH)
版本号文件 = os.path.join(项目根, "版本号.txt")

# collect_submodules() 在 Analysis() 执行前不会自动使用 pathex；如果
# 不先加入项目根目录，它会返回空列表，导致延迟导入的任务在 EXE 中缺失。
if 项目根 not in sys.path:
    sys.path.insert(0, 项目根)

from 工具包.版本管理 import 准备版本号生成环境

环境变量 = 准备版本号生成环境(项目根)
环境变量["PYTHONIOENCODING"] = "utf-8"
subprocess.run(
    [sys.executable, os.path.join(项目根, "工具包", "生成版本号文件.py")],
    check=True,
    cwd=项目根,
    env=环境变量,
)


def 收集数据文件(目录, 扩展名=None):
    """按相对目录结构收集运行时资源，不把 Python 源码重复塞进包里。"""
    结果 = []
    for 文件 in glob.glob(os.path.join(项目根, 目录, "**", "*"), recursive=True):
        if not os.path.isfile(文件):
            continue
        if 扩展名 and os.path.splitext(文件)[1].lower() not in 扩展名:
            continue
        目标目录 = os.path.relpath(os.path.dirname(文件), 项目根)
        结果.append((文件, 目标目录))
    return 结果


数据文件 = [
    (os.path.join(项目根, "img"), "img"),
    (os.path.join(项目根, "模块", "检测", "OCR识别器", "rapidocr_onnxruntime", "config.yaml"),
     "模块/检测/OCR识别器/rapidocr_onnxruntime"),
    (os.path.join(项目根, "模块", "检测", "YOLO检测器", "模型", "best.onnx"),
     "模块/检测/YOLO检测器/模型"),
    (os.path.join(项目根, "任务流程", "战宠升级", "模型", "战宠小屋检测模块.onnx"),
     "任务流程/战宠升级/模型"),
    (os.path.join(项目根, "任务流程", "战宠升级", "img.png"), "任务流程/战宠升级"),
    (版本号文件, "."),
    (os.path.join(项目根, "界面", "城控.ico"), "."),
]
# 活动识别资源（JSON + 模板）；运行时优先读 EXE 同级 资源/，再回退 _internal。
数据文件 += 收集数据文件("资源", 扩展名={".json", ".png", ".bmp"})
数据文件 += 收集数据文件(
    "模块",
    扩展名={".yaml", ".yml", ".json", ".onnx", ".png", ".bmp", ".txt", ".dict"},
)


a = Analysis(
    [os.path.join(项目根, "UI入口.py")],
    pathex=[项目根],
    binaries=[],
    datas=数据文件,
    hiddenimports=(
        collect_submodules("模块")
        + collect_submodules("核心")
        + collect_submodules("任务流程")
        + collect_submodules("服务")
        + collect_submodules("应用")
        + collect_submodules("界面")
        # PyInstaller 会通过 pyi_rth_pkgres 导入 pkg_resources。
        # setuptools 71+ 将 vendor 模块移到 setuptools._vendor，PyInstaller
        # 自带钩子会收集它们；只显式保留入口，避免把 pkg_resources.tests
        # 一并塞进发布包。旧版 setuptools 仍按 pkg_resources._vendor 收集。
        + (
            ["pkg_resources"]
            if setuptools_info.version and setuptools_info.version >= (71, 0)
            else collect_submodules("pkg_resources")
        )
    ),
    hookspath=[],
    runtime_hooks=[os.path.join(项目根, "打包运行时.py")],
    # 界面已迁移到 PySide6；不再打包 Tk 运行库。
    excludes=["tkinter", "_tkinter", "sv_ttk"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="部落冲突",
    icon=os.path.join(项目根, "界面", "城控.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="部落冲突",
)
