# -*- mode: python ; coding: utf-8 -*-
import glob
import os
import subprocess
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


项目根 = os.path.abspath(SPECPATH)
版本号文件 = os.path.join(项目根, "版本号.txt")

# collect_submodules() 在 Analysis() 执行前不会自动使用 pathex；如果
# 不先加入项目根目录，它会返回空列表，导致延迟导入的任务在 EXE 中缺失。
if 项目根 not in sys.path:
    sys.path.insert(0, 项目根)

环境变量 = os.environ.copy()
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
    (os.path.join(项目根, "核心", "op-0.4.5_with_model", "tools.dll"), "op_runtime"),
    (os.path.join(项目根, "核心", "op-0.4.5_with_model", "op_x64.dll"), "op_runtime"),
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
数据文件 += 收集数据文件(
    "模块",
    扩展名={".yaml", ".yml", ".json", ".onnx", ".png", ".bmp", ".txt", ".dict"},
)
数据文件 += collect_data_files("sv_ttk")


a = Analysis(
    [os.path.join(项目根, "UI入口.py")],
    pathex=[项目根],
    binaries=[],
    datas=数据文件,
    hiddenimports=(
        collect_submodules("模块")
        + collect_submodules("核心")
        + collect_submodules("任务流程")
    ),
    hookspath=[],
    runtime_hooks=[os.path.join(项目根, "打包运行时.py")],
    excludes=[],
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
