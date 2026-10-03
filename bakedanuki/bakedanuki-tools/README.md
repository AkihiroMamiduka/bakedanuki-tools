# bakedanuki-tools

`bakedanuki-tools` は、UI から Autodesk Maya を操作するユーザー向けツール群です。

現在は **v0.1.0 / pre-1.0.0 の初期開発段階**です。Maya 2025 以降を対象とし、
Python package 名は `bd_tools` です。

## Requirements

- Windows
- Autodesk Maya 2025 / 2026 / 2027
- `bakedanuki-util`

## Installation

配布パッケージでは、`bakedanuki-util` と同じ `bakedanuki/` ルートに配置します。

```text
bakedanuki/
  installer.py
  modules/
    bd_tools.mod
    bd_util.mod
  bakedanuki-tools/
    python/
      bd_tools/
    scripts/
      userSetup.py
  bakedanuki-util/
    python/
      bd_util/
```

共通の `installer.py` を Maya の viewport へドラッグ&ドロップするか、
`bakedanuki/modules` を `MAYA_MODULE_PATH` へ追加してください。

interactive Mayaの起動後、上部メニューバーの`bakedanuki > tools > bdChannelBox`から
ツールを開けます。各Module内の`userSetup.py`がメニュー登録を予約します。
この起動処理はユーザー自身の`userSetup.py`やsceneを書き換えません。
`bakedanuki`内の「Maya 起動時に bakedanuki メニューを表示」をOFFにすると、次回起動からメニューの
自動登録をスキップします。現在のメニューはそのセッション中に残ります。
再び表示するには共通の`installer.py`をviewportへドロップしてONへ戻し、Mayaを
再起動してください。設定は使用中のMayaバージョンごとに保存されます。
共通installerは初回導入やパス変更時に、確認後にMaya.envの`MAYA_MODULE_PATH`を
更新します。batchでは
メニューを登録しません。起動スクリプトを無効にした環境では、Script Editorから
次を実行できます。

```python
import bd_tools

bd_tools.install_menu()
```

`install_menu()`はUI未初期化時に`False`を返します。ツールを直接開く場合は
`bd_tools.bd_channel_box.show()`も使用できます。メニュー基盤を利用するには、
対応する`bakedanuki-util`を同時に配置してください。
自動表示をOFFにした状態でも、`install_menu()`による明示的な登録は使用できます。

## Import Check

Maya の Script Editor で次を実行します。

```python
import bd_tools
import bd_util

print(bd_tools.__version__)
print(bd_tools.__file__)
```

## Development Reload

tools の Python module を開発中に再読込できます。

```python
import bd_tools

bd_tools.reload_package()
```

同時に変更した `bd_util` も先に再読込する場合です。

```python
bd_tools.reload_package(reload_util=True)
```

callback や UI など Maya 外部状態の終了処理については
[Reloading](docs/reloading.md) を参照してください。

## Documentation

- [Development](docs/development.md)
- [Architecture](docs/architecture.md)
- [Testing](docs/testing.md)
- [Reloading](docs/reloading.md)
- [Roadmap](docs/roadmap.md)

## License

MIT License
