# Testing

検証は役割ごとに3層へ分けます。

## Unit Tests

`tests/unit` は Maya standalone を初期化せず、package metadata、純粋な処理、reload
lifecycle などを検証します。

```powershell
.\scripts\test-unit.cmd
```

実行 interpreter は Maya の `mayapy` ですが、テスト自体は Maya scene を必要としません。

## Maya Runtime Tests

`tests/maya` は session 開始時に `maya.standalone` を初期化し、Maya API、`bd_tools`、
`bd_util` が同じ環境で利用できることを検証します。

```powershell
.\scripts\test-maya2025.cmd
.\scripts\test-maya2026.cmd
.\scripts\test-maya2027.cmd
.\scripts\test-maya-all.cmd
```

scene 操作、undo、Maya callback、Maya UI adapter を使う機能はこの層にテストを追加します。
workspaceControl の実表示や Maya 再起動後の復元は `mayapy` だけでは完結しないため、対象
Maya 本体でも操作確認します。

## Type Contracts

`tests/typecheck` は実行用 pytest ではなく、公開 API の戻り値型と IDE 補完を Pyright で
固定する contract です。

```powershell
.\scripts\typecheck.cmd
```

`pyrightconfig.json` は package 本体と tests を strict mode で検査し、Maya stub は sibling
の `bakedanuki-util/typings` を利用します。

## Formatting And Combined Check

```powershell
.\scripts\format.cmd -Check
.\scripts\check.cmd
.\scripts\check.cmd -IncludeMaya
```

通常の `check.cmd` は Black、Pyright、unit test を実行します。`-IncludeMaya` を指定すると
選択した Maya version の runtime test も実行します。

## Test Placement

- Maya を import しないロジックと lifecycle: `tests/unit`
- Maya scene、OpenMaya、Qt / Maya UI adapter: `tests/maya`
- 公開 API の型と補完: `tests/typecheck`

不具合修正では、可能な限り最初に再現テストを追加します。個別ツールの UI test は、その
ツール package と対応が分かる階層へ配置します。
