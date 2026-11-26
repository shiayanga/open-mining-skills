#!/usr/bin/env python3
"""Tests for the mine-point-cloud scripts."""

from __future__ import annotations

import csv
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SURVEY = FIXTURES / "survey_points.xyz"

try:
    import numpy as np
except ImportError:
    np = None

HAVE_NUMPY = np is not None
if HAVE_NUMPY:
    sys.path.insert(0, str(SKILL_DIR / "scripts"))
    import pointcloud  # noqa: E402


def build_las(
    path: Path,
    version: tuple[int, int] = (1, 2),
    point_format: int = 0,
    record_length: int = 20,
    count: int = 5,
    compressed: bool = False,
    extended_count: int | None = None,
) -> None:
    """Write a minimal valid LAS header plus dummy point records."""
    major, minor = version
    header_size = 227 if minor <= 2 else (235 if minor == 3 else 375)
    data = bytearray(header_size)
    struct.pack_into("<4s", data, 0, b"LASF")
    struct.pack_into("<H", data, 4, 17)
    struct.pack_into("<H", data, 6, 0)
    struct.pack_into("<B", data, 24, major)
    struct.pack_into("<B", data, 25, minor)
    data[26:58] = b"Test System".ljust(32, b"\0")
    data[58:90] = b"mine-point-cloud test".ljust(32, b"\0")
    struct.pack_into("<H", data, 90, 123)
    struct.pack_into("<H", data, 92, 2026)
    struct.pack_into("<H", data, 94, header_size)
    struct.pack_into("<I", data, 96, header_size)
    struct.pack_into("<I", data, 100, 0)
    struct.pack_into(
        "<B", data, 104, point_format | (128 if compressed else 0)
    )
    struct.pack_into("<H", data, 105, record_length)
    legacy_count = 0 if (minor == 4 and extended_count is not None) else count
    struct.pack_into("<I", data, 107, legacy_count)
    struct.pack_into("<5I", data, 111, legacy_count, 0, 0, 0, 0)
    struct.pack_into("<3d", data, 131, 0.01, 0.01, 0.001)
    struct.pack_into("<3d", data, 155, 1000.0, 2000.0, 50.0)
    # max_x, min_x, max_y, min_y, max_z, min_z
    struct.pack_into(
        "<6d", data, 179, 1012.34, 1000.0, 2020.5, 2000.0, 65.432, 50.0
    )
    if minor >= 3:
        struct.pack_into("<Q", data, 227, 0)
    if minor >= 4:
        struct.pack_into("<Q", data, 235, 0)
        struct.pack_into("<I", data, 243, 0)
        ext = extended_count if extended_count is not None else count
        struct.pack_into("<Q", data, 247, ext)
        struct.pack_into("<15Q", data, 255, ext, *([0] * 14))
    with path.open("wb") as fh:
        fh.write(data)
        fh.write(b"\0" * (record_length * count))


@unittest.skipUnless(HAVE_NUMPY, "numpy is not installed")
class LasHeaderTests(unittest.TestCase):
    def test_las_1_2_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cloud.las"
            build_las(path)
            report = pointcloud.inspect_las(str(path))

        self.assertEqual(report["signature"], "LASF")
        self.assertEqual(report["version"], "1.2")
        self.assertTrue(report["supported_version"])
        self.assertEqual(report["header_size"], 227)
        self.assertEqual(report["point_data_offset"], 227)
        self.assertEqual(report["vlr_count"], 0)
        self.assertEqual(report["point_format"]["id"], 0)
        self.assertFalse(report["point_format"]["compressed"])
        self.assertEqual(report["point_format"]["record_length"], 20)
        self.assertEqual(report["point_count"], 5)
        self.assertEqual(report["point_count_source"], "legacy")
        self.assertEqual(report["legacy_point_count"], 5)
        self.assertIsNone(report["extended_point_count"])
        self.assertEqual(report["scale"], {"x": 0.01, "y": 0.01, "z": 0.001})
        self.assertEqual(report["offset"], {"x": 1000.0, "y": 2000.0, "z": 50.0})
        self.assertEqual(report["bounds"]["min_x"], 1000.0)
        self.assertEqual(report["bounds"]["max_x"], 1012.34)
        self.assertAlmostEqual(report["bounds"]["span_z"], 15.432)
        self.assertEqual(report["creation"], {"day_of_year": 123, "year": 2026})
        self.assertEqual(report["system_identifier"], "Test System")
        self.assertEqual(report["generating_software"], "mine-point-cloud test")
        self.assertEqual(report["expected_point_data_bytes"], 100)
        self.assertEqual(report["units"], "UNKNOWN")
        self.assertEqual(report["warnings"], [])

    def test_las_1_4_extended_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cloud14.las"
            build_las(
                path,
                version=(1, 4),
                count=7,
                extended_count=7,
            )
            report = pointcloud.inspect_las(str(path))

        self.assertEqual(report["version"], "1.4")
        self.assertEqual(report["header_size"], 375)
        self.assertEqual(report["point_count"], 7)
        self.assertEqual(report["point_count_source"], "extended")
        self.assertEqual(report["legacy_point_count"], 0)
        self.assertEqual(report["extended_point_count"], 7)
        self.assertEqual(report["evlr"], {"count": 0, "offset": 0})
        self.assertEqual(report["points_by_return"]["extended"][0], 7)

    def test_laz_compression_flag_is_reported_not_decoded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cloud.laz"
            build_las(path, point_format=1, compressed=True)
            report = pointcloud.inspect_las(str(path))

        self.assertTrue(report["point_format"]["compressed"])
        self.assertEqual(report["point_format"]["id"], 1)
        self.assertIsNone(report["expected_point_data_bytes"])
        self.assertTrue(any("PDAL" in warning for warning in report["warnings"]))

    def test_invalid_signature_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.las"
            path.write_bytes(b"NOPE" + b"\0" * 300)
            with self.assertRaises(SystemExit):
                pointcloud.inspect_las(str(path))

    def test_inspect_cli_writes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cloud.las"
            build_las(path)
            out_json = Path(tmp) / "header.json"
            out_md = Path(tmp) / "header.md"
            exit_code = pointcloud.main(
                [
                    "inspect",
                    str(path),
                    "--output",
                    str(out_json),
                    "--markdown",
                    str(out_md),
                ]
            )
            self.assertEqual(exit_code, 0)
            report = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(report["point_count"], 5)
            self.assertIn("# LAS Header Inspection", out_md.read_text(encoding="utf-8"))


