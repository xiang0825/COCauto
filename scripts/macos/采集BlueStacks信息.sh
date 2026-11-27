#!/bin/bash
# 只读采集 BlueStacks Air 的 ADB 信息，供适配用。不点击、不发送任何输入、不安装/关闭应用。
#   bash scripts/macos/采集BlueStacks信息.sh [地址，默认 127.0.0.1:5555]
#   bash scripts/macos/采集BlueStacks信息.sh --dry-run [地址]   # 只打印将使用的 adb/地址/输出文件
# 结果写到当前目录 bluestacks_info_<时间>.txt，把这个文件和 screencap.png 发回即可。
# 说明：会执行一次 adb connect（改变 adb server 的连接状态，不影响模拟器和游戏）。
# 计时用 macOS 自带的 perl（不用 /usr/bin/python3：未装 Xcode CLT 时会弹安装对话框）。
# 注意：bash 变量名必须是 ASCII，中文只能出现在字符串和注释里。
set -uo pipefail

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
  shift
fi
ADDR="${1:-127.0.0.1:5555}"

BREW_ADB="$(command -v adb 2>/dev/null || true)"
HD_ADB=""
for cand in /Applications/BlueStacks*.app/Contents/MacOS/hd-adb \
  /Applications/BlueStacks*.app/Contents/MacOS/HD-Adb; do
  if [ -x "$cand" ]; then HD_ADB="$cand"; break; fi
done
ADB="${ANDROID_ADB:-}"
if [ -z "$ADB" ]; then
  for cand in "$BREW_ADB" "$HD_ADB" /opt/homebrew/bin/adb; do
    if [ -n "$cand" ] && [ -x "$cand" ]; then ADB="$cand"; break; fi
  done
fi
OUT="bluestacks_info_$(date +%Y%m%d_%H%M%S).txt"

if [ "$DRY_RUN" = "1" ]; then
  echo "DRY-RUN adb=${ADB:-<not found>} brew_adb=${BREW_ADB:-<none>} hd_adb=${HD_ADB:-<none>}"
  echo "DRY-RUN addr=$ADDR out=$OUT"
  exit 0
fi
if [ -z "$ADB" ]; then
  echo "未找到 adb：请先 brew install android-platform-tools，或设置 ANDROID_ADB=<adb 路径>。" >&2
  exit 1
fi

section() { echo; echo "===== $* ====="; }
now_ms() { perl -MTime::HiRes=time -e 'printf("%d\n", time()*1000)'; }

time_screencap() {
  # $1 = 标签；对三种截图方式各计时 3 次
  local label="$1" mode i t0 t1 nbytes
  for mode in "screencap" "screencap -p" "screencap | gzip -1"; do
    for i in 1 2 3; do
      t0="$(now_ms)"
      nbytes="$("$ADB" -s "$ADDR" exec-out "$mode" | wc -c | tr -d ' ')"
      t1="$(now_ms)"
      echo "[$label] $mode: ${nbytes} bytes, $((t1 - t0)) ms"
    done
  done
}

bluestacks_state() {
  # 记录 BlueStacks 进程状态（App Nap 会降低被遮挡/最小化窗口的进程优先级）。只读。
  ps -axo pid,stat,pcpu,rss,comm | grep -i "[b]luestacks" || echo "(未找到 BlueStacks 进程)"
  pmset -g assertions 2>/dev/null | grep -iE "PreventUserIdleSystemSleep|PreventSystemSleep" | head -5
}

{
  section "系统"; sw_vers; uname -m
  section "BlueStacks 安装"; ls -d /Applications/BlueStacks*.app 2>&1
  for app in /Applications/BlueStacks*.app; do
    [ -d "$app" ] || continue
    ls "$app/Contents/MacOS" 2>&1
    bundle_id="$(mdls -raw -name kMDItemCFBundleIdentifier "$app" 2>/dev/null || true)"
    echo "bundle_id=$bundle_id"
    if [ -n "$bundle_id" ]; then
      echo "NSAppSleepDisabled=$(defaults read "$bundle_id" NSAppSleepDisabled 2>/dev/null || echo '<未设置>')"
    fi
  done
  ls "/Users/Shared/Library/Application Support/" 2>&1 | grep -i blue
  find "/Users/Shared/Library/Application Support" -maxdepth 3 -name "bluestacks.conf" 2>/dev/null
  for conf in "/Users/Shared/Library/Application Support"/BlueStacks*/bluestacks.conf; do
    [ -f "$conf" ] && grep -E "adb_port|display_width|display_height|dpi|status\.ip" "$conf"
  done
  section "监听端口"; lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | grep -iE "bluestacks|hd-|:555" || true
  section "adb 版本（brew adb 与 BlueStacks hd-adb）"
  echo "使用 ADB=$ADB"
  if [ -n "$BREW_ADB" ]; then echo "brew/PATH adb: $BREW_ADB"; "$BREW_ADB" version; else echo "brew/PATH adb: <none>"; fi
  if [ -n "$HD_ADB" ]; then echo "hd-adb: $HD_ADB"; "$HD_ADB" version; else echo "hd-adb: <none>"; fi
  section "connect"; "$ADB" connect "$ADDR"
  section "devices"; "$ADB" devices -l
  section "getprop"; "$ADB" -s "$ADDR" shell getprop | grep -iE "ro.product|ro.build.version|ro.hardware|bst|bluestacks|abi" | head -60
  section "wm size/density"; "$ADB" -s "$ADDR" shell wm size; "$ADB" -s "$ADDR" shell wm density
  section "display"; "$ADB" -s "$ADDR" shell dumpsys display | grep -iE "mDisplayId|DisplayDeviceInfo|uniqueId" | head -20
  section "getevent -lp（触摸设备，用于双指缩放）"; "$ADB" -s "$ADDR" shell getevent -lp
  section "/dev/input 权限"; "$ADB" -s "$ADDR" shell ls -l /dev/input; "$ADB" -s "$ADDR" shell id
  section "前台"; "$ADB" -s "$ADDR" shell dumpsys activity top-resumed 2>&1 | head -20
  section "CoC 安装"; "$ADB" -s "$ADDR" shell pm list packages | grep -i supercell
  section "BlueStacks 窗口可见时的进程状态"; bluestacks_state
  section "screencap 速度：窗口可见"; time_screencap "可见"
  "$ADB" -s "$ADDR" exec-out screencap -p > screencap.png && echo "已保存 screencap.png"
} > "$OUT" 2>&1

# App Nap：窗口最小化/被遮挡时 macOS 可能降低 BlueStacks 优先级，截图变慢甚至黑屏。
# 只有在终端交互运行时才询问，非交互运行直接跳过。
if [ -t 0 ]; then
  echo "请把 BlueStacks 窗口最小化（或用其他窗口完全挡住），然后按回车继续；直接输入 s 回车跳过。"
  read -r answer
  if [ "${answer:-}" != "s" ]; then
    {
      section "BlueStacks 窗口最小化/遮挡时的进程状态"; bluestacks_state
      section "screencap 速度：窗口最小化/遮挡"; time_screencap "最小化"
      "$ADB" -s "$ADDR" exec-out screencap -p > screencap_minimized.png && echo "已保存 screencap_minimized.png"
    } >> "$OUT" 2>&1
    echo "采集完成，请把 BlueStacks 窗口恢复显示。"
  else
    echo "(已跳过最小化测试)" >> "$OUT"
  fi
else
  echo "(非交互运行，未做最小化测试)" >> "$OUT"
fi

echo "完成：$OUT（以及 screencap.png）"
