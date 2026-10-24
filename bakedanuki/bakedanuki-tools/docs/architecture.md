# Architecture

## Dependency Direction

現在の依存方向は次の一方向です。

```text
bd_tools -> bd_util -> Maya API / Qt
bd_rig   -> bd_util
```

将来、rig UI から tools の機能を呼び出す場合は次の形を許容します。

```text
bd_rig -> bd_tools -> bd_util -> Maya API / Qt
```

`bd_util` から上位 package を import してはいけません。`bd_tools` から `bd_rig` も
import しません。この制約により、tools は rig の導入有無にかかわらず独立して動作します。

## Responsibility Boundaries

### `bd_util`

- 再利用可能な Maya / OpenMaya 操作
- 値型、node 操作、undo を扱う共通基盤
- Qt binding facade
- Window、workspaceControl、callback、UI 状態保存の共通 lifecycle
- Maya上部または設定された既存メニュー配下の`bakedanuki`メニュー、categoryと
  ownerごとの項目登録・解除、起動設定TOMLの読込み

### `bd_tools`

- ユーザーに提供する個別ツール
- UI とユーザー操作
- ツール固有のユースケースと設定
- `bd_util` の汎用 API を組み合わせた Maya scene 操作
- `tools` categoryと3ツールの項目、起動時登録hookと設定TOMLの初回作成

### `bd_rig`

- リグ固有の domain model、保存形式、builder
- リグシステム全体の UI
- 必要になった場合の `bd_tools` 公開 UI の呼び出し

ある処理が複数の Maya ツールで再利用でき、ツール固有の意味を持たない場合は
`bd_util` に置きます。単に現時点で2か所から呼ばれるという理由だけで移動せず、責務と
依存方向を先に確認します。

`bd_util.Nodes` の操作入口を保持する変数名は `bd_nodes` を基本にします。
ノード名の集合は `node_names` など、役割が分かる名前で区別します。

```python
import bd_util as bdu

bd_nodes = bdu.Nodes()
operator = bd_nodes.existing("ctrl")
```

## Tool Package Shape

個別ツールは、最初の機能を実装する段階で `bd_tools` 直下に package を追加します。
外部から開く必要がある UI は、小さく型付けされた `show()` を安定した入口として公開します。

```text
bd_tools/
  <tool_name>/
    __init__.py
    ui.py
    ...
```

