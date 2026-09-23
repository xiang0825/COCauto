"""Bounded, read-only MuMu capture/page/OCR probe; never starts a task plan."""
import argparse
import json
import sys
import time
import subprocess
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ctypes
from ctypes import wintypes
import win32api
import win32process
import cv2
import numpy as np
from 核心.ADB屏幕 import ADB屏幕
from 模块.ADB设备操作类 import ADB设备操作类
from 模块.检测.模板匹配器 import 模板匹配引擎
from 模块.检测.页面识别器 import 页面识别器
from 模块.检测.OCR识别器 import 安全OCR引擎
from 任务流程.更新主世界账号资源状态 import 更新家乡资源状态任务


def readonly_runner(argv, **kwargs):
    """Prevent the normal device adapter's recovery code from mutating ADB."""
    args = list(argv[1:])
    if args[:1] == ['-s']:
        args = args[2:]
    allowed = (
        args in (['devices'], ['devices', '-l'], ['get-state'])
        or (args[:2] == ['shell', 'getprop'] and len(args) in (2, 3))
        or args in (["shell", "dumpsys", "display"],
                    ["shell", "dumpsys", "window", "displays"],
                    ["shell", "dumpsys", "activity", "activities"],
                    ["shell", "wm", "size"])
        or args == ['exec-out', 'screencap', '-p']
        or (len(args) == 5 and args[:3] == ['exec-out', 'screencap', '-d'] and args[-1] == '-p')
    )
    if not allowed:
        raise RuntimeError(f"Read-only probe blocked ADB command: {args!r}")
    return subprocess.run(argv, **kwargs)


class ReplayDevice:
    参考宽度, 参考高度 = 800, 600

    def __init__(self, path):
        self.frame = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if self.frame is None:
            raise ValueError(f"Invalid frame: {path}")

    def 获取屏幕图像cv(self, *args):
        return self.frame

    def 获取当前前台包名(self):
        return "offline replay; no device connected"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb")
    parser.add_argument("--serial")
    parser.add_argument("--frame", type=Path, help="Replay a saved frame without connecting to ADB")
    parser.add_argument("--samples", type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.samples <= 120:
        parser.error("samples must be between 1 and 120")
    sys.stdout.reconfigure(encoding="utf-8")
    if args.frame:
        device = ReplayDevice(args.frame)
    elif args.adb and args.serial:
        device = ADB设备操作类(args.adb, args.serial, runner=readonly_runner, 自动检测路径=False)
    else:
        parser.error("provide --frame or both --adb and --serial")
    screen = ADB屏幕(device)
    detector = 页面识别器(模板匹配引擎())
    ocr = 安全OCR引擎()
    reader = 更新家乡资源状态任务.__new__(更新家乡资源状态任务)
    reader.ocr引擎 = ocr
    ctx = SimpleNamespace(op=screen, 置脚本状态=lambda *a, **k: print(*a, flush=True))
    process = win32api.GetCurrentProcess()
    handle_count = ctypes.windll.kernel32.GetProcessHandleCount
    handle_count.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    handle_count.restype = wintypes.BOOL
    started = time.monotonic()
    samples = []
    try:
        for index in range(args.samples):
            tick = time.monotonic()
            frame = screen.获取屏幕图像cv(强制刷新=True)
            page = detector.识别(frame)
            resources = None
            if page.页面 == "主世界主页":
                resources = reader.识别当前资源(ctx)
            handles = wintypes.DWORD()
            if not handle_count(int(process), ctypes.byref(handles)):
                raise ctypes.WinError()
            sample = {
                "sample": index + 1, "page": page.页面,
                "resources": resources,
                "ms": round((time.monotonic() - tick) * 1000),
                "rss_mb": round(win32process.GetProcessMemoryInfo(process)['WorkingSetSize'] / 1048576, 1),
                "handles": handles.value,
            }
            samples.append(sample)
            print(json.dumps(sample, ensure_ascii=False), flush=True)
            if index + 1 < args.samples:
                time.sleep(max(0, 2 - (time.monotonic() - tick)))
        warm = samples[min(10, len(samples) - 1):]
        print(json.dumps({
            "summary": True, "samples": len(samples),
            "seconds": round(time.monotonic() - started, 1),
            "rss_warm_range_mb": [min(s['rss_mb'] for s in warm), max(s['rss_mb'] for s in warm)],
            "handle_range": [min(s['handles'] for s in samples), max(s['handles'] for s in samples)],
            "ocr_failures": sum(s['resources'] is not None and not s['resources'].get('识别成功') for s in samples),
            "foreground": device.获取当前前台包名(),
            "system_available_mb": round(win32api.GlobalMemoryStatusEx()['AvailPhys'] / 1048576),
        }, ensure_ascii=False), flush=True)
    finally:
        ocr.释放模型()
        screen.安全清理()


if __name__ == "__main__":
    main()
