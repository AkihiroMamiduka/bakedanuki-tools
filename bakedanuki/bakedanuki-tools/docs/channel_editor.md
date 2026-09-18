# Channel Editor

選択ノードの値入力と表示・ロック状態を操作する、bool・float 系・enum属性のエディタです。

## 開発状態

2026-09-16に、bool・float系の複数選択編集、step操作、表示整理、Mayaへのドッキングまでの
初回開発を完了し、利用者による動作確認を終えました。今回の範囲に追加必須の機能はありません。
2026-09-17にenumのComboBox入力、2026-09-18に値入力／表示・ロックのモード切替、
両モードの表示フィルターと必要時だけの縦スクロールバー表示を追加しました。その他の拡張は
[今後の候補](roadmap.md#channel-editorの拡張候補)を参照してください。
同日に値同期を高速化し、transform・jointの属性表示に優先順を追加しました。

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
`FloatSliderSpinBox.layout_order`、`MayaChannelStateBinding`、
ドッキングとreloadの基盤が必要です。
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

- 上部の`Mode:`にあるComboBoxで「値編集」と「表示・ロック」を切り替えます。初回は値編集です。
  モードは開いているWindow内だけで保持し、scene・設定ファイルへ保存しません。
  切替だけでは属性の値・状態・Undo履歴を変更しません。
- その下の`Attribute Filter:`にあるComboBoxで表示対象を絞り込みます。両モードで5種類を利用できます。
  初期値は値編集が「keyable + channelbox」、表示・ロックが「全て」です。
  最後に選んだフィルターをモードごとにWindow内だけで保持します。
  選択ノードの変更や表示更新でも保持し、Windowを閉じて開き直すと初期値へ戻ります。
- 現在の選択リストの index 0 が基準です。ノード名だけを画面上部へ表示し、
  選択数と全ノードのpathはそのtooltipへまとめます。
  クリック履歴を記録するMayaの設定は変更しません。
- Maya nodeのobject選択が対象です。componentとplug選択は除外し、Shapeや履歴を
  自動で追加しません。DAG instanceの重複選択は同じnodeへまとめます。
- 基準nodeでフィルターに一致する対応scalarを、下記の優先順で表示します。
  XYZは子ごとに表示し、compound親の表示フラグでは子を除外しません。
  標準Channel Boxの表示順とは独立し、scene内の属性順は変更しません。
- 「全て」では非表示の属性も含めて列挙します。
  以前の操作や別ツールでHideにした属性も復帰できます。標準nodeの内部属性も含むため、
  表示される行数が増えます。値編集でも「全て」「hide」を選べば非表示属性へ入力できます。
  ロック中や入力接続済みの属性の値を変更できない制限は維持します。
- bool、float/double、距離、角度、enumに対応します。bool・enumのcompound子も対象です。
  整数、time、文字列、配列とその配下、compound全体は対象外です。
- 同じ正式属性pathと型・単位種別の属性へ絶対値を一括入力します。
  距離と角度は同名でも対応付けません。編集対象数、対応しないnodeや編集不可の理由は
  属性名と入力Viewのtooltipへ表示します。属性のないnodeへ属性を追加することはありません。

フィルターは基準ノードの現在のplug状態で判定します。
後続ノードの表示状態が異なっても、同名・同種の属性は一括編集の対象に含めます。

| フィルター | 基準属性の条件 |
| --- | --- |
| 全て | 表示状態による除外なし |
| keyable + channelbox | keyableまたはchannelBoxがTrue |
| keyable | keyableがTrue（channelBoxもTrueならこちらに分類） |
| channelbox | keyableがFalse、channelBoxがTrue |
| hide | keyableもchannelBoxもFalse |

状態を変更してフィルター条件から外れた行は、複数対象への操作が完了してから消えます。
「全て」を選ぶと再び表示でき、Undo／Redoや外部での状態変更にも表示が追従します。
フィルター切替だけではscene・Undo履歴を変更しません。

上部の2つのラベルは共通列で右揃えにし、ComboBoxの左端と幅を揃えます。
ラベル列は文字に必要な幅を使い、パネルを広げた分はComboBoxへ配分します。

属性の表示優先順は、両モード・全フィルターで共通です。
存在し、フィルターに一致する属性を次の順で先頭へ配置します。

| 優先位置 | 属性（各行の左から順） |
| --- | --- |
| 1 | visibility |
| 2–4 | translateX, translateY, translateZ |
| 5–7 | jointOrientX, jointOrientY, jointOrientZ |
| 8–10 | rotateX, rotateY, rotateZ |
| 11 | rotateOrder |
| 12–14 | rotateAxisX, rotateAxisY, rotateAxisZ |
| 15–17 | shearXY, shearXZ, shearYZ |
| 18–20 | scaleX, scaleY, scaleZ |
| 21–23 | rotatePivotX, rotatePivotY, rotatePivotZ |
| 24–26 | rotatePivotTranslateX, rotatePivotTranslateY, rotatePivotTranslateZ |
| 27–29 | scalePivotX, scalePivotY, scalePivotZ |
| 30–32 | scalePivotTranslateX, scalePivotTranslateY, scalePivotTranslateZ |
| その後 | drawOverride配下の対応scalar |
| 最後 | その他の対応scalar |

`drawOverride`配下は有効化を操作する`overrideEnabled`を先頭にします。
残りは`overrideColorRGB`のR/G/B子も含め、元の相対順を保ちます。
`overrideColor`は未対応のbyte型のため表示しません。その他の属性も元の相対順を保ちます。
表示名やleaf名ではなく、`translate.translateX`などの正式な属性pathで照合します。
別compound内の同名属性は優先対象に含めず、nodeの型による制限は設けません。
この順序はtoolsの`controller.py`内の`_PRIORITY_ATTRIBUTE_PATHS`へまとめています。
並べ替えは行の構築時だけ行い、通常の値変更では再実行しません。

属性名は共通幅の列で右揃えにし、表示中の全行で入力欄の左端を揃えます。
入力グループは値編集が156 px、表示・ロックが200 pxです。
モード切替ではWindow幅を保ち、設定モードでは名前列を縮めて操作欄を確保します。
初期サイズの指定は320×360、最小幅は280です。実際の寸法はMayaのドック領域に合わせて調整されます。
属性名側の余白は`ui.py`の`_INITIAL_WIDTH`・`_MINIMUM_WIDTH`で調整できます。
名前列の推奨幅は`widget.py`の`_NAME_FIELD_PREFERRED_WIDTH`（92 px）で指定します。
狭いパネルでは名前列を縮めて入力欄を確保します。
長い名前は省略表示し、正式な属性pathと省略していない表示名をtooltipへ表示します。
行数や名前の長さでWindow幅を広げず、縦スクロールバーは内容が収まらない場合だけ表示します。
その出入りに伴って、名前列の幅と入力欄の位置は変わります。
保存済みの広い配置を使っている場合は、パネル幅を縮めるか`reset_layout()`で初期配置へ戻します。

選択・初期表示・外部変更の同期・表示更新では値を書き込みません。
数値入力はEnterまたはフォーカス移動で確定し、値欄の上下操作・Sliderは操作時に反映します。
未編集のEnterやフォーカス移動も値を書き込みません。
数値の文字入力中に上部のモード・フィルターComboBoxへ移動した場合も、通常のフォーカス移動として
その編集を確定します。未編集の表示切替だけで値を揃えることはありません。
boolはutilの`BoolCheckBox`を使い、属性名のすぐ右、数値入力列の左端にチェックを表示します。
チェックまたはSpaceキーで切り替えると、対応する編集可能なノードへ一括適用します。
boolが混在していてもチェックは基準ノードのTrue / Falseを表示し、三状態表示にはしません。

enumはutilの`EnumComboBox`で項目名を表示します。入力列全体の156 pxを使い、
Step／Sliderは表示しません。標準属性（rotateOrderなど）も追加属性も同じ扱いですが、
他の型と同じフィルターで表示対象を決めます。
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
モードやフィルターの切替でもstep設定を維持します。

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

## 表示・ロック

属性名の右側を、`key / ch / hide`のラジオボタンと`lock`のCheckBoxへ切り替えます。
表示状態の3つだけを排他的に選択し、ロックは独立して操作できます。
設定モードの操作欄は200 pxです。狭いWindowでは属性名の省略が増えますが、
正式な名前はtooltipで確認できます。各ボタンのtooltipには省略前の意味も表示します。

| 表示状態 | keyable | channelBox |
| --- | --- | --- |
| key（Keyable） | True | False |
| ch（ChannelBox） | False | True |
| hide（Hide） | False | False |

Keyableはキー設定可能、ChannelBoxはキー設定不可でChannel Boxへ表示、
Hideはキー設定不可でChannel Boxから非表示の状態です。
既存属性のkeyableとchannelBoxが両方Trueの場合はKeyableとして表示します。
Hideは上記のplug状態だけを変更し、属性定義のhiddenや属性自体は変更・削除しません。
表示状態はロックを変更せず、ロック／解除は表示状態を変更しません。値やキーにも書き込みません。

属性定義によってkeyableとchannelBoxが両方Trueになっている特殊な属性は、
Maya標準Undoで元の組合せを復元できないため、表示状態の変更対象から除外します。
基準ノードの属性がこの状態なら、その行の表示状態の操作全体を無効にします。
基準以外だけが該当する場合は、その対象を除いて残りへ適用します。
理由はtooltipへ表示し、状態の自動修正や属性定義の変更は行いません。
この制限は表示状態にだけ適用し、ロック／解除は通常の操作可否に従って利用できます。

複数選択の対象は、値編集と同じ正式属性path・型区分の属性です。
enumの項目定義は変更しないため、定義が異なるenumも状態編集の対象になります。
表示状態が異なる場合はラジオボタンを3つとも未選択にし、属性名の「•」とtooltipで混在を示します。
ロックが異なる場合はCheckBoxへ三状態の印を表示します。
表示同期だけでは揃えず、表示状態を選択したときやロックを操作したときに、その項目だけ一括適用します。
ラジオボタンはクリック・Space・矢印キーで選択できます。同じ状態の再選択はUndo履歴を増やしません。
ロック混在のクリック／Spaceはロックする操作です。次の操作で解除します。
属性名と入力欄のtooltipで、各操作の対象数や操作できない理由を確認できます。

ロック中や入力接続済みの属性でも、表示状態の編集や自身のロック解除を操作できます。
値編集の可否判定は流用せず、状態ごとに操作可否を判定します。
compound祖先がロックされている場合、子の操作で祖先まで自動解除しません。
自身のロックと親による制限は区別して表示します。
属性名の右クリックと余白のメニューから「表示を更新」を選べます。

1回の表示状態変更、またはロック変更を、それぞれ1回のMaya標準Undoへまとめます。
Undoでは対象ごとに異なっていた状態と元のkeyable／channelBoxの組合せを復元します。
同じ状態への入力はUndo履歴を増やしません。外部変更とUndo／Redoにも追従します。

## 更新と終了

選択、属性追加・削除、keyable/channelBox切替、改名、Undo/Redo、scene切替で
構成を再取得します。「全て」では表示フラグだけの変更による全行再構築は不要です。
通常の値変更では全行を作り直さず、Bindingで表示を同期します。
utilの複数属性Bindingはdirtyになったplugと祖先を照合し、関係する行だけを読み直します。
「全て」で多数の行を表示しても、独立した1属性の変更で他の行を再読取りしません。
接続・親属性・アニメーションによる変更も追従し、Undo／Redoや単位変更では全対象を再同期します。
選択が変わると古いBindingと連続編集を終了してから、新しい対象へ接続します。
タイトルバーのclose、`close()`、`dispose()`、tools reloadでもcallbackと入力を終了します。
モード・フィルター切替、選択変更による行の再構築とWindow終了では、開いている属性メニューと
enum・表示状態の選択肢も閉じ、古いBindingと連続編集を終了します。

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
属性の表示・ロック状態の読取り、一括操作、Undo、操作可否と監視もutilが所有します。
値編集と状態編集の対象選別、モード・フィルター切替とWindow内の選択保持、
共通入力幅と各入力欄はtoolsが所有します。
状態変更による絞り込みはQtの次のイベントで行い、書込み中のBindingを破棄しません。
別ツールはこのcontrollerへ暗黙に依存せず、必要な汎用APIをutilから利用します。

### 見た目の調整箇所

以下の定数は`bd_tools/channel_editor`配下で管理します。サイズは全Maya versionで共通です。

| ファイル | 定数 | 現在値 | 調整する内容 |
| --- | --- | --- | --- |
| `widget.py` | `_VALUE_FIELD_WIDTH` | 90 | 数値入力欄の固定幅 |
| `widget.py` | `_AUXILIARY_FIELD_WIDTH` | 60 | StepとSliderの共通固定幅 |
| `widget.py` | `_FIELD_SPACING` | 6 | ValueとStep / Sliderの間隔 |
| `widget.py` | `_EDITOR_WIDTH` | 156（上記から算出） | 値編集の入力列の幅 |
| `widget.py` | `_STATE_EDITOR_WIDTH` | 200 | 表示・ロックの操作列の幅 |
| `widget.py` | `_NAME_FIELD_PREFERRED_WIDTH` | 92 | 属性名列の推奨幅。長い名前は省略表示 |
| `ui.py` | `_INITIAL_WIDTH` | 320 | Window / workspaceControlの初期幅 |
| `ui.py` | `_MINIMUM_WIDTH` | 280 | Window / workspaceControlの最小幅 |

utilの`FloatValueStepSpinBox`のstep既定幅は68ですが、このツールでは60を明示指定しています。
値・補助欄の幅を変えたら、最小Window幅で入力が隠れないことも確認してください。
属性名列は余剰幅を受け取るため、名前の推奨幅だけを下げても広いパネルの余白は減りません。
パネル幅と初期・最小Window幅を合わせて調整します。boolは同じ入力列の左端に配置します。

定数を変更した後はtoolsをreloadして`channel_editor`をimportし直し、`show()`で作り直します。
保存済みworkspaceの幅が優先される場合は、パネルを手動で縮めるか`reset_layout()`を実行します。
幅・配置を変更した際は`tests/maya/test_channel_editor.py`の配置検証も新しい仕様に合わせ、
Sliderあり／なし、最小幅／拡大時、ドック／floatingで表示を確認してください。

### 拡張時に維持する仕様

- 選択・表示更新・外部からの値変更は読取りと表示同期だけにし、他ノードへ値を転送しない。
- 明示的な入力・揃える操作だけを一括編集し、Undoで各ノードの元値を復元する。
- Stepの変更はViewの操作設定として扱い、sceneとUndoへ書き込まない。
- モード・フィルター切替では値・状態・Undoを変更せず、入力幅とstep設定を維持する。
- 表示状態とロックを独立して変更し、非表示属性も状態モードから復帰できるようにする。
- 編集不可属性や型・範囲の不一致を尊重し、除外理由や拒否理由を表示する。
- 選択切替・close・reloadでは古い入力、連続編集、callback、メニューを確実に終了する。
- 汎用の型・Binding・View・保存基盤はutil、表示対象と各行の組み合わせはtoolsへ置く。

## 検証

`tests/maya/test_channel_editor.py` は、選択時の無書込み、外部変更の非伝播、
View選択、混在編集、除外対象、範囲違い、Undo、構成変更を検証します。
「keyable」「全て」のどちらでも、UI・外部入力によって無関係な行の再読取りや
全行の作り直しが発生しないことを、時間の閾値ではなく更新対象で検証します。
`tests/maya/test_channel_editor_enum.py`は、enumの飛び番・定義不一致の除外、使用中の
定義変更、未定義値、ロック・接続、混在、Undo／Redo、選択肢の終了を検証します。
`tests/maya/test_channel_editor_states.py`は、既存Hide属性の列挙と復帰、表示・ロックの
独立操作、混在、Undo／Redo、モード切替の無書込みとstep保持、必要時だけのスクロールを検証します。
両モードの5種類のフィルター、モードごとの選択保持、状態変更後の絞り込みとUndo／Redo、
非表示属性の値入力・操作制限、外部変更、入力途中や連続編集中の切替も検証します。
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

### 表示・ロック追加時の確認（2026-09-18）

| 確認対象 | 結果 |
| --- | --- |
| toolsの`check.cmd -IncludeMaya` | Black・Pyright・unit 8件・Maya 2025 runtime 68件が成功 |
| Maya 2026 / 2027のtools runtime test | 各68件成功 |
| toolsの3 version Pyright | エラー・警告なし |
| utilの`verify.cmd` | 成功。3 versionの型・Qt/UI互換性、全pytest、差分チェックを含む |
| utilのUI専用検証 | Qt/UIは790件、Maya UIは326件を各versionで成功。状態編集基盤の17件を含む |
| Maya 2025本体の操作 | 34工程成功。モード切替、既存Hideの復帰、表示状態、Lock/Unlock、混在、Undo/Redo、step維持を含む |
| 幅・列配置 | 280 / 360 / 520 pxの両モードで横スクロールなし。本体では値13行から設定147行へ増えても列幅を維持 |
| Maya 2025本体の終了 | 既知の終了待ちタイムアウトが再現。操作結果は成功、runnerの終了codeは1 |

未編集のモード切替はscene・Undoを変更せず、キーボードの上下キーだけで往復できます。
入力途中の数値は通常のフォーカス移動として確定し、状態編集とは別のUndo操作になります。
Maya 2025本体の保存画像で切替前後の列位置、名前の省略、混在とロックの表示を確認しました。
今回もMaya 2026 / 2027本体の画面操作は実施していません。
本体検証の結果・画像は検証実行環境の
`%TEMP%/bd-channel-editor-maya2025-xnb085bt`へ保存しました。

### 表示フィルター・スクロールバー変更時の確認（2026-09-18）

| 確認対象 | 結果 |
| --- | --- |
| toolsの`check.cmd -IncludeMaya` | Black・Pyright・unit 8件・Maya 2025 runtime 86件が成功 |
| Maya 2026 / 2027のtools runtime test | 各86件成功 |
| toolsの3 version Pyright | エラー・警告なし |
| モード・状態・フィルター関連test | 37件成功。両モードの5分類、選択保持、状態変更後の行の除去・Undo／Redo、Hideの値入力と操作制限を含む |
| Maya 2025本体の操作 | 36工程成功。実ComboBoxからの絞り込み、状態操作後の再評価、Undo／Redo、close／reload後のcallback解放を含む |
| 幅・列配置 | 280 / 360 / 520 pxで横スクロールなし。縦スクロールバーの出入りを確認し、入力グループ156 pxを維持 |
| Maya 2025本体の終了 | 既知の終了待ちタイムアウトが再現。操作結果は成功、runnerの終了codeは1 |

本体画像で値編集の「hide」、表示・ロックの「keyable」、既定の両モードを確認しました。
フィルターにより行数が変わっても横スクロールは発生せず、必要時だけ縦スクロールバーを表示します。
この拡張はtoolsだけの変更です。Maya 2026 / 2027はruntime testで検証し、本体の画面操作は未実施です。
本体検証の結果・画像は検証実行環境の
`%TEMP%/bd-channel-editor-maya2025-ux83mnxs`へ保存しました。

### 値同期の高速化（2026-09-18）

utilの複数属性Storeを変更し、dirtyになったplugと祖先に関係するBindingだけを再同期します。
通知されたnodeの対象をcallbackへ直接渡すことで、複数選択時に他nodeの対象を走査しません。
公開APIやUIは変更せず、既存scene・保存設定の移行も不要です。反映にはutilを含めて更新し、
`bd_tools.reload_package(reload_util=True)`で再読込みしてください。

Maya 2025 standalone・Qt offscreenで、transformに追加した独立double属性`weight`を
同じUI操作で変更しました。生成・フィルター切替を計測区間から除き、2回warm-up後の
9回の中央値を比較しています。遅延同期とQtイベント処理を含みます。

| 選択node数 | フィルター・行数 | 変更前 | 変更後 |
| --- | --- | --- | --- |
| 1 | keyable・11行 | 1.316 ms | 0.629 ms |
| 1 | 全て・144行 | 14.517 ms | 1.287 ms |
| 10 | keyable・11行 | 2.996 ms | 1.462 ms |
| 10 | 全て・144行 | 51.444 ms | 10.706 ms |

「全て」の同じUI入力では、Storeの再読取りは144回から変更行の1回へ減りました。
callback自体の登録数は同じですが、複数選択時の照合は通知node内に限定しています。
これは独立シーンでの参考値です。実際のrig評価・viewport描画や環境負荷による時間は別途変わります。
外部`setAttr`からの同期も計測し、他属性への転送や無関係な行の再読取りがないことを確認しました。

検証結果は次のとおりです。

- toolsの`check.cmd -IncludeMaya`: Black・Pyright・unit 8件・Maya 2025 runtime 90件が成功。
- Maya 2026 / 2027のtools runtime test: 各90件成功。
- utilの`verify.cmd`: Black・3 versionのPyright・Maya 2025 full pytest・3 versionのUI互換性・差分検査が成功。
  Qt/UIは各790件、Maya UIは各340件。通知対象を絞る追加回帰test 14件を含む。
- util変更ファイルのMaya 2025 Pyright: エラー・警告なし。
- Maya 2025本体: 36工程成功。10node・各30追加属性の入力中央値はkeyable 40行で5.564 ms、
  全て173行で18.746 ms。単独の計測条件とは異なるため、上表と直接比較しない。

Maya本体の操作結果・画像は検証実行環境の
`%TEMP%/bd-channel-editor-maya2025-euh2_qt8`へ保存しました。
本体終了時は既知の終了待ちタイムアウトが再現し、runnerの終了codeは1です。
36工程の操作成功とプロセスの正常終了は区別しています。
Maya 2026 / 2027はruntimeとUI互換性の自動検証で確認し、本体の画面操作は未実施です。

### 属性の表示優先順（2026-09-18）

指定32属性、drawOverride配下、その他の順に、行の構築時だけ並べ替えます。
通常の値変更では行を作り直さず、関係する行だけを再同期する従来の処理を維持します。
toolsだけの変更です。反映には`bd_tools.reload_package()`で再読込みしてから開き直します。

- `check.cmd -IncludeMaya`: Black・Pyright・unit 8件・Maya 2025 runtime 96件が成功。
- Maya 2026 / 2027のruntime test: 各96件成功。
- 追加した順序検証6件: transform・joint、両モード・5フィルター、RGB子と残りの相対順、
  正式pathの照合、node型に依存しない優先表示、scene・Undoへの無書込みを確認。
- 既存の値同期test: 独立した値の変更で無関係な行を再読取りせず、行Widgetを維持することを確認。
- Maya 2025本体: 37工程成功。jointの両モードで指定32属性とdrawOverrideの配置を確認。
  保存画像で優先順と入力欄の配置を確認し、close／reload後のcallback解放も成功。

本体検証の結果・画像は検証実行環境の
`%TEMP%/bd-channel-editor-maya2025-p3febnx8`へ保存しました。
本体終了時は既知の終了待ちタイムアウトが再現し、runnerの終了codeは1です。
37工程の操作成功とは区別し、検証専用processの停止を確認しました。
Maya 2026 / 2027本体の画面操作は今回実施していません。

同日の追加調整で、drawOverride内の先頭をoverrideEnabledへ変更しました。
残りの相対順は維持し、関連Maya 2025 test 10件、Pyright、Black checkが成功しました。
Maya 2025本体も37工程成功し、両モードの保存画像でoverrideEnabledが先頭になることを確認しました。
追加調整の結果・画像は`%TEMP%/bd-channel-editor-maya2025-1nuu7kke`へ保存しました。
追加調整でも本体終了待ちの既知タイムアウトが再現し、runnerの終了codeは1です。

### 上部ComboBoxの説明ラベル（2026-09-18）

ModeとAttribute Filterのラベルを右揃えの共通列に追加しました。
関連Maya 2025 test 26件、Pyright、Black checkが成功し、280 / 360 / 520 pxで
ラベルと選択欄の整列・幅、モード・フィルター操作を確認しました。
Maya 2025本体も37工程成功し、保存画像で両モードの文字と配置を確認しました。
本体検証の結果・画像は`%TEMP%/bd-channel-editor-maya2025-za269o96`へ保存しました。
終了待ちでは既知のタイムアウトが再現し、runnerの終了codeは1です。
操作37工程の成功とは区別し、検証専用processの停止を確認しました。

### 表示状態のラジオボタン化（2026-09-18）

表示状態をkey／ch／hideのラジオボタンに変更し、設定モードの操作幅を200 pxにしました。
lockは独立したCheckBoxとし、表示状態の混在時は3ボタンとも未選択にします。
既存のMayaChannelStateBindingを利用するtoolsだけの変更です。

- `check.cmd -IncludeMaya`: Black・Pyright・unit 8件・Maya 2025 runtime 98件が成功。
- Maya 2026 / 2027のruntime test: 各98件成功。
- 280 / 360 / 520 pxの配置、クリック・矢印・Space、混在、一括入力、Undo／Redo、
  編集不可状態での無書込み、フィルターによる行の除去・再表示を確認。
- Maya 2025本体: 37工程成功。実マウス入力とSpaceで状態を変更し、
  保存画像で200 pxの操作欄・文字・混在表示を確認。

本体検証の結果・画像は`%TEMP%/bd-channel-editor-maya2025-wv4li987`へ保存しました。
終了待ちでは既知のタイムアウトが再現し、runnerの終了codeは1です。
操作37工程の成功とは区別し、検証専用processの停止を確認しました。
Maya 2026 / 2027本体の画面操作は今回実施していません。
