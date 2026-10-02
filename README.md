# gsi-field-notes

[![check](https://github.com/rihito-dev/gsi-field-notes/actions/workflows/check.yml/badge.svg)](https://github.com/rihito-dev/gsi-field-notes/actions/workflows/check.yml)

**Field notes and a starter MapLibre style for GSI (国土地理院) vector tiles — observed from the actual tiles.**

国土地理院の最適化ベクトルタイルと標高タイルを MapLibre で使うための、最小構成のスタイルと、実際のタイルを復号して確かめたことの記録(野帳)です。

色はプリセットとして分けてあり、差し替えるだけで別の見た目になります。

## Field notes

- **[海と陸の表し方](notes/land-and-sea.md)**(観測済み・目視確認・仕様と照合済み)
  z4–z7 では海が WA に入っておらず、陸が AdmArea の面として来る。z8 から逆になる
- **[居住地名の注記コード](notes/place-label-codes.md)**(観測済み・仕様と照合済み)
  居住地名のコードは縮尺帯で系列が分かれる(13xx は z4–z7、14xx は z8–z10)
- **[標高タイルの復号](notes/dem-png-decoding.md)**(観測済み・目視確認・対処を実装)
  線形の custom encoding では、データなしが約 83,886 m、海面下が約 167,772 m と読まれ、海岸や干拓地の縁に黒い線が出る。読み直すプロトコルで消える
- **[外部タイルが届かないとき](notes/loading-without-external-tiles.md)**(観測済み)
  地理院に届かないと `load` は来ない。自前のデータは `style.load` で足せば描かれる
- **[仕様との照合](notes/spec-comparison.md)**(仕様と照合済み)
  観測した vt_code 105件のうち103件は仕様のズーム範囲内。港・空港の2件だけ範囲外でも出た

観測は決めた地点の真上のタイルだけを見た標本です。状態の意味と限界は [notes/README.md](notes/README.md) にあります。

## Before / after: 標高タイルの読み方

スタイルのまま(線形の custom encoding)だと、海面下の土地や海岸の縁に黒い線が出ます。[`src/gsi-dem-protocol.js`](src/gsi-dem-protocol.js) で読み直すと消えます。

| linear(スタイルのまま) | fixed(読み直し) |
|---|---|
| ![八郎潟干拓地 z11、線形の読み方。干拓地の縁に黒いギザギザの線が出ている](docs/images/hachirogata-linear.png) | ![八郎潟干拓地 z11、読み直し版。縁の線は消えている](docs/images/hachirogata-fixed.png) |
| ![函館 z12.5、線形の読み方。埠頭と海岸の縁に黒い線が出ている](docs/images/hakodate-linear.png) | ![函館 z12.5、読み直し版。縁の線は消えている](docs/images/hakodate-fixed.png) |

上: 八郎潟干拓地(z11、海面下の土地)。下: 函館(z12.5、普通の海岸)。いずれも dark プリセット。画像は国土地理院最適化ベクトルタイル・地理院タイル(標高タイル(基盤地図情報数値標高モデル))を加工して作成しました。[`scripts/capture_comparisons.mjs`](scripts/capture_comparisons.mjs) で撮り直せます。

## Quick start

推奨は、生成済みスタイルに標高の復号プロトコルを組み合わせる使い方です。`styles/*.json` 単体では無効値・負の標高を誤読するため、下の例では `withFixedDem` を通します。PMTiles のプロトコルも登録します。

リポジトリ直下に HTML を置き、HTTP サーバ経由で開く例です。

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/maplibre-gl@6.11.2/dist/maplibre-gl.css">
<script src="https://cdn.jsdelivr.net/npm/pmtiles@4.5.0/dist/pmtiles.js"></script>
<div id="map" style="height: 100vh"></div>
<script type="module">
  import { Map, addProtocol } from "https://cdn.jsdelivr.net/npm/maplibre-gl@6.11.2/dist/maplibre-gl.mjs";
  import { SCHEME, createGsiDemProtocol, withFixedDem } from "./src/gsi-dem-protocol.js";
  const protocol = new pmtiles.Protocol();
  addProtocol("pmtiles", protocol.tile);
  addProtocol(SCHEME, createGsiDemProtocol());
  const response = await fetch("styles/dark.json");
  if (!response.ok) throw new Error(`style: HTTP ${response.status}`);
  const style = withFixedDem(await response.json());
  new Map({ container: "map", style, center: [142.8, 43.4], zoom: 6 });
</script>
```

復号には `OffscreenCanvas` と `createImageBitmap` が使えるブラウザが必要です。無効値と HTTP 404 を 0 m へ置き換えるのは陰影表示用の補完で、実測値ではありません。測量や標高の分析には使わず、詳しい限界は [標高のノート](notes/dem-png-decoding.md) を参照してください。

### デモ

デモはリポジトリの直下でサーバを立てて開きます。

```sh
python3 -m http.server 8765 --bind 127.0.0.1
# http://127.0.0.1:8765/demo/
```

初期表示は `fixed` です。`?preset=light` で配色、`?dem=linear` で誤読を再現する比較モードに切り替えられます。デモは CDN と地理院のサーバに接続します。外部タイルの遮断試験でも CDN とローカルサーバは必要です。

## プリセットと色

[`presets/`](presets/) の JSON は色と陰影の強さだけを持ち、スタイルの構造(ソース・レイヤ・フィルタ)は [`scripts/build_styles.py`](scripts/build_styles.py) だけが持ちます。

| プリセット | 内容 |
|---|---|
| `dark` | [Orometry](https://orometry.com) の地図から切り出した暗色 |
| `light` | 色だけを差し替えた例 |

新しいプリセットは `presets/<name>.json` を足して生成します。標準ライブラリだけで動きます。

```sh
python3 scripts/build_styles.py          # styles/<name>.json を生成
python3 scripts/build_styles.py --check  # 生成物が最新かを確かめる(CI で実行)
```

## 観測を再現する

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/observe_vector_tiles.py --out work/observations/new-run
python scripts/observe_dem_png.py --out work/observations/new-run
python scripts/compare_with_spec.py \
  --observations work/observations/new-run/vector_tiles.csv \
  --out work/observations/new-run
```

掲載済みの `data/observations/` は 2026-09-25〜26 の記録です。再実行は別の出力先を指定して比較し、既存の記録を置き換える場合は観測条件・日時とノートも更新してください。

地理院のサーバへは 1 秒以上の間隔を空けて順番に要求します(2026-09-25 の実行ではベクトルタイルで 66 件、標高タイルで 24 件)。取得したタイルは集計にだけ使い、リポジトリには保存しません。観測日時は `*.meta.json` に残ります。掲載済みのベクトルタイルには Last-Modified / ETag、仕様書には Last-Modified があります。掲載済みの標高タイルには画素の集計と日時のみがあり、取得時の版・ハッシュは未記録です。今後の実行では標高タイルごとの版と SHA-256、仕様書と観測 CSV の SHA-256 も記録します。タイルは更新されるので、同じ結果になるとは限りません。

## 検証と更新

Python 3.12 以上・Node.js 22 以上を推奨します。ネットワーク不要の検証は以下です。

```sh
python3 scripts/build_styles.py --check
python3 scripts/check_repository.py
npm test
```

CI では加えて固定版の MapLibre style spec で検証します。ブラウザでの撮影・外部タイル遮断試験の手順は [CONTRIBUTING.md](CONTRIBUTING.md) にあります。

## Repository

```text
presets/                   色の指定(プリセット)
styles/                    生成された MapLibre スタイル(コミットしてある)
notes/                     野帳。実際のタイルを見てわかったこと
data/observations/         観測スクリプトの出力
src/
  gsi-dem-protocol.js      標高タイルを読み直すプロトコル(任意)
tests/                     src/ のテスト(npm test)
scripts/
  build_styles.py          プリセットからスタイルを生成する
  observe_vector_tiles.py  ベクトルタイルのレイヤと vt_code を数える
  observe_dem_png.py       標高タイルの画素を2通りに復号して比べる
  compare_with_spec.py     観測した vt_code を地理院の仕様書と突き合わせる
  capture_comparisons.mjs  デモを headless Chrome で撮影し docs/images/ に書く
  check_offline.mjs        地理院のホストを遮断してデモを開き、描画を確かめる
  _cdp.mjs                 上の2本が使う headless Chrome の操作(依存なし)
demo/                      スタイルを表示するだけのページ
docs/images/               README とノートの画像
```

## 出典とライセンス

### 国土地理院のデータ

- 使っているデータは、国土地理院の[最適化ベクトルタイル](https://github.com/gsi-cyberjapan/optimal_bvmap)(試験公開)と[地理院タイル](https://maps.gsi.go.jp/development/ichiran.html)の標高タイル(基盤地図情報数値標高モデル, DEM10B)、地名表示用のフォント(グリフ)です。フォントは第三者の [Noto Sans JP](https://github.com/notofonts/noto-cjk/blob/main/Sans/LICENSE)(SIL Open Font License 1.1)を使用しています。いずれもスタイルが実行時に地理院のサーバから読み込み、リポジトリには含みません
- 地理院のデータの利用条件は[国土地理院コンテンツ利用規約](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html) (公共データ利用規約 第1.0版, PDL1.0)です。ウェブ上でリアルタイムに読み込んで表示する使い方は、出典の明示だけで申請は不要とされています。スタイルの `attribution` に「国土地理院最適化ベクトルタイル」「地理院タイル」の出典とリンクを入れてあります
- 使っている2種類のタイルは、どちらも測量法の基本測量成果ではありません(標高タイルは地理院タイル一覧の「基本測量成果以外で出典の記載のみで利用可能なもの」、最適化ベクトルタイルは地理院の説明で基本測量成果と位置付けていないもの)

### このリポジトリに含まれる、国土地理院のデータをもとにしたもの

| もの | 出典と加工の表示 |
|---|---|
| `docs/images/*.png`(比較画像) | 国土地理院最適化ベクトルタイル・地理院タイル(標高タイル(基盤地図情報数値標高モデル))を加工して作成 |
| `data/observations/`(観測の集計と、例として記録した地名) | 国土地理院最適化ベクトルタイル・地理院タイル(標高タイル)をもとに作成 |
| `notes/` の表(仕様の分類名とズーム範囲) | 国土地理院「[注記分類コード・地物種別コード一覧](https://maps.gsi.go.jp/help/pdf/vector/optbv_featurecodes.xlsx)」をもとに作成 |

これらは国土地理院コンテンツ利用規約に従います。**このリポジトリは国土地理院とは関係がなく、国土地理院が作成・確認したものではありません。**「地理院地図」「地理院タイル」は国土地理院の登録商標です。

### このリポジトリのライセンス

- コード・スタイル・プリセット・ノートの文章は [MIT](LICENSE) です。国土地理院のデータそのものには及びません
- デモは実行時に CDN から [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js)(BSD-3-Clause)と[PMTiles](https://github.com/protomaps/PMTiles)(BSD-3-Clause)を読み込みます。観測スクリプトの依存パッケージ(`requirements.txt`)も含め、いずれもリポジトリには同梱していません

## Deliberate limits

- 観測は北海道の数地点での標本で、全国・全タイルについての主張ではありません
- 最適化ベクトルタイルは地理院の**試験公開**で、URL・データ構成・属性が変わる可能性があります。観測日・ベクトルタイルと仕様書の版を記録しています
- vt_code の照合は、観測で出たコードについてだけ行っています([ノート](notes/spec-comparison.md))
- 標高タイルの読み直しは JavaScript のプロトコルで行うので、スタイル JSON だけを使う場合は直りません([ノート](notes/dem-png-decoding.md))

## Where it came from

北海道 179 市町村の財政を地図で見る [Orometry](https://orometry.com) の開発中に見つけたことを、汎用の形に切り出しました。
