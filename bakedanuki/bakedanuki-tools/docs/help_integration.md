# ヘルプ連携仕様

## 状態と対象

2026-11-08に確定した、util・tools・webで共有する実装仕様です。
本書は実装済みの共通基盤と、今後追加するtools・webの契約を定義します。
utilのサイトJSON・公開定数・URL組み立て・汎用ブラウザーAPIは実装済みです。
toolsのページ対応表・ヘルプAPI・公開原稿・ヘルプUIと、webの集約処理は未実装です。
現在の公開先はHello Worldの確認まで完了しており、個別ヘルプは未公開です。

初回はbdChannelBoxの1ページを対象にします。toolsの他のツール、utilの利用ガイド、
rig、過去版の切り替えは、必要な原稿と実装を揃えた段階で追加します。
本仕様の正本は当面このファイルとし、他リポジトリへ同じ仕様を複製しません。
文書自体の配置は、下記の実行時の依存を意味しません。

## 決定事項

| 項目 | 契約 |
| --- | --- |
| サイト基点URL | `https://web.bakedanuki.workers.dev/` |
| CloudflareのWorker名 | `web` |
| アカウント側サブドメイン | `bakedanuki.workers.dev` |
| 初回のページID | `bd_channel_box` |
| 初回の公開パス | `tools/tool/bd-channel-box/` |
| 初回の完成URL | `https://web.bakedanuki.workers.dev/tools/tool/bd-channel-box/` |
| URLの正本 | utilのJSON。Python定数とWeb設定はその値から作る |
| 個別ページの正本 | 各パッケージのページ対応表・Markdown・画像 |
| 分類 | カテゴリはメタデータで管理し、個別ページの公開パスに含めない |
| 公開する版 | Web側で明示的に採用した公開済みReleaseのタグとコミット |
| 初期の版数 | 掲載パッケージごとに1つ。全パッケージの版番号を揃える必要はない |
| 公開基盤 | Starlightで静的サイトを生成し、Cloudflare Workersへ配置する |

`/tools/`はパッケージ全体の入口、`/tools/tool/`はツールの区画です。
パッケージ紹介・導入・設定・FAQなどを`/tools/`以下に追加できます。
原稿の配置、URL、メニューの階層を一致させる必要はありません。

## 責務と依存方向

| 所有者 | 所有するもの |
| --- | --- |
| util | 共通サイト情報、URLの組み立て、汎用ブラウザー起動 |
| tools | 自分のページID・パス・分類・原稿・画像、ヘルプ操作のUIと通知 |
| rigなどの利用側 | 自分のページ情報とUI。toolsを経由せずutilの共通APIを利用 |
| web | 採用Releaseの一覧、原稿の集約、分類名・表示順、共通ページ、デザイン、生成・公開 |

実行時は`bd_tools -> bd_util`、`bd_rig -> bd_util`を維持します。
utilはtools・rig・webをimportせず、tools・rigもwebをimportしません。
webはサイト生成時に各パッケージのReleaseからファイルを取得するだけです。

webはPythonパッケージを実行・importせず、JSONと原稿を直接読み取ります。
共通情報の読み取り処理自体はMaya・Qtへの依存を持たせませんが、
現在の`bd_util/__init__.py`にはMaya依存があります。
通常のPythonから`import bd_util.site`できることを、Web連携の前提にしません。

利用者の環境から原稿取得用のGitHub APIへ接続する処理や、
ヘルプの存在を調べるHTTPリクエストは行いません。
ネットワークアクセスを伴う閲覧は、利用者が明示的にヘルプを開いたときに行います。

## ファイルの配置

以下のうちutilの項目は実装済みで、toolsとwebの項目は今後追加する配置です。
未着手の項目について、空のパッケージやJSONだけを先に作成しません。
`package root`はMaya Module定義が指すフォルダを指し、リポジトリ直下とは区別します。

