#!/usr/bin/env python3
"""Create a minimal single-tile 3D Tiles 1.1 tileset for a GLB or OBJ file.

The v0.1 tool does not subdivide space or generate LOD levels. It computes an
axis-aligned bounding box (from OBJ vertices, or from a required ``--bbox`` for
GLB), copies the content next to ``tileset.json`` and writes a local tileset
plus a report. See ``references/tileset-structure.md`` and the py3dtiles
roadmap in ``references/tiling-roadmap.md`` for the future tiling path.
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
import struct
import sys
import urllib.parse
from pathlib import Path

import common

TILESET_VERSION = "1.1"
GENERATOR = "open-mining-skills mine-3d-tiles v0.1"
GLB_MAGIC = b"glTF"
GLB_VERSION = 2


def read_obj_bounds(path: str) -> dict:
    """Compute a bounding box from the ``v`` records of an OBJ file."""
    text, encoding = common.read_text(path)
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] != "v":
            continue
        if len(parts) < 4:
            raise SystemExit(f"{path}:{lineno}: vertex requires x y z")
        try:
            x, y, z = (float(value) for value in parts[1:4])
        except ValueError as exc:
            raise SystemExit(f"{path}:{lineno}: non-numeric vertex coordinate") from exc
        if not all(math.isfinite(value) for value in (x, y, z)):
            raise SystemExit(f"{path}:{lineno}: non-finite vertex coordinate")
        xs.append(x)
        ys.append(y)
        zs.append(z)
    if not xs:
        raise SystemExit(f"{path}: no vertices found")
    return {
        "vertex_count": len(xs),
        "min": [min(xs), min(ys), min(zs)],
        "max": [max(xs), max(ys), max(zs)],
        "encoding": encoding,
    }


def check_glb_header(path: str) -> dict:
    """Check the GLB magic, version and declared file length."""
    with open(path, "rb") as fh:
        header = fh.read(12)
    if len(header) < 12:
        raise SystemExit(f"{path}: file is too short to be a GLB")
    magic, version, declared_length = struct.unpack("<4sII", header)
    if magic != GLB_MAGIC:
        raise SystemExit(f"{path}: not a GLB (magic {magic!r})")
    if version != GLB_VERSION:
        raise SystemExit(f"{path}: unsupported GLB version {version}")
    actual_length = Path(path).stat().st_size
    if declared_length != actual_length:
        raise SystemExit(
            f"{path}: GLB header declares {declared_length} bytes but the file "
            f"is {actual_length} bytes"
        )
    return {
        "version": version,
        "declared_length": declared_length,
        "file_size_bytes": actual_length,
    }


def parse_bbox(value: str) -> dict:
    """Parse ``minx,miny,minz,maxx,maxy,maxz`` into a bbox record."""
    tokens = [token for token in re.split(r"[,\s]+", value.strip()) if token]
    if len(tokens) != 6:
        raise SystemExit(
            "--bbox requires six comma-separated values: "
            "minx,miny,minz,maxx,maxy,maxz"
        )
    try:
        values = [float(token) for token in tokens]
    except ValueError as exc:
        raise SystemExit(f"--bbox contains a non-numeric value: {value!r}") from exc
    if not all(math.isfinite(number) for number in values):
        raise SystemExit("--bbox values must be finite")
    minimum = values[:3]
    maximum = values[3:]
    if any(maximum[axis] <= minimum[axis] for axis in range(3)):
        raise SystemExit("--bbox must satisfy maxx > minx, maxy > miny and maxz > minz")
    return bbox_record(minimum, maximum)


def bbox_record(minimum: list[float], maximum: list[float]) -> dict:
    """Build the bbox, centre, span, diagonal and 3D Tiles box values."""
    span = [maximum[axis] - minimum[axis] for axis in range(3)]
    centre = [(maximum[axis] + minimum[axis]) / 2.0 for axis in range(3)]
    half = [span[axis] / 2.0 for axis in range(3)]
    diagonal = math.sqrt(sum(value * value for value in span))
    box = [
        centre[0],
        centre[1],
        centre[2],
        half[0],
        0.0,
        0.0,
        0.0,
        half[1],
        0.0,
        0.0,
        0.0,
        half[2],
    ]
    return {
        "min": minimum,
        "max": maximum,
        "span": span,
        "centre": centre,
        "half_extent": half,
        "diagonal": diagonal,
        "box": box,
    }


def build_tileset(
    content_uri: str, bbox: dict, geometric_error: float, refine: str = "ADD"
) -> dict:
    """Build a single-root 3D Tiles 1.1 tileset document."""
    return {
        "asset": {
            "version": TILESET_VERSION,
            "generator": GENERATOR,
        },
        "geometricError": geometric_error,
        "root": {
            "boundingVolume": {"box": list(bbox["box"])},
            "geometricError": 0,
            "refine": refine,
            "content": {"uri": content_uri},
        },
    }


def copy_content(content_path: str, out_dir: Path) -> tuple[Path, str, bool]:
    """Copy the content next to tileset.json and return its URI."""
    source = Path(content_path)
    destination = out_dir / source.name
    copied = source.resolve() != destination.resolve()
    if copied:
        shutil.copy2(source, destination)
    uri = urllib.parse.quote(destination.name)
    return destination, uri, copied


def render_markdown(report: dict) -> str:
    bbox = report["bounding_box"]
    lines = [
        "# 3D Tiles Publishing Report",
        "",
        "## Summary",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Content | {report['source']['content']['name']} ({report['source']['content_type']}) |",
        f"| Content URI | `{report['tileset']['content_uri']}` |",
        f"| Tileset version | {report['asset_version']} |",
        f"| Bounding box source | {report['source']['bbox_source']} |",
        f"| Centre | {', '.join(common.fmt(value) for value in bbox['centre'])} |",
        f"| Span | {', '.join(common.fmt(value) for value in bbox['span'])} |",
        f"| Geometric error | {common.fmt(report['geometric_error'], 6)} |",
        f"| Refine | {report['refine']} |",
        "",
        "## Warnings",
        "",
    ]
    if report["warnings"]:
        lines.extend(f"- {warning}" for warning in report["warnings"])
    else:
        lines.append("- None")
    lines.extend(["", "## v0.1 limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a minimal single-tile 3D Tiles 1.1 tileset."
    )
    parser.add_argument("content", help="GLB or OBJ content file")
    parser.add_argument(
        "--bbox",
        help="Bounding box minx,miny,minz,maxx,maxy,maxz; required for GLB",
    )
    parser.add_argument("--out-dir", default="tiles_output", help="Output directory")
    parser.add_argument(
        "--geometric-error",
        type=float,
        help="Top-level geometricError; defaults to the bbox diagonal",
    )
    parser.add_argument("--refine", choices=["ADD", "REPLACE"], default="ADD")
    args = parser.parse_args(argv)

    content_path = Path(args.content)
    if not content_path.is_file():
        raise SystemExit(f"Content file not found: {args.content}")
    suffix = content_path.suffix.lower()
    if suffix not in {".obj", ".glb"}:
        raise SystemExit(
            "v0.1 supports OBJ and GLB content only; convert other formats first"
        )

    warnings: list[str] = []
    glb_header = None
    if suffix == ".obj":
        obj_bounds = read_obj_bounds(args.content)
        if args.bbox:
            bbox = parse_bbox(args.bbox)
            bbox_source = "cli_bbox_override_obj"
            warnings.append(
                "Provided --bbox overrides the bounding box computed from OBJ vertices."
            )
        else:
            bbox = bbox_record(obj_bounds["min"], obj_bounds["max"])
            bbox_source = "obj_vertices"
        source_stats = {"obj_vertex_count": obj_bounds["vertex_count"]}
        content_type = "OBJ"
    else:
        glb_header = check_glb_header(args.content)
        if not args.bbox:
            raise SystemExit(
                "--bbox is required for GLB input in v0.1; GLB buffer bounds are "
                "not parsed automatically."
            )
        bbox = parse_bbox(args.bbox)
        bbox_source = "cli_bbox"
        source_stats = {"glb_header": glb_header}
        content_type = "GLB"

    if bbox["diagonal"] == 0:
        raise SystemExit(
            "Bounding box has zero volume; cannot build a 3D Tiles bounding box"
        )
    if any(span == 0 for span in bbox["span"]):
        warnings.append(
            "Bounding box has zero span on at least one axis; the tile is flat "
            "and the box is degenerate."
        )

    if args.geometric_error is None:
        geometric_error = bbox["diagonal"]
    else:
        geometric_error = args.geometric_error
        if not math.isfinite(geometric_error) or geometric_error < 0:
            raise SystemExit("--geometric-error must be a finite non-negative number")
        if geometric_error == 0:
            warnings.append(
                "geometricError is 0; the single tile will never refine its detail."
            )

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    destination, content_uri, copied = copy_content(args.content, out)
    tileset = build_tileset(content_uri, bbox, geometric_error, args.refine)
    tileset_path = out / "tileset.json"
    common.write_json(tileset_path, tileset)

    warnings.append(
        "Single-tile tileset only: no spatial subdivision, LOD levels or point-cloud tiling."
    )
    warnings.append(
        "The tileset contains no CRS metadata; content coordinates, bounding-box "
        "coordinates and units stay in the content frame. No axis conversion is applied."
    )

    report = {
        "schema_version": "0.1",
        "status": "ok",
        "asset_version": TILESET_VERSION,
        "source": {
            "content": common.source_manifest(args.content),
            "content_type": content_type,
            "bbox_source": bbox_source,
            **source_stats,
        },
        "tileset": {
            "path": "tileset.json",
            "content_uri": content_uri,
            "content_copied": copied,
            "content_path": str(destination),
            "content_sha256": common.file_sha256(destination),
        },
        "bounding_box": {
            "frame": "content",
            "min": bbox["min"],
            "max": bbox["max"],
            "span": bbox["span"],
            "centre": bbox["centre"],
            "diagonal": bbox["diagonal"],
            "box": bbox["box"],
        },
        "geometric_error": geometric_error,
        "refine": args.refine,
        "warnings": warnings,
        "limitations": [
            "No spatial subdivision or external tilesets.",
            "No LOD generation or mesh simplification.",
            "Point cloud tiling (XYZ/LAS/LAZ/PLY) is not implemented.",
            "GLB bounds must be supplied with --bbox; the GLB buffers are not parsed.",
            "Only an axis-aligned box bounding volume is generated.",
        ],
    }
    common.write_json(out / "tiling_report.json", report)
    common.write_text(out / "tiling_report.md", render_markdown(report))

    print(
        f"Wrote tileset: {tileset_path} "
        f"(content {content_uri}, bbox from {bbox_source}, "
        f"geometricError {common.fmt(geometric_error, 6)})"
    )
    print(
        "Outputs: "
        + ", ".join(
            [
                str(tileset_path),
                str(destination),
                str(out / "tiling_report.json"),
                str(out / "tiling_report.md"),
            ]
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
