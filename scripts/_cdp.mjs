// headless Chrome を起動し、Chrome DevTools Protocol で1枚のページを操作する最小限の道具。
// 依存パッケージは使わない(Node 22 以上の WebSocket だけ)。
// CHROME 環境変数で Chrome の実行ファイルを指定できる。

import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9333;

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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

/**
 * Chrome を起動して fn({ send, evaluate }) を実行し、終わったら片付ける。
 * extraArgs で起動時の引数(ホストの名前解決の差し替えなど)を足せる。
 */
export async function withChrome(fn, { extraArgs = [], viewport = { width: 800, height: 600, deviceScaleFactor: 1 } } = {}) {
  const profile = await mkdtemp(join(tmpdir(), "gsi-field-notes-chrome-"));
  const chrome = spawn(CHROME, [
    "--headless=new",
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--hide-scrollbars",
    ...extraArgs,
    "about:blank",
  ], { stdio: "ignore" });
  let session;
  try {
    let targets;
    for (let i = 0; i < 50 && !targets; i++) {
      try {
        targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      } catch {
        await sleep(200);
      }
    }
    if (!targets) throw new Error("Chrome did not start");
    session = await connect(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
    const { send } = session;
    await send("Page.enable");
    await send("Emulation.setDeviceMetricsOverride", { ...viewport, mobile: false });
    const evaluate = async (expression) => {
      const result = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description ?? "evaluate failed");
      return result.result.value;
    };
    return await fn({ send, evaluate });
  } finally {
    session?.close();
    chrome.kill();
    await sleep(500);
    await rm(profile, { recursive: true, force: true });
  }
}

/** ページを開き、新しい文書に切り替わるまで待つ。 */
export async function open(send, url) {
  await send("Page.navigate", { url });
  await sleep(1000);
}

export async function screenshot(send) {
  const { data } = await send("Page.captureScreenshot", { format: "png" });
  return Buffer.from(data, "base64");
}
