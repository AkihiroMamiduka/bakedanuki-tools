[CmdletBinding()]
param(
    [string]$UtilRoot,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"
$testScript = Join-Path $PSScriptRoot "test-maya.ps1"

# 対応する全Maya versionを順番に検証し、失敗時点で停止する
foreach ($mayaVersion in @("2025", "2026", "2027")) {
    Write-Host "Running Maya $mayaVersion tests."
    & $testScript `
        -MayaVersion $mayaVersion `
        -UtilRoot $UtilRoot `
        @PytestArgs
}
