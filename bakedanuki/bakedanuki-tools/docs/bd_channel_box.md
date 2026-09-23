# bdChannelBox

選択ノードの値入力と表示・ロック状態を操作する、bool・float 系・enum属性のエディタです。

## 開発状態

2026-09-19に、選択切替の高速化まで利用者による動作確認を終えました。
その後の要望による属性の複数選択、数値の直接一括入力、基本メニューの初回実装と、
自動テスト・Maya 2025本体での操作検証が完了しました。複数行の同時編集は利用者も動作確認済みです。
この拡張の検証結果は、従来機能の利用者確認・完了記録と分けて扱います。

bool・float系・enumの複数ノード編集、step操作、表示・ロックの切替、5種類の表示フィルター、
属性検索、表示状態とlockのなぞり操作、設定可能な属性優先順、ドッキングと再起動復元に対応しています。
選択属性値はOSクリップボードを介して別のMayaへ搬送できます。
値同期と選択切替の負荷も改善しました。将来の任意候補は
[Roadmap](roadmap.md#bdchannelboxの拡張候補)、変更ごとの確認結果は[検証](#検証)を参照してください。

## 起動と終了

```python
from bd_tools import bd_channel_box

window = bd_channel_box.show()
bd_channel_box.close()
```

`show()` は既存Windowを再利用します。importだけでは表示やscene変更を行いません。
初回はMaya右側へドッキングします。タイトル部分をドラッグして、他の領域への移動、
タブ化、floatingへ切り替えられます。移動だけでは入力やstep設定を破棄しません。
配置はMayaのworkspaceへ保存され、再表示やMaya再起動時の復元に使われます。
本変更に対応した `bakedanuki-util` と組み合わせて使用してください。

利用するutilには、複数属性用の`MayaBoolPlugsBinding` / `MayaFloatPlugsBinding`、
`MayaEnumPlugsBinding`、`EnumComboBox`、`read_enum_definition()`、enum対応の属性列挙、
属性列挙・選択取得、`BoolCheckBox`、`FloatValueStepSpinBox`の幅指定、
`FloatSliderSpinBox.layout_order`、`MayaChannelStateBinding`、`MayaEditSession`、
`RadioButtonSweep` / `CheckBoxSweep`、`apply_plugs_values()`と
`MayaFloatValueEdit` / `MayaBoolValueEdit` / `MayaEnumValueEdit`、
ドッキングとreloadの基盤が必要です。
toolsとutilを配布するときは、組み合わせて動作確認した版を使用してください。

タイトルバーまたは `close()` で、workspaceControl・入力・callbackを破棄します。
次の `show()` は新しいWindowを生成します。開発時の完全破棄には `dispose()` を使います。
Escapeは値欄やメニューの操作に使い、パネル全体は閉じません。

配置を初期状態へ戻す場合は、次を実行します。

```python
window = bd_channel_box.reset_layout()
```

固定workspaceControl名は `bd_channel_box.WORKSPACE_CONTROL_NAME`
（`bdChannelBoxWindowWorkspaceControl`）です。
MayaのuiScriptは `bd_tools.bd_channel_box.ui.restore()` を呼び、復元中のcontrolへ内容を接続します。
`restore()` は通常の起動用ではなくMayaの復元処理専用です。
再起動後もtoolsとutilをimportできるよう、Maya.envまたはmodule pathの設定が必要です。

初回は右側へ配置し、以降はMayaが保存したworkspace配置を使います。
`reset_layout()` はworkspaceControlの保存配置をutilの統合APIで消去します。

## 表示と入力

- 一覧の余白・属性名・入力部品の周囲は、Maya UIの通常背景色を使います。
  数値・Stepなどの入力欄は暗い背景を保ち、入力箇所を区別します。
  boolのOFF表示も通常背景上に描画し、選択中は属性名だけを青く強調します。
  属性名の右側には4pxの内側余白を設け、選択色と文字の間隔を保ちます。
  属性名と入力Viewの間に外側の隙間は設けず、入力View内部の各欄は6px間隔で表示します。
  値・Step・Slider・bool・enumの入力部品は、属性選択によって配色を変更しません。
  色番号は固定せず、現在のQt paletteを使用します。
- 上部の`Mode:`にあるComboBoxで「値編集」と「表示・ロック」を切り替えます。初回は値編集です。
  モードは開いているWindow内だけで保持し、scene・設定ファイルへ保存しません。
  切替だけでは属性の値・状態・Undo履歴を変更しません。
- その下の`Attribute Filter:`にあるComboBoxで表示対象を絞り込みます。両モードで5種類を利用できます。
  初期値は値編集が「keyable + channelbox」、表示・ロックが「全て」です。
  最後に選んだフィルターをモードごとにWindow内だけで保持します。
  選択ノードの変更や表示更新でも保持し、Windowを閉じて開き直すと初期値へ戻ります。
- `Attribute Search:`はNice Name・属性名・正式pathを検索します。初期状態では
  Attribute Filterが「全て」の場合だけ表示し、検索文字列はWindow内だけで保持します。
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
ラジオボタンをなぞっている間は行を維持し、マウスを離した後にまとめて絞り込みます。
「全て」を選ぶと再び表示でき、Undo／Redoや外部での状態変更にも表示が追従します。
フィルター切替だけではscene・Undo履歴を変更しません。

### 属性検索

検索欄はNice Name・leaf属性名・`translate.translateX`などの正式属性pathを、
大文字小文字を区別せず部分一致で検索します。空白で区切った複数語はAND条件です。
正規表現とワイルドカードは解釈しません。検索は現在のAttribute Filterの結果へ追加で適用し、
属性の表示順は変更しません。

設定メニューの「検索欄の表示」では、次の3項目を排他的に選択します。

| 表示方針 | 動作 |
| --- | --- |
| 非表示 | Attribute Filterに関係なく検索欄を表示しない |
| 「全て」の場合のみ表示 | Attribute Filterが「全て」の場合だけ表示する。初期値 |
| 常に表示 | 5種類すべてのAttribute Filterで表示する |

検索条件は検索欄が表示されている間だけ有効です。条件や設定によって検索欄が隠れた場合は、
入力済みの文字列をWindow内に保持したまま検索を停止し、Attribute Filterに該当する全行を表示します。
再表示すると保持した文字列を再適用します。検索文字列はモード・ノード選択・表示更新をまたいで
維持しますが、Windowの終了・reload・Maya再起動後は空から開始します。
表示方針だけを`bd_channel_box/preferences/main`へ保存し、Window再表示・Maya再起動後に
復元します。既存設定に項目がなければ「全て」の場合のみ表示から開始し、`reset_layout()`では削除しません。

検索で隠れた属性は選択から外し、検索を解除しても自動再選択しません。
表示されていない属性が値・状態・選択属性Copy/Pasteの対象へ残ることを防ぎます。
「全属性」Copyと「コピー元と同じ属性」Pasteは、従来どおり画面の表示行や検索に依存しません。
結果が0件の場合は、対応属性やAttribute Filterが0件の場合と区別して案内します。

検索ではMaya属性を再列挙せず、既に構築したQTableViewの行を表示・非表示にします。
既存の行Widget・Binding・callbackを維持し、scene・値・状態・Undo履歴を変更しません。
検索で行を隠す前に未確定の値入力と連続操作を終了します。

上部のラベルは共通列で右揃えにし、ComboBoxと検索欄の左端・幅を揃えます。
ラベル列は文字に必要な幅を使い、パネルを広げた分は入力欄へ配分します。

属性の表示優先順は、両モード・全フィルターで共通です。
存在し、フィルターに一致する属性を次の順で先頭へ配置します。

| 優先位置 | 属性（各行の左から順） |
| --- | --- |
| 1 | visibility |
| 2–4 | translateX, translateY, translateZ |
| 5–7 | rotateX, rotateY, rotateZ |
| 8–10 | scaleX, scaleY, scaleZ |
| 11–13 | jointOrientX, jointOrientY, jointOrientZ |
| 14 | rotateOrder |
| 15–17 | rotateAxisX, rotateAxisY, rotateAxisZ |
| 18–20 | shearXY, shearXZ, shearYZ |
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
この順序は[config.py](../python/bd_tools/bd_channel_box/config.py)の
`ATTRIBUTE_PRIORITY_PATHS`で調整できます。上から優先したい順に文字列を並べ、
必要な属性の追加・削除もこのtupleだけで行います。存在しない属性は飛ばし、
重複したpathは最初の指定を採用します。
未指定属性は`drawOverride`配下、その他の順に並び、それぞれ元の相対順を保ちます。
既定の`drawOverride.overrideEnabled`の指定を残すと、同系統の先頭を維持できます。
並べ替えは行の構築時だけ行い、通常の値変更では再実行しません。

ファイルを編集・保存した後は、次のコードでtoolsを再読込みして開き直します。

```python
import bd_tools
bd_tools.reload_package()

from bd_tools import bd_channel_box
bd_channel_box.show()
```

Pythonから`bd_channel_box.config.ATTRIBUTE_PRIORITY_PATHS`を一時的に差し替える場合は、
画面の「表示を更新」で反映できます。再読込み・Maya再起動後はファイル内の設定へ戻ります。
表示順だけを変更し、sceneの属性順・値・Undo履歴には書き込みません。

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
有効な項目への変更は可能ですが、その属性だけを選んだ「この値に揃える」は無効になります。
複数属性の「この値に揃える」では、その未定義の行を対象から除外します。
選択肢が空なら入力も無効です。ComboBoxで同じ項目を選び直すだけでは書き込まず、
混在した値を表示中の項目へ揃える場合は属性名の「この値に揃える」を使います。

値が異なる場合、基準の値を表示したまま属性名の左へ小さな `•` を添えます。
印の意味と対象の詳細はtooltipで確認できます。
属性名を右クリックすると「この値に揃える」「表示を更新」と表示・ロックの操作を選べます。
「この値に揃える」は選択した属性のいずれかが混在し、その基準属性が編集可能な場合に有効です。
各属性の基準ノードの未丸め実値を、同じ属性の他の編集可能な対象へ適用します。
メニューを開くだけでは変更しません。複数属性を選んだ場合の対象は次節を参照してください。
画面の余白からは「表示を更新」を選べます。値・step欄はQt標準の編集メニューを使用します。
すべての対象が同値の入力はUndo履歴を増やしません。

たとえばAが1、Bが2なら、選択時には1を表示したままBの2を維持します。
表示中の1へ揃えるだけなら、属性名のメニューから「この値に揃える」を実行します。
表示精度によって丸められた文字列ではなく、基準ノードの実値を適用します。

## 属性の複数選択と一括操作

Mayaのノード選択とは別に、一覧内で複数の属性行を選択できます。
選択した属性名だけを強調表示します。属性を選ぶだけでは値・状態・Undoを変更しません。
複数ノードも選択している場合は、選択した各属性について、その行の対応ノードへ操作します。

- 属性名のクリックで1行を選び、Ctrlクリックで追加・解除、Shiftクリックで連続範囲を選びます。
  Ctrl+Shiftでは範囲を現在の選択へ追加します。
- 属性名からのドラッグ、または数値欄からの縦ドラッグでも範囲を選べます。
  数値欄内の横ドラッグは文字選択として扱います。
- 選択済みの属性を右クリックした場合は複数選択を維持します。
  未選択の属性を右クリックした場合は、その属性だけを選んでメニューを開きます。
- 同じノード群の表示更新やUndo／Redoでは、正式属性pathと型区分が一致する残存行の選択を保ちます。
  モード・フィルターを切り替えた場合も、表示に残る行だけを引き継ぎます。
  対象ノードまたは基準になる選択順が変わった場合は属性選択を解除します。
  属性選択はWindow内だけで保持し、scene・設定ファイルへ保存しません。

### 数値の直接入力

複数の属性を選び、選択中の数値欄へ文字を入力するか、キーボードで数値を貼り付けると、
一括入力用の文字欄を開きます。入力は編集可能な数値欄から開始します。
一覧にフォーカスがあり、操作中の行が編集可能な数値属性の場合も入力できます。
Enter・フォーカス移動・一覧のスクロールで確定し、Escapeで取り消します。
同じ表示数値を入力し直した場合も明示的な入力として扱い、各対象へその値を適用します。
文字入力を伴わないEnter・フォーカス移動では値を揃えません。

入力開始時の選択属性を操作対象として保持します。未確定のまま選択ノード・scene・属性構成が変わった
場合や、表示更新、Windowの非表示・終了・reloadでは入力を取り消します。
それらより先にフォーカス移動が起きた場合は、移動時点で切替前の対象へ確定します。
モード・フィルターComboBoxへの移動は通常のフォーカス移動として、切替前の対象へ確定します。

数値は各行の現在の表示単位で解釈します。例えば距離・角度・単位なしの属性へ`5`を入力すると、
それぞれ現在の距離単位の5、現在の角度単位の5、単位なしの5として変換します。
基準が編集不可の行とbool・enum行は数値入力の対象から除外し、画面に理由を表示します。
各行の基準以外のノードに対する除外条件は、従来の型・範囲・編集可否の規則を維持します。

すべての編集対象の型・値・hard limitを先に検証し、どれかが範囲外なら操作全体を拒否します。
対象ごとのclampは行いません。成功した一括入力は全属性・全ノードを含めて1回のUndoとなり、
途中の書込み失敗は操作前の値へ復旧します。復旧も失敗した場合は両方の理由を報告します。
全対象がすでに入力値と一致していればUndo履歴を増やしません。

値欄の上下操作では、操作した行のStepから表示単位の増減量を求め、選択した各数値属性の
現在値へ同じ増減量を加えます。各行・各ノードの値の差は維持します。どれかがhard limitを
超える場合は全体を変更しません。

Step欄の直接入力と上下操作では、選択中でStep欄を持つ属性へ同じ表示stepを反映します。
距離・角度・通常数値が混在していても、各行の現在の表示単位で同じ数値を使用します。
各行のmultiplicative／additive方式は変更しません。Slider・bool・enumなどStep欄のない行は
対象外として理由を表示し、未選択行のStep欄を操作した場合はその行だけを変更します。
設定をONにすると、Step欄はフォーカスがなくてもマウスオーバー中のホイールを受け付けます。
この位置では一覧をスクロールせず、Stepを変更します。値欄も同じ操作が可能です。

### Step設定の保存とリセット

変更したStepは`bd_channel_box/preferences/main`の`attribute_steps`へ保存し、Windowの
close・再表示、tools/utilのreload、Maya再起動後へ復元します。`reset_layout()`は
配置だけを初期化し、Step設定を維持します。sceneとMaya Undo履歴には書き込みません。

保存の識別子は正式な相対属性pathと`number`／`distance`／`angle`の組です。
node名、node型、namespace、scene、現在のcm／m・deg／radなどの単位名は含めません。
表示単位を変更しても保存した数値を換算せず、例えば0.1は新しい表示単位でも0.1として使います。
radiusは0.1、angleは15、その他は1を初期値とし、初期値と同じ設定は保存しません。
Step欄自身のmultiplicative／additive方式と増減幅は保存せず、行構築時の設定を使用します。

値編集行または画面余白の右クリックメニューにある「Step設定」は、次の順で表示します。

1. `初期値に戻す: 全ての属性`
2. `初期値に戻す: 選択属性`

全属性は現在表示していない属性を含む保存済みStepを全て削除し、表示行を各行の初期値へ戻します。
選択属性は現在選択中でStep欄を持ち、保存値がある行だけを戻します。未選択行を右クリックした場合は、
従来の右クリック選択規則に従ってその行を選択してから判定します。画面余白では選択を変更しません。
対象となる保存値がない操作は無効になり、成功通知と確認dialogは表示しません。

### ホイール編集の設定

画面上部の「設定」メニューには、チェック可能な「未フォーカス時のホイール編集」があります。
初期値はOFFです。ONでは数値の値欄・Step欄・enum欄にマウスを重ねるだけでホイール編集できます。
OFFでは各欄をクリック・Tabなどでフォーカスを得た場合だけ値を変更し、未フォーカス時の
ホイールを属性一覧のスクロールへ渡します。通常の`[値][Step]`行、Slider付き行の値欄、enum欄は、
ホイール入力だけで自動的にフォーカスを取得しません。ON時の従来動作は維持します。
Slider本体とboolはこの設定の対象外です。Slider本体はフォーカスのないホイールを常に一覧へ渡します。

変更は表示中の全値入力行へ即時反映し、選択・モード・フィルター変更による行の再構築後も
維持します。設定は`bd_channel_box/preferences/main`へ保存し、Windowの再表示とMaya再起動後に
復元します。保存済みの選択は初期値より優先します。sceneとUndo履歴には書き込まず、
`reset_layout()`でも削除しません。

値欄のフォーカス制御はutilの共通部品で扱います。反映にはtoolsとutilを更新し、
`bd_tools.reload_package(reload_util=True)`で再読み込みしてください。

Sliderは選択した数値属性を操作位置と同じ表示値へ揃え、1回のドラッグを1回のUndoへまとめます。
boolは選択したbool属性を操作後のON／OFFへ揃えます。enumは操作元と整数値・項目名の定義が
一致する選択enum属性だけを同じ項目へ揃えます。異なる型とenum定義が異なる行は対象外として
理由を表示します。未選択行の部品を操作した場合は、その行だけを対象にします。

### 選択属性のメニュー

属性名の右クリックメニューは、両モードで「ロック」「ロック解除」「Keyable」
「ChannelBox」「Hide」を提供します。選択した全属性を1回のUndoで変更し、
値の入力可否とは別に、表示・ロックそれぞれの操作可否で対象を判定します。
ロック解除でcompound祖先を自動解除しません。enumの項目定義が違うノードも、
同じ正式属性path・型区分であれば状態操作の対象になります。
フィルターによる行の除去は状態操作を終えてから反映します。

値編集モードの「この値に揃える」は、選択した各属性を**その属性の基準ノードの値**へ揃えます。
例えば基準のTranslate Xが1、Translate Yが2なら、各対応ノードのXを1、Yを2へ揃えます。
数値・bool・有効なenumを混ぜて選べます。編集不可の行や未定義enum値は除外し、理由を表示します。
この操作も全対象を事前検証し、書込み失敗時は復旧し、成功時は1回のUndoへまとめます。

### 属性値のOSクリップボードCopy/Paste

メニューバーの「編集」と、値編集モードの属性名メニューには、同じ構成の操作があります。

- `コピー > 全属性`: 現在の基準nodeで対応している全属性をコピーします。
- `コピー > 選択属性`: 現在選択している属性だけをコピーします。
- `ペースト > コピー元と同じ属性 > 全て`: コピー情報に含まれる全正式pathへ貼り付けます。
- `ペースト > コピー元と同じ属性 > keyable + channelbox`: 貼り付け時の基準nodeで
  KeyableまたはChannelBoxのコピー項目へ絞ります。
- `ペースト > コピー元と同じ属性 > keyable／channelbox／hide`: 貼り付け時の基準nodeで
  各表示状態のコピー項目へ絞ります。
- `ペースト > 選択属性`: コピー値が複数なら、現在選択した属性と同じ正式pathだけを
  貼り付けます。コピー値が一つなら、その値を現在選択した互換属性すべてへ貼り付けます。

Copyは現在の基準ノードからbool・number・distance・angle・enum属性を取得します。
「全属性」は行選択や現在のAttribute Filterに依存せず、「選択属性」は表示中の行選択だけを
対象にします。値は表示文字列へ丸めず、distanceはcm、angleはdegree、通常数値は単位なしの
公開単位で保存します。enumの実整数と項目定義も型付きで保存します。
CopyはsceneとUndo履歴を変更しません。

「コピー元と同じ属性」の`全て`は、OSクリップボード内の全属性を現在選択中の1個または
複数nodeの同じ正式pathへ適用します。ほかの四項目は、現在の先頭選択nodeを基準に
Paste時点の表示状態から対象pathを一度決め、その同じpathを全選択nodeへ適用します。
後続nodeごとの表示状態では再判定しないため、一操作の一部nodeだけが条件外にはなりません。

`keyable + channelbox`はKeyableまたはChannelBox、`keyable`はKeyable、`channelbox`は
非KeyableかつChannelBox、`hide`はKeyableでもChannelBoxでもない属性です。画面上部の
Attribute Filterとは独立して明示的に選び、選択した条件は保存しません。条件外のコピー項目数は
内部のPaste結果へ保持し、画面には表示しません。対象pathが0件ならsceneとUndo履歴を変更しません。

複数項目をコピーした後の「選択属性」は、OSクリップボード内の値から現在選択した属性と
同じ正式pathだけを取り出します。`translate.translateX`のような正式な相対pathと
型・単位区分が一致する属性だけを対象とし、行順やクリック順による対応付けは行いません。
選択pathがクリップボードにない場合は、コピー値なしとして内部結果の対象外にします。

一項目だけをコピーした後の「選択属性」は、コピーした一値を現在選択している属性pathと
全選択nodeへ展開します。Paste時にコピー元pathを右クリックする必要はありません。
number・distance・angle・boolは同じ型区分同士に限定し、enumは整数値と項目名の定義が
一致する属性だけを対象にします。コピー元pathと貼り付け先pathの一致は要求しません。

enumは整数値と項目名の対応が一致する場合だけ対象にし、表示順だけの違いは許容します。
属性なし、型・単位違い、enum定義違い、lock・入力接続などの編集不可属性は対象外として
内部結果へ理由を保持します。残った全対象の型・hard limitを先に検証し、一回のUndoで変更します。
途中失敗は操作前の値へ復旧し、全対象が同値ならUndo項目を作りません。

Pasteの成功・部分適用・対象0件では画面へ操作通知を表示せず、以前の通知も消去します。
未対応versionや壊れたJSONなど、Paste処理を開始できない場合だけ簡潔なエラーを表示します。

custom MIMEとmarker付きtextへversion付きJSONを保存するため、別のMaya processからも
貼り付けられます。未対応version、壊れたJSON、過大data、未知の型は値を書き込む前に拒否します。
Copy元は一つの基準nodeに限定し、全対応属性または選択属性をコピーします。
複数source nodeを行順・選択順で対応させるPasteは提供しません。

「表示を更新」は一覧全体を再取得します。余白のメニューは従来どおり表示更新だけを提供し、
値・step欄の右クリックはQt標準の編集メニューを使用します。
Maya標準Channel Boxの選択やメニューには連動しません。
キー編集、接続解除、Freeze、Graph Editor連携はこの段階の対象外です。

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
複数選択への入力時は対象となった各属性のキャッシュを同時に更新します。その後は各行を
個別に変更できます。Windowの終了・reload後は既定値から開始し、設定ファイルやsceneへ
stepを保存しません。
モードやフィルターの切替でもstep設定を維持します。

表示範囲は基準属性を使い、他対象の制限は書込み前に検証します。
入力がどれかの編集可能な対象の範囲外なら、その入力全体を拒否して理由を表示します。
対象ごとに値を黙ってclampすることはありません。
属性の表示名・範囲設定を変更した後は、右クリックの「表示を更新」でView構成を読み直せます。

自身またはcompound祖先にlock・入力接続がある属性は編集不可です。
アニメーション接続も表示専用で、キーの作成・変更や接続解除は行いません。
基準が編集不可なら行全体の値入力を止めます。基準以外の編集不可属性は除外し、
残る編集可能な対応属性へ適用します。tooltipの編集対象数はその適用対象数です。

一回の数値確定・上下操作・bool変更・enum項目変更は、選択した全属性・全ノードを含めて
一回のUndoで戻ります。Sliderドラッグも全対象を含めて一回のUndoへまとめます。
Undoでは混在していた各属性・各ノードの元値が戻ります。
途中の書込み失敗は同じ操作内で復旧し、復旧にも失敗した場合は両方の理由を報告します。

## 表示・ロック

属性名の右側を、`key / ch / hide`のラジオボタンと`lock`のCheckBoxへ切り替えます。
表示状態の3つだけを排他的に選択し、ロックは独立して操作できます。
ラジオボタンから左ドラッグすると、通過したボタンの状態へ順に変更できます。
例えば`ch`列を縦になぞると、その範囲の属性をChannelBoxへ揃えられます。
選択済みのボタンからも開始でき、通常クリック・キーボード操作は維持します。
小さな手ぶれは通常クリックとして扱い、速い移動でも経路上の途中の行を対象にします。
`lock`から左ドラッグすると、押下時がOFF・混在ならロック、ONなら解除へ通過行を揃えます。
既に目的の状態なら変更せず、同じ行を往復しても再反転しません。
一部の対象が操作不可で適用後も混在表示が残る場合も、その行への再要求は一操作一回です。
通常クリック・Spaceキーでの操作も維持します。
ラジオボタンから始めた操作はラジオボタンだけ、`lock`から始めた操作は`lock`だけを対象にします。
両操作とも表示範囲内の有効なボタンだけを対象とし、画面外の行は変更しません。
なぞり中のホイール移動と画面端の自動スクロールには対応しません。

なぞった変更はその場で反映し、一回のUndo／Redoにまとめます。無変更なら履歴は増えません。
フィルターによる行の除外は操作終了まで保留します。マウス解放、Escape、非表示、
フォーカス喪失、モード・選択・scene・属性構成の変更、終了・reloadで入力を止めます。
中断ではそれまでの変更を保持し、戻す場合はUndoを使います。
書込み失敗時は失敗した行を既存Bindingが復旧し、なぞり全体を終了します。
それ以前に変更した行は保持し、一回のUndoで元へ戻せます。

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
表示同期だけでは揃えません。選択中の行の`key / ch / hide / lock`を操作すると、
操作後の表示状態またはlockを、選択属性すべてと各選択nodeへ適用します。
選択外の行の操作部品は、現在の選択集合を変更せず、その行だけを対象にします。
ラジオボタンはクリック・Space・矢印キーで選択できます。同じ状態の再選択はUndo履歴を増やしません。
ロック混在のクリック／Spaceはロックする操作です。次の操作で解除します。
属性名と入力欄のtooltipで、各操作の対象数や操作できない理由を確認できます。

左ドラッグがなぞり操作の開始距離を超えた場合は、属性選択へは展開しません。
表示状態は通過した同じ列のradio、lockは通過したCheckBoxだけを開始時の
操作に揃え、既に選択されている離れた行は変更しません。単発クリックとなぞりは、
どちらも操作単位を1回のMaya標準Undoへまとめます。

ロック中や入力接続済みの属性でも、表示状態の編集や自身のロック解除を操作できます。
値編集の可否判定は流用せず、状態ごとに操作可否を判定します。
compound祖先がロックされている場合、子の操作で祖先まで自動解除しません。
自身のロックと親による制限は区別して表示します。
属性名の右クリックから選択属性の表示・ロック操作と「表示を更新」を選べます。
余白のメニューからも「表示を更新」を選べます。

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

`bd_channel_box/ui.py` は公開Windowと配置・reload、`widget.py` は属性行・メニュー・検索条件、
`table.py` は属性選択・数値直接入力・検索行の表示切替、`controller.py` は基準node・対応属性・
選択追従と操作対象の組み立てを所有します。
一覧は`QTableView`の1属性1セルで構成し、delegateのpersistent editorとして既存の行Widgetを
常時表示します。既存の数値・Step・Slider・bool・enum・状態ViewとBindingを維持し、
値をtable modelへ二重に保存しません。選択中の複数属性への文字入力だけ一時的な文字欄で受け付け、
既存Viewからの上下・Slider・bool・enum入力はutilの任意入力handlerを通してcontrollerへ渡します。
Step入力はWindow内で選択を解釈し、各行の既存Viewと`FloatStepProfile`へ反映します。
Windowはutilの `MayaDockableWindow` を継承し、`dock_closed` と
`dock_about_to_dispose` で入力controllerを終了します。workspaceControl作成・削除・
Maya再起動時の接続・画面外補正・配置resetはutilへ委譲します。
stepの初期値選択と保存対象の判定はtools、属性path・単位種別ごとのprofileと状態保存、
値とstepの連動はutilが所有します。
値の単位変換・型付き属性列挙・一括書込み・混在状態・Undoはutilを使用します。
複数行の値操作はutilの`apply_plugs_values()`へ型付きの絶対値または相対値の編集要求を渡し、
全件の事前検証・復旧・1回のUndoを委譲します。Sliderは`MayaEditSession`も渡して連続入力をまとめます。
属性の表示・ロック状態の読取り、一括操作、Undo、操作可否と監視もutilが所有します。
値編集と状態編集の対象選別、モード・フィルター切替とWindow内の選択保持、
共通入力幅と各入力欄はtoolsが所有します。
状態変更による絞り込みはQtの次のイベントで行い、書込み中のBindingを破棄しません。
別ツールはこのcontrollerへ暗黙に依存せず、必要な汎用APIをutilから利用します。

### UI部品を参照するコードの移行

`widget.table_view`を属性一覧の入口にします。既存の`widget.scroll_area`も同じ一覧を参照しますが、
型は`QScrollArea`から`ChannelTableView`へ変わりました。
内容Widgetを取得していた`widget.scroll_area.widget()`は`widget.table_view.viewport()`へ移行します。
`verticalScrollBar()`と`ensureWidgetVisible()`による既存のスクロール操作は引き続き使えます。
Maya本体がviewportを交換する場合があるため、内容の親Widgetは保持せず、使用時に`viewport()`で取得します。
`row_widgets`、各行の`editor`、公開`show()`とWindowの復元入口は維持します。
`ChannelRow` / `ChannelStateRow`を直接構築するコードは、対応ノード名のtupleを
新しい`target_names`引数へ渡してください。scene・保存設定の移行は不要です。

### 見た目の調整箇所

以下の定数は`bd_tools/bd_channel_box`配下で管理します。サイズは全Maya versionで共通です。

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

定数を変更した後はtoolsをreloadして`bd_channel_box`をimportし直し、`show()`で作り直します。
保存済みworkspaceの幅が優先される場合は、パネルを手動で縮めるか`reset_layout()`を実行します。
幅・配置を変更した際は`tests/maya/test_bd_channel_box.py`の配置検証も新しい仕様に合わせ、
Sliderあり／なし、最小幅／拡大時、ドック／floatingで表示を確認してください。

### 拡張時に維持する仕様

- 選択・表示更新・外部からの値変更は読取りと表示同期だけにし、他ノードへ値を転送しない。
- 明示的な入力・揃える操作だけを一括編集し、Undoで各ノードの元値を復元する。
- ノード選択と属性選択を分け、属性選択・未編集のフォーカス移動では値を揃えない。
- 複数行の値操作は全対象を先に検証し、途中の失敗で一部の行だけ変更を残さない。
- Stepの変更はViewの操作設定として扱い、sceneとUndoへ書き込まない。
- モード・フィルター切替では値・状態・Undoを変更せず、入力幅とstep設定を維持する。
- 表示状態とロックを独立して変更し、非表示属性も状態モードから復帰できるようにする。
- なぞり操作は1回のUndoへまとめ、フィルターによる行の除去は操作終了後に反映する。
  選択・scene・属性構成が変わる場合は、なぞりを終了して古い対象を解放する。
- 編集不可属性や型・範囲の不一致を尊重し、除外理由や拒否理由を表示する。
- 選択切替・close・reloadでは古い入力、連続編集、callback、メニューを確実に終了する。
- 汎用の型・Binding・View・保存基盤はutil、表示対象と各行の組み合わせはtoolsへ置く。

### 性能改善を続ける場合

値変更の同期と選択変更による行の再構築は、別の処理として計測します。
値変更では無関係な行の再読取りを避け、選択変更では古い入力とcallbackの解放を維持します。
現状は行・Bindingの再利用や、選択をまたぐ属性情報のキャッシュ、監視の共有化を行っていません。
これらは追加の負荷計測で必要性が確認された場合に、無効化条件とlifecycleを含めて検討します。

2026-09-19の選択切替改善は、util側の次の2実装で行いました。

- `bd_util/maya/node/_attribute_lookup.py`: 一意な実名は直接取得し、親pathも照合する。
  aliasや誤った親pathを受理せず、非一意名は従来の全件検索で曖昧さを判定する。
- `bd_util/ui/binding/float/view/step_spin_box.py`: 正しい初期値を先に設定してから下限を適用し、
  生成途中の不要な極小値表記を避ける。精度・許容範囲・加算／乗算の操作仕様は維持する。

utilの変更では同リポジトリの検証方針に従い、toolsとの組合せも確認します。
比較条件と記録方法は[Testing](testing.md#性能比較を記録するとき)を参照してください。

## 検証

`tests/maya/test_bd_channel_box.py` は、選択時の無書込み、外部変更の非伝播、
View選択、混在編集、除外対象、範囲違い、Undo、構成変更を検証します。
「keyable」「全て」のどちらでも、UI・外部入力によって無関係な行の再読取りや
全行の作り直しが発生しないことを、時間の閾値ではなく更新対象で検証します。
`tests/maya/test_bd_channel_box_enum.py`は、enumの飛び番・定義不一致の除外、使用中の
定義変更、未定義値、ロック・接続、混在、Undo／Redo、選択肢の終了を検証します。
`tests/maya/test_bd_channel_box_states.py`は、既存Hide属性の列挙と復帰、表示・ロックの
独立操作、混在、Undo／Redo、モード切替の無書込みとstep保持、必要時だけのスクロールを検証します。
両モードの5種類のフィルター、モードごとの選択保持、状態変更後の絞り込みとUndo／Redo、
非表示属性の値入力・操作制限、外部変更、入力途中や連続編集中の切替も検証します。
`tests/maya/test_bd_channel_box_order.py`は、優先順設定、両モード・全フィルターでの表示順、
正式pathによる照合と未指定属性の相対順を検証します。
`tests/maya/test_bd_channel_box_sweep.py`は、表示状態・lockのなぞり操作と1回Undo、
行の除去の保留、操作中断・失敗時の終了と編集不可行の扱いを検証します。
`tests/maya/test_bd_channel_box_selection.py`は、複数属性選択、数値直接入力、選択維持・解除、
未編集時の無書込み、入力中断、単位変換、全件の範囲検証、1回Undo、対象外属性の通知、
選択属性のメニュー、共通増減量、Slider・bool・enumの互換属性への一括入力、
同じ表示Stepの一括設定と属性ごとのキャッシュを検証する入口です。
モード切替時に先行するフォーカス移動の有無によらず拒否理由を維持することと、
Maya側がviewportを交換した後に古い親を参照しないことも検証します。
複数行の事前検証・書込み失敗時の復旧はutilの`tests/maya/ui/test_plugs_value_edits.py`でも検証します。
`tests/maya/test_bd_channel_box_dock.py` は、batchで扱えないworkspaceの画面境界を置換し、
公開show / restore / close / reset、Window重複防止、監視解除とreloadを検証します。
公開入口の型は `tests/typecheck/bd_channel_box_contract.py` で固定します。
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
[Maya本体検証の手順](testing.md#bdchannelboxのmaya本体検証)を参照してください。

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
`%TEMP%/bd-channel-box-maya2025-xnb085bt`へ保存しました。

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
`%TEMP%/bd-channel-box-maya2025-ux83mnxs`へ保存しました。

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
`%TEMP%/bd-channel-box-maya2025-euh2_qt8`へ保存しました。
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
`%TEMP%/bd-channel-box-maya2025-p3febnx8`へ保存しました。
本体終了時は既知の終了待ちタイムアウトが再現し、runnerの終了codeは1です。
37工程の操作成功とは区別し、検証専用processの停止を確認しました。
Maya 2026 / 2027本体の画面操作は今回実施していません。

同日の追加調整で、drawOverride内の先頭をoverrideEnabledへ変更しました。
残りの相対順は維持し、関連Maya 2025 test 10件、Pyright、Black checkが成功しました。
Maya 2025本体も37工程成功し、両モードの保存画像でoverrideEnabledが先頭になることを確認しました。
追加調整の結果・画像は`%TEMP%/bd-channel-box-maya2025-1nuu7kke`へ保存しました。
追加調整でも本体終了待ちの既知タイムアウトが再現し、runnerの終了codeは1です。

### 上部ComboBoxの説明ラベル（2026-09-18）

ModeとAttribute Filterのラベルを右揃えの共通列に追加しました。
関連Maya 2025 test 26件、Pyright、Black checkが成功し、280 / 360 / 520 pxで
ラベルと選択欄の整列・幅、モード・フィルター操作を確認しました。
Maya 2025本体も37工程成功し、保存画像で両モードの文字と配置を確認しました。
本体検証の結果・画像は`%TEMP%/bd-channel-box-maya2025-za269o96`へ保存しました。
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

本体検証の結果・画像は`%TEMP%/bd-channel-box-maya2025-wv4li987`へ保存しました。
終了待ちでは既知のタイムアウトが再現し、runnerの終了codeは1です。
操作37工程の成功とは区別し、検証専用processの停止を確認しました。
Maya 2026 / 2027本体の画面操作は今回実施していません。

### 表示状態のなぞり選択（2026-09-18）

`key / ch / hide`の左ドラッグ選択を追加しました。toolsとutilの両方を更新し、
`bd_tools.reload_package(reload_util=True)`で再読込みしてから開き直してください。
なぞり操作と共有Undoはutil、対象登録とフィルターの再構築保留はtoolsが所有します。

- `check.cmd -IncludeMaya`: Black・Pyright・unit 8件・Maya 2025 runtime 107件が成功。
- Maya 2026 / 2027のruntime test: 各107件成功。
- toolsの追加9件で、高速移動の途中行、複数ノード、一回Undo／Redo、フィルター保留、
  Escape・非表示・モード・フィルター・更新・選択・破棄・属性削除での終了を確認。
- utilの`verify.cmd`が成功。Black・3版Pyright、Maya 2025全体4210 passed / 697 skipped、
  Maya 2025 / 2026 / 2027の専用Qt検証各797件とMaya UI検証各343件が成功。
  全体実行でskipするWidget検証も、専用UIプロセスではskipなしで確認。
- utilのQt検証で、単発クリック・Space、選択済みからの開始、無効／未登録の除外、
  中断後の遅いrelease、viewport差し替えと画面外除外を確認。
  Maya側で無変更、Undo無効、複数Binding、書込み中の終了要求とowner破棄を確認。
- Maya 2025本体の38工程が成功。なぞり中と終了後の保存画像を確認し、
  三軸・両選択ノードへの反映、一回Undo／Redo、reload後の再表示も成功。

Maya本体でviewportの保持参照が無効になる事象を検出し、操作補助のownerを
ScrollArea本体にして現在のviewportを判定時に取得する形へ修正しました。
本体検証の結果・画像は`%TEMP%/bd-channel-box-maya2025-yefskvp6`へ保存しました。
38工程の操作結果は成功ですが、本体終了待ちの既知タイムアウトによりrunnerの終了codeは1です。
検証専用processの停止を確認済みです。Maya 2026 / 2027本体の画面操作は今回実施していません。

### lockのなぞり操作（2026-09-18）

`lock`にも左ドラッグ操作を追加しました。toolsとutilの両方を更新し、
`bd_tools.reload_package(reload_util=True)`で再読込みしてください。
utilの`CheckBoxSweep`と`RadioButtonSweep`は内部のマウス追跡を共有し、
toolsはlockの明示入力と既存の共有Undoセッションを接続します。

- `check.cmd -IncludeMaya`: Black・Pyright・unit 8件・Maya 2025 runtime 119件が成功。
- Maya 2026 / 2027のruntime test: 各119件成功。
- toolsの追加12件で、ON・OFF・混在からの開始、複数ノード、往復、一回Undo／Redo、
  中断、途中の書込み失敗と現行行の復旧、親lockによる操作不可行の除外を確認。
- utilの`verify.cmd`が成功。Black・3版Pyright、Maya 2025全体4216 passed / 711 skipped、
  Maya 2025 / 2026 / 2027の専用Qt検証各811件とMaya UI検証各349件が成功。
  全体実行でskipするWidget検証も専用UIプロセスではskipなしで確認。
- utilのQt検証で、通常クリック・Space、ボタン種類の分離、非表示／無効の除外、
  混在表示が残る入力先への再要求防止、中断後の遅いreleaseを確認。
  Maya側で同値の無書込み、共有Undoと親属性・ノードlockの既存制限を確認。
- Maya 2025本体の39工程が成功。lock列の往復によるロック・解除、一回Undo／Redo、
  既存ラジオ操作とreload後の再表示を確認し、ロック前後の保存画像も確認。

結果・画像・util検証ログは`%TEMP%/bd-channel-box-maya2025-4eg23ktj`へ保存しました。
操作39工程は成功ですが、本体終了待ちの既知タイムアウトによりrunnerの終了codeは1です。
検証専用processの停止を確認済みです。Maya 2026 / 2027本体の画面操作は今回実施していません。

### 優先順の調整と設定の分離（2026-09-18）

先頭10属性をvisibility・translate X/Y/Z・rotate X/Y/Z・scale X/Y/Zに変更し、
残りの相対順を維持しました。優先順を`bd_channel_box/config.py`の
`ATTRIBUTE_PRIORITY_PATHS`へ分離し、行構築時に現在の設定を参照します。

- `check.cmd -IncludeMaya`: Black・Pyright・unit 8件・Maya 2025 runtime 121件が成功。
- 既存の順序検証で、transform・joint、両モード・全5フィルター、
  drawOverride内のoverrideEnabled先頭、その他の相対順とscene・Undoへの無書込みを確認。
- 追加2件で、設定変更後の表示更新、カスタム属性の優先表示、未存在・重複指定の処理、
  優先指定した属性以外の相対順が維持されることを両モードで確認。
- Maya 2025本体の39工程が成功し、runnerも終了code 0で完了。
  新しい先頭10属性と後続の順番を両モードの保存画像で確認。

本体検証の結果・画像は`%TEMP%/bd-channel-box-maya2025-5lf9abq1`へ保存しました。
今回はtoolsだけの変更で、Maya 2026 / 2027のruntime・本体確認は実施していません。

### bdChannelBoxへの名称統一（2026-09-18）

ツール名をbdChannelBox、公開packageを`bd_tools.bd_channel_box`へ統一しました。
Windowタイトル、workspaceControl ID、復元入口、設定path、テスト、検証runner、
ドキュメントも同じ名称へ揃えています。

- `check.cmd -IncludeMaya`: Black・Pyright・unit 8件・Maya 2025 runtime 121件が成功。
- Maya 2026 / 2027のruntime test: 各121件成功。
- Maya 2025本体の初回40工程が成功。WindowとworkspaceControlのタイトル、
  ドッキング、入力、reload、floating配置の保存を確認。
- Maya 2025の別processで再起動し、`show()`前のworkspaceControl自動復元、
  floating配置、単一Windowの再利用、複数ノード編集を確認。

本体検証の結果・画像は`%TEMP%/bd-channel-box-maya2025-0178bgaj`へ保存しました。
再起動検証の4工程は成功ですが、本体終了待ちの既知タイムアウトによりrunnerの
終了codeは1です。操作結果と画像の保存、検証専用processの停止を確認済みです。

### 選択切替の高速化（2026-09-19）

utilの属性検索とstep入力欄の初期化を改善しました。一意な属性は長名・短名と
親pathを確認して直接取得し、非一意な属性は既存の全件検索で判定します。
step欄は初期値を設定してから下限を適用し、生成途中の不要な極小値表示を省きます。
UIの再利用や監視の共有化は追加せず、選択変更時の入力・callback解放を維持します。
toolsとutilを更新し、`bd_tools.reload_package(reload_util=True)`で再読込みしてください。

Maya 2025本体の同一processで、変更前の2実装と変更後を交互に計測しました。
各30個のfloat属性を追加したtransformを使用し、2回のwarm-up後の7回の中央値です。
入力行の破棄・再構築・Qt更新を含め、前の試行の循環参照回収は測定前に完了しています。
1ノードでは先頭・末尾ノードを切り替え、10ノードでは選択順序を反転しています。

| 条件 | 変更前 | 変更後 |
| --- | ---: | ---: |
| 1ノード・値編集40行 | 113.080 ms | 91.806 ms |
| 1ノード・値編集173行 | 375.907 ms | 310.413 ms |
| 10ノード・値編集173行 | 1024.795 ms | 584.613 ms |
| 1ノード・表示・ロック173行 | 346.262 ms | 311.831 ms |

計測値はsceneと実行環境によって変わり、性能保証値ではありません。
比較用runnerと結果は検証環境の`%TEMP%/bd_selection_native_compare.py`、
`%TEMP%/bd-channel-box-maya2025-8evw63y2`へ保存しました。

- utilの`verify.cmd`: Black、3版Pyright、Maya 2025全体4229 passed / 723 skippedが成功。
  3版の専用Qt検証各823件、Maya UI検証各349件も成功し、全体実行でskipするUIも確認。
- utilの追加テストでalias・誤った親pathの拒否13件、step初期値の境界12件を確認。
  属性解決の関連24件はMaya 2026 / 2027でも成功。
- toolsの`check.cmd -IncludeMaya`: Black、Pyright、unit 8件、Maya 2025 runtime 121件が成功。
  Maya 2026 / 2027のruntime testも各121件成功。
- Maya 2025本体の比較検証39工程が成功し、値・enum・表示・ロック・なぞり・Undo／Redo、
  close／reloadと保存画像を確認。
- 正式runnerも39工程が成功し、追加した選択切替の計測結果と行数を確認。
  結果・画像は`%TEMP%/bd-channel-box-maya2025-9qim_h78`へ保存。

比較検証・正式runnerとも操作結果は成功ですが、Maya本体の終了待ちがタイムアウトし、
runnerの終了codeは1です。検証専用processの停止を確認済みです。
Maya 2026 / 2027本体の画面操作は今回実施していません。

### 複数属性の選択・数値入力・基本メニュー（2026-09-19）

QTableViewと既存行Viewを組み合わせ、複数属性選択、数値の直接入力、
各属性の基準値へ揃える操作、ロック／解除・表示状態の選択メニューを追加しました。
初回実装と自動・本体検証は完了しています。利用者による操作確認はまだ行っていません。
上下・Step・Slider・bool・enumの通常入力は、従来どおり1行の対応ノードだけを対象にします。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright | 通過。Pyrightのerrorは0件 |
| toolsのunit test | 8件成功 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各144件成功。従来121件から23件追加 |
| utilの`verify.cmd` | 終了code 0。対応3 versionの検証を含めて成功 |
| Maya 2025本体の操作 | 40工程成功。複数属性の選択・数値入力・メニュー・1回Undoと従来操作を含む |
| Maya 2025本体の終了 | 2回連続で正常終了。runnerの終了codeは0 |
| 本体の保存画像 | 複数選択・入力中・適用後・右クリックメニューを確認。文字切れなし |

実Mayaのviewport交換によって、保持していた親Widgetが無効になる不具合を修正しました。
属性行の構築時に現在の`viewport()`を取得し、交換後の再構築を回帰テストと本体で確認しています。
入力拒否の直後にモードを切り替えても理由表示を消さないことを、
直接の切替と先行するFocusOutの2ケースで確認しました。

最終結果と画像は`%TEMP%/bd-channel-box-maya2025-q6i850he`へ保存しました。
`result.json`の`success`はTrue、操作履歴は40工程です。
直前の`%TEMP%/bd-channel-box-maya2025-iau99qaw`も同じ製品コードで40工程成功・正常終了しました。
最終runは右クリックメニューを独立したpopupとして画像保存するrunnerの修正を含みます。
過去の終了待ちタイムアウトはこの2回では再現しませんでしたが、原因が解決したとは断定しません。
Maya 2026 / 2027はruntime testによる確認で、本体の画面操作は今回実施していません。

### 一覧の背景色とboolの視認性（2026-09-19）

一覧の余白と属性行にQt paletteのWindow背景を使い、暗い入力欄と区別しました。
数値・Step欄の背景と選択色は維持し、Mayaがviewportを交換した場合も同じ背景を適用します。
Maya 2025本体の画像で、OFFのboolが周囲のグレーから判別できることを確認しました。
チェックボックスの独自描画や固定色の指定は追加していません。

- toolsのBlack・Pyright・unit 8件が成功。
- Maya 2025 / 2026 / 2027のruntime testは各144件成功。
- Maya 2025本体の40工程が成功。通常表示、選択色、入力欄、boolのON／OFFを画像で確認。
  結果と画像は`%TEMP%/bd-channel-box-maya2025-09xqi9yg`へ保存。
  操作完了後の終了待ちでは既知の180秒タイムアウトが再発し、runnerは終了code 1。
  検証専用processの停止を確認済み。操作成功と正常終了は区別する。

toolsだけの変更です。反映には`bd_tools.reload_package()`で再読み込みします。

### 既存Viewによる複数属性入力（2026-09-20）

値欄の上下操作、Slider、bool、enumの通常入力を、選択中の互換属性へ適用するよう拡張しました。
上下操作は操作元Stepによる同じ表示増減量を加え、Slider・bool・enumは操作後の値へ揃えます。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Pyrightのerrorは0件 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各150件成功 |
| utilの`verify.cmd` | 成功。Maya 2025全4,973件、各versionのQt 827件・Maya UI 366件を含む |
| Maya 2025本体の操作 | `result.json`の`success`はTrue。41工程成功 |
| 追加した本体工程 | 上下・Slider・bool・互換enumの複数属性入力と各1回Undoが成功 |
| 本体の保存画像 | 選択enum行と通常の既存Viewを含む画面を確認。文字切れなし |

本体の結果と画像は`%TEMP%/bd-channel-box-maya2025-upgbttmk`へ保存しました。
操作と結果保存は完了しましたが、その後のMaya process終了待ちは既知のタイムアウトとなりました。
Maya 2026 / 2027はruntime testによる確認で、本体の画面操作は実施していません。

toolsとutilの変更です。反映には`bd_tools.reload_package(reload_util=True)`で再読み込みします。

### Step設定の複数属性入力（2026-09-20）

Step欄の直接入力と上下操作を、選択中で同欄を持つ属性へ適用するよう拡張しました。
各行の表示単位で同じ数値を設定し、multiplicative／additive方式を維持します。
Step欄のない行は対象外として通知し、属性値とMaya Undo履歴は変更しません。
対象となった属性ごとのWindow内キャッシュを更新し、再構築後も設定を復元します。
Step欄のマウスオーバー中は、クリック前でもホイールにより同じ経路で変更します。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Pyrightのerrorは0件 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各152件成功 |
| 選択操作のtarget test | Maya 2025で31件成功。Step一括設定、対象外通知、増減方式、キャッシュ、単独変更、未focus時のホイール操作を含む |
| utilのBlack・Pyright・Maya 2025 runtime test | 成功。runtime 4,246件成功、730件skip、各versionのPyright errorは0件 |
| utilの関連Qt test | Maya 2025 / 2026 / 2027で各2件成功。既定値と上書き後のホイール動作を含む |
| utilのUI compatibility test | 既知のclipboard test 1件を除外し、各versionでQt/UI 829件・Maya UI 366件成功 |

既存行Viewと配置寸法は変更していません。Maya本体の画面操作による確認は利用者確認前の段階では
実施していません。toolsとutilの変更で、`bd_tools.reload_package(reload_util=True)`により
再読み込みできます。

### ホイール編集設定メニュー（2026-09-20）

上部へ「設定」メニューを追加し、「未フォーカス時のホイール編集」で数値の値欄とStep欄を
まとめて切り替えられるようにしました。初期値はONです。選択は配置とは別の
`bd_channel_box/preferences/main`へ保存し、Window再表示、Maya再起動、reload後に復元します。
配置リセット、scene、Undo履歴には影響しません。Slider本体、bool、enumは対象外です。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Pyrightのerrorは0件 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各154件成功 |
| utilのBlack・Pyright | 成功。Maya 2025 / 2026 / 2027のPyright errorは0件 |
| utilのUI state test | Maya 2025 / 2026 / 2027で各17件成功。checkable QActionの保存・復元を含む |
| Maya 2025本体の操作 | `result.json`の`success`はTrue。42工程成功、正常終了 |
| 追加した本体工程 | メニュー描画、通常・Slider付き値欄とStep欄のOFF、配置reset・再表示・reload後の復元が成功 |
| 本体の保存画像 | メニューバー、チェック付き設定メニュー、OFF反映後の画面を確認。文字切れなし |

本体の結果と30枚の画像は`%TEMP%/bd-channel-box-maya2025-0n245r0a`へ保存しました。
toolsとutilの変更です。反映には`bd_tools.reload_package(reload_util=True)`を使用します。

### ホイールによる値欄の自動フォーカス取得の修正（2026-09-20）

設定OFFでも通常の値欄とSlider付き値欄が編集される問題を修正しました。
値欄の`WheelFocus`では、Qtが`wheelEvent()`より先にフォーカスを移し、未フォーカス判定を
通り抜けていました。共有部品`FloatSpinBox`をOFF時は`StrongFocus`へ切り替え、
クリック・Tab後の編集と、ON時の従来動作を維持します。

メニュー導入時のテストは`QApplication.sendEvent()`による入力で、この自動フォーカスを
再現していませんでした。Windowsの`WM_MOUSEWHEEL`へ変更したrunnerで、修正前はOFFでも
translateXが両ノードとも0から1へ変わる失敗を確認しました。
修正前の結果は`%TEMP%/bd-channel-box-maya2025-skc4n4ql`へ保存しています。

- Maya 2025本体の43工程が成功し、runnerも終了code 0で正常終了。
  通常・Slider付き値欄でOFF→ON→OFF、未フォーカス時の無書込みとフォーカス保持、
  フォーカス後の編集・Undo、値欄とStep欄から一覧へのスクロール伝達を確認。
- toolsのBlack・Pyright・unit 8件と、Maya 2025 / 2026 / 2027のruntime各154件が成功。
- utilの`verify.cmd`が終了code 0。Black・3版Pyright、Maya 2025全体4,247 passed / 731 skipped、
  3版の専用Qt/UI各832件・Maya UI各366件が成功。全体実行でskipするUIも専用processで確認。

修正後の結果と画像は`%TEMP%/bd-channel-box-maya2025-gcts1_cg`へ保存しました。
Maya 2026 / 2027本体の画面操作は今回は実施していません。
utilも変更しているため、反映には`bd_tools.reload_package(reload_util=True)`を使用します。

### enumホイール編集と初期値OFF（2026-09-20）

「未フォーカス時のホイール編集」をenum欄にも適用し、未フォーカスのenum上でも一覧を
安全にスクロールできるようにしました。設定の初期値はOFFです。保存済みの利用者設定が
ある場合はその選択を維持し、設定変更は既存行と再構築後の行へ即時反映します。

共有部品の`EnumComboBox`に同じフォーカス制御を追加しました。独自APIはPEP 8に合わせて
`wheel_requires_focus()`と`set_wheel_requires_focus()`へ統一し、数値・Step欄にあった
camelCase名も移行しました。v1.0.0未満のため旧名のaliasは追加していません。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Pyrightのerrorは0件 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各154件成功 |
| utilの`verify.cmd` | 終了code 0。Maya 2025全体4,247件成功・733件skip、各versionのQt 834件・Maya UI 366件が成功 |
| Maya 2025本体の操作 | `result.json`の`success`はTrue。43工程成功し、検証用processも終了 |
| 追加した本体確認 | メニュー初期OFF、数値・Step・Slider付き数値・enumのOFF→focus→ON→OFF、一覧スクロールが成功 |

Maya本体ではWindowsの`WM_MOUSEWHEEL`を送り、Qtの自動フォーカス取得を含む実入力経路を
確認しました。結果と30枚の画像は`%TEMP%/bd-channel-box-maya2025-mdtb6hhi`へ保存しました。
Maya 2026 / 2027本体の画面操作は今回は実施していません。

toolsとutilの変更です。反映には`bd_tools.reload_package(reload_util=True)`を使用します。

### 属性値のOSクリップボードCopy/Paste（2026-09-20）

基準nodeの選択属性値をOSクリップボードへコピーし、現在選択中の1個または複数nodeの
同一正式pathへ貼り付ける初回範囲を実装しました。行順による対応付けは追加していません。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Pyrightのerrorは0件 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各157件成功 |
| utilの`verify.cmd` | 終了code 0。Maya 2025全体4,256件成功・739件skip、各versionのQt 843件・Maya UI 372件が成功 |
| Maya 2025本体の初回process | `result.json`の`success`はTrue。Copy/Pasteを含む45工程と31枚の画像を確認 |
| Maya 2025本体の別process | `result-restart.json`の`success`はTrue。前process終了後の属性値読取りと元clipboardの復元を確認 |

utilではcustom MIMEとmarker付きtextのJSON、型付きsnapshot、公開単位、enum定義、
同path適用を検証しました。欠落・型違い・enum定義違い・lockを内部結果の対象外とし、
hard limit違反では全候補を変更しないこと、適用成功時は一回のUndoになることを確認しています。

Maya本体の結果と画像は
`%TEMP%/bd-channel-box-maya2025-vch4wi8d`へ保存しました。初回と再起動後の両processが
終了code 0で正常終了しています。検証前のOSクリップボードは形式ごとのbyte列を退避し、
別processでの読取り後に復元しました。Maya 2026 / 2027本体の画面操作は実施していません。

toolsとutilの変更です。反映には`bd_tools.reload_package(reload_util=True)`を使用します。

### 一つのコピー値を選択属性へ貼り付け（2026-09-21）

OSクリップボードに一属性値だけがある場合に、その値を選択中の複数属性pathと
全選択nodeへ展開する操作を追加しました。異なる型区分、enum定義違い、readonly属性は
既存の同path Pasteと同様に内部結果の対象外とし、適用候補は一回のUndoへまとめます。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Pyrightのerrorは0件 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各158件成功 |
| utilの`verify.cmd` | 終了code 0。Maya 2025全体4,259件成功・739件skip、各versionのQt 843件・Maya UI 375件が成功 |
| Maya 2025本体の操作 | `result.json`の`success`はTrue。新旧Pasteを含む45工程と31枚の画像を確認 |
| メニュー表示 | Copy、同path Paste、一値の選択属性Pasteを文字切れなく表示 |

Maya本体ではTranslate Xの一値を選択したTranslate Y / Zと両nodeへ貼り、
一回のUndoで各元値へ戻ることを確認しました。同じ実装に対する最初の本体実行では
初回processと別processがともに終了code 0となり、OSクリップボード搬送と元dataの復元も成功しました。
最終資料の再取得では45工程完了後に既知のMaya終了待ちタイムアウトが再発したため、
`result.json`の機能結果とrunnerの終了codeを分けて記録します。

最終の結果と画像は`%TEMP%/bd-channel-box-maya2025-pe1n1023`です。
Maya 2026 / 2027本体の画面操作は実施していません。

toolsとutilの変更です。反映には`bd_tools.reload_package(reload_util=True)`を使用します。

### 全属性Copyと選択path Paste（2026-09-21）

Copyを基準nodeの全対応scalar属性へ拡張し、Paste側で選択した正式pathとの共通部分だけを
適用する構成へ変更しました。メニューバーへ「編集」を追加し、行選択なしでも全属性を
Copyできます。既存の一値展開は、右クリックしたpathのコピー値を全属性clipboardから選ぶ
操作へ変更し、一度のCopyで同path Pasteと異なる選択pathへの展開を使い分けられます。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Pyrightのerrorは0件 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各158件成功 |
| utilの`verify.cmd` | 終了code 0。Maya 2025全体4,261件成功・739件skip、各versionのQt 843件・Maya UI 377件が成功 |
| Maya 2025本体の初回操作 | `result.json`の`success`はTrue。Copy/Pasteを含む45工程と31枚の画像を確認 |
| Maya 2025本体の別process | `result-restart.json`の`success`はTrue。全属性clipboardの読取りを含む5工程と1枚の画像を確認 |

Maya本体では全属性Copy、選択した同pathだけの複数node Paste、右クリックしたpathの一値展開、
各操作の一回Undoを確認しました。初回・再起動後とも操作結果の保存には成功し、既知の
Maya終了待ちタイムアウトが発生したため、runnerが専用processを停止しています。
結果と32枚の画像は`%TEMP%/bd-channel-box-maya2025-mglh23po`です。
Maya 2026 / 2027本体の画面操作は実施していません。

toolsとutilの変更です。反映には`bd_tools.reload_package(reload_util=True)`を使用します。

### Copy/Pasteメニューと選択属性Pasteの整理（2026-09-21）

Copyを「全属性」「選択属性」、Pasteを「コピー元と同じ属性」「選択属性」のサブメニューへ
整理しました。「選択属性」Pasteはclipboardの項目数で動作を決め、一項目なら選択中の
互換属性すべてへ同じ値を展開し、複数項目なら選択属性と同じ正式pathだけを適用します。
Paste時にコピー元pathを右クリックし直す操作は削除しました。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Pyrightのerrorは0件 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各159件成功 |
| Maya 2025本体の初回操作 | `result.json`の`success`はTrue。Copy/Pasteを含む45工程と31枚の画像を確認 |
| Maya 2025本体の別process | `result-restart.json`の`success`はTrue。全属性clipboardの読取りを含む5工程と1枚の画像を確認 |
| Pasteサブメニュー表示 | 「コピー元と同じ属性」「選択属性」を文字切れなく表示 |

Maya本体では、Translate XだけのCopyから選択したTranslate Y / Zへの一値展開、
選択したweight / enabled / modeのCopyから同じ正式pathへの複数node Paste、全属性Copy、
各Pasteの一回Undoを確認しました。初回・再起動後とも操作結果は成功し、既知の
Maya終了待ちタイムアウトが発生したため、runnerが専用processを停止しています。
結果と32枚の画像は`%TEMP%/bd-channel-box-maya2025-gh5014j7`です。
Maya 2026 / 2027本体の画面操作は実施していません。

toolsとutilの変更です。反映には`bd_tools.reload_package(reload_util=True)`を使用します。

### コピー元と同じ属性の表示状態フィルター（2026-09-21）

「コピー元と同じ属性」に`全て`／`keyable + channelbox`／`keyable`／`channelbox`／`hide`を
追加しました。Paste時の先頭選択nodeで対象pathを決め、同じpathを全選択nodeへ適用します。
条件外項目は内部結果へ保持し、対象0件ではUndoを作りません。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Pyrightのerrorは0件 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各160件成功 |
| utilのBlack・3 version型契約・Maya 2025 full pytest | 成功。Maya testは4,262件成功・739件skip |
| Maya 2025本体の初回操作 | `result.json`の`success`はTrue。表示状態Pasteを含む45工程と32枚の画像を確認 |
| Maya 2025本体の別process | `result-restart.json`の`success`はTrue。全属性clipboardの読取りを含む5工程と1枚の画像を確認 |
| Pasteフィルターメニュー表示 | 5項目を文字切れなく表示 |

Maya本体では基準nodeの`enabled`だけをChannelBox、後続nodeではHideにして、
`channelbox` Pasteが両nodeの`enabled`へ適用されることと、一回のUndoを確認しました。
別process側も操作結果は成功しましたが、既知のMaya終了待ちタイムアウトによりrunnerの
終了codeは1でした。結果は`%TEMP%/bd-channel-box-maya2025-0qj3g0fp`です。

utilの標準`verify.cmd`では上記の工程まで成功後、Maya 2025のQt/UI互換testでWindowsの
OS clipboardが書込み直後に空を返し、既存clipboard test 3件が失敗しました。
今回追加した表示分類testと、tools側のOS clipboard Copy/Paste testは成功しています。
Maya 2026 / 2027本体の画面操作は実施していません。

toolsとutilの変更です。反映には`bd_tools.reload_package(reload_util=True)`を使用します。

### Paste結果通知の抑制（2026-09-21）

Pasteの成功・部分適用・対象0件では操作通知を表示せず、Paste開始時に
以前の通知を消去するようにしました。Transformの計算属性やlock属性などの
除外理由は内部結果に保持します。壊れたJSONや未対応versionなど、Pasteを
開始できない場合だけ、従来どおり画面へ簡潔なエラーを表示します。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Pyrightのerrorは0件 |
| 選択操作のMaya runtime test | Maya 2025 / 2026 / 2027で各38件成功 |
| Paste通知 | 一値展開・同path・表示状態フィルター・部分適用・対象0件で非表示を確認 |
| 致命的なclipboardエラー | 以前の通知を消し、壊れたJSONのエラーだけを表示することを確認 |
| Maya 2025本体の初回操作 | `result.json`の`success`はTrue。Paste後の通知非表示を含む45工程と32枚の画像を確認 |

Maya本体の結果は`%TEMP%/bd-channel-box-maya2025-l7j58fwb`です。初回processは
機能結果の保存後に既知のMaya終了待ちタイムアウトになりました。別processの
再起動確認ではWindowsのOS clipboardが空を返し、clipboard転送工程を
完了できませんでした。今回変更したPaste通知は初回processと各versionの
runtime testで検証済みです。Maya 2026 / 2027本体の画面操作は実施していません。

toolsのみの変更です。反映には`bd_tools.reload_package()`を使用します。

### 選択属性の表示・ロック直接操作（2026-09-22）

表示・ロックモードで選択中の行にある`key / ch / hide / lock`を直接操作すると、
操作後の状態を選択属性すべてと各選択nodeへ適用するようにしました。
選択外の行はその行だけを変更し、現在の属性選択は維持します。クリックとキー入力は
選択属性への一括操作、開始距離を超えた左ドラッグは通過行だけのなぞり操作として分離し、
どちらも操作単位を一回のMaya標準Undoへまとめます。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Pyrightのerrorは0件 |
| 状態・選択・なぞりのMaya 2025 runtime test | 103件成功 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各165件成功 |
| 選択属性への直接操作 | radioのクリックとlockのSpace入力を複数属性・複数nodeへ適用し、一回Undoで復元 |
| 選択外の直接操作 | 操作した一行だけを変更し、既存の複数選択を維持 |
| なぞり操作 | 選択済みの離れた行へ波及せず、通過行だけを変更 |
| Maya 2025本体の操作 | `result.json`の`success`はTrue。追加操作を含む45工程と34枚の画像を確認 |

Maya 2025本体ではTranslate X / Yを選択し、表示状態のクリックとlockのSpace入力が
両属性・両nodeへ適用されること、それぞれ一回のUndoで元へ戻ることを確認しました。
結果と画像は`%TEMP%/bd-channel-box-maya2025-78z1ar_q`です。機能結果の保存後に
既知のMaya終了待ちタイムアウトが発生したため、runnerの終了codeは1でした。

Maya 2026の最初の全件実行では、今回の変更と独立したOS clipboard testが一度だけ
失敗しました。該当testの単独再実行と全165件の再実行はどちらも成功しています。
Maya 2026 / 2027本体の画面操作は実施していません。

toolsのみの変更です。反映には`bd_tools.reload_package()`を使用します。

### 属性検索と検索欄の表示設定（2026-09-22）

Nice Name・属性名・正式pathを対象とする、大文字小文字を区別しないAND検索を追加しました。
検索は既存Table行の表示だけを切り替え、Bindingを再生成しません。設定メニューから
非表示／「全て」の場合のみ表示／常に表示を排他的に選択し、表示方針だけを保存します。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Pyrightのerrorは0件 |
| 検索・設定復元のMaya 2025 runtime test | 13件成功 |
| 検索・選択のMaya 2025 runtime test | 65件成功 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各178件成功 |
| 検索対象 | Nice Name・属性名・正式path、大小文字、複数語ANDを確認 |
| 表示方針 | 3項目の排他選択、初期値、全て連動、非表示中の検索停止を確認 |
| 選択とlifecycle | 隠れた属性の選択解除とShift選択起点の移動、両モード・ノード変更後の再適用を確認 |
| 保存 | 表示方針だけをWindow再表示・配置reset後へ復元し、検索文字列は破棄 |
| Maya 2025本体の操作 | `result.json`の`success`はTrue。検索を含む46工程と36枚の画像を確認 |

Maya 2025本体では3項目のメニュー表示、正式path検索、行・Bindingの維持、隠れた選択の解除、
非表示中の全行復帰、scene・Undoへの無書込みを確認しました。結果と画像は
`%TEMP%/bd-channel-box-maya2025-d9_ba798`です。機能結果の保存後に既知の
Maya終了待ちタイムアウトが発生したため、runnerの終了codeは1でした。
Maya 2026 / 2027本体の画面操作は実施していません。

toolsのみの変更です。反映には`bd_tools.reload_package()`を使用します。

### 属性Stepの保存と右クリックリセット（2026-09-23）

Step欄で確定した正の有限値を、正式属性pathと`number`／`distance`／`angle`の組で保存するように
しました。属性固有の初期値と同じStepは保存せず、Window再表示、package reload、Maya再起動、
配置reset後へ復元します。右クリックの「Step設定」から、選択属性または画面外を含む全属性の
保存設定を初期値へ戻せます。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Maya 2025 / 2026 / 2027のPyright errorは0件 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各181件成功 |
| utilの`verify.cmd` | 終了code 0。Maya 2025全体4,268件成功・753件skip、各versionのQt 863件・Maya UI 377件が成功 |
| Maya 2025本体の初回操作 | `result.json`の`success`はTrue。再表示・reloadを含む47工程と36枚の画像を確認 |
| Maya 2025本体の別process | `result-restart.json`の`success`はTrue。Step・workspace・clipboard復元を含む5工程と1枚の画像を確認 |

Maya本体では、複数選択したTranslate / RotateのStep `0.5`を再表示と
`bd_tools.reload_package(reload_util=True)`後へ復元し、別processでも保存済み
workspaceControlとともに復元できることを確認しました。初回・再起動後とも操作結果の
保存には成功し、既知のMaya終了待ちタイムアウトが発生したため、runnerの終了codeは1でした。
結果と37枚の画像は`%TEMP%/bd-channel-box-maya2025-57ylf_y1`です。
Maya 2026 / 2027本体の画面操作は実施していません。

toolsとutilの変更です。反映には`bd_tools.reload_package(reload_util=True)`を使用します。

### 属性名だけの選択強調と右余白（2026-09-24）

属性選択の青い強調表示を属性名だけへ限定し、float値欄を含む入力部品は
未選択時のQt paletteを維持するようにしました。属性名には4pxの右内側余白を設け、
選択色の内側で文字が境界へ接しないようにしています。属性名と入力Viewの外側spacingは
0pxにし、入力View内部の6px間隔は維持しました。値欄のクリック・縦ドラッグ・
複数属性入力などのイベント処理は変更していません。

| 確認対象 | 結果 |
| --- | --- |
| toolsのBlack・Pyright・unit test | 成功。unit 8件、Maya 2025 / 2026 / 2027のPyright errorは0件 |
| Maya 2025 / 2026 / 2027のtools runtime test | 各182件成功 |
| 入力部品の配色 | 値・Step・Slider・bool・enumのpaletteとautoFillBackgroundを選択前後で維持 |
| 属性名の余白 | 両モードで右内側4px・入力Viewとの外側0pxを維持し、狭いdock幅でも横scrollを発生させない |
| Maya 2025本体の操作 | `result.json`の`success`はTrue。属性名だけの選択強調と右余白を含む46工程と36枚の画像を確認 |

Maya 2025本体ではTranslate / Rotateの六属性を実際にドラッグ選択し、属性名だけが
Highlight色になって文字の右側へ青い余白が残り、そのまま入力欄へ接続することを確認しました。
float値欄のBase / Text色も
選択前から変化しないことを確認しました。
結果と画像は`%TEMP%/bd-channel-box-maya2025-5019hbkn`です。機能結果の保存後に
既知のMaya終了待ちタイムアウトが発生したため、runnerの終了codeは1でした。
Maya 2026 / 2027本体の画面操作は実施していません。

toolsのみの変更です。反映には`bd_tools.reload_package()`を使用します。
