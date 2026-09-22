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

リポジトリ直下から専用runnerを実行します。`--maya-version` は2025 / 2026 / 2027を
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

boolのCheckBoxへのSpace入力、floatの文字入力、Sliderのマウスドラッグ、
enumの選択肢表示・マウス選択・飛び番入力、右クリックメニューからの
表示更新とbool・enumの混在値を揃える操作、
各操作の1回Undo、選択追従、close / reopen、utilとtoolsのreloadを確認します。
ドッキングからfloatingへの切替、Mayaへのタブ再配置、Maya側のcloseによる破棄も確認します。
step欄のキー入力が値とUndoを変更しないこと、変更後の刻み幅で値入力できること、
値をUndoしてもstepが保持されることも確認します。
ホイールはWindowsの`WM_MOUSEWHEEL`を専用MayaのWindowへ送り、Qtによる自動フォーカス
移動も含めて検証します。通常の値欄・Slider付きの値欄・enum欄でOFF→ON→OFFを切り替え、
OFFかつ未フォーカス時の無書込み、フォーカス後とON時の編集、値欄・Step欄・enum欄から
一覧へのスクロール伝達を確認します。`QApplication.sendEvent()`だけではホイールによる
自動フォーカス取得を再現できないため、この検証の代用にはしません。
上部ComboBoxから値編集と表示・ロックを切り替え、非表示属性の追加によって
Window幅が変わらず、値編集156 px・設定200 pxの操作欄が収まることを確認します。
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
- `04-attribute-menu.png`: 属性名を右クリックして開いた操作メニュー。
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

複数属性拡張の最終検証（2026-09-19）では、Maya 2025本体の40工程が2回連続で成功し、
いずれもrunnerの終了code 0で正常終了しました。過去の終了待ちタイムアウトの原因が
解決したとは断定せず、再発時も操作結果と終了結果を分けます。
最終資料は`%TEMP%/bd-channel-box-maya2025-q6i850he`です。
toolsはBlack・Pyright・unit 8件、Maya 2025 / 2026 / 2027のruntime各144件が成功し、
utilの`verify.cmd`も対応3 versionを含めて成功しました。
詳細は[bdChannelBoxの検証記録](bd_channel_box.md#検証)を参照してください。利用者による確認は未実施です。

### 次回変更時の回帰確認

変更ごとの件数と確認範囲は[bdChannelBoxの検証記録](bd_channel_box.md#検証)を参照します。
変更した仕様に応じて既存testと本体runnerを更新し、次を確認します。

- 属性の複数選択: Ctrl／Shift・属性名ドラッグ・数値欄の縦ドラッグ、選択の強調表示、
  右クリック時の選択維持／切替、更新・Undo後の残存選択、対象ノード変更時の選択解除。
- 複数属性入力: 数値直接入力と貼付け、Enter／フォーカス移動での確定、Escapeでの取消、
  単位が異なる行への入力、範囲外の全体拒否、全属性・全ノードを含む1回Undo、
  属性・scene・選択構成が変わった後の古い対象への無書込み。
  上下・Slider・bool・互換enumの選択属性への適用と、未選択行だけの単独操作。
- 選択メニュー: 各属性をそれぞれの基準値へ揃えること、ロック／解除と3種類の表示状態、
  状態操作ではenum定義の不一致を理由にノードを除外しないこと、親ロックを自動解除しないこと。
- 表示・ロックの選択操作: 選択行のradio・CheckBoxのクリックとキー入力を
  選択属性全体へ適用し、選択外の行は単行操作となること。表示状態とlockの混在、
  一回Undo、行の除去の遅延、選択済みの離れた行へなぞり操作が波及しないことも確認する。
- OSクリップボード: Copyが基準nodeの全対応属性または選択属性を、
  未丸め値・型・単位・enum定義付きで保存し、
  sceneとUndoを変更しないこと。Pasteが1個／複数nodeの同一正式pathへ、表示行と行順に依存せず
  非表示属性も適用すること。欠落・型違い・enum定義違い・readonly対象の内部除外、hard limitの
  全体拒否、一回Undo、同値時の無Undo、壊れたdataと未対応versionの無書込みを確認する。
  表示状態で絞るPasteは先頭選択nodeでpathを決め、後続nodeへ同じpathを適用すること、
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
- step: 値／Undoを変更しないこと、型別初期値、選択行への同じ表示stepの反映、
  増減方式と対象ごとのキャッシュ維持、Step欄のない行の除外、非フォーカス時のホイール、
  close後の初期化。
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
- 幅・配置: Sliderあり／なし、最小幅／拡大時、長い属性名、縦スクロール時、ドック／floating。
  QTableView内の既存行Viewが常時表示され、選択の配色と一括入力欄で文字切れ・重なりがないこと。
  上部のMode／Attribute Filterラベルと選択欄が最小幅280 pxにも収まり、2行の選択欄が揃うこと。
  StepとSliderの幅・開始位置、値欄の文字切れ、不要な右余白を保存画像でも確認する。
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
