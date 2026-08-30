[CmdletBinding()]
param(
    [ValidateSet("2025", "2026", "2027")]
    [string]$MayaVersion = "2025",
    [string]$UtilRoot,
    [switch]$IncludeMaya
)

$ErrorActionPreference = "Stop"

# 日常確認として整形、型、unit testを順番に実行する
& (Join-Path $PSScriptRoot "format.ps1") -Check
& (Join-Path $PSScriptRoot "typecheck.ps1") `
    -MayaVersion $MayaVersion `
    -UtilRoot $UtilRoot
& (Join-Path $PSScriptRoot "test-unit.ps1") `
    -MayaVersion $MayaVersion `
    -UtilRoot $UtilRoot

# 明示指定された場合だけMaya runtime testも追加する
if ($IncludeMaya) {
    & (Join-Path $PSScriptRoot "test-maya.ps1") `
        -MayaVersion $MayaVersion `
        -UtilRoot $UtilRoot
}
