"""Compare completed observation runs offline and retain the exact reviewed inputs.

Only vector_tiles.csv/dem_png.csv and their metadata are supported. No tile
downloads or third-party packages are needed. Exit 0: equal/verified, 1: changes,
2: invalid input or failed verification. Use --verify to recheck a saved review.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import sys

PROFILES = {
    "vector_tiles": {
        "columns": ("zoom", "layer", "vt_code", "features", "tiles", "examples"),
        "keys": ("zoom", "layer", "vt_code"),
        "counts": ("features", "tiles"),
    },
    "dem_png": {
        "columns": ("point", "zoom", "x", "y", "http_status", "pixels", "valid", "nodata",
                    "below_sea_level", "true_min_m", "true_max_m", "linear_max_m"),
        "keys": ("point", "zoom", "x", "y"),
        "counts": ("pixels", "valid", "nodata", "below_sea_level"),
    },
}
CONDITION_FIELDS = ("source", "points", "zooms", "linear_factors", "tiles_observed", "tiles_missing")
VERIFICATION = {
    "rows": "dictionary join checked by a sorted merge of separately parsed snapshots",
    "counts": "exact integer totals reconciled with added - removed + changed",
    "scope": "stored CSV/metadata bytes and reported results; not source-data truth or a signature",
}
FILES = tuple(f"{name}{suffix}" for name in PROFILES for suffix in (".csv", ".meta.json"))
MAX_INPUT_BYTES = 16 * 1024 * 1024


class ReviewError(ValueError):
    """The input or stored review cannot be verified."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _receipt(report: dict) -> str:
    return sha256(_canonical({k: v for k, v in report.items() if k != "receipt_sha256"})).hexdigest()


def _unique(pairs: list) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ReviewError("duplicate JSON field")
        result[name] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ReviewError("non-finite JSON number")