最初の実装は `bd_tools.bd_channel_box` です。`ui.py` がWindow、`widget.py` が入力行、
`table.py`が一覧内の属性選択と数値直接入力、`controller.py` が選択ノード・対応属性と
操作対象を組み立てます。`custom_filters.py`は共有JSONの形式と読込みを、
`custom_filter_registry.py`はツール固有の登録順・有効状態と個人設定を扱います。
`custom_filter_editor.py`は共有JSONの作業中データと競合検出・原子的保存を、
`custom_filter_setup.py`はノード型ごとの属性選択・順序・保存UIを扱います。
表示順一覧の複数選択はsetup UIが保持し、選択全件の移動・除外は作業中データへ
一度で適用します。移動後も正式pathで同じ属性の選択を復元します。
汎用の属性列挙と一括編集はutilへ配置します。
「値編集」（`values`）は選択数によらず全選択ノードを操作対象として保持し、
属性列挙・行生成・常設Binding・値監視を基準ノード一個へ限定します。
明示的な操作時だけ必要な属性を全対象から解決し、常時監視を持たない一時Bindingで
既存の一括編集・検証・Undo経路を使用します。対象の解決と操作範囲はtools、
監視を持たないBinding・型・接続・範囲検証・一括書込みと失敗復旧はutilの責務です。
値編集は混在や全対象の編集可能件数を常時計算しません。
「表示・ロック」（`states`）も全選択を保持し、属性列挙・常設Binding・構成監視は基準だけです。
明示入力時に正式pathと型区分だけを全対象から照合し、状態専用の一時Bindingで操作します。
基準の操作可否と対象ごとの除外、通常の複数行入力の一括復旧を維持します。
なぞりは通過行だけを即時変更し、共有Undoを渡して全体を一回Undoにまとめます。
表示とlockの混在・全対象の変更可能件数は常時計算せず、適用候補と除外理由を操作時に示します。
utilのSweepは明示入力先・同状態入力・開始列を指定でき、同じ行への反復入力を避けます。
カスタムフィルターのなぞりは未保存データだけを変え、候補radioを即時同期し、
表示順と状態表示の更新は終了時にまとめます。属性名ドラッグによる選択は維持します。
Step・Slider・メニューの操作と、基準だけを扱うCopy・改名・独立ツールの対象規則は維持します。
Mode先頭・初期選択は値編集で、値編集には選択数上限を設けません。
カスタムフィルター設定も選択数上限を設けず、選択抽出後は基準一個だけを保持します。
属性・識別情報の取得と構成監視も基準に限定し、その型の共有JSON定義を編集します。
別の型の定義と未保存データは保持し、Mayaの選択は変更しません。
値編集・表示とロックへ戻ると現在の全選択を取得し直します。どのモードも選択数上限はありません。
旧`bulk_values`の呼出しは`values`へ移行します。Mode自体はWindow内で保持し、
値編集のフィルター選択だけを個人設定へ保存します。
ModeとAttribute Filterは独立した共通ヘッダーに配置し、その下を横線で区切ります。
検索欄は線の下へ分離し、表示切替やモード固有UIが共通2行の列幅を変えない構造にします。
bdChannelBoxは `MayaDockableWindowController` を使い、固定workspaceControl IDと
`bd_tools.bd_channel_box.ui.restore` を維持します。初回は右ドック、close時は完全破棄とし、
workspace配置の復元・resetはutil、入力と選択監視の終了はtoolsが所有します。
`bd_child_compensated_set`は移動・回転の共通2タブWindow、
`bd_rotation_preserving_pose`は姿勢維持の回転Windowを所有します。どちらも独立した
`MayaDockableWindowController`と公開`show()`を持ち、bdChannelBoxは右クリックから
起動する際にだけ各公開入口を呼びます。新ツールからbdChannelBoxをimportしません。
共通の選択監視・XYZ入力部品と画面内配置計算は`bd_tools._shared`に置き、
Maya操作・Undoは`bd_util`のコマンドを使います。Mayaが両Windowのドック配置を保持し、
子維持ツールの選択タブ・入力条件・浮動タブ別サイズは同ツールの`ui.ini`へ保存します。
選択変更・Undo／Redo・scene切替の監視は各画面の寿命に結び付け、現在選択の末尾にある
基準ノード1個の実値へ同期します。表示更新とStep設定はscene・Undo履歴を変更しません。
値とstepの複合View、属性path・数値種別ごとのprofileと保存基盤はutilへ配置します。
属性別の初期step、profileの識別子、操作対象の選別はbdChannelBoxが所有します。
step設定はuser preferencesへ保存し、sceneの値・Undo履歴へ含めません。
属性名の整列、混在の印、対象情報のtooltip、選択属性を操作する右クリックメニューも
bdChannelBoxが所有します。値編集モードでは値欄のQt標準編集メニューを表示せず、
属性行のどこを右クリックしても同じツール用メニューを開きます。
一覧は`QTableView`へ1属性1セルを置き、delegateが既存の属性行Widgetをpersistent editorとして
常時表示します。modelは行と選択を管理し、値は既存Bindingから同期します。
Maya本体がviewportを交換する場合に備え、行の親は構築時に`viewport()`から取得し、
以前のviewportを永続的な参照として保持しません。
既存の数値・Step・Slider・bool・enum・string・状態Viewを維持し、値をmodelへ複製しません。
複数選択時の数値文字入力・貼付けだけを一時的な文字欄で受け付け、入力開始時の属性集合へ確定します。
既存の数値・Slider・bool・enum・string Viewは任意入力handlerを使い、選択中の互換属性へ操作を委譲します。
ノードの識別子と属性path・型区分を用いて、同じノードの再表示では残存行の選択を維持し、
対象ノードが変わる場合は選択を解除します。属性選択自体はsceneや設定ファイルへ保存しません。
選択色は属性名の`QLabel`だけへ適用し、値・Step・Slider・bool・enum・stringのpaletteは変更しません。
属性名は右側に4pxの内側余白を持ち、選択色の内側で文字が境界へ接しないようにします。
属性名と入力Viewの外側spacingは0pxとし、入力View内部の部品間隔だけを6pxに保ちます。
boolにはutilの`BoolCheckBox`、両側hard limit付きfloatには`FloatSliderSpinBox`、
それ以外のfloatには`FloatValueStepSpinBox`を使います。値欄とSliderの並び順の機能はutil、
Value先行の選択、単位の非表示、固定幅と右寄せはtoolsの表示方針です。
stringにはutilの`StringLineEdit`を使い、bdChannelBoxでは確定したMaya値が編集中に
変化した場合の追従を有効にします。入力保持を既定とする汎用Viewと、Maya値を優先する
bdChannelBoxの表示方針を分けます。
ノード名は属性stringとは異なる正本なので、utilの`MayaNodeNameBinding`と
`StringLineEdit`を組み合わせます。Maya名の採番、外部改名の監視、Undo／Redoへの追従、
編集可否はutilへ委譲し、toolsの`_NodeNameLineEdit`は閲覧・入力・競合時の外観だけを
切り替えます。controllerは選択リスト末尾を基準とし、WidgetはそのnodeのUUIDで
名前欄の寿命を判定します。同じ実体の改名や属性行の再構築では入力欄を維持し、
選択実体が変わると旧入力を停止・破棄してから新しいBindingへ接続します。
float値欄とStep欄ではutilの`select_all_on_mouse_focus`を有効にし、初回クリックで
入力文字を置換できる状態にします。再クリックと横ドラッグは通常の文字編集へ渡します。
属性行の優先順もtoolsの表示方針です。`bd_channel_box/config.py`の
`ATTRIBUTE_PRIORITY_PATHS`をcontrollerが行構築時に読み、正式pathで照合します。
既定ではvisibility・translate・rotate・scaleの10属性、残りの指定22属性、
drawOverride配下、その他の順に安定ソートしてから行を構築します。
drawOverride内では設定に含めたoverrideEnabledを先頭にし、残りの相対順を維持します。
両モードと標準5フィルターで共有し、utilの列挙順とscene内の属性順は変更しません。
カスタムフィルターではJSONの属性配列順を用い、登録ファイルの順序はComboBoxの
カスタム項目の順序にだけ適用します。
共有JSONの新規作成・複製は`custom_filter_dialogs.py`で保存先・登録の経路を共有し、
保存ダイアログの実ファイル名から表示名を決めます。管理画面と設定画面から利用し、
未保存確認はファイル作成前に行います。既存pathは保存処理でも拒否し、再選択へ戻します。
設定画面の操作は編集用ComboBox右隣に新規作成・名前変更・保存・破棄・管理の20×20アイコンを置きます。
管理アイコンの要求は親Widgetへ渡し、設定メニューと同じ管理ウィンドウを再利用します。
管理ウィンドウは説明ラベル・20×20のQToolButton 7個・登録一覧の順で配置し、アイコンを左寄せに並べます。
登録一覧は階層なしのQTreeWidgetで、表示アイコン付きの名前・ファイルパス・読込状態の3列を持ちます。
名前・読込状態列はResizeToContents、パス列はStretchで残り幅を使用します。
パス列専用delegateはElideLeftを指定し、実パスと全文tooltipを保持したまま末尾を優先します。
末尾列の自動Stretchは無効にし、登録順と列ソートを混在させないためソートは無効にします。
行単位のExtendedSelectionを使い、目のアイコンによる表示状態とボタン操作対象の複数選択を分離します。
`custom_filter_manager_view.py`の専用delegateで名前左のチェック領域を目のアイコンに描き換えます。
ONは`ghostingVisible.png`、OFFは`ghostingHidden.png`を16×16で描画し、
約20×20のクリック領域を使用します。名前や行の余白の操作は通常の行選択へ渡します。
treeのマウス処理では目のクリックを行選択より先に扱い、対象行を管理画面へ通知します。
選択内なら選択全件をクリック行の反対状態へ揃え、選択外ならその1件だけを切り替えます。
選択集合とcurrentは変更せず、`registry.set_enabled_many()`で保存と通知を各一度にまとめます。
一覧と管理画面専用QToolButtonはSpaceのShortcutOverride・KeyPress・KeyReleaseを
ignoreしてQtの行選択・ボタン操作を避け、Mayaのショートカット配送へ受け流します。
長押しのrepeatも同じ扱いとし、Hotboxを直接呼ばずMaya側の割当を使用します。
この処理は管理画面だけに限定し、その他のキーと別の入力ダイアログには適用しません。
内部は既存のCheckStateRoleを保持し、
プログラムによる個別変更は`registry.set_enabled()`へ接続します。読込エラーは独立した状態列で示します。
公開`tree_widget`は引き続き`qt.QTreeWidget`型とし、JSON・個人設定の形式は変更しません。
登録パスの順序が変わらない更新では既存行を書き換え、チェック通知中のQt内部参照を破棄しません。
再構築前に選択pathとcurrent pathを保持し、再読込・移動・表示切替後も残存登録へ戻します。
選択登録の一括解除と上下移動はregistryの`remove_many()`・`move_many()`へ委譲します。
一括操作は変更後に一度だけ個人設定を保存し、完了した状態を一度だけ通知します。
上下移動は選択内の相対順を保ち、選択全件を1段移動します。方向の端を含む場合は変更せず、
対応ボタンも無効にします。複製は正常な登録の単独選択だけを受け付けます。
目のtooltipへ表示ON/OFFと操作案内、行tooltipへパス全文と読込エラー理由を出し、通常の下部詳細は置きません。
登録設定そのものの読込・保存失敗は専用の`storage_error_label`で表示します。
UIの再読込は全登録を対象にまとめ、登録順と有効状態を保持する`registry.reload_all()`へ委譲します。
個別の再読込ボタンとそのUI callbackは廃止し、内部処理で使用する`registry.reload()`は維持します。
管理画面からの新規作成・複製後は、管理画面を非表示にせず作成行を選択します。
新しいpathを設定モードの編集対象へ渡す既存の経路は維持します。
名前変更は入力中にファイル名・宛先衝突を検証し、`CustomFilterDraft.rename()`へ渡して
表示名と`destination_path`の下書きだけを更新します。保存時は外部変更と衝突を再検査し、
実ファイルの名前変更を確定してregistryのpathを順序・有効状態ごと引き継ぎます。
保存直後は検証済みの定義をregistryへ渡し、再読込の失敗で旧pathだけが残る状態を防ぎます。
pathの変更通知を通常の登録変更通知より先に送り、controllerの各モードと値編集の
保存済み選択を新pathへ追従させます。JSON・設定schemaは維持します。
編集用ComboBoxは同名時にファイル名・フォルダーを補い、下書き名と未保存印を反映します。
registryの保存済み名は保存後に更新します。常設の状態ラベルは置かず、型調査失敗は
既存の共通通知へ流します。ノード型のComboBoxは5アイコンの幅に制約されない別行に配置します。
設定モードでは共通WidgetのStepコンテキストメニューを抑止します。表示順一覧はviewportの
右押下を標準処理より先に受け、選択内は集合を維持、選択外は単独選択にして「除外する」を開きます。
除外はゴミ箱ボタンと同じ正式path・下書きの経路を使い、余白では選択を変えずに通知を消費します。
検索欄もContextMenu通知だけを消費し、標準編集キーを維持します。親へ転送するNoContextMenuは
使用しません。専用メニューは一覧再構築・モード切替・Widget破棄で閉じます。
新規作成の初期保存先はutilの設定path解決から求めたMaya version別prefs内の
`bd_channel_box/custom_filter`です。複製の初期保存先は元JSONのフォルダーを使います。
複製は元ファイルを読み直して全型を別JSONへ保存し、元ファイルを変更しません。
設定画面は選択ノードに追従する編集と、JSON内のノード型を固定した編集を持ちます。
型の標準scalar候補の取得はutilの`inspect_scalar_attributes_by_type()`へ委譲し、
ノードの作成とsceneの変更を行いません。型から照合できない保存済みpathは値種別を
推測せず専用の候補として保持し、標準表示条件が「全て」のときだけ提示します。
編集対象は同じ`CustomFilterDraft`内で切り替え、全型の未保存データを維持します。
設定モードでは表示順と候補をQToolBoxの2ページに配置し、選択中のページへ領域を
配分します。初回は候補を開き、ページ選択はWindow内で保持します。ページを作り直さず
検索・選択・スクロール位置を維持し、切替時はメニューとなぞり・ドラッグを終了します。
QToolBoxのbackgroundRoleはWindowとし、Mayaの通常背景を内部のページと候補へ継承します。
複数選択した候補の変更は選択中の属性pathをまとめて
作業中のJSON定義へ反映し、候補行の表示更新を操作後に行います。候補外の既存pathと
別ノード型の定義は保持し、sceneのBindingとUndoは使用しません。
候補の複数選択はUI内に正式pathの集合として持ち、属性名への入力だけで更新します。
選択中の行のラジオ操作は選択したpathを候補の表示順で既存の一括編集へ渡し、
選択外のラジオはその1件だけを渡します。選択色とtooltipは変更した行だけを更新し、
行の再構築とJSON書込みを選択中に行いません。
`CustomFilterDraft`は設定画面の生存中だけ作業中データを保持し、保存時に共有JSONの
外部変更を確認して書き込みます。登録定義の再読込は保存後に行います。モードと編集対象の
切替は未保存確認を通しますが、Window終了・配置reset・package reloadの破棄経路は
確認を通さず作業中データを捨てます。この経路を変更する場合はworkspaceControlの終了、
配置reset、reloadの各lifecycleとcallbackの解除を併せて検証します。
通常の値変更では並べ替えや行の再構築を行いません。
値編集のAttribute Filter選択はtoolsの`ValueFilterPreferences`が担当します。
controllerの`values_attribute_filter`を正本とし、ほかのモードの表示中もその保持値だけを
`bd_channel_box/ui.ini`の`preferences/main/values_attribute_filter`へ同期します。
保存値は標準ID、または`custom:`に正規化JSON pathを続けた文字列です。
登録一覧を読んでから選択を復元し、カスタムは登録・ON・正常読込済みの定義だけを採用します。
利用不能・不正・未設定は`visible`へ戻します。既存のUiStateManagerが管理する
ホイール・Stepなどのキーとは分け、sceneのBindingとUndoには参加しません。
今後対応型を追加するときも、toolsで汎用BindingやViewを複製せずutilを拡張します。
空の directory は作りません。個別ツール同士の
暗黙の import は避け、共有処理は責務に応じた場所へ抽出します。

