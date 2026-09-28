import os
import sys
import subprocess
import re

def 获取本地版本号():
    """
    获取版本号，优先从 git tag 获取，支持打包环境读取版本文件。
    返回最简洁的版本号（tag 名），如果 HEAD 不在 tag 上，则返回最近 tag。
    失败时返回本地版本文件内容或“本地版”。
    """
    是否打包环境 = hasattr(sys, '_MEIPASS')
    当前目录 = sys._MEIPASS if 是否打包环境 else os.path.dirname(os.path.abspath(__file__))
    版本路径 = os.path.join(当前目录, "版本号.txt")

    if 是否打包环境 and os.path.exists(版本路径):
        with open(版本路径, "r", encoding="utf-8") as f:
            return f.read().strip()

    try:
        简洁版本号 = subprocess.check_output(
            ["git", "describe", "--tags", "--exact-match"],
            stderr=subprocess.DEVNULL, encoding="utf-8"
        ).strip()
        return 简洁版本号
    except subprocess.CalledProcessError:
        pass

    try:
        复杂版本号 = subprocess.check_output(
            ["git", "describe", "--tags"],
            stderr=subprocess.DEVNULL, encoding="utf-8"
        ).strip()
        return 复杂版本号.split("-")[0]
    except Exception:
        pass

    if os.path.exists(版本路径):
        with open(版本路径, "r", encoding="utf-8") as f:
            return f.read().strip()

    return "本地版"

def 获取本地易读版本号():
    """
    返回更易读的版本号字符串。
    解析 git describe --tags --always --dirty 的输出，显示正式版或开发版说明。
    打包环境从 VERSION.txt 读取。
    """
    是否打包 = hasattr(sys, '_MEIPASS')
    当前目录 = sys._MEIPASS if 是否打包 else os.path.dirname(os.path.abspath(__file__))
    版本路径 = os.path.join(当前目录, "版本号.txt")

    if 是否打包 and os.path.exists(版本路径):
        with open(版本路径, "r", encoding="utf-8") as f:
            原始版本 = f.read().strip()
    else:
        try:
            原始版本 = subprocess.check_output(
                ["git", "describe", "--tags", "--always", "--dirty"],
                stderr=subprocess.DEVNULL,
                encoding="utf-8"
            ).strip()
        except Exception:
            原始版本 = "本地版"

    匹配 = re.match(r"^(v[\d\.]+)(?:-(\d+)-g([0-9a-f]+))?(-dirty)?$", 原始版本)

    if not 匹配:
        # 没有可用 Git 标签时，提交哈希对普通用户没有帮助；保留“本地版”
        # 语义，避免关于窗口出现看似未完成的 unknown/哈希字符串。
        if 原始版本.startswith("本地版") or re.fullmatch(r"[0-9a-f]{7,}(-dirty)?", 原始版本):
            后缀 = "（含未提交修改）" if 原始版本.endswith("-dirty") else ""
            return f"版本 本地版{后缀}"
        return f"版本 {原始版本}"

    tag版本, 提交数, 哈希, 是否脏 = 匹配.groups()

    if 提交数 is None:
        return f"版本 {tag版本}（正式版）"
    else:
        附加说明 = f"开发版，+{提交数} 提交，当前为 {哈希}"
        if 是否脏:
            附加说明 += "，含未提交修改"
        return f"版本 {tag版本}（{附加说明}）"

if __name__ == "__main__":
    print("简洁版本号:", 获取本地版本号())
    print("易读版本号:", 获取本地易读版本号())
