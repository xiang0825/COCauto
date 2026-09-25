param(
    [Parameter(Mandatory = $true)]
    [string]$PackageDirectory,
    [string]$ReleaseDirectory = ""
)

$ErrorActionPreference = "Stop"
$脚本目录 = if ($PSScriptRoot) {
    $PSScriptRoot
} else {
    Split-Path -Parent $MyInvocation.MyCommand.Definition
}
if ([string]::IsNullOrWhiteSpace($ReleaseDirectory)) {
    $ReleaseDirectory = Split-Path -Parent $脚本目录
}
$package = (Resolve-Path -LiteralPath $PackageDirectory).Path
$source = Join-Path $package "部落冲突"
$target = (Resolve-Path -LiteralPath $ReleaseDirectory).Path
$sourceExe = Join-Path $source "部落冲突.exe"
$sourceInternal = Join-Path $source "_internal"
$targetExe = Join-Path $target "部落冲突.exe"
$targetInternal = Join-Path $target "_internal"

if (-not (Test-Path -LiteralPath $sourceExe -PathType Leaf)) {
    throw "发布包不完整：缺少部落冲突.exe"
}
$sourcePythonDll = Get-ChildItem -LiteralPath $sourceInternal -File -Filter "python3*.dll" |
    Where-Object { $_.Length -ge 5000000 } |
    Select-Object -First 1
if (-not $sourcePythonDll) {
    throw "发布包不完整：_internal 中没有有效的 Python 运行时 DLL"
}

$expectedInternalFileCount = (Get-ChildItem -LiteralPath $sourceInternal -File -Recurse | Measure-Object).Count
if ($expectedInternalFileCount -lt 1000) {
    throw "发布包校验失败：_internal 文件数只有 $expectedInternalFileCount，疑似仍在复制或构建不完整"
}

# 不允许在旧进程仍占用文件时切换发布目录。
$running = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    try { $_.Path -eq $targetExe } catch { $false }
}
if ($running) {
    throw "请先关闭正在运行的部落冲突.exe（PID: $($running.Id -join ',')）再发布"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmssfff"
$oldExe = Join-Path $target "部落冲突.exe.$stamp.old"
$oldInternal = Join-Path $target "_internal.$stamp.old"

# 先把旧入口移走，让切换期间不会有人启动到“新 EXE + 旧 DLL”组合。
if (Test-Path -LiteralPath $targetExe) { Move-Item -LiteralPath $targetExe -Destination $oldExe }
try {
    if (Test-Path -LiteralPath $targetInternal) { Move-Item -LiteralPath $targetInternal -Destination $oldInternal }
    Move-Item -LiteralPath $sourceInternal -Destination $targetInternal
    Move-Item -LiteralPath $sourceExe -Destination $targetExe

    $actualInternalFileCount = (Get-ChildItem -LiteralPath $targetInternal -File -Recurse | Measure-Object).Count
    $dll = Get-ChildItem -LiteralPath $targetInternal -File -Filter "python3*.dll" |
        Where-Object { $_.Length -ge 5000000 } |
        Select-Object -First 1
    if ($actualInternalFileCount -ne $expectedInternalFileCount -or -not $dll) {
        throw "切换后的发布目录校验失败：_internal files=$actualInternalFileCount/$expectedInternalFileCount, Python运行时DLL缺失"
    }
}
catch {
    if (Test-Path -LiteralPath $targetExe) { Remove-Item -LiteralPath $targetExe -Force }
    if (Test-Path -LiteralPath $targetInternal) { Remove-Item -LiteralPath $targetInternal -Recurse -Force }
    if (Test-Path -LiteralPath $oldInternal) { Move-Item -LiteralPath $oldInternal -Destination $targetInternal }
    if (Test-Path -LiteralPath $oldExe) { Move-Item -LiteralPath $oldExe -Destination $targetExe }
    throw
}

# 新包已完成且通过校验后再清理旧包，避免任何旧文件混入当前发布目录。
if (Test-Path -LiteralPath $oldInternal) { Remove-Item -LiteralPath $oldInternal -Recurse -Force }
if (Test-Path -LiteralPath $oldExe) { Remove-Item -LiteralPath $oldExe -Force }
Write-Output "发布完成：$targetExe；_internal 文件数=$actualInternalFileCount；$($dll.Name)=$($dll.Length) 字节"
