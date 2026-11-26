#!/usr/bin/env python3
"""Build a v0.1 mine scene by merging a terrain OBJ with footprint boxes.

Inputs
------
* Terrain OBJ: ``v`` vertices and ``f`` faces (polygons are fan-triangulated).
* Footprints CSV: ``id,x,y,width,depth,height,rotation_deg[,base_z]``.

Outputs
-------
* ``model.obj`` — merged terrain and boxes, source Z-up coordinates.
* ``model.glb`` — minimal glTF 2.0 binary (POSITION, NORMAL, uint32 indices),
  converted from source Z-up to glTF Y-up as ``(x, y, z) -> (x, z, -y)``.
* ``model_manifest.json`` and modeling reports.

The script is deliberately dependency-free and does not perform texture, UV,
material, clipping, LOD or CSG processing. See ``references/`` for the exact
subset and its limitations.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import struct
import sys
from pathlib import Path

import common

CSV_REQUIRED = ("id", "x", "y", "width", "depth", "height", "rotation_deg")
CSV_BASE_Z_NAMES = ("base_z", "z")

GLB_MAGIC = b"glTF"
GLB_VERSION = 2
JSON_CHUNK_TYPE = 0x4E4F534A
BIN_CHUNK_TYPE = 0x004E4942
GENERATOR = "open-mining-skills mine-3d-modeling v0.1"
GLB_AXIS_MAPPING = "(x, y, z) -> (x, z, -y)"
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963
FLOAT = 5126
UNSIGNED_INT = 5125
TRIANGLES = 4


# ---------------------------------------------------------------------------
# OBJ input
# ---------------------------------------------------------------------------


def _triangle_area2(vertices: list[tuple[float, float, float]], a: int, b: int, c: int) -> float:
    ax, ay, az = vertices[a]
    bx, by, bz = vertices[b]
    cx, cy, cz = vertices[c]
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    return nx * nx + ny * ny + nz * nz


def read_obj(path: str) -> dict:
    """Read the v0.1 OBJ subset: vertices and faces.

    Faces must reference previously defined vertices. Polygons are
    fan-triangulated; degenerate triangles are removed. ``vt``, ``vn``,
    materials, groups and other records are counted but not used.
    """
    text, encoding = common.read_text(path)
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    stats = {
        "v": 0,
        "vt": 0,
        "vn": 0,
        "f": 0,
        "other": 0,
        "polygons_triangulated": 0,
        "negative_indices": 0,
        "degenerate_triangles_removed": 0,
    }

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        key = parts[0]
        if key == "v":
            if len(parts) < 4:
                raise SystemExit(f"{path}:{lineno}: vertex requires x y z")
            try:
                coords = tuple(float(value) for value in parts[1:4])
            except ValueError as exc:
                raise SystemExit(f"{path}:{lineno}: non-numeric vertex coordinate") from exc
            if not all(math.isfinite(value) for value in coords):
                raise SystemExit(f"{path}:{lineno}: non-finite vertex coordinate")
            vertices.append(coords)  # type: ignore[arg-type]
            stats["v"] += 1
        elif key == "f":
            if len(parts) < 4:
                raise SystemExit(f"{path}:{lineno}: face requires at least 3 vertices")
            refs: list[int] = []
            for token in parts[1:]:
                index_token = token.split("/", 1)[0]
                if not index_token:
                    raise SystemExit(f"{path}:{lineno}: invalid face reference {token!r}")
                try:
                    index = int(index_token)
                except ValueError as exc:
                    raise SystemExit(
                        f"{path}:{lineno}: non-integer face reference {token!r}"
                    ) from exc
                if index == 0:
                    raise SystemExit(f"{path}:{lineno}: OBJ indices are 1-based, 0 is invalid")
                if index < 0:
                    stats["negative_indices"] += 1
                    resolved = len(vertices) + index
                else:
                    resolved = index - 1
                if resolved < 0 or resolved >= len(vertices):
                    raise SystemExit(
                        f"{path}:{lineno}: face references vertex {index} outside "
                        f"the {len(vertices)} vertices defined so far"
                    )
                refs.append(resolved)
            stats["f"] += 1
            if len(refs) > 3:
                stats["polygons_triangulated"] += 1
            for offset in range(1, len(refs) - 1):
                a, b, c = refs[0], refs[offset], refs[offset + 1]
                if a == b or b == c or a == c:
                    stats["degenerate_triangles_removed"] += 1
                    continue
                if _triangle_area2(vertices, a, b, c) <= 1e-24:
                    stats["degenerate_triangles_removed"] += 1
                    continue
                triangles.append((a, b, c))
        elif key in {"vt", "vn"}:
            stats[key] += 1
        else:
            stats["other"] += 1

    if not vertices:
        raise SystemExit(f"{path}: no vertices found")
    if not triangles:
        raise SystemExit(f"{path}: no valid triangles found")

    referenced = {index for face in triangles for index in face}
    return {
        "vertices": vertices,
        "faces": triangles,
        "vertex_count": len(vertices),
        "face_count": len(triangles),
        "orphan_vertex_count": len(vertices) - len(referenced),
        "stats": stats,
        "bounds": bounds_from_faces(vertices, triangles),
        "encoding": encoding,
    }


# ---------------------------------------------------------------------------
# Footprints
# ---------------------------------------------------------------------------


def _cell(row: list[str], index: dict[str, int], name: str) -> str:
    position = index.get(name)
    if position is None or position >= len(row):
        return ""
    return row[position].strip()


def _required_number(value: str, path: str, line: int, name: str) -> float:
    if value == "":
        raise SystemExit(f"{path}:{line}: missing numeric value for {name}")
    try:
        number = float(value)
    except ValueError as exc:
        raise SystemExit(f"{path}:{line}: non-numeric {name} {value!r}") from exc
    if not math.isfinite(number):
        raise SystemExit(f"{path}:{line}: non-finite {name}")
    return number


def read_footprints(path: str) -> dict:
    """Read the footprint CSV and validate geometric fields.

    ``x, y`` is the footprint centre in source coordinates. ``width`` runs
    along local X, ``depth`` along local Y, ``height`` upward. Rotation is
    counter-clockwise around +Z in degrees. ``base_z`` (or ``z``) is optional;
    when absent the base is inferred from the nearest terrain vertex.
    """
    text, encoding = common.read_text(path)
    reader = csv.reader(io.StringIO(text))
    header: list[str] | None = None
    data_rows: list[tuple[int, list[str]]] = []
    header_line = 0

    for row in reader:
        if not row or not any(cell.strip() for cell in row):
            continue
        if row[0].lstrip().startswith("#"):
            continue
        if header is None:
            header = [cell.strip().lower() for cell in row]
            header_line = reader.line_num
            continue
        data_rows.append((reader.line_num, row))

    if header is None:
        raise SystemExit(f"{path}: missing header row")
    missing = [name for name in CSV_REQUIRED if name not in header]
    if missing:
        raise SystemExit(f"{path}: missing required columns: {', '.join(missing)}")

    index = {name: header.index(name) for name in header}
    base_z_name = next((name for name in CSV_BASE_Z_NAMES if name in index), None)
    footprints: list[dict] = []
    seen_ids: dict[str, int] = {}

    for line, row in data_rows:
        footprint_id = _cell(row, index, "id")
        if not footprint_id:
            raise SystemExit(f"{path}:{line}: empty footprint id")
        if footprint_id in seen_ids:
            raise SystemExit(
                f"{path}:{line}: duplicate footprint id {footprint_id!r} "
                f"(first on line {seen_ids[footprint_id]})"
            )
        seen_ids[footprint_id] = line

        x = _required_number(_cell(row, index, "x"), path, line, "x")
        y = _required_number(_cell(row, index, "y"), path, line, "y")
        width = _required_number(_cell(row, index, "width"), path, line, "width")
        depth = _required_number(_cell(row, index, "depth"), path, line, "depth")
        height = _required_number(_cell(row, index, "height"), path, line, "height")
        rotation = _required_number(
            _cell(row, index, "rotation_deg"), path, line, "rotation_deg"
        )
        if width <= 0 or depth <= 0 or height <= 0:
            raise SystemExit(f"{path}:{line}: width, depth and height must be greater than 0")

        base_z = None
        if base_z_name:
            raw_base = _cell(row, index, base_z_name)
            if raw_base != "":
                base_z = _required_number(raw_base, path, line, base_z_name)

        footprints.append(
            {
                "id": footprint_id,
                "x": x,
                "y": y,
                "width": width,
                "depth": depth,
                "height": height,
                "rotation_deg": rotation,
                "base_z": base_z,
                "base_z_source": "footprints_csv" if base_z is not None else None,
                "source_line": line,
            }
        )

    return {
        "footprints": footprints,
        "header": header,
        "header_line": header_line,
        "base_z_column": base_z_name,
        "row_count": len(data_rows),
        "encoding": encoding,
        "delimiter": "comma",
    }


def _nearest_terrain_z(
    x: float, y: float, vertices: list[tuple[float, float, float]]
) -> float:
    nearest = min(vertices, key=lambda vertex: (vertex[0] - x) ** 2 + (vertex[1] - y) ** 2)
    return nearest[2]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def make_box(footprint: dict, base_z: float) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Return 24 vertices and 12 triangles for a rotated footprint box.

    Each face has its own four vertices, so GLB normals stay hard on edges.
    """
    width = footprint["width"]
    depth = footprint["depth"]
    height = footprint["height"]
    theta = math.radians(footprint["rotation_deg"])
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    hx = width / 2.0
    hy = depth / 2.0

    def transform(x: float, y: float, z: float) -> tuple[float, float, float]:
        rotated_x = cos_theta * x - sin_theta * y
        rotated_y = sin_theta * x + cos_theta * y
        return (footprint["x"] + rotated_x, footprint["y"] + rotated_y, base_z + z)

    face_corners = [
        # bottom, outward -Z
        [(-hx, -hy, 0.0), (-hx, hy, 0.0), (hx, hy, 0.0), (hx, -hy, 0.0)],
        # top, outward +Z
        [(-hx, -hy, height), (hx, -hy, height), (hx, hy, height), (-hx, hy, height)],
        # front (local -Y)
        [(-hx, -hy, 0.0), (hx, -hy, 0.0), (hx, -hy, height), (-hx, -hy, height)],
        # back (local +Y)
        [(hx, hy, 0.0), (-hx, hy, 0.0), (-hx, hy, height), (hx, hy, height)],
        # right (local +X)
        [(hx, -hy, 0.0), (hx, hy, 0.0), (hx, hy, height), (hx, -hy, height)],
        # left (local -X)
        [(-hx, hy, 0.0), (-hx, -hy, 0.0), (-hx, -hy, height), (-hx, hy, height)],
    ]

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for corners in face_corners:
        base = len(vertices)
        vertices.extend(transform(*corner) for corner in corners)
        faces.append((base, base + 1, base + 2))
        faces.append((base, base + 2, base + 3))
    return vertices, faces


