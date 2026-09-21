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
- [x] 選択切替の高速化までの利用者確認と開発完了（2026-09-19、下記の複数属性拡張前）

### bdChannelBoxの複数属性拡張（初回実装・検証完了）

複数属性の選択と一括操作の要望に対応し、数値の直接入力と基本メニューを実装しました。
既存のViewを常時利用できる一覧へ移行し、自動テストとMaya 2025本体検証が完了しています。
複数行の同時編集は利用者も動作確認済みです。結果は[検証記録](bd_channel_box.md#検証)を参照します。

- [x] QTableViewとdelegateによる一覧、Ctrl／Shift・名前ドラッグ・値欄の縦ドラッグによる複数選択
- [x] 数値文字入力・貼付けの一括適用、属性ごとの単位換算、全件事前検証・復旧・1回Undo
- [x] 各属性を基準ノード値へ揃える操作、ロック／解除・Keyable／ChannelBox／Hideの選択メニュー
- [x] 選択の保持・解除、入力中断、既存の上下・Step・Slider・bool・enum・なぞり操作の回帰確認
- [x] Maya 2025 / 2026 / 2027のruntime test各144件と、Maya 2025本体の40工程・配置確認
- [x] 利用者による複数行同時編集の動作確認
- [x] 上下操作の共通増減量、Slider・bool・互換enumの複数属性入力と操作単位のUndo
- [x] 選択中でStep欄を持つ属性への同じ表示stepの入力、増減方式とWindow内キャッシュの維持
- [x] 未フォーカス時の値・Step・enumホイール編集を切り替える設定メニューとuser preferencesへの保存
- [x] OSクリップボードへ基準nodeの全対応属性または選択属性をコピー
- [x] コピー元と同じ正式pathへの一括Pasteと、複数コピー値から選択した同pathだけのPaste
- [x] 一項目だけをコピーした場合に、同じ型区分の選択属性と全選択nodeへ値を展開するPaste

### bdChannelBoxの拡張候補

以下は実装済みの複数属性拡張とは別の候補です。
将来の入力拡張を見据えて属性選択と一括書込みの経路を分けています。
操作の意味と対象型を決めてから着手します。

| 候補 | 着手を検討する状況 | 設計時に確認する点 |
| --- | --- | --- |
| 複数source nodeのCopy/Paste | node集合の値を別のnode集合へ移したい | sourceとtargetを同名または明示IDで対応させ、行順・選択順による誤対応を作らない |
| Paste対象の表示状態フィルター | コピー済みのnode状態から一部の表示区分だけを移したい | all／visible／keyable／channelBox／hiddenの指定場所と、Copy時点・Paste時点のどちらで判定するか決める |
| 属性名による検索 | 実装済みの表示状態フィルターでも目的の行を探しにくい | 基準ノードと編集対象の決定を維持し、既存の5種類のフィルターとの組合せを決める |
| step設定の永続化 | Windowを閉じるたびに同じstepを設定し直している | utilの保存基盤を使い、属性path・型・単位、初期値との優先順位、reset時の扱いを決める。sceneへは保存しない |

キー付き属性の入力やSlider操作範囲のカスタマイズも、用途が具体化したときに別途検討します。
行順・属性クリック順だけで異なるpathを対応させる貼り付けは、意図しない属性間の変更を
避けるため候補に含めません。既存の「この値に揃える」は、同じ選択中の即時操作として維持します。
アニメーションの編集を追加する場合は、キー・レイヤー・Undoの仕様を先に定義します。

### 保守上の継続課題

- 検証用Maya 2025の終了待ちタイムアウトは原因未特定。複数属性拡張時は2回連続で正常終了したが、
  背景色調整時の検証で再発した。操作結果とprocessの終了を区別して調査する。
  詳細と手順は[Testing](testing.md#bdchannelboxのmaya本体検証)を参照する。
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
