[CmdletBinding()]
param(
    [string]$PythonExecutable,
    [switch]$ForceRecreate
)

$ErrorActionPreference = "Stop"

# リポジトリ内に閉じたBlack環境とrequirementsのpathを組み立てる
$repoRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..")
)
$venvPath = Join-Path $repoRoot ".venv-format"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$requirementsPath = Join-Path $repoRoot "requirements-format.txt"

# 指定したPythonが実際に起動できるか確認する
function Test-PythonExecutable {
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

# 明示設定または利用可能な既存環境からvenv作成元Pythonを選ぶ
function Resolve-BootstrapPython {
    param(
        [string]$ConfiguredExecutable,
        [string]$RepositoryRoot
    )

    # 明示指定がなければ環境変数、system、util環境の順で候補を集める
    if ($ConfiguredExecutable) {
        $candidates = @($ConfiguredExecutable)
    }
    else {
        $candidates = @()
        $environmentPython = [Environment]::GetEnvironmentVariable(
            "BAKEDANUKI_FORMAT_PYTHON",
            "Process"
        )
        if ($environmentPython) {
            $candidates += $environmentPython
        }

        $systemPython = Get-Command python -ErrorAction SilentlyContinue
        if ($systemPython) {
            $candidates += $systemPython.Source
        }

        $candidates += Join-Path `
            (Split-Path $RepositoryRoot -Parent) `
            "bakedanuki-util\.venv-format\Scripts\python.exe"
    }

    # 最初に正常起動できた候補だけを採用する
    foreach ($candidate in $candidates) {
        if (Test-PythonExecutable -ExecutablePath $candidate) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }

    throw @"
A regular Python interpreter for the Black environment was not found.
Pass -PythonExecutable or set BAKEDANUKI_FORMAT_PYTHON.
Maya's mayapy cannot create a reliable standalone Black environment here.
"@
}

# 削除対象がrepository直下のformat環境であることを確認してから削除する
function Remove-FormatEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$RepositoryRoot
    )

    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    $expectedPath = [System.IO.Path]::GetFullPath(
        (Join-Path $RepositoryRoot ".venv-format")
    )
    if (-not [string]::Equals(
        $resolvedPath,
        $expectedPath,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing to remove an unexpected format environment: $resolvedPath"
    }

    if (Test-Path -LiteralPath $resolvedPath) {
        Remove-Item -LiteralPath $resolvedPath -Recurse -Force
    }
}

# 既存環境の有無と起動可否を分けて判定する
$environmentExists = Test-Path -LiteralPath $venvPath -PathType Container
$environmentIsHealthy = Test-PythonExecutable $venvPython

if ($environmentExists -and -not $environmentIsHealthy -and -not $ForceRecreate) {
    throw @"
The format environment exists but cannot start.
Run .\scripts\setup-format.cmd -ForceRecreate to rebuild it explicitly.
"@
}

# 明示指定された場合だけ既存環境を安全に作り直す
if ($ForceRecreate -and $environmentExists) {
    Write-Host "Removing the format environment: $venvPath"
    Remove-FormatEnvironment -Path $venvPath -RepositoryRoot $repoRoot
    $environmentExists = $false
    $environmentIsHealthy = $false
}

# 環境がない場合は、選択した通常Pythonからvenvを作成する
if (-not $environmentExists) {
    $bootstrapPython = Resolve-BootstrapPython `
        -ConfiguredExecutable $PythonExecutable `
        -RepositoryRoot $repoRoot
    Write-Host "Creating the format environment with: $bootstrapPython"
    & $bootstrapPython -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the format environment."
    }
    if (-not (Test-PythonExecutable $venvPython)) {
        throw "The newly created format environment cannot start."
    }
}

# 固定versionのBlackを導入し、CLIが起動できることまで確認する
& $venvPython -m pip install `
    --disable-pip-version-check `
    --requirement $requirementsPath
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install the format dependencies."
}

& $venvPython -m black --version
if ($LASTEXITCODE -ne 0) {
    throw "Black is not available in the format environment."
}
