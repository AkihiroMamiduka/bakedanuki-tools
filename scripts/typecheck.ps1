[CmdletBinding()]
param(
    [ValidateSet("2025", "2026", "2027")]
    [string]$MayaVersion = "2025",
    [string]$UtilRoot
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

# tools・util・開発ツールをmayapyから解決できる環境へ揃える
$repoRoot = Get-ToolsRepositoryRoot
$resolvedUtilRoot = Enable-BakedanukiDevelopmentEnvironment `
    -UtilRoot $UtilRoot
Ensure-DevTools -MayaVersion $MayaVersion
Enable-DevToolsPythonPath

$mayapy = Get-MayaExecutable `
    -MayaVersion $MayaVersion `
    -ExecutableName "mayapy.exe"
$env:BAKEDANUKI_UTIL_ROOT = $resolvedUtilRoot
$env:PYRIGHT_PYTHON_CACHE_DIR = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    "bakedanuki-tools-pyright-cache"

# 解決済みutil rootを反映した一時Pyright設定を生成する
$sourceConfigPath = Join-Path $repoRoot "pyrightconfig.json"
$generatedConfigPath = Join-Path `
    $repoRoot `
    ".pyrightconfig.generated.json"
$pyrightConfig = Get-Content -Raw -Encoding UTF8 $sourceConfigPath |
    ConvertFrom-Json
$pyrightConfig.extraPaths = @(
    (Join-Path $repoRoot "bakedanuki\bakedanuki-tools\python"),
    (Join-Path `
        $resolvedUtilRoot `
        "bakedanuki\bakedanuki-util\python")
)
$pyrightConfig.stubPath = Join-Path $resolvedUtilRoot "typings"
$generatedConfigJson = $pyrightConfig | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText(
    $generatedConfigPath,
    $generatedConfigJson,
    [System.Text.UTF8Encoding]::new($false)
)

# Maya interpreterを明示してstrict型検査を実行する
Push-Location $repoRoot
try {
    & $mayapy -m pyright `
        --project $generatedConfigPath `
        --pythonpath $mayapy
    $pyrightExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($pyrightExitCode -ne 0) {
    throw "Pyright exited with code $pyrightExitCode."
}