def bounds_from_vertices(vertices: list[tuple[float, float, float]]) -> dict | None:
    if not vertices:
        return None
    xs = [vertex[0] for vertex in vertices]
    ys = [vertex[1] for vertex in vertices]
    zs = [vertex[2] for vertex in vertices]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)
    return {
        "min_x": min_x,
        "min_y": min_y,
        "min_z": min_z,
        "max_x": max_x,
        "max_y": max_y,
        "max_z": max_z,
        "span_x": max_x - min_x,
        "span_y": max_y - min_y,
        "span_z": max_z - min_z,
    }


def bounds_from_faces(
    vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]]
) -> dict | None:
    if not faces:
        return None
    used = {index for face in faces for index in face}
    return bounds_from_vertices([vertices[index] for index in used])


def build_scene(terrain: dict, footprint_data: dict) -> dict:
    """Merge terrain triangles and footprint boxes into one indexed mesh."""
    merged_vertices = list(terrain["vertices"])
    terrain_faces = list(terrain["faces"])
    merged_faces = list(terrain_faces)
    footprint_records: list[dict] = []
    inferred: list[str] = []

    for footprint in footprint_data["footprints"]:
        base_z = footprint["base_z"]
        if base_z is None:
            base_z = _nearest_terrain_z(footprint["x"], footprint["y"], terrain["vertices"])
            footprint["base_z"] = base_z
            footprint["base_z_source"] = "nearest_terrain_vertex"
            inferred.append(footprint["id"])
        box_vertices, box_faces = make_box(footprint, base_z)
        offset = len(merged_vertices)
        merged_vertices.extend(box_vertices)
        shifted_faces = [
            (a + offset, b + offset, c + offset) for a, b, c in box_faces
        ]
        merged_faces.extend(shifted_faces)
        record = dict(footprint)
        record["bounds"] = bounds_from_faces(box_vertices, box_faces)
        record["box_vertex_count"] = len(box_vertices)
        record["box_triangle_count"] = len(box_faces)
        footprint_records.append(record)

    warnings: list[str] = []
    stats = terrain["stats"]
    if stats["degenerate_triangles_removed"]:
        warnings.append(
            f"{stats['degenerate_triangles_removed']} degenerate terrain triangle(s) "
            "were removed."
        )
    if terrain["orphan_vertex_count"]:
        warnings.append(
            f"{terrain['orphan_vertex_count']} terrain vertex/vertices are not "
            "referenced by any triangle."
        )
    if inferred:
        warnings.append(
            f"{len(inferred)} footprint base elevation(s) were inferred from the "
            "nearest terrain vertex; verify against survey data."
        )
    if not footprint_records:
        warnings.append("No footprints were supplied; the model contains terrain only.")

    return {
        "vertices": merged_vertices,
        "faces": merged_faces,
        "terrain_vertices": terrain["vertices"],
        "terrain_faces": terrain_faces,
        "footprints": footprint_records,
        "bounds": bounds_from_vertices(merged_vertices),
        "warnings": warnings,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# OBJ output
# ---------------------------------------------------------------------------


def _format_coordinate(value: float, precision: int) -> str:
    if abs(value) < 0.5 * 10 ** (-precision):
        value = 0.0
    return f"{value:.{precision}f}"


def write_obj(path: str, scene: dict, precision: int = 6) -> None:
    """Write the merged model as a Z-up OBJ with object groups."""
    lines = [
        "# Generated by open-mining-skills mine-3d-modeling v0.1",
        "# Axis: Z-up. Units: UNKNOWN. CRS: UNKNOWN.",
        f"# Vertices: {len(scene['vertices'])}; triangles: {len(scene['faces'])}",
        "# Source normals, UVs, materials and groups are not preserved.",
        "",
    ]
    for vertex in scene["vertices"]:
        lines.append("v " + " ".join(_format_coordinate(value, precision) for value in vertex))

    lines.append("")
    lines.append("o terrain")
    for face in scene["terrain_faces"]:
        lines.append(f"f {face[0] + 1} {face[1] + 1} {face[2] + 1}")

    face_index = len(scene["terrain_faces"])
    for record in scene["footprints"]:
        object_name = record["id"].replace("\r", " ").replace("\n", " ")
        lines.append(f"o {object_name}")
        count = record["box_triangle_count"]
        for face in scene["faces"][face_index : face_index + count]:
            lines.append(f"f {face[0] + 1} {face[1] + 1} {face[2] + 1}")
        face_index += count

    common.write_text(path, "\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# GLB output
# ---------------------------------------------------------------------------


def compute_vertex_normals(
    vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]]
) -> list[tuple[float, float, float]]:
    """Area-weighted per-vertex normals.

    Box faces do not share vertices, so their edges stay hard. Shared terrain
    vertices are smooth-shaded. Zero-length normals fall back to +Z.
    """
    accum = [[0.0, 0.0, 0.0] for _ in vertices]
    for a, b, c in faces:
        ax, ay, az = vertices[a]
        bx, by, bz = vertices[b]
        cx, cy, cz = vertices[c]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        for index in (a, b, c):
            accum[index][0] += nx
            accum[index][1] += ny
            accum[index][2] += nz

    normals: list[tuple[float, float, float]] = []
    for x, y, z in accum:
        length = math.sqrt(x * x + y * y + z * z)
        if length == 0.0:
            normals.append((0.0, 0.0, 1.0))
        else:
            normals.append((x / length, y / length, z / length))
    return normals


