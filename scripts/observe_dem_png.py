"""標高タイル(dem_png)の画素を、地理院の仕様どおりの復号と、MapLibre の線形な
custom encoding による復号の両方で読み、食い違う画素を数える。

地理院の仕様: x = 2^16 R + 2^8 G + B
  x <  2^23 → h = 0.01x
  x =  2^23 → 無効値(データなし)
  x >  2^23 → h = 0.01(x - 2^24)   (海面より低い地点)
MapLibre の custom: h = R*redFactor + G*greenFactor + B*blueFactor - baseShift
  このリポジトリのスタイルでは 655.36 / 2.56 / 0.01 / 0 を使っている。

出力:
  data/observations/dem_png.csv
  data/observations/dem_png.meta.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

from PIL import Image

from _gsi import DEM_PNG_URL, HOKKAIDO_POINTS, Point, PoliteSession, lonlat_to_tile, utc_now

ROOT = Path(__file__).resolve().parent.parent
FACTORS = (655.36, 2.56, 0.01)
NODATA = 2**23

# 北海道の地点に加えて、海面下の土地(八郎潟干拓地)と沖合の海上を見る。
EXTRA_POINTS = [
    Point("ogata_below_sea_level", 140.0230, 40.0040),
    Point("uchiura_bay_offshore", 140.6000, 42.3000),
]


def classify(img: Image.Image) -> dict:
    stats = {"pixels": 0, "valid": 0, "nodata": 0, "below_sea_level": 0,
             "true_min_m": None, "true_max_m": None, "linear_max_m": None}
    rgb = img.convert("RGB")
    for r, g, b in rgb.get_flattened_data():
        stats["pixels"] += 1
        x = (r << 16) + (g << 8) + b
        linear = r * FACTORS[0] + g * FACTORS[1] + b * FACTORS[2]
        stats["linear_max_m"] = linear if stats["linear_max_m"] is None else max(stats["linear_max_m"], linear)
        if x == NODATA:
            stats["nodata"] += 1
            continue
        h = 0.01 * (x - 2**24) if x > NODATA else 0.01 * x
        if x > NODATA:
            stats["below_sea_level"] += 1
        stats["valid"] += 1
        stats["true_min_m"] = h if stats["true_min_m"] is None else min(stats["true_min_m"], h)
        stats["true_max_m"] = h if stats["true_max_m"] is None else max(stats["true_max_m"], h)
    for k in ("true_min_m", "true_max_m", "linear_max_m"):
        if stats[k] is not None:
            stats[k] = round(stats[k], 2)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zooms", default="8,11,14", help="観測するズーム (カンマ区切り)")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "observations")
    args = parser.parse_args()
    zooms = [int(z) for z in args.zooms.split(",")]

    http = PoliteSession()
    rows = []
    for point in HOKKAIDO_POINTS + EXTRA_POINTS:
        for z in zooms:
            x, y = lonlat_to_tile(point.lon, point.lat, z)
            res = http.get(DEM_PNG_URL.format(z=z, x=x, y=y))
            row = {"point": point.name, "zoom": z, "x": x, "y": y, "http_status": res.status_code}
            if res.status_code == 200:
                row.update(classify(Image.open(io.BytesIO(res.content))))
            rows.append(row)
            print(f"{point.name} z{z}: HTTP {res.status_code}")

    fields = ["point", "zoom", "x", "y", "http_status", "pixels", "valid", "nodata", "below_sea_level",
              "true_min_m", "true_max_m", "linear_max_m"]
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "dem_png.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    meta = {
        "checked_at": utc_now(),
        "source": DEM_PNG_URL,
        "linear_factors": {"redFactor": FACTORS[0], "greenFactor": FACTORS[1], "blueFactor": FACTORS[2], "baseShift": 0},
        "points": [p.__dict__ for p in HOKKAIDO_POINTS + EXTRA_POINTS],
        "zooms": zooms,
        "requests": http.requests_made,
        "note": "Sample of tiles directly above fixed points; not a census.",
    }
    (args.out / "dem_png.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out / 'dem_png.csv'}")


if __name__ == "__main__":
    main()
