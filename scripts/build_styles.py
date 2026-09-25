"""presets/*.json の色指定から、MapLibre のスタイル styles/<name>.json を生成する。

スタイルの構造(ソース・レイヤ・フィルタ)はこのファイルだけが持ち、プリセットは色と
陰影の強さだけを持つ。生成物もコミットするので、使う人はビルドせずに読み込める。

  python3 scripts/build_styles.py          生成する
  python3 scripts/build_styles.py --check  生成物が最新かを確かめる(CIで実行)

標準ライブラリだけで動く。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRESETS = ROOT / "presets"
STYLES = ROOT / "styles"

REQUIRED_COLORS = [
    "land", "water", "river", "boundary", "railway", "road", "label", "label_halo",
    "hillshade_shadow", "hillshade_highlight", "hillshade_accent",
]

GSI_VECTOR = "pmtiles://https://cyberjapandata.gsi.go.jp/xyz/optimal_bvmap-v1/optimal_bvmap-v1.pmtiles/{z}/{x}/{y}"
GSI_DEM = "https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png"
GSI_GLYPHS = "https://gsi-cyberjapan.github.io/optimal_bvmap/glyphs/{fontstack}/{range}.pbf"
ATTRIBUTION = '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener">地理院タイル</a>'

# 居住地名の注記コード。縮尺帯ごとに系列が分かれている(notes/place-label-codes.md)。
PLACE_LABEL_CODES = [1301, 1302, 1303, 1401, 1402, 1403]
LAND_SEA_SWITCH_ZOOM = 8


def build(preset: dict) -> dict:
    c = preset["colors"]
    return {
        "version": 8,
        "name": f"gsi-field-notes/{preset['name']}",
        "glyphs": GSI_GLYPHS,
        "sources": {
            "gsi": {
                "type": "vector",
                "minzoom": 4,
                "maxzoom": 16,
                "tiles": [GSI_VECTOR],
                "attribution": ATTRIBUTION + "(最適化ベクトルタイル)",
            },
            "gsi-dem": {
                "type": "raster-dem",
                "tiles": [GSI_DEM],
                "tileSize": 256,
                "minzoom": 1,
                "maxzoom": 14,
                # 線形の custom encoding は地理院の無効値・負の標高を表せない(notes/dem-png-decoding.md)
                "encoding": "custom",
                "redFactor": 655.36,
                "greenFactor": 2.56,
                "blueFactor": 0.01,
                "baseShift": 0,
                "attribution": ATTRIBUTION + "(標高タイル)",
            },
        },
        "layers": [
            # 海の表し方が縮尺帯で入れ替わる(notes/land-and-sea.md)。
            # z4–z7: 海はWAに無く、陸がAdmAreaの面として来る → 地色は海、AdmAreaを陸で塗る
            # z8以上: AdmAreaが無く、海がWAに来る → 地色は陸、WAを海で塗る
            {"id": "background", "type": "background",
             "paint": {"background-color": ["step", ["zoom"], c["water"], LAND_SEA_SWITCH_ZOOM, c["land"]]}},
            {"id": "land-lowzoom", "type": "fill", "source": "gsi", "source-layer": "AdmArea",
             "maxzoom": LAND_SEA_SWITCH_ZOOM, "paint": {"fill-color": c["land"]}},
            {
                "id": "hillshade",
                "type": "hillshade",
                "source": "gsi-dem",
                "paint": {
                    "hillshade-shadow-color": c["hillshade_shadow"],
                    "hillshade-highlight-color": c["hillshade_highlight"],
                    "hillshade-accent-color": c["hillshade_accent"],
                    "hillshade-exaggeration": preset.get("hillshade_exaggeration", 0.35),
                    "hillshade-method": "igor",
                },
            },
            {"id": "water", "type": "fill", "source": "gsi", "source-layer": "WA",
             "paint": {"fill-color": c["water"]}},
            {"id": "river", "type": "line", "source": "gsi", "source-layer": "RvrCL", "minzoom": 9,
             "paint": {"line-color": c["river"], "line-width": 1}},
            {"id": "admin-boundary", "type": "line", "source": "gsi", "source-layer": "AdmBdry",
             "paint": {"line-color": c["boundary"], "line-width": 1}},
            {"id": "railway", "type": "line", "source": "gsi", "source-layer": "RailCL", "minzoom": 10,
             "paint": {"line-color": c["railway"], "line-width": 1, "line-dasharray": [4, 3]}},
            {"id": "road", "type": "line", "source": "gsi", "source-layer": "RdCL", "minzoom": 10,
             "paint": {"line-color": c["road"], "line-width": 1}},
            {
                "id": "place-label",
                "type": "symbol",
                "source": "gsi",
                "source-layer": "Anno",
                "filter": ["in", ["get", "vt_code"], ["literal", PLACE_LABEL_CODES]],
                "layout": {
                    "text-field": ["get", "vt_text"],
                    "text-font": ["NotoSansJP-Regular"],
                    "text-size": 15,
                },
                "paint": {
                    "text-color": c["label"],
                    "text-halo-color": c["label_halo"],
                    "text-halo-width": 2,
                },
            },
        ],
    }


def load_presets() -> list[dict]:
    presets = []
    for path in sorted(PRESETS.glob("*.json")):
        preset = json.loads(path.read_text(encoding="utf-8"))
        if preset.get("name") != path.stem:
            raise SystemExit(f"{path.name}: name must be {path.stem!r}")
        missing = [k for k in REQUIRED_COLORS if k not in preset.get("colors", {})]
        if missing:
            raise SystemExit(f"{path.name}: missing colors {missing}")
        presets.append(preset)
    return presets


def render(style: dict) -> str:
    return json.dumps(style, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="生成せず、styles/ が最新かだけを確かめる")
    args = parser.parse_args()

    stale = []
    STYLES.mkdir(exist_ok=True)
    for preset in load_presets():
        target = STYLES / f"{preset['name']}.json"
        text = render(build(preset))
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                stale.append(target.name)
        else:
            target.write_text(text, encoding="utf-8")
            print(f"wrote styles/{target.name}")
    if stale:
        print(f"styles/ is out of date: {', '.join(stale)}. Run python3 scripts/build_styles.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
