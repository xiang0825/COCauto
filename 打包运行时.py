"""Windows 打包版的基础运行环境。"""
import ctypes
import os
import sys


if getattr(sys, "frozen", False):
    # 以 exe 所在目录为工作目录，保证数据库、日志和相对路径稳定。
    程序目录 = os.path.dirname(os.path.abspath(sys.executable))
    内部目录 = os.path.join(程序目录, "_internal")
    os.chdir(程序目录)

    # PyInstaller 6 的 onedir 包会把原生 DLL 放进 _internal。Windows 在
    # 不同版本/不同安全策略下对“由 DLL 再加载 DLL”的搜索路径并不完全
    # 一致，尤其会影响 onnxruntime、OpenCV 和 OCR。启动早期显式加入
    # 目录，避免运行到一半才出现“LoadLibrary: module not found”。
    if os.path.isdir(内部目录):
        try:
            os.add_dll_directory(内部目录)
        except (AttributeError, OSError):
            pass
        os.environ["PATH"] = 内部目录 + os.pathsep + os.environ.get("PATH", "")
        try:
            ctypes.windll.kernel32.SetDllDirectoryW(内部目录)
        except (AttributeError, OSError):
            pass

    # 单文件解包目录每次启动都会变化；持久数据要放在 EXE 所在目录。
    os.makedirs(os.path.join(程序目录, "数据库"), exist_ok=True)
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    雷电默认目录 = r"E:\LDPlayer\LDPlayer14"
    if os.path.isdir(雷电默认目录):
        os.environ.setdefault("COC_LDPLAYER_DIR", 雷电默认目录)

# 无控制台的 GUI 程序仍会调用 print；将输出安全丢弃，避免 None stdout 导致线程异常。
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
