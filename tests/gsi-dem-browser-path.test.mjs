import assert from "node:assert/strict";
import test from "node:test";
import { createGsiDemProtocol, decodeTerrarium, readBitmapPixels } from "../src/gsi-dem-protocol.js";

function globals(t, values) {
  for (const [name, value] of Object.entries(values)) {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    t.after(() => descriptor ? Object.defineProperty(globalThis, name, descriptor) : delete globalThis[name]);
  }
}

const size = 256;
const noCanvas = class { constructor() { throw new Error("Canvas must not be used"); } };

test("VideoFrame reads RGBA/RGBX/BGRA/BGRX without Canvas and closes frames", async (t) => {
  let format;
  let closed = 0;
  globals(t, {
    OffscreenCanvas: noCanvas,
    VideoFrame: class {
      constructor() { this.format = format; }
      async copyTo(data, options) {
        assert.deepEqual(options, { layout: [{ offset: 0, stride: size * 4 }] });
        for (let i = 0; i < data.length; i += 4) {
          const rgba = [i / 4 % 256, 23, 197, 255];
          if (format.startsWith("BGR")) [rgba[0], rgba[2]] = [rgba[2], rgba[0]];
          data.set(rgba, i);
        }
      }
      close() { closed++; }
    },
  });
  for (format of ["RGBA", "RGBX", "BGRA", "BGRX"]) {
    const data = await readBitmapPixels({ width: size, height: size });
    for (let i = 0; i < data.length; i += 4) {
      assert.deepEqual([...data.subarray(i, i + 4)], [i / 4 % 256, 23, 197, 255]);
    }
  }
  assert.equal(closed, 4);
});

test("VideoFrame rejects unexpected dimensions/formats and closes on read failure", async (t) => {
  let format = "I420";
  let closed = 0;
  globals(t, {
    VideoFrame: class {
      constructor() { this.format = format; }
      async copyTo() { throw new Error("copy failed"); }
      close() { closed++; }
    },
  });
  await assert.rejects(readBitmapPixels({ width: 512, height: 256 }), /expected/);
  await assert.rejects(readBitmapPixels({ width: size, height: size }), /unsupported/);
  format = "RGBA";
  await assert.rejects(readBitmapPixels({ width: size, height: size }), /copy failed/);
  assert.equal(closed, 2);
});

test("protocol returns a bitmap of correct heights without Canvas readback or PNG export", async (t) => {
  const source = new Uint8ClampedArray(size * size * 4);
  for (let i = 0; i < source.length; i += 4) source.set([128, 0, 0, 255], i);
  source.set([255, 254, 12, 255], 0); // -5 m
  source.set([0, 39, 16, 255], 4); // 100 m
  let inputClosed = 0;
  let frameClosed = 0;
  let outputClosed = 0;
  let response = new Response(new Blob(["PNG"]));
  const controller = new AbortController();
  globals(t, {
    OffscreenCanvas: noCanvas,
    fetch: async (url, options) => {
      assert.equal(url, "https://example.com/11/1824/762.png");
      assert.equal(options.signal, controller.signal);
      return response;
    },
    ImageData: class { constructor(data, width, height) { Object.assign(this, { data, width, height }); } },
    createImageBitmap: async (input, options) => {
      assert.deepEqual(options, { premultiplyAlpha: "none", colorSpaceConversion: "none" });
      if (input instanceof Blob) return { width: size, height: size, close() { inputClosed++; } };
      return { width: input.width, height: input.height, data: input.data, close() { outputClosed++; } };
    },
    VideoFrame: class {
      format = "RGBA";
      async copyTo(data) { data.set(source); }
      close() { frameClosed++; }
    },
  });
  const handler = createGsiDemProtocol({ url: "https://example.com/{z}/{x}/{y}.png" });
  const params = { url: "gsidem://11/1824/762" };
  const bitmap = (await handler(params, controller)).data;
  assert.equal(decodeTerrarium(...bitmap.data.subarray(0, 3)), -5);
  assert.equal(decodeTerrarium(...bitmap.data.subarray(4, 7)), 100);
  assert.equal(decodeTerrarium(...bitmap.data.subarray(8, 11)), 0);
  assert.equal(inputClosed, 1);
  assert.equal(frameClosed, 1);
  response = new Response(null, { status: 404 });
  const flat = (await handler(params, controller)).data;
  for (let i = 0; i < flat.data.length; i += 4) assert.equal(decodeTerrarium(...flat.data.subarray(i, i + 3)), 0);
  assert.equal(frameClosed, 1); // 404 needs no bitmap decoding
  response = new Response(null, { status: 500 });
  await assert.rejects(handler(params, controller), /HTTP 500/);
  response = new Response(null, { status: 404 });
  controller.abort();
  await assert.rejects(handler(params, controller), { name: "AbortError" });
  assert.equal(outputClosed, 1); // don't leak an aborted output bitmap
});
