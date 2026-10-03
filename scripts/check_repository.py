"""Check local Markdown links and common publication hazards; no network requests.

Optional --history scans every reachable Git blob and commit metadata as well.
This is a heuristic check, not a guarantee that no secret exists.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "GitHub token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"),
    "AWS access key": re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    "API token": re.compile(rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{32,}|xox[baprs]-[A-Za-z0-9-]{20,})"),
    "personal path": re.compile(rb"/(?:Users|home)/[A-Za-z0-9._-]+/"),
}
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LINK = re.compile(r"!?\[[^\]\n]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def hazards(data: bytes) -> list[str]:
    found = [name for name, pattern in PATTERNS.items() if pattern.search(data)]
    public_email = lambda value: value.endswith(b"@users.noreply.github.com") or value in {b"noreply@github.com", b"noreply@anthropic.com"}
    if any(not public_email(match) for match in EMAIL.findall(data)):
        found.append("non-noreply email (review required)")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    failures = []
    names = [n for n in git("ls-files", "-z").decode().split("\0") if n]
    links = 0
    for name in names:
        path = ROOT / name
        if not path.is_file():
            failures.append(f"{name}: missing tracked file")
            continue
        if (path.name.startswith(".env") and path.name != ".env.example") or path.suffix in {".pem", ".key", ".pmtiles", ".pbf"}:
            failures.append(f"{name}: private or raw-data file (review required)")
        for kind in hazards(path.read_bytes()):
            failures.append(f"{name}: {kind}")
        if path.suffix == ".md":
            for target in LINK.findall(path.read_text()):
                parts = urlsplit(target.strip("<>"))
                if parts.scheme or parts.netloc or not parts.path:
                    continue
                links += 1
                dest = (path.parent / unquote(parts.path)).resolve()
                if not dest.is_relative_to(ROOT) or not dest.exists():
                    failures.append(f"{name}: broken/outside local link {target}")
    blobs = commits = 0
    if args.history:
        for line in git("rev-list", "--objects", "--all").decode().splitlines():
            sha = line.split(" ", 1)[0]
            kind = git("cat-file", "-t", sha).strip()
            if kind not in {b"blob", b"commit"}:
                continue
            blobs += kind == b"blob"
            commits += kind == b"commit"
            for hazard in hazards(git("cat-file", kind.decode(), sha)):
                failures.append(f"history {sha[:12]}: {hazard}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"OK: {len(names)} tracked files, {links} local links; history: {commits} commits, {blobs} blobs")
    print("Heuristic scan only; manually review new data sources and unfamiliar secret formats.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
