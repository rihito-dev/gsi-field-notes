"""Offline regression checks for saved observation reviews; synthetic fixtures only."""

from contextlib import redirect_stderr, redirect_stdout
import copy
import csv
import io
import json
from pathlib import Path
import random
import shutil
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import review_observations as review


class ReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.before, self.after, self.out = (self.root / name for name in ("before", "after", "review"))
        self.before.mkdir()
        self.vector = [
            {"zoom": "4", "layer": "AdmArea", "vt_code": "", "features": "23", "tiles": "1", "examples": ""},
            {"zoom": "4", "layer": "Anno", "vt_code": "1301", "features": "1", "tiles": "1", "examples": "札幌"},
            {"zoom": "8", "layer": "Anno", "vt_code": "1401", "features": "3", "tiles": "2", "examples": "合成地点"},
        ]
        self.dem = [dict(zip(review.PROFILES["dem_png"]["columns"],
                            ("sample", "8", "228", "94", "200", "4", "3", "1", "1", "-0.2", "2.0", "83886.08"))),
                    dict(zip(review.PROFILES["dem_png"]["columns"],
                            ("missing", "8", "228", "95", "404", "", "", "", "", "", "", "")))]
        for name, rows in (("vector_tiles", self.vector), ("dem_png", self.dem)):
            self.write_rows(self.before, name, rows)
            (self.before / (name + ".meta.json")).write_text(json.dumps({
                "checked_at": "2026-01-01T00:00:00+00:00", "source": "https://example.invalid/tiles",
                "points": [{"name": "sample", "lon": 140.0, "lat": 43.0}],
                "zooms": [4, 8] if name == "vector_tiles" else [8],
            }), encoding="utf-8")
        shutil.copytree(self.before, self.after)

    def write_rows(self, folder, name, rows, columns=None):
        with (folder / (name + ".csv")).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns or review.PROFILES[name]["columns"])
            writer.writeheader()
            writer.writerows(rows)

    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = review.main(args)
        return code, out.getvalue(), err.getvalue()

    def create(self):
        return review.create_review(self.before, self.after, self.out)

    def forge(self, report):
        report["receipt_sha256"] = review._receipt(report)
        (self.out / "review.json").write_text(json.dumps(report), encoding="utf-8")

    def test_known_row_differences_and_exact_count_movement_are_verified_offline(self):
        after = copy.deepcopy(self.vector[1:])
        after[0]["features"] = "4"
        after.append({"zoom": "8", "layer": "LdBdry", "vt_code": "test", "features": "10", "tiles": "2", "examples": ""})
        self.write_rows(self.after, "vector_tiles", after)
        dem = copy.deepcopy(self.dem)
        dem[1].update(http_status="200", pixels="4", valid="4", nodata="0", below_sea_level="0")
        self.write_rows(self.after, "dem_png", dem)
        with patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")) as network:
            report = self.create()
            review.verify_review(self.out)
            network.assert_not_called()
        vector = report["comparisons"]["vector_tiles"]
        self.assertEqual(vector["counts"], {"added": 1, "removed": 1, "changed": 1, "unchanged": 1})
        self.assertEqual(vector["count_totals"]["features"], {
            "before": 27, "after": 17, "delta": -10, "added": 10, "removed": 23,
            "changed_delta": 3, "before_blanks": 0, "after_blanks": 0})
        dem_totals = report["comparisons"]["dem_png"]["count_totals"]["pixels"]
        self.assertEqual((dem_totals["delta"], dem_totals["before_blanks"], dem_totals["after_blanks"]), (4, 1, 0))
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_inputs_are_exact_copies_and_verification_needs_no_original_directories(self):
        self.create()
        for name in review.FILES:
            self.assertEqual((self.before / name).read_bytes(), (self.out / "inputs" / "before" / name).read_bytes())
        shutil.rmtree(self.before)
        shutil.rmtree(self.after)
        review.verify_review(self.out)

    def test_row_and_column_reordering_changes_bytes_but_not_rows(self):
        self.write_rows(self.after, "vector_tiles", list(reversed(self.vector)),
                        tuple(reversed(review.PROFILES["vector_tiles"]["columns"])))
        report = self.create()
        self.assertNotEqual(report["inputs"]["before"], report["inputs"]["after"])
        self.assertEqual(report["comparisons"]["vector_tiles"]["counts"]["unchanged"], 3)
        self.assertEqual(report["comparisons"]["vector_tiles"]["counts"]["changed"], 0)

    def test_metadata_reports_conditions_separately_from_time_and_version(self):
        path = self.after / "vector_tiles.meta.json"
        meta = json.loads(path.read_bytes())
        meta.update(zooms=[4, 9], checked_at="2026-01-02T00:00:00+00:00", source_etag="synthetic")
        path.write_text(json.dumps(meta), encoding="utf-8")
        result = self.create()["comparisons"]["vector_tiles"]
        self.assertEqual([item["field"] for item in result["recorded_condition_changes"]], ["zooms"])
        self.assertEqual({item["field"] for item in result["metadata_changes"]}, {"zooms", "checked_at", "source_etag"})

    def test_counter_values_beyond_binary_float_precision_are_exact(self):
        rows = copy.deepcopy(self.vector)
        rows[0]["features"] = "9007199254740993"
        self.write_rows(self.after, "vector_tiles", rows)
        result = self.create()["comparisons"]["vector_tiles"]["count_totals"]["features"]
        self.assertEqual(result["after"], 9007199254740997)
        self.assertEqual(result["delta"], 9007199254740970)

    def test_duplicate_keys_invalid_counts_and_schema_errors_create_no_output(self):
        for scenario in ("duplicate", "negative", "decimal", "whitespace", "unicode", "blank", "missing_column", "ragged"):
            with self.subTest(scenario=scenario):
                rows = copy.deepcopy(self.vector)
                if scenario == "duplicate":
                    rows.append(copy.deepcopy(rows[0]))
                elif scenario in ("negative", "decimal", "whitespace", "unicode", "blank"):
                    rows[0]["features"] = {"negative": "-1", "decimal": "1.0", "whitespace": " 1", "unicode": "１２", "blank": ""}[scenario]
                self.write_rows(self.after, "vector_tiles", rows)
                path = self.after / "vector_tiles.csv"
                if scenario == "missing_column":
                    path.write_text("zoom,layer\n4,Anno\n", encoding="utf-8")
                if scenario == "ragged":
                    with path.open("a", encoding="utf-8") as stream:
                        stream.write("too,few\n")
                with self.assertRaises(review.ReviewError):
                    self.create()
                self.assertFalse(self.out.exists())

    def test_invalid_metadata_fails_without_creating_output(self):
        path = self.after / "dem_png.meta.json"
        for content in ('{"source":"a","source":"b"}', '{"x":NaN}', "[]", "[" * 1100, '{"points":[],"zooms":[]}'):
            with self.subTest(content=content[:30]):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(review.ReviewError):
                    self.create()
                self.assertFalse(self.out.exists())

    def test_missing_symlinked_and_oversize_inputs_fail_closed(self):
        path = self.after / "vector_tiles.csv"
        path.unlink()
        with self.assertRaises(review.ReviewError):
            self.create()
        path.symlink_to(self.before / "vector_tiles.csv")
        with self.assertRaises(review.ReviewError):
            self.create()
        with self.assertRaises(review.ReviewError):
            review._read(self.before / "vector_tiles.csv", limit=8)
        self.assertFalse(self.out.exists())

    def test_existing_output_is_never_overwritten(self):
        self.create()
        original = (self.out / "review.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual((self.out / "review.json").read_bytes(), original)

    def test_snapshot_edit_is_detected(self):
        self.create()
        (self.out / "inputs" / "before" / "vector_tiles.csv").write_bytes(b"edited")
        with self.assertRaises(review.ReviewError):
            review.verify_review(self.out)

    def test_rewritten_receipt_cannot_hide_forged_row_counts_or_numeric_totals(self):
        report = self.create()
        for section in ("rows", "totals"):
            with self.subTest(section=section):
                forged = copy.deepcopy(report)
                comparison = forged["comparisons"]["vector_tiles"]
                if section == "rows":
                    comparison["counts"]["unchanged"] += 1
                else:
                    comparison["count_totals"]["features"]["after"] += 1
                self.forge(forged)
                with self.assertRaises(review.ReviewError):
                    review.verify_review(self.out)

    def test_saved_markdown_edit_is_detected(self):
        self.create()
        (self.out / "review.md").write_text("misleading summary", encoding="utf-8")
        with self.assertRaises(review.ReviewError):
            review.verify_review(self.out)

    def test_second_implementation_detects_main_row_matching_and_totaling_failures(self):
        for target in ("_dictionary_diff", "_totals"):
            original = getattr(review, target)
            def wrong(*args):
                result = original(*args)
                if target == "_dictionary_diff":
                    result["unchanged"] += 1
                else:
                    next(iter(result.values()))["after"] += 1
                return result
            with self.subTest(target=target), patch.object(review, target, side_effect=wrong):
                with self.assertRaises(review.ReviewError):
                    self.create()
            self.assertFalse(self.out.exists())

    def test_small_generated_populations_match_a_hand_constructed_oracle(self):
        rng = random.Random(42)
        base = self.vector[0]
        for size in (0, 1, 20):
            old = [dict(base, vt_code=str(i), features=str(rng.randrange(100))) for i in range(size)]
            new = [dict(row) for row in old if int(row["vt_code"]) % 3 != 0]
            changed = 0
            for row in new:
                if int(row["vt_code"]) % 3 == 1:
                    row["features"] = str(int(row["features"]) + 1)
                    changed += 1
            new.append(dict(base, vt_code="extra", features="7"))
            self.write_rows(self.before, "vector_tiles", old)
            self.write_rows(self.after, "vector_tiles", new)
            report = review.create_review(self.before, self.after, self.root / f"generated-{size}")
            counts = report["comparisons"]["vector_tiles"]["counts"]
            self.assertEqual(counts, {"added": 1, "removed": sum(i % 3 == 0 for i in range(size)),
                                      "changed": changed, "unchanged": sum(i % 3 == 2 for i in range(size))})

    def test_cli_exit_codes_distinguish_equal_changed_verified_and_invalid(self):
        args = ["--before", str(self.before), "--after", str(self.after), "--out", str(self.out)]
        self.assertEqual(self.invoke(args)[0], 0)
        self.assertEqual(self.invoke(["--verify", str(self.out)])[0], 0)
        self.assertEqual(self.invoke(args)[0], 2)
        rows = copy.deepcopy(self.vector)
        rows[0]["examples"] = "changed"
        self.write_rows(self.after, "vector_tiles", rows)
        args[-1] = str(self.root / "changed")
        self.assertEqual(self.invoke(args)[0], 1)


if __name__ == "__main__":
    unittest.main()
