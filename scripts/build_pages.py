"""Package only the demo's runtime files for GitHub Pages; standard library only."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="0; url=./demo/">
  <title>gsi-field-notes — 地理院タイルのデモ</title>
</head>
<body>
  <p><a href="./demo/">地理院タイルのデモを開く</a></p>
  <script>
    const target = new URL("./demo/", location.href);
    target.search = location.search;
    target.hash = location.hash;
    location.replace(target.href);
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "work" / "pages",
                        help="empty output directory (default: work/pages)")
    out = parser.parse_args().out
    if out.exists() and any(out.iterdir()):
        parser.error("output directory must be empty; choose a fresh --out")

    files = [Path("demo/index.html"), Path("demo/local.geojson"),
             Path("src/gsi-dem-protocol.js"), Path("LICENSE")]
    files += sorted(path.relative_to(ROOT) for path in (ROOT / "styles").glob("*.json"))
    for name in files:
        source = ROOT / name
        if source.is_symlink() or not source.is_file():
            parser.error(f"missing or symlinked runtime file: {name}")
    out.mkdir(parents=True, exist_ok=True)
    for name in files:
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    (out / "index.html").write_text(ENTRY, encoding="utf-8")
    print(f"Built {len(files) + 1} static files in {out}")


if __name__ == "__main__":
    main()
