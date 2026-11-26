#!/usr/bin/env python3
"""Tests for the mine-cad-parser scripts."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import parse_dxf  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class ParserTests(unittest.TestCase):
    def setUp(self):
        try:
            import ezdxf  # noqa: F401
        except ImportError:
            self.skipTest("ezdxf is not installed")
        self.result = parse_dxf.parse_dxf(str(FIXTURES / "cad_sample.dxf"))
        self.report = self.result["report"]
        self.features = self.result["features"]

    def top_level_feature(self, entity_type):
        for feature in self.features:
            props = feature["properties"]
            if props["entity_type"] == entity_type and not props["block_name"]:
                return feature
        return None

    def test_feature_and_skip_counts(self):
        self.assertEqual(self.report["feature_count"], 12)
        self.assertEqual(self.report["skipped_count"], 1)
        self.assertEqual(self.report["unsupported_types"], {"HATCH": 1})

        stats = self.report["feature_entity_statistics"]
        self.assertEqual(stats["POINT"], 1)
        self.assertEqual(stats["LINE"], 2)
        self.assertEqual(stats["LWPOLYLINE"], 1)
        self.assertEqual(stats["POLYLINE"], 1)
        self.assertEqual(stats["SPLINE"], 1)
        self.assertEqual(stats["ARC"], 1)
        self.assertEqual(stats["CIRCLE"], 2)
        self.assertEqual(stats["ELLIPSE"], 1)
        self.assertEqual(stats["TEXT"], 1)
        self.assertEqual(stats["MTEXT"], 1)

        source = self.report["source_entity_statistics"]
        self.assertEqual(source["INSERT"], 1)
        self.assertEqual(source["HATCH"], 1)

    def test_closed_lwpolyline_is_polygon_with_elevation(self):
        feature = self.top_level_feature("LWPOLYLINE")
        self.assertEqual(feature["geometry"]["type"], "Polygon")
        self.assertTrue(feature["properties"]["closed"])
        ring = feature["geometry"]["coordinates"][0]
        self.assertEqual(ring[0][2], 121.0)
        self.assertEqual(ring[0], ring[-1])

    def test_block_expansion(self):
        block_features = [
            feature
            for feature in self.features
            if feature["properties"]["block_name"] == "CONTROL_POINT"
        ]
        self.assertEqual(len(block_features), 2)
        xs = []
        for feature in block_features:
            geometry = feature["geometry"]
            points = (
                geometry["coordinates"][0]
                if geometry["type"] == "Polygon"
                else geometry["coordinates"]
            )
            xs.extend(point[0] for point in points)
        self.assertTrue(all(x > 500015 for x in xs))

    def test_text_values(self):
        text = self.top_level_feature("TEXT")
        self.assertEqual(text["properties"]["text"], "MINE-01")
        mtext = self.top_level_feature("MTEXT")
        self.assertEqual(mtext["properties"]["text"], "PIT RIM")

    def test_three_dimensional_line(self):
        line = self.top_level_feature("LINE")
        coordinates = line["geometry"]["coordinates"]
        self.assertEqual(coordinates[0][2], 120.0)
        self.assertEqual(coordinates[1][2], 123.0)

    def test_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = parse_dxf.write_outputs(self.result, tmp)
            for path in paths.values():
                self.assertTrue(Path(path).exists(), path)

            geojson = json.loads(Path(paths["geojson"]).read_text(encoding="utf-8"))
            self.assertEqual(len(geojson["features"]), 12)
            self.assertEqual(geojson["mine_metadata"]["coordinate_system"], "UNKNOWN")

            with open(paths["csv"], encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 12)
            self.assertIn("feature_id", rows[0])
            self.assertIn("geometry_type", rows[0])

            layers = json.loads(Path(paths["layers"]).read_text(encoding="utf-8"))
            layer_names = {layer["name"] for layer in layers["layers"]}
            self.assertTrue({"SURVEY", "ROADS", "TEXT", "BLOCKS"}.issubset(layer_names))

    def test_no_text_option(self):
        result = parse_dxf.parse_dxf(
            str(FIXTURES / "cad_sample.dxf"), include_text=False
        )
        self.assertEqual(result["report"]["feature_count"], 10)
        self.assertEqual(result["report"]["skipped_count"], 3)
        types = {feature["properties"]["entity_type"] for feature in result["features"]}
        self.assertNotIn("TEXT", types)
        self.assertNotIn("MTEXT", types)


if __name__ == "__main__":
    unittest.main()
