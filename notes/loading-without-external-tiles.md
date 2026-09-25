# 自前のデータは `style.load` で足す

- 状態: 未検証(Orometry では 2026-08-18 に確認。このリポジトリのデモではまだ遮断試験をしていない)
- 実装例: [`demo/index.html`](../demo/index.html)

## 何が起きたか

自前の GeoJSON を `map.on("load")` の中で足していたところ、地理院のサーバへ届かない環境では
地図が**完全に空**になった。地理院の基図が出ないだけでなく、ローカルに置いてある自前の
データまで描画されなかった。13 秒待っても `isStyleLoaded()` は false のままだった。

## 原因

MapLibre の `load` は、スタイルの初期ソースが揃うまで発火しない。このリポジトリのスタイルの
ソース(`gsi` と `gsi-dem`)はどちらも外部のホストにあるので、そこへ届かなければ `load` は
来ない。自前のデータは外部と無関係なのに、発火待ちに巻き込まれる。

## 対処

`style.load` で足す。スタイルの JSON を読み終えた時点で発火するので、タイルが来なくても
自前のデータは出る。

```js
map.on("style.load", async () => {
  if (map.getSource("local")) return; // setStyle のたびに再発火するので二重追加を防ぐ
  const data = await fetch("./local.geojson").then((r) => r.json());
  map.addSource("local", { type: "geojson", data });
  map.addLayer({ id: "local-point", type: "circle", source: "local" });
});
```

自治体の庁内網のように、外部ホストが許可リストから漏れることがある環境で効く。

## このリポジトリでやること

デモで地理院のホストを遮断し、ローカルの点だけが表示されることを確かめて、状態を更新する。