## UI Lifecycle

UI 基盤は `bd_util.ui` と `bd_util.maya.ui` を利用します。

- Qt class は `bd_util.ui.qt` 経由で使用する。
- 通常 Window は `MayaWindowController` で重複表示を防ぐ。
- dockable UI は `MayaDockableWindowController` と固定 `control_id` を使用する。
- `settings_path` はツール名を先頭にした固定 path にする。
  例: `bd_child_compensated_set/main`。
- Maya callback は Window owner に関連付ける。
- import 時には UI を表示せず、明示的な `show()` で表示する。
- reload 前には controller、workspaceControl、callback を完全に破棄する。

`bd_tools`のMaya Moduleは、専用の`scripts/userSetup.py`を持ちます。
interactive起動時だけ`maya.utils.executeDeferred()`へメニュー登録を予約し、
`bd_util.maya.ui.register_menu_item()`で`bakedanuki > tools`に`bdChannelBox`、
「移動・回転をセット（子を維持）」、
「回転をセット（姿勢を維持）」をこの順に追加します。各ツール本体はクリックされるまで
読み込みません。上部メニューからは引数なしの公開`show()`を呼び、既存の配置と
選択タブ・設定先を尊重します。登録のownerは`bd_tools`、
categoryは`tools`とし、将来のrig・physicsは別owner/categoryで同じ`bakedanuki`を共有します。
メニューのMaya UI構築と他ownerを保つ解除処理はutilが所有します。
画像は各ツールpackageの`icon/<package名>.png`に置き、各`icon/__init__.py`が
`MENU: Final[Path]`で実配置から絶対pathを解決します。パス解決は共通の
`bd_util.py.path.resolve_relative_path(__file__, 画像名)`を利用し、util側へ集約します。
メニュー定義は登録時にこの定数を読み込み、utilの`register_menu_item(icon_path=...)`へ
渡します。`import bd_tools`だけではutilを読み込みませんが、画像定数の取得にはutilを
利用します。親packageは`icon`と軽量な型定義を読み込み、
既存の公開関数・Window classは`__getattr__()`で初回の属性参照時に読み込みます。
型検査時は公開型を明示し、`__all__`と`__dir__()`で公開入口を保持します。
画像pathや属性候補の取得ではUI本体をimportしません。画像の読込み検証とMayaへの設定はutilが
担当し、画像不備では警告して画像なしの項目を登録します。
toolsのreload前には所有項目を解除し、reload後に新しいcallbackで再登録します。
起動時のdeferred処理だけがutilの共有設定を読み、OFFなら登録をスキップします。
明示的な`install_menu()`と開発reload時の復元は設定の影響を受けません。

