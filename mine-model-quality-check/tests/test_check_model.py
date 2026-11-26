#!/usr/bin/env python3
"""Tests for the mine-model-quality-check scripts."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CUBE = FIXTURES / "cube.obj"
BROKEN = FIXTURES / "cube_broken.obj"
NONMANIFOLD = FIXTURES / "nonmanifold.obj"

try:
    import numpy as np
except ImportError:
    np = None

HAVE_NUMPY = np is not None
if HAVE_NUMPY:
    sys.path.insert(0, str(SKILL_DIR / "scripts"))
    import check_model  # noqa: E402


def write_registration(path: Path, rmse: float = 0.02, max_residual: float = 0.04) -> None:
    payload = {
        "parameters": {
            "rmse": rmse,
            "max_residual": max_residual,
            "source_crs": "LOCAL_MINE_GRID",
            "target_crs": "LOCAL_MINE_GRID",
        },
        "diagnostics": {"rmse": rmse, "max_residual": max_residual},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


@unittest.skipUnless(HAVE_NUMPY, "numpy is not installed")
class ObjParsingTests(unittest.TestCase):
    def test_fan_triangulation_of_quads(self):
        parsed = check_model.parse_obj(str(CUBE))
        self.assertEqual(parsed["vertices"].shape, (8, 3))
        self.assertEqual(parsed["faces"].shape, (12, 3))
        self.assertEqual(parsed["polygon_count"], 6)
        self.assertEqual(parsed["polygon_vertex_counts"], {4: 6})
        self.assertEqual(parsed["invalid_faces"], [])
        self.assertEqual(parsed["warnings"], [])

    def test_negative_indices(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quad.obj"
            path.write_text(
                "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf -4 -3 -2 -1\n",
                encoding="utf-8",
            )
            parsed = check_model.parse_obj(str(path))
        self.assertEqual(parsed["vertices"].shape, (4, 3))
        self.assertEqual(parsed["faces"].shape, (2, 3))
        self.assertEqual(parsed["faces"].tolist(), [[0, 1, 2], [0, 2, 3]])

    def test_invalid_face_index_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.obj"
            path.write_text(
                "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 9\n",
                encoding="utf-8",
            )
            parsed = check_model.parse_obj(str(path))
        self.assertEqual(parsed["faces"].shape, (0, 3))
        self.assertEqual(len(parsed["invalid_faces"]), 1)
        self.assertIn("out of range", parsed["invalid_faces"][0]["reason"])


@unittest.skipUnless(HAVE_NUMPY, "numpy is not installed")
class QualityCheckTests(unittest.TestCase):
    def test_good_cube_passes(self):
        report = check_model.run_checks(str(CUBE))
        metrics = report["metrics"]

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(metrics["vertex_count"], 8)
        self.assertEqual(metrics["triangle_count"], 12)
        self.assertEqual(metrics["source_polygon_count"], 6)
        self.assertEqual(metrics["edge_count"], 18)
        self.assertEqual(metrics["boundary_edge_count"], 0)
        self.assertEqual(metrics["non_manifold_edge_count"], 0)
        self.assertEqual(metrics["duplicate_vertex_count"], 0)
        self.assertEqual(metrics["degenerate_triangle_count"], 0)
        self.assertTrue(metrics["closed"])
        self.assertEqual(metrics["orientation"], "OUTWARD")
        self.assertAlmostEqual(metrics["signed_volume"], 8.0, places=9)
        self.assertEqual(metrics["z_range"], {"min": -1.0, "max": 1.0, "span": 2.0})
        self.assertTrue(all(check["status"] == "PASS" for check in report["checks"]))
        self.assertEqual(report["warnings"], [])

    def test_broken_cube_fails(self):
        report = check_model.run_checks(str(BROKEN))
        metrics = report["metrics"]
        statuses = {check["id"]: check["status"] for check in report["checks"]}

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(metrics["vertex_count"], 9)
        self.assertEqual(metrics["triangle_count"], 11)
        self.assertEqual(metrics["duplicate_vertex_count"], 1)
        self.assertEqual(metrics["duplicate_vertex_group_count"], 1)
        self.assertEqual(metrics["degenerate_triangle_count"], 1)
        self.assertEqual(metrics["boundary_loop_count"], 1)
        self.assertEqual(metrics["hole_count"], 1)
        self.assertEqual(metrics["open_boundary_chain_count"], 1)
        self.assertEqual(metrics["non_manifold_edge_count"], 1)
        self.assertFalse(metrics["closed"])
        self.assertEqual(statuses["duplicate_vertices"], "FAIL")
        self.assertEqual(statuses["degenerate_triangles"], "FAIL")
        self.assertEqual(statuses["non_manifold_edges"], "FAIL")
        self.assertEqual(statuses["boundary"], "FAIL")
        self.assertEqual(statuses["orientation"], "UNKNOWN")
        self.assertEqual(report["duplicate_vertex_groups"][0]["vertex_indices"], [1, 9])
        self.assertEqual(report["degenerate_triangles"][0]["vertices"], [1, 2, 9])

    def test_non_manifold_edge_detected(self):
        report = check_model.run_checks(str(NONMANIFOLD))
        statuses = {check["id"]: check["status"] for check in report["checks"]}
        self.assertEqual(report["metrics"]["non_manifold_edge_count"], 1)
        self.assertEqual(statuses["non_manifold_edges"], "FAIL")
        edge = report["non_manifold_edges"][0]
        self.assertEqual(edge["vertices"], [1, 2])
        self.assertEqual(edge["face_count"], 3)

    def test_inverted_cube_fails_orientation(self):
        text = CUBE.read_text(encoding="utf-8")
        inverted_lines = []
        for line in text.splitlines():
            if line.startswith("f "):
                tokens = line.split()
                inverted_lines.append("f " + " ".join(reversed(tokens[1:])))
            else:
                inverted_lines.append(line)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inverted.obj"
            path.write_text("\n".join(inverted_lines) + "\n", encoding="utf-8")
            report = check_model.run_checks(str(path))

        statuses = {check["id"]: check["status"] for check in report["checks"]}
        self.assertEqual(report["metrics"]["orientation"], "INWARD")
        self.assertAlmostEqual(report["metrics"]["signed_volume"], -8.0, places=9)
        self.assertTrue(report["metrics"]["closed"])
        self.assertEqual(statuses["orientation"], "FAIL")
        self.assertEqual(report["status"], "FAIL")

    def test_registration_threshold_pass_and_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            registration = Path(tmp) / "registration_report.json"
            write_registration(registration, rmse=0.02, max_residual=0.04)

            passing = check_model.run_checks(
                str(CUBE),
                registration_path=str(registration),
                max_rmse=0.05,
            )
            failing = check_model.run_checks(
                str(CUBE),
                registration_path=str(registration),
                max_rmse=0.01,
            )

        self.assertEqual(passing["status"], "PASS")
        self.assertEqual(passing["registration"]["status"], "PASS")
        self.assertAlmostEqual(passing["registration"]["rmse"], 0.02)
        self.assertAlmostEqual(passing["registration"]["max_residual"], 0.04)
        self.assertEqual(passing["registration"]["source_crs"], "LOCAL_MINE_GRID")
        self.assertEqual(failing["status"], "FAIL")
        self.assertEqual(failing["registration"]["status"], "FAIL")
        statuses = {check["id"]: check["status"] for check in failing["checks"]}
        self.assertEqual(statuses["registration_rmse"], "FAIL")

    def test_registration_requires_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            registration = Path(tmp) / "registration_report.json"
            write_registration(registration)
            with self.assertRaises(SystemExit):
                check_model.run_checks(
                    str(CUBE), registration_path=str(registration)
                )

    def test_registration_without_rmse_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            registration = Path(tmp) / "registration_report.json"
            registration.write_text('{"parameters": {}}', encoding="utf-8")
            report = check_model.run_checks(
                str(CUBE),
                registration_path=str(registration),
                max_rmse=0.05,
            )
        statuses = {check["id"]: check["status"] for check in report["checks"]}
        self.assertEqual(statuses["registration_rmse"], "UNKNOWN")
        self.assertEqual(report["status"], "UNKNOWN")


@unittest.skipUnless(HAVE_NUMPY, "numpy is not installed")
class OutputTests(unittest.TestCase):
    def test_fail_exit_code_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            exit_code = check_model.main(
                [str(BROKEN), "--out-dir", tmp]
            )
            self.assertEqual(exit_code, 1)
            out = Path(tmp)
            for name in ("quality_report.json", "quality_report.md", "issues.csv"):
                self.assertTrue((out / name).exists(), name)

            report = json.loads(
                (out / "quality_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["units"], "UNKNOWN")
            self.assertEqual(report["crs"], "UNKNOWN")
            self.assertTrue(report["limitations"])
            self.assertIn("check_model.py", report["reproduction_command"])

            markdown = (out / "quality_report.md").read_text(encoding="utf-8")
            self.assertIn("# Model Quality Report", markdown)
            self.assertIn("**FAIL**", markdown)

            with (out / "issues.csv").open(
                encoding="utf-8-sig", newline=""
            ) as fh:
                issues = list(csv.DictReader(fh))
            codes = {row["code"] for row in issues}
            self.assertIn("CHECK", codes)
            self.assertIn("DUPLICATE_VERTEX_GROUP", codes)
            self.assertIn("DEGENERATE_TRIANGLE", codes)
            self.assertIn("BOUNDARY_LOOP", codes)
            self.assertTrue(any(row["status"] == "WARNING" for row in issues))

    def test_no_fail_flag_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            exit_code = check_model.main(
                [str(BROKEN), "--out-dir", tmp, "--no-fail"]
            )
        self.assertEqual(exit_code, 0)

    def test_good_cube_cli_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            exit_code = check_model.main([str(CUBE), "--out-dir", tmp])
            report = json.loads(
                (Path(tmp) / "quality_report.json").read_text(encoding="utf-8")
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