| 用途 | リポジトリからの相対パス |
| --- | --- |
| utilのサイト情報 | `bakedanuki/bakedanuki-util/python/bd_util/site/site.json` |
| utilの公開API | `bakedanuki/bakedanuki-util/python/bd_util/site/__init__.py` |
| Web関連の公開入口 | `bakedanuki/bakedanuki-util/python/bd_util/py/web/__init__.py` |
| 汎用ブラウザー起動 | `bakedanuki/bakedanuki-util/python/bd_util/py/web/browser.py` |
| 共通のURL検証 | `bakedanuki/bakedanuki-util/python/bd_util/py/web/_url.py` |
| toolsのページ対応表 | `bakedanuki/bakedanuki-tools/python/bd_tools/help/pages.json` |
| toolsのヘルプAPI | `bakedanuki/bakedanuki-tools/python/bd_tools/help/__init__.py` |
| 公開用原稿・画像 | `bakedanuki/bakedanuki-tools/docs/user/`以下 |
| 初回の原稿 | `bakedanuki/bakedanuki-tools/docs/user/bd-channel-box/index.md` |
| 初回の画像 | 同じ`bd-channel-box/`内の`images/`以下 |
| webの採用版一覧 | `bakedanuki-web`リポジトリの`config/releases.json` |
| webの分類表示 | 同リポジトリの`config/categories.json` |
| webの集約処理 | 同リポジトリの`scripts/collect-help.mjs` |

toolsのpackage rootは`bakedanuki/bakedanuki-tools/`、
utilのpackage rootは`bakedanuki/bakedanuki-util/`です。
`bd_util.py.web`の`__init__.py`は公開APIの取りまとめに留め、
ブラウザー起動の実装は`browser.py`、siteと共有するURL検証は`_url.py`へ配置します。
現在の`docs/architecture.md`、`docs/testing.md`などは開発向け文書として維持し、
`docs/`全体を利用者向けサイトへ自動公開しません。

## 共通JSONの規則

`site.json`、`pages.json`とwebの設定は、UTF-8・BOMなしのJSONとします。
コメント、重複キー、未定義フィールド、未知の`schema_version`を許可しません。
`schema_version`は真偽値ではなく整数の`1`です。
読み取り側は勝手な補正・上書き・自動移行をせず、原因と対象ファイルが分かる形で失敗します。
JSONのキーの並び順に意味を持たせません。表示順が必要な箇所だけ配列を使用します。

これらは配布する固定情報です。個人用の`config.toml`、Maya preferences、
UiStateManager、scene、Undoの状態から独立させます。

### utilのsite.json

```json
{
  "schema_version": 1,
  "base_url": "https://web.bakedanuki.workers.dev/"
}
```

| フィールド | 型 | 意味 |
| --- | --- | --- |
| `schema_version` | 整数 | この形式の版。初版は`1` |
| `base_url` | 文字列 | 全パッケージが利用するサイト基点URL |

`base_url`はHTTPSの絶対URLとし、ホストと末尾の`/`を必須にします。
ユーザー情報、クエリ、フラグメント、空白・制御文字を含めません。
共通パスは許可します。例えばGitHub Pagesへ移る場合の
`https://example.github.io/bakedanuki-web/`も基点にできます。
共通パスの各セグメントは、後述のページパスと同じ文字の規則に従います。
原稿・Pythonコード・webの設定に、別の正本として同じURLを手書きしません。
実際のドメイン接続・転送・公開先の設定はweb側の責務です。

### toolsのpages.json

初回の登録内容は次の1件です。

```json
{
  "schema_version": 1,
  "package": "bd_tools",
  "pages": {
    "bd_channel_box": {
      "path": "tools/tool/bd-channel-box/",
      "source": "docs/user/bd-channel-box/index.md",
      "categories": ["util"]
    }
  }
}
```

| フィールド | 型 | 意味 |
| --- | --- | --- |
| `schema_version` | 整数 | 初版は`1` |
| `package` | 文字列 | 所有するPythonパッケージ名。ここでは`bd_tools` |
| `pages` | オブジェクト | ページIDをキーにした対応表 |
| `path` | 文字列 | サイト基点URLからの相対的な公開パス |
| `source` | 文字列 | 所有パッケージのpackage rootを基準にした原稿パス |
| `categories` | 文字列の配列 | 用途別の分類ID。空配列・複数所属を許可 |

