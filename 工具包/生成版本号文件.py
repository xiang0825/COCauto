# -*- coding: utf-8 -*-
import subprocess
import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def 获取简洁版本号():
    try:
        # HEAD 正好在 tag 上
        版本号 = subprocess.check_output(
            ["git", "describe", "--tags", "--exact-match"],
            stderr=subprocess.DEVNULL, encoding="utf-8"
        ).strip()
    except subprocess.CalledProcessError:
        try:
            # 获取最近的 tag 名称（不含后缀）
            版本号 = subprocess.check_output(
                ["git", "describe", "--tags"],
                stderr=subprocess.DEVNULL, encoding="utf-8"
            ).strip().split("-")[0]
        except Exception:
            版本号 = "unknown"
    return 版本号

def 写入版本文件():
    版本号 = 获取简洁版本号()
    with open("./版本号.txt", "w", encoding="utf-8") as f:
        f.write(版本号)
    print(f"版本号写入完成：{版本号}")

if __name__ == "__main__":
    写入版本文件()
