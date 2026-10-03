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

`test_bd_channel_box_order.py`はtransform・jointの優先順、drawOverrideのRGB子、
残りの属性の相対順、両モードと5フィルターの組合せを検証します。
drawOverride内ではoverrideEnabledが先頭になることも確認します。
表示切替でsceneの属性順・値・フラグ・Undoを変更しないことと、別compound内の同名属性や
類似した名前を誤って優先しないことも確認します。

`test_bd_channel_box_selection.py`は複数属性選択と一括入力の入口です。
Ctrl／Shift、選択後の未編集Enter・フォーカス移動での無書込み、同値の明示入力、
複数行・複数ノードの1回Undo、各行の単位変換、全件の範囲検証、編集不可・非数値行の除外、
選択の保持・解除、入力中断、モード変更時の確定、選択属性メニューを検証します。
モード変更時の入力拒否理由の維持と、Maya側のviewport交換後の行構築も回帰対象です。
上下・Slider・bool・互換enum操作とStep設定が選択属性へ適用されること、
Step欄のない行の除外、未選択行の操作がその行だけへ適用されることも確認します。
util側の`tests/maya/ui/test_plugs_value_edits.py`で、複数Bindingをまとめた事前検証と
書込み失敗時の復旧を確認します。toolsとutilの両方を更新し、同じ組合せで検証してください。

## bdChannelBoxのMaya本体検証

`scripts/test_bd_channel_box_maya.py`は、末尾ノードを基準にする選択追従と、
現行の揃える・ロックのサブメニュー、Step設定順を検証します。
現行メニューの自動回帰には`tests/maya/test_bd_channel_box*.py`を使用します。

リポジトリ直下から専用runnerを実行します。
`--maya-version` は2025 / 2026 / 2027を
指定でき、`--util-root` を省略すると環境変数またはsiblingのutilを使用します。

```powershell
& "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" -B `
    scripts/test_bd_channel_box_maya.py --maya-version 2025 --timeout 180
