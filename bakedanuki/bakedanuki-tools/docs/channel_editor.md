# Channel Editor

選択ノードの値入力を支援する、bool・float 系・enum属性のエディタです。

## 開発状態

2026-09-16に、bool・float系の複数選択編集、step操作、表示整理、Mayaへのドッキングまでの
初回開発を完了し、利用者による動作確認を終えました。今回の範囲に追加必須の機能はありません。
2026-09-17にenumのComboBox入力を追加しました。その他の拡張は
[今後の候補](roadmap.md#channel-editorの拡張候補)を参照してください。

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

利用するutilには、複数属性用の`MayaBoolPlugsBinding` / `MayaFloatPlugsBinding`、
`MayaEnumPlugsBinding`、`EnumComboBox`、`read_enum_definition()`、enum対応の属性列挙、
属性列挙・選択取得、`BoolCheckBox`、`FloatValueStepSpinBox`の幅指定、
`FloatSliderSpinBox.layout_order`、ドッキングとreloadの基盤が必要です。
toolsとutilを配布するときは、組み合わせて動作確認した版を使用してください。

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
- bool、float/double、距離、角度、enumに対応します。bool・enumのcompound子も対象です。
  整数、time、文字列、配列とその配下、compound全体は対象外です。
- 同じ正式属性pathと型・単位種別の属性へ絶対値を一括入力します。
  距離と角度は同名でも対応付けません。編集対象数、対応しないnodeや編集不可の理由は
  属性名と入力Viewのtooltipへ表示します。属性のないnodeへ属性を追加することはありません。

属性名は共通幅の列で右揃えにし、入力欄の左端を全行で揃えます。
初期サイズの指定は320×360、最小幅は280です。実際の寸法はMayaのドック領域に合わせて調整されます。
属性名側の余白は`ui.py`の`_INITIAL_WIDTH`・`_MINIMUM_WIDTH`で調整できます。
名前列の最小幅は`widget.py`の`_NAME_FIELD_MINIMUM_WIDTH`（92 px）で指定し、長い名前には自動で広げます。
保存済みの広い配置を使っている場合は、パネル幅を縮めるか`reset_layout()`で初期配置へ戻します。

選択・初期表示・外部変更の同期・表示更新では値を書き込みません。
数値入力はEnterまたはフォーカス移動で確定し、値欄の上下操作・Sliderは操作時に反映します。
未編集のEnterやフォーカス移動も値を書き込みません。
boolはutilの`BoolCheckBox`を使い、属性名のすぐ右、数値入力列の左端にチェックを表示します。
チェックまたはSpaceキーで切り替えると、対応する編集可能なノードへ一括適用します。
boolが混在していてもチェックは基準ノードのTrue / Falseを表示し、三状態表示にはしません。

enumはutilの`EnumComboBox`で項目名を表示します。入力列全体の156 pxを使い、
Step／Sliderは表示しません。標準属性（rotateOrderなど）も追加属性も同じ扱いですが、
基準属性の`keyable OR channelBox`がFalseなら表示しません。
負数・飛び番を扱い、ComboBoxの位置ではなく定義の整数値を入力します。
tooltipには省略されていない基準の項目名と実整数も表示します。

enumの編集対象は、正式属性pathと型に加えて**整数値と項目名の対応**が一致するノードです。
定義の表示順だけの違いは許容します。初期表示・選択変更・表示更新時に不一致の対象を
除外し、tooltipへ理由を表示します。項目名による値の変換や定義の書き換えは行いません。
Bindingへ登録した対象の定義が使用中に不一致になると、その行の入力を停止します。
定義が揃えば再開し、「表示を更新」では除外した対象も含めて組み合わせを再判定します。
除外済みの対象を定義修正後に戻す場合も「表示を更新」を使用してください。

現在値が選択肢に含まれない場合は`未定義 (5)`などと表示し、値を自動修正しません。
有効な項目への変更は可能ですが、「この値に揃える」は無効になります。
選択肢が空なら入力も無効です。ComboBoxで同じ項目を選び直すだけでは書き込まず、
混在した値を表示中の項目へ揃える場合は属性名の「この値に揃える」を使います。

値が異なる場合、基準の値を表示したまま属性名の左へ小さな `•` を添えます。
印の意味と対象の詳細はtooltipで確認できます。
属性名を右クリックすると「この値に揃える」「表示を更新」を選べます。
「この値に揃える」は混在していて基準属性が編集可能な場合だけ有効になり、
基準の未丸め実値を他の編集可能な対象へ適用します。メニューを開くだけでは変更しません。
画面の余白からは「表示を更新」を選べます。値・step欄はQt標準の編集メニューを使用します。
すべての対象が同値の入力はUndo履歴を増やしません。

たとえばAが1、Bが2なら、選択時には1を表示したままBの2を維持します。
表示中の1へ揃えるだけなら、属性名のメニューから「この値に揃える」を実行します。
表示精度によって丸められた文字列ではなく、基準ノードの実値を適用します。

## 範囲、単位、編集不可

両側のhard min/maxが有限で最小値より最大値が大きいfloatには
`FloatSliderSpinBox`、それ以外には`FloatValueStepSpinBox`を使用します。
通常float行は`[Value][Step]`、Slider行は`[Value][Slider]`の順に配置します。
値欄は90 px、Step／Sliderは共通の60 px、欄間は6 pxに固定します。
通常float行はutilの`value_width`・`step_width`を使い、Sliderにも同じ幅を指定します。
数値入力グループ全体を156 pxで右寄せし、画面を広げた分は属性名側へ配分します。
boolも同じ幅の入力列を確保し、その中でチェックを左詰めにします。
Sliderの有無によらず、入力欄の左端・右端とStep／Sliderの開始位置が揃います。
片側のhard limitも数値入力では尊重します。soft limitは初版では使用しません。
Mayaの表示単位へ追従し、小数桁数は行の生成時にChannel Box設定から取得します。
値欄・step欄の単位文字（cm / degなど）は、Slider付きの値欄も含めて非表示です。
文字を省略しても、現在の表示単位での数値表示・入力と単位変更時の換算は継続します。

Slider以外の行には、値欄の右へ `step` 欄を表示します。
フィールド内の「step」表記は省略し、4桁程度が収まるコンパクトな幅にします。

| 属性 | step変更方式 | 初期値 | step欄の上下操作 |
| --- | --- | --- | --- |
| 距離（doubleLinear） | multiplicative | 1 | 0.1 ↔ 1 ↔ 10 |
| 角度（doubleAngle） | additive | 15 | 15 ↔ 30 ↔ 45 |
| その他のfloat / double | multiplicative | 1 | 0.1 ↔ 1 ↔ 10 |
| 正式属性名がradius | multiplicative | 0.1 | 0.01 ↔ 0.1 ↔ 1 |

radiusは型の設定より優先します。Slider行にも同じ値欄幅を適用します。
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

一回の数値確定・bool変更・enum項目変更は一回のUndoで戻ります。Sliderドラッグは、全対象を含めて
一回のUndoへまとめます。Undoでは混在していた各ノードの元値が戻ります。
途中の書込み失敗は同じ操作内で復旧し、復旧にも失敗した場合は両方の理由を報告します。

## 更新と終了

選択、属性追加・削除、keyable/channelBox切替、改名、Undo/Redo、scene切替で
構成を再取得します。通常の値変更では全行を作り直さず、Bindingで表示を同期します。
選択が変わると古いBindingと連続編集を終了してから、新しい対象へ接続します。
タイトルバーのclose、`close()`、`dispose()`、tools reloadでもcallbackと入力を終了します。
選択変更による行の再構築とWindow終了では、開いている属性メニューとenumの選択肢も閉じます。

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

### 見た目の調整箇所

以下の定数は`bd_tools/channel_editor`配下で管理します。サイズは全Maya versionで共通です。

| ファイル | 定数 | 現在値 | 調整する内容 |
| --- | --- | --- | --- |
| `widget.py` | `_VALUE_FIELD_WIDTH` | 90 | 数値入力欄の固定幅 |
| `widget.py` | `_AUXILIARY_FIELD_WIDTH` | 60 | StepとSliderの共通固定幅 |
| `widget.py` | `_FIELD_SPACING` | 6 | ValueとStep / Sliderの間隔 |
| `widget.py` | `_EDITOR_WIDTH` | 156（上記から算出） | boolも含めて確保する入力列の幅 |
| `widget.py` | `_NAME_FIELD_MINIMUM_WIDTH` | 92 | 属性名列の最小幅。長い名前では自動拡張 |
| `ui.py` | `_INITIAL_WIDTH` | 320 | Window / workspaceControlの初期幅 |
| `ui.py` | `_MINIMUM_WIDTH` | 280 | Window / workspaceControlの最小幅 |

utilの`FloatValueStepSpinBox`のstep既定幅は68ですが、このツールでは60を明示指定しています。
値・補助欄の幅を変えたら、最小Window幅で入力が隠れないことも確認してください。
属性名列は余剰幅を受け取るため、名前の最小幅だけを下げても広いパネルの余白は減りません。
パネル幅と初期・最小Window幅を合わせて調整します。boolは同じ入力列の左端に配置します。

定数を変更した後はtoolsをreloadして`channel_editor`をimportし直し、`show()`で作り直します。
保存済みworkspaceの幅が優先される場合は、パネルを手動で縮めるか`reset_layout()`を実行します。
幅・配置を変更した際は`tests/maya/test_channel_editor.py`の配置検証も新しい仕様に合わせ、
Sliderあり／なし、最小幅／拡大時、ドック／floatingで表示を確認してください。

### 拡張時に維持する仕様

- 選択・表示更新・外部からの値変更は読取りと表示同期だけにし、他ノードへ値を転送しない。
- 明示的な入力・揃える操作だけを一括編集し、Undoで各ノードの元値を復元する。
- Stepの変更はViewの操作設定として扱い、sceneとUndoへ書き込まない。
- 編集不可属性や型・範囲の不一致を尊重し、除外理由や拒否理由を表示する。
- 選択切替・close・reloadでは古い入力、連続編集、callback、メニューを確実に終了する。
- 汎用の型・Binding・View・保存基盤はutil、表示対象と各行の組み合わせはtoolsへ置く。

## 検証

`tests/maya/test_channel_editor.py` は、選択時の無書込み、外部変更の非伝播、
View選択、混在編集、除外対象、範囲違い、Undo、構成変更を検証します。
`tests/maya/test_channel_editor_enum.py`は、enumの飛び番・定義不一致の除外、使用中の
定義変更、未定義値、ロック・接続、混在、Undo／Redo、選択肢の終了を検証します。
`tests/maya/test_channel_editor_dock.py` は、batchで扱えないworkspaceの画面境界を置換し、
公開show / restore / close / reset、Window重複防止、監視解除とreloadを検証します。
公開入口の型は `tests/typecheck/channel_editor_contract.py` で固定します。
対応Maya全versionでruntime testを行い、本体の操作確認は開発用smoke scriptを利用します。

初回開発完了時の確認結果（2026-09-16）です。対象のtoolsは`bed114f`、utilは`e8e996dc`です。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright | 通過 |
| unit test | 8件成功 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各38件成功 |
| 配置 | 280 / 360 / 520 pxで横スクロールなし、Sliderの有無とCheckBoxの左詰めを確認 |
| Maya 2025本体の操作 | 24工程成功。CheckBoxのSpace操作、float入力、Sliderドラッグ、Undo、ドック／floating、reloadを含む |
| Maya 2025本体の終了 | 終了待ちでタイムアウト。操作結果は成功だがrunnerは終了code 1 |

Maya 2026 / 2027の最終UI変更はruntime testによる確認です。最終配置の本体画像確認はMaya 2025で行いました。
終了待ちの原因調査は未完了です。操作成功とプロセスの正常終了を区別し、runner全体が成功したとは扱いません。
UIを配布する前には、利用するMaya versionと画面倍率・フォントでも文字切れと操作を確認します。
大量選択時の性能は、既存runnerの計測を使って必要に応じて再評価します。
実行コマンド、独立したMaya起動環境、操作内容、画像と計測結果の保存先は
[Maya本体検証の手順](testing.md#channel-editorのmaya本体検証)を参照してください。

### enum追加時の確認（2026-09-17）

| 確認対象 | 結果 |
| --- | --- |
| toolsの`check.cmd -IncludeMaya` | Black・Pyright・unit 8件・Maya 2025 runtime 49件が成功 |
| Maya 2026 / 2027のtools runtime test | 各49件成功 |
| utilの`verify.cmd` | 成功。3 versionの型・Qt/UI互換性を含む |
| utilのMaya 2025 full pytest | 4,176 passed / 690 skipped。Qt/UI専用processで790件、Maya UI専用processで309件を各versionで別途検証 |
| Maya 2025本体の操作 | 29工程成功。enumの選択肢表示・マウス入力・飛び番・代表値へ揃える操作・Undoを含む |
| Maya 2025本体の終了 | 既知の終了待ちタイムアウトが再現。操作結果は成功、runnerの終了codeは1 |

offscreenで発生していた最小幅の配置testの失敗は、Qtのフォント一覧が空だったためです。
test環境でSegoe UIを読み込む対応により、enumも含めて280 / 360 / 520 pxの配置検証が成功しました。
製品のフォント・幅設定は変更していません。Maya 2025本体の保存画像でもComboBoxと選択肢を確認しました。
Maya 2026 / 2027本体での手動操作は今回実施していません。
