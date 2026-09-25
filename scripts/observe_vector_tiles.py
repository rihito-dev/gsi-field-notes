"""最適化ベクトルタイルを、決めた地点・ズームで復号し、レイヤと vt_code の出現を数える。

出力:
  data/observations/vector_tiles.csv       zoom × layer × vt_code ごとの件数
  data/observations/vector_tiles.meta.json 観測日時・対象ファイルの版・取得条件

これは地点の真上のタイルだけを見た標本であり、全国・全タイルの集計ではない。
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path

import mapbox_vector_tile
from pmtiles.reader import Reader
from pmtiles.tile import Compression

from _gsi import HOKKAIDO_POINTS, PMTILES_URL, PoliteSession, RangeSource, lonlat_to_tile, utc_now

ROOT = Path(__file__).resolve().parent.parent
MAX_EXAMPLES = 3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zooms", default="4-14", help="観測するズーム範囲 (例: 4-14)")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "observations")
    args = parser.parse_args()
    lo, hi = (int(v) for v in args.zooms.split("-"))

    http = PoliteSession()
    source = RangeSource(http, PMTILES_URL)
    reader = Reader(source)
    header = reader.header()
    compression = header["tile_compression"]

    counts: dict[tuple[int, str, str], int] = defaultdict(int)
    tiles_with: dict[tuple[int, str, str], set] = defaultdict(set)
    examples: dict[tuple[int, str, str], list[str]] = defaultdict(list)
    missing: list[dict] = []
    seen: set[tuple[int, int, int]] = set()

    for z in range(lo, hi + 1):
        for point in HOKKAIDO_POINTS:
            x, y = lonlat_to_tile(point.lon, point.lat, z)
            if (z, x, y) in seen:
                continue
            seen.add((z, x, y))
            data = reader.get(z, x, y)
            if data is None:
                missing.append({"zoom": z, "x": x, "y": y, "point": point.name})
                continue
            if compression == Compression.GZIP:
                data = gzip.decompress(data)
            for layer_name, layer in mapbox_vector_tile.decode(data).items():
                for feature in layer["features"]:
                    props = feature.get("properties", {})
                    code = str(props.get("vt_code", ""))
                    key = (z, layer_name, code)
                    counts[key] += 1
                    tiles_with[key].add((x, y))
                    text = props.get("vt_text")
                    if text and len(examples[key]) < MAX_EXAMPLES and text not in examples[key]:
                        examples[key].append(str(text))
        print(f"z{z}: done ({http.requests_made} requests so far)")

    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "vector_tiles.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["zoom", "layer", "vt_code", "features", "tiles", "examples"])
        for key in sorted(counts, key=lambda k: (k[0], k[1], k[2])):
            z, layer_name, code = key
            writer.writerow([z, layer_name, code, counts[key], len(tiles_with[key]), " / ".join(examples[key])])

    meta = {
        "checked_at": utc_now(),
        "source": PMTILES_URL,
        "source_last_modified": source.last_modified,
        "source_etag": source.etag,
        "pmtiles_header": {k: header[k] for k in ("min_zoom", "max_zoom", "tile_type", "tile_compression")},
        "points": [p.__dict__ for p in HOKKAIDO_POINTS],
        "zooms": [lo, hi],
        "tiles_observed": len(seen) - len(missing),
        "tiles_missing": missing,
        "requests": http.requests_made,
        "note": "Sample of tiles directly above fixed points; not a census.",
    }
    for k, v in meta["pmtiles_header"].items():
        meta["pmtiles_header"][k] = getattr(v, "name", v)
    (args.out / "vector_tiles.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out / 'vector_tiles.csv'}")


if __name__ == "__main__":
    main()