```

runnerは別の `maya.exe` を起動し、一時ディレクトリの `MAYA_APP_DIR`、Maya.env探索先、
project、script pathを使用します。通常のMaya.envを書き換えず、起動済みMayaへ接続しません。
PythonのuserSetupは読み込まず、検証用sceneで操作した後に専用processを終了します。
時間切れの場合も、runner自身が起動したprocessだけを終了します。
起動時のdeferred処理が完了した後に検証を開始し、専用sceneのUndoを有効にします。
Qt signal経由の例外も工程名付きで記録し、操作工程を終えても例外が残れば失敗とします。

runnerは、boolのCheckBoxへのSpace入力、floatの文字入力、
Sliderのマウスドラッグ、enumの選択肢表示・マウス選択・飛び番入力、
右クリックのサブメニューからの整列と複数属性のロックを検証します。
右クリックに「表示を更新」がないことと、直接更新が値・Undoを変更しないことも確認します。
各操作の1回Undo、選択追従、close / reopen、utilとtoolsのreloadも検証対象です。
ドッキングからfloatingへの切替、Mayaへのタブ再配置、Maya側のcloseによる破棄も確認します。
step欄のキー入力が値とUndoを変更しないこと、変更後の刻み幅で値入力できること、
値をUndoしてもstepが保持されることも確認します。
ホイールはWindowsの`WM_MOUSEWHEEL`を専用MayaのWindowへ送り、Qtによる自動フォーカス
移動も含めて検証します。通常の値欄・Slider付きの値欄・enum欄でOFF→ON→OFFを切り替え、
OFFかつ未フォーカス時の無書込み、フォーカス後とON時の編集、値欄・Step欄・enum欄から
一覧へのスクロール伝達を確認します。`QApplication.sendEvent()`だけではホイールによる
自動フォーカス取得を再現できないため、この検証の代用にはしません。
上部ComboBoxから値編集と表示・ロックを切り替え、非表示属性の追加によって
Window幅が変わらず、値編集216 pxと設定モードの必要幅の操作欄が収まることを確認します。
設定モードでは`hide`と`lock`の間が他のボタンと同じ6 pxになることも確認します。
縦スクロールバーは必要時だけ表示し、その出入りによる名前列幅・入力列位置の変化は許容します。
既存Hide属性の復帰、key／ch／hideのラジオボタン選択、lock／解除のSpace操作、
表示とロックの混在・独立操作・Undo／Redo、値とstepの維持も確認します。
両モードで5種類のフィルターを実ComboBoxから選び、モードごとの選択保持、無書込み、
絞り込み中の状態変更による行の除去・Undo／Redoでの再評価を確認します。
jointを選択して両モードの指定32属性とdrawOverrideの配置を確認します。
drawOverrideの先頭はoverrideEnabled、その次はoverrideDisplayTypeです。
属性名のドラッグでTranslate・Rotateの六属性を選び、数値を直接入力し、
両ノードの全対象へ適用されることと1回Undoを確認します。選択属性メニューでのロックとUndo、
選択維持、入力前・入力中・適用後とメニューの表示も確認します。
さらに10ノード・各30個の追加float属性を用いて、Window生成、一括入力、選択切替を
1回ずつ計測します。「keyable」「全て」では同じ属性を2回warm-up後に9回入力し、
遅延同期・描画を含む時間の中央値を`edit_keyable_median_ms`／`edit_all_median_ms`へ保存します。
行数は`edit_keyable_rows`／`edit_all_rows`です。
選択切替も値編集の40行・173行、10ノードの173行、表示・ロックの173行で計測します。
先頭と末尾のノードを交互に代表へ切り替え、10ノードでは選択リストの順序を反転します。
2回のwarm-up後に7回測り、入力行の破棄・再構築・Qt更新を含む中央値と行数を
`selection_<mode>_<filter>_<count>_nodes_median_ms`／`..._rows`へ記録します。
計測値は同時実行中の処理やMayaの環境によって変わるため、
性能保証値や自動判定の閾値には使用しません。

起動時に表示する `output` ディレクトリへ次の資料を残します。

- `result.json`: 成否、操作履歴、実行Maya version、性能計測値、各段階のUndo状態。
- `01-multiple-selection.png`、`02-single-selection.png`、`03-after-reload.png`:
  QtのWindow描画から保存した確認画像。
- `04-attribute-menu.png`: 初回実装時に属性名を右クリックして開いた操作メニュー。
- `05-docked.png`、`06-floating-content.png`: Maya右側へのドッキングとfloatingの表示。
- `08-enum-popup.png`、`09-enum-selected.png`: enumの選択肢と入力後の表示。
- `10-values-before-mode-switch.png`、`14-values-after-mode-switch.png`:
  モード切替前後の値入力表示。
- `11-state-mode-hidden-attributes.png`、`12-state-mode-locked.png`、
  `13-state-mode-mixed.png`: 非表示属性の設定行、ロック中、混在状態の表示。
- `15-values-hidden-filter.png`、`16-states-keyable-filter.png`:
  非表示属性の値編集と、Keyableだけに絞り込んだ状態編集の配置。
- `17-attribute-order-mode-0.png`、`17-attribute-order-mode-1.png`、
  `18-draw-override-mode-0.png`、`18-draw-override-mode-1.png`:
  jointの値編集／表示・ロックでの優先属性とdrawOverrideの配置。
- `25-multi-attribute-selection.png`、`26-multi-attribute-typing.png`、
  `27-multi-attribute-applied.png`: 六属性の選択、一括数値入力中、適用後の表示。
- `28-multi-attribute-menu.png`: 選択属性の操作メニュー。独立したpopupのためメニュー自身を描画して保存する。
- `29-multi-attribute-value-controls.png`: 上下・Slider・bool・enumの複数属性入力後の表示。
- `30-wheel-settings-menu.png`、`31-wheel-setting-off.png`:
  ホイール編集の設定メニューと、OFFを反映した値編集画面。
- `32-clipboard-value-menu.png`: 同一path Pasteと、一つの値を選択属性へ貼る操作を含むメニュー。
- `33-clipboard-filter-menu.png`: 基準nodeの表示状態で同一path Pasteを絞る5項目のメニュー。
- `34-multi-attribute-display-state.png`、`35-multi-attribute-lock-state.png`:
  選択属性へ直接適用した表示状態とlockの結果。
- `36-search-visibility-menu.png`、`37-attribute-search.png`:
  検索欄の3段階表示設定と、正式pathによる検索結果。
- `38-value-field-width.png`: 20文字の未確定文字列を値欄へ表示した幅の確認画像。
  通常行とSlider行の内側幅を検証し、撮影後はsceneへ確定せず元の表示へ戻す。
- `39-input-connection-colors.png`: 現在キー・現在キーなし・その他の入力接続・
  pairBlend・constraint・ロックをMaya本体で描画した画像。
  帯の中央画素と通常背景色、上下1pxの余白を照合する。
- `40-special-input-colors.png`: Driven Key・Expression・Muted・Animation Layer・
  Nonkeyable・Animation Clip・Key Alteredを実接続で描画した画像。
- `41-last-selected-reference.png`: 2ノードの元の選択順を保ち、末尾ノードの名前と値を表示した画像。
- `42-native-reference-0.png`〜`42-native-reference-7.png`: 選択履歴設定のOFF／ONと
  transform・jointの順序変更、再追加、network混在時のMaya標準Channel Boxの実表示。
- `result-restart.json`、`clipboard-original.json`: 別Maya processでのOSクリップボード読取り結果と、
  検証後に復元する元のMIME data。
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

複数属性拡張の初回検証（2026-09-19）では、Maya 2025本体の40工程が2回連続で成功し、
いずれもrunnerの終了code 0で正常終了しました。過去の終了待ちタイムアウトの原因が
解決したとは断定せず、再発時も操作結果と終了結果を分けます。
最終資料は`%TEMP%/bd-channel-box-maya2025-q6i850he`です。
toolsはBlack・Pyright・unit 8件、Maya 2025 / 2026 / 2027のruntime各144件が成功し、
utilの`verify.cmd`も対応3 versionを含めて成功しました。この段落は初回実装時点の記録です。
後続機能を含む利用者の最終確認は2026-09-24に完了しています。現在の件数と結果は
[bdChannelBoxの検証記録](bd_channel_box.md#検証)を参照してください。

### 次回変更時の回帰確認

変更ごとの件数と確認範囲は[bdChannelBoxの検証記録](bd_channel_box.md#検証)を参照します。
変更した仕様に応じて既存testと本体runnerを更新し、次を確認します。

- 基準ノード: 対象objectを抽出した選択リストの末尾を表示し、順序を入れ替えると
  見出し・属性行・値・enum定義・編集可否・接続色・表示状態が一緒に切り替わること。
  component・plug・同一nodeの重複除去と選択履歴設定の維持、未選択・単一・3ノードも確認する。
  選択順変更時は属性選択・古いメニュー・未確定入力を破棄し、sceneへ表示値を書き戻さないこと。
  Maya本体ではtransform・jointの順序変更と再追加を標準Channel Boxの描画に照らし、
  末尾の基準が一致すること。`mainObjectList`は同型の複数対象を返すため、
  照会リストの順序だけで表示nodeを断定しない。network混在時の標準UIの対象も記録する。
  複数ノードのアニメーションカーブCopy/Pasteは、基準優先のBinding順ではなく
  元の選択順でコピー元と貼り付け先を対応させること。
- 属性の複数選択: Ctrl／Shift・属性名ドラッグ・数値欄の縦ドラッグ、属性名だけの選択強調、
  属性名の右内側余白と入力Viewまでのspacing、値・Step・Slider・bool・enum・stringの入力palette維持、
  右クリック時の選択維持／切替、更新・Undo後の残存選択、対象ノード変更時の選択解除。
- 複数属性入力: 数値直接入力と貼付け、Enter／フォーカス移動での確定、Escapeでの取消、
  float値欄・Step欄・Slider付き値欄の初回クリック全選択と再クリック・横ドラッグ、
  単位が異なる行への入力、範囲外の全体拒否、全属性・全ノードを含む1回Undo、
  属性・scene・選択構成が変わった後の古い対象への無書込み。
  上下・Slider・bool・互換enumの選択属性への適用と、未選択行だけの単独操作。
- 選択メニュー: 各属性をそれぞれの基準値へ揃えること、ロック／解除と3種類の表示状態、
  状態操作ではenum定義の不一致を理由にノードを除外しないこと、親ロックを自動解除しないこと。
- 現行の右クリックメニュー: 値編集行のラベル・入力部品から同じメニューを開き、
  選択済みの行は複数選択を維持し、未選択行はその行だけを選ぶこと。
  状態編集行はメニューも選択変更もなく、余白はStep設定だけを示すこと。
  アニメーション、値の揃え・コピー・ペースト、フリーズ、Step設定、ロック・表示の
  並びと2階層以内の子項目を[現行仕様](bd_channel_box.md#選択属性のメニュー)に照らすこと。
- 値を揃える操作: 「選択属性」は各行の表示ノード値を使い、「全て」と各表示条件は
  表示ノードの属性状態で同じpathを選ぶこと。検索・表示フィルター・行選択で隠れた属性、
  型やenum定義の不一致、編集不可、未丸め値、1回Undo、同値時の無Undo、
  OSクリップボードの維持を確認すること。
- 表示・ロックの選択操作: 選択行のradio・CheckBoxのクリックとキー入力を
  選択属性全体へ適用し、選択外の行は単行操作となること。表示状態とlockの混在、
  一回Undo、行の除去の遅延、選択済みの離れた行へなぞり操作が波及しないことも確認する。
- OSクリップボード: Copyが基準nodeの全対応属性または選択属性を、
  未丸め値・型・単位・enum定義付きで保存し、
  sceneとUndoを変更しないこと。Pasteが1個／複数nodeの同一正式pathへ、表示行と行順に依存せず
  非表示属性も適用すること。欠落・型違い・enum定義違い・readonly対象の内部除外、hard limitの
  全体拒否、一回Undo、同値時の無Undo、壊れたdataと未対応versionの無書込みを確認する。
  表示状態で絞るPasteは末尾の基準nodeでpathを決め、他のnodeへ同じpathを適用すること、
  成功・部分適用・対象0件で通知を表示せず、以前の通知を消すことも確認する。
  一属性値だけの場合は選択した複数の同型pathと全選択nodeへ展開し、複数値や型・単位・
  enum定義が異なる対象へ誤って適用しないことも確認する。
  Windowsでは二つのMaya process間でCopy/Pasteし、custom MIMEまたはmarker付きtextが
  OSクリップボードを介して維持されることも確認する。
- 入力・対応型: 選択／更新で無書込み、外部変更の非伝播、混在値への一括入力、1回Undo、編集不可対象の扱い。
- 値同期の負荷: 表示フィルターや入力経路に関わらず、無関係な行の再読取りを発生させない。
  接続・親属性・アニメーションによるdirtyの同期はutilの通知回帰testでも検証する。
- 属性順: transform・jointの指定属性、drawOverride配下、残りの安定順を保ち、
  モード・フィルター・表示更新で順序を揃える。並べ替えでsceneやUndoを変更しない。
- bool: 基準値を二値CheckBoxで表示し、クリック／Spaceで切替、属性名の直後に左詰め。
- enum: 項目名と実整数、飛び番・未定義値、定義不一致の除外・入力停止、同値揃えと選択肢の終了。
- string: 空文字・前後の空白・Unicodeの保持、NULの拒否、同じ基準文字列の明示入力による
  後続値の統一、複数属性・複数nodeへの一括入力と一回Undoを確認する。編集中に基準または
  後続plugの値が外部変更された場合は未確定入力を破棄して基準値を表示し、表示同期と
  その後のフォーカス移動で書き戻さないことを確認する。入力可能なままの状態通知や
  同値再通知では入力を保持し、汎用`StringLineEdit`の既定の競合保持も検証する。
- step: 値／Undoを変更しないこと、型別初期値、選択行への同じ表示stepの反映、
  増減方式と対象ごとの設定維持、Step欄のない行の除外、非フォーカス時のホイールを確認する。
  正式属性pathと数値種別ごとの保存、初期値と同じ項目の非保存、Window再表示・reload・
  Maya再起動・配置reset後の復元、右クリックからの選択属性／画面外を含む全属性リセットも検証する。
- ホイール設定: 初期OFF、値欄・Step欄・enum欄への即時反映、OFF時の未フォーカス入力停止、
  行再構築・Window再表示・Maya再起動後の復元、配置リセット後の維持、scene・Undoへの無書込み。
  通常の値欄・Slider付きの値欄・enum欄の自動フォーカス取得防止、フォーカス後の編集、
  ONへの復帰と再度OFFにした場合の動作、一覧へのスクロール伝達をWindows入力経路で検証する。
- 表示・ロック: 既存Hide属性の列挙・復帰、Keyable／ChannelBox／Hide、ロック／解除、
  各項目の混在と独立操作、1回UndoとRedo、接続済み属性・親ロックの扱い。
  表示状態の混在は3ボタンとも未選択にし、印・tooltipを確認する。
  矢印・Spaceの選択、同じ状態の再選択、無効なボタンからの無書込みも検証する。
- モード切替: sceneとUndoへの無書込み、step保持、古い入力と選択肢の終了、
  enum定義が異なる対象の状態編集、全てフィルターでHide行を維持すること。
- フィルター: 両モードの5分類、初期値とモードごとの保持、基準ノードだけの表示判定、
  状態変更完了後と外部変更・Undo／Redoでの再評価、Hide属性の値編集と従来の操作制限。
  入力途中の数値確定、連続編集のUndo終了、step保持、キーボードでの往復も検証する。
- 属性検索: Nice Name・属性名・正式path、大小文字を無視した空白区切りAND検索、
  5分類との組合せ、両モードとノード変更後の文字列維持、検索によるBindingの無再生成を確認する。
  隠れた属性の選択解除と無復元、結果0件の案内、検索非表示中の条件無効化、scene・Undoへの
  無書込みも検証する。検索欄の非表示／「全て」の場合のみ／常時表示は排他的に選択し、
  表示方針だけをWindow再表示・Maya再起動・配置reset後へ復元する。
- 幅・配置: Sliderあり／なし、最小幅／拡大時、長い属性名、縦スクロール時、ドック／floating。
  QTableView内の既存行Viewが常時表示され、選択の配色と一括入力欄で文字切れ・重なりがないこと。
  上部のMode／Attribute Filter／Attribute Searchが最小幅340 pxにも収まり、各入力欄が揃うこと。
  StepとSliderの幅・開始位置、値欄の文字切れ、不要な右余白を保存画像でも確認する。
  値欄150 pxで`1234.123456789123456`の20文字が収まり、Step／Sliderの60 pxを維持すること。
  行数と長い属性名が増えてもWindow幅を保ち、各モードの操作幅で文字切れ・重なりがないことを確認する。
  縦スクロールバーは必要時だけ表示する。
- lifecycle: 選択切替・close・reloadで古い入力とcallbackを終了し、再表示で重複させない。
  Maya側がviewportを交換した後も現在の親へ行を生成できることを確認する。

対応version、配布構成、Qt / Maya API互換性の変更では3 versionのruntime testを実行します。
workspaceControl、再起動復元、実画面配置の変更では対象Maya本体で確認し、
再起動復元の仕様を変える場合は以下の2段階検証も行います。
Markdownのみの変更は`git diff --check -- <changed-files>`を実行し、runtime testの再実行は不要です。

Windowsの`QT_QPA_PLATFORM=offscreen`ではQtのフォント一覧が空になる場合があります。
toolsのMaya testは、その場合だけWindows標準のSegoe UIを読み込み、9 ptで配置を検証します。
フォントなしの仮の文字幅を製品の配置不具合として扱わないためのtest側の設定です。
読み込み失敗はtestを停止します。製品UIのフォント・幅設定は変更せず、Maya本体でも確認します。

### 性能比較を記録するとき

上記の本体runnerは現在の実装を計測します。比較する場合は変更前後で同じMaya version、
ノード数、属性構成、モード、フィルター、表示行数を使い、tools・utilそれぞれのcommitと
未commit差分の有無も記録してください。異なるprocessや負荷条件の単発値を直接比較しません。
反復回数とwarm-up、Qtの遅延更新・削除・描画、GCの扱いを揃え、中央値を比較します。
特に選択切替は`cmds.select()`の呼出しだけでなく、入力行の再構築とQt更新まで含めます。

`result.json`、画像、ログは既定では`%TEMP%`配下にあるため、将来の比較資料として使う場合は
消去される前に保管してください。docsには比較条件・結果・検証の制限を残し、
操作成功とrunnerの終了codeを別々に記録します。性能改善時も既存操作の回帰確認は維持します。

### Maya再起動による配置復元

一度目の検証で `--prepare-restart` を指定すると、全操作の確認後に新しいWindowを開き、
floatingにしてworkspaceとpreferencesを専用profileへ保存します。

```powershell
& "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" -B `
    scripts/test_bd_channel_box_maya.py --maya-version 2025 --prepare-restart --timeout 180
```

