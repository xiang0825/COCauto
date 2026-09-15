"""Windows 打包版的基础运行环境。"""
import os
import sys


if getattr(sys, "frozen", False):
    # 以 exe 所在目录为工作目录，保证数据库、日志和相对路径稳定。
    os.chdir(os.path.dirname(os.path.abspath(sys.executable)))
    # 单文件解包目录每次启动都会变化；持久数据要放在 EXE 所在目录。
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "数据库"), exist_ok=True)
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
