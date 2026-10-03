# 検証と観測の更新

Python 3.12 以上と Node.js 22 以上を推奨します。色は `presets/` を変更し、`python3 scripts/build_styles.py` で生成します。

```sh
python3 scripts/build_styles.py --check
python3 scripts/check_repository.py
npm test
npx --yes -p @maplibre/maplibre-gl-style-spec@26.4.4 gl-style-validate styles/*.json
```

`check_repository.py` は Markdown のローカルリンクと、よくある秘密情報・個人パスの文字列を確認する簡易チェックです。未知の形式の秘密情報や権利関係まで検出するものではありません。

## ブラウザでの確認

まずリポジトリ直下で `python3 -m http.server 8765 --bind 127.0.0.1` を起動し、`http://127.0.0.1:8765/demo/` を開きます。dark / light と fixed / linear の切り替え、ローカルの点、出典表示を確認します。

撮影・遮断試験のスクリプトは headless Chrome と Node.js 22 以上を使います。macOS 以外では `CHROME` 環境変数に Chrome / Chromium の実行ファイルを指定してください。

```sh
node scripts/capture_comparisons.mjs
node scripts/check_offline.mjs
```

この2本は既存の画像と `data/observations/offline.json` を更新します。別の作業コピーで実行し、画像・記録・ノートの差分を確認してください。撮影には CDN と地理院タイルへの接続が必要です。遮断試験も CDN とローカルサーバには接続します。

## 観測の更新

README の手順で `--out work/observations/<run-name>` に書き、既存の観測を上書きせず比較します。地点・ズーム・日時・入力の版とハッシュ・欠測を確認し、更新するときは CSV とメタデータ、ノートを同じ変更に含めます。全国や未観測の縮尺へ結果を広げないでください。

出典・加工表示を維持し、取得したタイル・仕様書本体、実メールアドレス、秘密情報をコミットしないでください。新しいデータソースを加える場合は、その提供元の利用条件も確認します。
