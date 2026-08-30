[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("2025", "2026", "2027")]
    [string]$MayaVersion,
    [string]$UtilRoot,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$MayaArgs
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

# toolsとutilを一時的に有効化したprocess環境を準備する
$resolvedUtilRoot = Enable-BakedanukiDevelopmentEnvironment `
    -UtilRoot $UtilRoot
$env:BAKEDANUKI_UTIL_ROOT = $resolvedUtilRoot
$mayaExecutable = Get-MayaExecutable `
    -MayaVersion $MayaVersion `
    -ExecutableName "maya.exe"

# 追加引数を保ったまま対話用Maya processを起動する
if ($MayaArgs.Count -gt 0) {
    Start-Process -FilePath $mayaExecutable -ArgumentList $MayaArgs
}
else {
    Start-Process -FilePath $mayaExecutable
}