def _float32(value: float) -> float:
    try:
        return struct.unpack("<f", struct.pack("<f", value))[0]
    except OverflowError as exc:
        raise SystemExit(f"Coordinate {value} exceeds the float32 range required by glTF") from exc


def _float32_bounds(values: list[tuple[float, float, float]]) -> tuple[list[float], list[float]]:
    minimum = [min(value[axis] for value in values) for axis in range(3)]
    maximum = [max(value[axis] for value in values) for axis in range(3)]
    return minimum, maximum


def write_glb(path: str, vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]]) -> dict:
    """Write a minimal valid glTF 2.0 binary and return export metadata."""
    if not faces:
        raise SystemExit("Cannot export an empty GLB")
    if len(vertices) >= 2**32:
        raise SystemExit("GLB export supports fewer than 2^32 vertices")

    normals = compute_vertex_normals(vertices, faces)
    # glTF is Y-up and right-handed; source mine data is Z-up.
    positions_yup = [
        (_float32(x), _float32(z), _float32(-y)) for x, y, z in vertices
    ]
    normals_yup = [
        (_float32(x), _float32(z), _float32(-y)) for x, y, z in normals
    ]

    position_bytes = b"".join(struct.pack("<3f", *value) for value in positions_yup)
    normal_bytes = b"".join(struct.pack("<3f", *value) for value in normals_yup)
    indices = [index for face in faces for index in face]
    index_bytes = struct.pack(f"<{len(indices)}I", *indices)
    binary = position_bytes + normal_bytes + index_bytes

    position_min, position_max = _float32_bounds(positions_yup)
    position_abs_max = max(abs(value) for position in positions_yup for value in position)
    gltf = {
        "asset": {
            "version": "2.0",
            "generator": GENERATOR,
            "extras": {
                "sourceAxis": "Z_UP",
                "glbAxis": "Y_UP",
                "axisMapping": GLB_AXIS_MAPPING,
            },
        },
        "scene": 0,
        "scenes": [{"name": "mine_scene", "nodes": [0]}],
        "nodes": [{"name": "mine_model", "mesh": 0}],
        "meshes": [
            {
                "name": "mine_model",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1},
                        "indices": 2,
                        "mode": TRIANGLES,
                    }
                ],
            }
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": len(position_bytes),
                "target": ARRAY_BUFFER,
            },
            {
                "buffer": 0,
                "byteOffset": len(position_bytes),
                "byteLength": len(normal_bytes),
                "target": ARRAY_BUFFER,
            },
            {
                "buffer": 0,
                "byteOffset": len(position_bytes) + len(normal_bytes),
                "byteLength": len(index_bytes),
                "target": ELEMENT_ARRAY_BUFFER,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": FLOAT,
                "count": len(positions_yup),
                "type": "VEC3",
                "min": position_min,
                "max": position_max,
            },
            {
                "bufferView": 1,
                "componentType": FLOAT,
                "count": len(normals_yup),
                "type": "VEC3",
            },
            {
                "bufferView": 2,
                "componentType": UNSIGNED_INT,
                "count": len(indices),
                "type": "SCALAR",
            },
        ],
    }

    json_bytes = json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    bin_bytes = binary + b"\x00" * ((4 - len(binary) % 4) % 4)
    total_length = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)

    with open(path, "wb") as fh:
        fh.write(struct.pack("<4sII", GLB_MAGIC, GLB_VERSION, total_length))
        fh.write(struct.pack("<II", len(json_bytes), JSON_CHUNK_TYPE))
        fh.write(json_bytes)
        fh.write(struct.pack("<II", len(bin_bytes), BIN_CHUNK_TYPE))
        fh.write(bin_bytes)

    return {
        "vertex_count": len(positions_yup),
        "triangle_count": len(faces),
        "index_count": len(indices),
        "position_bounds": {
            "min": position_min,
            "max": position_max,
        },
        "position_abs_max": position_abs_max,
        "normal_mode": "area_weighted_per_vertex",
        "axis": "Y_UP",
        "file_size_bytes": total_length,
        "buffer_byte_length": len(binary),
        "accessors": {
            "position": {"component_type": "FLOAT", "type": "VEC3"},
            "normal": {"component_type": "FLOAT", "type": "VEC3"},
            "indices": {"component_type": "UNSIGNED_INT", "type": "SCALAR"},
        },
    }


