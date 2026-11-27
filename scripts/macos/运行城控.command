#!/bin/bash
# macOS 源码运行城控（BlueStacks Air）。Finder 里双击或在终端执行：
#   bash scripts/macos/运行城控.command            # 打开桌面控制台
#   bash scripts/macos/运行城控.command --cli ...  # 运行 主入口.py（命令行）
#   bash scripts/macos/运行城控.command --dry-run  # 只检查环境并打印将执行的动作，不安装、不启动
# 首次运行会在仓库根目录创建 .venv-mac 并安装 requirements-macos.txt。
# 注意：bash 变量名必须是 ASCII，中文只能出现在字符串和注释里。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
  shift
fi

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for cand in python3.11 /opt/homebrew/bin/python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
  done
fi
if [ -z "$PY" ]; then
  echo "未找到 Python 3.11。请先执行：brew install python@3.11" >&2
  exit 1
fi

# onnxruntime/opencv 的 arm64 wheel 需要 Apple Silicon 原生 Python；Rosetta 下的
# x86_64 Python 能跑但会慢很多，也可能装到不同的 wheel。
PY_ARCH="$("$PY" -c 'import platform; print(platform.machine())' 2>/dev/null || echo unknown)"
if [ "$(uname -s)" = "Darwin" ] && [ "$PY_ARCH" != "arm64" ]; then
  echo "警告：$PY 的架构是 $PY_ARCH，不是 arm64 原生 Python（可能在 Rosetta 下运行）。" >&2
  echo "      建议使用 /opt/homebrew/bin/python3.11（brew install python@3.11）。" >&2
fi

# 不继承测试/远程环境里的无头设置，否则窗口不会显示。
if [ "${QT_QPA_PLATFORM:-}" = "offscreen" ]; then
  unset QT_QPA_PLATFORM
fi

ADB_HINT=""
if ! command -v adb >/dev/null 2>&1 \
  && [ ! -x "/Applications/BlueStacks.app/Contents/MacOS/hd-adb" ] \
  && [ -z "${ANDROID_ADB:-}" ]; then
  ADB_HINT="提示：未找到 adb。可执行 brew install android-platform-tools，或设置 ANDROID_ADB=<adb 路径>。"
  echo "$ADB_HINT" >&2
fi

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
# Mac 上只支持 BlueStacks（纯 ADB）；需要临时改回可自行覆盖。
export COC_EMULATOR_TYPE="${COC_EMULATOR_TYPE:-bluestacks}"

ENTRY="UI入口.py"
if [ "${1:-}" = "--cli" ]; then
  shift
  ENTRY="主入口.py"
fi

if [ "$DRY_RUN" = "1" ]; then
  echo "DRY-RUN repo=$REPO_ROOT"
  echo "DRY-RUN python=$PY arch=$PY_ARCH"
  if [ -x .venv-mac/bin/python ]; then
    echo "DRY-RUN venv=.venv-mac (exists)"
  else
    echo "DRY-RUN venv=.venv-mac (would create and pip install -r requirements-macos.txt)"
  fi
  echo "DRY-RUN emulator=$COC_EMULATOR_TYPE qt_platform=${QT_QPA_PLATFORM:-<default>}"
  echo "DRY-RUN exec .venv-mac/bin/python -X utf8 $ENTRY $*"
  exit 0
fi

if [ ! -x .venv-mac/bin/python ]; then
  echo "首次运行：创建 .venv-mac 并安装依赖（需要联网，几分钟）……"
  "$PY" -m venv .venv-mac
  .venv-mac/bin/python -m pip install --upgrade pip
  .venv-mac/bin/python -m pip install -r requirements-macos.txt
fi

exec .venv-mac/bin/python -X utf8 "$ENTRY" "$@"
