"""Windows 桌面通知（右下角 toast），作为企业微信之外的通知渠道。

实现要点：
- 不引入任何第三方依赖：后台启动一个隐藏的 PowerShell 进程，在屏幕右下角
  显示一个置顶、不抢焦点的小窗（WinForms），并用系统 WinRT toast 在通知
  中心静默留档。Windows 勿扰模式会吞掉普通 toast 弹窗，所以可见提醒用
  自绘小窗。打包后的 exe 不需要额外模块。
- 标题/正文经环境变量传给 PowerShell，脚本本体固定，杜绝命令注入。
- ``subprocess.Popen`` 立即返回，绝不阻塞脚本线程。
- 同一原因键默认 10 分钟内只弹一次；记录“未恢复的问题”，恢复时弹一条
  “已恢复”（只对真正弹过的问题发恢复通知）。
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import threading
import time
from typing import Callable, Optional

默认节流秒 = 600.0
应用名称 = "部落冲突机器人"

# PowerShell 自带的 AppUserModelID：不需要注册快捷方式即可显示 toast。
_POWERSHELL_AUMID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

_PS脚本 = r"""
$t = $env:COC_TOAST_TITLE
$b = $env:COC_TOAST_BODY
$app = $env:COC_TOAST_AUMID
$secs = [int]$env:COC_TOAST_SECONDS
function Esc([string]$s) { return [System.Security.SecurityElement]::Escape($s) }
# 1) 通知中心留一条记录（SuppressPopup：不重复弹 toast；勿扰模式下也会进通知中心）
try {
  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
  [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
  $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
  $xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>" + (Esc $t) + "</text><text>" + (Esc $b) + "</text></binding></visual></toast>")
  $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
  $toast.SuppressPopup = $true
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)
} catch { }
# 2) 右下角置顶小窗：不抢焦点、不受勿扰模式影响，点击或到时自动关闭
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @'
using System.Windows.Forms;
public class CocNoActivateForm : Form {
  protected override bool ShowWithoutActivation { get { return true; } }
  protected override CreateParams CreateParams { get {
    CreateParams p = base.CreateParams;
    p.ExStyle |= 0x08000000 | 0x00000008 | 0x00000080; // NOACTIVATE | TOPMOST | TOOLWINDOW
    return p; } }
}
'@
$f = New-Object CocNoActivateForm
$f.FormBorderStyle = 'None'
$f.ShowInTaskbar = $false
$f.TopMost = $true
$f.StartPosition = 'Manual'
$f.BackColor = [System.Drawing.Color]::FromArgb(32, 36, 44)
$f.Size = New-Object System.Drawing.Size(380, 120)
$wa = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$slot = [int]$env:COC_TOAST_SLOT
$f.Location = New-Object System.Drawing.Point(($wa.Right - 396), ($wa.Bottom - 136 - 128 * $slot))
$bar = New-Object System.Windows.Forms.Panel
$bar.BackColor = [System.Drawing.Color]::FromArgb([int]$env:COC_TOAST_R, [int]$env:COC_TOAST_G, [int]$env:COC_TOAST_B)
$bar.SetBounds(0, 0, 6, 120)
$l1 = New-Object System.Windows.Forms.Label
$l1.Text = $t
$l1.ForeColor = [System.Drawing.Color]::White
$l1.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 11, [System.Drawing.FontStyle]::Bold)
$l1.SetBounds(18, 10, 352, 26)
$l2 = New-Object System.Windows.Forms.Label
$l2.Text = $b
$l2.ForeColor = [System.Drawing.Color]::FromArgb(220, 224, 230)
$l2.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9)
$l2.SetBounds(18, 40, 352, 74)
$f.Controls.AddRange(@($bar, $l1, $l2))
$close = { $f.Close() }
$f.Add_Click($close); $l1.Add_Click($close); $l2.Add_Click($close)
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = [Math]::Max(3, $secs) * 1000
$timer.Add_Tick($close)
$timer.Start()
[System.Windows.Forms.Application]::Run($f)
"""


def _编码脚本(脚本: str) -> str:
    return base64.b64encode(脚本.encode("utf-16-le")).decode("ascii")


_级别颜色 = {
    "警告": (232, 145, 45),
    "错误": (220, 70, 70),
    "恢复": (70, 180, 110),
    "信息": (80, 140, 230),
}
_槽位 = 0
_槽位锁 = threading.Lock()


def _下一个槽位() -> int:
    """同时弹出多条时竖向错开，最多 3 层后回到底部。"""
    global _槽位
    with _槽位锁:
        当前 = _槽位
        _槽位 = (_槽位 + 1) % 3
        return 当前


def 弹出Windows通知(标题: str, 正文: str, 级别: str = "警告", 显示秒: int = 15) -> bool:
    """后台弹出一条 Windows 桌面通知；立即返回，失败返回 False。"""
    if sys.platform != "win32":
        return False
    环境 = dict(os.environ)
    r, g, b = _级别颜色.get(级别, _级别颜色["信息"])
    环境.update({
        "COC_TOAST_R": str(r), "COC_TOAST_G": str(g), "COC_TOAST_B": str(b),
        "COC_TOAST_SECONDS": str(int(显示秒)),
        "COC_TOAST_SLOT": str(_下一个槽位()),
    })
    环境["COC_TOAST_TITLE"] = str(标题 or 应用名称)[:120]
    环境["COC_TOAST_BODY"] = str(正文 or "")[:600]
    环境["COC_TOAST_AUMID"] = _POWERSHELL_AUMID
    参数 = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-EncodedCommand",
        _编码脚本(_PS脚本),
    ]
    try:
        subprocess.Popen(
            参数,
            env=环境,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            close_fds=True,
        )
        return True
    except Exception:
        return False


class 桌面通知器:
    """按原因键节流的桌面通知；线程安全，所有机器人共享一个实例。"""

    def __init__(
        self,
        弹出: Optional[Callable[..., bool]] = None,
        时钟: Callable[[], float] = time.monotonic,
        节流秒: float = 默认节流秒,
    ):
        self._弹出 = 弹出 or 弹出Windows通知
        self._时钟 = 时钟
        self.节流秒 = float(节流秒)
        self._锁 = threading.Lock()
        self._上次发送: dict[str, float] = {}
        self._未恢复: dict[str, str] = {}

    def 通知(self, 键: str, 标题: str, 正文: str, 节流秒: Optional[float] = None,
             需要恢复通知: bool = True, 级别: str = "警告") -> bool:
        """发送问题通知；同键在节流时间内只发一次。返回是否真的弹出。"""
        现在 = self._时钟()
        间隔 = self.节流秒 if 节流秒 is None else float(节流秒)
        with self._锁:
            上次 = self._上次发送.get(键)
            if 上次 is not None and 现在 - 上次 < 间隔:
                if 需要恢复通知:
                    self._未恢复.setdefault(键, 标题)
                return False
            self._上次发送[键] = 现在
            if 需要恢复通知:
                self._未恢复[键] = 标题
        return bool(self._弹出(标题, 正文, 级别))

    def 恢复(self, 键: str, 正文: str = "") -> bool:
        """问题恢复时弹一条“已恢复”；该键从未弹过问题通知时什么都不做。"""
        with self._锁:
            原标题 = self._未恢复.pop(键, None)
            if 原标题 is None:
                return False
            # 恢复后同一问题再次出现应立即提醒，不受上一次节流影响。
            self._上次发送.pop(键, None)
        return bool(self._弹出(f"已恢复：{原标题}", 正文 or "机器人已恢复正常运行", "恢复"))

    def 有未恢复(self, 键: str) -> bool:
        with self._锁:
            return 键 in self._未恢复


_共享实例: Optional[桌面通知器] = None
_共享锁 = threading.Lock()


def 获取桌面通知器() -> 桌面通知器:
    global _共享实例
    with _共享锁:
        if _共享实例 is None:
            _共享实例 = 桌面通知器()
        return _共享实例


def 发送测试通知() -> bool:
    """设置页“测试桌面通知”按钮使用：不节流，直接弹一条。"""
    return 弹出Windows通知(
        f"{应用名称}：测试通知",
        f"桌面通知工作正常（{time.strftime('%H:%M:%S')}）。脚本停下、待命超时、断线重连失败等情况会这样提醒你。",
        "信息",
    )


def 机器人桌面通知(设置, 机器人标志: str, 原因键: str, 标题: str, 正文: str = "",
                级别: str = "警告", 需要恢复通知: bool = True,
                节流秒: Optional[float] = None) -> bool:
    """按机器人设置发送桌面通知；设置关闭时静默跳过，绝不抛异常。"""
    try:
        if 设置 is not None and not bool(getattr(设置, "桌面通知", True)):
            return False
        return 获取桌面通知器().通知(
            f"{机器人标志}:{原因键}",
            f"{机器人标志}｜{标题}",
            正文,
            节流秒=节流秒,
            需要恢复通知=需要恢复通知,
            级别=级别,
        )
    except Exception:
        return False


def 机器人桌面恢复(机器人标志: str, 原因键: str, 正文: str = "") -> bool:
    """之前弹过该原因的问题通知时，弹一条“已恢复”；否则什么都不做。"""
    try:
        return 获取桌面通知器().恢复(f"{机器人标志}:{原因键}", 正文)
    except Exception:
        return False
