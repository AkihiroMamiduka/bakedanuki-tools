# Reloading

## Basic Usage

tools だけを変更した場合です。

```python
import bd_tools

bd_tools.reload_package()
```

同時に util も変更した場合は、依存先を先に reload します。

```python
bd_tools.reload_package(reload_util=True)
```

必要な場合だけ `__pycache__` も削除できます。

```python
bd_tools.reload_package(clear_pycache=True)
```

## External State Lifecycle

Python module を `sys.modules` から外すだけでは、次の Maya 外部状態は破棄されません。

- Qt Window と controller
- workspaceControl
- Maya callback
- scriptJob
- signal connection
- timer やその他の process state

外部状態を作成する module は、再読込前に必要な終了処理を登録します。

```python
import bd_tools


def dispose() -> None:
    """このmoduleが所有するUIとcallbackを破棄する。"""
    controller.dispose()


bd_tools.register_reload_disposer(dispose)
```

同じ callable は重複登録されません。終了処理は登録と逆順に一度だけ実行されます。
一部が失敗した場合も残りを実行し、最後に `ReloadDisposalError` でまとめて通知します。
破棄が不完全な状態では reload を続行しません。

## Reload Order

`reload_util=True` の順序です。

1. 開いているtoolsの再表示先をutilの共通UI基盤から文字列として取得
2. tools が登録した外部状態の終了処理
3. `bd_util.reload_package()`
4. `bd_tools` 配下の古い module 参照を削除
5. `bd_tools` の再 import
6. 新しいutilから、リロード前に開いていたtoolsだけを再表示

toolsだけをreloadする場合も、1、2、4、5、6の順に実行します。タイトルバーや
`close()`で閉じたtoolは再表示しません。再表示が失敗したtoolがあっても残りを試し、
失敗内容を例外で通知します。Mayaの起動時復元は従来どおり`uiScript`へ任せます。
Widget生成を後回しにしたdockは、tools側で定義したworkspaceControl名から検出します。
開発reload時のタブ位置やアクティブなタブの完全復元は対象外です。

Maya Script Editor が保持する古い `bd_tools` 変数にも、新しい package 内容を反映します。
ただし個別 module や class instance を別変数へ保持していた場合、その参照は自動更新されません。

将来 `bd_rig` が tools を利用する場合、rig 側で util → tools → rig の順を扱います。
`bd_tools` 自身は rig を reload しません。

## Development Guidance

bdChannelBoxは `bd_channel_box.dispose()` を登録します。dock controllerの
`dock_about_to_dispose` で各Binding・選択監視・開いたUndoを終了してから
workspaceControlとWindowを破棄します。Maya側のcloseも `dock_closed` で同じ終了処理へ接続します。
`show()`とMayaの`restore()`の両方で、utilへ再表示情報を登録します。reload前に
開いていたbdChannelBoxは自動的に再表示されるため、手動の`show()`は不要です。
個別moduleやclass instanceを変数へ保持した場合は、必要に応じて取り直してください。

- UI module の import 時に Window を表示しない。
- controller は module 単位で1つにする。
- `dispose()` は複数回呼ばれても安全にする。
- reload 後に callback や workspaceControl が重複していないことを確認する。
- 外部状態の終了処理が失敗した場合、その例外を握りつぶさない。
