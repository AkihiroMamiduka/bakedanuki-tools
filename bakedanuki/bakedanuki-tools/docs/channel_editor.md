# Channel Editor

選択ノードの値入力を支援する、bool・float 系属性のエディタです。

## 起動と終了

```python
from bd_tools import channel_editor

window = channel_editor.show()
channel_editor.close()
```

`show()` は既存Windowを再利用します。importだけでは表示やscene変更を行いません。
初回はMaya右側へドッキングします。タイトル部分をドラッグして、他の領域への移動、
タブ化、floatingへ切り替えられます。移動だけでは入力やstep設定を破棄しません。
配置はMayaのworkspaceへ保存され、再表示やMaya再起動時の復元に使われます。
本変更に対応した `bakedanuki-util` と組み合わせて使用してください。

タイトルバーまたは `close()` で、workspaceControl・入力・callbackを破棄します。
次の `show()` は新しいWindowを生成します。開発時の完全破棄には `dispose()` を使います。
Escapeは値欄やメニューの操作に使い、パネル全体は閉じません。

配置を初期状態へ戻す場合は、次を実行します。

```python
window = channel_editor.reset_layout()
```

固定workspaceControl名は `channel_editor.WORKSPACE_CONTROL_NAME`
（`bdToolsChannelEditorWindowWorkspaceControl`）です。
MayaのuiScriptは `bd_tools.channel_editor.ui.restore()` を呼び、復元中のcontrolへ内容を接続します。
`restore()` は通常の起動用ではなくMayaの復元処理専用です。
再起動後もtoolsとutilをimportできるよう、Maya.envまたはmodule pathの設定が必要です。

旧通常Windowの `channel_editor/windows/main` にある配置はdock配置へ自動変換しません。
初回は右側へ配置し、以降はMayaが保存したworkspace配置を使います。
`reset_layout()` はこの旧配置とworkspaceControlの保存配置をutilの統合APIで消去します。

## 表示と入力

- 現在の選択リストの index 0 が基準です。ノード名だけを画面上部へ表示し、
  選択数と全ノードのpathはそのtooltipへまとめます。
  クリック履歴を記録するMayaの設定は変更しません。
- Maya nodeのobject選択が対象です。componentとplug選択は除外し、Shapeや履歴を
  自動で追加しません。DAG instanceの重複選択は同じnodeへまとめます。
- 基準nodeで `keyable OR channelBox` がTrueの対応scalarを、属性順で表示します。
  XYZは子ごとに表示し、compound親の表示フラグでは子を除外しません。
  標準Channel Boxの表示順への同期は行わず、ノード内部の属性順を維持します。
- bool、float/double、距離、角度に対応します。boolのcompound子も対象です。
  整数、enum、time、文字列、配列とその配下、compound全体は対象外です。
- 同じ正式属性pathと型・単位種別の属性へ絶対値を一括入力します。
  距離と角度は同名でも対応付けません。編集対象数、対応しないnodeや編集不可の理由は
  属性名と入力Viewのtooltipへ表示します。属性のないnodeへ属性を追加することはありません。

属性名は共通幅の列で右揃えにし、入力欄の左端を全行で揃えます。
初期サイズの指定は420×360で、実際の寸法はMayaのドック領域に合わせて調整されます。
値・step欄が狭いタブへ隠れないよう、最小幅は360です。

選択・初期表示・外部変更の同期・表示更新では値を書き込みません。
数値入力はEnterまたはフォーカス移動で確定し、値欄の上下操作・Sliderは操作時に反映します。
未編集のEnterやフォーカス移動も値を書き込みません。boolはoff/onの選択変更で適用します。

値が異なる場合、基準の値を表示したまま属性名の左へ小さな `•` を添えます。
印の意味と対象の詳細はtooltipで確認できます。
属性名を右クリックすると「この値に揃える」「表示を更新」を選べます。
「この値に揃える」は混在していて基準属性が編集可能な場合だけ有効になり、
基準の未丸め実値を他の編集可能な対象へ適用します。メニューを開くだけでは変更しません。
画面の余白からは「表示を更新」を選べます。値・step欄はQt標準の編集メニューを使用します。
すべての対象が同値の入力はUndo履歴を増やしません。

## 範囲、単位、編集不可

両側のhard min/maxが有限で最小値より最大値が大きいfloatには
`FloatSliderSpinBox`、それ以外には`FloatValueStepSpinBox`を使用します。
片側のhard limitも数値入力では尊重します。soft limitは初版では使用しません。
Mayaの表示単位へ追従し、小数桁数は行の生成時にChannel Box設定から取得します。

Slider以外の行には、値欄の右へ `step` 欄を表示します。
フィールド内の「step」表記は省略し、4桁程度と単位が収まるコンパクトな幅にします。

| 属性 | step変更方式 | 初期値 | step欄の上下操作 |
| --- | --- | --- | --- |
| 距離（doubleLinear） | multiplicative | 1 | 0.1 ↔ 1 ↔ 10 |
| 角度（doubleAngle） | additive | 15 | 15 ↔ 30 ↔ 45 |
| その他のfloat / double | multiplicative | 1 | 0.1 ↔ 1 ↔ 10 |
| 正式属性名がradius | multiplicative | 0.1 | 0.01 ↔ 0.1 ↔ 1 |