`pages`は1件以上を持ち、各項目は`path`・`source`・`categories`をすべて持ちます。
`package`は`[a-z][a-z0-9_]*`とし、Web側の採用版一覧のキーと一致させます。
ページIDは`[a-z][a-z0-9_]*`とし、初回は既存のツールIDを使用します。
`bd_child_compensated_set`、`bd_rotation_preserving_pose`なども、
実際に原稿を追加する段階で登録します。未作成原稿の仮登録はしません。

`path`は`tools/`で始まり、tools内でも全サイトでも一意にします。
同じ`source`を複数ページへ割り当てず、複数分類から同じページへリンクします。
分類を変更しても`path`は変更しません。
分類IDは`[a-z][a-z0-9-]*`とし、同じ配列内の重複を禁止します。
分類表示順は配列から決めず、webの設定に従います。
`util`分類は「汎用・補助」の意味であり、`bd_util`への依存を示す値ではありません。

`source`は`docs/user/`配下の`.md`ファイルを指す、`/`区切りの相対パスです。
絶対パス、バックスラッシュ、`.`・`..`のセグメントを禁止します。
例えば上の値は、リポジトリ内の
`bakedanuki/bakedanuki-tools/docs/user/bd-channel-box/index.md`を指します。
原稿の移動時は`source`だけを更新でき、URLは維持できます。
PythonでURLを得る際には、この原稿ファイルの実在を要求しません。

### URLのページパス

ページパスは`/`から始めず、末尾に`/`を付けます。
各セグメントは`[a-z0-9]+(?:-[a-z0-9]+)*`とし、
空のセグメント、`.`、`..`、バックスラッシュ、`:`、`?`、`#`、
`%`、空白・制御文字を許可しません。
絶対URLやURLエンコード済みのパスをページパスとして渡しません。

`pages.json`の`path`に空文字列は許可しません。
共通APIの`build_url("")`だけは、サイトのトップページを表す指定として許可します。
先頭の`/`を除去するなどの暗黙の補正はせず、誤った指定はエラーにします。
パスの結合ではサイト基点の共通パスを保持し、
引数によってホストや共通パスを置き換えないようにします。

| 基点 | ページパス | 結果 |
| --- | --- | --- |
| `https://web.bakedanuki.workers.dev/` | `tools/tool/bd-channel-box/` | `https://web.bakedanuki.workers.dev/tools/tool/bd-channel-box/` |
| `https://example.github.io/bakedanuki-web/` | `tools/tool/bd-channel-box/` | `https://example.github.io/bakedanuki-web/tools/tool/bd-channel-box/` |

## Pythonの公開APIとキャッシュ

以下のAPI名・型を初期実装の契約とします。
`bd_util.site`と`bd_util.py.web`は実装済みで、`bd_tools.help`は実装予定です。

| 公開場所 | 名前・型 | 役割 |
| --- | --- | --- |
| `bd_util.site` | `SITE_BASE_URL: Final[str]` | 検証済みのサイト基点URL |
| 同上 | `build_url(page_path: str) -> str` | 検証した相対パスと基点からURLを組み立てる |
| `bd_util.py.web` | `open_url(url: str) -> bool` | HTTP/HTTPSの絶対URLをOSのブラウザーへ渡す |
| `bd_tools.help` | `HelpPage` | ページID・path・source・categoriesを持つ値型 |
| 同上 | `PAGES: Final[Mapping[str, HelpPage]]` | 読み込み済みのページ対応表 |
| 同上 | `get_url(page_id: str) -> str` | 登録ページIDに対応する完成URLを返す |
| 同上 | `open_page(page_id: str) -> bool` | 登録URLを汎用ブラウザーAPIで開く |

