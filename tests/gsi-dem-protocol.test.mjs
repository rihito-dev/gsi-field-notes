import assert from "node:assert/strict";
import test from "node:test";

import {
  convertPixels,
  decodeGsiPixel,
  decodeTerrarium,
  encodeTerrarium,
  withFixedDem,
} from "../src/gsi-dem-protocol.js";

const close = (actual, expected, tol = 1 / 256) =>
  assert.ok(Math.abs(actual - expected) <= tol, `${actual} is not within ${tol} of ${expected}`);

test("地理院の仕様どおりに読む", () => {
  assert.equal(decodeGsiPixel(0, 0, 0), 0);
  close(decodeGsiPixel(0, 0, 1), 0.01, 1e-9);
  close(decodeGsiPixel(0, 0x27, 0x10), 100, 1e-9); // x = 10000
  assert.equal(decodeGsiPixel(128, 0, 0), null); // 無効値
  close(decodeGsiPixel(255, 255, 255), -0.01, 1e-9); // 海面下で最も浅い値
  close(decodeGsiPixel(255, 254, 12), -5.0, 1e-9); // x = 2^24 - 500
});

test("terrarium への往復で 1/256 m 以内に収まる", () => {
  for (const h of [0, 0.01, -0.01, -4.9, 83.5, 1813.56, 3776.24, -32767]) {
    close(decodeTerrarium(...encodeTerrarium(h)), h);
  }
});

test("線形では壊れる画素を、正しい標高に直す", () => {
  // 無効値・海面下 −4.9 m・陸 437.73 m の3画素
  const minus = 2 ** 24 - 490;
  const land = 43773;
  const data = new Uint8ClampedArray([
    128, 0, 0, 255,
    minus >> 16, (minus >> 8) & 255, minus & 255, 255,
    land >> 16, (land >> 8) & 255, land & 255, 255,
  ]);
  const counts = convertPixels(data, 0);
  assert.deepEqual(counts, { nodata: 1, belowSeaLevel: 1 });
  close(decodeTerrarium(data[0], data[1], data[2]), 0);
  close(decodeTerrarium(data[4], data[5], data[6]), -4.9);
  close(decodeTerrarium(data[8], data[9], data[10]), 437.73);
});

test("無効値の置き換え先を選べる", () => {
  const data = new Uint8ClampedArray([128, 0, 0, 255]);
  convertPixels(data, -1);
  close(decodeTerrarium(data[0], data[1], data[2]), -1);
});

test("withFixedDem は元のスタイルを変えずに標高ソースだけ差し替える", () => {
  const style = {
    version: 8,
    sources: { "gsi-dem": { type: "raster-dem", tiles: ["https://example.com/{z}/{x}/{y}.png"], minzoom: 1, maxzoom: 14, encoding: "custom", attribution: "a" } },
    layers: [],
  };
  const fixed = withFixedDem(style);
  assert.equal(style.sources["gsi-dem"].encoding, "custom");
  assert.deepEqual(fixed.sources["gsi-dem"], {
    type: "raster-dem",
    tiles: ["gsidem://{z}/{x}/{y}"],
    tileSize: 256,
    minzoom: 1,
    maxzoom: 14,
    encoding: "terrarium",
    attribution: "a",
  });
  assert.throws(() => withFixedDem(style, "missing"));
});
