[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("2025", "2026", "2027")]
    [string]$MayaVersion,
    [string]$UtilRoot,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

# 指定Maya versionからtools・util・pytestを解決できる環境を準備する
$repoRoot = Get-ToolsRepositoryRoot
$resolvedUtilRoot = Enable-BakedanukiDevelopmentEnvironment `
    -UtilRoot $UtilRoot
Ensure-DevTools -MayaVersion $MayaVersion
Enable-DevToolsPythonPath

$mayapy = Get-MayaExecutable `
    -MayaVersion $MayaVersion `
    -ExecutableName "mayapy.exe"
$env:BAKEDANUKI_UTIL_ROOT = $resolvedUtilRoot

# Maya standaloneを使うruntime testだけを実行する
Push-Location $repoRoot
try {
    & $mayapy -m pytest (Join-Path $repoRoot "tests\maya") @PytestArgs
    $pytestExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($pytestExitCode -ne 0) {
    throw "Maya $MayaVersion tests exited with code $pytestExitCode."
}
