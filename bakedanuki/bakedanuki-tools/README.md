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
  uninstaller.py
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

interactive Mayaの起動後、既定では上部メニューバーの`bakedanuki > tools`から
`bdChannelBox`、「移動・回転をセット（子を維持）」、
「回転をセット（姿勢を維持）」を開けます。各Module内の`userSetup.py`が
メニュー登録を予約します。
`bakedanuki`全体と`tools`は、メニュー先頭の点線から独立Windowへ切り離せます。
切り離し側からも同じツールを起動でき、起動時表示のチェックも元メニューと同期します。
reloadで元メニューを作り直すと切り離しWindowは閉じるため、必要に応じて再度切り離してください。
この起動処理はユーザー自身の`userSetup.py`やsceneを書き換えません。
`prefs/bakedanuki/config.toml`は、初回起動時にコメント例付きで自動作成されます。
`[menu]`の`parent_menu`で既存メニューのUIパスを
指定した場合、`bakedanuki > tools`をそのメニューの下へ配置します。
個人用ファイルの場所、組織・プロジェクト用のTOMLを起動環境から指定する方法、
親メニューを作成する順序は`bakedanuki-util/docs/ui/README.md`の
「起動設定とメニュー配置」を参照してください。
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
各packageの公開`show()`も使用できます。メニュー基盤を利用するには、
対応する`bakedanuki-util`を同時に配置してください。
自動表示をOFFにした状態でも、`install_menu()`による明示的な登録は使用できます。

解除するときは、共通の `uninstaller.py` を Maya のビューポートへドロップし、
対象の `Maya.env` とパスを確認してください。同じ `modules` に同梱した tools・util は
Maya の再起動後にまとめて読み込まれなくなります。配布ファイルと個人設定は残ります。
`uninstall_menu()` は現在のセッションの tools メニュー項目だけを外す API です。

## Shelf とマーキングメニュー

上部メニューの3ツールには、MELからPythonの公開`show()`を呼ぶコマンドを登録しています。
Maya標準の操作でメニューからShelfへ登録すると、コマンドと言語`MEL`が引き継がれます。
標準マーキングメニューのコマンド欄にも、各ツールの次の1行をそのまま使用できます。

bdChannelBox:

```mel
python("import bd_tools.bd_channel_box; bd_tools.bd_channel_box.show()");
```

移動・回転をセット（子を維持）:

```mel
python("import bd_tools.bd_child_compensated_set; bd_tools.bd_child_compensated_set.show()");
```

回転をセット（姿勢を維持）:

```mel
python("import bd_tools.bd_rotation_preserving_pose; bd_tools.bd_rotation_preserving_pose.show()");
```

Shelfへ直接記入する場合は、コマンドの言語を`MEL`に設定します。
各コマンドは毎回importするため、事前のスクリプト実行やメニュー登録は不要です。
toolsとutilがPythonから読み込める環境なら、メニュー自動登録OFFや開発reload後も使用できます。
既に開いているWindowは、公開`show()`の仕様に従って再利用します。

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