def _json(data: bytes) -> dict:
    try:
        value = json.loads(data, object_pairs_hook=_unique, parse_constant=_invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise ReviewError("invalid or excessively nested JSON") from exc
    if not isinstance(value, dict):
        raise ReviewError("JSON must be an object")
    return value


def _read(path: Path, limit: int = MAX_INPUT_BYTES) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ReviewError(f"expected a regular, non-symlinked file: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ReviewError(f"file exceeds the {limit}-byte limit: {path.name}")
    return data


def _snapshots(root: Path) -> dict[str, bytes]:
    return {name: _read(root / name) for name in FILES}


def _identity(snapshots: dict[str, bytes]) -> dict:
    return {name: {"sha256": sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in snapshots.items()}


def _rows(data: bytes, profile: dict) -> list[dict[str, str]]:
    reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    header = next(reader, [])
    if len(header) != len(set(header)) or set(header) != set(profile["columns"]):
        raise ReviewError("CSV columns do not match the supported observation schema")
    rows, seen = [], set()
    for line, values in enumerate(reader, 2):
        if len(values) != len(header):
            raise ReviewError(f"CSV row {line}: wrong number of cells")
        row = dict(zip(header, values))
        key = tuple(row[col] for col in profile["keys"])
        if any(not row[col] for col in profile["keys"] if col != "vt_code"):
            raise ReviewError(f"CSV row {line}: empty key")
        if key in seen:
            raise ReviewError(f"CSV row {line}: duplicate key")
        seen.add(key)
        for col in profile["counts"]:
            value = row[col]
            if value and (not value.isascii() or not value.isdigit()):
                raise ReviewError(f"CSV row {line}: {col} must be a nonnegative integer or blank")
            if not value and "point" not in profile["keys"]:
                raise ReviewError(f"CSV row {line}: {col} cannot be blank")
        rows.append(row)
    return rows


def _metadata(data: bytes) -> dict:
    value = _json(data)
    for field in ("checked_at", "source"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise ReviewError(f"metadata requires a nonempty {field}")
    for field in ("points", "zooms"):
        if not isinstance(value.get(field), list) or not value[field]:
            raise ReviewError(f"metadata requires a nonempty {field} list")
    return value


def _metadata_changes(before: dict, after: dict) -> list[dict]:
    return [{"field": field, "before_present": field in before, "before": before.get(field),
             "after_present": field in after, "after": after.get(field)}
            for field in sorted(before.keys() | after.keys())
            if (field in before) != (field in after) or _canonical(before.get(field)) != _canonical(after.get(field))]


def _dictionary_diff(before: list[dict], after: list[dict], keys: tuple) -> dict:
    old = {tuple(row[col] for col in keys): row for row in before}
    new = {tuple(row[col] for col in keys): row for row in after}
    added = [new[key] for key in sorted(new.keys() - old.keys())]
    removed = [old[key] for key in sorted(old.keys() - new.keys())]
    changed = [{"before": old[key], "after": new[key]} for key in sorted(old.keys() & new.keys())
               if old[key] != new[key]]
    return {"added": added, "removed": removed, "changed": changed,
            "unchanged": len(old) - len(removed) - len(changed)}


def _sorted_diff(before: list[dict], after: list[dict], keys: tuple) -> dict:
    """Second row-matching implementation; no dictionary join or set partition."""
    old = sorted((tuple(row[col] for col in keys), row) for row in before)
    new = sorted((tuple(row[col] for col in keys), row) for row in after)
    result = {"added": [], "removed": [], "changed": [], "unchanged": 0}
    i = j = 0
    while i < len(old) or j < len(new):
        if j == len(new) or (i < len(old) and old[i][0] < new[j][0]):
            result["removed"].append(old[i][1])
            i += 1
        elif i == len(old) or new[j][0] < old[i][0]:
            result["added"].append(new[j][1])
            j += 1
        else:
            if old[i][1] == new[j][1]:
                result["unchanged"] += 1
            else:
                result["changed"].append({"before": old[i][1], "after": new[j][1]})
            i += 1
            j += 1
    return result


def _totals(before: list[dict], after: list[dict], changes: dict, columns: tuple) -> dict:
    result = {}
    for col in columns:
        old = sum(int(row[col] or "0") for row in before)
        new = sum(int(row[col] or "0") for row in after)
        added = sum(int(row[col] or "0") for row in changes["added"])
        removed = sum(int(row[col] or "0") for row in changes["removed"])
        changed = sum(int(item["after"][col] or "0") - int(item["before"][col] or "0")
                      for item in changes["changed"])
        if new - old != added - removed + changed:
            raise ReviewError(f"{col}: row movements do not reconcile with the column totals")
        result[col] = {"before": old, "after": new, "delta": new - old,
                       "added": added, "removed": removed, "changed_delta": changed,
                       "before_blanks": sum(row[col] == "" for row in before),
                       "after_blanks": sum(row[col] == "" for row in after)}
    return result


def _verified_totals(before: list[dict], after: list[dict], changes: dict, columns: tuple) -> dict:
    """Re-accumulate with a separate ledger rather than calling the main totaler."""
    result = {}
    for col in columns:
        ledger = Counter({field: 0 for field in ("before", "after", "added", "removed",
                          "changed_delta", "before_blanks", "after_blanks")})
        for side, rows in (("before", before), ("after", after),
                           ("added", changes["added"]), ("removed", changes["removed"])):
            for row in rows:
                if row[col]:
                    ledger[side] += int(row[col])
                elif side in ("before", "after"):
                    ledger[side + "_blanks"] += 1
        for item in changes["changed"]:
            ledger["changed_delta"] += int(item["after"][col] or "0") - int(item["before"][col] or "0")
        ledger["delta"] = ledger["after"] - ledger["before"]
        if ledger["delta"] != ledger["added"] - ledger["removed"] + ledger["changed_delta"]:
            raise ReviewError(f"{col}: verification ledger does not balance")
        result[col] = dict(ledger)
    return result


def _comparison(old: dict[str, bytes], new: dict[str, bytes], name: str, *, verify: bool) -> dict:
    profile = PROFILES[name]
    before = _rows(old[name + ".csv"], profile)
    after = _rows(new[name + ".csv"], profile)
    changes = (_sorted_diff if verify else _dictionary_diff)(before, after, profile["keys"])
    metadata = _metadata_changes(_metadata(old[name + ".meta.json"]), _metadata(new[name + ".meta.json"]))
    return {"keys": list(profile["keys"]), "count_columns": list(profile["counts"]),
            "counts": {kind: changes[kind] if kind == "unchanged" else len(changes[kind])
                       for kind in ("added", "removed", "changed", "unchanged")},
            "changes": {kind: changes[kind] for kind in ("added", "removed", "changed")},
            "count_totals": (_verified_totals if verify else _totals)(before, after, changes, profile["counts"]),
            "metadata_changes": metadata,
            "recorded_condition_changes": [item for item in metadata if item["field"] in CONDITION_FIELDS]}


def _verify(report: dict, before: dict[str, bytes], after: dict[str, bytes]) -> None:
    if set(report) != {"schema_version", "reviewer_sha256", "inputs", "comparisons", "verification", "receipt_sha256"}:
        raise ReviewError("unsupported review fields")
    if type(report.get("schema_version")) is not int or report["schema_version"] != 1 or report.get("receipt_sha256") != _receipt(report):
        raise ReviewError("unsupported review schema or receipt checksum mismatch")
    reviewer = report.get("reviewer_sha256")
    if not isinstance(reviewer, str) or len(reviewer) != 64 or any(c not in "0123456789abcdef" for c in reviewer):
        raise ReviewError("invalid reviewer content hash")
    if _canonical(report.get("inputs")) != _canonical({"before": _identity(before), "after": _identity(after)}):
        raise ReviewError("stored input bytes disagree with the review receipt")
    expected = {name: _comparison(before, after, name, verify=True) for name in PROFILES}
    if _canonical(report.get("comparisons")) != _canonical(expected) or report.get("verification") != VERIFICATION:
        raise ReviewError("saved results disagree with the independently matched rows")


def _markdown(report: dict) -> str:
    lines = ["# 観測更新の比較", "", "保存したCSVとメタデータの比較です。実データの正しさや全国の傾向を判定するものではありません。",
             "", "原本コピーは `inputs/`、全件明細とハッシュは `review.json` にあります。", ""]
    for name, item in report["comparisons"].items():
        counts = item["counts"]
        lines += [f"## {name}", "", f"追加 {counts['added']} / 削除 {counts['removed']} / 変更 {counts['changed']} / 不変 {counts['unchanged']}",
                  "", "| 件数列 | 前 | 後 | 増減 | 追加 − 削除 ＋ 変更分 |", "|---|---:|---:|---:|---:|"]
        for col, total in item["count_totals"].items():
            lines.append(f"| {col} | {total['before']} | {total['after']} | {total['delta']} | "
                         f"{total['added']} − {total['removed']} ＋ {total['changed_delta']} |")
        lines += ["", "列の単純合計です。空欄は0寄与とし、件数をJSONに記録します。ズーム間の重複や標本範囲を除いた全数集計ではありません。", "",
                  "### 記録された観測条件の差", "", "```json",
                  json.dumps(item["recorded_condition_changes"], ensure_ascii=False, indent=2), "```", "",
                  "日時・版などを含む全メタデータの差はJSONに記録しています。条件の差があれば、行の差をタイルの更新だけに帰属させないでください。", ""]
        for kind, rows in item["changes"].items():
            if rows:
                lines += [f"### {kind}（先頭20件 / 全{len(rows)}件）", "", "```json",
                          json.dumps(rows[:20], ensure_ascii=False, indent=2), "```", ""]
    return "\n".join(lines)


def create_review(before_dir: Path, after_dir: Path, output: Path) -> dict:
    before, after = _snapshots(before_dir), _snapshots(after_dir)
    report = {"schema_version": 1, "reviewer_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "inputs": {"before": _identity(before), "after": _identity(after)},
              "comparisons": {name: _comparison(before, after, name, verify=False) for name in PROFILES},
              "verification": VERIFICATION}
    report["receipt_sha256"] = _receipt(report)
    _verify(report, before, after)
    # Exclusive creation prevents replacing previous reviews or input directories.
    # review.json is written last; interrupted output without it is incomplete.
    output.mkdir(parents=True, exist_ok=False)
    for side, snapshots in (("before", before), ("after", after)):
        folder = output / "inputs" / side
        folder.mkdir(parents=True)
        for name, data in snapshots.items():
            (folder / name).write_bytes(data)
    (output / "review.md").write_text(_markdown(report), encoding="utf-8")
    (output / "review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return verify_review(output)


def verify_review(output: Path) -> dict:
    report = _json(_read(output / "review.json", 128 * 1024 * 1024))
    _verify(report, _snapshots(output / "inputs" / "before"), _snapshots(output / "inputs" / "after"))
    if _read(output / "review.md") != _markdown(report).encode("utf-8"):
        raise ReviewError("readable summary disagrees with the verified review")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, help="completed baseline observation directory")
    parser.add_argument("--after", type=Path, help="completed new observation directory")
    parser.add_argument("--out", type=Path, help="new output directory; never overwritten")
    parser.add_argument("--verify", type=Path, metavar="REVIEW", help="recheck a saved review offline")
    args = parser.parse_args(argv)
    if (args.verify and any((args.before, args.after, args.out))) or (not args.verify and not all((args.before, args.after, args.out))):
        parser.error("use --before/--after/--out together, or --verify alone")
    try:
        report = verify_review(args.verify) if args.verify else create_review(args.before, args.after, args.out)
        changed = False
        for name, item in report["comparisons"].items():
            print(f"{name}: {json.dumps(item['counts'])}; metadata changes: {len(item['metadata_changes'])}")
            changed |= bool(item["metadata_changes"] or any(item["counts"][k] for k in ("added", "removed", "changed")))
        print("Verified: input hashes, every row difference, count reconciliation and saved summary")
        return 0 if args.verify else int(changed)
    except (OSError, ValueError, csv.Error, RecursionError, KeyError, TypeError) as exc:
        print(f"review_observations: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
