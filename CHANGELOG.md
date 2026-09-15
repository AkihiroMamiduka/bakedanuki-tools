# Changelog

このプロジェクトの主な変更を記録します。

形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) を参考にし、
バージョンは [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

### Changed

- Channel Editorをutilの `MayaDockableWindowController` に移行し、Maya右側へのドッキング、
  タブ化、floating、workspaceControlによる配置復元へ対応。
  `show()` の戻り値は同名の `ChannelEditorWindow` だが、基底は `QDialog` から
  `MayaDockableWindow` へ変更する。`exec()` / `reject()` は使用せず、表示は `show()`、
  終了はタイトルバーまたは新しい `channel_editor.close()` / `dispose()` へ移行する。
  Escapeではパネル全体を閉じない。closeで入力・callbackを破棄し、再表示で作り直す。
  固定IDは `bdToolsChannelEditorWindowWorkspaceControl`、復元入口は
  `bd_tools.channel_editor.ui.restore`。`reset_layout()` はutilの統合reset APIを利用する。
  旧 `channel_editor/windows/main` の通常Window配置は自動変換せず、最初は右ドックから開始する。
  sceneの移行は不要。旧配置ファイルは明示的な `reset_layout()` で削除できる。
- Channel Editorの常設ボタン・件数欄・「基準:」表記を削除し、属性名を右揃えに変更。
  混在は属性名の左の小さな印、対象数と除外理由はtooltipへ集約する。
  属性名の右クリックメニューへ「この値に揃える」「表示を更新」を移し、余白からも更新可能。
  初回Windowサイズを420×360へ縮小する。保存済みの配置とsceneの移行は不要。
  UI部品を直接参照するコードでは `align_button` を `align_action`、`refresh_button` を
  `refresh_action` へ置き換え、操作は `trigger()` で実行する。
  `status_label.toolTip()` は `name_label.toolTip()` へ移行する。
  `widget.refresh()` とBindingによる一括編集APIは引き続き利用できる。

### Added

- Channel EditorのSlider以外のfloat系入力に、utilの `FloatValueStepSpinBox` を採用。
  距離・通常数値はmultiplicative/1、角度はadditive/15、radiusはmultiplicative/0.1とする。
  stepの変更は値やUndo履歴へ影響せず、選択変更やUndo後もWindow内で属性ごとに保持する。
  step欄は名称の接頭辞を省略し、4桁程度と単位を表示できるコンパクトな幅とする。
  行の公開 `editor` 型が `FloatSpinBox` から複合Viewへ変わるため、利用コードでは
  値欄へのアクセスを `editor.spin_box`、刻み幅の変更を `editor.setSingleStep()` へ移行する。
  対応するutilの更新が必要。既存scene・設定ファイルの移行は不要。
- 最初のツール `bd_tools.channel_editor` を追加。`show()` で通常Windowを開き、
  選択リストの先頭を基準に bool・float・距離・角度の属性を入力できる。
  `keyable OR channelBox` のscalar属性を表示し、両側hard limit付きfloatにはSliderを使う。
  ユーザーの編集時だけ、同名・同種の編集可能な属性へ一括適用する。
  混在値の表示、明示的な「揃える」、Undo / Redo、選択追従、close / reload時の解放に対応。
  キー付き・入力接続済み・ロックされた属性は表示専用とする。
  利用には同時追加された `bakedanuki-util` の複数属性Binding・inspection APIが必要。
  新規ツールのため既存sceneの移行は不要。配置設定は `channel_editor/windows/main` に保存する。
- Maya Module 形式の `bd_tools` パッケージ骨格。
- Black、Pyright、pytest、VS Code の開発環境。
- Maya 2025 / 2026 / 2027 用のテストと開発 launcher。
- module reload 前の終了処理を登録できる reload lifecycle。
- `bakedanuki-util`、`bakedanuki-rig` との依存方向と責務境界。
