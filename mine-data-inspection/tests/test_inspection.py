#!/usr/bin/env python3
"""Tests for the mine-data-inspection scripts."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import inspect_dxf  # noqa: E402
import inspect_file  # noqa: E402
import inspect_xyz  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class XYZInspectionTests(unittest.TestCase):
    def test_survey_fixture(self):
        report = inspect_xyz.inspect_xyz(str(FIXTURES / "survey.xyz"))

        self.assertEqual(report["format"], "XYZ")
        self.assertEqual(report["point_count"], 7)
        self.assertEqual(report["skipped_rows"], 1)
        self.assertEqual(report["duplicate_coordinates"], 1)
        self.assertAlmostEqual(report["extent"]["min_x"], 500000.0)
        self.assertAlmostEqual(report["extent"]["max_x"], 500050.0)
        self.assertAlmostEqual(report["extent"]["span_y"], 20.0)
        self.assertAlmostEqual(report["z_range"]["span"], 2.5)
        self.assertEqual(report["coordinate_clue"], "PROJECTED_METER_CANDIDATE")
        self.assertEqual(report["units"], "UNKNOWN")
        self.assertTrue(report["source"]["sha256"])
        self.assertEqual(len(report["warnings"]), 2)

    def test_markdown_renderer(self):
        report = inspect_xyz.inspect_xyz(str(FIXTURES / "survey.xyz"))
        markdown = inspect_xyz.render_markdown(report)
        self.assertIn("# Data Inspection Report", markdown)
        self.assertIn("survey.xyz", markdown)


class DXFInspectionTests(unittest.TestCase):
    def setUp(self):
        try:
            import ezdxf  # noqa: F401
        except ImportError:
            self.skipTest("ezdxf is not installed")

    def test_sample_fixture(self):
        report = inspect_dxf.inspect_dxf(str(FIXTURES / "sample.dxf"))

        self.assertEqual(report["format"], "DXF")
        self.assertEqual(report["format_version"], "AC1024")
        self.assertEqual(report["units"], "Meters")
        self.assertTrue(report["has_3d_entities"])
        self.assertIsNotNone(report["extent"])

        stats = report["entity_statistics"]
        for entity_type in ("LINE", "POINT", "LWPOLYLINE", "TEXT", "INSERT"):
            self.assertGreaterEqual(stats.get(entity_type, 0), 1, entity_type)

        layer_names = {layer["name"] for layer in report["layers"]}
        self.assertTrue({"SURVEY", "ROADS", "TEXT"}.issubset(layer_names))
        self.assertEqual(report["blocks"]["defined"], 1)
        self.assertEqual(report["blocks"]["inserts"], 1)

    def test_markdown_renderer(self):
        report = inspect_dxf.inspect_dxf(str(FIXTURES / "sample.dxf"))
        markdown = inspect_dxf.render_markdown(report)
        self.assertIn("# Data Inspection Report", markdown)
        self.assertIn("Entity statistics", markdown)


class DispatcherTests(unittest.TestCase):
    def test_dwg_is_unsupported(self):
        with tempfile.NamedTemporaryFile(suffix=".dwg") as fh:
            fh.write(b"dummy")
            fh.flush()
            report = inspect_file.dispatch(fh.name)
        self.assertEqual(report["status"], "UNSUPPORTED")
        self.assertIn("DWG", report["format"])

    def test_point_cloud_is_unsupported(self):
        with tempfile.NamedTemporaryFile(suffix=".las") as fh:
            fh.write(b"dummy")
            fh.flush()
            report = inspect_file.dispatch(fh.name)
        self.assertEqual(report["status"], "UNSUPPORTED")
        self.assertIn("Point cloud", report["warnings"][0])


if __name__ == "__main__":
    unittest.main()
