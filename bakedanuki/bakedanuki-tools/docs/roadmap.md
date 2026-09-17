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
- [x] 属性別step設定と、値・step／sliderの整列・単位非表示
- [x] boolのCheckBox化、コンパクトな幅、右クリック操作
- [x] util基盤によるドッキング、floating、配置reset
- [x] 利用者による動作確認と初回開発の完了（2026-09-16）
- [x] enumのComboBox入力、定義一致による一括編集、未定義値の表示（2026-09-17）

### Channel Editorの拡張候補

今回のbool・float値入力ツールは、上記範囲で完了です。
以下は未着手の任意候補であり、今回の完了条件や実装予定ではありません。

| 候補 | 着手を検討する状況 | 設計時に確認する点 |
| --- | --- | --- |
| 属性名検索・表示フィルター | 属性数が多く、目的の行を探しにくい | 基準ノードと編集対象の決定は維持し、表示の絞込みと値の書込みを分離する |
| step設定の永続化 | Windowを閉じるたびに同じstepを設定し直している | utilの保存基盤を使い、属性path・型・単位、初期値との優先順位、reset時の扱いを決める。sceneへは保存しない |

キー付き属性の入力やSlider操作範囲のカスタマイズも、用途が具体化したときに別途検討します。
アニメーションの編集を追加する場合は、キー・レイヤー・Undoの仕様を先に定義します。

### 保守上の継続課題

- 検証用Maya 2025の終了待ちタイムアウトを調査する。操作24工程の成功と正常終了は区別する。
  詳細と再現手順は[Testing](testing.md#channel-editorのmaya本体検証)を参照する。
- 大量の選択ノードや属性で負荷が問題になった場合は、まず既存runnerで構築・入力・選択切替を計測する。
  node callbackが対象数・属性数に応じて増えるため、必要ならutil側の監視共有を検討する。

## Phase 3: Tool Collection Conventions

次のツールを追加するときに、Channel Editorの実装を参考にして共通規約を整えます。
完成したツールの仕様と責務分担は[Channel Editor](channel_editor.md)を参照します。

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
