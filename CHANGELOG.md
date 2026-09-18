# Changelog

このプロジェクトの主な変更を記録します。

形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) を参考にし、
バージョンは [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

### Changed

- ツール名をbdChannelBox、公開packageを`bd_tools.bd_channel_box`へ統一。
  Windowタイトル、workspaceControl ID、復元入口、設定path、テスト、ドキュメントも
  新名称に揃える。pre-1.0.0の未公開ツールのため互換用の入口は設けない。
- bdChannelBoxの先頭10属性をvisibility、translate X/Y/Z、rotate X/Y/Z、
  scale X/Y/Zへ変更し、残りの相対順を維持。
  優先順を`bd_tools.bd_channel_box.config.ATTRIBUTE_PRIORITY_PATHS`へ分離し、
  `config.py`のtupleを編集してtoolsを再読込みすると変更できるようにした。
  両モード・全フィルターへ共通適用し、既存呼出し・scene・保存設定の移行は不要。
- bdChannelBoxの`lock`へ左ドラッグでのなぞり操作を追加。
  開始時がOFF・混在ならロック、ONなら解除へ通過行を揃え、往復でも再反転しない。
  ラジオボタンと操作対象を分離し、一操作を一回のUndo／Redoにまとめる。
  対応する`bakedanuki-util`への更新が必要。既存の呼出し・scene・保存設定の移行は不要。
- bdChannelBoxの`key / ch / hide`へ左ドラッグでのなぞり選択を追加。
  通過した表示中の有効なボタンを選択し、一操作を一回のUndo／Redoにまとめる。
  なぞり中のフィルター再構築は終了まで保留し、選択・scene・属性構成の変更では終了する。
  ラジオボタン操作中の`lock`変更と自動スクロールは対象外。対応する`bakedanuki-util`への更新が必要。
  既存の呼出し・scene・保存設定の移行は不要。
- bdChannelBoxの表示状態入力を`key / ch / hide`のラジオボタンへ変更し、
  ロックの表記を`lock`へ変更。設定モードの操作欄を200 pxに広げる。
  混在時は3つとも未選択にし、既存の印とtooltipで示す。一括操作・Undo／Redoは維持する。
  Viewを参照するコードは`display_combo`から`display_buttons`へ移行し、
  状態名（`"keyable"`、`"channel_box"`、`"hidden"`）をキーにしたボタンの
  `isChecked()`／`click()`を使う。
  値編集は156 pxを維持し、scene・保存設定の移行やutilの追加変更は不要。
- bdChannelBox上部のComboBoxへ`Mode:`と`Attribute Filter:`のラベルを追加。
  ラベルは右揃えの共通列へ配置し、選択欄の左端と幅を揃える。
  操作・scene・保存設定の変更や移行は不要。
- bdChannelBoxの属性表示を、visibilityからtransform・jointの指定32属性、
  drawOverride配下、その他の順へ変更。存在し、フィルターに一致する属性だけを
  両モード共通の順で表示し、drawOverride内はoverrideEnabledを先頭にする。
  残りのdrawOverride内とその他の属性は元の相対順を維持する。
  tools内の表示方針だけを変更し、sceneの属性順・値・状態は変更しない。
  scene・保存設定の移行やutilの追加変更は不要。
- bdChannelBoxの値同期を高速化したutilに対応。bool・float・enumの一括Bindingは
  変更に関係する属性だけを再同期し、複数選択時も通知nodeの対象だけを照合する。
  「全て」表示時の無関係な行の再読取りを抑える。UIの操作方法・公開APIは変更しない。
  利用には同時変更の`bakedanuki-util`を更新すること。scene・保存設定の移行は不要。
- bdChannelBoxの縦スクロールバーを必要時だけ表示する。モードやフィルターにより
  名前列の幅・入力列の位置が変わることを許容し、入力グループの156 pxは維持する。
  scene・保存設定の移行は不要。
- bdChannelBoxのbool入力をutilの`BoolCheckBox`へ変更し、属性名のすぐ右へ左詰めにする。
  行の`editor`を直接操作するコードは`BoolComboBox`から`BoolCheckBox`へ型判定を移行し、
  `currentText()` / `setCurrentIndex()`を`isChecked()` / `setChecked()`へ置き換える。
  初期Window幅を420から320 px、最小幅を360から280 pxへ縮小し、
  `ui.py`の`_INITIAL_WIDTH`・`_MINIMUM_WIDTH`と`widget.py`の
  `_NAME_FIELD_MINIMUM_WIDTH`で属性名側の余白を調整できるようにする。
  sceneの移行は不要。保存配置を縮める場合はパネル幅の変更か`reset_layout()`を使用する。
- bdChannelBoxのfloat値欄を110 pxから90 pxへ縮小し、step欄・Sliderを共通の
  60 pxに固定する。Slider行はutilの`layout_order="value_slider"`を使って
  `[Value][Slider]`へ変更し、通常float行の`[Value][Step]`と値欄の位置を揃える。
  数値入力グループを156 pxで右寄せし、画面を広げても数値入力後方に余白を作らない。
  値、scene、設定ファイルの移行は不要。
- bdChannelBoxの値欄・step欄の単位文字（cm / degなど）を非表示にする。
  Slider付きの値欄にも適用する。表示単位への数値換算とstepの扱いは維持し、
  scene・設定ファイルの移行は不要。
- bdChannelBoxをutilの `MayaDockableWindowController` に移行し、Maya右側へのドッキング、
  タブ化、floating、workspaceControlによる配置復元へ対応。
  `show()` の戻り値は同名の `ChannelBoxWindow` だが、基底は `QDialog` から
  `MayaDockableWindow` へ変更する。`exec()` / `reject()` は使用せず、表示は `show()`、
  終了はタイトルバーまたは新しい `bd_channel_box.close()` / `dispose()` へ移行する。
  Escapeではパネル全体を閉じない。closeで入力・callbackを破棄し、再表示で作り直す。
  固定IDは `bdChannelBoxWindowWorkspaceControl`、復元入口は
  `bd_tools.bd_channel_box.ui.restore`。`reset_layout()` はutilの統合reset APIを利用する。
  初回は右ドックから開始し、保存したworkspaceControl配置を再利用する。
  sceneの移行は不要。保存配置は明示的な `reset_layout()` で削除できる。
- bdChannelBoxの常設ボタン・件数欄・「基準:」表記を削除し、属性名を右揃えに変更。
  混在は属性名の左の小さな印、対象数と除外理由はtooltipへ集約する。
  属性名の右クリックメニューへ「この値に揃える」「表示を更新」を移し、余白からも更新可能。
  初回Windowサイズを420×360へ縮小する。保存済みの配置とsceneの移行は不要。
  UI部品を直接参照するコードでは `align_button` を `align_action`、`refresh_button` を
  `refresh_action` へ置き換え、操作は `trigger()` で実行する。
  `status_label.toolTip()` は `name_label.toolTip()` へ移行する。
  `widget.refresh()` とBindingによる一括編集APIは引き続き利用できる。

### Added

- bdChannelBoxへ両モード共通の表示フィルターComboBoxを追加。
  全て／keyable + channelbox／keyable／channelbox／hideの5種類を、基準ノードで判定する。
  channelbox単独は非keyableの表示属性を指す。値編集はkeyable + channelbox、
  表示・ロックは全てを初期値とし、モードごとの最終選択をWindow内だけで保持する。
  Hide属性の値入力にも対応し、従来のロック・入力接続による編集制限を維持する。
  絞り込み中の状態変更は全対象への操作完了後に表示へ反映し、Undo／Redoにも追従する。
  `controller.attribute_filter`、`set_attribute_filter()`、`ChannelAttributeFilter`、
  `widget.filter_combo`を追加。scene・保存設定の移行やutilの追加変更は不要。
- bdChannelBoxに「値編集／表示・ロック」の切替を追加。表示・ロックでは非表示の
  対応scalarも列挙し、Keyable／ChannelBox／HideとLock／Unlockを独立して一括操作する。
  混在表示、外部変更、Maya標準Undo／Redoへ対応し、全てフィルターではHideへ変更した行も維持する。
  属性定義によりkeyableとchannelBoxが両方Trueの属性は、Maya標準Undoで復元できないため
  表示変更だけを不可とし、理由をtooltipへ表示する。基準属性なら行の表示変更を停止し、
  後続の対象だけなら除外する。ロック／解除は通常どおり操作でき、自動修正や移行は行わない。
  両モードで右列156 pxを共用し、長い属性名は省略表示とtooltipへ変更する。
  名前欄の幅調整定数は`_NAME_FIELD_MINIMUM_WIDTH`から`_NAME_FIELD_PREFERRED_WIDTH`へ変更する。
  モード切替はscene・Undoを変更せず、Window内のstep設定を維持する。
  utilの`MayaChannelStateBinding`が必要なため、toolsとutilを組み合わせて更新する。
  `controller.rows`へ`ChannelStateRow`、`widget.row_widgets`へ`AttributeStateRowWidget`が
  加わるため、値編集用の`binding`／`editor`を参照する利用コードは`isinstance()`で
  行の型を絞ること。既存scene・保存設定の移行は不要。
- bdChannelBoxのenum入力を追加。utilの`EnumComboBox` / `MayaEnumPlugsBinding`を使用し、
  同じ正式属性path・整数値と項目名の対応を持つ対象へ、明示操作時だけ一括適用する。
  飛び番・未定義値・混在・定義不一致の除外、Undo／Redo、選択肢の終了に対応する。
  対応するutilのenum属性列挙と`read_enum_definition()`が必要なため、両packageを更新する。
  行の`editor`と`ChannelBinding`のunionにenum型が加わる。数値Viewとしてアクセスする
  利用コードは`isinstance()`で型を絞ること。既存scene・保存設定の移行は不要。

- bdChannelBoxのSlider以外のfloat系入力に、utilの `FloatValueStepSpinBox` を採用。
  距離・通常数値はmultiplicative/1、角度はadditive/15、radiusはmultiplicative/0.1とする。
  stepの変更は値やUndo履歴へ影響せず、選択変更やUndo後もWindow内で属性ごとに保持する。
  step欄は名称の接頭辞を省略し、4桁程度を表示できるコンパクトな幅とする。
  行の公開 `editor` 型が `FloatSpinBox` から複合Viewへ変わるため、利用コードでは
  値欄へのアクセスを `editor.spin_box`、刻み幅の変更を `editor.setSingleStep()` へ移行する。
  対応するutilの更新が必要。既存scene・設定ファイルの移行は不要。
- 最初のツール `bd_tools.bd_channel_box` を追加。`show()` で通常Windowを開き、
  選択リストの先頭を基準に bool・float・距離・角度の属性を入力できる。
  `keyable OR channelBox` のscalar属性を表示し、両側hard limit付きfloatにはSliderを使う。
  ユーザーの編集時だけ、同名・同種の編集可能な属性へ一括適用する。
  混在値の表示、明示的な「揃える」、Undo / Redo、選択追従、close / reload時の解放に対応。
  キー付き・入力接続済み・ロックされた属性は表示専用とする。
  利用には同時追加された `bakedanuki-util` の複数属性Binding・inspection APIが必要。
  新規ツールのため既存sceneの移行は不要。配置設定は `bd_channel_box/windows/main` に保存する。
- Maya Module 形式の `bd_tools` パッケージ骨格。
- Black、Pyright、pytest、VS Code の開発環境。
- Maya 2025 / 2026 / 2027 用のテストと開発 launcher。
- module reload 前の終了処理を登録できる reload lifecycle。
- `bakedanuki-util`、`bakedanuki-rig` との依存方向と責務境界。
