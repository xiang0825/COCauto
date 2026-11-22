import hashlib
import os
import sys
import subprocess
import re
from functools import lru_cache


@lru_cache(maxsize=4)
def _获取可执行文件短哈希(路径):
    """流式读取当前程序文件，给打包版提供可与 EXE 核对的短标识。"""
    摘要 = hashlib.sha256()
    with open(路径, "rb") as 文件:
        for 块 in iter(lambda: 文件.read(1024 * 1024), b""):
            摘要.update(块)
    return 摘要.hexdigest()[:8]


def 准备版本号生成环境(项目根, 环境变量=None):
    """优先保留项目明确记录的发布版本，显式环境变量仍可覆盖。"""
    环境 = dict(os.environ if 环境变量 is None else 环境变量)
    if str(环境.get("COC_RELEASE_VERSION", "") or "").strip():
        return 环境

    版本路径 = os.path.join(项目根, "版本号.txt")
    if os.path.isfile(版本路径):
        with open(版本路径, "r", encoding="utf-8") as 文件:
            版本号 = 文件.read().strip()
        if 版本号:
            环境["COC_RELEASE_VERSION"] = 版本号
    return 环境


def _获取版本文件路径():
    """返回发布版本文件路径；源码下取项目根，打包后取运行库根。"""
    if hasattr(sys, "_MEIPASS"):
        项目根 = sys._MEIPASS
    else:
        项目根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(项目根, "版本号.txt")


def 获取本地版本号():
    """
    优先读取源码/安装包声明的版本；没有版本文件时再回退到 Git 标签。
    """
    是否打包环境 = hasattr(sys, '_MEIPASS')
    版本路径 = _获取版本文件路径()

    if 是否打包环境 and os.path.exists(版本路径):
        with open(版本路径, "r", encoding="utf-8") as f:
            版本号 = f.read().strip()
        if 版本号:
            try:
                短哈希 = _获取可执行文件短哈希(sys.executable)
            except OSError:
                短哈希 = ""
            if 短哈希:
                return f"{版本号} · {短哈希}"
        return 版本号

    if os.path.isfile(版本路径):
        with open(版本路径, "r", encoding="utf-8") as f:
            版本号 = f.read().strip()
        if 版本号:
            return 版本号

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
    返回与源码/安装包版本文件一致的易读版本号；缺失时回退到 Git 描述。
    """
    是否打包 = hasattr(sys, '_MEIPASS')
    版本路径 = _获取版本文件路径()

    if os.path.exists(版本路径):
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
