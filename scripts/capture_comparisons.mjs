// デモを headless Chrome で開き、標高タイルの読み方(linear / fixed)ごとに同じ視点を撮影する。
// 地図の描画が終わる(タイルが揃い idle になる)まで待ってから撮るので、読み込み途中の絵にはならない。
//
//   python3 -m http.server 8765          # リポジトリの直下で
//   node scripts/capture_comparisons.mjs # docs/images/ に PNG を書く

import { mkdir, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";

import { open, screenshot, withChrome } from "./_cdp.mjs";

const ROOT = resolve(import.meta.dirname, "..");
const OUT = join(ROOT, "docs", "images");
const BASE = process.env.DEMO_URL ?? "http://localhost:8765/demo/";

// 視点は notes/dem-png-decoding.md の表と同じ。
const SHOTS = [
  { name: "hachirogata", hash: "11/39.99/140.0" },
  { name: "hakodate", hash: "12.5/41.76/140.72" },
];
const MODES = ["linear", "fixed"];

// 地図の描画が終わるのを待つ。タイルが揃って idle になったあと、念のため少し置く。
const WAIT_FOR_IDLE = `new Promise((resolve, reject) => {
  const deadline = setTimeout(() => reject(new Error("map did not become idle")), 90000);
  const check = () => {
    // 地図ができるまでは、window.map は id="map" の要素を指している(名前付きアクセス)。
    if (typeof window.map?.loaded !== "function") return setTimeout(check, 200);
    const done = () => { clearTimeout(deadline); setTimeout(resolve, 1500); };
    if (window.map.loaded() && window.map.areTilesLoaded()) done();
    else window.map.once("idle", done);
  };
  check();
})`;

await mkdir(OUT, { recursive: true });
await withChrome(async ({ send, evaluate }) => {
  for (const shot of SHOTS) {
    for (const dem of MODES) {
      await open(send, `${BASE}?dem=${dem}&shot=${shot.name}#${shot.hash}`);
      await evaluate(WAIT_FOR_IDLE);
      const file = join(OUT, `${shot.name}-${dem}.png`);
      await writeFile(file, await screenshot(send));
      console.log(`wrote ${file.slice(ROOT.length + 1)}`);
    }
  }
}, { viewport: { width: 800, height: 600, deviceScaleFactor: 2 } });
