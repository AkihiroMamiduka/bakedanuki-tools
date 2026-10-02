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

Mayaで`bd_tools`のWindowを開いている間は、`bd_util.reload_package()`を単独で
実行しません。Windowやcallbackが保持する古いutilのclass参照は自動更新されず、
選択追従などに不整合が生じます。utilを変更した場合は上記のtools側入口を使い、
Windowの破棄から再表示までまとめて実行します。

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
- `bd > tools` のメニュー項目

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
6. 登録されていたtoolsメニューを新しいcallbackで再作成
7. 新しいutilから、リロード前に開いていたtoolsだけを再表示

toolsだけをreloadする場合も、1、2、4、5、6、7の順に実行します。タイトルバーや
`close()`で閉じたtoolは再表示しません。再表示が失敗したtoolがあっても残りを試し、
失敗内容を例外で通知します。Mayaの起動時復元は従来どおり`uiScript`へ任せます。
メニュー未登録の状態でreloadした場合、メニューは自動登録しません。
Widget生成を後回しにしたdockは、tools側で定義したworkspaceControl名から検出します。
開発reload時のタブ位置やアクティブなタブの完全復元は対象外です。

Maya Script Editor が保持する古い `bd_tools` 変数にも、新しい package 内容を反映します。
ただし個別 module や class instance を別変数へ保持していた場合、その参照は自動更新されません。

現在の`bd_tools.reload_package(reload_util=True)`が退避・再表示するのは
`bd_tools`が所有するtoolだけです。将来`bd_rig`や`bd_physics`など別packageのUIも
起動する場合、utilの単独reloadやこの入口だけでは、他packageの古い参照とUIを
更新できません。変更したpackageと、それを参照する稼働中のpackageを対象に、
全対象の表示情報を退避→依存する側から外部状態を破棄→依存先からreload→
新しいmoduleから再表示、という一括入口を必要になった時点で整備します。
例えばrigがtoolsを利用する場合のreload順はutil→tools→rigです。
一括入口を用意するまでは、複数packageのUIを同時起動しているMayaで依存先を
reloadする必要が生じたら、Mayaを再起動します。

## 新しいtoolを再表示対象に追加する

1. `show()`とdockの`restore()`が成功した後、
   `bd_util.maya.ui.register_open_tool()`で
   `owner="bd_tools"`、固有のtool ID、import可能な再表示module/function名、
   Windowごとの`token`を登録します。再表示関数は引数なしで呼べるようにします。
2. タイトルバーのclose、Maya側のdock終了、`dispose()`など、Windowが終わる
   全経路で同じ`token`を使って`unregister_open_tool()`を呼びます。古いWindowの
   遅延通知が新しい登録を消さないためです。
3. dockable toolは、固定のworkspaceControl名も`_dev/reopen_targets.py`の
   `KNOWN_DOCK_TOOLS`へ追加します。Mayaが`uiScript`の実行を遅らせ、Widgetが
   まだ登録されていないdockを見つけるためです。
4. `dispose()`を`register_reload_disposer()`へ登録し、reload後に開いていたtool
   だけが戻ること、閉じたtoolは戻らないこと、callbackやworkspaceControlが
   重複しないことを確認します。複数dockをタブ化した場合は、非アクティブな
   タブも再表示対象に入ることをMaya本体で確認します。

登録・解除の実例は[bdChannelBoxのUI実装](../python/bd_tools/bd_channel_box/ui.py)、
dockの識別情報は[reopen_targets.py](../python/bd_tools/_dev/reopen_targets.py)を
参照してください。

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
