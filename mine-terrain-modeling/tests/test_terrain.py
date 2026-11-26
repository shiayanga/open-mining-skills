#!/usr/bin/env python3
"""Tests for the mine-terrain-modeling scripts."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

try:
    import numpy as np
    import scipy  # noqa: F401
except ImportError:
    np = None

HAVE_SCIPY = np is not None
if HAVE_SCIPY:
    sys.path.insert(0, str(SKILL_DIR / "scripts"))
    import terrain  # noqa: E402

SURVEY = FIXTURES / "survey_hill.csv"
CHECKS = FIXTURES / "check_points.xyz"


@unittest.skipUnless(HAVE_SCIPY, "numpy/scipy are not installed")
class TerrainTests(unittest.TestCase):
    def load_tin(self):
        meta = terrain.load_points(str(SURVEY))
        cleaned, cleaning = terrain.clean_points(meta["points"])
        return meta, cleaning, cleaned, terrain.build_tin(cleaned)

    def test_load_points(self):
        meta = terrain.load_points(str(SURVEY))
        self.assertEqual(meta["points"].shape, (20, 3))
        self.assertEqual(meta["delimiter"], ",")
        self.assertTrue(meta["has_header"])
        self.assertEqual(meta["columns"], [1, 2, 3])
        self.assertEqual(meta["skipped"], [])

    def test_tin_counts_area_and_slope(self):
        _, cleaning, cleaned, tin = self.load_tin()
        self.assertEqual(cleaning["output_point_count"], 20)
        stats = tin["stats"]

        self.assertEqual(stats["vertex_count"], 20)
        self.assertEqual(stats["triangle_count"], 24)
        self.assertAlmostEqual(stats["total_area_xy"], 1200.0, places=6)
        self.assertGreater(stats["total_area_3d"], stats["total_area_xy"])
        self.assertEqual(tin["degenerate_triangles_dropped"], 0)
        self.assertGreaterEqual(stats["slope_deg_min"], 0.0)
        self.assertLessEqual(stats["slope_deg_max"], 90.0)
        self.assertLessEqual(stats["slope_deg_min"], stats["slope_deg_mean"])
        self.assertLessEqual(stats["slope_deg_mean"], stats["slope_deg_max"])
        self.assertAlmostEqual(stats["z_min"], 100.996116, places=6)
        self.assertAlmostEqual(stats["z_max"], 114.773925, places=6)

    def test_dem_shape_and_values(self):
        _, _, cleaned, _ = self.load_tin()
        dem = terrain.build_dem(cleaned, 10.0, "linear")
        stats = dem["stats"]

        self.assertEqual(stats["shape"], [4, 5])
        self.assertEqual(stats["node_count"], 20)
        self.assertEqual(stats["valid_cells"], 20)
        self.assertEqual(stats["coverage_fraction"], 1.0)
        self.assertEqual(dem["x"].shape, (5,))
        self.assertEqual(dem["y"].shape, (4,))
        self.assertAlmostEqual(float(dem["x"][-1]), 40.0)
        self.assertAlmostEqual(float(dem["y"][-1]), 30.0)
        # DEM node (row 1, col 1) is the survey point at X=10, Y=10.
        self.assertAlmostEqual(float(dem["values"][1, 1]), 108.773925, places=6)

        nearest = terrain.build_dem(cleaned, 10.0, "nearest")
        self.assertEqual(nearest["stats"]["valid_cells"], 20)

    def test_check_point_accuracy(self):
        _, _, cleaned, _ = self.load_tin()
        check_meta = terrain.load_points(str(CHECKS))
        result = terrain.evaluate_check_points(cleaned, check_meta["points"])

        self.assertEqual(result["check_point_count"], 12)
        self.assertEqual(result["checked_count"], 12)
        self.assertEqual(result["outside_hull_count"], 0)
        self.assertIsNotNone(result["rmse"])
        self.assertLess(result["rmse"], 1.0)
        self.assertLess(result["max_abs_error"], 1.5)
        self.assertEqual(len(result["points"]), 12)
        self.assertEqual(result["warnings"], [])

    def test_obj_export_preserves_coordinates(self):
        meta = terrain.load_points(str(SURVEY))
        _, _, cleaned, tin = self.load_tin()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "terrain.obj"
            terrain.write_obj(path, tin["vertices"], tin["faces"])
            lines = path.read_text(encoding="utf-8").splitlines()

        vertices = []
        faces = []
        for line in lines:
            if line.startswith("v "):
                vertices.append([float(value) for value in line.split()[1:4]])
            elif line.startswith("f "):
                faces.append([int(value) for value in line.split()[1:4]])

        self.assertEqual(len(vertices), 20)
        self.assertEqual(len(faces), 24)
        for face in faces:
            self.assertEqual(len(face), 3)
            self.assertTrue(all(1 <= index <= 20 for index in face), face)
        exported_z = sorted(vertex[2] for vertex in vertices)
        source_z = sorted(float(value) for value in meta["points"][:, 2])
        self.assertEqual(exported_z, source_z)

    def test_esri_ascii_export(self):
        _, _, cleaned, _ = self.load_tin()
        dem = terrain.build_dem(cleaned, 10.0, "linear")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "terrain_dem.asc"
            terrain.write_esri_ascii(path, dem)
            lines = path.read_text(encoding="utf-8").splitlines()

        self.assertIn("ncols 5", lines)
        self.assertIn("nrows 4", lines)
        self.assertIn("cellsize 10", lines)
        self.assertIn("xllcorner -5", lines)
        self.assertIn("yllcorner -5", lines)
        self.assertTrue(any(line.startswith("NODATA_value") for line in lines))
        data_rows = [line for line in lines if line and line[0] in "-0123456789"]
        self.assertEqual(len(data_rows), 4)
        self.assertTrue(all(len(line.split()) == 5 for line in data_rows))

    def test_fewer_than_three_points_raises(self):
        points = np.array([[0.0, 0.0, 100.0], [10.0, 10.0, 101.0]])
        with self.assertRaises(SystemExit):
            terrain.build_tin(points)

    def test_collinear_points_raise(self):
        points = np.array(
            [[0.0, 0.0, 0.0], [10.0, 0.0, 1.0], [20.0, 0.0, 2.0]]
        )
        with self.assertRaises(SystemExit):
            terrain.build_tin(points)

    def test_clean_points_reports_duplicates(self):
        points = np.array(
            [
                [0.0, 0.0, 100.0],
                [0.0, 0.0, 100.0],
                [0.0, 0.0, 101.0],
                [10.0, 0.0, 102.0],
            ]
        )
        cleaned, cleaning = terrain.clean_points(points)
        self.assertEqual(cleaned.shape, (2, 3))
        self.assertEqual(cleaning["exact_duplicates_removed"], 1)
        self.assertEqual(cleaning["xy_conflicts_removed"], 1)
        self.assertEqual(len(cleaning["xy_conflict_examples"]), 1)
        self.assertEqual(cleaning["xy_conflict_examples"][0]["kept_z"], 100.0)

    def test_full_cli_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            exit_code = terrain.main(
                [
                    str(SURVEY),
                    "--out-dir",
                    tmp,
                    "--cell-size",
                    "10",
                    "--check-points",
                    str(CHECKS),
                ]
            )
            self.assertEqual(exit_code, 0)
            out = Path(tmp)
            for name in (
                "terrain.obj",
                "terrain_dem.asc",
                "terrain_report.json",
                "terrain_report.md",
            ):
                self.assertTrue((out / name).exists(), name)

            report = json.loads((out / "terrain_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["tin"]["triangle_count"], 24)
            self.assertEqual(report["dem"]["shape"], [4, 5])
            self.assertEqual(report["check_points"]["checked_count"], 12)
            self.assertEqual(report["units"], "UNKNOWN")
            self.assertEqual(report["crs"], "UNKNOWN")
            self.assertTrue(report["limitations"])
            markdown = (out / "terrain_report.md").read_text(encoding="utf-8")
            self.assertIn("# Terrain Modeling Report", markdown)
            self.assertIn("breaklines", markdown)


if __name__ == "__main__":
    unittest.main()
