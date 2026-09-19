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

### `bd_tools`

- ユーザーに提供する個別ツール
- UI とユーザー操作
- ツール固有のユースケースと設定
- `bd_util` の汎用 API を組み合わせた Maya scene 操作

### `bd_rig`

- リグ固有の domain model、保存形式、builder
- リグシステム全体の UI
- 必要になった場合の `bd_tools` 公開 UI の呼び出し

ある処理が複数の Maya ツールで再利用でき、ツール固有の意味を持たない場合は
`bd_util` に置きます。単に現時点で2か所から呼ばれるという理由だけで移動せず、責務と
依存方向を先に確認します。

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
操作対象を組み立てます。汎用の属性列挙と一括編集はutilへ配置します。
bdChannelBoxは `MayaDockableWindowController` を使い、固定workspaceControl IDと
`bd_tools.bd_channel_box.ui.restore` を維持します。初回は右ドック、close時は完全破棄とし、
workspace配置の復元・resetはutil、入力と選択監視の終了はtoolsが所有します。
値とstepの複合Viewもutilへ配置し、属性別の初期stepとWindow内での設定保持は
bdChannelBoxが所有します。step設定はsceneの値・Undo履歴へ含めません。
属性名の整列、混在の印、対象情報のtooltip、選択属性を操作する右クリックメニューも
bdChannelBoxが所有し、値欄のQt標準編集メニューとは独立して提供します。
一覧は`QTableView`へ1属性1セルを置き、delegateが既存の属性行Widgetをpersistent editorとして
常時表示します。modelは行と選択を管理し、値は既存Bindingから同期します。
Maya本体がviewportを交換する場合に備え、行の親は構築時に`viewport()`から取得し、
以前のviewportを永続的な参照として保持しません。
既存の数値・Step・Slider・bool・enum・状態Viewを維持し、値をmodelへ複製しません。
複数選択時の数値文字入力・貼付けだけを一時的な文字欄で受け付け、入力開始時の属性集合へ確定します。
既存の数値・Slider・bool・enum Viewは任意入力handlerを使い、選択中の互換属性へ操作を委譲します。
ノードの識別子と属性path・型区分を用いて、同じノードの再表示では残存行の選択を維持し、
対象ノードが変わる場合は選択を解除します。属性選択自体はsceneや設定ファイルへ保存しません。
boolにはutilの`BoolCheckBox`、両側hard limit付きfloatには`FloatSliderSpinBox`、
それ以外のfloatには`FloatValueStepSpinBox`を使います。値欄とSliderの並び順の機能はutil、
Value先行の選択、単位の非表示、固定幅と右寄せはtoolsの表示方針です。
属性行の優先順もtoolsの表示方針です。`bd_channel_box/config.py`の
`ATTRIBUTE_PRIORITY_PATHS`をcontrollerが行構築時に読み、正式pathで照合します。
既定ではvisibility・translate・rotate・scaleの10属性、残りの指定22属性、
drawOverride配下、その他の順に安定ソートしてから行を構築します。
drawOverride内では設定に含めたoverrideEnabledを先頭にし、残りの相対順を維持します。
両モードと全フィルターで共有し、utilの列挙順とscene内の属性順は変更しません。
通常の値変更では並べ替えや行の再構築を行いません。
今後対応型を追加するときも、toolsで汎用BindingやViewを複製せずutilを拡張します。
空の directory は作りません。個別ツール同士の
暗黙の import は避け、共有処理は責務に応じた場所へ抽出します。

## UI Lifecycle

UI 基盤は `bd_util.ui` と `bd_util.maya.ui` を利用します。

- Qt class は `bd_util.ui.qt` 経由で使用する。
- 通常 Window は `MayaWindowController` で重複表示を防ぐ。
- dockable UI は `MayaDockableWindowController` と固定 `control_id` を使用する。
- `settings_path` は `<tool_name>/windows/<window_name>` のように固定する。
- Maya callback は Window owner に関連付ける。
- import 時には UI を表示せず、明示的な `show()` で表示する。
- reload 前には controller、workspaceControl、callback を完全に破棄する。

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
`MayaFloatValueEdit` / `MayaFloatOffsetEdit` / `MayaBoolValueEdit` / `MayaEnumValueEdit`へまとめます。
`apply_plugs_values()`が全件の事前検証、書込み失敗時の復旧、1回のUndoを所有します。
数値直接入力は各行の表示単位で換算し、「この値に揃える」は各行自身の基準ノード値を使います。
上下操作は操作元Stepによる表示増減量を各数値の現在値へ加え、Slider・bool・enumは互換属性を
操作後の値へ揃えます。Sliderの連続入力は`MayaEditSession`で1回のUndoへまとめます。
Step欄の設定はViewごとの操作設定として保持し、一括変更はtoolsの将来候補です。

一覧を参照するコードは`widget.table_view`を使います。`scroll_area`は同じ
`ChannelTableView`への参照として残しますが、`QScrollArea.widget()`の代わりに`viewport()`を使います。
`row_widgets`と既存Viewの`editor`は維持します。`ChannelRow` / `ChannelStateRow`の
`target_names`は対応ノード名を保持し、選択属性のメニューが操作先を再解決するために使います。

enumも同じ責務分担です。実定義の取得と比較用の値型はutilの`read_enum_definition()`と
`EnumDefinition`を使用します。controllerが代表と定義の一致する対象を選び、
`MayaEnumPlugsBinding`へ渡します。混在・Undo・定義変更時の入力停止はutil、
除外理由の表示と「表示を更新」による再選別はtoolsが担当します。

表示・ロック状態はutilの`MayaChannelStateBinding`を使用します。状態の読取り、
複数対象の混在と操作可否、外部変更の監視、表示・ロックごとの一括操作、
Maya標準Undoへの登録はutilが所有します。値入力不可でもロック解除や表示変更を
操作できるよう、値用Bindingと状態用Bindingの可否判定を分離します。
toolsは値編集／表示・ロックのモード、基準属性の表示状態による5種類のフィルターと
モードごとの選択保持、非表示属性を含む編集対象の選別、
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
