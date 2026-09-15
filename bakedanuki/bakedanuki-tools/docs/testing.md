# Testing

検証は役割ごとに3層へ分けます。

## Unit Tests

`tests/unit` は Maya standalone を初期化せず、package metadata、純粋な処理、reload
lifecycle などを検証します。

```powershell
.\scripts\test-unit.cmd
```

実行 interpreter は Maya の `mayapy` ですが、テスト自体は Maya scene を必要としません。

## Maya Runtime Tests

`tests/maya` は session 開始時に `maya.standalone` を初期化し、Maya API、`bd_tools`、
`bd_util` が同じ環境で利用できることを検証します。

```powershell
.\scripts\test-maya2025.cmd
.\scripts\test-maya2026.cmd
.\scripts\test-maya2027.cmd
.\scripts\test-maya-all.cmd
```

scene 操作、undo、Maya callback、Maya UI adapter を使う機能はこの層にテストを追加します。
QWidgetも同じ入口で検証できるよう、Maya初期化前にQt facadeからQApplicationを作ります。
テストの `qt_application` fixtureはそのsession共通instanceを提供します。
workspaceControl の実表示や Maya 再起動後の復元は `mayapy` だけでは完結しないため、対象
Maya 本体でも操作確認します。

## Channel EditorのMaya本体検証

リポジトリ直下から専用runnerを実行します。`--maya-version` は2025 / 2026 / 2027を
指定でき、`--util-root` を省略すると環境変数またはsiblingのutilを使用します。

```powershell
& "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" -B `
    scripts/test_channel_editor_maya.py --maya-version 2025 --timeout 180
```

runnerは別の `maya.exe` を起動し、一時ディレクトリの `MAYA_APP_DIR`、Maya.env探索先、
project、script pathを使用します。通常のMaya.envを書き換えず、起動済みMayaへ接続しません。
PythonのuserSetupは読み込まず、検証用sceneで操作した後に専用processを終了します。
時間切れの場合も、runner自身が起動したprocessだけを終了します。
起動時のdeferred処理が完了した後に検証を開始し、専用sceneのUndoを有効にします。

boolのキー入力、floatの文字入力、Sliderのマウスドラッグ、混在値を揃える操作、
各操作の1回Undo、選択追従、close / reopen、utilとtoolsのreloadを確認します。
さらに10ノード・各30個の追加float属性を用いて、Window生成、一括入力、選択切替を
1回ずつ計測します。計測値は同時実行中の処理やMayaの環境によって変わるため、
性能保証値や自動判定の閾値には使用しません。

起動時に表示する `output` ディレクトリへ次の資料を残します。

- `result.json`: 成否、操作履歴、実行Maya version、性能計測値、各段階のUndo状態。
- `01-multiple-selection.png`、`02-single-selection.png`、`03-after-reload.png`:
  QtのWindow描画から保存した確認画像。
- `progress.json`: 実行中の段階と完了済みの操作。
- `maya.log`、`process.log`、`python-stacks.log`: Mayaの出力と、長時間停止した場合の
  Python stack。

終了codeが0で `result.json` の `success` がTrueでも、保存画像で文字切れ、配置、
入力欄の状態を確認してください。結果が保存されなかった場合は失敗として扱います。

初回のMaya 2025本体検証では、全操作の成功結果とcallback解放を確認した後、
Mayaアプリケーションの終了待ちが180秒でタイムアウトしました。native MELの
deferred quitでも発生しており、終了待ちの原因は未特定です。runnerはこの場合も
成功扱いにせず、結果を表示して専用processだけを停止し、終了code 1を返します。
操作の検証結果とMayaアプリケーションの正常終了は区別して確認してください。

## Type Contracts

`tests/typecheck` は実行用 pytest ではなく、公開 API の戻り値型と IDE 補完を Pyright で
固定する contract です。

```powershell
.\scripts\typecheck.cmd
```

`pyrightconfig.json` は package 本体と tests を strict mode で検査し、Maya stub は sibling
の `bakedanuki-util/typings` を利用します。

## Formatting And Combined Check

```powershell
.\scripts\format.cmd -Check
.\scripts\check.cmd
.\scripts\check.cmd -IncludeMaya
```

通常の `check.cmd` は Black、Pyright、unit test を実行します。`-IncludeMaya` を指定すると
選択した Maya version の runtime test も実行します。

## Test Placement

- Maya を import しないロジックと lifecycle: `tests/unit`
- Maya scene、OpenMaya、Qt / Maya UI adapter: `tests/maya`
- 公開 API の型と補完: `tests/typecheck`

不具合修正では、可能な限り最初に再現テストを追加します。個別ツールの UI test は、その
ツール package と対応が分かる階層へ配置します。
