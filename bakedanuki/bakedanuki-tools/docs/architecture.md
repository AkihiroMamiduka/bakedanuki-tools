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

最初の実装は `bd_tools.channel_editor` です。`ui.py` がWindow、`widget.py` が入力行、
`controller.py` が選択と対応属性を組み立てます。汎用の属性列挙と一括編集はutilへ配置します。
値とstepの複合Viewもutilへ配置し、属性別の初期stepとWindow内での設定保持は
Channel Editorが所有します。step設定はsceneの値・Undo履歴へ含めません。
属性名の整列、混在の印、対象情報のtooltip、更新・揃えるための右クリックメニューも
Channel Editorが所有し、値欄のQt標準編集メニューとは独立して提供します。
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