各 module が保持する controller の `dispose()` を package の
`register_reload_disposer()` へ登録し、古い UI と callback を残したまま code を
reload しないようにします。

## Public API

利用者や `bd_rig` が直接触る API では次を重視します。

- 明示的な型注釈と `__all__`
- Pylance / Pyright のドットアクセス補完
- 小さく意図が読める入口
- import だけでは scene や UI を変更しないこと
- scene mutation の実行単位と undo 境界が明確であること

公開 API を追加した場合は `tests/typecheck` に contract を追加し、実行時のテストと IDE の
補完品質を別々に確認します。

bdChannelBoxを利用側から開く場合は`bd_tools.bd_channel_box.show()`を使います。
別ツールの実装で必要になる属性列挙や一括編集は、bdChannelBoxのcontrollerを経由せず
utilを直接利用します。画面寸法の定数はtools内部の調整箇所で、保存設定や公開APIではありません。

複数属性への値入力は、toolsのcontrollerが各行の対象と入力値を決め、utilの
`MayaFloatValueEdit` / `MayaFloatOffsetEdit` / `MayaBoolValueEdit` /
`MayaEnumValueEdit` / `MayaStringValueEdit`へまとめます。
`apply_plugs_values()`が全件の事前検証、書込み失敗時の復旧、1回のUndoを所有します。
数値直接入力は各行の表示単位で換算し、「表示ノードの値に揃える」は各属性の
表示ノードの未丸め値を使います。
上下操作は操作元Stepによる表示増減量を各数値の現在値へ加え、Slider・bool・enum・stringは互換属性を
操作後の値へ揃えます。Sliderの連続入力は`MayaEditSession`で1回のUndoへまとめます。
Step欄の入力はtoolsが選択を解釈し、同欄を持つ各Viewへ同じ表示stepを設定します。
属性pathと数値種別ごとの非初期値はutilの`FloatStepProfile`へ集約し、既存の
preferences用`UiStateManager`からWindow再生成とMaya再起動をまたいで保存します。
各Viewの増減方式は維持し、属性path・型ごとのProfileを対象ごとに更新します。
Step欄のない選択行は除外し、sceneとMaya Undo履歴は変更しません。

