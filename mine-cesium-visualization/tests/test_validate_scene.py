#!/usr/bin/env python3
"""Tests for the mine-cesium-visualization scene validator."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import validate_scene  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class SceneValidationTests(unittest.TestCase):
    def setUp(self):
        self.viewer = load_fixture("viewer_config.json")
        self.manifest = load_fixture("scene_manifest.json")

    def codes(self, entries: list[dict]) -> set[str]:
        return {entry["code"] for entry in entries}

    def test_valid_scene_passes(self):
        report = validate_scene.validate_scene(self.viewer, self.manifest)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["summary"]["layers"], 5)
        self.assertEqual(report["summary"]["tilesets"], 1)
        self.assertEqual(report["summary"]["models"], 1)
        self.assertEqual(report["summary"]["cameraBookmarks"], 2)
        self.assertEqual(report["viewer"]["terrainProviderType"], "CesiumTerrainProvider")
        self.assertEqual(report["scene"]["coordinateSystemId"], "MINE-LOCAL-001")

    def test_duplicate_layer_ids_fail(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["layers"][2]["id"] = "pit"

        report = validate_scene.validate_scene(self.viewer, manifest)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("DUPLICATE_LAYER_ID", self.codes(report["errors"]))

    def test_missing_tileset_uri_fails(self):
        manifest = copy.deepcopy(self.manifest)
        del manifest["tilesets"][0]["uri"]

        report = validate_scene.validate_scene(self.viewer, manifest)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("MISSING_TILESET_URI", self.codes(report["errors"]))

    def test_commercial_provider_fails(self):
        viewer = copy.deepcopy(self.viewer)
        viewer["imageryProvider"]["url"] = (
            "https://api.mapbox.com/styles/v1/mine/tiles/{z}/{x}/{y}.png"
        )

        report = validate_scene.validate_scene(viewer, self.manifest)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("COMMERCIAL_PROVIDER", self.codes(report["errors"]))

    def test_world_terrain_type_fails(self):
        viewer = copy.deepcopy(self.viewer)
        viewer["terrainProvider"] = {
            "type": "CesiumWorldTerrain",
            "url": "https://assets.cesium.com/terrain",
        }

        report = validate_scene.validate_scene(viewer, self.manifest)

        self.assertIn("COMMERCIAL_PROVIDER", self.codes(report["errors"]))

    def test_invalid_transform_fails(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["tilesets"][0]["transform"] = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]

        report = validate_scene.validate_scene(self.viewer, manifest)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("INVALID_TRANSFORM", self.codes(report["errors"]))

    def test_coordinate_system_mismatch_fails(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["coordinateSystemId"] = "MINE-LOCAL-002"

        report = validate_scene.validate_scene(self.viewer, manifest)

        self.assertIn("COORDINATE_SYSTEM_MISMATCH", self.codes(report["errors"]))

    def test_unknown_layer_reference_fails(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["tilesets"][0]["layerId"] = "missing-layer"

        report = validate_scene.validate_scene(self.viewer, manifest)

        self.assertIn("UNKNOWN_LAYER_REF", self.codes(report["errors"]))

    def test_markdown_renderer(self):
        report = validate_scene.validate_scene(self.viewer, self.manifest)
        markdown = validate_scene.render_markdown(report)

        self.assertIn("# Cesium Scene Validation Report", markdown)
        self.assertIn("MINE-LOCAL-001", markdown)
        self.assertIn("Scene Layers", markdown)

    def test_write_outputs(self):
        report = validate_scene.validate_scene(self.viewer, self.manifest)
        with tempfile.TemporaryDirectory() as tmp:
            paths = validate_scene.write_outputs(
                report, str(Path(tmp) / "scene_validation.json"), str(Path(tmp) / "scene_validation.md")
            )
            written = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

        self.assertEqual(written["status"], "PASS")
        self.assertIn("# Cesium Scene Validation Report", markdown)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "scene_validation.json")
            markdown = str(Path(tmp) / "scene_validation.md")
            ok = validate_scene.main(
                [
                    str(FIXTURES / "viewer_config.json"),
                    str(FIXTURES / "scene_manifest.json"),
                    "--output",
                    output,
                    "--markdown",
                    markdown,
                ]
            )
            self.assertEqual(ok, 0)
            self.assertTrue(Path(output).exists())

            invalid_manifest = copy.deepcopy(self.manifest)
            invalid_manifest["layers"][1]["id"] = "base-terrain"
            invalid_path = Path(tmp) / "invalid_manifest.json"
            invalid_path.write_text(json.dumps(invalid_manifest), encoding="utf-8")

            failed = validate_scene.main(
                [
                    str(FIXTURES / "viewer_config.json"),
                    str(invalid_path),
                    "--output",
                    output,
                    "--markdown",
                    markdown,
                ]
            )
            self.assertEqual(failed, 1)

            no_fail = validate_scene.main(
                [
                    str(FIXTURES / "viewer_config.json"),
                    str(invalid_path),
                    "--output",
                    output,
                    "--markdown",
                    markdown,
                    "--no-fail",
                ]
            )
            self.assertEqual(no_fail, 0)


if __name__ == "__main__":
    unittest.main()