`HelpPage`は`frozen=True`のdataclassとし、`page_id`・`path`・`source`は`str`、
`categories`は`tuple[str, ...]`とします。
`PAGES`は`MappingProxyType`等の読み取り専用Mappingで公開し、
元の可変辞書を利用側に渡しません。
各公開モジュールに`__all__`と明示的な型注釈を整えます。

`bd_util.site`の初回読み込み時に、同梱`site.json`を一度読み込み・検証し、
`SITE_BASE_URL`へ格納します。各所はその定数を参照します。
Python側にもURL文字列を手書きする構成にはしません。
`Final`は再代入を行わない型契約であり、利用者向けの変更APIは設けません。
ファイルの自動監視、毎回の再読込、追加のキャッシュ管理APIは作りません。

`bd_tools.help`も初回読み込み時に同梱`pages.json`を読み、`PAGES`へ保持します。
この読み込みだけではutil・Maya・Qt・ツールUIを読み込みません。
`get_url()`を呼ぶ段階でutilのサイトAPIを使用し、`open_page()`を明示的に
呼んだときだけブラウザーAPIを使用します。
`import bd_tools`時のutil・Maya・Qtを読み込まない既存契約も維持します。

実装後の利用例です。Web側ではこのPythonコードを使いません。

```python
from bd_util import site
from bd_tools import help as tool_help

print(site.SITE_BASE_URL)
print(tool_help.get_url("bd_channel_box"))
```

JSONの読込失敗は`OSError`、内容・形式の不正は`ValueError`として通知し、
対象ファイルと不正な項目が分かるメッセージを付けます。
未知のページIDは`KeyError`、不正なURL・ページパスは`ValueError`です。
空文字列・仮URL・サイトトップへの代替で不備を隠しません。

汎用`open_url()`はサイト情報・ページIDを知らず、渡されたHTTP/HTTPSの絶対URLを
`webbrowser.open(url, new=2)`へ渡します。新規タブ等の最終動作はブラウザーに従います。
戻り値は起動依頼の成否であり、HTTP成功・本文表示・サイトの存在を保証しません。
`webbrowser.Error`や`OSError`は握り潰しません。
UI側は`False`や例外を既存の通知経路へ渡し、Mayaのscene・Undoを変更しません。

### reload

toolsのページ対応表だけを変えた場合は`bd_tools.reload_package()`を使います。
utilのJSON・URL処理も変えた場合は`bd_tools.reload_package(reload_util=True)`を使い、
toolsのUI破棄後にutil→toolsの順でモジュールと定数を作り直します。
ファイルを書き換えただけでは保持値を変更しません。

長く保持する処理では`site.SITE_BASE_URL`や`tool_help.get_url()`のように
モジュール経由で参照し、定数のコピーを各所へ散らしません。
モジュールや関数を外部変数に保持していた場合は、既存のreload方針どおり取り直します。
複数の利用側パッケージが稼働している場合は、[Reloading](reloading.md)に従って
全利用側を含む入口を使い、その入口が未整備ならMayaを再起動します。

## 公開原稿と画像

公開原稿はUTF-8のMarkdownとし、初回は`.md`だけを扱います。
先頭のfrontmatterは必須の`title`と任意の`description`のみを受け付けます。
タイトルや見出しは日本語で記述できます。
公開パスの正本は`pages.json`とし、原稿には`slug`や完全なヘルプURLを重複記載しません。
`draft`を含む他のfrontmatterフィールドも初版では使用しません。
公開しない下書きは対応表に登録せず、リリース準備時に原稿と登録を同時に揃えます。

```markdown
---
title: bdChannelBox の使い方
description: 起動方法と基本的な属性編集の操作
---

## 起動する

MayaのbakedanukiメニューからbdChannelBoxを開きます。

## 画面の見方

![bdChannelBoxの画面](./images/main.png)
```

