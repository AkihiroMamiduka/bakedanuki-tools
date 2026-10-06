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

## bdChannelBox

bool・float系・enum・stringの値入力、step操作、表示・ロック状態の変更、Mayaへのドッキングに対応しています。
今後の任意の拡張候補は[Roadmap](bakedanuki/bakedanuki-tools/docs/roadmap.md#bdchannelboxの拡張候補)にまとめています。

Maya の Script Editor で実行します。

```python
from bd_tools import bd_channel_box

bd_channel_box.show()
```

初回はMaya右側へドッキングし、タイトル部分のドラッグでfloatingやタブ配置へ変更できます。
終了は `bd_channel_box.close()`、配置のリセットと再表示は `bd_channel_box.reset_layout()` です。

対象objectを抽出した選択リストの末尾ノードを基準に、Channel Box に表示する
bool・float系・enum・単一typed string属性の
入力欄を表示します。同名・同種の属性を持つ選択ノードへ、編集時だけ値を一括反映します。
画面上部の名前欄では、複数選択中も末尾の基準ノードだけを改名できます。
選択や表示更新では値を揃えません。両側に hard min/max がある属性は Slider 付き、
bool は属性名の右に置く CheckBox です。通常時間カーブとAnimation Layerへの入力は
MayaのAuto Key設定に従い、OFFでは一時値、ONでは現在時刻のキーを追加・更新します。
Driven Keyはキーを変えずに一時値を入力できます。未接続属性は通常の値設定のままです。
属性名と値欄の間の帯で、現在キー（赤）・アニメーション中のキーなし（淡い赤）・
Key Altered（淡い桃）・Driven Key（青）・Expression（紫）・
Animation Layer（青緑）・Animation Clip（橙）・Muted（茶）・
Nonkeyable（灰色）も確認できます。pairBlend、constraint、その他の入力接続、
ロックにも専用色を使い、キー設定可能な未接続属性はMayaの通常背景色です。
ロックや未対応の入力接続は表示専用です。対象範囲は[値編集の仕様](bakedanuki/bakedanuki-tools/docs/bd_channel_box.md#アニメーション属性の値編集)を参照してください。
enumはComboBoxで項目名を表示し、整数値と項目名の対応が一致する対象へ一括適用します。
定義不一致の除外理由はtooltipで確認できます。未定義の現在値は自動修正しません。
属性を複数選択すると、数値の直接入力、上下操作、Slider、bool、互換enumを同時に操作できます。
Step欄の直接入力と上下操作も、選択中でStep欄を持つ属性へ同じ表示stepを反映します。
変更したStepは正式属性pathと数値種別ごとに保存し、Window再表示とMaya再起動後にも復元します。
属性行または画面余白の右クリックにある「Step設定」から、全属性または選択属性を
それぞれの初期値へ戻せます。Step設定とリセットはsceneとUndo履歴を変更しません。
初期状態では値欄・Step欄・enum欄がフォーカス中の場合だけホイールで値を変更します。
上部の「設定」メニューで未フォーカス時のホイール編集をONにすると、クリック前の
マウスオーバー中も変更できます。この選択はMaya再起動後も復元します。
Step欄のない行は対象外として通知し、属性値とUndo履歴は変更しません。

上部ComboBoxで「表示・ロック」へ切り替えると、属性名の右側を状態設定へ置き換えます。
非表示の属性も列挙し、Keyable／ChannelBox／HideとLock／Unlockを独立して一括変更できます。
複数属性の選択中は、選択行の`key / ch / hide / lock`をクリックすると、
同じ状態を選択属性すべてへ適用します。左ドラッグのなぞり操作は通過行だけを変更します。
その下のComboBoxで全て／keyable + channelbox／keyable／channelbox／hideを選び、
両モードの表示対象を絞り込めます。フィルター選択はモードごとにWindow内で保持します。
「設定」→「カスタムフィルター管理」からJSON定義ファイルを任意数登録し、
ノード型ごとに使う属性をKeyableなどの表示状態と独立して表示できます。
登録順を変更でき、ファイルごとのON/OFF、再読込にも対応します。
管理画面の「新規作成...」でJSONを作成し、「カスタムフィルター設定」モードで
選択ノード型の属性と表示順を設定してJSONへ保存できます。
設定モードでは「フィルターの表示順」と属性候補の境界をドラッグして、作業する側を広げられます。
標準Attribute Filterと検索で絞った候補は、スクロール外も含めて一括で「含める」／
「含めない」に切り替えられます。変更は「JSONに保存」まで作業中の定義に留まります。
候補の属性名をCtrl／Shiftクリックまたはドラッグで複数選択し、選択中の行のラジオを押すと
選択した属性をまとめて切り替えられます。選択外の行のラジオはその1行だけを変更します。
JSONの形式と未定義ノード型の扱いは
[カスタムフィルター](bakedanuki/bakedanuki-tools/docs/bd_channel_box.md#カスタムフィルター)を参照してください。
Attribute SearchはNice Name・属性名・正式pathを、大文字小文字を区別せずAND検索します。
検索欄は初期状態で「全て」の場合だけ表示し、設定メニューから非表示／「全て」の場合のみ／
常時表示を選べます。表示方針はMaya再起動後も復元し、検索文字列自体は保存しません。
値編集行の右クリックから、選択属性やKeyable属性へのキー・ブレイクダウン設定と、
選択属性やChannelBox表示属性のミュート・解除を操作できます。
アニメーションカーブは選択属性／全アニメーション属性をコピーし、
現在時刻からコピー元と同じ属性／選択属性へ貼り付けられます。
カーブの貼り付けはdouble・角度・距離・bool・enum間でも行えます。
選択属性またはKeyable／ChannelBox表示属性の全時間のカーブを削除できます。
編集メニューと属性行の右クリックから、基準ノードの全対応属性または選択属性をコピーできます。
貼り付けはコピー元と同じ正式pathを表示状態で絞るか、選択属性を明示して適用します。
一属性だけのコピー値は互換性のある複数の選択属性へ展開でき、OSクリップボードを介して
別のMayaへも搬送できます。行順や属性のクリック順では対応付けません。
縦スクロールバーは必要時だけ表示し、値編集のstep設定も維持します。
状態の混在表示とMaya標準Undo／Redoへ対応します。

対応する `bakedanuki-util` の値・状態の複数対象Binding、属性列挙、複合View、ドッキング基盤が必要です。
toolsとutilは、組み合わせて動作確認した版を配置してください。
詳細は [bdChannelBox](bakedanuki/bakedanuki-tools/docs/bd_channel_box.md) を参照してください。

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