一度目のprocessが終了したことと `result.json` の成功、`prepared-restart.json` の存在を確認し、
表示された `output` を二度目の `--restart-from` に指定します。
終了待ちだけがタイムアウトした場合も、専用processの停止を確認してから実行します。

```powershell
& "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" -B `
    scripts/test_bd_channel_box_maya.py --maya-version 2025 --restart-from <output> --timeout 180
```

二度目は同じprofileの別processを起動し、`show()` を呼ぶ前にworkspaceControlと入力UIが
自動復元されたことを確認します。floating配置・寸法の復元を確認し、新しいsceneの選択と
一括入力を検証してから終了します。結果は `result-restart.json`、画像は
`07-after-maya-restart.png`、ログは `*-restart.log` に保存し、一度目の結果を残します。
この再起動検証はsceneの保存・復元ではなく、Maya workspaceからのUI復元を対象にします。

## 値欄の幅拡張の検証（2026-09-30）

値欄160 px・共通入力列226 pxへの変更では、Maya 2025のbdChannelBox関連runtime test
188件、Pyright、Black checkが成功しました。幅280 / 360 / 520 pxで横スクロールがなく、
通常行とSlider行で20文字の文字幅が編集領域内へ収まることを確認しました。

Maya 2025本体では46工程の操作結果が成功し、`38-value-field-width.png`で
`1234.123456789123456`が末尾まで見えることを確認しました。
資料は`%TEMP%/bd-channel-box-maya2025-69fcd5de`です。
ただしMaya本体の終了待ちが180秒でタイムアウトし、runnerは専用processを停止して
終了code 1を返しました。操作と表示の検証成功と、本体の正常終了は区別します。

## 値欄150 pxと表示・ロック行の余白調整（2026-10-01）

値欄150 px、初期Window幅380 px、最小幅340 pxへの調整では、
bdChannelBox関連runtime testがMaya 2025 / 2026 / 2027で各189件、
Pyright、Black checkが成功しました。
表示・ロック行は幅340 / 380 / 520 / 650 pxで属性名が残り、`hide`と`lock`の間も
他のボタン間と同じ6 pxであることを確認しました。

Maya 2025本体の隔離processでは46工程の操作結果が成功し、
`11-state-mode-hidden-attributes.png`で属性名と操作部品の配置を確認しました。
資料は`%TEMP%/bd-channel-box-maya2025-gtgj6mwk`です。
検証用Mayaの終了待ちは150秒でタイムアウトし、runnerは終了code 1を返しました。
表示・操作の成功と本体の正常終了は区別します。

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
