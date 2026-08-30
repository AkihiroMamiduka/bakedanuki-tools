[CmdletBinding()]
param(
    [ValidateSet("2025", "2026", "2027")]
    [string]$MayaVersion = "2025",
    [switch]$ForceRecreate
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

# 開発ツールの配置先がrepository直下の想定pathか検証する
$repoRoot = Get-ToolsRepositoryRoot
$toolsPath = Get-DevToolsPythonPath
$expectedToolsPath = [System.IO.Path]::GetFullPath(
    (Join-Path $repoRoot ".dev-tools\python")
)
$resolvedToolsPath = [System.IO.Path]::GetFullPath($toolsPath)
if (-not [string]::Equals(
    $resolvedToolsPath,
    $expectedToolsPath,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Refusing to manage an unexpected development tools path: $resolvedToolsPath"
}

# 明示指定された場合だけ既存の開発ツールを削除する
if ($ForceRecreate -and (Test-Path -LiteralPath $resolvedToolsPath)) {
    Write-Host "Removing the development tools: $resolvedToolsPath"
    Remove-Item -LiteralPath $resolvedToolsPath -Recurse -Force
}

# 対象Maya Pythonと固定requirementsのpathを取得する
$mayapy = Get-MayaExecutable `
    -MayaVersion $MayaVersion `
    -ExecutableName "mayapy.exe"
$testRequirements = Join-Path $repoRoot "requirements-test.txt"
$typecheckRequirements = Join-Path $repoRoot "requirements-typecheck.txt"

# Maya Python本体へ入れず、ローカルdirectoryへpytestとPyrightを導入する
Write-Host "Installing development tools with Maya $MayaVersion Python."
& $mayapy -m pip install `
    --disable-pip-version-check `
    --no-warn-script-location `
    --upgrade `
    --target $resolvedToolsPath `
    --requirement $testRequirements `
    --requirement $typecheckRequirements
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install the development tools."
}

# 導入した各CLIを実行し、setup完了を確認する
Enable-DevToolsPythonPath
& $mayapy -m pytest --version
if ($LASTEXITCODE -ne 0) {
    throw "pytest is not available in the development tools."
}
& $mayapy -m pyright --version
if ($LASTEXITCODE -ne 0) {
    throw "Pyright is not available in the development tools."
}
