// 地理院のホストに届かない環境で、デモが自前のデータ(demo/local.geojson)を描けるかを確かめる。
//
// 地理院のホストの名前解決を Chrome の起動引数で差し替え、3通りの環境を作る。
//   control      差し替えなし(比較用)
//   dns_failure  名前解決に失敗する。接続はすぐに失敗する
//   no_response  応答しないアドレス(192.0.2.1, 文書用の予約アドレス)へ向ける。接続が返ってこない
// それぞれ一定時間待ってから、MapLibre の load / style.load が来たか、自前のレイヤが描かれたかを記録する。
//
//   python3 -m http.server 8765    # リポジトリの直下で
//   node scripts/check_offline.mjs # data/observations/offline.json と docs/images/offline-no_response.png を書く

import { mkdir, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";

import { open, screenshot, sleep, withChrome } from "./_cdp.mjs";

const ROOT = resolve(import.meta.dirname, "..");
const BASE = process.env.DEMO_URL ?? "http://localhost:8765/demo/";
const GSI_HOSTS = ["cyberjapandata.gsi.go.jp", "gsi-cyberjapan.github.io"];
const WAIT_MS = 20000;
// 札幌駅(demo/local.geojson の点)が画面に入る視点
const HASH = "10/43.07/141.35";

const ENVIRONMENTS = {
  control: [],
  dns_failure: [`--host-resolver-rules=${GSI_HOSTS.map((h) => `MAP ${h} ~NOTFOUND`).join(", ")}`],
  no_response: [`--host-resolver-rules=${GSI_HOSTS.map((h) => `MAP ${h} 192.0.2.1`).join(", ")}`],
};
const MODES = ["linear", "fixed"];

// デモが window.map に地図を置いた瞬間に、イベントの到着時刻を記録する仕掛けを付ける。
const HOOK = `(() => {
  const t0 = performance.now();
  const at = () => Math.round(performance.now() - t0);
  window.__events = {};
  let map;
  Object.defineProperty(window, "map", {
    configurable: true,
    get: () => map,
    set: (value) => {
      map = value;
      for (const name of ["load", "style.load", "idle"]) {
        map.on(name, () => { window.__events[name] ??= at(); });
      }
      const poll = setInterval(() => {
        if (map.getLayer("local-point")) { window.__events["local-layer-added"] ??= at(); clearInterval(poll); }
      }, 50);
    },
  });
})()`;

const REPORT = `(async () => {
  const map = window.map;
  const probe = await fetch("https://cyberjapandata.gsi.go.jp/xyz/dem_png/8/228/94.png", { signal: AbortSignal.timeout(3000) })
    .then((r) => "HTTP " + r.status)
    .catch((e) => e.name);
  return {
    events_ms: window.__events,
    load_fired: "load" in window.__events,
    is_style_loaded: map.isStyleLoaded(),
    local_features_rendered: map.queryRenderedFeatures({ layers: ["local-point"] }).length,
    gsi_probe: probe,
  };
})()`;

const results = [];
await mkdir(join(ROOT, "docs", "images"), { recursive: true });
for (const [environment, extraArgs] of Object.entries(ENVIRONMENTS)) {
  await withChrome(async ({ send, evaluate }) => {
    await send("Page.addScriptToEvaluateOnNewDocument", { source: HOOK });
    for (const dem of MODES) {
      await open(send, `${BASE}?dem=${dem}#${HASH}`);
      await sleep(WAIT_MS);
      const result = { environment, dem, waited_ms: WAIT_MS, ...(await evaluate(REPORT)) };
      results.push(result);
      console.log(JSON.stringify(result));
      // 遮断した環境の見た目はどちらも同じ(基図が無く、自前の点だけ)なので、1枚だけ残す。
      if (environment === "no_response" && dem === "linear") {
        const file = join(ROOT, "docs", "images", `offline-${environment}.png`);
        await writeFile(file, await screenshot(send));
      }
    }
  }, { extraArgs });
}

const out = join(ROOT, "data", "observations");
await mkdir(out, { recursive: true });
await writeFile(join(out, "offline.json"), JSON.stringify({
  checked_at: new Date().toISOString().replace(/\.\d+Z$/, "+00:00"),
  blocked_hosts: GSI_HOSTS,
  view: HASH,
  results,
}, null, 2) + "\n");
console.log("wrote data/observations/offline.json");
