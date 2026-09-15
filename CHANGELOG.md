# Changelog

このプロジェクトの主な変更を記録します。

形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) を参考にし、
バージョンは [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

### Added

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
