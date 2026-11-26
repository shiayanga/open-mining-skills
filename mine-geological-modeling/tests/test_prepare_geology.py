#!/usr/bin/env python3
"""Tests for the mine-geological-modeling scripts."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import prepare_geology  # noqa: E402


def call_silently(function, argv):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        return function(argv)


class PrepareGeologyTests(unittest.TestCase):
    def test_valid_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = prepare_geology.prepare_geology(
                str(FIXTURES / "interfaces_valid.csv"),
                boreholes_path=str(FIXTURES / "boreholes_valid.csv"),
                out_dir=tmp,
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["report"]["validation"]["errors"], [])

            counts = result["report"]["counts"]
            self.assertEqual(counts["interface_points"], 9)
            self.assertEqual(counts["orientations"], 5)
            self.assertEqual(counts["series"], 2)
            self.assertEqual(counts["surfaces"], 3)
            self.assertEqual(counts["borehole_observations"], 3)
            self.assertEqual(counts["boreholes"], 2)
            self.assertEqual(counts["duplicate_pairs"], 0)

            definition = result["definition"]
            self.assertIsNotNone(definition)
            self.assertEqual(
                definition["extent"], [100.0, 500.0, 100.0, 700.0, 88.0, 121.0]
            )
            self.assertEqual(
                definition["extent_order"],
                ["x_min", "x_max", "y_min", "y_max", "z_min", "z_max"],
            )
            self.assertEqual(definition["resolution"], [50, 50, 50])
            self.assertEqual(
                [series["name"] for series in definition["series"]],
                ["overburden", "ore"],
            )
            self.assertEqual(
                definition["series"][0]["surfaces"], ["topsoil", "clay"]
            )
            self.assertEqual(definition["series"][1]["surfaces"], ["ore_body"])

            surfaces = {item["name"]: item for item in definition["surfaces"]}
            self.assertEqual(surfaces["topsoil"]["interface_count"], 3)
            self.assertEqual(surfaces["topsoil"]["orientation_count"], 3)
            self.assertEqual(surfaces["clay"]["interface_count"], 3)
            self.assertEqual(surfaces["clay"]["orientation_count"], 0)
            self.assertEqual(surfaces["ore_body"]["interface_count"], 3)
            self.assertEqual(surfaces["ore_body"]["orientation_count"], 2)

            self.assertEqual(len(definition["interfaces"]), 9)
            self.assertEqual(len(definition["orientations"]), 5)
            first_orientation = definition["orientations"][0]
            self.assertEqual(first_orientation["dip"], 5.0)
            self.assertEqual(first_orientation["azimuth"], 90.0)
            self.assertEqual(first_orientation["polarity"], 1)
            self.assertEqual(first_orientation["surface"], "topsoil")

            self.assertEqual(definition["boreholes"]["observation_count"], 3)
            self.assertEqual(definition["boreholes"]["borehole_count"], 2)
            self.assertEqual(definition["target"]["software"], "GemPy")
            self.assertFalse(definition["target"]["executed"])

            paths = result["paths"]
            self.assertTrue(Path(paths["definition"]).is_file())
            self.assertTrue(Path(paths["report_json"]).is_file())
            self.assertTrue(Path(paths["report_md"]).is_file())
            report = json.loads(
                Path(paths["report_json"]).read_text(encoding="utf-8")
            )
            self.assertEqual(report["status"], "ok")
            self.assertTrue(report["definition_written"])
            self.assertTrue(report["source"]["interfaces"]["sha256"])
            self.assertTrue(report["source"]["boreholes"]["sha256"])
            warning_codes = {
                item["code"] for item in report["validation"]["warnings"]
            }
            self.assertIn("SERIES_ORDER_ASSUMED", warning_codes)
            self.assertIn("EXTENT_EQUALS_DATA_BOUNDS", warning_codes)
            self.assertNotIn("SPARSE_SURFACE", warning_codes)

            markdown = Path(paths["report_md"]).read_text(encoding="utf-8")
            self.assertIn("# Geological Model Preparation Report", markdown)
            self.assertIn("overburden", markdown)
            self.assertIn("ore_body", markdown)

    def test_invalid_dataset_flags_dip_duplicate_and_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = prepare_geology.prepare_geology(
                str(FIXTURES / "interfaces_invalid.csv"),
                out_dir=tmp,
            )
            self.assertEqual(result["status"], "invalid")
            self.assertIsNone(result["definition"])
            self.assertFalse((Path(tmp) / "model_definition.json").exists())
            self.assertTrue((Path(tmp) / "geology_report.json").is_file())
            self.assertTrue((Path(tmp) / "geology_report.md").is_file())
            self.assertEqual(result["report"]["status"], "invalid")
            self.assertFalse(result["report"]["definition_written"])

            errors = result["report"]["validation"]["errors"]
            codes = {item["code"] for item in errors}
            self.assertIn("DIP_OUT_OF_RANGE", codes)
            self.assertIn("AZIMUTH_OUT_OF_RANGE", codes)
            self.assertIn("DUPLICATE_INTERFACE", codes)
            self.assertIn("SERIES_SURFACE_CONFLICT", codes)
            self.assertIn("NON_NUMERIC_COORDINATE", codes)

            dip_error = next(item for item in errors if item["code"] == "DIP_OUT_OF_RANGE")
            self.assertEqual(dip_error["line"], 3)
            self.assertEqual(dip_error["value"], 120.0)
            self.assertEqual(dip_error["field"], "dip")

            azimuth_error = next(
                item for item in errors if item["code"] == "AZIMUTH_OUT_OF_RANGE"
            )
            self.assertEqual(azimuth_error["line"], 4)
            self.assertEqual(azimuth_error["value"], 400.0)

            duplicate = next(
                item for item in errors if item["code"] == "DUPLICATE_INTERFACE"
            )
            self.assertEqual(duplicate["line"], 11)
            self.assertEqual(duplicate["other_line"], 2)
            self.assertEqual(duplicate["coordinates"], [100.0, 100.0, 120.0])

            conflict = next(
                item for item in errors if item["code"] == "SERIES_SURFACE_CONFLICT"
            )
            self.assertEqual(conflict["surface"], "clay")
            self.assertEqual(conflict["series"], ["ore", "overburden"])

            non_numeric = next(
                item for item in errors if item["code"] == "NON_NUMERIC_COORDINATE"
            )
            self.assertEqual(non_numeric["line"], 12)
            self.assertEqual(non_numeric["field"], "z")

    def test_series_order_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = prepare_geology.prepare_geology(
                str(FIXTURES / "interfaces_valid.csv"),
                out_dir=tmp,
                series_order_value="ore,overburden",
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(
                [series["name"] for series in result["definition"]["series"]],
                ["ore", "overburden"],
            )
            warning_codes = {
                item["code"]
                for item in result["report"]["validation"]["warnings"]
            }
            self.assertNotIn("SERIES_ORDER_ASSUMED", warning_codes)

    def test_extent_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = prepare_geology.prepare_geology(
                str(FIXTURES / "interfaces_valid.csv"),
                out_dir=tmp,
                extent_value="0,600,0,800,50,150",
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(
                result["definition"]["extent"], [0.0, 600.0, 0.0, 800.0, 50.0, 150.0]
            )
            self.assertEqual(result["report"]["resolution"], [50, 50, 50])

    def test_extent_must_contain_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = prepare_geology.prepare_geology(
                str(FIXTURES / "interfaces_valid.csv"),
                out_dir=tmp,
                extent_value="200,600,200,800,50,150",
            )
            self.assertEqual(result["status"], "invalid")
            self.assertIsNone(result["definition"])
            codes = {
                item["code"]
                for item in result["report"]["validation"]["errors"]
            }
            self.assertIn("EXTENT_DOES_NOT_CONTAIN_DATA", codes)

    def test_headerless_interfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "interfaces.csv"
            path.write_text(
                "100,100,120,overburden,topsoil,5,90\n"
                "200,150,118,overburden,clay,,\n"
                "300,200,90,ore,ore_body,15,120\n",
                encoding="utf-8",
            )
            loaded = prepare_geology.load_interfaces(str(path))
            self.assertFalse(loaded["has_header"])
            self.assertEqual(loaded["delimiter"], ",")
            self.assertEqual(len(loaded["points"]), 3)
            self.assertEqual(len(loaded["orientations"]), 2)
            self.assertEqual(loaded["errors"], [])
            self.assertEqual(
                loaded["points"][0],
                {
                    "x": 100.0,
                    "y": 100.0,
                    "z": 120.0,
                    "series": "overburden",
                    "surface": "topsoil",
                    "source_line": 1,
                },
            )

    def test_resolution_and_extent_parsing(self):
        self.assertEqual(
            prepare_geology.parse_resolution("50, 40, 25"), [50, 40, 25]
        )
        with self.assertRaises(SystemExit):
            prepare_geology.parse_resolution("50,40")
        with self.assertRaises(SystemExit):
            prepare_geology.parse_resolution("50,0,25")
        extent = prepare_geology.parse_extent("100,500,100,700,88,121")
        self.assertEqual(extent["min"], [100.0, 100.0, 88.0])
        self.assertEqual(extent["max"], [500.0, 700.0, 121.0])
        self.assertEqual(extent["gem_py"], [100.0, 500.0, 100.0, 700.0, 88.0, 121.0])
        with self.assertRaises(SystemExit):
            prepare_geology.parse_extent("100,500,100,700,88")

    def test_main_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                call_silently(
                    prepare_geology.main,
                    [
                        str(FIXTURES / "interfaces_valid.csv"),
                        "--out-dir",
                        str(Path(tmp) / "valid"),
                    ],
                ),
                0,
            )
            self.assertTrue(
                (Path(tmp) / "valid" / "model_definition.json").is_file()
            )
            self.assertEqual(
                call_silently(
                    prepare_geology.main,
                    [
                        str(FIXTURES / "interfaces_invalid.csv"),
                        "--out-dir",
                        str(Path(tmp) / "invalid"),
                    ],
                ),
                1,
            )
            self.assertFalse(
                (Path(tmp) / "invalid" / "model_definition.json").exists()
            )
            self.assertTrue(
                (Path(tmp) / "invalid" / "geology_report.json").is_file()
            )

    def test_stale_definition_is_removed_on_invalid_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "model_definition.json"
            stale.write_text('{"stale": true}', encoding="utf-8")
            result = prepare_geology.prepare_geology(
                str(FIXTURES / "interfaces_invalid.csv"),
                out_dir=tmp,
            )
            self.assertEqual(result["status"], "invalid")
            self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
