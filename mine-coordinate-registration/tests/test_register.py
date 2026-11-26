#!/usr/bin/env python3
"""Tests for the mine-coordinate-registration scripts."""

from __future__ import annotations

import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

try:
    import numpy as np
except ImportError:
    np = None

HAVE_NUMPY = np is not None
if HAVE_NUMPY:
    sys.path.insert(0, str(SKILL_DIR / "scripts"))
    import register  # noqa: E402


def rotation_zyx(rx_deg: float, ry_deg: float, rz_deg: float):
    rx, ry, rz = map(math.radians, (rx_deg, ry_deg, rz_deg))
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    rx_m = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry_m = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz_m = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz_m @ ry_m @ rx_m


TRUE_SCALE = 1.02
TRUE_TRANSLATION = np.array([1200.5, -800.25, 35.75]) if HAVE_NUMPY else None
TRUE_ROTATION = rotation_zyx(5, 10, 30) if HAVE_NUMPY else None


@unittest.skipUnless(HAVE_NUMPY, "numpy is not installed")
class RegistrationTests(unittest.TestCase):
    def load_control(self, name: str):
        return register.load_control_points(str(FIXTURES / name))

    def test_control_point_parsing(self):
        control = self.load_control("control_points_3d.csv")
        self.assertEqual(control["src_cols"], [1, 2, 3])
        self.assertEqual(control["dst_cols"], [4, 5, 6])
        self.assertEqual(len(control["points"]), 8)
        self.assertEqual(control["points"].shape, (8, 6))

        points = register.load_points(str(FIXTURES / "points_to_transform.xyz"))
        self.assertEqual(len(points["points"]), 3)
        self.assertEqual(points["points"].shape, (3, 3))

    def test_3d_similarity_recovers_transform(self):
        data = self.load_control("control_points_3d.csv")["points"]
        result = register.register_control_points(
            data[:, 0:3], data[:, 3:6], mode="3d"
        )
        params = result["parameters"]

        self.assertAlmostEqual(params["scale"], TRUE_SCALE, places=6)
        np.testing.assert_allclose(
            np.array(params["rotation_matrix"]), TRUE_ROTATION, atol=1e-6
        )
        np.testing.assert_allclose(
            np.array(params["translation"]), TRUE_TRANSLATION, atol=1e-3
        )
        self.assertLess(result["diagnostics"]["rmse"], 1e-6)
        self.assertEqual(params["used_control_points"], 8)
        self.assertEqual(params["control_point_count"], 8)

        angles = params["euler_angles_deg_zyx"]
        self.assertAlmostEqual(angles["rx"], 5.0, places=4)
        self.assertAlmostEqual(angles["ry"], 10.0, places=4)
        self.assertAlmostEqual(angles["rz"], 30.0, places=4)

    def test_outlier_rejection(self):
        data = self.load_control("control_points_outlier.csv")["points"]
        result = register.register_control_points(
            data[:, 0:3], data[:, 3:6], mode="3d", reject_above=0.5
        )
        diagnostics = result["diagnostics"]

        self.assertEqual(diagnostics["used_control_points"], 7)
        self.assertEqual(len(diagnostics["rejected_control_points"]), 1)
        rejected = diagnostics["rejected_control_points"][0]
        self.assertEqual(rejected["index"], 6)
        self.assertGreater(rejected["residual"], 0.5)
        self.assertLess(diagnostics["rmse"], 1e-6)

        point = diagnostics["points"][5]
        self.assertTrue(point["rejected"])
        self.assertFalse(point["used"])
        self.assertGreater(point["rejection_residual"], 0.5)

    def test_2d_similarity(self):
        data = self.load_control("control_points_2d.csv")["points"]
        result = register.register_control_points(
            data[:, 0:3], data[:, 3:6], mode="2d"
        )
        params = result["parameters"]

        self.assertAlmostEqual(params["scale"], 1.01, places=6)
        self.assertAlmostEqual(params["rotation_deg_2d"], 30.0, places=5)
        self.assertAlmostEqual(params["translation"][0], 1200.0, places=3)
        self.assertAlmostEqual(params["translation"][1], -800.0, places=3)
        self.assertAlmostEqual(params["translation"][2], 35.5, places=3)
        self.assertLess(result["diagnostics"]["rmse"], 1e-6)

    def test_apply_transform(self):
        data = self.load_control("control_points_3d.csv")["points"]
        result = register.register_control_points(
            data[:, 0:3], data[:, 3:6], mode="3d"
        )
        points = register.load_points(str(FIXTURES / "points_to_transform.xyz"))["points"]
        transformed = register.apply_transform(points, result["internal"], "3d")
        expected = TRUE_SCALE * (points @ TRUE_ROTATION.T) + TRUE_TRANSLATION
        np.testing.assert_allclose(transformed, expected, atol=1e-6)

    def test_insufficient_and_collinear_points(self):
        src = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        dst = src + 1.0
        with self.assertRaises(SystemExit):
            register.register_control_points(src, dst, mode="3d")

        collinear = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [20.0, 0.0, 0.0]])
        collinear_dst = collinear + np.array([1.0, 2.0, 3.0])
        with self.assertRaises(SystemExit):
            register.register_control_points(collinear, collinear_dst, mode="3d")

    def test_outputs(self):
        control_path = FIXTURES / "control_points_3d.csv"
        points_path = FIXTURES / "points_to_transform.xyz"
        control = register.load_control_points(str(control_path))
        data = control["points"]
        result = register.register_control_points(
            data[:, 0:3], data[:, 3:6], mode="3d"
        )
        points = register.load_points(str(points_path))
        transformed = register.apply_transform(points["points"], result["internal"], "3d")
        options = {
            "mode": "3d",
            "reject_above": None,
            "source_crs": "UNKNOWN",
            "target_crs": "UNKNOWN",
            "control_columns": {
                "source": control["src_cols"],
                "target": control["dst_cols"],
            },
            "control_input": {
                "delimiter": control["delimiter"],
                "encoding": control["encoding"],
                "has_header": control["has_header"],
            },
            "skipped_control_rows": control["skipped"],
            "skipped_point_rows": points["skipped"],
        }

        with tempfile.TemporaryDirectory() as tmp:
            paths = register.write_outputs(
                result,
                tmp,
                str(control_path),
                str(points_path),
                transformed,
                points,
                "UNKNOWN",
                "UNKNOWN",
                options,
            )
            for key in (
                "transformation",
                "report_json",
                "report_md",
                "residuals_csv",
                "transformed_points",
            ):
                self.assertTrue(Path(paths[key]).exists(), key)

            report = json.loads(Path(paths["report_json"]).read_text(encoding="utf-8"))
            self.assertEqual(report["diagnostics"]["used_control_points"], 8)
            self.assertEqual(report["parameters"]["source_crs"], "UNKNOWN")

            with open(paths["residuals_csv"], encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 8)

            with open(
                paths["transformed_points"], encoding="utf-8-sig", newline=""
            ) as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 3)
            self.assertIn("delta_x", rows[0])
            self.assertIn("x", rows[0])

            markdown = Path(paths["report_md"]).read_text(encoding="utf-8")
            self.assertIn("Coordinate Registration Report", markdown)


if __name__ == "__main__":
    unittest.main()
