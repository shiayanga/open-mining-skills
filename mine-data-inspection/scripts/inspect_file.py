#!/usr/bin/env python3
"""Dispatch a mine data file to the right inspector.

Supported in v0.1:
  - DXF drawings (requires ezdxf)
  - XYZ / CSV / TSV / whitespace-delimited survey points

DWG requires conversion to DXF first. LAS/LAZ/SHP inspection is planned.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import common
import inspect_dxf
import inspect_xyz

XYZ_SUFFIXES = {".xyz", ".csv", ".tsv", ".txt", ".asc"}
POINT_CLOUD_SUFFIXES = {".las", ".laz", ".ply", ".e57"}


def unsupported_report(path: str, format_name: str, reason: str) -> dict:
    return {
        "file": Path(path).name,
        "format": format_name,
        "status": "UNSUPPORTED",
        "coordinate_system": "UNKNOWN",
        "units": "UNKNOWN",
        "warnings": [reason],
        "source": common.source_manifest(path),
    }


def render_unsupported_markdown(report: dict) -> str:
    lines = [
        "# Data Inspection Report",
        "",
        f"- **File**: `{report['file']}`",
        f"- **Format**: {report['format']}",
        f"- **Status**: {report['status']}",
        "",
        "## Warnings",
        "",
    ]
    lines.extend(f"- {warning}" for warning in report["warnings"])
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


def dispatch(path: str, format_hint: str = "auto", **xyz_options) -> dict:
    suffix = Path(path).suffix.lower()
    if format_hint == "dxf" or (format_hint == "auto" and suffix == ".dxf"):
        return inspect_dxf.inspect_dxf(path)
    if format_hint == "xyz" or (format_hint == "auto" and suffix in XYZ_SUFFIXES):
        return inspect_xyz.inspect_xyz(path, **xyz_options)
    if suffix == ".dwg":
        return unsupported_report(
            path,
            "DWG",
            "DWG is not parsed directly. Convert it to DXF first; see "
            "references/dwg-notes.md.",
        )
    if suffix in POINT_CLOUD_SUFFIXES:
        return unsupported_report(
            path,
            suffix.lstrip(".").upper(),
            "Point cloud inspection is planned for v0.2 and will use PDAL. "
            "Use mine-point-cloud when it is implemented.",
        )
    return unsupported_report(
        path,
        suffix.lstrip(".").upper() or "UNKNOWN",
        "Unsupported file type in v0.1. Supported: DXF, XYZ, CSV, TSV.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect a mine data file.")
    parser.add_argument("path", help="Path to the file")
    parser.add_argument("--format", choices=["auto", "dxf", "xyz"], default="auto")
    parser.add_argument("--delimiter", choices=[",", ";", "tab"], help="XYZ delimiter")
    parser.add_argument("--header", dest="has_header", action="store_true", default=None)
    parser.add_argument("--no-header", dest="has_header", action="store_false")
    parser.add_argument("--x-col", type=int)
    parser.add_argument("--y-col", type=int)
    parser.add_argument("--z-col", type=int)
    parser.add_argument("--encoding")
    parser.add_argument("--output", help="Write the JSON report to this path")
    parser.add_argument("--markdown", help="Write a Markdown report to this path")
    parser.add_argument("--manifest", help="Write a source manifest JSON to this path")
    args = parser.parse_args(argv)

    xyz_options = {
        "delimiter": {"tab": "\t"}.get(args.delimiter, args.delimiter),
        "has_header": args.has_header,
        "x_col": args.x_col,
        "y_col": args.y_col,
        "z_col": args.z_col,
        "encoding": args.encoding,
    }
    report = dispatch(args.path, args.format, **xyz_options)

    if args.output:
        common.write_json(args.output, report)
    if args.markdown:
        if report.get("status") == "UNSUPPORTED":
            text = render_unsupported_markdown(report)
        elif report.get("format") == "DXF":
            text = inspect_dxf.render_markdown(report)
        else:
            text = inspect_xyz.render_markdown(report)
        common.write_text(args.markdown, text)
    if args.manifest:
        common.write_json(args.manifest, report["source"])

    if report.get("status") == "UNSUPPORTED":
        print(f"{report['file']}: unsupported — {report['warnings'][0]}")
        return 0
    if report.get("format") == "DXF":
        extent = report.get("extent") or {}
        print(
            f"Inspected {report['file']}: DXF {report['format_version']}, "
            f"{report['entity_total']} entities, {len(report['layers'])} layers, "
            f"Z {common.fmt(extent.get('min_z'))}..{common.fmt(extent.get('max_z'))}; "
            f"warnings: {len(report['warnings'])}"
        )
    else:
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