Copy / Pasteでは、メニュー構成、基準node、選択属性、表示状態による貼付けpathの選別を
toolsが所有します。型・単位・enum定義を保持する`MayaScalarValueTransfer`、値のsnapshot、
JSONのversion・size検証、OS clipboard、全対象の事前検証と一括適用はutilが所有します。
別ツールで値転送が必要な場合も、bdChannelBoxのcontrollerを再利用せずutilの公開APIを使います。

一覧を参照するコードは`widget.table_view`を使います。`scroll_area`は同じ
`ChannelTableView`への参照として残しますが、`QScrollArea.widget()`の代わりに`viewport()`を使います。
`row_widgets`と既存Viewの`editor`は維持します。`ChannelRow` / `ChannelStateRow`の
`target_names`は対応ノード名を保持し、選択属性のメニューが操作先を再解決するために使います。

enumも同じ責務分担です。実定義の取得と比較用の値型はutilの`read_enum_definition()`と
`EnumDefinition`を使用します。controllerが代表と定義の一致する対象を選び、
`MayaEnumPlugsBinding`へ渡します。混在・Undo・定義変更時の入力停止はutil、
除外理由の表示と、ノードの選択し直しによる対象の再選別はtoolsが担当します。

表示・ロック状態はutilの`MayaChannelStateBinding`を使用します。状態の読取り、
複数対象の混在と操作可否、外部変更の監視、表示・ロックごとの一括操作、
Maya標準Undoへの登録はutilが所有します。値入力不可でもロック解除や表示変更を
操作できるよう、値用Bindingと状態用Bindingの可否判定を分離します。
toolsは値編集／表示・ロックのモード、基準属性の表示状態による5種類の標準フィルターと
ノード型別のカスタムフィルター、モードごとの選択保持、非表示属性を含む編集対象の選別、
状態RadioButton・ロックCheckBox、名前の省略表示と共通列幅を所有します。
フィルターは両モードへ適用し、後続ノードとの対応付けは表示状態で除外しません。
表示フラグの通知時はQtの次のイベントで再評価し、状態の一括操作中にBindingを破棄しません。
状態編集ではenum値を変更しないため、enum定義の一致による対象除外を行いません。
この判定は値編集モードの状態メニューにも適用します。複数選択した属性の状態操作は、
各行の基準に対する制約を判定したうえで操作可能なplugを集約し、utilの状態Bindingへ渡します。
標準Channel Boxの選択状態や`channelBoxCommand`には依存しません。

なぞり操作の座標・通過順・中断判定はutilの`RadioButtonSweep`と`CheckBoxSweep`の
内部共通処理、一操作のUndo管理は`MayaEditSession`が担当します。
チェックボックスは押下時に適用値を固定し、登録した入力先へ明示的に渡します。
toolsはラジオボタンとlockの対象登録、lock入力とBindingの接続、共有セッションを
各行へ渡す接続を所有します。なぞり中はフィルターによる行の再構築だけを保留し、
選択・scene・属性構成の変更やWindow終了では操作を終了して既存の破棄処理へ進みます。
