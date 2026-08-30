# Development

## Requirements

- Windows
- Autodesk Maya 2025 / 2026 / 2027
- Maya 2025 bundled Python 3.11.4 以降を互換性の基準とする
- PowerShell 5.1 以降
- sibling に配置した `bakedanuki-util`

```text
bakedanuki_dev/
  bakedanuki-tools/
  bakedanuki-util/
```

既定配置以外を使う場合、各 script の `-UtilRoot` または process 環境変数
`BAKEDANUKI_UTIL_ROOT` で util の repository root を指定できます。

## Initial Setup

Black 用の通常 Python 環境を準備します。

```powershell
.\scripts\setup-format.cmd
```

既定では `python`、次に sibling の `bakedanuki-util/.venv-format` を作成元として探します。
明示する場合は `-PythonExecutable` または `BAKEDANUKI_FORMAT_PYTHON` を使います。

pytest と Pyright は Maya Python と互換性を揃えるため、repository 内の `.dev-tools/python`
へ target install します。

```powershell
.\scripts\setup-dev.cmd
```

既存環境を明示的に作り直す場合です。

```powershell
.\scripts\setup-format.cmd -ForceRecreate
.\scripts\setup-dev.cmd -ForceRecreate
```

setup script は削除対象がこの repository 内の想定 path と一致することを検証します。

## Daily Commands

```powershell
.\scripts\format.cmd
.\scripts\format.cmd -Check -Diff
.\scripts\typecheck.cmd
.\scripts\test-unit.cmd
.\scripts\test-maya2025.cmd
.\scripts\check.cmd
```

追加の pytest 引数は wrapper からそのまま渡せます。

```powershell
.\scripts\test-unit.cmd -q
.\scripts\test-maya2025.cmd tests\maya\test_runtime.py -q
```

## Maya Module Development

通常利用する Maya では `Maya.env` へ両 repository の module path を設定します。

```env
MAYA_MODULE_PATH=D:/develop/bakedanuki_dev/bakedanuki-tools/bakedanuki/modules;D:/develop/bakedanuki_dev/bakedanuki-util/bakedanuki/modules;
```

一時的な開発環境で Maya を起動する場合は launcher を使います。

```powershell
.\scripts\launch-maya2025.cmd
```

launcher は呼び出し元の `Maya.env` を編集しません。起動する process の
`MAYA_MODULE_PATH` と `PYTHONPATH` の先頭へ tools / util を追加します。

## VS Code

`.vscode/settings.json` は Maya 2025 の `mayapy.exe` を interpreter とし、tools と sibling
util を解析 path に追加します。Black は `.venv-format` の固定 version を使用します。

util を既定以外の場所へ置く場合、command line の `-UtilRoot` は解決できますが、VS Code
の `python.analysis.extraPaths` は workspace 用設定で調整してください。

## Distribution Layout

この repository は共通 installer を所有しません。配布時に tools と util の
`bakedanuki/` を共通 root へ重ね、必要に応じて rig も同梱します。各 repository の
`.mod` が同じ `modules` directory に集まる構成です。