画像は原稿からの相対パスで参照し、解決後も`docs/user/`内に収めます。
初版の同梱画像は`.png`・`.jpg`・`.jpeg`・`.webp`・`.gif`・`.svg`です。
ルート相対URLで画像を指す方式を避け、公開基点の共通パスを変えても参照を保ちます。
相対リンク先のMarkdownは対応表へ登録された原稿に限定します。
Web集約時に、リンク先の`path`へサイト基点の共通パスを一度付けた
ルート相対URL、または`build_url()`相当の完成URLへ変換します。
例えば共通パスが`/bakedanuki-web/`なら、リンク先を
`/bakedanuki-web/tools/tool/bd-channel-box/`とします。
`tools/tool/.../`をそのまま現在ページからの相対リンクとして使いません。
同一ページ内・ページ間のアンカーも維持します。
外部への通常のHTTPSリンクは本文に記載できます。

webの集約処理は、登録されたMarkdownと参照する画像だけをコピーします。
packageごとに`src/content/docs/imported/<package>/`以下へ
`docs/user/`内の相対構造を保って配置し、各原稿に対応表由来の`slug`を付けます。
例えば公開パス`tools/tool/bd-channel-box/`から、
`slug: tools/tool/bd-channel-box`を生成します。
元の原稿は書き換えず、生成用コピーはGitへ登録しません。

`slug`はフォルダ由来のページIDを上書きします。
単にtoolsフォルダへ原稿をコピーすれば公開パスが確定する、という実装にはしません。
未登録Markdown・開発文書・未参照画像を一緒に公開しません。
ソースや画像の不存在、シンボリックリンクを含む公開原稿root外への参照は、
release準備・Web生成の検証で失敗させます。
Mayaの実行時には原稿・画像の存在検証を行いません。

## webの設定と公開処理

以下のJSONと集約処理はbakedanuki用に設ける契約であり、
Starlightが標準で読み込む設定ファイルではありません。

### config/releases.json

採用版はwebリポジトリで履歴管理します。
次のタグとSHAは形式を示す仮の値であり、実際の公開版を表しません。
初回のWeb実装では、本仕様のデータが含まれる公開済みReleaseへ置き換えます。

```json
{
  "schema_version": 1,
  "packages": {
    "bd_util": {
      "repository": "AkihiroMamiduka/bakedanuki-util",
      "tag": "v0.1.0",
      "commit": "1111111111111111111111111111111111111111",
      "package_root": "bakedanuki/bakedanuki-util",
      "site_data": "python/bd_util/site/site.json"
    },
    "bd_tools": {
      "repository": "AkihiroMamiduka/bakedanuki-tools",
      "tag": "v0.1.0",
      "commit": "2222222222222222222222222222222222222222",
      "package_root": "bakedanuki/bakedanuki-tools",
      "pages": "python/bd_tools/help/pages.json"
    }
  }
}
```

`packages`のキーは`[a-z][a-z0-9_]*`のPythonパッケージ名です。
各項目は`repository`・`tag`・`commit`・`package_root`を必須とし、
`site_data`は`bd_util`だけに必須とし、他の項目への指定は禁止します。
`bd_util`はサイト情報の供給元として、利用ガイドがなくても必ず含めます。
`pages`は公開原稿を持つ項目に指定し、その対応表の`package`との一致を確認します。
utilに利用ガイドを追加する場合も、その項目に`pages`を指定できます。
その他のパッケージは、原稿を掲載するものだけを一覧へ入れます。

`repository`はGitHubの`owner/repository`、`tag`は採用Releaseのタグ、
`commit`はタグを解決した完全な40桁のコミットSHAです。
`package_root`はcheckout先を基準とした相対パス、
`site_data`・`pages`はそのpackage rootを基準とした相対パスです。
各パスは通常の`/`区切りとし、絶対パス・`.`・`..`・root外の参照を禁止します。
原稿の`source`も、その原稿を所有するpackage rootが基準です。

取り込み対象は公開済みGitHub Releaseのうち、
`draft=false`・`prerelease=false`のものに限定します。
`v0.x`でも、この条件を満たす公開版は採用できます。
タグがあるだけ、開発ブランチへ取り込まれただけの状態は対象にしません。
`target_commitish`はブランチ名の場合もあるため、SHAの代わりに使用しません。

