# AI Agent Guide

このファイルは、`bakedanuki-tools` で作業する AI エージェント向けの作業仕様書です。
新しい作業を始めるときは、最初にこのファイルを読んでください。

## Project Context

`bakedanuki-tools` は、UI から Autodesk Maya を操作し、制作作業を支援する個人開発の
ツール群です。

`bakedanuki-util` は、このリポジトリから利用する Maya 向け汎用基盤です。特定ツールに
閉じない Maya 操作、値型、Qt facade、Window lifecycle、設定保存などは tools へ
重複実装せず、原則として `bakedanuki-util` 側へ配置してください。

`bakedanuki-rig` は別の利用側 package です。現在 tools と rig は互いに依存しません。
将来 rig UI から tools の公開 UI を呼び出す場合は `bd_rig -> bd_tools` の依存を許容しますが、
`bd_tools -> bd_rig` の逆依存は禁止します。

現在は v1.0.0 未満の初期開発段階です。将来の設計と使いやすさを優先し、必要な
破壊的変更を許容します。公開 API、設定形式、scene 互換性に影響する変更は、移行方法と
ともに `CHANGELOG.md` へ記録してください。

## Repository Layout

- `bakedanuki/bakedanuki-tools/python/bd_tools`
  - Python パッケージ本体です。
- `bakedanuki/bakedanuki-tools/docs`
  - 開発、設計、テスト、リロードのドキュメントです。
- `bakedanuki/modules/bd_tools.mod`
  - 配布時に共通 `bakedanuki/modules` へ配置する Maya Module 定義です。
- `tests/unit`
  - Maya runtime に依存しない仕様のテストです。
- `tests/maya`
  - `maya.standalone` を初期化する Maya runtime test です。
- `tests/typecheck`
  - Pyright で公開 API の型と IDE 補完を固定する contract です。
- `scripts`
  - Black、Pyright、pytest、Maya launcher の共通入口です。

個別ツールの package 階層は、最初の機能とテストを置く段階で追加してください。空の階層を
設計の代わりに増やしません。

## Development Environment

- OS: Windows
- Maya: Maya 2025 / 2026 / 2027
- Target Python: Maya 2025 bundled Python 3.11.4 以降
- Shell: PowerShell
- Main checkout: `D:\develop\bakedanuki_dev\bakedanuki-tools`
- Util checkout: `D:\develop\bakedanuki_dev\bakedanuki-util`

開発時は2つのリポジトリを sibling として配置します。`-UtilRoot`、
`BAKEDANUKI_UTIL_ROOT`、sibling の `../bakedanuki-util` の順で util を解決します。

通常起動する Maya の環境は、ユーザーが各バージョンの `Maya.env` へ tools と util の
module path を手動設定します。リポジトリ内のスクリプトは `Maya.env` を変更しません。

配布時は tools と util の `bakedanuki/` を共通ルートへ重ねます。rig を同梱する場合も
同じルートへ重ねます。共通の `installer.py`、launchers、`modules` フォルダは配布ルート側の
責務です。tools リポジトリへ installer を複製しないでください。

## Development Commands

初期セットアップです。

```powershell
.\scripts\setup-format.cmd
.\scripts\setup-dev.cmd
```

日常的な検証です。

```powershell
.\scripts\format.cmd -Check
.\scripts\typecheck.cmd
.\scripts\test-unit.cmd
.\scripts\test-maya2025.cmd
```

まとめて実行する場合です。

```powershell
.\scripts\check.cmd
.\scripts\check.cmd -IncludeMaya
.\scripts\test-maya-all.cmd
```

Maya を一時的な開発環境で起動する場合です。

```powershell
.\scripts\launch-maya2025.cmd
.\scripts\launch-maya2026.cmd
.\scripts\launch-maya2027.cmd
```

## Verification Policy

- Markdown / docs のみ
  - `git diff --check -- <changed-files>` を実行します。
- Maya に依存しない Python 変更
  - targeted unit test、Pyright、Black check を実行します。
- Maya 操作や UI controller の変更
  - targeted Maya test、Pyright、Black check を実行します。
- reload lifecycle、共有 public API、設定形式の変更
  - unit test と関連 Maya test の両方を実行します。
- 対応 Maya version、配布構成、Qt / Maya API 互換性に関わる変更
  - Maya 2025 / 2026 / 2027 の全 runtime test を実行します。
- workspaceControl、再起動復元、実画面配置に関わる変更
  - 自動テストに加えて対象 Maya 本体で操作確認します。

## Architecture Boundaries

依存方向を次のように保ちます。

```text
bd_rig (将来・任意) -> bd_tools -> bd_util -> Maya API / Qt
bd_rig             -> bd_util
```

- `bd_util` は `bd_tools` と `bd_rig` を import しません。
- `bd_tools` は `bd_rig` を import しません。
- 個別ツールは UI、ユーザー操作、ユースケース、汎用 API の組み立てを所有します。
- 汎用的な Maya 操作、値型、UI 基盤は `bakedanuki-util` の責務です。
- rig 固有のデータモデルや builder は `bakedanuki-rig` の責務です。
- util に変更が必要な場合は、util 側の `AGENTS.md` を読んでから作業してください。
- rig に変更が必要な場合は、rig 側の `AGENTS.md` を読んでから作業してください。