# ---------------------------------------------------------------------------
# Manifest and report
# ---------------------------------------------------------------------------


def build_manifest(
    scene: dict,
    terrain: dict,
    glb_meta: dict,
    terrain_path: str,
    footprints_path: str,
    precision: int,
) -> dict:
    return {
        "schema_version": "0.1",
        "skill": "mine-3d-modeling",
        "generator": GENERATOR,
        "units": "UNKNOWN",
        "crs": "UNKNOWN",
        "axis_convention": {
            "source": "Z_UP",
            "obj": "Z_UP",
            "glb": "Y_UP",
            "glb_mapping": GLB_AXIS_MAPPING,
        },
        "source": {
            "terrain_obj": common.source_manifest(terrain_path),
            "footprints_csv": common.source_manifest(footprints_path),
        },
        "options": {
            "obj_precision": precision,
            "footprint_base_z": (
                "explicit base_z/z column when present, otherwise the nearest "
                "terrain vertex (XY distance)"
            ),
            "rotation": "degrees counter-clockwise around +Z",
        },
        "terrain": {
            "vertex_count": terrain["vertex_count"],
            "face_count": terrain["face_count"],
            "orphan_vertex_count": terrain["orphan_vertex_count"],
            "bounds": terrain["bounds"],
            "input_stats": terrain["stats"],
        },
        "footprints": scene["footprints"],
        "merged": {
            "vertex_count": len(scene["vertices"]),
            "face_count": len(scene["faces"]),
            "triangle_count": len(scene["faces"]),
            "bounds": scene["bounds"],
        },
        "glb": glb_meta,
        "outputs": {
            "obj": "model.obj",
            "glb": "model.glb",
            "manifest": "model_manifest.json",
            "report_json": "modeling_report.json",
            "report_markdown": "modeling_report.md",
        },
        "warnings": scene["warnings"],
        "limitations": [
            "Terrain must be supplied as OBJ; DEM/TIN raster inputs are not converted.",
            "Footprints become boxes only; roads, pit benches, slopes, textures and LOD are not modeled.",
            "Boxes are not clipped to the terrain surface; base elevation is a single value per footprint.",
            "Source normals, UVs, materials and other OBJ metadata are not preserved.",
            "No CRS or unit conversion is applied; the model is not georeferenced.",
            "GLB positions are float32; large mine coordinates lose precision "
            "(about 0.01 m at 1e5 and 0.25 m at 4e6). Recenter or use a "
            "dedicated RTC/georeferencing transform for survey-grade work.",
        ],
    }


