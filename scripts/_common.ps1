Set-StrictMode -Version Latest

# toolsリポジトリ直下の絶対pathを返す
function Get-ToolsRepositoryRoot {
    return [System.IO.Path]::GetFullPath(
        (Join-Path $PSScriptRoot "..")
    )
}

# 引数・環境変数・siblingの順でutilリポジトリを解決する
function Resolve-BakedanukiUtilRoot {
    param(
        [string]$UtilRoot
    )

    $repoRoot = Get-ToolsRepositoryRoot
    $configuredRoot = [Environment]::GetEnvironmentVariable(
        "BAKEDANUKI_UTIL_ROOT",
        "Process"
    )

    # 明示設定を優先し、未設定時だけ既定のsibling配置を使用する
    if ($UtilRoot) {
        $candidate = $UtilRoot
        $source = "-UtilRoot"
    }
    elseif ($configuredRoot) {
        $candidate = $configuredRoot
        $source = "BAKEDANUKI_UTIL_ROOT"
    }
    else {
        $candidate = Join-Path (Split-Path $repoRoot -Parent) "bakedanuki-util"
        $source = "sibling repository"
    }

    # package本体とMaya stubの両方が存在することを確認する
    $resolvedRoot = [System.IO.Path]::GetFullPath($candidate)
    $packageMarker = Join-Path `
        $resolvedRoot `
        "bakedanuki\bakedanuki-util\python\bd_util\__init__.py"
    $typingsMarker = Join-Path $resolvedRoot "typings\maya"

    if (-not (Test-Path -LiteralPath $packageMarker -PathType Leaf)) {
        throw "bakedanuki-util was not found from $source`: $resolvedRoot"
    }
    if (-not (Test-Path -LiteralPath $typingsMarker -PathType Container)) {
        throw "Maya typings were not found in bakedanuki-util: $typingsMarker"
    }

    return $resolvedRoot
}

# 対応Maya versionの実行ファイルを検証して返す
function Get-MayaExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("2025", "2026", "2027")]
        [string]$MayaVersion,
        [Parameter(Mandatory = $true)]
        [ValidateSet("maya.exe", "mayapy.exe")]
        [string]$ExecutableName
    )

    $executable = Join-Path `
        "C:\Program Files\Autodesk\Maya$MayaVersion\bin" `
        $ExecutableName
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "Maya $MayaVersion executable was not found: $executable"
    }
    return $executable
}

# process環境変数の先頭へ重複なしでpathを追加する
function Add-ProcessPathEntries {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string[]]$Paths
    )

    $currentValue = [Environment]::GetEnvironmentVariable($Name, "Process")
    $entries = [System.Collections.Generic.List[string]]::new()

    # 新しく指定されたpathを絶対pathへ正規化して先に登録する
    foreach ($path in $Paths) {
        $resolvedPath = [System.IO.Path]::GetFullPath($path)
        if (-not (Test-Path -LiteralPath $resolvedPath)) {
            throw "Cannot add a missing path to $Name`: $resolvedPath"
        }
        if ($entries -notcontains $resolvedPath) {
            $entries.Add($resolvedPath)
        }
    }

    # 呼び出し元processが持つ既存pathは順序を保って後ろへ残す
    if ($currentValue) {
        foreach ($entry in $currentValue.Split(";")) {
            $trimmedEntry = $entry.Trim()
            if ($trimmedEntry -and $entries -notcontains $trimmedEntry) {
                $entries.Add($trimmedEntry)
            }
        }
    }

    [Environment]::SetEnvironmentVariable(
        $Name,
        ($entries -join ";"),
        "Process"
    )
}

# toolsとutilのMaya Module・Python pathを現在processへ設定する
function Enable-BakedanukiDevelopmentEnvironment {
    param(
        [string]$UtilRoot
    )

    $repoRoot = Get-ToolsRepositoryRoot
    $resolvedUtilRoot = Resolve-BakedanukiUtilRoot -UtilRoot $UtilRoot

    # Mayaが両packageの.modを検出できるようmodule pathを設定する
    $toolsModules = Join-Path $repoRoot "bakedanuki\modules"
    $utilModules = Join-Path $resolvedUtilRoot "bakedanuki\modules"
    Add-ProcessPathEntries `
        -Name "MAYA_MODULE_PATH" `
        -Paths @($toolsModules, $utilModules)

    # mayapyから直接importできるようPython pathも設定する
    $toolsPython = Join-Path `
        $repoRoot `
        "bakedanuki\bakedanuki-tools\python"
    $utilPython = Join-Path `
        $resolvedUtilRoot `
        "bakedanuki\bakedanuki-util\python"
    Add-ProcessPathEntries `
        -Name "PYTHONPATH" `
        -Paths @($toolsPython, $utilPython)

    return $resolvedUtilRoot
}

# pytest・Pyrightを配置するローカルpathを返す
function Get-DevToolsPythonPath {
    $repoRoot = Get-ToolsRepositoryRoot
    return Join-Path $repoRoot ".dev-tools\python"
}

# ローカル開発ツールを現在processのPython pathへ追加する
function Enable-DevToolsPythonPath {
    $toolsPath = Get-DevToolsPythonPath
    Add-ProcessPathEntries -Name "PYTHONPATH" -Paths @($toolsPath)
}

# 開発ツールが未導入の場合だけsetupを実行する
function Ensure-DevTools {
    param(
        [ValidateSet("2025", "2026", "2027")]
        [string]$MayaVersion = "2025"
    )

    $repoRoot = Get-ToolsRepositoryRoot
    $toolsPath = Get-DevToolsPythonPath
    $pytestMarker = Join-Path $toolsPath "pytest\__init__.py"
    $pyrightMarker = Join-Path $toolsPath "pyright\__init__.py"

    if (
        -not (Test-Path -LiteralPath $pytestMarker -PathType Leaf) -or
        -not (Test-Path -LiteralPath $pyrightMarker -PathType Leaf)
    ) {
        & (Join-Path $repoRoot "scripts\setup-dev.ps1") `
            -MayaVersion $MayaVersion
    }
}
