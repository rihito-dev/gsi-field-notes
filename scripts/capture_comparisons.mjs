// デモを headless Chrome で開き、標高タイルの読み方(linear / fixed)ごとに同じ視点を撮影する。
// 地図の描画が終わる(タイルが揃い idle になる)まで待ってから撮るので、読み込み途中の絵にはならない。
//
//   python3 -m http.server 8765          # リポジトリの直下で
//   node scripts/capture_comparisons.mjs # docs/images/ に PNG を書く
//
// 依存パッケージは使わない(Node 22 以上の WebSocket と Chrome DevTools Protocol だけ)。
// CHROME 環境変数で Chrome の実行ファイルを指定できる。

import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "..");
const OUT = join(ROOT, "docs", "images");
const BASE = process.env.DEMO_URL ?? "http://localhost:8765/demo/";
const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9333;
const VIEWPORT = { width: 800, height: 600, deviceScaleFactor: 2 };

// 視点は notes/dem-png-decoding.md の表と同じ。
const SHOTS = [
  { name: "hachirogata", hash: "11/39.99/140.0" },
  { name: "hakodate", hash: "12.5/41.76/140.72" },
];
const MODES = ["linear", "fixed"];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitForChrome() {
  for (let i = 0; i < 50; i++) {
    try {
      return await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
    } catch {
      await sleep(200);
    }
  }
  throw new Error("Chrome did not start");
}

function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let id = 0;
  const pending = new Map();
  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { ok, fail } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? fail(new Error(msg.error.message)) : ok(msg.result);
    }
  });
  const send = (method, params = {}) =>
    new Promise((ok, fail) => {
      const n = ++id;
      pending.set(n, { ok, fail });
      ws.send(JSON.stringify({ id: n, method, params }));
    });
  return new Promise((ok) => ws.addEventListener("open", () => ok({ send, close: () => ws.close() })));
}

// 地図の描画が終わるのを待つ。タイルが揃って idle になったあと、念のため少し置く。
const WAIT_FOR_IDLE = `new Promise((resolve, reject) => {
  const deadline = setTimeout(() => reject(new Error("map did not become idle")), 90000);
  const check = () => {
    if (!window.map) return setTimeout(check, 200);
    const done = () => { clearTimeout(deadline); setTimeout(resolve, 1500); };
    if (window.map.loaded() && window.map.areTilesLoaded()) done();
    else window.map.once("idle", done);
  };
  check();
})`;

async function capture(send, url) {
  await send("Page.navigate", { url });
  await sleep(1000); // 前のページで評価しないよう、新しい文書に切り替わるのを待つ
  const result = await send("Runtime.evaluate", { expression: WAIT_FOR_IDLE, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(`${url}: ${result.exceptionDetails.exception?.description}`);
  const { data } = await send("Page.captureScreenshot", { format: "png" });
  return Buffer.from(data, "base64");
}

const profile = await mkdtemp(join(tmpdir(), "gsi-field-notes-chrome-"));
const chrome = spawn(CHROME, [
  "--headless=new",
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${profile}`,
  "--use-angle=swiftshader",
  "--enable-unsafe-swiftshader",
  "--hide-scrollbars",
  "about:blank",
], { stdio: "ignore" });

try {
  await waitForChrome();
  const [page] = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).filter((t) => t.type === "page");
  const { send, close } = await connect(page.webSocketDebuggerUrl);
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { ...VIEWPORT, mobile: false });
  await mkdir(OUT, { recursive: true });
  for (const shot of SHOTS) {
    for (const dem of MODES) {
      const url = `${BASE}?dem=${dem}&shot=${shot.name}#${shot.hash}`;
      const file = join(OUT, `${shot.name}-${dem}.png`);
      await writeFile(file, await capture(send, url));
      console.log(`wrote ${file.slice(ROOT.length + 1)}`);
    }
  }
  close();
} finally {
  chrome.kill();
  await sleep(500);
  await rm(profile, { recursive: true, force: true });
}