@unittest.skipUnless(HAVE_NUMPY, "numpy is not installed")
class FilterTests(unittest.TestCase):
    def test_load_points(self):
        meta = pointcloud.load_points(str(SURVEY))
        self.assertEqual(meta["points"].shape, (7, 3))
        self.assertTrue(meta["has_header"])
        self.assertEqual(meta["delimiter"], "whitespace")
        self.assertEqual(meta["columns"], [1, 2, 3])
        self.assertEqual(meta["skipped"], [])

    def test_filter_voxel_and_ground(self):
        meta = pointcloud.load_points(str(SURVEY))
        result = pointcloud.filter_points(
            meta["points"],
            voxel_size=1.0,
            z_min=95.0,
            z_max=106.0,
            ground_cell_size=2.0,
        )

        self.assertEqual(result["input"]["count"], 7)
        self.assertEqual(result["z_filter"]["count_removed"], 2)
        self.assertEqual(result["z_filter"]["count_kept"], 5)
        self.assertEqual(result["z_filter"]["z_range"], {"min": 99.0, "max": 105.0})
        self.assertEqual(result["voxel_downsample"]["count_removed"], 1)
        self.assertEqual(result["voxel_downsample"]["count_kept"], 4)
        self.assertEqual(
            sorted(result["filtered_points"][:, 2].tolist()),
            [99.0, 100.0, 103.0, 105.0],
        )
        self.assertEqual(result["filtered_source_indices"].tolist(), [0, 2, 5, 6])

        ground = result["ground_candidates"]
        self.assertEqual(ground["count"], 3)
        self.assertEqual(ground["method"], "lowest_z_per_xy_cell")
        self.assertFalse(ground["is_classification"])
        self.assertEqual(ground["z_range"], {"min": 99.0, "max": 103.0})
        rows = result["ground_rows"]
        self.assertEqual(len(rows), 3)
        self.assertEqual((rows[0]["cell_x"], rows[0]["cell_y"]), (0, 0))
        self.assertEqual(rows[0]["z"], 100.0)
        self.assertEqual((rows[1]["cell_x"], rows[1]["cell_y"]), (1, 0))
        self.assertEqual((rows[2]["cell_x"], rows[2]["cell_y"]), (2, 2))
        self.assertEqual(rows[2]["z"], 103.0)
        self.assertEqual(rows[2]["source_index"], 6)

    def test_filter_validates_parameters(self):
        meta = pointcloud.load_points(str(SURVEY))
        with self.assertRaises(SystemExit):
            pointcloud.filter_points(meta["points"], z_min=110.0, z_max=100.0)
        with self.assertRaises(SystemExit):
            pointcloud.filter_points(meta["points"], voxel_size=0.0)
        with self.assertRaises(SystemExit):
            pointcloud.filter_points(meta["points"], ground_cell_size=-1.0)

    def test_filter_cli_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            exit_code = pointcloud.main(
                [
                    "filter",
                    str(SURVEY),
                    "--out-dir",
                    tmp,
                    "--voxel-size",
                    "1",
                    "--z-min",
                    "95",
                    "--z-max",
                    "106",
                    "--ground-cell-size",
                    "2",
                ]
            )
            self.assertEqual(exit_code, 0)
            out = Path(tmp)
            for name in (
                "filtered_points.csv",
                "ground_candidates.csv",
                "pointcloud_filter_report.json",
                "pointcloud_filter_report.md",
            ):
                self.assertTrue((out / name).exists(), name)

            with (out / "filtered_points.csv").open(
                encoding="utf-8-sig", newline=""
            ) as fh:
                filtered = list(csv.DictReader(fh))
            self.assertEqual(len(filtered), 4)
            self.assertEqual(float(filtered[0]["z"]), 100.0)
            self.assertEqual(int(filtered[0]["index"]), 1)

            with (out / "ground_candidates.csv").open(
                encoding="utf-8-sig", newline=""
            ) as fh:
                ground = list(csv.DictReader(fh))
            self.assertEqual(len(ground), 3)
            self.assertEqual(int(ground[-1]["index"]), 7)
            self.assertEqual(float(ground[-1]["z"]), 103.0)
            self.assertEqual(int(ground[-1]["cell_x"]), 2)

            report = json.loads(
                (out / "pointcloud_filter_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["stages"]["z_filter"]["count_kept"], 5)
            self.assertEqual(
                report["stages"]["voxel_downsample"]["count_kept"], 4
            )
            self.assertEqual(report["stages"]["ground_candidates"]["count"], 3)
            self.assertEqual(report["units"], "UNKNOWN")
            self.assertTrue(report["limitations"])
            markdown = (out / "pointcloud_filter_report.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("# Point Cloud Filter Report", markdown)
            self.assertIn("NOT a ground classification", markdown)


if __name__ == "__main__":
    unittest.main()