def render_markdown(manifest: dict) -> str:
    terrain = manifest["terrain"]
    merged = manifest["merged"]
    glb = manifest["glb"]
    lines = [
        "# Mine 3D Modeling Report",
        "",
        "## Summary",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Terrain vertices / triangles | {terrain['vertex_count']} / {terrain['face_count']} |",
        f"| Footprint boxes | {len(manifest['footprints'])} |",
        f"| Merged vertices / triangles | {merged['vertex_count']} / {merged['triangle_count']} |",
        f"| GLB size | {glb['file_size_bytes']} bytes |",
        f"| Axis convention | source Z-up, GLB Y-up (`{manifest['axis_convention']['glb_mapping']}`) |",
        f"| Units / CRS | {manifest['units']} / {manifest['crs']} |",
        "",
        "## Footprints",
        "",
    ]
    if manifest["footprints"]:
        lines.extend(
            [
                "| id | centre x, y | base z | width × depth × height | rotation | base source |",
                "|---|---|---:|---|---:|---|",
            ]
        )
        for footprint in manifest["footprints"]:
            lines.append(
                f"| {footprint['id']} | "
                f"{common.fmt(footprint['x'])}, {common.fmt(footprint['y'])} | "
                f"{common.fmt(footprint['base_z'])} | "
                f"{common.fmt(footprint['width'])} × "
                f"{common.fmt(footprint['depth'])} × "
                f"{common.fmt(footprint['height'])} | "
                f"{common.fmt(footprint['rotation_deg'])}° | "
                f"{footprint['base_z_source']} |"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Warnings", ""])
    if manifest["warnings"]:
        lines.extend(f"- {warning}" for warning in manifest["warnings"])
    else:
        lines.append("- None")

    lines.extend(["", "## v0.1 limitations", ""])
    lines.extend(f"- {item}" for item in manifest["limitations"])
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge terrain OBJ geometry with footprint boxes and export OBJ/GLB."
    )
    parser.add_argument("terrain_obj", help="Terrain OBJ file (Z-up)")
    parser.add_argument("footprints_csv", help="Footprint CSV file")
    parser.add_argument("--out-dir", default="model_output", help="Output directory")
    parser.add_argument(
        "--precision", type=int, default=6, help="Decimal places written to the merged OBJ"
    )
    args = parser.parse_args(argv)
    if args.precision < 0 or args.precision > 12:
        raise SystemExit("--precision must be between 0 and 12")

    terrain = read_obj(args.terrain_obj)
    footprint_data = read_footprints(args.footprints_csv)
    scene = build_scene(terrain, footprint_data)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    obj_path = str(out / "model.obj")
    glb_path = str(out / "model.glb")
    write_obj(obj_path, scene, precision=args.precision)
    glb_meta = write_glb(glb_path, scene["vertices"], scene["faces"])
    if glb_meta["position_abs_max"] > 1e5:
        scene["warnings"].append(
            "GLB positions are float32 and the maximum absolute coordinate is "
            f"{common.fmt(glb_meta['position_abs_max'], 3)}; sub-decimetre "
            "precision may be lost. Recenter the model or add an RTC/georeferencing "
            "transform before survey-grade use."
        )

    manifest = build_manifest(
        scene,
        terrain,
        glb_meta,
        args.terrain_obj,
        args.footprints_csv,
        args.precision,
    )
    report = {
        "status": "ok",
        "manifest": manifest,
        "warnings": scene["warnings"],
        "limitations": manifest["limitations"],
    }
    common.write_json(str(out / "model_manifest.json"), manifest)
    common.write_json(str(out / "modeling_report.json"), report)
    common.write_text(str(out / "modeling_report.md"), render_markdown(manifest))

    print(
        f"Merged {terrain['vertex_count']} terrain vertices and "
        f"{len(scene['footprints'])} footprint box(es) into "
        f"{len(scene['vertices'])} vertices / {len(scene['faces'])} triangles."
    )
    print(f"GLB: {glb_meta['file_size_bytes']} bytes, {glb_meta['triangle_count']} triangles.")
    print(
        "Outputs: "
        + ", ".join(
            [
                obj_path,
                glb_path,
                str(out / "model_manifest.json"),
                str(out / "modeling_report.json"),
                str(out / "modeling_report.md"),
            ]
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
