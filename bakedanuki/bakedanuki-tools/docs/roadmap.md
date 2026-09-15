# Roadmap

この roadmap は初期開発の方向を示すもので、個別ツールの優先順位が決まった段階で更新します。

## Phase 1: Repository Foundation

- [x] Maya Module 形式の `bd_tools` package
- [x] sibling `bakedanuki-util` を使う開発環境
- [x] Black / Pyright / pytest
- [x] Maya 2025 / 2026 / 2027 の launcher と runtime test
- [x] UI / callback を安全に破棄する reload lifecycle
- [x] tools / util / rig の責務と依存方向

## Phase 2: First Tool Vertical Slice

- [x] 最初のユーザー課題と操作フローを決める（Channel Editorの値入力）
- [x] `bd_util` の Window controller を使った UI を実装する
- [x] Maya 操作と undo 境界を実装する
- [x] unit / Maya / type contract を追加する
- [x] reload と callback 破棄を Maya 本体で確認する

## Phase 3: Tool Collection Conventions

Channel Editorはutil基盤によるドッキングへ対応しています。
次段階では、キー付き属性の入力、Slider操作範囲の
カスタマイズを実用途に応じて検討します。初版仕様は [Channel Editor](channel_editor.md) を参照します。

- [ ] 個別ツールの命名と package 構成を実例から確定する
- [ ] 共通の tool discovery / launcher が必要か評価する
- [ ] UI 設定 path と workspaceControl ID の命名規約を固定する
- [ ] 複数ツールで本当に共有される処理を適切な層へ抽出する

## Phase 4: Rig Integration

- [ ] rig UI から tools を呼び出す実要件を確認する
- [ ] 必要な場合だけ `bd_rig -> bd_tools` の runtime dependency を追加する
- [ ] util → tools → rig の reload 順と配布 contract を検証する
- [ ] tools 単独利用が維持されていることをテストする

## Phase 5: Distribution

- [ ] 共通 `bakedanuki/` 配布 root へ tools / util を統合する
- [ ] version と changelog の release 手順を決める
- [ ] 対応 Maya version ごとの導入・起動確認を行う
