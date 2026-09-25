"""観測スクリプトの共通部分。

地理院のサーバへは、1ホストあたり1秒以上の間隔を空けて順番に要求する。
取得したものは集計にだけ使い、タイルそのものはリポジトリへ保存しない。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

USER_AGENT = "gsi-field-notes/0.1 (+https://github.com/rihito-dev/gsi-field-notes)"
MIN_INTERVAL = 1.0

PMTILES_URL = "https://cyberjapandata.gsi.go.jp/xyz/optimal_bvmap-v1/optimal_bvmap-v1.pmtiles"
DEM_PNG_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png"


@dataclass(frozen=True)
class Point:
    name: str
    lon: float
    lat: float


# 全数調査ではなく、決めた地点の真上のタイルだけを見る。地点は結果を見る前に固定する。
HOKKAIDO_POINTS = [
    Point("sapporo", 141.3544, 43.0621),
    Point("hakodate", 140.7288, 41.7687),
    Point("asahikawa", 142.3650, 43.7706),
    Point("kushiro", 144.3814, 42.9849),
    Point("wakkanai", 141.6730, 45.4156),
    Point("assabu", 140.2270, 41.9210),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


class PoliteSession:
    """同じホストへの要求の開始間隔を MIN_INTERVAL 以上に保つ。"""

    def __init__(self, interval: float = MIN_INTERVAL) -> None:
        self.interval = interval
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last = 0.0
        self.requests_made = 0

    def get(self, url: str, **kwargs) -> requests.Response:
        wait = self._last + self.interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.requests_made += 1
        return self.session.get(url, timeout=30, **kwargs)


class RangeSource:
    """pmtiles.reader.Reader に渡す get_bytes。ヘッダとディレクトリの再取得を避けるため記憶する。"""

    def __init__(self, http: PoliteSession, url: str) -> None:
        self.http = http
        self.url = url
        self.cache: dict[tuple[int, int], bytes] = {}
        self.last_modified: str | None = None
        self.etag: str | None = None

    def __call__(self, offset: int, length: int) -> bytes:
        key = (offset, length)
        if key not in self.cache:
            res = self.http.get(self.url, headers={"Range": f"bytes={offset}-{offset + length - 1}"})
            res.raise_for_status()
            if res.status_code != 206:
                raise RuntimeError(f"range request not honoured: HTTP {res.status_code}")
            self.last_modified = res.headers.get("Last-Modified", self.last_modified)
            self.etag = res.headers.get("ETag", self.etag)
            self.cache[key] = res.content
        return self.cache[key]