GitHub APIでReleaseを確認し、タグが指すコミットを解決して記録SHAと照合します。
注釈付きタグもコミットまで解決し、一致するSHAを明示して取得します。
`latest`やdefault branchを暗黙に選択せず、取得失敗時も`main`へ代替しません。
サイト基点は採用したutilの`site_data`だけから読み取ります。
webの`site`・`base`の設定へ反映するときは、基点の共通パスを一度だけ適用します。
実際の配置先URLと一致することも公開設定時に確認します。

### config/categories.json

初回の表示設定は次の形です。配列順を分類の表示順とし、空の分類は表示しません。

```json
{
  "schema_version": 1,
  "packages": {
    "bd_tools": [
      {"id": "util", "label": "汎用・補助"},
      {"id": "model", "label": "モデリング"},
      {"id": "uv", "label": "UV"},
      {"id": "texture", "label": "テクスチャ"},
      {"id": "skin", "label": "スキニング"},
      {"id": "anim", "label": "アニメーション"},
      {"id": "rig", "label": "リギング"}
    ]
  }
}
```

各項目の`id`・`label`は空でない文字列とし、パッケージ内のIDを一意にします。
対応表の未知の分類は、表示から黙って落とさずWeb生成エラーにします。
空配列のページもツール全体の一覧には掲載します。
カテゴリ一覧を設ける場合のパスは`tools/tool/category/<分類ID>/`とし、
個別ページのパスとは分けます。集約する全原稿・共通ページ・分類ページ間で
同じ公開パスが発生した場合は生成を止めます。
メニュー・分類名・表示順の変更は、パッケージのURL変更を伴いません。

### ビルドと公開

1. webの採用版一覧を読み、指定ReleaseとSHAを検証して必要なファイルを取得する。
2. site・pages・分類JSONを検証し、重複パス、原稿、画像、リンクを検査する。
3. 一時的な生成用コピーへslugとサイト内リンクを反映し、共通ページと組み合わせる。
4. Starlightでページと検索用データを生成し、登録された全URLの出力を確認する。
5. 検証に通った生成物を、Cloudflareの同じ`web` Workerへ配置する。

パッケージのソース・設定は変更しません。生成物、取得したソース、認証情報は
webリポジトリへコミットせず、失敗時は公開処理を実行しません。
別のprivateリポジトリを取得する場合は、対象への読み取り権限を別途設定します。
通常の`GITHUB_TOKEN`だけで、すべてのリポジトリへアクセスできるとは扱いません。

最初はパッケージのRelease公開後に、web側の採用版一覧を手動で更新し、
その変更の取り込みをきっかけに集約・生成・公開を自動実行します。
リリースごとの原稿や画像の手動コピーは行いません。
将来はRelease公開通知から、採用版一覧を更新するPRの自動作成へ拡張できます。
`release: published`はプレリリースでも起動するため、通知側・取り込み側ともに
採用条件を確認します。初期実装にリポジトリ間通知は必須ではありません。

## 配布・変更・移転

- `site.json`と`pages.json`は、それぞれのPythonパッケージと一緒に必ず配布します。
- 公開原稿・画像はタグ付きソースに保持します。Maya実行用配布物から省略しても、
  URL取得・起動が可能なようにします。
- 初回リリースには、必要なJSON・API・原稿・画像を揃えます。原稿のない古い版は
  開発ブランチから補完せず、本仕様を満たす次のReleaseを採用します。
- 固定パスはカテゴリ・表示名・原稿配置の変更に追従させません。
  パスを変更する場合は、旧パスからの転送をweb側に用意します。
- siteの基点変更はutilをリリースし、webもその版を採用して反映します。
  互換性を維持したutilだけの更新で、既存toolsも新しい基点を利用できます。
  古いutilやブックマークへ変更が自動反映されるわけではありません。
- `workers.dev`の住所は他サービスへ移管できません。移転時の旧URL転送は、
  Cloudflare側を継続利用できる範囲で維持します。
