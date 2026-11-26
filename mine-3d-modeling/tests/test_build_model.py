#!/usr/bin/env python3
"""Tests for the mine-3d-modeling scripts."""

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

import build_model  # noqa: E402


def parse_glb(path: Path) -> dict:
    data = path.read_bytes()
    magic, version, total_length = struct.unpack_from("<4sII", data, 0)
    json_length, json_type = struct.unpack_from("<II", data, 12)
    json_start = 20
    gltf = json.loads(data[json_start : json_start + json_length].decode("utf-8"))
    bin_header = json_start + json_length
    bin_length, bin_type = struct.unpack_from("<II", data, bin_header)
    bin_start = bin_header + 8
    return {
        "data": data,
        "magic": magic,
        "version": version,
        "total_length": total_length,
        "json_length": json_length,
        "json_type": json_type,
        "json": gltf,
        "bin_length": bin_length,
        "bin_type": bin_type,
        "bin": data[bin_start : bin_start + bin_length],
    }


def object_vertex_bounds(obj_text: str, name: str) -> dict:
    vertices = [
        tuple(float(value) for value in line.split()[1:4])
        for line in obj_text.splitlines()
        if line.startswith("v ")
    ]
    current = None
    referenced: set[int] = set()
    for line in obj_text.splitlines():
        if line.startswith("o "):
            current = line[2:].strip()
        elif line.startswith("f ") and current == name:
            for token in line.split()[1:]:
                referenced.add(int(token.split("/", 1)[0]) - 1)
    points = [vertices[index] for index in referenced]
    return {
        "min_x": min(point[0] for point in points),
        "min_y": min(point[1] for point in points),
        "min_z": min(point[2] for point in points),
        "max_x": max(point[0] for point in points),
        "max_y": max(point[1] for point in points),
        "max_z": max(point[2] for point in points),
    }


def call_silently(function, argv):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        return function(argv)


