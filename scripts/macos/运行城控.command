#!/bin/bash
# macOS 源码运行城控（BlueStacks Air）。Finder 里双击或在终端执行：
#   bash scripts/macos/运行城控.command            # 打开桌面控制台
#   bash scripts/macos/运行城控.command --cli ...  # 运行 主入口.py（命令行）
# 首次运行会在仓库根目录创建 .venv-mac 并安装 requirements-macos.txt。
set -euo pipefail

仓库根="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$仓库根"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for 候选 in python3.11 /opt/homebrew/bin/python3.11 python3; do
    if command -v "$候选" >/dev/null 2>&1; then PY="$候选"; break; fi
  done
fi
if [ -z "$PY" ]; then
  echo "未找到 Python 3.11。请先执行：brew install python@3.11" >&2
  exit 1
fi

if [ ! -x .venv-mac/bin/python ]; then
  echo "首次运行：创建 .venv-mac 并安装依赖（需要联网，几分钟）……"
  "$PY" -m venv .venv-mac
  .venv-mac/bin/python -m pip install --upgrade pip
  .venv-mac/bin/python -m pip install -r requirements-macos.txt
fi

if ! command -v adb >/dev/null 2>&1 \
  && [ ! -x "/Applications/BlueStacks.app/Contents/MacOS/hd-adb" ] \
  && [ -z "${ANDROID_ADB:-}" ]; then
  echo "提示：未找到 adb。可执行 brew install android-platform-tools，或设置 ANDROID_ADB=<adb 路径>。" >&2
fi

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
# Mac 上只支持 BlueStacks（纯 ADB）；需要临时改回可自行覆盖。
export COC_EMULATOR_TYPE="${COC_EMULATOR_TYPE:-bluestacks}"

if [ "${1:-}" = "--cli" ]; then
  shift
  exec .venv-mac/bin/python -X utf8 主入口.py "$@"
fi
exec .venv-mac/bin/python -X utf8 UI入口.py "$@"
