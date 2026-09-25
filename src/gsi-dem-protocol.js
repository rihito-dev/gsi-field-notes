/**
 * 地理院の標高タイル(dem_png)を正しく復号し、MapLibre が扱える terrarium 形式に
 * 並べ替えて返すプロトコル。
 *
 * スタイルの線形な custom encoding では、無効値(海など)が約 83,886 m、海面下の土地が
 * 約 167,772 m と読まれる(notes/dem-png-decoding.md)。このプロトコルは画素ごとに
 * 地理院の仕様どおりに読み直す。
 *
 *   import { Map, addProtocol } from "maplibre-gl";
 *   import { createGsiDemProtocol, withFixedDem } from "./gsi-dem-protocol.js";
 *   addProtocol("gsidem", createGsiDemProtocol());
 *   const style = withFixedDem(await (await fetch("styles/dark.json")).json());
 *   new Map({ container: "map", style });
 *
 * 計算部分(decodeGsiPixel / encodeTerrarium / convertPixels)は DOM に依存しないので、
 * Node から直接テストできる。
 */

export const GSI_DEM_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png";
export const SCHEME = "gsidem";
const NODATA = 2 ** 23;
const TILE_SIZE = 256;

/** 地理院の画素を標高[m]に読む。無効値は null。 */
export function decodeGsiPixel(r, g, b) {
  const x = r * 65536 + g * 256 + b;
  if (x === NODATA) return null;
  return x > NODATA ? (x - 2 ** 24) * 0.01 : x * 0.01;
}

/** 標高[m]を terrarium の RGB に書く。精度は 1/256 m。 */
export function encodeTerrarium(h) {
  const n = Math.round((h + 32768) * 256);
  return [Math.floor(n / 65536), Math.floor(n / 256) % 256, n % 256];
}

export function decodeTerrarium(r, g, b) {
  return r * 256 + g + b / 256 - 32768;
}

/**
 * RGBA の画素列をその場で書き換える。無効値は nodataHeight[m] に置き換える。
 * 戻り値は置き換えた画素の内訳(確認用)。
 */
export function convertPixels(data, nodataHeight = 0) {
  const counts = { nodata: 0, belowSeaLevel: 0 };
  for (let i = 0; i < data.length; i += 4) {
    let h = decodeGsiPixel(data[i], data[i + 1], data[i + 2]);
    if (h === null) {
      counts.nodata += 1;
      h = nodataHeight;
    } else if (h < 0) {
      counts.belowSeaLevel += 1;
    }
    const [r, g, b] = encodeTerrarium(h);
    data[i] = r;
    data[i + 1] = g;
    data[i + 2] = b;
    data[i + 3] = 255;
  }
  return counts;
}

/**
 * addProtocol に渡すハンドラを作る。タイルの URL は `gsidem://{z}/{x}/{y}`。
 *
 * 陸地を含まない沖合のタイルは地理院側が 404 を返す。その場合は全画素 nodataHeight の
 * 平らなタイルを返し、隣のタイルとの境目で陰影が途切れないようにする。
 */
export function createGsiDemProtocol({ nodataHeight = 0, url = GSI_DEM_URL } = {}) {
  return async (params, abortController) => {
    const [z, x, y] = params.url.slice(`${SCHEME}://`.length).split("/").map(Number);
    const res = await fetch(url.replace("{z}", z).replace("{x}", x).replace("{y}", y), {
      signal: abortController.signal,
    });
    const canvas = new OffscreenCanvas(TILE_SIZE, TILE_SIZE);
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    let image;
    if (res.status === 404) {
      // 全画素を地理院の無効値 (128, 0, 0) にし、下の convertPixels に置き換えを任せる。
      image = ctx.createImageData(TILE_SIZE, TILE_SIZE);
      for (let i = 0; i < image.data.length; i += 4) image.data.set([128, 0, 0, 255], i);
    } else if (!res.ok) {
      throw new Error(`dem_png ${z}/${x}/${y}: HTTP ${res.status}`);
    } else {
      // 色空間の変換や乗算済みアルファが入ると画素値が変わり、標高が壊れる。
      const bitmap = await createImageBitmap(await res.blob(), {
        premultiplyAlpha: "none",
        colorSpaceConversion: "none",
      });
      ctx.drawImage(bitmap, 0, 0);
      bitmap.close();
      image = ctx.getImageData(0, 0, TILE_SIZE, TILE_SIZE);
    }
    convertPixels(image.data, nodataHeight);
    ctx.putImageData(image, 0, 0);
    const blob = await canvas.convertToBlob({ type: "image/png" });
    return { data: await blob.arrayBuffer() };
  };
}

/** スタイルの標高ソースを、このプロトコルを通す terrarium のソースに差し替えた複製を返す。 */
export function withFixedDem(style, sourceId = "gsi-dem") {
  const copy = structuredClone(style);
  const source = copy.sources[sourceId];
  if (!source) throw new Error(`style has no source ${sourceId}`);
  copy.sources[sourceId] = {
    type: "raster-dem",
    tiles: [`${SCHEME}://{z}/{x}/{y}`],
    tileSize: TILE_SIZE,
    minzoom: source.minzoom,
    maxzoom: source.maxzoom,
    encoding: "terrarium",
    attribution: source.attribution,
  };
  return copy;
}
