#!/usr/bin/env python3
"""Inspect LAS headers and filter mine point clouds in XYZ/CSV form.

v0.1 is deliberately dependency-light:

* ``inspect`` reads LAS 1.0-1.4 headers with :mod:`struct`, including scale,
  offset, bounds, point format and compression flag. LAZ-compressed point
  records are never decompressed; only the header is reported.
* ``filter`` reads XYZ/CSV points, applies a Z range filter, optional voxel
  downsampling and a simple lowest-Z-per-XY-cell ground candidate selection.

PDAL and Open3D integration is planned for v0.2.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - environment dependent
    raise SystemExit(
        "numpy is required. Install it with:\n"
        "  python3 -m pip install -r requirements.txt"
    ) from exc


LAS_SIGNATURE = b"LASF"
KNOWN_POINT_FORMATS = set(range(11))
STANDARD_HEADER_SIZES = {0: 227, 1: 227, 2: 227, 3: 235, 4: 375}

X_NAMES = {"x", "easting", "east", "东坐标", "x坐标"}
Y_NAMES = {"y", "northing", "north", "北坐标", "y坐标"}
Z_NAMES = {"z", "elevation", "elev", "height", "高程", "z坐标"}

LIMITATIONS = [
    "LAZ-compressed point records are NOT decompressed in v0.1; use PDAL, "
    "laszip or LAStools to decompress LAZ data first.",
    "Only the LAS header is read. Point attributes, VLR payloads, classifications "
    "and per-point elevations are not decoded.",
    "Ground candidates are the lowest point per XY cell. This is NOT a ground "
    "classification and may select low noise, vehicles or vegetation.",
    "No CRS or unit conversion is performed; every value remains in source units.",
    "Voxel downsampling keeps the first point per voxel in file order. It is not "
    "a statistical outlier filter.",
    "The whole XYZ/CSV file is loaded into memory; split very large clouds first.",
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


def _decode_fixed(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("ascii", errors="replace").strip()


def _u16(buf: bytes, offset: int) -> int:
    return int(struct.unpack_from("<H", buf, offset)[0])


def _u32(buf: bytes, offset: int) -> int:
    return int(struct.unpack_from("<I", buf, offset)[0])


def _u64(buf: bytes, offset: int) -> int:
    return int(struct.unpack_from("<Q", buf, offset)[0])


def inspect_las(path: str) -> dict:
    """Read a LAS 1.0-1.4 header and report format, counts and bounds.

    Compressed (LAZ) point records are not decompressed and no point records
    are read at all. The function only requires the standard header bytes.
    """
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"File not found: {path}")
    file_size = p.stat().st_size
    with p.open("rb") as fh:
        head = fh.read(375)

    if len(head) < 4:
        raise SystemExit(f"{path} is too small to be a LAS file")
    signature = head[:4]
    if signature != LAS_SIGNATURE:
        raise SystemExit(
            f"{path} is not a LAS file: expected signature LASF, found "
            f"{signature!r}"
        )
    if len(head) < 107:
        raise SystemExit("LAS header is truncated before the core fields")

    warnings: list[str] = []
    version_major = head[24]
    version_minor = head[25]
    supported_version = version_major == 1 and 0 <= version_minor <= 4
    if not supported_version:
        warnings.append(
            f"LAS version {version_major}.{version_minor} is outside the "
            "supported 1.0-1.4 range; header fields were parsed best-effort."
        )

    system_identifier = _decode_fixed(head[26:58])
    generating_software = _decode_fixed(head[58:90])
    creation_day = _u16(head, 90)
    creation_year = _u16(head, 92)
    header_size = _u16(head, 94)
    point_data_offset = _u32(head, 96)
    vlr_count = _u32(head, 100)
    point_format_raw = head[104]
    point_format_id = point_format_raw & 0x7F
    compressed = bool(point_format_raw & 0x80)
    record_length = _u16(head, 105)
    legacy_point_count = _u32(head, 107)

    expected_header_size = STANDARD_HEADER_SIZES.get(version_minor)
    if expected_header_size and header_size != expected_header_size:
        warnings.append(
            f"Header size {header_size} differs from the LAS "
            f"{version_major}.{version_minor} standard ({expected_header_size})."
        )
    if file_size < header_size:
        warnings.append(
            f"File size {file_size} is smaller than the declared header size "
            f"{header_size}."
        )
    if point_data_offset < header_size:
        warnings.append(
            f"Point data offset {point_data_offset} is before the end of the "
            f"header ({header_size})."
        )
    if point_data_offset > file_size:
        warnings.append(
            f"Point data offset {point_data_offset} is beyond the file size "
            f"{file_size}."
        )

    scale = None
    offset = None
    bounds = None
    if len(head) >= 227:
        sx, sy, sz = struct.unpack_from("<3d", head, 131)
        ox, oy, oz = struct.unpack_from("<3d", head, 155)
        max_x, min_x, max_y, min_y, max_z, min_z = struct.unpack_from(
            "<6d", head, 179
        )
        scale = {"x": float(sx), "y": float(sy), "z": float(sz)}
        offset = {"x": float(ox), "y": float(oy), "z": float(oz)}
        bounds = {
            "min_x": float(min_x),
            "max_x": float(max_x),
            "min_y": float(min_y),
            "max_y": float(max_y),
            "min_z": float(min_z),
            "max_z": float(max_z),
            "span_x": float(max_x - min_x),
            "span_y": float(max_y - min_y),
            "span_z": float(max_z - min_z),
        }
        if any(value == 0 for value in scale.values()):
            warnings.append("One or more LAS scale factors are zero.")
        if min_x > max_x or min_y > max_y or min_z > max_z:
            warnings.append("LAS header bounds are inconsistent (min greater than max).")
    else:
        warnings.append(
            "LAS header is truncated before scale, offset and bounds fields."
        )

    legacy_by_return = []
    if len(head) >= 131:
        legacy_by_return = [int(value) for value in struct.unpack_from("<5I", head, 111)]

    waveform_offset = None
    if header_size >= 235 and len(head) >= 235:
        waveform_offset = _u64(head, 227)

    evlr = None
    extended_point_count = None
    extended_by_return = None
    if version_major == 1 and version_minor >= 4 and header_size >= 375 and len(head) >= 375:
        first_evlr = _u64(head, 235)
        evlr_count = _u32(head, 243)
        extended_point_count = _u64(head, 247)
        extended_by_return = [
            int(value) for value in struct.unpack_from("<15Q", head, 255)
        ]
        evlr = {"count": evlr_count, "offset": first_evlr}
    elif version_minor >= 4:
        warnings.append(
            "LAS 1.4 header is shorter than 375 bytes; extended point counts "
            "and EVLR fields were not read."
        )

    if version_major == 1 and version_minor >= 4 and extended_point_count is not None:
        point_count = (
            extended_point_count
            if extended_point_count > 0 or legacy_point_count == 0
            else legacy_point_count
        )
        point_count_source = (
            "extended"
            if extended_point_count > 0 or legacy_point_count == 0
            else "legacy"
        )
        if (
            legacy_point_count > 0
            and extended_point_count > 0
            and legacy_point_count != extended_point_count
        ):
            warnings.append(
                f"Legacy point count {legacy_point_count} differs from extended "
                f"point count {extended_point_count}."
            )
    else:
        point_count = legacy_point_count
        point_count_source = "legacy"

    if compressed:
        warnings.append(
            "LAZ-compressed point records are not read in v0.1; use PDAL or "
            "laszip to decompress before point-level processing."
        )
    if point_format_id not in KNOWN_POINT_FORMATS:
        warnings.append(
            f"Point data record format {point_format_id} is not a known LAS "
            "format (0-10)."
        )
    if point_format_id > 5 and not (version_major == 1 and version_minor >= 4):
        warnings.append(
            "Point formats 6-10 require LAS 1.4; the header declares an older "
            "version."
        )
    if point_count == 0:
        warnings.append("The header declares zero point records.")
    if p.suffix.lower() == ".laz" and not compressed:
        warnings.append(
            "The file has a .laz extension but the LAS compression bit is not "
            "set; verify the file with PDAL."
        )

    expected_point_data_bytes = None
    if not compressed and point_data_offset and record_length and point_count:
        expected_point_data_bytes = point_count * record_length
        expected_end = point_data_offset + expected_point_data_bytes
        if expected_end > file_size:
            warnings.append(
                f"Point data requires {expected_end} bytes but the file has "
                f"{file_size}; the file appears truncated."
            )

    return {
        "file": p.name,
        "format": "LAS",
        "signature": signature.decode("ascii", errors="replace"),
        "version": f"{version_major}.{version_minor}",
        "version_major": int(version_major),
        "version_minor": int(version_minor),
        "supported_version": supported_version,
        "header_size": int(header_size),
        "point_data_offset": int(point_data_offset),
        "vlr_count": int(vlr_count),
        "evlr": evlr,
        "waveform_data_offset": waveform_offset,
        "point_format": {
            "id": int(point_format_id),
            "raw": int(point_format_raw),
            "compressed": compressed,
            "record_length": int(record_length),
            "recognized": point_format_id in KNOWN_POINT_FORMATS,
        },
        "point_count": int(point_count),
        "point_count_source": point_count_source,
        "legacy_point_count": int(legacy_point_count),
        "extended_point_count": (
            int(extended_point_count) if extended_point_count is not None else None
        ),
        "points_by_return": {
            "legacy": legacy_by_return,
            "extended": extended_by_return,
        },
        "scale": scale,
        "offset": offset,
        "bounds": bounds,
        "creation": {"day_of_year": int(creation_day), "year": int(creation_year)},
        "system_identifier": system_identifier,
        "generating_software": generating_software,
        "file_size_bytes": int(file_size),
        "expected_point_data_bytes": (
            int(expected_point_data_bytes)
            if expected_point_data_bytes is not None
            else None
        ),
        "units": "UNKNOWN",
        "crs": "UNKNOWN",
        "warnings": warnings,
        "limitations": LIMITATIONS,
        "source": source_manifest(path),
    }


def render_inspection_markdown(report: dict) -> str:
    fmt_info = report["point_format"]
    bounds = report["bounds"]
    lines = [
        "# LAS Header Inspection",
        "",
        f"- **File**: `{report['file']}`",
        f"- **Version**: LAS {report['version']}"
        f"{' (supported)' if report['supported_version'] else ' (unsupported)'}",
        f"- **Header size**: {report['header_size']} bytes",
        f"- **Point data offset**: {report['point_data_offset']}",
        f"- **Point format**: {fmt_info['id']} "
        f"(record length {fmt_info['record_length']})",
        f"- **Compressed (LAZ)**: {fmt_info['compressed']}",
        f"- **Point count**: {report['point_count']} "
        f"(source: {report['point_count_source']})",
        f"- **Legacy point count**: {report['legacy_point_count']}",
        f"- **Extended point count**: {fmt(report['extended_point_count'])}",
        f"- **VLR count**: {report['vlr_count']}",
        f"- **Units**: {report['units']} (not assumed)",
        f"- **CRS**: {report['crs']} (not assumed)",
        "",
    ]
    if report["scale"] and report["offset"]:
        lines.extend(
            [
                "## Scale and Offset",
                "",
                f"- Scale: X {report['scale']['x']}, Y {report['scale']['y']}, "
                f"Z {report['scale']['z']}",
                f"- Offset: X {report['offset']['x']}, Y {report['offset']['y']}, "
                f"Z {report['offset']['z']}",
                "",
            ]
        )
    if bounds:
        lines.extend(
            [
                "## Header Bounds",
                "",
                f"- X: {fmt(bounds['min_x'])} .. {fmt(bounds['max_x'])}",
                f"- Y: {fmt(bounds['min_y'])} .. {fmt(bounds['max_y'])}",
                f"- Z: {fmt(bounds['min_z'])} .. {fmt(bounds['max_z'])}",
                f"- Spans: X {fmt(bounds['span_x'])}, Y {fmt(bounds['span_y'])}, "
                f"Z {fmt(bounds['span_z'])}",
                "",
            ]
        )
    lines.extend(["## Warnings", ""])
    if report["warnings"]:
        lines.extend(f"- {warning}" for warning in report["warnings"])
    else:
        lines.append("- None")
    lines.extend(["", "## Limitations (v0.1)", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def _z_summary(points: np.ndarray) -> dict | None:
    if len(points) == 0:
        return None
    return {"min": float(points[:, 2].min()), "max": float(points[:, 2].max())}


def _unique_grid_first(points: np.ndarray, cell_size: float) -> np.ndarray:
    keys = np.floor(points / cell_size).astype(np.int64)
    _, first = np.unique(keys, axis=0, return_index=True)
    return np.sort(first)


def filter_points(
    points: np.ndarray,
    voxel_size: float | None = None,
    z_min: float | None = None,
    z_max: float | None = None,
    ground_cell_size: float = 10.0,
) -> dict:
    """Apply a Z range filter, voxel downsampling and ground candidate selection."""
    if len(points) == 0:
        raise SystemExit("Point cloud contains no points")
    if z_min is not None and z_max is not None and z_min > z_max:
        raise SystemExit("--z-min must not be greater than --z-max")
    if voxel_size is not None and voxel_size <= 0:
        raise SystemExit("--voxel-size must be greater than 0")
    if ground_cell_size <= 0:
        raise SystemExit("--ground-cell-size must be greater than 0")

    warnings: list[str] = []
    input_count = int(len(points))
    input_z = _z_summary(points)

    keep = np.ones(len(points), dtype=bool)
    if z_min is not None:
        keep &= points[:, 2] >= z_min
    if z_max is not None:
        keep &= points[:, 2] <= z_max
    source_indices = np.nonzero(keep)[0]
    z_filtered = points[keep]
    z_filter_stats = {
        "enabled": z_min is not None or z_max is not None,
        "z_min": z_min,
        "z_max": z_max,
        "count_removed": input_count - int(len(z_filtered)),
        "count_kept": int(len(z_filtered)),
        "z_range": _z_summary(z_filtered),
    }
    if z_filter_stats["enabled"] and len(z_filtered) == 0:
        warnings.append("The Z range filter removed every point.")

    voxel_stats = {
        "enabled": voxel_size is not None,
        "voxel_size": voxel_size,
        "count_removed": 0,
        "count_kept": int(len(z_filtered)),
        "z_range": _z_summary(z_filtered),
    }
    if voxel_size is not None and len(z_filtered):
        first_positions = _unique_grid_first(z_filtered, voxel_size)
        downsampled = z_filtered[first_positions]
        source_indices = source_indices[first_positions]
        voxel_stats["count_removed"] = int(len(z_filtered) - len(downsampled))
        voxel_stats["count_kept"] = int(len(downsampled))
        voxel_stats["z_range"] = _z_summary(downsampled)
        if len(downsampled) == 1 and len(z_filtered) > 1:
            warnings.append(
                "Voxel size is larger than the cloud extent; downsampling kept "
                "a single point."
            )
    else:
        downsampled = z_filtered

    ground_rows: list[dict] = []
    if len(downsampled):
        keys = np.floor(downsampled[:, :2] / ground_cell_size).astype(np.int64)
        # Sort by cell X, cell Y, Z, then source index; the first row per cell
        # is therefore the lowest-Z point (ties resolved by source order).
        order = np.lexsort(
            (source_indices, downsampled[:, 2], keys[:, 1], keys[:, 0])
        )
        sorted_keys = keys[order]
        group_start = np.ones(len(order), dtype=bool)
        if len(order) > 1:
            group_start[1:] = np.any(
                sorted_keys[1:] != sorted_keys[:-1], axis=1
            )
        chosen = order[group_start]
        for position in chosen:
            row = downsampled[position]
            cell = keys[position]
            ground_rows.append(
                {
                    "cell_x": int(cell[0]),
                    "cell_y": int(cell[1]),
                    "source_index": int(source_indices[position]),
                    "x": float(row[0]),
                    "y": float(row[1]),
                    "z": float(row[2]),
                }
            )
        if len(ground_rows) == len(downsampled) and len(downsampled) > 1:
            warnings.append(
                "Every point falls in its own ground cell; the cell size may be "
                "smaller than the point spacing."
            )
    else:
        warnings.append("No points remain; ground candidates could not be generated.")

    ground_z = (
        {"min": min(row["z"] for row in ground_rows),
         "max": max(row["z"] for row in ground_rows)}
        if ground_rows
        else None
    )
    ground_stats = {
        "cell_size": float(ground_cell_size),
        "count": len(ground_rows),
        "z_range": ground_z,
        "method": "lowest_z_per_xy_cell",
        "is_classification": False,
    }

    return {
        "input": {
            "count": input_count,
            "z_range": input_z,
        },
        "z_filter": z_filter_stats,
        "voxel_downsample": voxel_stats,
        "ground_candidates": ground_stats,
        "filtered_points": downsampled,
        "filtered_source_indices": source_indices,
        "ground_rows": ground_rows,
        "warnings": warnings,
    }


def write_filtered_csv(path: str | Path, points: np.ndarray, indices: np.ndarray) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["index", "x", "y", "z"])
        for offset, point in enumerate(points):
            writer.writerow(
                [
                    int(indices[offset]) + 1,
                    repr(float(point[0])),
                    repr(float(point[1])),
                    repr(float(point[2])),
                ]
            )


def write_ground_csv(path: str | Path, rows: list[dict]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["index", "cell_x", "cell_y", "x", "y", "z"])
        for row in rows:
            writer.writerow(
                [
                    row["source_index"] + 1,
                    row["cell_x"],
                    row["cell_y"],
                    repr(row["x"]),
                    repr(row["y"]),
                    repr(row["z"]),
                ]
            )


def build_filter_report(
    source_path: str,
    points_meta: dict,
    result: dict,
    options: dict,
    outputs: dict | None = None,
) -> dict:
    warnings = list(result["warnings"])
    if points_meta["skipped"]:
        warnings.append(
            f"{len(points_meta['skipped'])} input row(s) skipped; see "
            "input.skipped_details."
        )
    if not points_meta["has_header"]:
        warnings.append("No header row detected; columns were assumed to be X, Y, Z.")
    warnings.append("Units and CRS are UNKNOWN; they were not inferred.")

    return {
        "file": Path(source_path).name,
        "source": source_manifest(source_path),
        "format": "XYZ",
        "units": "UNKNOWN",
        "crs": "UNKNOWN",
        "input": {
            "point_count": int(len(points_meta["points"])),
            "skipped_rows": len(points_meta["skipped"]),
            "skipped_details": points_meta["skipped"][:50],
            "delimiter": points_meta["delimiter"],
            "encoding": points_meta["encoding"],
            "has_header": points_meta["has_header"],
            "header": points_meta["header"],
            "columns": points_meta["columns"],
            "z_range": result["input"]["z_range"],
        },
        "parameters": options,
        "stages": {
            "z_filter": result["z_filter"],
            "voxel_downsample": result["voxel_downsample"],
            "ground_candidates": result["ground_candidates"],
        },
        "outputs": outputs or {},
        "warnings": warnings,
        "limitations": LIMITATIONS,
    }


def render_filter_markdown(report: dict) -> str:
    stages = report["stages"]
    input_info = report["input"]
    z_filter = stages["z_filter"]
    voxel = stages["voxel_downsample"]
    ground = stages["ground_candidates"]
    lines = [
        "# Point Cloud Filter Report",
        "",
        f"- **File**: `{report['file']}`",
        f"- **Input points**: {input_info['point_count']}",
        f"- **Skipped rows**: {input_info['skipped_rows']}",
        f"- **Input Z range**: "
        f"{fmt((input_info['z_range'] or {}).get('min'))} .. "
        f"{fmt((input_info['z_range'] or {}).get('max'))}",
        f"- **Units**: {report['units']} (not assumed)",
        f"- **CRS**: {report['crs']} (not assumed)",
        "",
        "## Stages",
        "",
        "| Stage | Enabled | Removed | Kept | Z min | Z max |",
        "|---|---|---:|---:|---:|---:|",
        f"| Z filter | {z_filter['enabled']} | {z_filter['count_removed']} | "
        f"{z_filter['count_kept']} | "
        f"{fmt((z_filter['z_range'] or {}).get('min'))} | "
        f"{fmt((z_filter['z_range'] or {}).get('max'))} |",
        f"| Voxel downsample | {voxel['enabled']} | {voxel['count_removed']} | "
        f"{voxel['count_kept']} | "
        f"{fmt((voxel['z_range'] or {}).get('min'))} | "
        f"{fmt((voxel['z_range'] or {}).get('max'))} |",
        f"| Ground candidates | - | - | {ground['count']} | "
        f"{fmt((ground['z_range'] or {}).get('min'))} | "
        f"{fmt((ground['z_range'] or {}).get('max'))} |",
        "",
        "## Parameters",
        "",
        f"- Voxel size: {fmt(voxel['voxel_size'])}",
        f"- Ground cell size: {fmt(ground['cell_size'])}",
        f"- Ground method: {ground['method']} "
        "(NOT a ground classification)",
        "",
        "## Outputs",
        "",
    ]
    if report["outputs"]:
        lines.extend(
            f"- `{name}`: `{path}`" for name, path in report["outputs"].items()
        )
    else:
        lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    if report["warnings"]:
        lines.extend(f"- {warning}" for warning in report["warnings"])
    else:
        lines.append("- None")
    lines.extend(["", "## Limitations (v0.1)", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def _run_inspect(args: argparse.Namespace) -> int:
    report = inspect_las(args.path)
    if args.output:
        write_json(args.output, report)
    if args.markdown:
        write_text(args.markdown, render_inspection_markdown(report))
    if not args.output and not args.markdown:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        fmt_info = report["point_format"]
        print(
            f"LAS {report['version']}: {report['point_count']} points, "
            f"format {fmt_info['id']}, compressed={fmt_info['compressed']}, "
            f"header {report['header_size']} bytes, "
            f"warnings {len(report['warnings'])}"
        )
    return 0


def _run_filter(args: argparse.Namespace) -> int:
    delimiter = {"tab": "\t"}.get(args.delimiter, args.delimiter)
    meta = load_points(
        args.points,
        x_col=args.x_col,
        y_col=args.y_col,
        z_col=args.z_col,
        delimiter=delimiter,
        encoding=args.encoding,
    )
    result = filter_points(
        meta["points"],
        voxel_size=args.voxel_size,
        z_min=args.z_min,
        z_max=args.z_max,
        ground_cell_size=args.ground_cell_size,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "filtered_points": str(out_dir / "filtered_points.csv"),
        "ground_candidates": str(out_dir / "ground_candidates.csv"),
        "report_json": str(out_dir / "pointcloud_filter_report.json"),
        "report_md": str(out_dir / "pointcloud_filter_report.md"),
    }
    write_filtered_csv(
        paths["filtered_points"],
        result["filtered_points"],
        result["filtered_source_indices"],
    )
    write_ground_csv(paths["ground_candidates"], result["ground_rows"])
    options = {
        "voxel_size": args.voxel_size,
        "z_min": args.z_min,
        "z_max": args.z_max,
        "ground_cell_size": args.ground_cell_size,
        "columns": {"x": args.x_col, "y": args.y_col, "z": args.z_col},
    }
    report = build_filter_report(args.points, meta, result, options, paths)
    write_json(paths["report_json"], report)
    write_text(paths["report_md"], render_filter_markdown(report))

    print(
        f"Input {result['input']['count']} -> Z filter {result['z_filter']['count_kept']} "
        f"-> voxel {result['voxel_downsample']['count_kept']} "
        f"-> ground candidates {result['ground_candidates']['count']}"
    )
    print("Outputs: " + ", ".join(paths.values()))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect LAS headers or filter XYZ point clouds."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Read a LAS header")
    inspect_parser.add_argument("path", help="LAS or LAZ file")
    inspect_parser.add_argument("--output", help="Write the JSON report here")
    inspect_parser.add_argument("--markdown", help="Write the Markdown report here")
    inspect_parser.set_defaults(handler=_run_inspect)

    filter_parser = subparsers.add_parser("filter", help="Filter XYZ/CSV points")
    filter_parser.add_argument("points", help="XYZ/CSV/TSV/whitespace point file")
    filter_parser.add_argument("--out-dir", default="pointcloud_output")
    filter_parser.add_argument("--voxel-size", type=float)
    filter_parser.add_argument("--z-min", type=float)
    filter_parser.add_argument("--z-max", type=float)
    filter_parser.add_argument("--ground-cell-size", type=float, default=10.0)
    filter_parser.add_argument("--x-col", type=int, default=1)
    filter_parser.add_argument("--y-col", type=int, default=2)
    filter_parser.add_argument("--z-col", type=int, default=3)
    filter_parser.add_argument("--delimiter", choices=[",", ";", "tab"])
    filter_parser.add_argument("--encoding")
    filter_parser.set_defaults(handler=_run_filter)

    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
