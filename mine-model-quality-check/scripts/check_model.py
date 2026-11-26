#!/usr/bin/env python3
"""Independently validate an OBJ mesh and optional registration accuracy.

Checks in v0.1:

* duplicate vertices (rounded coordinates)
* degenerate triangles
* boundary and non-manifold edges
* boundary loop / hole counts
* signed volume and normal orientation for closed meshes
* bounding box and Z range
* registration RMSE against an explicit threshold

The checker is read-only. It never repairs the model and reports every
unknown explicitly. Exit code is 1 on FAIL unless ``--no-fail`` is given.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - environment dependent
    raise SystemExit(
        "numpy is required. Install it with:\n"
        "  python3 -m pip install -r requirements.txt"
    ) from exc


DETAIL_LIMIT = 100

LIMITATIONS = [
    "v0.1 parses OBJ only; GLB, glTF and PLY are planned for a later version.",
    "Polygon faces are triangulated with a simple fan. Strongly concave "
    "polygons may be triangulated incorrectly.",
    "Duplicate vertices are detected from rounded positions only; UV, normal "
    "and material seams are not considered.",
    "Signed volume validates net orientation only. Mixed or locally inverted "
    "faces on a closed mesh may not be detected; self-intersections are not "
    "checked.",
    "Boundary loops are interpreted as holes only for closed meshes. Open "
    "surfaces such as terrain have legitimate outer boundaries; use "
    "--allow-boundary for those models.",
    "Units and CRS are unknown and are never inferred. Area and volume values "
    "are expressed in source units.",
    "Only one model is checked per run; overlapping models and coordinate "
    "offset between models are not evaluated.",
    "The checker never repairs the model or writes changes to it.",
]


def file_sha256(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    return {
        "path": str(p.resolve()),
        "name": p.name,
        "size_bytes": p.stat().st_size,
        "sha256": file_sha256(p),
    }


def write_json(path: str | Path, data: Any) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_text(path: str | Path, text: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def fmt(value: float | int | None, digits: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        if value != 0.0 and abs(value) < 10 ** (-digits):
            return f"{value:.2e}"
        return f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def read_obj_text(path: str, encoding: str | None = None) -> tuple[str, str]:
    encodings = [encoding] if encoding else ["utf-8-sig", "utf-8", "gbk", "latin-1"]
    for enc in encodings:
        if not enc:
            continue
        try:
            return Path(path).read_text(encoding=enc), enc
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"Unable to decode OBJ file: {path}")


def parse_obj(path: str) -> dict:
    """Parse OBJ vertices and faces, fan-triangulating polygon faces."""
    text, encoding = read_obj_text(path)
    vertices: list[list[float]] = []
    polygons: list[dict] = []
    warnings: list[str] = []

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        keyword = parts[0].lower()
        if keyword == "v":
            if len(parts) < 4:
                warnings.append(
                    f"Line {lineno}: vertex with fewer than 3 coordinates ignored."
                )
                continue
            try:
                coordinates = [float(parts[1]), float(parts[2]), float(parts[3])]
            except ValueError:
                warnings.append(
                    f"Line {lineno}: non-numeric vertex coordinate ignored."
                )
                continue
            if not all(math.isfinite(value) for value in coordinates):
                warnings.append(
                    f"Line {lineno}: non-finite vertex coordinate retained for "
                    "reporting; affected checks will be UNKNOWN or FAIL."
                )
            vertices.append(coordinates)
        elif keyword == "f":
            polygon = {
                "line": lineno,
                "indices": [],
                "valid": True,
                "reason": "",
            }
            if len(parts) < 4:
                polygon["valid"] = False
                polygon["reason"] = "fewer than 3 vertex references"
                polygons.append(polygon)
                continue
            for token in parts[1:]:
                head = token.split("/")[0]
                if not head:
                    polygon["valid"] = False
                    polygon["reason"] = "missing vertex index"
                    break
                try:
                    value = int(head)
                except ValueError:
                    polygon["valid"] = False
                    polygon["reason"] = f"non-integer vertex index {token!r}"
                    break
                if value == 0:
                    polygon["valid"] = False
                    polygon["reason"] = "vertex index 0 is invalid in OBJ"
                    break
                if value < 0:
                    value = len(vertices) + value
                else:
                    value -= 1
                polygon["indices"].append(value)
            polygons.append(polygon)

    vertex_count = len(vertices)
    triangles: list[list[int]] = []
    triangle_lines: list[int] = []
    invalid_faces: list[dict] = []
    polygon_vertex_counts: Counter[int] = Counter()

    for polygon in polygons:
        indices = polygon["indices"]
        polygon_vertex_counts[len(indices)] += 1
        if not polygon["valid"]:
            invalid_faces.append(
                {
                    "obj_line": polygon["line"],
                    "reason": polygon["reason"],
                    "vertex_indices": [index + 1 for index in indices],
                }
            )
            continue
        out_of_range = [
            index for index in indices if index < 0 or index >= vertex_count
        ]
        if out_of_range:
            invalid_faces.append(
                {
                    "obj_line": polygon["line"],
                    "reason": "vertex index out of range",
                    "vertex_indices": [index + 1 for index in indices],
                    "invalid_indices": [
                        index + 1 if index >= 0 else index for index in out_of_range
                    ],
                }
            )
            continue
        for offset in range(1, len(indices) - 1):
            triangles.append([indices[0], indices[offset], indices[offset + 1]])
            triangle_lines.append(polygon["line"])

    return {
        "vertices": np.asarray(vertices, dtype=float).reshape(-1, 3),
        "faces": np.asarray(triangles, dtype=np.int64).reshape(-1, 3),
        "face_lines": np.asarray(triangle_lines, dtype=np.int64),
        "polygon_count": len(polygons),
        "polygon_vertex_counts": dict(sorted(polygon_vertex_counts.items())),
        "invalid_faces": invalid_faces,
        "warnings": warnings,
        "encoding": encoding,
    }


def analyze_duplicates(vertices: np.ndarray, decimals: int) -> dict:
    if len(vertices) == 0:
        return {
            "duplicate_vertex_count": 0,
            "duplicate_vertex_group_count": 0,
            "groups": [],
        }
    rounded = np.round(vertices, decimals)
    groups: dict[tuple, list[int]] = {}
    for index, key in enumerate(map(tuple, rounded.tolist())):
        groups.setdefault(key, []).append(index)
    duplicates = [
        {
            "vertex_indices": [index + 1 for index in indexes],
            "coordinates": [float(value) for value in coordinates],
            "count": len(indexes),
        }
        for coordinates, indexes in groups.items()
        if len(indexes) > 1
    ]
    duplicates.sort(key=lambda group: group["vertex_indices"][0])
    return {
        "duplicate_vertex_count": sum(group["count"] - 1 for group in duplicates),
        "duplicate_vertex_group_count": len(duplicates),
        "groups": duplicates,
    }


def trace_boundary_loops(boundary_edges: np.ndarray) -> tuple[list[dict], list[dict]]:
    """Trace boundary edges into closed loops and open chains."""
    adjacency: dict[int, list[int]] = defaultdict(list)
    edge_set: set[tuple[int, int]] = set()
    for edge in boundary_edges:
        u, v = int(edge[0]), int(edge[1])
        if u == v:
            continue
        key = (min(u, v), max(u, v))
        edge_set.add(key)
        adjacency[u].append(v)
        adjacency[v].append(u)
    for node in adjacency:
        adjacency[node].sort()

    visited: set[tuple[int, int]] = set()

    def walk(start: int) -> list[int]:
        path = [start]
        while True:
            current = path[-1]
            candidates = [
                neighbor
                for neighbor in adjacency[current]
                if (min(current, neighbor), max(current, neighbor)) not in visited
            ]
            if not candidates:
                break
            nxt = candidates[0]
            visited.add((min(current, nxt), max(current, nxt)))
            path.append(nxt)
            if nxt == path[0]:
                break
        return path

    closed_loops: list[dict] = []
    open_chains: list[dict] = []
    for edge in sorted(edge_set):
        if edge in visited:
            continue
        u, v = edge
        visited.add(edge)
        path = [u] + walk(v)
        if path[-1] != path[0]:
            backward = walk(u)
            path = list(reversed(backward)) + path[1:]
        if len(path) >= 2 and path[-1] == path[0]:
            closed_loops.append(
                {
                    "edge_count": len(path) - 1,
                    "vertex_count": len(path) - 1,
                    "vertices": [index + 1 for index in path[:-1]],
                }
            )
        else:
            open_chains.append(
                {
                    "edge_count": len(path) - 1,
                    "vertex_count": len(path),
                    "vertices": [index + 1 for index in path],
                }
            )
    return closed_loops, open_chains


def analyze_topology(faces: np.ndarray, vertex_count: int) -> dict:
    if len(faces) == 0:
        return {
            "edge_count": 0,
            "boundary_edge_count": 0,
            "non_manifold_edge_count": 0,
            "boundary_loops": [],
            "open_boundary_chains": [],
            "boundary_loop_count": 0,
            "open_boundary_chain_count": 0,
            "hole_count": 0,
            "boundary_vertex_degree_gt_2_count": 0,
            "closed": False,
            "non_manifold_edges": [],
        }

    edges = np.concatenate(
        [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=0
    )
    edges = np.sort(edges, axis=1)
    edges = edges[edges[:, 0] != edges[:, 1]]
    unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    boundary_edges = unique_edges[counts == 1]
    non_manifold_mask = counts > 2
    non_manifold_edges = unique_edges[non_manifold_mask]
    non_manifold_counts = counts[non_manifold_mask]

    closed_loops, open_chains = trace_boundary_loops(boundary_edges)
    boundary_degrees: Counter[int] = Counter()
    for edge in boundary_edges:
        boundary_degrees[int(edge[0])] += 1
        boundary_degrees[int(edge[1])] += 1
    high_degree = sum(1 for degree in boundary_degrees.values() if degree > 2)

    non_manifold_details = [
        {
            "vertices": [int(edge[0]) + 1, int(edge[1]) + 1],
            "face_count": int(count),
        }
        for edge, count in zip(non_manifold_edges, non_manifold_counts)
    ]
    return {
        "edge_count": int(len(unique_edges)),
        "boundary_edge_count": int(len(boundary_edges)),
        "non_manifold_edge_count": int(len(non_manifold_edges)),
        "boundary_loops": closed_loops,
        "open_boundary_chains": open_chains,
        "boundary_loop_count": len(closed_loops),
        "open_boundary_chain_count": len(open_chains),
        "hole_count": len(closed_loops),
        "boundary_vertex_degree_gt_2_count": high_degree,
        "closed": bool(
            len(boundary_edges) == 0
            and len(non_manifold_edges) == 0
            and vertex_count > 0
        ),
        "non_manifold_edges": non_manifold_details,
    }


def _triangle_areas(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    if len(faces) == 0:
        return np.asarray([], dtype=float)
    a = vertices[faces[:, 0]]
    b = vertices[faces[:, 1]]
    c = vertices[faces[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)


def analyze_degenerate_triangles(
    vertices: np.ndarray,
    faces: np.ndarray,
    face_lines: np.ndarray,
    area_epsilon: float,
) -> tuple[np.ndarray, list[dict]]:
    if len(faces) == 0:
        return np.asarray([], dtype=float), []
    areas = _triangle_areas(vertices, faces)
    repeated = (
        (faces[:, 0] == faces[:, 1])
        | (faces[:, 1] == faces[:, 2])
        | (faces[:, 0] == faces[:, 2])
    )
    invalid_area = ~np.isfinite(areas)
    degenerate = repeated | invalid_area | (areas <= area_epsilon)

    details = []
    for face_index in np.nonzero(degenerate)[0]:
        if repeated[face_index]:
            reason = "repeated vertex index"
        elif invalid_area[face_index]:
            reason = "non-finite triangle area"
        else:
            reason = f"area <= {area_epsilon:g}"
        details.append(
            {
                "triangle_index": int(face_index) + 1,
                "obj_line": int(face_lines[face_index]) if len(face_lines) else None,
                "vertices": [int(index) + 1 for index in faces[face_index]],
                "area": float(areas[face_index]),
                "reason": reason,
            }
        )
    return areas, details


def analyze_geometry(
    vertices: np.ndarray, faces: np.ndarray, areas: np.ndarray, closed: bool
) -> dict:
    result: dict[str, Any] = {
        "bbox": None,
        "z_range": None,
        "non_finite_vertex_count": 0,
        "triangle_area_total": float(areas.sum()) if len(areas) else 0.0,
        "signed_volume": None,
        "absolute_volume": None,
        "orientation": "UNKNOWN",
        "orientation_note": "Mesh is not closed; signed volume is not meaningful.",
    }
    if len(vertices) == 0:
        result["orientation_note"] = "Mesh has no vertices."
        return result

    finite_mask = np.all(np.isfinite(vertices), axis=1)
    non_finite = int(np.count_nonzero(~finite_mask))
    result["non_finite_vertex_count"] = non_finite
    finite_vertices = vertices[finite_mask]
    if len(finite_vertices):
        result["bbox"] = {
            "min_x": float(finite_vertices[:, 0].min()),
            "max_x": float(finite_vertices[:, 0].max()),
            "min_y": float(finite_vertices[:, 1].min()),
            "max_y": float(finite_vertices[:, 1].max()),
            "min_z": float(finite_vertices[:, 2].min()),
            "max_z": float(finite_vertices[:, 2].max()),
            "span_x": float(
                finite_vertices[:, 0].max() - finite_vertices[:, 0].min()
            ),
            "span_y": float(
                finite_vertices[:, 1].max() - finite_vertices[:, 1].min()
            ),
            "span_z": float(
                finite_vertices[:, 2].max() - finite_vertices[:, 2].min()
            ),
        }
        result["z_range"] = {
            "min": result["bbox"]["min_z"],
            "max": result["bbox"]["max_z"],
            "span": result["bbox"]["span_z"],
        }

    if len(faces):
        triangles = vertices[faces]
        if not np.all(np.isfinite(triangles)):
            result["orientation_note"] = (
                "Mesh has non-finite coordinates; volume was not computed."
            )
            return result
        volume_terms = np.einsum(
            "ij,ij->i", triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])
        )
        signed_volume = float(volume_terms.sum() / 6.0)
        result["signed_volume"] = signed_volume
        result["absolute_volume"] = abs(signed_volume)
        if closed:
            if signed_volume > 0:
                result["orientation"] = "OUTWARD"
                result["orientation_note"] = (
                    "Positive signed volume under the right-hand rule."
                )
            elif signed_volume < 0:
                result["orientation"] = "INWARD"
                result["orientation_note"] = (
                    "Negative signed volume: face winding is likely inverted."
                )
            else:
                result["orientation"] = "ZERO"
                result["orientation_note"] = (
                    "Signed volume is zero; orientation cannot be established."
                )
        else:
            result["orientation_note"] = (
                "Mesh is not closed; signed volume is reported but orientation "
                "cannot be verified."
            )
    return result


def _find_number(payload: Any, key: str) -> float | None:
    if not isinstance(payload, dict):
        return None
    for section in ("diagnostics", "parameters"):
        nested = payload.get(section)
        if isinstance(nested, dict) and key in nested:
            value = nested[key]
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return float(value)
    value = payload.get(key)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def load_registration_report(path: str, max_rmse: float) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Unable to read registration report {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("Registration report must be a JSON object")

    rmse = _find_number(payload, "rmse")
    max_residual = _find_number(payload, "max_residual")
    source_crs = None
    target_crs = None
    parameters = payload.get("parameters")
    if isinstance(parameters, dict):
        source_crs = parameters.get("source_crs")
        target_crs = parameters.get("target_crs")
    source_crs = payload.get("source_crs", source_crs)
    target_crs = payload.get("target_crs", target_crs)

    if rmse is None:
        status = "UNKNOWN"
        summary = "Registration report has no numeric RMSE field."
    elif rmse <= max_rmse:
        status = "PASS"
        summary = f"Registration RMSE {fmt(rmse, 6)} <= {fmt(max_rmse, 6)}."
    else:
        status = "FAIL"
        summary = f"Registration RMSE {fmt(rmse, 6)} > {fmt(max_rmse, 6)}."

    return {
        "file": Path(path).name,
        "source": source_manifest(path),
        "rmse": rmse,
        "max_residual": max_residual,
        "max_rmse": max_rmse,
        "source_crs": source_crs,
        "target_crs": target_crs,
        "status": status,
        "summary": summary,
    }


def _check(
    check_id: str,
    status: str,
    summary: str,
    value: Any = None,
    threshold: Any = None,
) -> dict:
    return {
        "id": check_id,
        "status": status,
        "summary": summary,
        "value": value,
        "threshold": threshold,
    }


def run_checks(
    model_path: str,
    expect_closed: bool = True,
    round_decimals: int = 6,
    area_epsilon: float = 1e-12,
    registration_path: str | None = None,
    max_rmse: float | None = None,
) -> dict:
    if round_decimals < 0:
        raise SystemExit("--round-decimals must be 0 or greater")
    if area_epsilon < 0:
        raise SystemExit("--area-epsilon must be 0 or greater")
    if registration_path and max_rmse is None:
        raise SystemExit("--max-rmse is required when --registration is provided")
    if max_rmse is not None and max_rmse <= 0:
        raise SystemExit("--max-rmse must be greater than 0")

    parsed = parse_obj(model_path)
    vertices = parsed["vertices"]
    faces = parsed["faces"]
    warnings = list(parsed["warnings"])
    duplicates = analyze_duplicates(vertices, round_decimals)
    areas, degenerate = analyze_degenerate_triangles(
        vertices, faces, parsed["face_lines"], area_epsilon
    )
    topology = analyze_topology(faces, len(vertices))
    geometry = analyze_geometry(vertices, faces, areas, topology["closed"])
    invalid_faces = parsed["invalid_faces"]
    face_count = len(faces)

    checks: list[dict] = []
    if len(vertices) == 0:
        checks.append(_check("vertices_present", "FAIL", "Model has no vertices."))
    else:
        checks.append(
            _check(
                "vertices_present",
                "PASS",
                f"{len(vertices)} vertices parsed.",
                value=len(vertices),
            )
        )

    if len(vertices) == 0:
        duplicate_status = "UNKNOWN"
        duplicate_summary = "No vertices to compare."
    elif duplicates["duplicate_vertex_count"]:
        duplicate_status = "FAIL"
        duplicate_summary = (
            f"{duplicates['duplicate_vertex_count']} duplicate vertex/vertices "
            f"in {duplicates['duplicate_vertex_group_count']} group(s) at "
            f"{round_decimals} decimals."
        )
    else:
        duplicate_status = "PASS"
        duplicate_summary = "No duplicate vertices at the chosen rounding."
    checks.append(
        _check(
            "duplicate_vertices",
            duplicate_status,
            duplicate_summary,
            value=duplicates["duplicate_vertex_count"],
            threshold=0,
        )
    )

    if face_count == 0:
        checks.append(
            _check(
                "degenerate_triangles",
                "UNKNOWN",
                "Model has no valid triangles.",
                value=0,
                threshold=0,
            )
        )
        checks.append(
            _check(
                "non_manifold_edges",
                "UNKNOWN",
                "Model has no valid triangles.",
                value=0,
                threshold=0,
            )
        )
        boundary_status = "UNKNOWN"
        boundary_summary = "Model has no valid triangles."
    else:
        checks.append(
            _check(
                "degenerate_triangles",
                "PASS" if not degenerate else "FAIL",
                (
                    "No degenerate triangles."
                    if not degenerate
                    else f"{len(degenerate)} degenerate triangle(s) found "
                    f"(area <= {area_epsilon:g} or repeated vertices)."
                ),
                value=len(degenerate),
                threshold=0,
            )
        )
        checks.append(
            _check(
                "non_manifold_edges",
                "PASS" if topology["non_manifold_edge_count"] == 0 else "FAIL",
                (
                    "No non-manifold edges."
                    if topology["non_manifold_edge_count"] == 0
                    else f"{topology['non_manifold_edge_count']} edge(s) are "
                    "shared by more than 2 faces."
                ),
                value=topology["non_manifold_edge_count"],
                threshold=0,
            )
        )
        if expect_closed:
            boundary_status = (
                "PASS" if topology["boundary_edge_count"] == 0 else "FAIL"
            )
            boundary_summary = (
                "Mesh has no boundary edges."
                if topology["boundary_edge_count"] == 0
                else f"{topology['boundary_edge_count']} boundary edge(s) in "
                f"{topology['boundary_loop_count']} loop(s) and "
                f"{topology['open_boundary_chain_count']} open chain(s) "
                "(closed mesh expected)."
            )
        else:
            boundary_status = "PASS"
            boundary_summary = (
                f"{topology['boundary_edge_count']} boundary edge(s) in "
                f"{topology['boundary_loop_count']} loop(s) and "
                f"{topology['open_boundary_chain_count']} open chain(s); "
                "allowed by --allow-boundary."
            )
    checks.append(
        _check(
            "boundary",
            boundary_status,
            boundary_summary,
            value=topology["boundary_edge_count"],
            threshold=0 if expect_closed else None,
        )
    )

    if face_count == 0:
        orientation_status = "UNKNOWN"
        orientation_summary = "Model has no valid triangles."
    elif topology["closed"]:
        orientation_status = (
            "PASS" if geometry["orientation"] == "OUTWARD" else "FAIL"
        )
        orientation_summary = (
            f"Closed mesh signed volume {fmt(geometry['signed_volume'], 6)}; "
            f"orientation {geometry['orientation']}."
        )
    else:
        orientation_status = "UNKNOWN"
        orientation_summary = (
            "Mesh is not closed; normal orientation and signed volume could "
            "not be verified."
        )
    checks.append(
        _check(
            "orientation",
            orientation_status,
            orientation_summary,
            value=geometry["orientation"],
        )
    )

    if parsed["polygon_count"] == 0:
        faces_status = "UNKNOWN"
        faces_summary = "OBJ contains no face elements."
    else:
        faces_status = "PASS" if not invalid_faces else "FAIL"
        faces_summary = (
            "All face references are valid."
            if not invalid_faces
            else f"{len(invalid_faces)} face element(s) could not be parsed or "
            "reference out-of-range vertices."
        )
    checks.append(
        _check(
            "face_indices",
            faces_status,
            faces_summary,
            value=len(invalid_faces),
            threshold=0,
        )
    )

    if len(vertices) == 0 or geometry["non_finite_vertex_count"]:
        extent_status = "FAIL"
        extent_summary = (
            "Model has no vertices."
            if len(vertices) == 0
            else f"{geometry['non_finite_vertex_count']} vertex/vertices have "
            "non-finite coordinates."
        )
    else:
        extent_status = "PASS"
        extent_summary = (
            "All vertices are finite and have a computable bounding box."
        )
    checks.append(
        _check(
            "coordinate_extent",
            extent_status,
            extent_summary,
            value=geometry["non_finite_vertex_count"],
            threshold=0,
        )
    )

    registration = None
    if registration_path:
        registration = load_registration_report(registration_path, float(max_rmse))
        checks.append(
            _check(
                "registration_rmse",
                registration["status"],
                registration["summary"],
                value=registration["rmse"],
                threshold=registration["max_rmse"],
            )
        )

    if invalid_faces:
        warnings.append(
            f"{len(invalid_faces)} face element(s) were excluded from topology "
            "checks; see invalid_faces."
        )
    if topology["boundary_vertex_degree_gt_2_count"]:
        warnings.append(
            f"{topology['boundary_vertex_degree_gt_2_count']} boundary vertex/vertices "
            "have degree greater than 2; boundary loops may be approximate."
        )
    if face_count and not topology["closed"]:
        warnings.append(
            "Mesh is not closed. Signed volume and orientation are reported as "
            "UNKNOWN; use --allow-boundary only for legitimately open surfaces."
        )
    if duplicates["duplicate_vertex_count"]:
        warnings.append(
            f"{duplicates['duplicate_vertex_count']} duplicate vertex/vertices "
            "detected; the checker does not merge or repair them."
        )
    if degenerate:
        warnings.append(
            f"{len(degenerate)} degenerate triangle(s) detected; they are not "
            "repaired automatically."
        )
    if geometry["non_finite_vertex_count"]:
        warnings.append(
            "Non-finite vertex coordinates are present; volume and extent checks "
            "may be incomplete."
        )

    checks_statuses = [check["status"] for check in checks]
    if "FAIL" in checks_statuses:
        overall = "FAIL"
    elif "UNKNOWN" in checks_statuses:
        overall = "UNKNOWN"
    else:
        overall = "PASS"

    detail_categories = {
        "duplicate_vertex_groups": duplicates["groups"],
        "degenerate_triangles": degenerate,
        "non_manifold_edges": topology["non_manifold_edges"],
        "boundary_loops": topology["boundary_loops"],
        "open_boundary_chains": topology["open_boundary_chains"],
        "invalid_faces": invalid_faces,
    }
    details_truncated = {
        name: len(items) > DETAIL_LIMIT for name, items in detail_categories.items()
    }
    if any(details_truncated.values()):
        warnings.append(
            f"Some issue details are truncated to the first {DETAIL_LIMIT} "
            "entries; counts in metrics are complete."
        )

    referenced = int(len(np.unique(faces))) if face_count else 0
    reproduction = [
        "python3 scripts/check_model.py",
        f'"{model_path}"',
        "--round-decimals",
        str(round_decimals),
        "--area-epsilon",
        repr(area_epsilon),
    ]
    if not expect_closed:
        reproduction.append("--allow-boundary")
    if registration_path:
        reproduction.extend(
            ["--registration", f'"{registration_path}"', "--max-rmse", repr(max_rmse)]
        )

    report = {
        "file": Path(model_path).name,
        "source": source_manifest(model_path),
        "format": "OBJ",
        "encoding": parsed["encoding"],
        "units": "UNKNOWN",
        "crs": "UNKNOWN",
        "status": overall,
        "options": {
            "expect_closed": expect_closed,
            "round_decimals": round_decimals,
            "area_epsilon": area_epsilon,
            "registration_report": registration_path,
            "max_rmse": max_rmse,
        },
        "metrics": {
            "vertex_count": int(len(vertices)),
            "referenced_vertex_count": referenced,
            "source_polygon_count": parsed["polygon_count"],
            "polygon_vertex_counts": parsed["polygon_vertex_counts"],
            "triangle_count": face_count,
            "edge_count": topology["edge_count"],
            "boundary_edge_count": topology["boundary_edge_count"],
            "non_manifold_edge_count": topology["non_manifold_edge_count"],
            "boundary_loop_count": topology["boundary_loop_count"],
            "open_boundary_chain_count": topology["open_boundary_chain_count"],
            "hole_count": topology["hole_count"],
            "boundary_vertex_degree_gt_2_count": topology[
                "boundary_vertex_degree_gt_2_count"
            ],
            "closed": topology["closed"],
            "duplicate_vertex_count": duplicates["duplicate_vertex_count"],
            "duplicate_vertex_group_count": duplicates[
                "duplicate_vertex_group_count"
            ],
            "degenerate_triangle_count": len(degenerate),
            "invalid_face_count": len(invalid_faces),
            "non_finite_vertex_count": geometry["non_finite_vertex_count"],
            "triangle_area_total": geometry["triangle_area_total"],
            "signed_volume": geometry["signed_volume"],
            "absolute_volume": geometry["absolute_volume"],
            "orientation": geometry["orientation"],
            "orientation_note": geometry["orientation_note"],
            "bbox": geometry["bbox"],
            "z_range": geometry["z_range"],
        },
        "checks": checks,
        "duplicate_vertex_groups": duplicates["groups"][:DETAIL_LIMIT],
        "degenerate_triangles": degenerate[:DETAIL_LIMIT],
        "non_manifold_edges": topology["non_manifold_edges"][:DETAIL_LIMIT],
        "boundary_loops": topology["boundary_loops"][:DETAIL_LIMIT],
        "open_boundary_chains": topology["open_boundary_chains"][:DETAIL_LIMIT],
        "invalid_faces": invalid_faces[:DETAIL_LIMIT],
        "details_truncated": details_truncated,
        "detail_limit": DETAIL_LIMIT,
        "registration": registration,
        "warnings": warnings,
        "limitations": LIMITATIONS,
        "reproduction_command": " ".join(reproduction),
    }
    return report


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value)


def write_issues_csv(path: str | Path, report: dict) -> int:
    rows: list[dict] = []
    for check in report["checks"]:
        rows.append(
            {
                "check": check["id"],
                "status": check["status"],
                "code": "CHECK",
                "message": check["summary"],
                "location": "",
                "value": _csv_value(check["value"]),
                "threshold": _csv_value(check["threshold"]),
            }
        )
    for group in report["duplicate_vertex_groups"]:
        rows.append(
            {
                "check": "duplicate_vertices",
                "status": "FAIL",
                "code": "DUPLICATE_VERTEX_GROUP",
                "message": "Vertices share rounded coordinates.",
                "location": "vertices " + ", ".join(
                    str(index) for index in group["vertex_indices"]
                ),
                "value": group["count"],
                "threshold": 1,
            }
        )
    for triangle in report["degenerate_triangles"]:
        rows.append(
            {
                "check": "degenerate_triangles",
                "status": "FAIL",
                "code": "DEGENERATE_TRIANGLE",
                "message": triangle["reason"],
                "location": f"triangle {triangle['triangle_index']} "
                f"(OBJ line {triangle['obj_line']})",
                "value": triangle["area"],
                "threshold": report["options"]["area_epsilon"],
            }
        )
    for edge in report["non_manifold_edges"]:
        rows.append(
            {
                "check": "non_manifold_edges",
                "status": "FAIL",
                "code": "NON_MANIFOLD_EDGE",
                "message": f"Edge shared by {edge['face_count']} faces.",
                "location": f"vertices {edge['vertices'][0]}-{edge['vertices'][1]}",
                "value": edge["face_count"],
                "threshold": 2,
            }
        )
    boundary_status = "FAIL" if report["options"]["expect_closed"] else "INFO"
    for loop in report["boundary_loops"]:
        rows.append(
            {
                "check": "boundary",
                "status": boundary_status,
                "code": "BOUNDARY_LOOP",
                "message": "Closed boundary loop; a hole when the mesh is expected "
                "to be closed.",
                "location": "vertices " + ", ".join(
                    str(index) for index in loop["vertices"][:20]
                ),
                "value": loop["edge_count"],
                "threshold": 0 if report["options"]["expect_closed"] else None,
            }
        )
    for chain in report["open_boundary_chains"]:
        rows.append(
            {
                "check": "boundary",
                "status": boundary_status,
                "code": "OPEN_BOUNDARY_CHAIN",
                "message": "Open boundary chain; not a closed loop.",
                "location": "vertices " + ", ".join(
                    str(index) for index in chain["vertices"][:20]
                ),
                "value": chain["edge_count"],
                "threshold": 0 if report["options"]["expect_closed"] else None,
            }
        )
    for face in report["invalid_faces"]:
        rows.append(
            {
                "check": "face_indices",
                "status": "FAIL",
                "code": "INVALID_FACE",
                "message": face["reason"],
                "location": f"OBJ line {face['obj_line']}",
                "value": "",
                "threshold": "",
            }
        )
    for warning in report["warnings"]:
        rows.append(
            {
                "check": "general",
                "status": "WARNING",
                "code": "WARNING",
                "message": warning,
                "location": "",
                "value": "",
                "threshold": "",
            }
        )

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        fieldnames = [
            "check",
            "status",
            "code",
            "message",
            "location",
            "value",
            "threshold",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def render_markdown(report: dict) -> str:
    metrics = report["metrics"]
    lines = [
        "# Model Quality Report",
        "",
        f"- **File**: `{report['file']}`",
        f"- **Format**: OBJ",
        f"- **Overall status**: **{report['status']}**",
        f"- **Vertices / triangles**: {metrics['vertex_count']} / "
        f"{metrics['triangle_count']}",
        f"- **Source polygon faces**: {metrics['source_polygon_count']}",
        f"- **Closed mesh**: {metrics['closed']}",
        f"- **Orientation**: {metrics['orientation']}",
        f"- **Units**: {report['units']} (not assumed)",
        f"- **CRS**: {report['crs']} (not assumed)",
        "",
        "## Checks",
        "",
        "| Check | Status | Summary |",
        "|---|---|---|",
    ]
    for check in report["checks"]:
        lines.append(
            f"| {check['id']} | **{check['status']}** | {check['summary']} |"
        )
    lines.extend(
        [
            "",
            "## Metrics",
            "",
            f"- **Edges**: {metrics['edge_count']}",
            f"- **Boundary edges**: {metrics['boundary_edge_count']}",
            f"- **Boundary loops (holes for closed meshes)**: "
            f"{metrics['boundary_loop_count']}",
            f"- **Open boundary chains**: {metrics['open_boundary_chain_count']}",
            f"- **Non-manifold edges**: {metrics['non_manifold_edge_count']}",
            f"- **Duplicate vertices**: {metrics['duplicate_vertex_count']} "
            f"({metrics['duplicate_vertex_group_count']} group(s))",
            f"- **Degenerate triangles**: {metrics['degenerate_triangle_count']}",
            f"- **Invalid faces**: {metrics['invalid_face_count']}",
            f"- **Signed volume**: {fmt(metrics['signed_volume'], 6)}",
            f"- **Absolute volume**: {fmt(metrics['absolute_volume'], 6)}",
        ]
    )
    if metrics["z_range"]:
        lines.append(
            f"- **Z range**: {fmt(metrics['z_range']['min'])} .. "
            f"{fmt(metrics['z_range']['max'])} "
            f"(span {fmt(metrics['z_range']['span'])})"
        )
    if metrics["bbox"]:
        bbox = metrics["bbox"]
        lines.append(
            f"- **Bounding box**: X {fmt(bbox['min_x'])} .. {fmt(bbox['max_x'])}, "
            f"Y {fmt(bbox['min_y'])} .. {fmt(bbox['max_y'])}, "
            f"Z {fmt(bbox['min_z'])} .. {fmt(bbox['max_z'])}"
        )
    lines.append("")

    registration = report.get("registration")
    if registration:
        lines.extend(
            [
                "## Registration Accuracy",
                "",
                f"- **Report**: `{registration['file']}`",
                f"- **RMSE**: {fmt(registration['rmse'], 6)}",
                f"- **Max residual**: {fmt(registration['max_residual'], 6)}",
                f"- **Threshold (max RMSE)**: {fmt(registration['max_rmse'], 6)}",
                f"- **Status**: **{registration['status']}**",
                "",
            ]
        )

    lines.extend(["## Issues", ""])
    issue_sections = [
        ("Duplicate vertices", report["duplicate_vertex_groups"]),
        ("Degenerate triangles", report["degenerate_triangles"]),
        ("Non-manifold edges", report["non_manifold_edges"]),
        ("Boundary loops", report["boundary_loops"]),
        ("Open boundary chains", report["open_boundary_chains"]),
        ("Invalid faces", report["invalid_faces"]),
    ]
    found = False
    for title, items in issue_sections:
        if not items:
            continue
        found = True
        lines.append(f"### {title} ({len(items)})")
        lines.append("")
        for item in items[:20]:
            if title == "Duplicate vertices":
                lines.append(
                    f"- vertices {', '.join(str(i) for i in item['vertex_indices'])} "
                    f"at {item['coordinates']}"
                )
            elif title == "Degenerate triangles":
                lines.append(
                    f"- triangle {item['triangle_index']} (OBJ line "
                    f"{item['obj_line']}): {item['reason']}, area {fmt(item['area'], 12)}"
                )
            elif title == "Non-manifold edges":
                lines.append(
                    f"- edge {item['vertices'][0]}-{item['vertices'][1]} shared by "
                    f"{item['face_count']} faces"
                )
            elif title in {"Boundary loops", "Open boundary chains"}:
                lines.append(
                    f"- {item['edge_count']} edges: "
                    f"{', '.join(str(i) for i in item['vertices'][:20])}"
                )
            elif title == "Invalid faces":
                lines.append(
                    f"- OBJ line {item['obj_line']}: {item['reason']}"
                )
        if len(items) > 20:
            lines.append(f"- ... {len(items) - 20} more (see JSON/CSV)")
        lines.append("")
    if not found:
        lines.extend(["- None", ""])

    lines.extend(["## Warnings", ""])
    if report["warnings"]:
        lines.extend(f"- {warning}" for warning in report["warnings"])
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Limitations (v0.1)",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(
        [
            "",
            "## Reproduce",
            "",
            f"`{report['reproduction_command']}`",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: dict, out_dir: str | Path) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "report_json": str(out / "quality_report.json"),
        "report_md": str(out / "quality_report.md"),
        "issues_csv": str(out / "issues.csv"),
    }
    write_json(paths["report_json"], report)
    write_text(paths["report_md"], render_markdown(report))
    write_issues_csv(paths["issues_csv"], report)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check OBJ mesh topology, geometry orientation and registration accuracy."
    )
    parser.add_argument("model", help="OBJ mesh file")
    parser.add_argument("--out-dir", default="quality_output")
    parser.add_argument(
        "--allow-boundary",
        dest="expect_closed",
        action="store_false",
        help="Allow boundary edges (use for open terrain surfaces)",
    )
    parser.add_argument("--round-decimals", type=int, default=6)
    parser.add_argument("--area-epsilon", type=float, default=1e-12)
    parser.add_argument("--registration", help="Registration report JSON")
    parser.add_argument("--max-rmse", type=float, help="Maximum acceptable RMSE")
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0, even when the overall status is FAIL",
    )
    parser.set_defaults(expect_closed=True)
    args = parser.parse_args(argv)

    report = run_checks(
        args.model,
        expect_closed=args.expect_closed,
        round_decimals=args.round_decimals,
        area_epsilon=args.area_epsilon,
        registration_path=args.registration,
        max_rmse=args.max_rmse,
    )
    paths = write_outputs(report, args.out_dir)

    metrics = report["metrics"]
    print(
        f"Status {report['status']}: {metrics['vertex_count']} vertices, "
        f"{metrics['triangle_count']} triangles, "
        f"{metrics['boundary_edge_count']} boundary edges, "
        f"{metrics['non_manifold_edge_count']} non-manifold edges, "
        f"orientation {metrics['orientation']}"
    )
    print("Outputs: " + ", ".join(paths.values()))
    if report["status"] == "FAIL" and not args.no_fail:
        print("Quality check FAILED (use --no-fail to exit 0).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
