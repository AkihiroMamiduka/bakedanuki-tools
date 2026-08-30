[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Diff
)

$ErrorActionPreference = "Stop"

# Black環境、設定、整形対象のpathをリポジトリ基準で組み立てる
$repoRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..")
)
$venvPython = Join-Path $repoRoot ".venv-format\Scripts\python.exe"
$setupScript = Join-Path $PSScriptRoot "setup-format.ps1"
$configPath = Join-Path $repoRoot "pyproject.toml"
$formatTargets = @(
    (Join-Path $repoRoot "bakedanuki"),
    (Join-Path $repoRoot "tests")
)

# format環境のPythonが正常に起動できるか確認する
function Test-PythonEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExecutablePath
    )

    if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
        return $false
    }
    try {
        & $ExecutablePath -c "import sys" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

# 初回実行時だけformat環境を自動作成する
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Write-Host "The format environment is missing. Creating it."
    & $setupScript
}

if (-not (Test-PythonEnvironment $venvPython)) {
    throw @"
The format environment exists but cannot start.
Run .\scripts\setup-format.cmd -ForceRecreate to rebuild it explicitly.
"@
}

# check・diff指定をBlackのCLI引数へ変換する
$blackArgs = @(
    "-m",
    "black",
    "--config",
    $configPath
)
if ($Check) {
    $blackArgs += "--check"
}
if ($Diff) {
    $blackArgs += "--diff"
}
$blackArgs += $formatTargets

# 実行位置を固定してBlackを起動し、終了codeを保持する
Push-Location $repoRoot
try {
    & $venvPython @blackArgs
    $blackExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($blackExitCode -ne 0) {
    throw "Black exited with code $blackExitCode."
}
