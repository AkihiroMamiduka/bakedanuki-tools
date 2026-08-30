[CmdletBinding()]
param(
    [ValidateSet("2025", "2026", "2027")]
    [string]$MayaVersion = "2025",
    [string]$UtilRoot,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

# Mayaを初期化せず、対象Pythonと両packageを解決できる環境を準備する
$repoRoot = Get-ToolsRepositoryRoot
$resolvedUtilRoot = Enable-BakedanukiDevelopmentEnvironment `
    -UtilRoot $UtilRoot
Ensure-DevTools -MayaVersion $MayaVersion
Enable-DevToolsPythonPath

$mayapy = Get-MayaExecutable `
    -MayaVersion $MayaVersion `
    -ExecutableName "mayapy.exe"
$env:BAKEDANUKI_UTIL_ROOT = $resolvedUtilRoot

# 追加のpytest引数を保ったままunit testだけを実行する
Push-Location $repoRoot
try {
    & $mayapy -m pytest (Join-Path $repoRoot "tests\unit") @PytestArgs
    $pytestExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($pytestExitCode -ne 0) {
    throw "Unit tests exited with code $pytestExitCode."
}
