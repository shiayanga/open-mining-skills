#!/usr/bin/env python3
"""Build a Delaunay TIN, DEM and OBJ mesh from mine survey XYZ points.

v0.1 implements unconstrained Delaunay triangulation of scattered survey
points, an ESRI ASCII DEM sampled from the survey points, and optional
elevation checks against independent check points. Breakline-constrained
triangulation, contour handling and bench/crest/toe preservation are NOT
implemented in this version.

The tool never assumes units or a CRS, never modifies the source file, and
preserves the original X, Y and Z values in the TIN and OBJ export.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

try:
    import numpy as np
    from scipy.interpolate import LinearNDInterpolator, griddata
    from scipy.spatial import Delaunay, QhullError
except ImportError as exc:  # pragma: no cover - environment dependent
    raise SystemExit(
        "numpy and scipy are required. Install them with:\n"
        "  python3 -m pip install -r requirements.txt"
    ) from exc


X_NAMES = {"x", "easting", "east", "东坐标", "x坐标"}
Y_NAMES = {"y", "northing", "north", "北坐标", "y坐标"}
Z_NAMES = {"z", "elevation", "elev", "height", "高程", "z坐标"}

MAX_DEM_CELLS = 25_000_000
NODATA_VALUE = -9999.0

LIMITATIONS = [
    "The Delaunay TIN is unconstrained: breaklines, contours, pit limits and "
    "bench edges are not enforced in v0.1.",
    "Bench, crest and toe preservation is NOT implemented. A plain TIN can "
    "smooth or bridge sharp mining steps.",
    "No spike removal, contour extraction or boundary clipping is performed. "
    "Only exact duplicate points are removed.",
    "Units and coordinate reference systems are never inferred; every output "
    "carries UNKNOWN labels.",
    "Linear DEM nodes outside the TIN convex hull are NoData; the tool does "
    "not extrapolate.",
    "Check points outside the TIN convex hull are excluded from the elevation "
    "statistics.",
    "The DEM is ESRI ASCII, not GeoTIFF. The OBJ mesh contains geometry only "
    "(no CRS, units or normals).",
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


def read_text(path: str, encoding: str | None = None) -> tuple[str, str]:
    encodings = [encoding] if encoding else ["utf-8-sig", "utf-8", "gbk", "latin-1"]
    for enc in encodings:
        if not enc:
            continue
        try:
            return Path(path).read_text(encoding=enc), enc
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"Unable to decode file: {path}")


def detect_delimiter(lines: list[str]) -> str | None:
    candidates = {",": 0, ";": 0, "\t": 0}
    for line in lines:
        for delimiter in candidates:
            candidates[delimiter] += line.count(delimiter)
    best = max(candidates, key=candidates.get)
    return best if candidates[best] > 0 else None


def split_line(line: str, delimiter: str | None) -> list[str]:
    if delimiter is None:
        return line.split()
    return [part.strip() for part in line.split(delimiter)]


def is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def _find_column(header: list[str], names: set[str]) -> int | None:
    for index, name in enumerate(header):
        if name.strip().lower() in names:
            return index + 1
    return None


def load_points(
    path: str,
    x_col: int = 1,
    y_col: int = 2,
    z_col: int = 3,
    delimiter: str | None = None,
    encoding: str | None = None,
) -> dict:
    """Read XYZ / CSV / TSV / whitespace points and report parsing metadata."""
    text, used_encoding = read_text(path, encoding)
    numbered = [
        (lineno, line.strip())
        for lineno, line in enumerate(text.splitlines(), 1)
        if line.strip() and not line.strip().startswith("#")
    ]
    if not numbered:
        raise SystemExit("File contains no data rows")

    sample = [line for _, line in numbered[:50]]
    if delimiter is None:
        delimiter = detect_delimiter(sample)
    sample_rows = [split_line(line, delimiter) for line in sample]
    has_header = any(
        any(not is_number(token) for token in row) for row in sample_rows[:5]
    )

    header: list[str] | None = None
    start = 0
    if has_header:
        header = sample_rows[0]
        found_x = _find_column(header, X_NAMES)
        found_y = _find_column(header, Y_NAMES)
        found_z = _find_column(header, Z_NAMES)
        if (
            None not in (found_x, found_y, found_z)
            and (x_col, y_col, z_col) == (1, 2, 3)
        ):
            x_col, y_col, z_col = int(found_x), int(found_y), int(found_z)
        start = 1

    points: list[list[float]] = []
    skipped: list[dict] = []
    for lineno, line in numbered[start:]:
        tokens = split_line(line, delimiter)
        try:
            values = [float(tokens[col - 1]) for col in (x_col, y_col, z_col)]
        except (ValueError, IndexError):
            skipped.append({"line": lineno, "reason": "missing or non-numeric coordinate"})
            continue
        if not all(math.isfinite(value) for value in values):
            skipped.append({"line": lineno, "reason": "non-finite coordinate"})
            continue
        points.append(values)

    if not points:
        raise SystemExit("No valid coordinate rows found")

    return {
        "points": np.asarray(points, dtype=float),
        "columns": [x_col, y_col, z_col],
        "delimiter": delimiter if delimiter is not None else "whitespace",
        "encoding": used_encoding,
        "has_header": has_header,
        "header": header,
        "skipped": skipped,
    }


def extent_of(points: np.ndarray) -> dict:
    xs, ys, zs = points[:, 0], points[:, 1], points[:, 2]
    return {
        "min_x": float(xs.min()),
        "max_x": float(xs.max()),
        "min_y": float(ys.min()),
        "max_y": float(ys.max()),
        "min_z": float(zs.min()),
        "max_z": float(zs.max()),
        "span_x": float(xs.max() - xs.min()),
        "span_y": float(ys.max() - ys.min()),
        "span_z": float(zs.max() - zs.min()),
    }


def clean_points(points: np.ndarray) -> tuple[np.ndarray, dict]:
    """Remove exact duplicates and XY conflicts so Delaunay stays valid.

    Exact 3D duplicates are dropped. A second point with the same XY but a
    different Z is also dropped and reported as a conflict, because a terrain
    surface cannot represent two elevations at the same location. The first
    occurrence in file order is kept.
    """
    seen_xyz: set[tuple[float, float, float]] = set()
    seen_xy: dict[tuple[float, float], float] = {}
    kept: list[tuple[float, float, float]] = []
    exact_duplicates = 0
    xy_conflicts: list[dict] = []

    for row in points:
        x, y, z = (float(row[0]), float(row[1]), float(row[2]))
        xyz = (x, y, z)
        if xyz in seen_xyz:
            exact_duplicates += 1
            continue
        seen_xyz.add(xyz)
        xy = (x, y)
        if xy in seen_xy:
            if len(xy_conflicts) < 10:
                xy_conflicts.append(
                    {"x": x, "y": y, "kept_z": seen_xy[xy], "skipped_z": z}
                )
            continue
        seen_xy[xy] = z
        kept.append(xyz)

    return np.asarray(kept, dtype=float), {
        "input_point_count": int(len(points)),
        "output_point_count": int(len(kept)),
        "exact_duplicates_removed": exact_duplicates,
        "xy_conflicts_removed": int(len(points) - exact_duplicates - len(kept)),
        "xy_conflict_examples": xy_conflicts,
    }


def _value_stats(values: np.ndarray, prefix: str = "") -> dict:
    if values.size == 0:
        return {}
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {}
    return {
        f"{prefix}min": float(np.min(values)),
        f"{prefix}max": float(np.max(values)),
        f"{prefix}mean": float(np.mean(values)),
        f"{prefix}median": float(np.median(values)),
        f"{prefix}std": float(np.std(values)),
        f"{prefix}p95": float(np.percentile(values, 95)),
    }


def build_tin(points: np.ndarray) -> dict:
    """Build an unconstrained Delaunay TIN and compute area/slope statistics."""
    if len(points) < 3:
        raise SystemExit(
            f"At least 3 unique XY points are required for a TIN; got {len(points)}"
        )
    try:
        triangulation = Delaunay(points[:, :2])
    except QhullError as exc:
        raise SystemExit(
            "Delaunay triangulation failed; the points may be collinear or "
            f"otherwise degenerate: {exc}"
        ) from exc

    faces = np.asarray(triangulation.simplices, dtype=np.int64)
    v0 = points[faces[:, 0]]
    v1 = points[faces[:, 1]]
    v2 = points[faces[:, 2]]
    cross = np.cross(v1 - v0, v2 - v0)

    # Qhull normally returns a consistent orientation; enforce upward-facing
    # (counter-clockwise in XY) triangles for a predictable OBJ winding.
    clockwise = cross[:, 2] < 0
    if np.any(clockwise):
        faces[clockwise] = faces[clockwise][:, [0, 2, 1]]
        cross[clockwise] *= -1.0

    area_xy = 0.5 * np.abs(cross[:, 2])
    area_3d = 0.5 * np.linalg.norm(cross, axis=1)
    keep = np.isfinite(area_3d) & (area_3d > 0.0) & (area_xy > 0.0)
    degenerate_dropped = int(np.count_nonzero(~keep))
    faces = faces[keep]
    area_xy = area_xy[keep]
    area_3d = area_3d[keep]
    cross = cross[keep]

    if len(faces) == 0:
        raise SystemExit("Delaunay produced no valid triangles (all degenerate)")

    horizontal = np.hypot(cross[:, 0], cross[:, 1])
    slope_deg = np.degrees(np.arctan2(horizontal, np.abs(cross[:, 2])))

    slope_stats = _value_stats(slope_deg, "slope_deg_")
    slope_stats["slope_deg_area_weighted_mean"] = float(
        np.average(slope_deg, weights=area_xy)
    )

    return {
        "vertices": points,
        "faces": faces,
        "degenerate_triangles_dropped": degenerate_dropped,
        "stats": {
            "vertex_count": int(len(points)),
            "triangle_count": int(len(faces)),
            "total_area_xy": float(area_xy.sum()),
            "total_area_3d": float(area_3d.sum()),
            "surface_to_planar_area_ratio": (
                float(area_3d.sum() / area_xy.sum()) if area_xy.sum() > 0 else None
            ),
            **slope_stats,
            "triangle_area_xy_min": float(area_xy.min()),
            "triangle_area_xy_max": float(area_xy.max()),
            "z_min": float(points[:, 2].min()),
            "z_max": float(points[:, 2].max()),
            "z_span": float(points[:, 2].max() - points[:, 2].min()),
        },
    }


def build_dem(points: np.ndarray, cell_size: float, method: str = "linear") -> dict:
    """Sample a square-cell DEM from the survey points.

    Grid nodes are anchored at the minimum X/Y of the data and spaced exactly
    ``cell_size`` apart. This never extrapolates beyond the data extent; any
    remainder smaller than one cell at the maximum edges is left uncovered.
    """
    if cell_size <= 0:
        raise SystemExit("--cell-size must be greater than 0")
    if method not in {"linear", "nearest"}:
        raise SystemExit(f"Unsupported DEM method: {method}")

    min_x, max_x = float(points[:, 0].min()), float(points[:, 0].max())
    min_y, max_y = float(points[:, 1].min()), float(points[:, 1].max())
    span_x, span_y = max_x - min_x, max_y - min_y
    nx = int(math.floor(span_x / cell_size + 1e-9)) + 1
    ny = int(math.floor(span_y / cell_size + 1e-9)) + 1
    nx, ny = max(nx, 1), max(ny, 1)

    if nx * ny > MAX_DEM_CELLS:
        raise SystemExit(
            f"DEM would contain {nx * ny} cells; increase --cell-size "
            f"(limit {MAX_DEM_CELLS} cells)"
        )

    xs = min_x + np.arange(nx, dtype=float) * cell_size
    ys = min_y + np.arange(ny, dtype=float) * cell_size
    grid_x, grid_y = np.meshgrid(xs, ys)
    try:
        values = griddata(
            points[:, :2], points[:, 2], (grid_x, grid_y), method=method
        )
    except QhullError as exc:
        raise SystemExit(
            f"DEM interpolation failed; the points may be degenerate: {exc}"
        ) from exc

    valid_mask = np.isfinite(values)
    valid_values = values[valid_mask]
    total_cells = int(values.size)
    valid_cells = int(np.count_nonzero(valid_mask))
    z_stats = _value_stats(valid_values, "z_")
    return {
        "values": values,
        "x": xs,
        "y": ys,
        "stats": {
            "method": method,
            "cell_size": float(cell_size),
            "shape": [int(ny), int(nx)],
            "node_count": total_cells,
            "valid_cells": valid_cells,
            "nodata_cells": total_cells - valid_cells,
            "coverage_fraction": (
                float(valid_cells / total_cells) if total_cells else 0.0
            ),
            "grid_extent": {
                "min_x": float(xs[0]),
                "max_x": float(xs[-1]),
                "min_y": float(ys[0]),
                "max_y": float(ys[-1]),
            },
            "uncovered_extent": {
                "x": float(max_x - xs[-1]),
                "y": float(max_y - ys[-1]),
            },
            "z_min": float(valid_values.min()) if valid_cells else None,
            "z_max": float(valid_values.max()) if valid_cells else None,
            "z_mean": float(valid_values.mean()) if valid_cells else None,
        },
    }


def evaluate_check_points(points: np.ndarray, check_points: np.ndarray) -> dict:
    """Compare TIN-interpolated elevations with independent check points."""
    if len(check_points) == 0:
        raise SystemExit("Check point file contains no valid coordinates")

    interpolator = LinearNDInterpolator(points[:, :2], points[:, 2])
    interpolated = np.asarray(
        interpolator(check_points[:, 0], check_points[:, 1]), dtype=float
    )
    inside = np.isfinite(interpolated)
    checked = int(np.count_nonzero(inside))
    outside = int(np.count_nonzero(~inside))

    rows = []
    errors = np.asarray([], dtype=float)
    if checked:
        interpolated_inside = interpolated[inside]
        checked_points = check_points[inside]
        errors = interpolated_inside - checked_points[:, 2]
        for index in range(checked):
            rows.append(
                {
                    "x": float(checked_points[index, 0]),
                    "y": float(checked_points[index, 1]),
                    "z_check": float(checked_points[index, 2]),
                    "z_tin": float(interpolated_inside[index]),
                    "error": float(errors[index]),
                }
            )

    rmse = float(np.sqrt(np.mean(errors ** 2))) if checked else None
    stats = {
        "check_point_count": int(len(check_points)),
        "checked_count": checked,
        "outside_hull_count": outside,
        "rmse": rmse,
        "mae": float(np.mean(np.abs(errors))) if checked else None,
        "max_abs_error": float(np.max(np.abs(errors))) if checked else None,
        "max_error": float(np.max(errors)) if checked else None,
        "min_error": float(np.min(errors)) if checked else None,
        "mean_error": float(np.mean(errors)) if checked else None,
        "std_error": float(np.std(errors)) if checked else None,
        "points": rows,
    }
    warnings: list[str] = []
    if checked == 0:
        warnings.append(
            "All check points are outside the TIN convex hull; elevation "
            "accuracy could not be evaluated."
        )
    elif checked < 4:
        warnings.append(
            f"Only {checked} check point(s) could be evaluated; the RMSE is "
            "not a reliable accuracy estimate."
        )
    if outside:
        warnings.append(
            f"{outside} check point(s) outside the TIN convex hull were excluded."
        )
    stats["warnings"] = warnings
    return stats


def write_obj(path: str | Path, vertices: np.ndarray, faces: np.ndarray) -> None:
    """Write the TIN as an OBJ mesh; coordinates use round-trip float repr."""
    lines = [
        "# mine-terrain-modeling v0.1 - unconstrained Delaunay TIN",
        "# coordinates are original survey values; units and CRS UNKNOWN",
        "o terrain_tin",
    ]
    for x, y, z in vertices:
        lines.append(f"v {float(x)!r} {float(y)!r} {float(z)!r}")
    for a, b, c in faces:
        lines.append(f"f {int(a) + 1} {int(b) + 1} {int(c) + 1}")
    write_text(path, "\n".join(lines) + "\n")


def write_esri_ascii(path: str | Path, dem: dict) -> None:
    """Write an ESRI ASCII grid with north-to-south row order."""
    values = dem["values"]
    cell_size = dem["stats"]["cell_size"]
    ny, nx = values.shape
    lines = [
        f"ncols {nx}",
        f"nrows {ny}",
        f"xllcorner {fmt(float(dem['x'][0]) - cell_size / 2.0, 6)}",
        f"yllcorner {fmt(float(dem['y'][0]) - cell_size / 2.0, 6)}",
        f"cellsize {fmt(float(cell_size), 6)}",
        f"NODATA_value {fmt(NODATA_VALUE, 1)}",
    ]
    for row in range(ny - 1, -1, -1):
        tokens = []
        for value in values[row]:
            tokens.append(f"{NODATA_VALUE:.1f}" if not np.isfinite(value) else f"{value:.6f}")
        lines.append(" ".join(tokens))
    write_text(path, "\n".join(lines) + "\n")


def render_markdown(report: dict) -> str:
    tin = report["tin"]
    dem = report["dem"]
    extent = report["input"]["extent"]
    lines = [
        "# Terrain Modeling Report",
        "",
        f"- **File**: `{report['file']}`",
        f"- **Format**: XYZ survey points",
        f"- **Input points**: {report['input']['point_count']}",
        f"- **Points used in TIN**: {tin['vertex_count']}",
        f"- **Skipped rows**: {report['input']['skipped_rows']}",
        f"- **Exact duplicates removed**: {report['input']['exact_duplicates_removed']}",
        f"- **XY conflicts removed**: {report['input']['xy_conflicts_removed']}",
        f"- **Extent**: X {fmt(extent['min_x'])} .. {fmt(extent['max_x'])}, "
        f"Y {fmt(extent['min_y'])} .. {fmt(extent['max_y'])}, "
        f"Z {fmt(extent['min_z'])} .. {fmt(extent['max_z'])}",
        f"- **Units**: {report['units']} (not assumed)",
        f"- **CRS**: {report['crs']} (not assumed)",
        "",
        "## TIN",
        "",
        f"- **Vertices**: {tin['vertex_count']}",
        f"- **Triangles**: {tin['triangle_count']}",
        f"- **Planar area**: {fmt(tin['total_area_xy'], 3)}",
        f"- **3D surface area**: {fmt(tin['total_area_3d'], 3)}",
        f"- **Slope min / mean / max (deg)**: "
        f"{fmt(tin['slope_deg_min'], 3)} / {fmt(tin['slope_deg_mean'], 3)} / "
        f"{fmt(tin['slope_deg_max'], 3)}",
        f"- **Degenerate triangles dropped**: {tin['degenerate_triangles_dropped']}",
        "",
        "## DEM",
        "",
        f"- **Method**: {dem['method']}",
        f"- **Cell size**: {fmt(dem['cell_size'], 6)} (source units)",
        f"- **Shape (rows x cols)**: {dem['shape'][0]} x {dem['shape'][1]}",
        f"- **Valid cells**: {dem['valid_cells']} / {dem['node_count']} "
        f"({fmt(dem['coverage_fraction'] * 100.0, 2)} %)",
        f"- **DEM Z range**: {fmt(dem['z_min'], 3)} .. {fmt(dem['z_max'], 3)}",
        "",
    ]
    if report.get("check_points"):
        check = report["check_points"]
        lines.extend(
            [
                "## Check Points",
                "",
                f"- **Check points**: {check['check_point_count']}",
                f"- **Evaluated**: {check['checked_count']}",
                f"- **Outside hull (excluded)**: {check['outside_hull_count']}",
                f"- **Elevation RMSE**: {fmt(check['rmse'], 6)}",
                f"- **MAE**: {fmt(check['mae'], 6)}",
                f"- **Max absolute error**: {fmt(check['max_abs_error'], 6)}",
                "",
            ]
        )
        if check["points"]:
            lines.extend(
                [
                    "| X | Y | Z check | Z TIN | Error |",
                    "|---:|---:|---:|---:|---:|",
                ]
            )
            for point in check["points"][:100]:
                lines.append(
                    f"| {fmt(point['x'])} | {fmt(point['y'])} | "
                    f"{fmt(point['z_check'])} | {fmt(point['z_tin'])} | "
                    f"{fmt(point['error'], 6)} |"
                )
            lines.append("")
    lines.extend(["## Warnings", ""])
    if report["warnings"]:
        lines.extend(f"- {warning}" for warning in report["warnings"])
    else:
        lines.append("- None")
    lines.extend(["", "## Limitations (v0.1)", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def build_report(
    source_path: str,
    points_meta: dict,
    cleaning: dict,
    tin: dict,
    dem: dict,
    check: dict | None,
    check_meta: dict | None,
    options: dict,
) -> dict:
    input_extent = extent_of(points_meta["points"])
    used_extent = extent_of(tin["vertices"])
    warnings: list[str] = [
        "Units and CRS are UNKNOWN; they were not inferred from coordinates.",
    ]
    if cleaning["exact_duplicates_removed"]:
        warnings.append(
            f"{cleaning['exact_duplicates_removed']} exact duplicate point(s) removed."
        )
    if cleaning["xy_conflicts_removed"]:
        warnings.append(
            f"{cleaning['xy_conflicts_removed']} point(s) shared an XY location "
            "with a different Z and were removed; review xy_conflict_examples."
        )
    if points_meta["skipped"]:
        warnings.append(
            f"{len(points_meta['skipped'])} input row(s) skipped; see input.skipped_details."
        )
    if not points_meta["has_header"]:
        warnings.append("No header row detected; columns were assumed to be X, Y, Z.")
    if tin["degenerate_triangles_dropped"]:
        warnings.append(
            f"{tin['degenerate_triangles_dropped']} degenerate triangle(s) were "
            "dropped from the TIN and OBJ mesh."
        )
    if dem["stats"]["shape"][0] < 2 or dem["stats"]["shape"][1] < 2:
        warnings.append(
            "DEM has fewer than 2 rows or columns; increase the data extent or "
            "reduce --cell-size."
        )
    if dem["stats"]["method"] == "linear" and dem["stats"]["coverage_fraction"] < 1.0:
        warnings.append(
            f"{dem['stats']['nodata_cells']} of {dem['stats']['node_count']} DEM "
            "nodes are NoData outside or on the edge of the TIN convex hull."
        )
    check_input = None
    if check is not None:
        warnings.extend(check["warnings"])
        meta = dict(check_meta or {})
        check_path = meta.pop("_path", None)
        meta.pop("points", None)
        check_input = {
            "file": Path(check_path).name if check_path else None,
            **meta,
        }

    report = {
        "file": Path(source_path).name,
        "source": source_manifest(source_path),
        "format": "XYZ",
        "units": "UNKNOWN",
        "crs": "UNKNOWN",
        "input": {
            "point_count": cleaning["input_point_count"],
            "skipped_rows": len(points_meta["skipped"]),
            "skipped_details": points_meta["skipped"][:50],
            "delimiter": points_meta["delimiter"],
            "encoding": points_meta["encoding"],
            "has_header": points_meta["has_header"],
            "header": points_meta["header"],
            "columns": points_meta["columns"],
            "extent": input_extent,
            "exact_duplicates_removed": cleaning["exact_duplicates_removed"],
            "xy_conflicts_removed": cleaning["xy_conflicts_removed"],
            "xy_conflict_examples": cleaning["xy_conflict_examples"],
        },
        "tin": {
            **tin["stats"],
            "degenerate_triangles_dropped": tin["degenerate_triangles_dropped"],
            "used_extent": used_extent,
            "output": "terrain.obj",
        },
        "dem": {
            **dem["stats"],
            "nodata_value": NODATA_VALUE,
            "output": "terrain_dem.asc",
        },
        "check_points": check,
        "check_point_input": check_input,
        "options": options,
        "warnings": warnings,
        "limitations": LIMITATIONS,
    }
    return report


def write_outputs(
    report: dict, tin: dict, dem: dict, out_dir: str | Path
) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "terrain_obj": str(out / "terrain.obj"),
        "terrain_dem": str(out / "terrain_dem.asc"),
        "report_json": str(out / "terrain_report.json"),
        "report_md": str(out / "terrain_report.md"),
    }
    write_obj(paths["terrain_obj"], tin["vertices"], tin["faces"])
    write_esri_ascii(paths["terrain_dem"], dem)
    write_json(paths["report_json"], report)
    write_text(paths["report_md"], render_markdown(report))
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an unconstrained Delaunay TIN and DEM from XYZ survey points."
    )
    parser.add_argument("points", help="XYZ/CSV/TSV/whitespace survey point file")
    parser.add_argument("--out-dir", default="terrain_output")
    parser.add_argument("--cell-size", type=float, default=1.0)
    parser.add_argument("--method", choices=["linear", "nearest"], default="linear")
    parser.add_argument("--check-points", help="Optional independent XYZ check points")
    parser.add_argument("--x-col", type=int, default=1)
    parser.add_argument("--y-col", type=int, default=2)
    parser.add_argument("--z-col", type=int, default=3)
    parser.add_argument("--delimiter", choices=[",", ";", "tab"])
    parser.add_argument("--encoding")
    args = parser.parse_args(argv)

    delimiter = {"tab": "\t"}.get(args.delimiter, args.delimiter)
    points_meta = load_points(
        args.points,
        x_col=args.x_col,
        y_col=args.y_col,
        z_col=args.z_col,
        delimiter=delimiter,
        encoding=args.encoding,
    )
    cleaned, cleaning = clean_points(points_meta["points"])
    tin = build_tin(cleaned)
    dem = build_dem(cleaned, args.cell_size, args.method)

    check = None
    check_meta = None
    if args.check_points:
        check_meta = load_points(
            args.check_points,
            x_col=args.x_col,
            y_col=args.y_col,
            z_col=args.z_col,
            delimiter=delimiter,
            encoding=args.encoding,
        )
        check_meta["_path"] = args.check_points
        check = evaluate_check_points(cleaned, check_meta["points"])

    options = {
        "cell_size": args.cell_size,
        "method": args.method,
        "columns": {"x": args.x_col, "y": args.y_col, "z": args.z_col},
        "check_points": args.check_points,
    }
    report = build_report(
        args.points, points_meta, cleaning, tin, dem, check, check_meta, options
    )
    paths = write_outputs(report, tin, dem, args.out_dir)

    stats = tin["stats"]
    print(
        f"TIN: {stats['vertex_count']} vertices, {stats['triangle_count']} "
        f"triangles, area_xy {fmt(stats['total_area_xy'], 2)}; "
        f"DEM {dem['stats']['shape'][0]}x{dem['stats']['shape'][1]} "
        f"({dem['stats']['valid_cells']} valid cells)"
    )
    if check is not None:
        print(
            f"Check points: {check['checked_count']}/{check['check_point_count']} "
            f"evaluated, RMSE {fmt(check['rmse'], 6)}, "
            f"max |error| {fmt(check['max_abs_error'], 6)}"
        )
    print("Outputs: " + ", ".join(paths.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
