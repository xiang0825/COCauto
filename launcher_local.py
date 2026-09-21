"""Local launcher: correct working directory and visible startup errors."""
import os
from pathlib import Path
import runpy
import sys
import traceback

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    os.chdir(ROOT)
    os.environ.setdefault("PYTHONUTF8", "1")
    # 默认使用 MuMu；连接具体实例的地址由“模拟器连接”配置保存。
    os.environ.setdefault("COC_MUMU_DIR", r"C:\Program Files\Netease\MuMuPlayer\nx_main")
    for 输出流 in (sys.stdout, sys.stderr):
        if hasattr(输出流, "reconfigure"):
            try:
                输出流.reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass
    try:
        runpy.run_path(str(ROOT / "UI入口.py"), run_name="__main__")
    except Exception:
        with (ROOT / "startup-error.log").open("a", encoding="utf-8") as stream:
            traceback.print_exc(file=stream)
        raise