class BuildModelTests(unittest.TestCase):
    def run_build(self, out_dir: str) -> int:
        return call_silently(
            build_model.main,
            [
                str(FIXTURES / "terrain.obj"),
                str(FIXTURES / "footprints.csv"),
                "--out-dir",
                out_dir,
            ],
        )

    def test_merged_obj_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_build(tmp), 0)
            out = Path(tmp)
            obj_text = (out / "model.obj").read_text(encoding="utf-8")
            vertex_count = sum(
                1 for line in obj_text.splitlines() if line.startswith("v ")
            )
            face_count = sum(
                1 for line in obj_text.splitlines() if line.startswith("f ")
            )
            object_names = [
                line[2:].strip()
                for line in obj_text.splitlines()
                if line.startswith("o ")
            ]
            self.assertEqual(vertex_count, 52)
            self.assertEqual(face_count, 26)
            self.assertEqual(object_names, ["terrain", "building_a", "building_b"])
            self.assertTrue(all(
                len(line.split()) == 4
                for line in obj_text.splitlines()
                if line.startswith("f ")
            ))

    def test_glb_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_build(tmp), 0)
            glb = parse_glb(Path(tmp) / "model.glb")
            self.assertEqual(glb["magic"], b"glTF")
            self.assertEqual(glb["version"], 2)
            self.assertEqual(glb["total_length"], len(glb["data"]))
            self.assertEqual(glb["json_type"], 0x4E4F534A)
            self.assertEqual(glb["bin_type"], 0x004E4942)
            self.assertEqual(glb["total_length"] % 4, 0)

            gltf = glb["json"]
            self.assertEqual(gltf["asset"]["version"], "2.0")
            self.assertEqual(gltf["scene"], 0)
            self.assertEqual(gltf["meshes"][0]["primitives"][0]["mode"], 4)
            attributes = gltf["meshes"][0]["primitives"][0]["attributes"]
            self.assertEqual(attributes, {"POSITION": 0, "NORMAL": 1})
            self.assertEqual(gltf["meshes"][0]["primitives"][0]["indices"], 2)

            position_accessor = gltf["accessors"][0]
            normal_accessor = gltf["accessors"][1]
            index_accessor = gltf["accessors"][2]
            self.assertEqual(position_accessor["componentType"], 5126)
            self.assertEqual(position_accessor["type"], "VEC3")
            self.assertEqual(position_accessor["count"], 52)
            self.assertEqual(normal_accessor["count"], 52)
            self.assertEqual(index_accessor["componentType"], 5125)
            self.assertEqual(index_accessor["type"], "SCALAR")
            self.assertEqual(index_accessor["count"], 78)
            self.assertEqual(gltf["buffers"][0]["byteLength"], 12 * 52 + 12 * 52 + 4 * 78)
            self.assertLessEqual(
                gltf["buffers"][0]["byteLength"], glb["bin_length"]
            )

            # Decode the BIN chunk: normals must be unit length and indices valid.
            buffer_views = gltf["bufferViews"]
            normal_view = buffer_views[1]
            index_view = buffer_views[2]
            for vertex_index in range(normal_accessor["count"]):
                offset = normal_view["byteOffset"] + vertex_index * 12
                nx, ny, nz = struct.unpack_from("<3f", glb["bin"], offset)
                length = math.sqrt(nx * nx + ny * ny + nz * nz)
                self.assertAlmostEqual(length, 1.0, places=5)
            indices = struct.unpack_from(
                f"<{index_accessor['count']}I", glb["bin"], index_view["byteOffset"]
            )
            self.assertEqual(len(indices), 78)
            self.assertLess(max(indices), position_accessor["count"])
            for a, b, c in zip(indices[0::3], indices[1::3], indices[2::3]):
                self.assertNotEqual(a, b)
                self.assertNotEqual(b, c)
                self.assertNotEqual(a, c)

            # Source merged bounds are x 0..10, y 0..10, z 0..6 (Z-up).
            # The GLB is Y-up: (x, y, z) -> (x, z, -y).
            expected_min = [0.0, 0.0, -10.0]
            expected_max = [10.0, 6.0, 0.0]
            for actual, expected in zip(position_accessor["min"], expected_min):
                self.assertAlmostEqual(actual, expected, places=5)
            for actual, expected in zip(position_accessor["max"], expected_max):
                self.assertAlmostEqual(actual, expected, places=5)

    def test_manifest_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_build(tmp), 0)
            out = Path(tmp)
            manifest = json.loads(
                (out / "model_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["schema_version"], "0.1")
            self.assertEqual(manifest["skill"], "mine-3d-modeling")
            self.assertEqual(manifest["units"], "UNKNOWN")
            self.assertEqual(manifest["crs"], "UNKNOWN")
            self.assertEqual(manifest["axis_convention"]["source"], "Z_UP")
            self.assertEqual(manifest["axis_convention"]["glb"], "Y_UP")
            self.assertIn("x, z, -y", manifest["axis_convention"]["glb_mapping"])
            self.assertEqual(manifest["terrain"]["vertex_count"], 4)
            self.assertEqual(manifest["terrain"]["face_count"], 2)
            self.assertEqual(manifest["merged"]["vertex_count"], 52)
            self.assertEqual(manifest["merged"]["face_count"], 26)
            self.assertEqual(manifest["merged"]["triangle_count"], 26)
            self.assertEqual(len(manifest["footprints"]), 2)
            self.assertEqual(manifest["glb"]["vertex_count"], 52)
            self.assertEqual(manifest["glb"]["triangle_count"], 26)
            self.assertEqual(manifest["glb"]["normal_mode"], "area_weighted_per_vertex")
            self.assertTrue(manifest["source"]["terrain_obj"]["sha256"])
            self.assertTrue(manifest["source"]["footprints_csv"]["sha256"])
            self.assertEqual(manifest["outputs"]["glb"], "model.glb")

            report = json.loads(
                (out / "modeling_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["manifest"]["merged"]["vertex_count"], 52)
            markdown = (out / "modeling_report.md").read_text(encoding="utf-8")
            self.assertIn("# Mine 3D Modeling Report", markdown)
            self.assertIn("building_b", markdown)

    def test_rotated_box_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_build(tmp), 0)
            out = Path(tmp)
            manifest = json.loads(
                (out / "model_manifest.json").read_text(encoding="utf-8")
            )
            by_id = {footprint["id"]: footprint for footprint in manifest["footprints"]}
            self.assertEqual(set(by_id), {"building_a", "building_b"})

            unrotated = by_id["building_a"]
            self.assertEqual(unrotated["rotation_deg"], 0.0)
            self.assertEqual(unrotated["base_z_source"], "nearest_terrain_vertex")
            self.assertAlmostEqual(unrotated["bounds"]["min_x"], 1.0)
            self.assertAlmostEqual(unrotated["bounds"]["max_x"], 5.0)
            self.assertAlmostEqual(unrotated["bounds"]["min_y"], 3.0)
            self.assertAlmostEqual(unrotated["bounds"]["max_y"], 5.0)
            self.assertAlmostEqual(unrotated["bounds"]["min_z"], 0.0)
            self.assertAlmostEqual(unrotated["bounds"]["max_z"], 6.0)

            expected_half = math.sqrt(2.0)
            rotated = by_id["building_b"]
            self.assertEqual(rotated["rotation_deg"], 45.0)
            self.assertAlmostEqual(rotated["bounds"]["min_x"], 7.0 - expected_half, places=5)
            self.assertAlmostEqual(rotated["bounds"]["max_x"], 7.0 + expected_half, places=5)
            self.assertAlmostEqual(rotated["bounds"]["min_y"], 7.0 - expected_half, places=5)
            self.assertAlmostEqual(rotated["bounds"]["max_y"], 7.0 + expected_half, places=5)
            self.assertAlmostEqual(rotated["bounds"]["min_z"], 1.0, places=6)
            self.assertAlmostEqual(rotated["bounds"]["max_z"], 4.0, places=6)

            # Recompute the rotated box bounds from actual merged OBJ geometry.
            obj_text = (out / "model.obj").read_text(encoding="utf-8")
            obj_bounds = object_vertex_bounds(obj_text, "building_b")
            self.assertAlmostEqual(obj_bounds["min_x"], 7.0 - expected_half, places=5)
            self.assertAlmostEqual(obj_bounds["max_x"], 7.0 + expected_half, places=5)
            self.assertAlmostEqual(obj_bounds["min_y"], 7.0 - expected_half, places=5)
            self.assertAlmostEqual(obj_bounds["max_y"], 7.0 + expected_half, places=5)
            self.assertAlmostEqual(obj_bounds["min_z"], 1.0, places=5)
            self.assertAlmostEqual(obj_bounds["max_z"], 4.0, places=5)

    def test_explicit_base_z(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "footprints.csv"
            csv_path.write_text(
                "id,x,y,width,depth,height,rotation_deg,base_z\n"
                "tank,2,2,1,1,2,0,5\n",
                encoding="utf-8",
            )
            data = build_model.read_footprints(str(csv_path))
            self.assertEqual(data["footprints"][0]["base_z"], 5.0)
            self.assertEqual(data["base_z_column"], "base_z")

    def test_invalid_footprint_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "footprints.csv"
            csv_path.write_text(
                "id,x,y,width,depth,height,rotation_deg\n"
                "bad,0,0,0,1,1,0\n",
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                build_model.read_footprints(str(csv_path))

    def test_large_coordinates_emit_float32_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj_path = Path(tmp) / "terrain.obj"
            obj_path.write_text(
                "v 500000 4000000 100\n"
                "v 500010 4000000 100\n"
                "v 500000 4000010 102\n"
                "f 1 2 3\n",
                encoding="utf-8",
            )
            csv_path = Path(tmp) / "footprints.csv"
            csv_path.write_text(
                "id,x,y,width,depth,height,rotation_deg\n"
                "b,500005,4000005,2,2,3,0\n",
                encoding="utf-8",
            )
            self.assertEqual(
                call_silently(
                    build_model.main,
                    [
                        str(obj_path),
                        str(csv_path),
                        "--out-dir",
                        str(Path(tmp) / "out"),
                    ],
                ),
                0,
            )
            manifest = json.loads(
                (Path(tmp) / "out" / "model_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertGreater(manifest["glb"]["position_abs_max"], 1e5)
            self.assertTrue(
                any("float32" in warning for warning in manifest["warnings"])
            )


if __name__ == "__main__":
    unittest.main()