- 各ヘルプは現在採用している配布版の説明です。古いツールから開いても、
  そのツール版専用の過去ヘルプへ自動的に切り替える機能は初版に含めません。
- 原稿だけの訂正も、初版は新しい公開Releaseから反映します。
  文書専用の訂正配信ルールは、必要になった段階で本仕様を更新して導入します。
- 実装時は各リポジトリのCHANGELOGへAPI・データ形式・必要な同梱物と更新方法を記録します。
  この文書化だけでは、利用者の設定やsceneを変更しません。

## 実装順と完了条件

| 段階 | 成果物と確認 |
| --- | --- |
| 1: 仕様 | 本書、既存docsからの参照、未実装項目が分かるroadmap |
| 2: util | site JSONと公開定数、URL組み立て、汎用ブラウザーAPI、型contractと配布確認 |
| 3: tools | ページJSONとAPI、bdChannelBoxの原稿・画像、「ヘルプ > オンラインヘルプ」の導線 |
| 4: パッケージ公開 | util→toolsの対応するReleaseを公開し、タグ・SHA・JSON・原稿を確認 |
| 5: web | 採用版一覧、集約・生成・公開、公開URLの本文と画像・リンク・検索を確認 |

段階1の仕様化と、段階2のutil実装まで完了しています。util側にはJSON・URLの検証、
初回読込と正規reload、ブラウザーAPIの戻り値・例外、型contractのテストを追加しました。
util内の具体的な使い方と配布対象は、同リポジトリの
`bakedanuki/bakedanuki-util/docs/site.md`に記載します。
段階3以降のtools・web実装と、対応するパッケージReleaseの公開は未着手です。
ヘルプUIは既存のQt facadeとWindow lifecycleを利用し、初回はbdChannelBoxの
メニューバーに追加します。URLをimport時やWindow表示時に自動で開きません。

段階2・3の検証では次の契約を固定します。

- JSONの型・未知フィールド・未知schema・重複・不正値をPythonとWebで同じ判定にする。
- 初回読込後の定数・Mapping参照では再読込せず、正規reloadで値を作り直す。
- 公開定数・Mapping・値型・関数の戻り値をPyrightの`assert_type()`で確認する。
- `bd_tools`単独importと未使用reloadがutil・Maya・Qtを読み込まない既存契約を保つ。
- 基点の共通パスを維持し、絶対URL・先頭`/`・親への逸脱を拒否する。
- JSONは同梱し、原稿を省略したMaya配布物でもURLを組み立てられる。
- 自動テストではブラウザー起動を差し替え、正しいURLと`False`・例外の通知を確認する。
- 対象Mayaの本体で、利用者操作により既定ブラウザーが期待URLを開くことを確認する。
  ヘルプ未公開時は起動先URLまでを確認し、本文の表示成功とは分けて記録する。

段階5では、未公開・プレリリース・タグとSHAの不一致、未登録原稿、分類不整合、
不正な参照、出力パス衝突を拒否し、検証失敗時に配置処理が呼ばれないことを確認します。
成功時は、同じ採用版からPythonが得るURLとWebの生成先が一致することを検証します。
実装時の実行コマンドは各リポジトリのAGENTS.mdと[Testing](testing.md)に従います。
文書だけを変更する段階1では、変更ファイルの`git diff --check`を実行します。

Tallyによる受付とGitHub Issuesへの対応整理は、Web制作時に追加します。
フォームやDiscussionsを、URL情報・原稿を配布するための前提にしません。

## 公式仕様の参照先

- [Starlightのページと原稿](https://starlight.astro.build/guides/pages/)
- [Starlightのslug](https://starlight.astro.build/reference/frontmatter/#slug)
- [Python 3.11のwebbrowser](https://docs.python.org/3.11/library/webbrowser.html)
- [GitHubのリリース管理](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
- [GitHubのReleaseイベント](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#release)
- [actions/checkoutの取得指定](https://github.com/actions/checkout#usage)
- [Cloudflareの静的ファイル配信](https://developers.cloudflare.com/workers/static-assets/)
