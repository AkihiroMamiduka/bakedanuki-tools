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

- [x] 最初のユーザー課題と操作フローを決める（bdChannelBoxの値入力）
- [x] `bd_util` の Window controller を使った UI を実装する
- [x] Maya 操作と undo 境界を実装する
- [x] unit / Maya / type contract を追加する
- [x] reload と callback 破棄を Maya 本体で確認する
- [x] 属性別step設定と、値・step／sliderの整列・単位非表示
- [x] boolのCheckBox化、コンパクトな幅、右クリック操作
- [x] util基盤によるドッキング、floating、配置reset
- [x] 利用者による動作確認と初回開発の完了（2026-09-16）
- [x] enumのComboBox入力、定義一致による一括編集、未定義値の表示（2026-09-17）
- [x] 値編集／表示・ロックのモード切替、非表示属性の復帰、状態の一括操作
- [x] transform・jointの指定32属性とdrawOverride配下の優先表示（2026-09-18）
- [x] 両モードの5種類の表示フィルター、必要時だけのスクロールバー表示
- [x] 表示状態とlockのなぞり操作、操作単位のUndo／Redo
- [x] 優先順をconfigへ分離し、visibility・translate・rotate・scaleを先頭へ配置
- [x] bdChannelBoxへの名称統一、公開入口とドキュメントの整備
- [x] 値同期と選択切替の高速化、既存操作の回帰確認
- [x] 拡張後の利用者確認と今回の開発の完了（2026-09-19）

### bdChannelBoxの拡張候補

現在のbool・float・enumの値入力と表示・ロック操作は、上記範囲が対象です。
追加必須の機能はなく、新たな利用上の要望が生じた場合に開発を再開します。
以下は未着手の任意候補であり、今回の完了条件や実装予定ではありません。

| 候補 | 着手を検討する状況 | 設計時に確認する点 |
| --- | --- | --- |
| 属性名による検索 | 実装済みの表示状態フィルターでも目的の行を探しにくい | 基準ノードと編集対象の決定を維持し、既存の5種類のフィルターとの組合せを決める |
| step設定の永続化 | Windowを閉じるたびに同じstepを設定し直している | utilの保存基盤を使い、属性path・型・単位、初期値との優先順位、reset時の扱いを決める。sceneへは保存しない |

キー付き属性の入力やSlider操作範囲のカスタマイズも、用途が具体化したときに別途検討します。
アニメーションの編集を追加する場合は、キー・レイヤー・Undoの仕様を先に定義します。

### 保守上の継続課題

- 検証用Maya 2025の終了待ちタイムアウトを調査する。直近の操作39工程の成功と正常終了は区別する。
  詳細と再現手順は[Testing](testing.md#bdchannelboxのmaya本体検証)を参照する。
- 大量の選択ノードや属性で負荷が問題になった場合は、まず既存runnerで構築・入力・選択切替を計測する。
  属性検索とstep欄の初期化は改善済み。追加のキャッシュ・行再利用・監視共有は実測に基づいて検討する。
  [維持する仕様](bd_channel_box.md#性能改善を続ける場合)を確認し、無効化や解放の複雑さも評価する。

## Phase 3: Tool Collection Conventions

次のツールを追加するときに、bdChannelBoxの実装を参考にして共通規約を整えます。
完成したツールの仕様と責務分担は[bdChannelBox](bd_channel_box.md)を参照します。

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
