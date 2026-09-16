# bakedanuki-tools

`bakedanuki-tools` は、UI から Autodesk Maya を操作し、制作作業を支援する
ユーザー向けツール群です。

再利用可能な Maya 操作や UI 基盤は
[`bakedanuki-util`](https://github.com/AkihiroMamiduka/bakedanuki-util) で管理し、
このリポジトリには各ツールの UI、ユースケース、Maya 操作の組み立てを配置します。

現在は **v0.1.0 / pre-1.0.0 の初期開発段階**です。公開 API は今後変更される
可能性があります。

## Status

- Target: Maya 2025 以降 / Python 3.11.4 以降
- Development verification: Windows / Maya 2025 / 2026 / 2027
- Runtime dependency: `bakedanuki-util`
- Distribution: Maya Module
- Python package: `bd_tools`
- License: MIT

## Repository Relationships

現在の依存方向です。

```text
bakedanuki-tools -> bakedanuki-util
bakedanuki-rig   -> bakedanuki-util
```

将来、rig UI から tools の公開 UI を呼び出す場合は、次の依存を追加できます。

```text
bakedanuki-rig -> bakedanuki-tools -> bakedanuki-util
```

`bakedanuki-tools` から `bakedanuki-rig` は参照しません。この一方向性により、tools を
リグシステムなしでも独立して利用できます。

## Development Layout

開発時は、次のようにリポジトリを sibling として配置します。

```text
bakedanuki_dev/
  bakedanuki-tools/
  bakedanuki-util/
  bakedanuki-rig/   # 必要な場合
```

通常起動する Maya では、各 Maya バージョンの `Maya.env` に tools と util の module
path を登録してください。

```env
MAYA_MODULE_PATH=D:/develop/bakedanuki_dev/bakedanuki-tools/bakedanuki/modules;D:/develop/bakedanuki_dev/bakedanuki-util/bakedanuki/modules;
```

リポジトリ内のテスト、型検査、開発用 Maya launcher は sibling の
`bakedanuki-util` を自動検出します。これらのスクリプトは `Maya.env` を変更しません。

## Initial Setup

Black 用環境と、pytest / Pyright 用の開発ツールを準備します。

```powershell
.\scripts\setup-format.cmd
.\scripts\setup-dev.cmd
```

## Channel Editor

Maya の Script Editor で実行します。

```python
from bd_tools import channel_editor

channel_editor.show()
```

初回はMaya右側へドッキングし、タイトル部分のドラッグでfloatingやタブ配置へ変更できます。
終了は `channel_editor.close()`、配置のリセットと再表示は `channel_editor.reset_layout()` です。

選択リストの先頭ノードを基準に、Channel Box に表示する bool・float 系属性の
入力欄を表示します。同名・同種の属性を持つ選択ノードへ、編集時だけ値を一括反映します。
選択や表示更新では値を揃えません。両側に hard min/max がある属性は Slider 付き、
bool は属性名のすぐ右に置く CheckBox です。キー付き・入力接続済み・ロックされた属性は表示専用です。

対応する `bakedanuki-util` の複数属性 Binding と属性列挙 API が必要です。
本変更の tools と util を組み合わせて配置してください。
詳細は [Channel Editor](bakedanuki/bakedanuki-tools/docs/channel_editor.md) を参照してください。

## Verification

日常的な確認です。

```powershell
.\scripts\format.cmd -Check
.\scripts\typecheck.cmd
.\scripts\test-unit.cmd
.\scripts\test-maya2025.cmd
```

整形、型検査、unit test はまとめて実行できます。

```powershell
.\scripts\check.cmd
```

Maya runtime test も含める場合です。

```powershell
.\scripts\check.cmd -IncludeMaya
.\scripts\test-maya-all.cmd
```

## Development Maya Launcher

個人の `Maya.env` を使わずに、tools と util を一時的に有効化して Maya を起動できます。

```powershell
.\scripts\launch-maya2025.cmd
.\scripts\launch-maya2026.cmd
.\scripts\launch-maya2027.cmd
```

環境変数の変更は、起動した Maya process のみに適用されます。

## Distribution

配布時は `bakedanuki-tools` と `bakedanuki-util` の `bakedanuki/` フォルダを、同じ
配布ルートへ重ねて配置します。rig を同梱する場合も同様です。

```text
bakedanuki/
  installer.py
  launchers/
  modules/
    bd_tools.mod
    bd_util.mod
    bd_rig.mod       # rigを同梱する場合
  bakedanuki-tools/
  bakedanuki-util/
  bakedanuki-rig/    # rigを同梱する場合
```

共通の `installer.py` は、この `bakedanuki/modules` を `MAYA_MODULE_PATH` に登録します。
tools リポジトリでは installer を複製しません。

## Documentation

- [Development](bakedanuki/bakedanuki-tools/docs/development.md)
- [Architecture](bakedanuki/bakedanuki-tools/docs/architecture.md)
- [Testing](bakedanuki/bakedanuki-tools/docs/testing.md)
- [Reloading](bakedanuki/bakedanuki-tools/docs/reloading.md)
- [Roadmap](bakedanuki/bakedanuki-tools/docs/roadmap.md)
- [AI Agent Guide](AGENTS.md)

## License

MIT License
