#!/usr/bin/env python3
"""Inspect XYZ / CSV / space-delimited survey point files.

The inspector reports what is actually in the file: columns, point count,
extents, elevation range, duplicates and data quality warnings. It never
guesses units or a coordinate reference system.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from pathlib import Path

import common

X_NAMES = {"x", "easting", "east", "东坐标", "x坐标"}
Y_NAMES = {"y", "northing", "north", "北坐标", "y坐标"}
Z_NAMES = {"z", "elevation", "elev", "height", "高程", "z坐标"}

ASCII_WHITESPACE = None  # sentinel for whitespace-delimited files


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
    return best if candidates[best] > 0 else ASCII_WHITESPACE


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


def inspect_xyz(
    path: str,
    delimiter: str | None = None,
    has_header: bool | None = None,
    x_col: int | None = None,
    y_col: int | None = None,
    z_col: int | None = None,
    encoding: str | None = None,
) -> dict:
    """Inspect an XYZ-like survey file and return a report dictionary."""
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
    if has_header is None:
        has_header = any(
            any(not is_number(token) for token in row)
            for row in sample_rows[:5]
        )

    header_columns: list[str] | None = None
    data_start = 0
    if has_header:
        header_columns = sample_rows[0]
        name_map = {}
        for index, name in enumerate(header_columns):
            lowered = name.strip().lower()
            if lowered in X_NAMES:
                name_map["x"] = index
            elif lowered in Y_NAMES:
                name_map["y"] = index
            elif lowered in Z_NAMES:
                name_map["z"] = index
        if len(name_map) == 3 and x_col is None and y_col is None and z_col is None:
            x_col = name_map["x"] + 1
            y_col = name_map["y"] + 1
            z_col = name_map["z"] + 1
        data_start = 1

    x_col = x_col or 1
    y_col = y_col or 2
    z_col = z_col or 3

    points: list[tuple[float, float, float]] = []
    skipped: list[dict] = []
    for lineno, line in numbered[data_start:]:
        tokens = split_line(line, delimiter)
        if len(tokens) < 3:
            skipped.append({"line": lineno, "reason": "fewer than 3 columns"})
            continue
        try:
            x = float(tokens[x_col - 1])
            y = float(tokens[y_col - 1])
            z = float(tokens[z_col - 1])
        except (ValueError, IndexError):
            skipped.append({"line": lineno, "reason": "non-numeric or missing coordinate"})
            continue
        if not all(math.isfinite(value) for value in (x, y, z)):
            skipped.append({"line": lineno, "reason": "non-finite coordinate"})
            continue
        points.append((x, y, z))

    if not points:
        raise SystemExit("No valid coordinate rows found")

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    extent = {
        "min_x": min(xs),
        "min_y": min(ys),
        "min_z": min(zs),
        "max_x": max(xs),
        "max_y": max(ys),
        "max_z": max(zs),
        "span_x": max(xs) - min(xs),
        "span_y": max(ys) - min(ys),
        "span_z": max(zs) - min(zs),
    }
    duplicated = sum(count - 1 for count in Counter(points).values() if count > 1)
    zero_z = sum(1 for z in zs if abs(z) < 1e-9)
    clue = common.magnitude_clue(
        extent["min_x"], extent["min_y"], extent["max_x"], extent["max_y"]
    )

    warnings: list[str] = []
    if not has_header:
        warnings.append(
            "No header row detected; columns were assumed to be X, Y, Z."
        )
    if skipped:
        warnings.append(f"{len(skipped)} row(s) skipped; see skipped_details.")
    if duplicated:
        warnings.append(f"{duplicated} duplicate coordinate row(s) found.")
    if zero_z == len(points):
        warnings.append("All Z values are zero; the data may be 2D.")
    if clue == "DEGREE_CANDIDATE":
        warnings.append(
            "Coordinates fall within geographic degree ranges; confirm whether "
            "they are longitude/latitude and not a local grid."
        )
    elif clue == "LOCAL_OR_UNKNOWN":
        warnings.append(
            "Coordinates look like a local or engineering grid; the CRS is unknown."
        )
    if extent["span_z"] > 100000:
        warnings.append(
            "Z span is very large; check whether elevation units are consistent."
        )
    if len(points) < 3:
        warnings.append("Fewer than 3 valid points; insufficient for surface modeling.")

    return {
        "file": str(Path(path).name),
        "format": "XYZ",
        "format_detail": {
            "delimiter": delimiter if delimiter is not None else "whitespace",
            "encoding": used_encoding,
            "has_header": has_header,
            "header_columns": header_columns,
            "column_mapping": {"x": x_col, "y": y_col, "z": z_col},
        },
        "point_count": len(points),
        "skipped_rows": len(skipped),
        "skipped_details": skipped[:50],
        "extent": extent,
        "z_range": {"min": extent["min_z"], "max": extent["max_z"], "span": extent["span_z"]},
        "duplicate_coordinates": duplicated,
        "zero_z_count": zero_z,
        "units": "UNKNOWN",
        "coordinate_system": "UNKNOWN",
        "coordinate_clue": clue,
        "warnings": warnings,
        "source": common.source_manifest(path),
    }


def render_markdown(report: dict) -> str:
    detail = report["format_detail"]
    extent = report["extent"]
    lines = [
        "# Data Inspection Report",
        "",
        f"- **File**: `{report['file']}`",
        f"- **Format**: XYZ ({detail['delimiter']}, encoding {detail['encoding']})",
        f"- **Header**: {'yes' if detail['has_header'] else 'no'}",
        f"- **Columns**: X={detail['column_mapping']['x']}, "
        f"Y={detail['column_mapping']['y']}, Z={detail['column_mapping']['z']}",
        f"- **Valid points**: {report['point_count']}",
        f"- **Skipped rows**: {report['skipped_rows']}",
        f"- **Duplicate coordinates**: {report['duplicate_coordinates']}",
        f"- **Extent**: X {common.fmt(extent['min_x'])} .. {common.fmt(extent['max_x'])}, "
        f"Y {common.fmt(extent['min_y'])} .. {common.fmt(extent['max_y'])}, "
        f"Z {common.fmt(extent['min_z'])} .. {common.fmt(extent['max_z'])}",
        f"- **Units**: {report['units']} (not assumed)",
        f"- **Coordinate system**: {report['coordinate_system']}",
        f"- **Coordinate clue**: {report['coordinate_clue']}",
        "",
        "## Warnings",
        "",
    ]
    if report["warnings"]:
        lines.extend(f"- {warning}" for warning in report["warnings"])
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Source",
            "",
            f"- Path: `{report['source']['path']}`",
            f"- Size: {report['source']['size_bytes']} bytes",
            f"- SHA-256: `{report['source']['sha256']}`",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect an XYZ/CSV survey file.")
    parser.add_argument("path", help="Path to the XYZ/CSV/TSV file")
    parser.add_argument("--delimiter", choices=[",", ";", "tab"], help="Column delimiter")
    parser.add_argument("--header", dest="has_header", action="store_true", default=None)
    parser.add_argument("--no-header", dest="has_header", action="store_false")
    parser.add_argument("--x-col", type=int, help="1-based X column index")
    parser.add_argument("--y-col", type=int, help="1-based Y column index")
    parser.add_argument("--z-col", type=int, help="1-based Z column index")
    parser.add_argument("--encoding", help="Force a text encoding")
    parser.add_argument("--output", help="Write the JSON report to this path")
    parser.add_argument("--markdown", help="Write a Markdown report to this path")
    parser.add_argument("--manifest", help="Write a source manifest JSON to this path")
    args = parser.parse_args(argv)

    delimiter = {"tab": "\t"}.get(args.delimiter, args.delimiter)
    report = inspect_xyz(
        args.path,
        delimiter=delimiter,
        has_header=args.has_header,
        x_col=args.x_col,
        y_col=args.y_col,
        z_col=args.z_col,
        encoding=args.encoding,
    )
    if args.output:
        common.write_json(args.output, report)
    if args.markdown:
        common.write_text(args.markdown, render_markdown(report))
    if args.manifest:
        common.write_json(args.manifest, report["source"])

    extent = report["extent"]
    print(
        f"Inspected {report['file']}: {report['point_count']} points, "
        f"X {common.fmt(extent['min_x'])}..{common.fmt(extent['max_x'])}, "
        f"Y {common.fmt(extent['min_y'])}..{common.fmt(extent['max_y'])}, "
        f"Z {common.fmt(extent['min_z'])}..{common.fmt(extent['max_z'])}; "
        f"warnings: {len(report['warnings'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
