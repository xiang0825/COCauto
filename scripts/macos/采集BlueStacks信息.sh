#!/bin/bash
# 只读采集 BlueStacks Air 的 ADB 信息，供适配用。不点击、不发送任何输入、不安装/关闭应用。
#   bash scripts/macos/采集BlueStacks信息.sh [地址，默认 127.0.0.1:5555]
# 结果写到当前目录 bluestacks_信息_<时间>.txt，把这个文件和 screencap.png 发回即可。
set -uo pipefail

地址="${1:-127.0.0.1:5555}"
ADB="${ANDROID_ADB:-}"
if [ -z "$ADB" ]; then
  for 候选 in "$(command -v adb 2>/dev/null)" \
    "/Applications/BlueStacks.app/Contents/MacOS/hd-adb" \
    "/Applications/BlueStacks.app/Contents/MacOS/HD-Adb" \
    "/opt/homebrew/bin/adb"; do
    if [ -n "$候选" ] && [ -x "$候选" ]; then ADB="$候选"; break; fi
  done
fi
输出="bluestacks_信息_$(date +%Y%m%d_%H%M%S).txt"
段() { echo; echo "===== $* ====="; }

{
  段 "系统"; sw_vers; uname -m
  段 "BlueStacks 安装"; ls -d /Applications/BlueStacks*.app 2>&1
  ls /Applications/BlueStacks*.app/Contents/MacOS 2>&1
  ls "/Users/Shared/Library/Application Support/" 2>&1 | grep -i blue
  find "/Users/Shared/Library/Application Support" -maxdepth 3 -name "bluestacks.conf" 2>/dev/null
  for 配置 in "/Users/Shared/Library/Application Support"/BlueStacks*/bluestacks.conf; do
    [ -f "$配置" ] && grep -E "adb_port|display_width|display_height|dpi|status\.ip" "$配置"
  done
  段 "监听端口"; lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | grep -iE "bluestacks|hd-|:555" || true
  段 "adb"; echo "ADB=$ADB"; "$ADB" version
  段 "connect"; "$ADB" connect "$地址"
  段 "devices"; "$ADB" devices -l
  S=("$ADB" -s "$地址")
  段 "getprop"; "${S[@]}" shell getprop | grep -iE "ro.product|ro.build.version|ro.hardware|bst|bluestacks|abi" | head -60
  段 "wm size/density"; "${S[@]}" shell wm size; "${S[@]}" shell wm density
  段 "display"; "${S[@]}" shell dumpsys display | grep -iE "mDisplayId|DisplayDeviceInfo|uniqueId" | head -20
  段 "getevent -lp（触摸设备，用于双指缩放）"; "${S[@]}" shell getevent -lp
  段 "/dev/input 权限"; "${S[@]}" shell ls -l /dev/input; "${S[@]}" shell id
  段 "前台"; "${S[@]}" shell dumpsys activity top-resumed 2>&1 | head -20
  段 "CoC 安装"; "${S[@]}" shell pm list packages | grep -i supercell
  段 "screencap 速度（各 3 次）"
  for 方式 in "screencap" "screencap -p" "screencap | gzip -1"; do
    for i in 1 2 3; do
      开始=$(python3 -c 'import time;print(time.time())')
      字节=$("${S[@]}" exec-out "$方式" | wc -c)
      结束=$(python3 -c 'import time;print(time.time())')
      echo "$方式: ${字节} bytes, $(python3 -c "print(round(($结束-$开始)*1000))") ms"
    done
  done
  "${S[@]}" exec-out screencap -p > screencap.png && echo "已保存 screencap.png"
} > "$输出" 2>&1

echo "完成：$输出（以及 screencap.png）"