radiusは型の設定より優先します。Slider行の構成・操作は変更しません。
stepの変更だけでは属性値・Undo履歴を変更せず、次の値欄の上下操作から適用します。
stepは現在の表示単位で扱い、単位変更時も数値を維持します（例: step 1 cm → 1 m）。
step欄への直接入力も可能です。ロック等で値が編集不可でも、step設定だけは変更できます。

変更したstepはWindowが開いている間、正式属性pathと型区分（数値／距離／角度）ごとに
保持します。別ノードの同属性、選択解除・再選択、更新、Undo / Redo、scene切替でも維持し、
X/Y/Zは独立して扱います。Windowの終了・reload後は既定値から開始し、設定ファイルや
sceneへstepを保存しません。

表示範囲は基準属性を使い、他対象の制限は書込み前に検証します。
入力がどれかの編集可能な対象の範囲外なら、その入力全体を拒否して理由を表示します。
対象ごとに値を黙ってclampすることはありません。
属性の表示名・範囲設定を変更した後は、右クリックの「表示を更新」でView構成を読み直せます。

自身またはcompound祖先にlock・入力接続がある属性は編集不可です。
アニメーション接続も表示専用で、キーの作成・変更や接続解除は行いません。
基準が編集不可なら行全体の値入力を止めます。基準以外の編集不可属性は除外し、
残る編集可能な対応属性へ適用します。tooltipの編集対象数はその適用対象数です。

一回の数値確定・bool変更は一回のUndoで戻ります。Sliderドラッグは、全対象を含めて
一回のUndoへまとめます。Undoでは混在していた各ノードの元値が戻ります。
途中の書込み失敗は同じ操作内で復旧し、復旧にも失敗した場合は両方の理由を報告します。

## 更新と終了

選択、属性追加・削除、keyable/channelBox切替、改名、Undo/Redo、scene切替で
構成を再取得します。通常の値変更では全行を作り直さず、Bindingで表示を同期します。
選択が変わると古いBindingと連続編集を終了してから、新しい対象へ接続します。
タイトルバーのclose、`close()`、`dispose()`、tools reloadでもcallbackと入力を終了します。
選択変更による行の再構築とWindow終了では、開いている属性メニューも閉じます。

```python
import bd_tools

bd_tools.reload_package()                 # toolsのみ変更した場合
bd_tools.reload_package(reload_util=True) # utilも変更した場合
```

## 実装の分担

`channel_editor/ui.py` は公開Windowと配置・reload、`widget.py` は属性行と表示、
`controller.py` は基準node・対応属性・選択追従を所有します。
Windowはutilの `MayaDockableWindow` を継承し、`dock_closed` と
`dock_about_to_dispose` で入力controllerを終了します。workspaceControl作成・削除・
Maya再起動時の接続・画面外補正・配置resetはutilへ委譲します。
stepの初期値選択とWindow内の設定保持はtools、値とstepの連動はutilの複合Viewが所有します。
値の単位変換・型付き属性列挙・一括書込み・混在状態・Undoはutilを使用します。
別ツールはこのcontrollerへ暗黙に依存せず、必要な汎用APIをutilから利用します。

## 検証

`tests/maya/test_channel_editor.py` は、選択時の無書込み、外部変更の非伝播、
View選択、混在編集、除外対象、範囲違い、Undo、構成変更を検証します。
`tests/maya/test_channel_editor_dock.py` は、batchで扱えないworkspaceの画面境界を置換し、
公開show / restore / close / reset、Window重複防止、監視解除とreloadを検証します。
公開入口の型は `tests/typecheck/channel_editor_contract.py` で固定します。
対応Maya全versionでruntime testを行い、本体の操作確認は開発用smoke scriptを利用します。

表示整理時はMaya 2025 / 2026 / 2027でtools runtime test各34件と型検査、
unit test 8件、Black checkを通過しています。Maya 2025本体で右クリックメニューからの
更新・揃える・Undoを確認し、Windowとメニューの画像を保存しました。

step追加時はtools runtime testが各versionで30件成功し、utilの統一検証も通過しています。
Maya 2025本体でstep欄のキー操作、刻み幅による一括入力、Undo後のstep保持も確認しました。
検証用Mayaアプリケーションの終了待ちは、下記手順書に記載したタイムアウトが継続しています。

初回実装ではMaya 2025 / 2026 / 2027のtools runtime test各17件と、utilの
統一検証を通過しています。Maya 2025本体でもキー入力、Sliderドラッグ、Undo、
close / reopen、選択追従、util / tools reloadとcallback解放を確認しました。
10ノード・各30追加属性（標準属性込み40行）の単回計測では、行構築を含むWindow生成
約252 ms、一括入力約11 ms、1ノードへの選択切替約73 msでした。環境依存の参考値です。
この条件で追加node callbackは1,230本で、対象数・行数に応じて増加します。
実行コマンド、独立したMaya起動環境、操作内容、画像と計測結果の保存先は
[Maya本体検証の手順](testing.md#channel-editorのmaya本体検証)を参照してください。
