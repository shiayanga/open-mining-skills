#!/usr/bin/env python3
"""Tests for the mine-3d-tiles scripts."""

from __future__ import annotations

import contextlib
import io
import json
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import make_tileset  # noqa: E402
import validate_tileset as validator  # noqa: E402


def call_silently(function, argv):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        return function(argv)


def write_dummy_glb(path: Path) -> None:
    gltf = {"asset": {"version": "2.0"}}
    json_bytes = json.dumps(gltf).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    total_length = 12 + 8 + len(json_bytes) + 8
    with open(path, "wb") as fh:
        fh.write(struct.pack("<4sII", b"glTF", 2, total_length))
        fh.write(struct.pack("<II", len(json_bytes), 0x4E4F534A))
        fh.write(json_bytes)
        fh.write(struct.pack("<II", 0, 0x004E4942))


class MakeTilesetTests(unittest.TestCase):
    def test_obj_bounds(self):
        bounds = make_tileset.read_obj_bounds(str(FIXTURES / "dummy.obj"))
        self.assertEqual(bounds["vertex_count"], 3)
        self.assertEqual(bounds["min"], [100.0, 200.0, 10.0])
        self.assertEqual(bounds["max"], [110.0, 205.0, 14.0])

    def test_make_tileset_from_obj(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                call_silently(
                    make_tileset.main,
                    [str(FIXTURES / "dummy.obj"), "--out-dir", tmp],
                ),
                0,
            )
            out = Path(tmp)
            tileset = json.loads((out / "tileset.json").read_text(encoding="utf-8"))
            self.assertEqual(tileset["asset"]["version"], "1.1")
            self.assertTrue(tileset["asset"]["generator"])
            self.assertAlmostEqual(
                tileset["geometricError"], math.sqrt(141.0), places=6
            )
            root = tileset["root"]
            self.assertEqual(root["geometricError"], 0)
            self.assertEqual(root["refine"], "ADD")
            self.assertEqual(root["content"]["uri"], "dummy.obj")
            self.assertTrue((out / "dummy.obj").is_file())
            self.assertEqual(len(root["boundingVolume"]["box"]), 12)
            expected_box = [
                105.0, 202.5, 12.0,
                5.0, 0.0, 0.0,
                0.0, 2.5, 0.0,
                0.0, 0.0, 2.0,
            ]
            for actual, expected in zip(root["boundingVolume"]["box"], expected_box):
                self.assertAlmostEqual(actual, expected)

            report = json.loads(
                (out / "tiling_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["asset_version"], "1.1")
            self.assertEqual(report["source"]["bbox_source"], "obj_vertices")
            self.assertEqual(report["source"]["content_type"], "OBJ")
            self.assertEqual(report["source"]["obj_vertex_count"], 3)
            self.assertEqual(report["bounding_box"]["frame"], "content")
            self.assertEqual(report["bounding_box"]["centre"], [105.0, 202.5, 12.0])
            self.assertEqual(
                report["tileset"]["content_sha256"],
                report["source"]["content"]["sha256"],
            )
            self.assertTrue((out / "tiling_report.md").is_file())

    def test_make_tileset_from_glb_requires_bbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            glb_path = Path(tmp) / "dummy.glb"
            write_dummy_glb(glb_path)
            with self.assertRaises(SystemExit):
                call_silently(
                    make_tileset.main, [str(glb_path), "--out-dir", str(Path(tmp) / "out")]
                )
            self.assertEqual(
                call_silently(
                    make_tileset.main,
                    [
                        str(glb_path),
                        "--bbox",
                        "0,0,0,10,20,5",
                        "--out-dir",
                        str(Path(tmp) / "out"),
                    ],
                ),
                0,
            )
            tileset = json.loads(
                (Path(tmp) / "out" / "tileset.json").read_text(encoding="utf-8")
            )
            box = tileset["root"]["boundingVolume"]["box"]
            expected = [
                5.0, 10.0, 2.5,
                5.0, 0.0, 0.0,
                0.0, 10.0, 0.0,
                0.0, 0.0, 2.5,
            ]
            for actual, expected_value in zip(box, expected):
                self.assertAlmostEqual(actual, expected_value)
            self.assertTrue((Path(tmp) / "out" / "dummy.glb").is_file())
            report = json.loads(
                (Path(tmp) / "out" / "tiling_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["source"]["bbox_source"], "cli_bbox")
            self.assertEqual(report["source"]["content_type"], "GLB")

    def test_bbox_override_on_obj(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                call_silently(
                    make_tileset.main,
                    [
                        str(FIXTURES / "dummy.obj"),
                        "--bbox",
                        "0,0,0,100,100,100",
                        "--out-dir",
                        tmp,
                    ],
                ),
                0,
            )
            report = json.loads(
                (Path(tmp) / "tiling_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                report["source"]["bbox_source"], "cli_bbox_override_obj"
            )
            self.assertTrue(
                any("overrides" in warning for warning in report["warnings"])
            )

    def test_invalid_bbox(self):
        with self.assertRaises(SystemExit):
            make_tileset.parse_bbox("1,2,3,4,5")
        with self.assertRaises(SystemExit):
            make_tileset.parse_bbox("1,2,3,4,5,6,7")
        with self.assertRaises(SystemExit):
            make_tileset.parse_bbox("0,0,0,10,10,10,x")
        with self.assertRaises(SystemExit):
            make_tileset.parse_bbox("10,0,0,0,10,10")

    def test_bad_glb_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            glb_path = Path(tmp) / "bad.glb"
            glb_path.write_bytes(b"not-a-glb-file")
            with self.assertRaises(SystemExit):
                make_tileset.check_glb_header(str(glb_path))


class ValidateTilesetTests(unittest.TestCase):
    def make_valid_tileset(self, tmp: str) -> Path:
        self.assertEqual(
            call_silently(
                make_tileset.main,
                [str(FIXTURES / "dummy.obj"), "--out-dir", tmp],
            ),
            0,
        )
        return Path(tmp) / "tileset.json"

    def test_generated_tileset_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            tileset_path = self.make_valid_tileset(tmp)
            result = validator.validate_tileset(str(tileset_path))
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(result["asset_version"], "1.1")
            self.assertEqual(result["errors"], [])
            self.assertEqual(call_silently(validator.main, [str(tileset_path)]), 0)

    def test_missing_content_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tileset_path = self.make_valid_tileset(tmp)
            (Path(tmp) / "dummy.obj").unlink()
            result = validator.validate_tileset(str(tileset_path))
            self.assertFalse(result["ok"])
            codes = {item["code"] for item in result["errors"]}
            self.assertIn("CONTENT_FILE_MISSING", codes)
            self.assertEqual(call_silently(validator.main, [str(tileset_path)]), 1)

    def test_bad_box_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tileset_path = self.make_valid_tileset(tmp)
            tileset = json.loads(tileset_path.read_text(encoding="utf-8"))
            tileset["root"]["boundingVolume"]["box"] = [0.0] * 11
            tileset_path.write_text(json.dumps(tileset), encoding="utf-8")
            result = validator.validate_tileset(str(tileset_path))
            self.assertFalse(result["ok"])
            codes = {item["code"] for item in result["errors"]}
            self.assertIn("BOX_LENGTH_INVALID", codes)

    def test_missing_geometric_error_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tileset_path = self.make_valid_tileset(tmp)
            tileset = json.loads(tileset_path.read_text(encoding="utf-8"))
            del tileset["geometricError"]
            tileset_path.write_text(json.dumps(tileset), encoding="utf-8")
            result = validator.validate_tileset(str(tileset_path))
            self.assertFalse(result["ok"])
            codes = {item["code"] for item in result["errors"]}
            self.assertIn("GEOMETRIC_ERROR_MISSING", codes)

            tileset = json.loads(tileset_path.read_text(encoding="utf-8"))
            tileset["geometricError"] = 10.0
            del tileset["root"]["geometricError"]
            tileset_path.write_text(json.dumps(tileset), encoding="utf-8")
            result = validator.validate_tileset(str(tileset_path))
            self.assertFalse(result["ok"])
            codes = {item["code"] for item in result["errors"]}
            self.assertIn("ROOT_GEOMETRIC_ERROR_MISSING", codes)

    def test_unsupported_asset_version_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tileset_path = self.make_valid_tileset(tmp)
            tileset = json.loads(tileset_path.read_text(encoding="utf-8"))
            tileset["asset"]["version"] = "0.9"
            tileset_path.write_text(json.dumps(tileset), encoding="utf-8")
            result = validator.validate_tileset(str(tileset_path))
            self.assertFalse(result["ok"])
            codes = {item["code"] for item in result["errors"]}
            self.assertIn("ASSET_VERSION_UNSUPPORTED", codes)

    def test_missing_root_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tileset_path = self.make_valid_tileset(tmp)
            tileset = json.loads(tileset_path.read_text(encoding="utf-8"))
            del tileset["root"]
            tileset_path.write_text(json.dumps(tileset), encoding="utf-8")
            result = validator.validate_tileset(str(tileset_path))
            self.assertFalse(result["ok"])
            codes = {item["code"] for item in result["errors"]}
            self.assertIn("ROOT_MISSING", codes)

    def test_missing_tileset_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = validator.validate_tileset(str(Path(tmp) / "missing.json"))
            self.assertFalse(result["ok"])
            self.assertEqual(result["errors"][0]["code"], "FILE_NOT_FOUND")
            self.assertEqual(
                call_silently(validator.main, [str(Path(tmp) / "missing.json")]), 1
            )


if __name__ == "__main__":
    unittest.main()