個別ツール間の暗黙の依存を避けます。共有する価値のある処理は、責務に応じて
`bd_tools` 内の明示的な共有層か `bd_util` へ移します。

## UI Policy

- Qt binding は直接 import せず、`bd_util.ui.qt` を使用します。
- 通常 Window は `MayaWindowController`、workspaceControl は
  `MayaDockableWindowController` を基本とします。
- module ごとに controller を1つ保持し、重複 Window を作りません。
- dockable UI の `control_id` と restore 用 module / function は公開後も維持します。
- 永続化する `settings_path` はツール名を先頭にした固定 path にします。
- Maya callback は Window lifecycle に結び付けて確実に解除します。
- UI 配置の reset は `bd_util.maya.ui` の統合 API を利用します。
- UI module は import 時に Window を自動表示せず、明示的な `show()` を公開します。

UI lifecycle や状態保存の仕様は、`bakedanuki-util` の
`bakedanuki/bakedanuki-util/docs/ui/README.md` を参照してください。

## Coding Policy

- package 内 import は、import 元を基準にした相対 import を使います。
- 公開 API は `__all__` と明示的な型注釈を整備します。
- `Any` や広範囲な `# pyright: ignore` で型問題を隠しません。
- 動的な Maya / Qt API 境界では、`cast()`、Protocol、局所 adapter で型の伝播を止めます。
- 公開 API の戻り値型とドットアクセス補完を API 品質として扱います。
- 抽象処理や未実装処理は暗黙の `None` を返さず、明示的な例外を送出します。
- Python は Black で整形し、79文字幅を使用します。

## Comment Policy

- source code のコメントと docstring は日本語で記述します。
- Python の関数とメソッドには、public / private、特殊メソッド、テスト用 helper を
  問わず、日本語の docstring を必ず記述します。
- 複数段階の処理では、処理のまとまりごとに目的を示す短い1行コメントを置きます。
- 1文だけの1行コメントでは、文末の「。」を付けません。
- 自明な代入やコードを読み上げるだけの冗長なコメントは追加しません。
- `.ps1` は日本語コメントを Windows PowerShell 5.1 でも読めるよう、UTF-8 BOM を
  維持します。
- 処理を変更した場合は、対応するコメントと docstring も同時に更新します。

## IDE Completion And Type Contracts

`pyrightconfig.json` は `bd_tools` 実装本体と `tests` の両方を strict mode で検査します。

公開 API を追加・変更した場合は、必要に応じて `tests/typecheck` に
`typing.assert_type()` を追加してください。runtime test が通るだけでなく、利用者が
Pylance / Pyright から具体的な型を辿れることを確認します。

`bd_tools/py.typed` は配布時にも必ず含めてください。

## Reload Policy

Maya callback、scriptJob、UI、workspaceControl、その他外部状態を作る module は、破棄用
callback を `register_reload_disposer()` へ登録してください。

tools だけを変更した場合:

```python
import bd_tools

bd_tools.reload_package()
```

util も変更した場合:

```python
bd_tools.reload_package(reload_util=True)
```

終了処理は tools の状態を破棄してから実行され、package は util → tools の順で reload
されます。終了処理の失敗を握りつぶさないでください。

将来 rig から tools を利用する場合、rig 側の reload は外部状態を破棄してから
util → tools → rig の依存順に行う設計へ拡張してください。

## Git And Editing Policy

- 作業前に `git status --short` を確認します。
- ユーザーの既存変更を勝手に戻しません。
- ユーザーの許可なく commit / push しません。
- `git reset --hard` や `git checkout -- <file>` を使用しません。
- 手作業の編集には `apply_patch` を使用します。
- 無関係な整形やリファクタを避けます。
- ユーザーとのやり取りは日本語を基本にします。

## Documentation Policy

仕様や設計判断を追加・変更した場合は、コードと同じ作業で docs を更新してください。

- `README.md`: 初見向けの入口、セットアップ、代表コマンド。
- `docs/architecture.md`: 責務境界、依存方向、UI 構成。
- `docs/development.md`: ローカル開発環境。
- `docs/testing.md`: 検証レイヤーと実行方法。
- `docs/reloading.md`: reload と外部状態の破棄。
- `docs/roadmap.md`: 未着手の段階的な計画。
- `CHANGELOG.md`: 利用者、設定、scene へ影響する変更。

## When In Doubt

次の優先順位で判断してください。

1. ユーザーの直近の指示
2. この `AGENTS.md`
3. 現行 docs とテスト
4. `bakedanuki-util` の UI 基盤と既存コード
5. Maya / OpenMaya / Qt の実挙動

Maya API、workspaceControl、undo、scene 保存時の挙動を推測で決めず、必要なら対象 Maya
本体または `mayapy` で確認してください。
