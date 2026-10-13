# bdChildCompensatedSet

子のworld位置や姿勢を維持しながら、選択ノードの移動・回転値を設定するツールです。
「移動」と「回転」は1つのdockable Windowのタブです。bdChannelBoxの右クリック
メニューからも開けます。

## 単独起動

MayaのScript Editorで実行します。

```python
from bd_tools import bd_child_compensated_set

window = bd_child_compensated_set.show()
bd_child_compensated_set.show("translate", "translate")
bd_child_compensated_set.show("rotation", "rotateAxis")
bd_child_compensated_set.close()
```

引数なしの`show()`は保存されたタブを開き、保存がない場合は移動タブを開きます。
回転タブの設定先には`rotate`、`rotateAxis`、Jointでは`jointOrient`も指定できます。
`show(tab, target)`で指定したタブと設定先は、保存状態より優先します。
bdChannelBoxのメニューは、右クリックした属性に対応する引数で`show()`を呼びます。

## 値の設定

操作時の現在選択の末尾にあるTransformまたはJointを1個だけ対象とします。
Windowを開いたまま選択を変えると、対象名とXYZ欄を新しいノードの未丸め実値で
更新します。選択変更・表示単位変更では未確定の文字入力を破棄します。対象がない場合は
値入力を無効にします。対象名は一意ならnamespace付き短名、同名ノードやインスタンスでは
選択中のフルパスを表示し、コマンドには常にフルパスを渡します。

入力空間は`World`／`Local`の順に表示し、初期値は`Local`です。Localは対象属性の値、
Worldの移動はDAG原点の最終world位置、Worldの回転は最終world姿勢を固定XYZ順の
Euler角で表した値です。Worldの回転値は対象ノードの`rotateOrder`で解釈する
属性値ではありません。値欄には現在のMaya表示単位を使い、内部では移動をcm、回転を
degreeで扱います。空間や設定先の切替だけではsceneを変更しません。

各軸はEnter・フォーカス移動で確定し、ホイール・上下操作はその場で反映します。
操作しない軸は現在の未丸め実値を使い、実行後にXYZを読み直します。各軸のStepは
独立しており、Step変更だけではsceneとUndo履歴を変更しません。bdChannelBoxのStep
とは連動しません。OK／Cancelによる一括確定はありません。

移動では直接の子のworld位置を保持します。回転では、直接の子のworld位置と姿勢を
保持する「座標と姿勢」が初期値で、「姿勢」のみへ切り替えられます。Transform子の
姿勢は`rotate`で補償します。子Jointの補償属性は`rotate`が初期値で、
`jointOrient`も選べます。補償により子の属性値は変更されます。
各値操作は`bdUtilCommands`の子補償コマンドを使い、1回のUndoで戻せます。
結果が現状と同じならUndo履歴を増やさず、ロックや入力接続などで変更できない場合は
エラーを表示します。

## 配置と設定

固定workspaceControl名は`bdChildCompensatedSetWindowWorkspaceControl`です。
保存済み配置のない初回起動で`anchor`を指定した場合、その位置を中心に浮動表示
します。bdChannelBoxからの起動では右クリック位置を渡します。位置を指定しない
単独起動時と、以降の配置はMayaに従います。
狭いドックではページをスクロールでき、ドック中のタブ切替ではドック寸法を変えません。
初回の浮動サイズは`dock_window.py`の`TRANSLATE_INITIAL_WIDTH`・
`TRANSLATE_INITIAL_HEIGHT`・`ROTATION_INITIAL_WIDTH`・
`ROTATION_INITIAL_HEIGHT`で指定します。手動変更したタブ別の浮動サイズ、選択タブ、
両タブの入力空間、回転の維持範囲と子Jointの補償属性はMaya user preferencesの
`bd_child_compensated_set/ui.ini`に保存し、再表示とMaya再起動後に復元します。
回転の設定先は保存せず、起動時の指定を優先します。

Mayaの`uiScript`は`bd_tools.bd_child_compensated_set.ui.restore()`を呼びます。
`show()`と`restore()`は共通の`ChildSetDockWindow`を返します。close、Maya終了、
reloadでは選択監視とcallbackを解除します。
