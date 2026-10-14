# bdRotationPreservingPose

ノードの現在姿勢を維持しながら、回転属性の値を設定するdockableツールです。
bdChannelBoxの「回転をセット（姿勢を維持）」からも開けます。

## 単独起動

上部の`bakedanuki > tools > 回転をセット（姿勢を維持）`から開けます。
MayaのScript Editorから直接開く場合は次を実行します。

```python
from bd_tools import bd_rotation_preserving_pose

window = bd_rotation_preserving_pose.show()
bd_rotation_preserving_pose.show("rotateAxis")
bd_rotation_preserving_pose.close()
```

`show(initial_target=...)`で`rotate`、`rotateAxis`、`jointOrient`を設定先に指定できます。
指定がない場合の初期値は`rotate`です。Windowを再度開くと、指定した属性を設定先に
して同じWindowを前面へ表示します。

## 値の設定

操作時の現在選択の末尾にあるTransformまたはJointを1個だけ対象とします。
Transformの設定先と補償先には`rotate`と`rotateAxis`を、Jointには加えて
`jointOrient`を使えます。設定先と補償先は異なる属性を選びます。Jointの補償先の
初期値は、設定先が`rotate`なら`jointOrient`、それ以外なら`rotate`です。
設定先を切り替えると、現在のノードから未丸め実値を読み直します。切替だけでは
sceneを変更しません。

Windowを開いたまま選択を変えると、対象名とXYZ欄を更新します。選択変更・角度単位
変更では未確定の文字入力を破棄し、対象がないときは値入力を無効にします。
Jointの`jointOrient`を設定先にしたままTransformへ切り替えた場合は`rotate`へ
変更します。対象名は一意ならnamespace付き短名、同名ノードやインスタンスでは
選択中のフルパスを表示し、コマンドには常にフルパスを渡します。

各軸はEnter・フォーカス移動で確定し、ホイール・上下操作はその場で反映します。
操作しない軸は現在の未丸め実値を使い、実行後にXYZを読み直します。各軸のStepは
bdChannelBoxとは独立しており、Step変更だけではsceneとUndo履歴を変更しません。
OK／Cancelによる一括確定はありません。値は現在のMaya角度単位で表示・入力します。

変更対象は設定先と補償先の二属性で、第三の回転属性は変更しません。現在のlocal
matrixを維持するため、子のworld位置と姿勢も変わりません。各値操作には
`bdUtilCommands`の`bdSetRotationPreservingPose`を使い、Undoで戻せます。
目標値が現在値と同じならUndoを追加せず、ロックや入力接続などで変更できない場合は
エラーを表示します。

## 配置

固定workspaceControl名は`bdRotationPreservingPoseWindowWorkspaceControl`です。
保存済み配置のない初回起動で`anchor`を指定した場合、その位置を中心に浮動表示
します。bdChannelBoxからの起動では右クリック位置を渡します。位置を指定しない
単独起動時と、以降の浮動位置・サイズとドック配置はMayaに従います。
狭いドックでは内容をスクロールできます。初回の浮動サイズは
`window.py`の`INITIAL_WIDTH`・`INITIAL_HEIGHT`で指定します。
`show()`と`restore()`は`RotationSetDockWindow`を返し、入力ページは
`rotation_page`から参照します。Mayaの`uiScript`は
`bd_tools.bd_rotation_preserving_pose.ui.restore()`を呼びます。close、Maya終了、
reloadでは選択監視とcallbackを解除します。
