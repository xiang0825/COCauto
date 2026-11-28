# -*- mode: python ; coding: utf-8 -*-
import glob
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.hooks.setuptools import setuptools_info


项目根 = os.path.abspath(SPECPATH)
版本号文件 = os.path.join(项目根, "版本号.txt")

# collect_submodules() 在 Analysis() 执行前不会自动使用 pathex；
# 必须先把项目根目录加入 sys.path，避免延迟导入的任务与服务模块缺失。
if 项目根 not in sys.path:
    sys.path.insert(0, 项目根)

if not os.path.isfile(版本号文件):
    raise FileNotFoundError(f"缺少版本号文件：{版本号文件}")

with open(版本号文件, "r", encoding="utf-8") as _版本句柄:
    版本号 = _版本句柄.read().strip()

if not 版本号:
    raise ValueError(f"版本号文件为空：{版本号文件}")


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
    (
        os.path.join(
            项目根, "模块", "检测", "OCR识别器", "rapidocr_onnxruntime", "config.yaml"
        ),
        "模块/检测/OCR识别器/rapidocr_onnxruntime",
    ),
    (
        os.path.join(项目根, "模块", "检测", "YOLO检测器", "模型", "best.onnx"),
        "模块/检测/YOLO检测器/模型",
    ),
    (
        os.path.join(项目根, "任务流程", "战宠升级", "模型", "战宠小屋检测模块.onnx"),
        "任务流程/战宠升级/模型",
    ),
    (os.path.join(项目根, "任务流程", "战宠升级", "img.png"), "任务流程/战宠升级"),
    (版本号文件, "."),
    (os.path.join(项目根, "界面", "城控.ico"), "."),
]
数据文件 += 收集数据文件("资源", 扩展名={".json", ".png", ".bmp"})
数据文件 += 收集数据文件(
    "模块",
    扩展名={".yaml", ".yml", ".json", ".onnx", ".png", ".bmp", ".txt", ".dict"},
)
数据文件 += collect_data_files("certifi")

图标路径 = os.path.join(项目根, "界面", "城控.ico")

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
        + collect_submodules("工具包")
        + collect_submodules("数据库")
        + collect_submodules("线程")
        + ["PySide6.QtSvg", "certifi"]
        + (
            ["pkg_resources"]
            if setuptools_info.version and setuptools_info.version >= (71, 0)
            else collect_submodules("pkg_resources")
        )
    ),
    hookspath=[],
    runtime_hooks=[os.path.join(项目根, "打包运行时.py")],
    excludes=["tkinter", "_tkinter", "sv_ttk"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="COCauto",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="COCauto",
)

app = BUNDLE(
    coll,
    name="COCauto.app",
    icon=图标路径 if os.path.isfile(图标路径) else None,
    bundle_identifier="com.xiang0825.cocauto",
    version=版本号,
    info_plist={
        "CFBundleName": "COCauto",
        "CFBundleDisplayName": "COCauto",
        "CFBundleIdentifier": "com.xiang0825.cocauto",
        "CFBundleVersion": 版本号,
        "CFBundleShortVersionString": 版本号,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
    },
)
