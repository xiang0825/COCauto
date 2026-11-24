param(
    [Parameter(Mandatory = $true)]
    [string]$PackageDirectory,
    [string]$ReleaseDirectory = "",
    [string]$VerifierPython = ""
)

$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1 默认按系统代码页输出，被 Python 等调用方读取时中文报错会变成 ???。
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$脚本目录 = if ($PSScriptRoot) {
    $PSScriptRoot
} else {
    Split-Path -Parent $MyInvocation.MyCommand.Definition
}
if ([string]::IsNullOrWhiteSpace($ReleaseDirectory)) {
    $gitFile = Join-Path $脚本目录 ".git"
    if (Test-Path -LiteralPath $gitFile -PathType Leaf) {
        throw "当前脚本位于 Git worktree，必须显式指定 ReleaseDirectory，避免发布到错误目录"
    }
    $ReleaseDirectory = Split-Path -Parent $脚本目录
}
$package = (Resolve-Path -LiteralPath $PackageDirectory).Path
$source = Join-Path $package "部落冲突"
$target = (Resolve-Path -LiteralPath $ReleaseDirectory).Path
$sourceExe = Join-Path $source "部落冲突.exe"
$sourceInternal = Join-Path $source "_internal"
$targetExe = Join-Path $target "部落冲突.exe"
$targetInternal = Join-Path $target "_internal"

if (-not [string]::IsNullOrWhiteSpace($VerifierPython)) {
    if (-not (Test-Path -LiteralPath $VerifierPython -PathType Leaf)) {
        throw "指定的发布校验 Python 不存在：$VerifierPython"
    }
    $pythonCandidates = @((Resolve-Path -LiteralPath $VerifierPython).Path)
} else {
    $pythonCandidates = @(
        (Join-Path $脚本目录 ".venv\Scripts\python.exe"),
        (Join-Path $脚本目录 ".venv311\Scripts\python.exe")
    )
}
if (-not (Test-Path -LiteralPath $sourceExe -PathType Leaf)) {
    throw "发布包不完整：缺少部落冲突.exe"
}

$sourcePythonDll = Get-ChildItem -LiteralPath $sourceInternal -File -Filter "python3*.dll" -ErrorAction SilentlyContinue |
    Where-Object { $_.Length -ge 5000000 } |
    Select-Object -First 1
if (-not $sourcePythonDll) {
    throw "发布包不完整：_internal 中没有有效的 Python 运行时 DLL"
}
if ($sourcePythonDll.Name -notmatch '^python(?<version>\d+)\.dll$') {
    throw "无法从运行时 DLL 名称确定 Python 版本：$($sourcePythonDll.Name)"
}
$expectedPythonVersion = $Matches.version
$pythonExe = $null
foreach ($candidate in $pythonCandidates) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    $actualPythonVersion = (& $candidate -c "import sys; print('%d%d' % sys.version_info[:2])") -join ""
    if ($LASTEXITCODE -eq 0 -and $actualPythonVersion.Trim() -eq $expectedPythonVersion) {
        $pythonExe = $candidate
        break
    }
}
if (-not $pythonExe) {
    throw "发布包使用 Python $($expectedPythonVersion[0]).$($expectedPythonVersion.Substring(1))，但没有可用的同版本发布校验器"
}

& $pythonExe (Join-Path $脚本目录 "scripts\verify_packaged_modules.py") $sourceExe
if ($LASTEXITCODE -ne 0) {
    throw "发布包模块或源码一致性校验失败，已停止发布；原有 EXE 未改动"
}

function Get-DirectoryManifest {
    param([Parameter(Mandatory = $true)][string]$Directory)

    $rootPath = (Resolve-Path -LiteralPath $Directory).Path.TrimEnd('\') + '\'
    @(
        Get-ChildItem -LiteralPath $Directory -File -Recurse | ForEach-Object {
            $relativePath = $_.FullName.Substring($rootPath.Length).Replace('\', '/')
            $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
            "$relativePath|$($_.Length)|$hash"
        } | Sort-Object
    )
}

$expectedExeHash = (Get-FileHash -LiteralPath $sourceExe -Algorithm SHA256).Hash
$expectedInternalManifest = @(Get-DirectoryManifest -Directory $sourceInternal)
$expectedInternalFileCount = $expectedInternalManifest.Count
# 实际发布包 _internal 约 470–520 个文件（rc123–rc127）；低于 300 才视为复制未完成。
if ($expectedInternalFileCount -lt 300) {
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

    $actualExeHash = (Get-FileHash -LiteralPath $targetExe -Algorithm SHA256).Hash
    if ($actualExeHash -ne $expectedExeHash) {
        throw "切换后的 EXE SHA-256 与候选包不一致：$actualExeHash / $expectedExeHash"
    }
    $actualInternalManifest = @(Get-DirectoryManifest -Directory $targetInternal)
    $manifestDifferences = @(
        Compare-Object `
            -ReferenceObject $expectedInternalManifest `
            -DifferenceObject $actualInternalManifest
    )
    if ($manifestDifferences.Count -gt 0) {
        throw "切换后的 _internal 文件清单或 SHA-256 与候选包不一致；已回滚旧包"
    }

    & $pythonExe (Join-Path $脚本目录 "scripts\verify_packaged_modules.py") $targetExe
    if ($LASTEXITCODE -ne 0) {
        throw "发布目录中的 EXE 未通过模块、源码或版本复核；已回滚旧包"
    }

    $actualInternalFileCount = $actualInternalManifest.Count
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
