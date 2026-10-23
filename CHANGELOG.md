# Changelog

このプロジェクトの主な変更を記録します。

形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) を参考にし、
バージョンは [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

### Fixed

- Maya 2027のQt型定義差で、bdChannelBoxの一括数値入力に出るPyright警告を修正。
  `findChild()`の呼出し境界に型を明示し、入力動作・scene・設定は変更しない。
- `overrideColor`など、byte属性の下限0または上限255を持つ狭い範囲で
  Step欄が表示される判定をutil側で修正。0～31などは`[値][Slider]`を表示する。
  型既定の全範囲0～255はStep表示を維持する。utilも更新して
  `bd_tools.reload_package(reload_util=True)`で反映する。設定・sceneの移行は不要。

### Added

- bdChannelBoxのカスタムフィルター管理に「複製...」を追加。
  初期名は`元の名前_copy`で、全ノード型・属性順・0件定義を別JSONへ複製する。
  設定画面内の「新規作成...」と、選択ノードまたは登録済みノード型を選ぶComboBoxも追加。
  ノードなしで型の標準属性と保存済みpathを追加・除外・並べ替えできる。
  型情報未確認の保存済み候補は「全て」で表示し、個別ノードの追加属性は「選択ノード」で取得する。
  属性検索を一括操作の下へ移動し、表示順操作を一覧左側の20×20アイコンへ変更。
  新規作成・複製前に未保存変更を確認し、中止時は新しいファイル・登録を残さない。
  utilも更新して`bd_tools.reload_package(reload_util=True)`で反映する。
  JSON形式・保存設定・sceneの移行は不要。
- bdChannelBoxへ「値編集（多数ノード）」モード（`bulk_values`）を追加。
  50ノード以上でも基準ノードの属性・値を表示し、明示的な操作時にだけ
  全選択ノードの対応属性を解決して一括編集する。Step、Slider、右クリック操作は維持する。
  値・ロック・接続状態の混在と全対象の編集可能件数は常時集計せず、表示は基準ノードに限定する。
  操作時の型・範囲・lock検証、途中失敗の復旧、一操作一回のUndoは維持する。
  通常の値編集・表示とロック・カスタムフィルター設定は既存の50ノード制限を維持する。
  utilも更新して`bd_tools.reload_package(reload_util=True)`で反映する。
  モードはWindow内だけで保持し、scene・保存設定・clipboardの移行は不要。
- bdChannelBoxの両側hard limit付き整数行へ`IntSliderSpinBox`を組込み、
  `[値][Slider]`表示と複数の整数・float属性へのライブ入力、一操作一回のUndoに対応。
  制限違反ではその更新全体を拒否し、時刻・選択・ロック変更などで操作を終了する。
  型固有範囲・片側制限・soft limit・同値制限だけの行は`[値][Step]`を使用する。
  保存済み整数StepはSlider表示中も保持し、Step表示へ戻ると復元する。
  行の`editor`は`IntSliderSpinBox | IntValueStepSpinBox`となる。
  値欄の操作は引き続き`editor.spin_box`を使用し、View固有APIの利用前に型を分岐する。
  utilも更新して`bd_tools.reload_package(reload_util=True)`で反映する。
  scene・設定・clipboardの移行は不要。
- bdChannelBoxの整数行にStep欄を追加。既定1の10倍方式と任意の正整数入力に対応し、
  複数行への設定、属性型・正式pathごとの保存、選択属性／全属性リセットを行う。
  floatとの混在選択は全対象を検証し、小数Stepを整数行へ適用する操作は全体を拒否する。
  整数設定は`integer_attribute_steps`へ保存し、既存float設定とsceneの移行は不要。
  Step付き行の`editor`は`IntValueStepSpinBox`で、値欄の直接操作は`editor.spin_box`を使用する。

- bdChannelBoxでMayaのbyte・short・long属性を整数欄として表示・編集できるようにした。
  単一属性とcompound子属性に対応し、複数ノード編集、整列、表示・ロック、
  Copy／Paste、Undoでも整数値と型固有の範囲を保つ。
  clipboard書込みはschema version 3に変わるため、旧版の利用側へ貼り付ける場合は
  利用側も更新する。version 1・2のコピー内容は引き続き読み込める。

### Fixed

- Maya 2027のPyright型検査エラー5件を解消。
  カスタムフィルター設定の`QSplitter.setSizes()`はQt呼び出しの境界で引数型を明示し、
  テストの`QLayout.itemAt()`は項目の存在を確認してからWidgetを取得する。
  分割領域の設定値・UI動作・scene・保存設定は変更しない。

### Changed

- bdChannelBoxの「表示・ロック」も選択数の上限を撤廃し、基準ノードだけを常時表示・監視する。
  混在マーカー・三状態lock・全対象の変更可能件数は表示せず、操作時に必要な属性だけを
  全選択から確認する。表示状態の再選択と同状態の行をなぞる操作も、他の対象へ適用する。
  lockは基準がOFFなら全対象をロック、ONなら全対象を解除する。単発は選択属性全体、
  なぞりは開始列の通過行だけへ一回ずつ適用し、一操作一回Undoと既存の失敗復旧を保つ。
  `ChannelStateRow.state_binding`と`target_names`は表示用の基準一個だけを保持する。
  状態の全対象編集はcontrollerの`set_selected_display`／`set_selected_locked`を使用する。
  カスタムフィルター設定の含める／含めないにも同じ列のなぞりを追加し、未保存データだけを
  通過順で変更する。表示順の更新は終了時にまとめ、保存は「JSONに保存」で確定する。
  utilも更新して`bd_tools.reload_package(reload_util=True)`で反映する。
  scene・JSON・保存設定の移行は不要。
- bdChannelBoxの「カスタムフィルター設定」は選択数によらず基準ノード一個だけを対象にする。
  属性取得・識別情報・構成監視を基準だけに限定し、50ノード以上でも設定画面を表示する。
  設定対象は基準ノードの型で、別の型の定義・未保存データ・Mayaの選択は保持する。
  `controller.node_names`もこのモードでは基準一個だけを返し、値編集へ戻ると全選択を取得する。
  JSON・scene・保存設定の移行は不要。
  toolsのみ更新し、`bd_tools.reload_package()`で反映する。
- bdChannelBoxの値編集を、基準ノードだけを常時表示する方式へ一本化。
  Mode先頭・初期選択は「値編集」とし、選択数の上限を設けず、操作時に全対象を照合する。
  混在値の「•」・接続やlockの混在情報・全対象の編集可能件数は常時計算しない。
  Step・Slider・右クリック・操作時の検証と除外・Undo／復旧を維持する。
  `ChannelBoxMode`から`bulk_values`を削除したため、呼出し側は`set_mode("values")`へ変更する。
  `AttributeRowWidget`の`representative_only`引数は削除し、呼出し側は指定を外す。
  モードは保存しないためscene・設定の移行は不要。utilの変更はない。
- bdChannelBoxの角度（doubleAngle）のSlider付き行で、値欄の上下・ホイールの刻み幅を1へ変更。
  utilの`FloatSliderSpinBox`がstep未指定時に単位種別から選び、通常数値・距離は0.1を維持する。
  Slider分割数・小数精度・Step付き角度行の既定15・保存済みStepは変更しない。
  utilも更新し、`bd_tools.reload_package(reload_util=True)`で反映する。scene・設定の移行は不要。
- bdChannelBoxの多数ノードモードで、フィルター対象の複数行を構築する間にもnode情報を共有。
  「値を揃える」「丸める」の準備を軽量化し、通常モードと単一行は従来の構築経路を使う。
  utilでは複数属性の値Pasteにも構築中だけ同じ共有を適用し、書込み前に索引を解放する。
  混在判定・型と範囲の検証・除外規則・Undo・失敗復旧、Step・Slider・右クリック操作を維持する。
  utilも更新し、`bd_tools.reload_package(reload_util=True)`で反映する。scene・設定の移行は不要。
- bdChannelBoxの多数ノード編集で、同時に構築する複数行のノード操作オブジェクトを
  構築中だけ共有し、初期準備の繰り返しを削減。名前・実体・DAG経路と各属性の型を
  再確認し、既存の入力検証・Undo・失敗復旧は維持する。
  enum値Pasteの重複検証をutilで整理し、非表示メニューではPaste説明文のための
  clipboard全量解析を省く。説明文はメニュー表示時、実際のPasteは実行時に最新内容を読む。
  Step・Slider・右クリック操作は維持する。utilも更新し、
  `bd_tools.reload_package(reload_util=True)`で反映する。scene・設定・clipboardの移行は不要。
- bdChannelBoxの多数ノード編集で、選択キー全体の有効性を確認した後、操作する型の
  行だけを一括編集用Bindingへ結ぶ。数値・bool・enum・string入力と丸めで非対応型の
  準備を省き、適用候補は操作する型の編集可能件数だけを数え、非対応型は行ごとに報告する。
  フィルター対象の揃え・丸めでは基準以外を正式path・型だけで照合し、丸めはfloat系に限定する。
  選択カーブCopyは値Bindingを作らず対象名を取得し、定義差のあるenum・選択順・曲線の対応を維持。
  Step・Slider・右クリック操作、型・範囲・lock検証、一回Undoと失敗復旧を維持する。
  utilも更新し、`bd_tools.reload_package(reload_util=True)`で反映する。scene・設定の移行は不要。
- bdChannelBoxの多数ノード操作で、対象照合は正式path・型だけを取得し、
  同時に生成する値Bindingの削除監視をnodeごとに共有する。
  各Bindingの検証・削除履歴・Undo・失敗復旧と、Step／Sliderは維持する。
  値編集行の右クリックメニューは初回利用時に生成・接続し、表示・Undo時の準備を削減。
  UI参照コードの`row.align_action`などは`row.context_menu.align_action`へ移行する。
  `context_menu`は型付きの`AttributeRowMenu`を返す。未使用メニューの終了処理には
  `close_context_menu()`を使う。utilも更新し、`bd_tools.reload_package(reload_util=True)`
  で反映する。scene・設定・clipboardの移行は不要。
- bdChannelBoxの選択カーブのカット・削除で値Bindingの準備を省き、
  一属性選択時はその正式pathだけを調査する。曖昧名は全列挙へ戻し、
  複数属性のnode内順序、異種型の対象、共有曲線の除外とUndoを維持する。
  多数ノードのキー・Layer・mute・lock・表示操作も対象名の照合を値Bindingから分離。
  enum定義が異なる対応先も従来どおり扱い、lock・表示の候補件数と除外理由は
  値編集ではなく各状態操作の可否で通知する。Step・Slider・メニュー構成は維持する。
  utilも更新し、`bd_tools.reload_package(reload_util=True)`で反映する。
  scene・設定・clipboardの移行は不要。
- bdChannelBoxの多数ノード数値入力で、入力前は基準の編集可否と表示単位だけを確認し、
  全対象の値・状態同期を適用後へ集約。書込み前の検証・削除監視・失敗復旧は維持する。
  カーブ貼付は候補の正式pathだけを調べ、値Bindingの準備と全曲線の反復探索を省く。
  コピー時のノード順とキーなしノードの除外順、型をまたぐ貼付・Undoを維持する。
  メニューの移動Freeze可否は、最初の対応transformで判定を終える。
  Step・Slider・右クリック操作・scene・保存設定の変更や移行は不要。
  utilも更新し、`bd_tools.reload_package(reload_util=True)`で反映する。
- bdChannelBoxの多数ノードモードで、連続する数値入力の対象準備を短期再利用。
  最初の単発入力は保持せず、同じ対象への次の入力が処理終了後500ms以内に続いた場合に保持する。
  値欄wheelの相対値、Slider wheelの同値適用、各イベントの独立Undoを維持する。
  値・Step・単位・lock・範囲・接続は毎入力で確認し、期限・中断・失敗時に監視を解放する。
  UI・右クリックメニュー・scene・保存設定は変更しない。utilも更新し、
  `bd_tools.reload_package(reload_util=True)`で反映する。移行処理は不要。
- bdChannelBoxの多数ノードモードで、Sliderの押下から解放まで対象の照合と一時Bindingを再利用。
  値・lock・範囲・接続の再検証と毎回の復旧値取得、一回Undoを維持する。
  全対象の削除と属性構成変更を監視し、変更・中断・失敗時は旧対象を解放する。
  操作専用Bindingの表示用キー状態取得も省き、常設の基準表示は維持する。
  属性行の選択通知と描画を集約し、途中集合を繰り返し通知しない。
  UI・Step・Slider・右クリックメニュー、wheelの一イベント一Undoは維持する。
  utilも更新し、`bd_tools.reload_package(reload_util=True)`で反映する。
  scene・保存設定・clipboardの移行は不要。
- bdChannelBoxのlock・表示状態編集で、util側の実体索引を使って多数対象の重複走査を削減。
  値Pasteもutilの共通書込み処理を使い、対象ごとの表示用Binding生成を省く。
  既存の対象判定、状態編集のcallback本数、Undoと失敗復旧は維持する。
  Paste中の対象削除を記録し、同名で再作成された別実体へ追従しない。
  外部処理による削除・再作成自体は復旧対象外とする。
  UI・メニュー・公開API・scene・設定形式は変更しない。utilも更新し、
  `bd_tools.reload_package(reload_util=True)`で反映する。移行処理は不要。
- bdChannelBoxの「値編集（多数ノード）」で、enumの明示入力・値揃え・値Pasteに
  utilの`enum_validation="operation"`を使用する。開始時の全定義を固定し、
  書込み直前の基準と当該対象、終了時の全対象を確認して重複検証を減らす。
  後続・既適用・未書込み対象や別行の変更検出が終了時まで遅れる場合がある。
  変更時は値の復旧を試みるが、外部callbackの副作用と定義自体は復旧対象外で、
  復旧不能時はエラーにする。通常モードは従来の検証方式を維持する。
  新しいUIモードは増やさず、Step・Slider・メニュー、scene・設定形式は変更しない。
  utilも更新し、`bd_tools.reload_package(reload_util=True)`で反映する。移行処理は不要。
- bdChannelBoxのenum一括入力で、utilが共有する属性定義の重複検証を削減。
  `drawStyle`など同じ属性実体を持つ対象は、検証のたびに共有定義を一度だけ取得する。
  別実体のカスタムenumは個別に検証し、定義変更の検出・Undo・失敗復旧を維持する。
  UI・メニュー・設定形式は変更しない。utilも更新し、
  `bd_tools.reload_package(reload_util=True)`で反映する。scene・設定の移行は不要。
- utilのパス解決API改名に合わせ、3ツールのアイコン定義を`resolve_relative_path()`へ変更。
  `icon_path()`を直接利用するスクリプトは新しい関数名へ置き換え、utilとtoolsを同時に更新する。
  画像pathの組み立て方・表示・scene・保存設定は変更しない。
- 3ツールの`MENU`は共通の`bd_util.py.path.resolve_relative_path(__file__, 画像名)`で解決する。
  メニューの画像情報は登録時に読み込み、`import bd_tools`だけではutilを読み込まない。
  アイコン取得にはutilを利用するが、ツールのUI本体は読み込まない。
  このAPIを含むutilとの同時更新が必要。sceneと保存設定の移行は不要。
- 3ツールの画像pathを各`icon/__init__.py`の`MENU: Final[Path]`へ移した。
  親packageの公開関数・Window classは初回の属性参照時に読み込み、
  メニュー登録時はUI本体を読み込まずに定数を利用する。既存APIと型補完は維持する。
  仮アイコンは文字を拡大し、長い方向の外周に2〜3px程度の余白を残す。
  sceneと保存設定の移行は不要。
- bdChannelBoxの整数欄で、時間カーブ・SDK・short／longのAnimation Layerへの
  入力・上下・整列・値Pasteを既存型と同じAuto Key規則で処理する。
  Enterの欄内受理と初回クリックの全選択も揃えた。小数カーブの整数評価による
  Key Alteredの誤判定を修正。利用側は対応するutilへ同時更新し、開いているMayaでは
  `bd_tools.reload_package(reload_util=True)`で反映する。scene・設定・clipboardの移行は不要。
- `bd_util.Nodes` の操作入口を保持する推奨変数名を `bd_nodes` に統一。
  内部コードと開発規約を揃え、ノード名の集合と区別する。
- bdChannelBoxの数値欄を150 pxから156 px、共通入力列を216 pxから222 pxへ広げた。
  Maya 2027でも20文字程度の数値が入力欄内に収まるようにし、sceneと保存設定は変更しない。
- bdChannelBoxの3つの値設定メニューから開くWindowを、単独起動できる
  `bd_tools.bd_child_compensated_set`と`bd_tools.bd_rotation_preserving_pose`へ分離。
  bdChannelBoxは公開`show()`を呼ぶ入口とし、共通の選択監視・XYZ入力部品は
  `bd_tools._shared`へ移した。旧`bd_channel_box`配下のWindow moduleとdialogは削除。
  両WindowのworkspaceControl IDとMayaの復元経路を新package名に変更したため、
  旧ドック配置は引き継がれない。子維持ツールの設定先も
  `bd_child_compensated_set/ui.ini`へ変更し、旧`bd_channel_box/ui.ini`のタブ・
  入力空間・補償設定・浮動サイズは移行しない。sceneの移行は不要。
- bdChannelBoxの「回転をセット（姿勢を維持）」を独立したdockable Windowへ変更。
  Mayaへのドッキングと再起動時の配置復元に対応し、初回の浮動表示だけ右クリック位置へ
  配置する。`rotation_set_ui.show()`の戻り値は入力ページからdockable Windowへ変更し、
  入力ページは`rotation_page`から参照する。scene・保存設定の移行は不要。
- bdChannelBoxの「移動・回転をセット（子を維持）」と「回転をセット（姿勢を維持）」
  では、設定対象が一意な場合は短名を表示し、同名ノードやインスタンスの場合は
  選択中のフルパスを表示する。操作対象のフルパスやscene・保存設定は変更しない。
- bdChannelBoxの「回転をセット（子を維持）」で、Jointの設定先候補を
  `jointOrient`→`rotate`→`rotateAxis`、子Jointの補償先候補を
  `jointOrient`→`rotate`の順に変更。Transformの設定先候補と補償先の初期値
  `rotate`は維持する。選択と保存は属性名で扱うため設定の移行は不要。
- bdChannelBoxの「移動・回転をセット（子を維持）」で、移動・回転それぞれの入力空間、
  回転の子の維持範囲と子Jointの補償属性を`bd_channel_box/ui.ini`へ保存し、
  再表示・Maya再起動時に復元する。既存設定はそのまま使え、未保存項目には従来の
  初期値を適用する。sceneの移行は不要。
- bdChannelBoxの「移動をセット（子を維持）」と「回転をセット（子を維持）」を
  1つのdockable Windowの「移動」「回転」タブへ統合。右クリックした属性に対応する
  タブを開き、浮動時のタブ別サイズと選択タブをMaya再起動後も復元する。
  タブ別サイズは浮動枠の寸法で保持し、切替を繰り返しても縮まない。
  回転メニューから初回起動しても、未表示の移動タブの初期サイズを上書きしない。
  ドック中のサイズはMayaの配置に従い、scene・既存設定の移行は不要。
- bdChannelBoxの3つの即時設定Windowでは、XYZ値・Step欄のEnter確定を欄内で受理し、
  Outlinerのノード名編集へ伝播させない。XYZの行間を2論理pxに縮め、縦リサイズ後も維持。
- bdChannelBoxの子を維持する設定Windowでは、入力空間の候補をWorld→Localの順にし、
  初期選択はLocalのまま維持。「回転をセット（姿勢を維持）」では属性ラベルと選択欄を
  横に並べた2行とし、設定対象との間に仕切り線を追加。
- bdChannelBoxの「移動をセット（子を維持）」「回転をセット（子を維持）」
  「回転をセット（姿勢を維持）」を、Mayaの選択に追従するモデルレスWindowへ変更。
  対象は現在選択の末尾にある基準ノード1個とし、選択変更時は未確定の文字入力を破棄して
  実値を読み直す。XYZのEnter／フォーカス移動による確定、ホイール・上下操作を即時反映し、
  各軸にbdChannelBox本体と独立したStep欄を設ける。OK／Cancelでの確定は廃止。
  既存の`bdUtilCommands`を使用し、scene・保存設定の移行は不要。
- bdChannelBoxの「回転をセット（姿勢を維持）」は画面上部の基準ノード1個だけを
  対象にする。複数選択中のほかのノードへは適用しない。既存のscene・保存設定の
  移行は不要。
- bdChannelBoxの回転属性行では、姿勢維持の回転設定と回転集約を丸め項目より上へ移動。
  回転設定Windowはクリック位置を中心に画面内へ配置し、設定先と補償先を縦2行に並べる。
  XYZ欄は初回マウスフォーカス時に全選択する。scene・保存設定の移行は不要。

### Added

- `bakedanuki > tools`の3項目へ、各ツールの`icon`フォルダに同梱した仮アイコンを追加。
  黒背景・白文字の64px PNGを絶対pathで設定し、Mayaのメニュー画像表示設定に従う。
  画像を差し替えて再登録でき、画像不備では警告して文字だけで起動する。
  `register_menu_item(icon_path=...)`に対応したutilとの同時更新が必要。
  sceneと保存設定の移行は不要。
- 起動時に共通基盤の個人用`prefs/bakedanuki/config.toml`を初回作成する。
  既存メニュー配下への配置は`bd_util`が行い、toolsの3項目と内部UI名は維持する。
  sceneの移行は不要。
- bdChannelBoxの移動・回転属性行へ「移動をセット（子を維持）」と
  「回転をセット（子を維持）」を追加。基準ノードのXYZをlocal属性値またはworldの
  位置・最終姿勢で入力し、直接の子を補償する。ダイアログ内の空間切替では編集中の
  目標値を換算し、sceneは変更しない。回転では子の座標も維持するかと子Jointの
  姿勢補償先を選べる。ダイアログの初期サイズは移動・回転で個別に調整でき、
  回転側の選択欄はラベル幅を揃えて縦に配置する。
  `bdUtilCommands`で1回のUndoに対応する。scene・保存設定の
  移行は不要。
- bdChannelBoxの回転属性行へ「回転をセット（姿勢を維持）」を追加。ダイアログで
  設定先・補償先・XYZ目標値を指定し、`bdUtilCommands`で基準ノードの
  現在姿勢を保ったまま変更する。Jointでは各設定先に二つの補償先を用意する。
  1回Undoに対応。scene・保存設定の移行は不要。
- bdChannelBoxの値編集行へ、`translate`、`rotate`、`rotateAxis`、`jointOrient`の
  XYZを子のworld座標・姿勢を保持して丸めるメニューを追加。表示単位で丸め、
  桁数候補は右クリックした行の表示桁数までとする。`bdUtilCommands`で
  選択ノードを一度のUndoにまとめ、`jointOrient`はJointだけを対象にする。
  scene・保存設定の移行は不要。
- bdChannelBoxの回転属性行へ「回転を集約」を追加。選択したTransform／Jointの現在回転を
  `rotate`、`rotateAxis`、Jointでは`jointOrient`へ集約し、local matrixを維持する。
  lock・入力接続の対象外処理、1回Undo、同値時の無Undoに対応する。scene・設定の移行は不要。
- bdChannelBoxの値編集行へfloat系属性用「小数点の四捨五入」を追加。
  選択属性または表示状態別の全属性について、各選択ノードの実値を表示単位で個別に丸める。
  桁数候補の上限はその行の現在の表示桁数とし、Maya設定の変更は表示更新後に反映する。
  1回Undo、同値時の無Undoに対応。scene・保存設定の移行は不要。
- bdChannelBoxのカスタムフィルター設定モードの表示順一覧でCtrl／Shift複数選択に対応。
  選択属性を相対順と間隔を保って一段ずつ上下に移動し、「除外」も選択全件へ適用する。
  JSON形式と保存設定の移行は不要。保存前の操作はsceneとUndo履歴を変更しない。
- bdChannelBoxのカスタムフィルター設定モードで、属性名のCtrl／Shiftクリックと
  ドラッグによる複数選択に対応。選択中の行のラジオは選択属性すべてに、選択外の行は
  その1行だけに適用する。検索・標準フィルターで隠れた選択は外し、候補一覧の余白で
  選択を解除できる。JSON形式と保存設定の移行は不要。
- bdChannelBoxのカスタムフィルター設定モードで、表示順一覧と属性候補の境界をドラッグして
  表示範囲を調整できる。標準Attribute Filterと検索に一致する候補を、スクロール外も含め
  一括で含める／含めないに変更できる。編集は保存までJSONの作業中データに留まり、
  sceneとUndo履歴を変更しない。JSON形式と保存設定の移行は不要。
- bdChannelBoxの管理画面から共有カスタムフィルターJSONを新規作成して自動登録できる。
  新しい「カスタムフィルター設定」モードで、基準ノード型の属性所属とJSON内の表示順を
  編集・保存できる。保存前の変更確認と共有ファイルの外部変更検出に対応する。
  `node_types`が空のJSONも有効になり、既存定義の移行は不要。設定モードはsceneと
  Undo履歴を変更しない。既存JSONの形式と登録設定はそのまま利用できる。

### Changed

- bdChannelBoxは対象objectが50ノード以上の選択で、全モードのノード固有の表示・編集を
  休止し、理由と49ノード以下への減らし方を画面に表示する。component・plugは数えず、
  DAG instanceの重複は同一nodeとして扱う。49ノード以下へ戻すと自動再開する。
  Mayaの選択・scene・Undoと保存設定の移行は不要。対応するutilと同時更新し、
  `bd_tools.reload_package(reload_util=True)`で反映する。
- bdChannelBoxの通常時間キーへの値入力をMayaのAuto Keyへ連動させ、SDKとAnimation Layerの
  値入力を許可。Auto Key OFFでは一時値だけを変更し、ONではMayaのレイヤ選択に従って
  既存アニメーションへキーを設定する。SDKはAuto Keyによらず一時値の変更のみ。
  数値、上下、Slider、bool、enum、整列、各Paste経路へ同じ方針を適用する。
  constraintはLayerなどの上流にある場合も除外し、一般のpairBlend、Mute、Clip、
  unitConversion、expression等は入力不可を維持する。tooltipに入力方針とレイヤ設定先を表示。
  以前の「常に現在キーを更新」に相当する操作にはMayaのAuto KeyをONにする。
  scene・保存設定の変換は不要。対応するutilと同時更新し、
  `bd_tools.reload_package(reload_util=True)`で反映する。
- bdChannelBoxの基準ノード名欄を、閲覧中は周囲の背景になじむ枠なし表示に変更。
  編集可能なフォーカス中と外部改名との競合中は従来の入力外観を使用する。
  読み取り専用時も文字の選択・コピーは可能。scene・保存設定の移行は不要。
  `bd_tools.reload_package()`で反映できる。
- bdChannelBoxの基準ノード名欄の右に、複数選択時だけ「2 ノード」などの件数を表示する。
  件数は属性編集の対象となるノード数で、名前欄は従来どおり末尾の基準ノードだけを改名する。
  scene・保存設定の移行は不要。`bd_tools.reload_package()`で反映できる。
- bdChannelBoxの上部に、選択末尾の基準ノードだけを改名する名前欄を追加。
  同名衝突はMayaの確定名を表示し、Undo／Redo・外部改名・編集不可状態にも追従する。
  選択切替では旧ノードの未確定入力を破棄し、名前欄のEnterをOutlinerへ伝播させない。
  選択中の名前表示Widgetは`header_label`から`node_name_edit`へ移るため、
  Widgetを直接参照するコードは移行する。scene・保存設定の移行は不要。
  `bd_tools.reload_package()`で反映できる。
- bdChannelBoxの基準ノードを、対象objectを抽出した現在の選択リストの先頭から末尾へ変更。
  ノード名・属性行・表示値・編集可否・接続色、値を揃える操作、値のコピー元、
  表示条件付きペーストとフリーズメニューの判定を同じ末尾ノードへ統一する。
  component・plugの除外と同一nodeの重複除去、Mayaの選択履歴設定は従来どおり。
  選択リスト自体の順序を維持し、複数ノードのアニメーションカーブは元の選択順で対応させる。
  `ChannelBoxController.representative_node_name`で基準名（未選択時は`None`）を取得できる。
  行の`target_names`は基準優先の順となるため、選択順が必要な利用側はcontrollerの
  `node_names`を使用する。
  Maya本体で配置リセット後に再生成されたメニュー区切りを取得し直し、
  フリーズメニューの準備時に削除済みQActionを参照する問題も修正。
  旧仕様で先頭に選んでいた基準ノードは最後に選択する。scene・保存設定の移行は不要で、
  `bd_tools.reload_package()`で反映できる。
- bdChannelBoxの値編集行メニューで「この値に揃える」を
  「表示ノードの値に揃える > 選択属性／全て／Keyable + ChannelBox／Keyable／
  ChannelBox／Hide」へ変更し、アニメーションレイヤ操作と値のコピー・ペーストの間へ移動。
  広い対象範囲は表示ノードの属性状態で決め、検索・表示フィルター・行選択に依存しない。
  属性ごとの未丸め値と従来の編集可否・Undoを維持し、OSクリップボードには触れない。
  sceneの値は変更され得るが、保存設定の移行は不要。
- bdChannelBoxの値編集行と画面余白の右クリックメニューから「表示を更新」を削除。
  通常の値変更は引き続き自動同期し、属性構成の手動再読込が必要な場合はノードを
  一度選択解除して選び直す。内部の`refresh()`は維持するが、行Widgetの`refresh_requested`と
  両メニューの`refresh_action`は廃止。scene・保存設定の移行は不要。
- bdChannelBoxの「表示・ロック」モードでは行の右クリックメニューを廃止し、
  右クリックによる属性選択も行わない。表示・ロックは行内のボタン、
  アニメーションレイヤ操作は値編集モードの行メニューで行う。
  状態行Widgetのメニュー関連属性はなくなるが、scene・保存設定の移行は不要。
- bdChannelBoxのカーブ貼り付け項目を「選択属性」「コピー元と同じ属性」の順に変更。
  属性値の「ペースト」は行メニューと「編集」メニューの両方で2階層へ浅くし、
  「選択属性」の後に「コピー元と同じ属性：全て／Keyable + ChannelBox／Keyable／
  ChannelBox／Hide」を並べる。貼り付け動作と保存設定に変更はなく、移行は不要。
- bdChannelBoxのアニメーションカーブ貼り付けで、属性の型とenum定義の一致制限を撤廃。
  double・角度・距離・bool・enum間でも、キー設定可能な同名属性または選択属性へ貼り付ける。
  ツール独自の値変換・丸めは加えず、Mayaの`pasteKey`の評価に任せる。
  異種型の同名属性を持つ複数ノードも個別に対象判定する。sceneのカーブは変更され得るが、
  保存設定の移行は不要。`bd_tools.reload_package()`で反映できる。

### Added

- `bakedanuki > tools`へ「移動・回転をセット（子を維持）」と
  「回転をセット（姿勢を維持）」を追加。クリック時に各独立ツールの公開`show()`を呼び、
  既存のドック配置とタブ・設定先を使用する。scene・保存設定の移行は不要。
- `bakedanuki`メニューの起動時表示設定に対応。OFFの次回起動では`bd_tools`の自動登録を
  スキップする。現在のセッションのメニューと明示的な`install_menu()`は維持する。
  共有設定は`bakedanuki-util`に保存され、既存設定がない環境ではONのまま動作する。
  再有効化には共通`installer.py`の再D&DとMaya再起動を利用できる。
- Maya Module内の`userSetup.py`からinteractive起動後に`bakedanuki > tools > bdChannelBox`
  を登録する。ユーザーの`userSetup.py`は変更せず、batchでは登録しない。
  メニュー未表示の場合は`bd_tools.install_menu()`で手動登録できる。
  `bd_tools.uninstall_menu()`はtools所有項目だけを解除する。
  開発reloadでは登録済み項目を新しいcallbackで戻す。
  共有メニュー基盤を備えた`bakedanuki-util`との同時更新が必要。
  scene・保存設定の移行は不要。
- bdChannelBoxのAttribute Filterに、ノード型別の正式属性pathを定義したJSONファイルを
  任意数登録できるカスタムフィルターを追加。登録順の並べ替え、ON/OFF、削除、再読込に対応し、
  有効なファイルを標準5項目の末尾へ表示する。登録パス・順序・ON/OFFはユーザー設定へ保存し、
  JSON本体とsceneには書き込まない。属性はJSONの記載順で表示状態に依存せず選び、
  ノード型は完全一致で照合する。未定義ノード型ではKeyable + ChannelBoxへ切り替える。
  既存のフィルター選択と設定はそのまま利用でき、移行操作は不要。
  `bd_tools.reload_package()`で反映できる。
- bdChannelBoxの属性行メニューで、アニメーションカーブ操作の直後に
  「アニメーションレイヤ：追加／除去 > 選択属性／全 Keyable」を追加。
  アニメーションレイヤエディタで選択中の実レイヤすべてを対象にし、値編集・状態編集の
  両モードで利用できる。除去するとそのレイヤ上のキーも失われるが、1回のUndoで戻せる。
  sceneのレイヤ所属とキーに影響するが設定移行は不要。`bd_tools.reload_package()`で反映できる。
- bdChannelBoxの値編集行メニューに「フリーズ > 移動／回転／スケール／全て」を追加。
  基準ノードがtransform系の場合だけ表示し、選択中のtransform系ノードへ
  Maya標準の`makeIdentity -apply true`を適用する。jointの移動は対象外。
  形状・子階層とsceneの値に影響するが保存設定の移行は不要。
  `bd_tools.reload_package()`で反映できる。
- bdChannelBoxの値編集行メニューに「アニメーションカーブ：カット >
  選択属性／全アニメーション属性」を追加。全時間の曲線をMaya標準のキー用clipboardと
  画面内の貼り付け情報へコピーしてから削除する。型の異なる同名属性も対象にし、
  共有曲線は除外する。sceneの曲線と値に影響するが保存設定の移行は不要。
  `bd_tools.reload_package()`で反映できる。
- bdChannelBoxの値編集行メニューに「アニメーションカーブ：削除 >
  選択属性／全アニメーション属性」を追加。選択属性は同名の全選択ノードと明示した
  Hide属性、全属性側は各ノードのKeyable／ChannelBox表示属性を対象にする。
  Maya標準の`cutKey -clear`で全時間のキーを削除し、キー用clipboardは保持する。
  出力先を共有する曲線は除外し、一操作を1回のUndoで戻せる。sceneの曲線と値に
  影響するが保存設定の移行は不要。`bd_tools.reload_package()`で反映できる。
- bdChannelBoxの値編集行メニューへ「アニメーションカーブ：コピー／ペースト」を追加。
  選択属性または各選択ノードのKeyable／ChannelBox表示属性の全時間のキーをコピーし、
  コピー元と同じ正式pathまたは選択属性へ現在時刻から貼り付ける。複数カーブは
  別名属性へ順序だけで割り当てず、複数ノードのコピーは選択順で一対一に対応させる。
  Mayaのキー用clipboardを更新するが、属性値用のOS clipboardは変更しない。
  貼り付けは1回のUndoで戻せる。sceneのキーとカーブに影響し、保存設定の移行は不要。
  `bd_tools.reload_package()`で反映できる。
- bdChannelBoxの値編集行メニューへ「ミュート」「ミュート解除」を追加し、
  それぞれ「選択属性」「全アニメーション属性」から操作できるようにする。
  全属性側は選択ノードのKeyable／ChannelBox表示属性を画面の検索・フィルターと独立して扱い、
  選択属性側はHide属性も明示的に対象にできる。未接続・変更不可の属性は静かに除外する。
  解除時に`force`を使わずミュート状態のキーを保持し、一操作を1回のUndoへまとめる。
  sceneにはMayaのmuteノードが作成され得る。保存設定の移行は不要で、
  `bd_tools.reload_package()`で反映できる。
- bdChannelBoxの値編集行メニューに「キーフレーム／ブレイクダウンフレーム >
  選択属性／全 Keyable」を追加。現在時刻の既存キーも選んだ種別へ切り替える。
  全Keyableは選択ノード自身のKeyable属性、選択属性は選択行と各ノードの対応属性を現在時刻に
  キー設定する。キーを打てない属性は静かに除外し、通常接続にpairBlendを暗黙に挿入しない。
  状態編集モードには表示しない。scene・保存設定の移行は不要。
  toolsのみの変更で、`bd_tools.reload_package()`で反映できる。
- bdChannelBoxの接続色へDriven Key、Expression、Animation Layer、
  Animation Clip（Time Editor）、Muted、Key Altered、Nonkeyableを追加。
  直結元の実接続、muteの有効状態、現在値とカーブ評価値、keyableフラグで判定する。
  ロック色を優先し、実接続はtooltipへ残す。scene・保存設定の移行は不要。
  `MayaPlugInputState`の網羅的な分岐には新状態を追加し、対応する
  `bakedanuki-util`へ更新してください。
- bdChannelBoxの接続色へpairBlendの淡い緑、constraintの淡い青を追加。
  属性自身かcompound親へ直結するノード型で判定し、属性名には依存しない。
  自身または親がロックされた場合は青みのある灰色を優先し、元の接続状態は
  tooltipへ残す。scene・保存設定の移行は不要。新しい`bakedanuki-util`が必要。
- bdChannelBoxの値編集行へ、入力接続を示す6pxの色帯を追加。現在キーは赤、
  時間カーブ上で現在キーがない場合は淡い赤、その他の入力接続は淡い黄、
  未接続はMayaの通常背景色とする。色帯の上下に各1pxの余白を設ける。
  基準ノードの状態を描画し、複数ノードの混在はtooltipへ表示する。
  時刻・キー・接続の変更とUndo／Redoに追従し、値入力可否とは独立する。
  scene・保存設定の移行は不要。対応する`bakedanuki-util`が必要。

- 開いているbdChannelBoxを`bd_tools.reload_package()`の後に自動再表示する。
  `reload_util=True`にも対応し、閉じていたWindowは再表示しない。
  汎用の開閉記録・再表示は`bakedanuki-util`のMaya UI基盤を利用する。

- bdChannelBoxへ単一typed string属性の一行入力を追加。既存の複数ノード・複数行編集、
  混在表示、表示・ロック、検索・表示フィルター、「この値に揃える」、Copy/Paste、
  Undoの規則を適用する。`.otherType`を含む個別属性の特例は設けない。
  Clipboard書込みはschema version 2とし、従来のversion 1は読み込める。
  `ChannelBinding`と行の`editor`の公開union型へstringを追加するため、利用側で
  数値Viewを決め打ちするコードは型を確認してください。scene・保存設定の移行は不要。
  対応する`bakedanuki-util`への更新と`bd_tools.reload_package(reload_util=True)`が必要。

### Changed

- Maya上部の共有メニュー表示名を`bd`から`bakedanuki`へ変更した。
  `bdChannelBox`の起動経路は`bakedanuki > tools > bdChannelBox`となる。
  内部UI識別子と保存設定は維持する。
- bdChannelBoxのキー操作を2階層へ整理し、選択属性を全Keyableより先に表示する。
  コピーの両メニューとStep設定も選択属性を先に揃える。操作対象、scene、保存設定は
  変更せず、`bd_tools.reload_package()`で反映できる。
- bdChannelBoxの属性行の右クリックメニューで、「ロック／解除」を「ロック」、
  「Keyable／ChannelBox／Hide」を「表示」のサブメニューへ整理する。
  操作対象・Undo・scene・保存設定の変更はなく、`bd_tools.reload_package()`で反映できる。
- bdChannelBoxの属性行では、属性名・値・Step・Slider・bool・enum・stringと
  表示／ロック入力欄のどこから右クリックしても、その行の操作メニューを開く。
  一括数値入力中も入力元の行メニューを開き、未確定値はフォーカス移動として確定する。
  Qt標準の右クリック編集メニューは表示しない。キーボードでの文字編集は維持する。
  scene・保存設定の移行は不要。toolsのみの変更で、`bd_tools.reload_package()`で反映できる。
- bdChannelBoxで、対応する既存アニメーション属性の値を編集できるようにする。
  直接接続された単独の時間カーブを対象とし、値が変わる場合に現在時刻のキーを追加・更新する。
  値欄・上下・Slider・bool・enum・「この値に揃える」・Pasteで同じ方針を使い、
  未接続属性は通常の値設定を維持する。Auto KeyのON/OFFには依存しない。
  書込み後は評価済みplugを再取得し、通常値との混在編集も一回のUndoで戻せる。
  Slider中の時刻変更で操作を確定終了し、未確定数値を次の時刻へ持ち越さない。
  lockや未対応の接続、Animation Layer・SDK・pairBlendなどは表示専用を維持する。
  既存scene・保存設定の移行は不要だが、これまで表示専用だった対応キー付き属性が編集可能になる。
  対応する`bakedanuki-util`への更新と`bd_tools.reload_package(reload_util=True)`が必要。
- bdChannelBoxのfloat値欄を90 pxから150 pxへ広げ、
  `1234.123456789123456`の20文字程度を一度に見渡せるようにする。
  Slider付き値欄にも同じ幅を適用し、Step／Sliderの60 pxと欄間6 pxは維持する。
  共通入力列は216 pxとなり、enum・stringもこの幅を使用する。
  属性名を見やすくするため初期Window幅を380 px、最小幅を340 pxに設定する。
  表示小数桁数とMayaの数値精度は変更しない。
  toolsのみの変更で、scene・保存設定の移行は不要。`bd_tools.reload_package()`で反映できる。
- bdChannelBoxの表示・ロック行で`hide`と`lock`の間の伸縮余白をなくし、
  操作欄の幅をボタンの必要幅に合わせる。空いた幅を属性名欄へ戻し、
  パネルを狭くした際も名前が見やすいようにする。scene・保存設定の移行は不要。
- bdChannelBoxのstring入力は、編集中に基準または後続ノードの値が外部変更された場合、
  未確定入力を破棄して基準ノードの最新値へ同期する。入力可能なままの状態通知では入力を
  維持し、同期だけでsceneやUndo履歴は変更しない。設定とsceneの移行は不要。
  対応する`bakedanuki-util`への更新と`bd_tools.reload_package(reload_util=True)`が必要。
- bdChannelBoxのfloat値欄、Step欄、Slider付き値欄は、マウスで初回フォーカスした
  左クリックだけ入力文字全体を選択する。そのまま入力すれば既存値を置換でき、
  フォーカス中の再クリック、横ドラッグの文字選択、上下ボタンは従来動作を維持する。
  utilの汎用opt-in APIを有効化するtools・utilの変更で、scene・保存設定の移行は不要。
- bdChannelBoxの属性選択色を属性名だけへ適用し、float値欄は未選択時と同じ
  Qt paletteを維持する。値欄のフォーカス・文字選択、縦ドラッグによる属性選択、
  複数属性入力は従来どおり利用できる。属性名の右側へ4pxの内側余白を設け、
  属性名と入力Viewの外側spacingを0pxにして、Maya標準と同様に選択色が文字の右側から
  入力欄まで続くようにする。bool・enum・Step・Sliderを含む入力部品の配色を
  属性選択から独立させるtoolsのみの変更で、scene・保存設定の移行は不要。
- bdChannelBoxの属性ごとのStep設定を`bd_channel_box/preferences/main`へ保存し、
  Window再表示・tools/util reload・Maya再起動後へ復元する。識別子は正式な相対属性pathと
  `number`／`distance`／`angle`の組で、現在の表示単位における数値だけを保持する。
  初期値と同じStepは保存せず、radiusは0.1、angleは15、その他は1へ戻る。
  値編集行と画面余白の右クリックメニューへ`Step設定`を追加し、
  `初期値に戻す: 選択属性`、`初期値に戻す: 全ての属性`の順で表示する。
  全属性は画面外の保存値も削除し、選択属性は選択中でStep欄を持つ行だけを戻す。
  成功通知と確認dialogは表示せず、scene・Undo履歴・`reset_layout()`へ影響しない。
  対応する`bakedanuki-util`への更新と`bd_tools.reload_package(reload_util=True)`が必要。
- bdChannelBoxへ属性検索を追加する。Nice Name・属性名・正式pathを大文字小文字を
  区別せず、空白区切りのAND条件で検索し、既存のAttribute Filterと組み合わせる。
  Maya属性・Bindingを再生成せずTable行だけを絞り込み、隠れた行は属性選択から外す。
  設定メニューの「検索欄の表示」で`非表示`／`「全て」の場合のみ表示`／`常に表示`を
  排他的に選択し、初期値は「全て」の場合のみ表示とする。検索欄が見えない間は
  検索条件を適用せず、表示方針だけをuser preferencesへ保存する。
  検索文字列、scene、Undo履歴、Copy/Pasteの全属性・同path対象は変更しない。
  既存設定に表示方針がなければ初期値を使うため、設定移行は不要。
  READMEで未フォーカス時のホイール編集が初期ONと読める説明も、実装どおり初期OFFへ修正する。
- bdChannelBoxの「表示・ロック」で、選択中の行の`key / ch / hide / lock`を
  直接操作した場合に、操作後の状態を選択属性すべてへ適用する。
  選択外の行は従来どおりその行だけを変更し、キーボード操作も同じ対象とする。
  ドラッグのなぞり操作は選択集合へ展開せず、通過行だけを従来の一回Undoで
  変更する。既存の状態Bindingと一括操作APIを使うtoolsのみの変更で、
  scene・保存設定の移行は不要。
- bdChannelBoxの「編集」メニューと値編集モードの属性名メニューへ、
  `コピー > 選択属性／全属性`と`ペースト > コピー元と同じ属性／選択属性`を追加。
  Copyは基準nodeの全対応属性または選択属性の未丸め値と型・単位・enum定義を
  OSクリップボードへ保存する。「コピー元と同じ属性」は`全て`に加え、貼り付け時の
  基準nodeを使う`keyable + channelbox`／`keyable`／`channelbox`／`hide`で
  コピー済みの正式pathを絞り込み、同じpathを全選択nodeへ適用する。
  「選択属性」は複数のコピー値なら選択属性と同じ正式pathだけを1個または複数nodeへ適用する。
  コピー値が一つなら、「選択属性」はその値を選択した互換属性すべてへ展開する。
  Paste時にコピー元pathを改めて右クリックする必要はない。表示行順・クリック順による
  対応付けは行わず、欠落・型違い・enum定義違い・編集不可属性を内部結果の対象外とし、
  適用対象は全件事前検証・一回Undo・失敗時復旧で変更する。
  一値の選択属性Pasteは、数値・距離・角度・boolを同じ型区分、enumを同じ定義へだけ展開する。
  Pasteの成功・部分適用・対象0件では画面へ操作通知を出さず、以前の通知を消去する。
  clipboardの不正形式など、処理を開始できない場合だけ簡潔なエラーを表示する。
  表示条件で0項目になった場合はsceneとUndo履歴を変更しない。
  OSクリップボードを使うため別Maya process間でも搬送できる。
  対応する`bakedanuki-util`への更新が必要。scene・保存設定の移行は不要。
- bdChannelBox上部へ「設定」メニューを追加し、「未フォーカス時のホイール編集」で
  数値の値欄・Step欄・enum欄のマウスオーバー操作をまとめてON／OFFできるようにする。
  初期値はOFFとし、OFFではフォーカス中だけ値を変更して、未フォーカス時のホイールを
  一覧のスクロールへ渡す。通常行・Slider付き行の値欄とenum欄へ適用し、行の再構築後も維持する。
  OFFでも値欄がホイール入力時に自動でフォーカスを取得して値を変更する不具合を修正する。
  クリック・Tabでフォーカスを得た欄の操作と、ON時の従来動作は維持する。
  選択は配置と別のuser preferencesへ保存し、Maya再起動後も復元する。
  `reset_layout()`、scene、Undo履歴には影響しない。Slider本体とboolは対象外。
  対応する`bakedanuki-util`への更新と`bd_tools.reload_package(reload_util=True)`が必要。
- bdChannelBoxで選択中の複数属性へ、既存の値欄の上下操作、Slider、bool、enum入力を一括適用する。
  上下操作は操作元のStepから求めた同じ表示増減量を各数値の現在値へ加え、値の差を維持する。
  Sliderは選択数値を同じ表示値へ揃え、1ドラッグを1回のUndoへまとめる。
  boolは同じ状態へ揃え、enumは操作元と項目定義が一致する選択属性だけへ適用する。
  Step欄の入力は、選択中でStep欄を持つ属性へ同じ表示stepを反映し、各行の増減方式を維持する。
  Step欄はクリック前のマウスオーバー中もホイール操作を受け付ける。
  異なる型や互換性のない行、Step欄のない行は対象外として理由を表示する。
  Stepだけの変更は属性値とUndo履歴へ影響しない。
  対応する`bakedanuki-util`への更新が必要。既存scene・保存設定の移行は不要。
- bdChannelBoxの一覧・属性名・入力部品の周囲をMaya UIの通常背景色へ変更。
  数値・Stepなどの入力欄の暗い背景と、選択中の属性名の青い強調表示は維持し、
  入力箇所とOFFのboolチェックボックスを見分けやすくした。
  toolsのみの変更で、既存API・scene・保存設定の移行は不要。
- bdChannelBoxの属性一覧を`QTableView`とdelegateへ移行し、既存の行Viewを常時表示する。
  Ctrl／Shift・属性名ドラッグ・値欄の縦ドラッグによる複数属性選択を追加。
  選択属性への数値文字入力・貼付けを、各行の表示単位で換算して一括適用する。
  Enter／フォーカス移動で確定、Escapeで取消。全対象を事前検証し、書込み失敗時は復旧し、
  成功時は全属性・全ノードを1回のUndoへまとめる。属性選択だけでは書き込まない。
  「この値に揃える」を選択した各属性の基準ノード値への一括操作へ拡張し、
  両モードへロック／解除・Keyable／ChannelBox／Hideの選択メニューを追加する。
  この初回変更時点では上下・Step・Slider・bool・enumの通常操作を1行へ適用した。
  対象ノードの変更で属性選択を解除し、同じノードの表示更新・Undoでは残存する属性の選択を維持する。
  `widget.scroll_area`の型は`QScrollArea`から`ChannelTableView`へ変更。
  内容の取得は`widget.scroll_area.widget()`から`widget.table_view.viewport()`へ移行する。
  Maya側のviewport交換後も再構築できるよう、行の親は使用時に取得する。
  `row_widgets`、各行の`editor`、公開`show()`とWindowの復元入口は維持する。
  `ChannelRow` / `ChannelStateRow`の直接構築時は対応ノード名の`target_names`引数を追加する。
  同時変更の`bakedanuki-util`への更新が必要。scene・保存設定の移行は不要。
- bdChannelBoxの選択切替を軽くするutilの属性検索・step入力欄初期化の改善に対応。
  属性検索は一意な名前を直接取得し、step欄は生成途中の不要な極小値表示を省く。
  値・状態の編集、Undo、精度、表示順、選択監視は維持する。
  `bakedanuki-util`の更新が必要。既存API・scene・保存設定の移行は不要。
- ツール名をbdChannelBox、公開packageを`bd_tools.bd_channel_box`へ統一。
  Windowタイトル、workspaceControl ID、復元入口、設定path、テスト、ドキュメントも
  新名称に揃える。pre-1.0.0の未公開ツールのため互換用の入口は設けない。
- bdChannelBoxの先頭10属性をvisibility、translate X/Y/Z、rotate X/Y/Z、
  scale X/Y/Zへ変更し、残りの相対順を維持。
  優先順を`bd_tools.bd_channel_box.config.ATTRIBUTE_PRIORITY_PATHS`へ分離し、
  `config.py`のtupleを編集してtoolsを再読込みすると変更できるようにした。
  両モード・全フィルターへ共通適用し、既存呼出し・scene・保存設定の移行は不要。
- bdChannelBoxの`lock`へ左ドラッグでのなぞり操作を追加。
  開始時がOFF・混在ならロック、ONなら解除へ通過行を揃え、往復でも再反転しない。
  ラジオボタンと操作対象を分離し、一操作を一回のUndo／Redoにまとめる。
  対応する`bakedanuki-util`への更新が必要。既存の呼出し・scene・保存設定の移行は不要。
- bdChannelBoxの`key / ch / hide`へ左ドラッグでのなぞり選択を追加。
  通過した表示中の有効なボタンを選択し、一操作を一回のUndo／Redoにまとめる。
  なぞり中のフィルター再構築は終了まで保留し、選択・scene・属性構成の変更では終了する。
  ラジオボタン操作中の`lock`変更と自動スクロールは対象外。対応する`bakedanuki-util`への更新が必要。
  既存の呼出し・scene・保存設定の移行は不要。
- bdChannelBoxの表示状態入力を`key / ch / hide`のラジオボタンへ変更し、
  ロックの表記を`lock`へ変更。設定モードの操作欄を200 pxに広げる。
  混在時は3つとも未選択にし、既存の印とtooltipで示す。一括操作・Undo／Redoは維持する。
  Viewを参照するコードは`display_combo`から`display_buttons`へ移行し、
  状態名（`"keyable"`、`"channel_box"`、`"hidden"`）をキーにしたボタンの
  `isChecked()`／`click()`を使う。
  値編集は156 pxを維持し、scene・保存設定の移行やutilの追加変更は不要。
- bdChannelBox上部のComboBoxへ`Mode:`と`Attribute Filter:`のラベルを追加。
  ラベルは右揃えの共通列へ配置し、選択欄の左端と幅を揃える。
  操作・scene・保存設定の変更や移行は不要。
- bdChannelBoxの属性表示を、visibilityからtransform・jointの指定32属性、
  drawOverride配下、その他の順へ変更。存在し、フィルターに一致する属性だけを
  両モード共通の順で表示し、drawOverride内はoverrideEnabledを先頭にする。
  残りのdrawOverride内とその他の属性は元の相対順を維持する。
  tools内の表示方針だけを変更し、sceneの属性順・値・状態は変更しない。
  scene・保存設定の移行やutilの追加変更は不要。
- bdChannelBoxの値同期を高速化したutilに対応。bool・float・enumの一括Bindingは
  変更に関係する属性だけを再同期し、複数選択時も通知nodeの対象だけを照合する。
  「全て」表示時の無関係な行の再読取りを抑える。UIの操作方法・公開APIは変更しない。
  利用には同時変更の`bakedanuki-util`を更新すること。scene・保存設定の移行は不要。
- bdChannelBoxの縦スクロールバーを必要時だけ表示する。モードやフィルターにより
  名前列の幅・入力列の位置が変わることを許容し、入力グループの156 pxは維持する。
  scene・保存設定の移行は不要。
- bdChannelBoxのbool入力をutilの`BoolCheckBox`へ変更し、属性名のすぐ右へ左詰めにする。
  行の`editor`を直接操作するコードは`BoolComboBox`から`BoolCheckBox`へ型判定を移行し、
  `currentText()` / `setCurrentIndex()`を`isChecked()` / `setChecked()`へ置き換える。
  初期Window幅を420から320 px、最小幅を360から280 pxへ縮小し、
  `ui.py`の`_INITIAL_WIDTH`・`_MINIMUM_WIDTH`と`widget.py`の
  `_NAME_FIELD_MINIMUM_WIDTH`で属性名側の余白を調整できるようにする。
  sceneの移行は不要。保存配置を縮める場合はパネル幅の変更か`reset_layout()`を使用する。
- bdChannelBoxのfloat値欄を110 pxから90 pxへ縮小し、step欄・Sliderを共通の
  60 pxに固定する。Slider行はutilの`layout_order="value_slider"`を使って
  `[Value][Slider]`へ変更し、通常float行の`[Value][Step]`と値欄の位置を揃える。
  数値入力グループを156 pxで右寄せし、画面を広げても数値入力後方に余白を作らない。
  値、scene、設定ファイルの移行は不要。
- bdChannelBoxの値欄・step欄の単位文字（cm / degなど）を非表示にする。
  Slider付きの値欄にも適用する。表示単位への数値換算とstepの扱いは維持し、
  scene・設定ファイルの移行は不要。
- bdChannelBoxをutilの `MayaDockableWindowController` に移行し、Maya右側へのドッキング、
  タブ化、floating、workspaceControlによる配置復元へ対応。
  `show()` の戻り値は同名の `ChannelBoxWindow` だが、基底は `QDialog` から
  `MayaDockableWindow` へ変更する。`exec()` / `reject()` は使用せず、表示は `show()`、
  終了はタイトルバーまたは新しい `bd_channel_box.close()` / `dispose()` へ移行する。
  Escapeではパネル全体を閉じない。closeで入力・callbackを破棄し、再表示で作り直す。
  固定IDは `bdChannelBoxWindowWorkspaceControl`、復元入口は
  `bd_tools.bd_channel_box.ui.restore`。`reset_layout()` はutilの統合reset APIを利用する。
  初回は右ドックから開始し、保存したworkspaceControl配置を再利用する。
  sceneの移行は不要。保存配置は明示的な `reset_layout()` で削除できる。
- bdChannelBoxの常設ボタン・件数欄・「基準:」表記を削除し、属性名を右揃えに変更。
  混在は属性名の左の小さな印、対象数と除外理由はtooltipへ集約する。
  属性名の右クリックメニューへ「この値に揃える」「表示を更新」を移し、余白からも更新可能。
  初回Windowサイズを420×360へ縮小する。保存済みの配置とsceneの移行は不要。
  UI部品を直接参照するコードでは `align_button` を `align_action`、`refresh_button` を
  `refresh_action` へ置き換え、操作は `trigger()` で実行する。
  `status_label.toolTip()` は `name_label.toolTip()` へ移行する。
  `widget.refresh()` とBindingによる一括編集APIは引き続き利用できる。

### Added

- bdChannelBoxへ両モード共通の表示フィルターComboBoxを追加。
  全て／keyable + channelbox／keyable／channelbox／hideの5種類を、基準ノードで判定する。
  channelbox単独は非keyableの表示属性を指す。値編集はkeyable + channelbox、
  表示・ロックは全てを初期値とし、モードごとの最終選択をWindow内だけで保持する。
  Hide属性の値入力にも対応し、従来のロック・入力接続による編集制限を維持する。
  絞り込み中の状態変更は全対象への操作完了後に表示へ反映し、Undo／Redoにも追従する。
  `controller.attribute_filter`、`set_attribute_filter()`、`ChannelAttributeFilter`、
  `widget.filter_combo`を追加。scene・保存設定の移行やutilの追加変更は不要。
- bdChannelBoxに「値編集／表示・ロック」の切替を追加。表示・ロックでは非表示の
  対応scalarも列挙し、Keyable／ChannelBox／HideとLock／Unlockを独立して一括操作する。
  混在表示、外部変更、Maya標準Undo／Redoへ対応し、全てフィルターではHideへ変更した行も維持する。
  属性定義によりkeyableとchannelBoxが両方Trueの属性は、Maya標準Undoで復元できないため
  表示変更だけを不可とし、理由をtooltipへ表示する。基準属性なら行の表示変更を停止し、
  後続の対象だけなら除外する。ロック／解除は通常どおり操作でき、自動修正や移行は行わない。
  両モードで右列156 pxを共用し、長い属性名は省略表示とtooltipへ変更する。
  名前欄の幅調整定数は`_NAME_FIELD_MINIMUM_WIDTH`から`_NAME_FIELD_PREFERRED_WIDTH`へ変更する。
  モード切替はscene・Undoを変更せず、Window内のstep設定を維持する。
  utilの`MayaChannelStateBinding`が必要なため、toolsとutilを組み合わせて更新する。
  `controller.rows`へ`ChannelStateRow`、`widget.row_widgets`へ`AttributeStateRowWidget`が
  加わるため、値編集用の`binding`／`editor`を参照する利用コードは`isinstance()`で
  行の型を絞ること。既存scene・保存設定の移行は不要。
- bdChannelBoxのenum入力を追加。utilの`EnumComboBox` / `MayaEnumPlugsBinding`を使用し、
  同じ正式属性path・整数値と項目名の対応を持つ対象へ、明示操作時だけ一括適用する。
  飛び番・未定義値・混在・定義不一致の除外、Undo／Redo、選択肢の終了に対応する。
  対応するutilのenum属性列挙と`read_enum_definition()`が必要なため、両packageを更新する。
  行の`editor`と`ChannelBinding`のunionにenum型が加わる。数値Viewとしてアクセスする
  利用コードは`isinstance()`で型を絞ること。既存scene・保存設定の移行は不要。

- bdChannelBoxのSlider以外のfloat系入力に、utilの `FloatValueStepSpinBox` を採用。
  距離・通常数値はmultiplicative/1、角度はadditive/15、radiusはmultiplicative/0.1とする。
  stepの変更は値やUndo履歴へ影響せず、選択変更やUndo後もWindow内で属性ごとに保持する。
  step欄は名称の接頭辞を省略し、4桁程度を表示できるコンパクトな幅とする。
  行の公開 `editor` 型が `FloatSpinBox` から複合Viewへ変わるため、利用コードでは
  値欄へのアクセスを `editor.spin_box`、刻み幅の変更を `editor.setSingleStep()` へ移行する。
  対応するutilの更新が必要。既存scene・設定ファイルの移行は不要。
- 最初のツール `bd_tools.bd_channel_box` を追加。`show()` で通常Windowを開き、
  選択リストの先頭を基準に bool・float・距離・角度の属性を入力できる。
  `keyable OR channelBox` のscalar属性を表示し、両側hard limit付きfloatにはSliderを使う。
  ユーザーの編集時だけ、同名・同種の編集可能な属性へ一括適用する。
  混在値の表示、明示的な「揃える」、Undo / Redo、選択追従、close / reload時の解放に対応。
  キー付き・入力接続済み・ロックされた属性は表示専用とする。
  利用には同時追加された `bakedanuki-util` の複数属性Binding・inspection APIが必要。
  新規ツールのため既存sceneの移行は不要。配置設定は `bd_channel_box/windows/main` に保存する。
- Maya Module 形式の `bd_tools` パッケージ骨格。
- Black、Pyright、pytest、VS Code の開発環境。
- Maya 2025 / 2026 / 2027 用のテストと開発 launcher。
- module reload 前の終了処理を登録できる reload lifecycle。
- `bakedanuki-util`、`bakedanuki-rig` との依存方向と責務境界。
