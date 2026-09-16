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

boolのCheckBoxへのSpace入力、floatの文字入力、Sliderのマウスドラッグ、右クリックメニューからの
表示更新と混在値を揃える操作、
各操作の1回Undo、選択追従、close / reopen、utilとtoolsのreloadを確認します。
ドッキングからfloatingへの切替、Mayaへのタブ再配置、Maya側のcloseによる破棄も確認します。
step欄のキー入力が値とUndoを変更しないこと、変更後の刻み幅で値入力できること、
値をUndoしてもstepが保持されることも確認します。
さらに10ノード・各30個の追加float属性を用いて、Window生成、一括入力、選択切替を
1回ずつ計測します。計測値は同時実行中の処理やMayaの環境によって変わるため、
性能保証値や自動判定の閾値には使用しません。

起動時に表示する `output` ディレクトリへ次の資料を残します。

- `result.json`: 成否、操作履歴、実行Maya version、性能計測値、各段階のUndo状態。
- `01-multiple-selection.png`、`02-single-selection.png`、`03-after-reload.png`:
  QtのWindow描画から保存した確認画像。
- `04-attribute-menu.png`: 属性名を右クリックして開いた操作メニュー。
- `05-docked.png`、`06-floating-content.png`: Maya右側へのドッキングとfloatingの表示。
- `progress.json`: 実行中の段階と完了済みの操作。
- `maya-initial.log`、`process-initial.log`、`python-stacks-initial.log`: Mayaの出力と、長時間停止した場合の
  Python stack。

終了codeが0で `result.json` の `success` がTrueでも、保存画像で文字切れ、配置、
入力欄の状態を確認してください。結果が保存されなかった場合は失敗として扱います。

初回のMaya 2025本体検証では、全操作の成功結果とcallback解放を確認した後、
Mayaアプリケーションの終了待ちが180秒でタイムアウトしました。native MELの
deferred quitでも発生しており、終了待ちの原因は未特定です。runnerはこの場合も
成功扱いにせず、結果を表示して専用processだけを停止し、終了code 1を返します。
操作の検証結果とMayaアプリケーションの正常終了は区別して確認してください。

### 次回変更時の回帰確認

初回開発完了時の件数と確認範囲は[Channel Editorの検証記録](channel_editor.md#検証)を参照します。
変更した仕様に応じて既存testと本体runnerを更新し、次を確認します。

- 入力・対応型: 選択／更新で無書込み、外部変更の非伝播、混在値への一括入力、1回Undo、編集不可対象の扱い。
- bool: 基準値を二値CheckBoxで表示し、クリック／Spaceで切替、属性名の直後に左詰め。
- step: 値／Undoを変更しないこと、型別初期値、選択変更／Undo後の保持、close後の初期化。
- 幅・配置: Sliderあり／なし、最小幅／拡大時、長い属性名、縦スクロール時、ドック／floating。
  StepとSliderの幅・開始位置、値欄の文字切れ、不要な右余白を保存画像でも確認する。
- lifecycle: 選択切替・close・reloadで古い入力とcallbackを終了し、再表示で重複させない。

対応version、配布構成、Qt / Maya API互換性の変更では3 versionのruntime testを実行します。
workspaceControl、再起動復元、実画面配置の変更では対象Maya本体で確認し、
再起動復元の仕様を変える場合は以下の2段階検証も行います。
Markdownのみの変更は`git diff --check -- <changed-files>`を実行し、runtime testの再実行は不要です。

### Maya再起動による配置復元

一度目の検証で `--prepare-restart` を指定すると、全操作の確認後に新しいWindowを開き、
floatingにしてworkspaceとpreferencesを専用profileへ保存します。

```powershell
& "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" -B `
    scripts/test_channel_editor_maya.py --maya-version 2025 --prepare-restart --timeout 180
```

一度目のprocessが終了したことと `result.json` の成功、`prepared-restart.json` の存在を確認し、
表示された `output` を二度目の `--restart-from` に指定します。
終了待ちだけがタイムアウトした場合も、専用processの停止を確認してから実行します。

```powershell
& "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" -B `
    scripts/test_channel_editor_maya.py --maya-version 2025 --restart-from <output> --timeout 180
```

二度目は同じprofileの別processを起動し、`show()` を呼ぶ前にworkspaceControlと入力UIが
自動復元されたことを確認します。floating配置・寸法の復元を確認し、新しいsceneの選択と
一括入力を検証してから終了します。結果は `result-restart.json`、画像は
`07-after-maya-restart.png`、ログは `*-restart.log` に保存し、一度目の結果を残します。
この再起動検証はsceneの保存・復元ではなく、Maya workspaceからのUI復元を対象にします。

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
