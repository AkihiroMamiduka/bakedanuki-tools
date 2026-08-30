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
  bakedanuki-util/
    python/
      bd_util/
```

共通の `installer.py` を Maya の viewport へドラッグ&ドロップするか、
`bakedanuki/modules` を `MAYA_MODULE_PATH` へ追加してください。

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
