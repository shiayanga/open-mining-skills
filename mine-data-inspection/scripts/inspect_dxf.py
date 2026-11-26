#!/usr/bin/env python3
"""Inspect DXF drawings and report structure, layers, entities and extents.

DXF does not store a coordinate reference system, so the inspector reports
coordinate clues only and never claims a CRS.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import common

UNITS = {
    0: "Unitless",
    1: "Inches",
    2: "Feet",
    3: "Miles",
    4: "Millimeters",
    5: "Centimeters",
    6: "Meters",
    7: "Kilometers",
    8: "Microinches",
    9: "Mils",
    10: "Yards",
    11: "Angstroms",
    12: "Nanometers",
    13: "Microns",
    14: "Decimeters",
    15: "Decameters",
    16: "Hectometers",
    17: "Gigameters",
    18: "Astronomical units",
    19: "Light years",
    20: "Parsecs",
}

VERSIONS = {
    "AC1009": "R12",
    "AC1012": "R13",
    "AC1014": "R14",
    "AC1015": "AutoCAD 2000",
    "AC1018": "AutoCAD 2004",
    "AC1021": "AutoCAD 2007",
    "AC1024": "AutoCAD 2010",
    "AC1027": "AutoCAD 2013",
    "AC1032": "AutoCAD 2018",
}

THREE_D_TYPES = {
    "3DFACE",
    "3DPOLYLINE",
    "MESH",
    "3DSOLID",
    "BODY",
    "REGION",
    "SURFACE",
    "EXTRUDEDSURFACE",
    "LOFTEDSURFACE",
    "REVOLVEDSURFACE",
    "SWEPTSURFACE",
}

PROXY_TYPES = {"ACAD_PROXY_ENTITY", "ACAD_PROXY_OBJECT"}


def _require_ezdxf():
    try:
        import ezdxf  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "ezdxf is required for DXF inspection. Install it with:\n"
            "  python3 -m pip install ezdxf"
        ) from exc
    return __import__("ezdxf")


def _extent_from_bbox(msp) -> tuple[dict | None, str | None]:
    try:
        from ezdxf import bbox

        box = bbox.extents(msp)
        if not box.has_data:
            return None, "Drawing has no computable bounding box."
        extmin, extmax = box.extmin, box.extmax
        return (
            {
                "min_x": extmin.x,
                "min_y": extmin.y,
                "min_z": extmin.z,
                "max_x": extmax.x,
                "max_y": extmax.y,
                "max_z": extmax.z,
                "span_x": extmax.x - extmin.x,
                "span_y": extmax.y - extmin.y,
                "span_z": extmax.z - extmin.z,
            },
            None,
        )
    except Exception as exc:  # pragma: no cover - depends on file content
        return None, f"Bounding box calculation failed: {exc}"


def inspect_dxf(path: str) -> dict:
    ezdxf = _require_ezdxf()
    warnings: list[str] = []
    try:
        doc = ezdxf.readfile(path)
    except Exception as exc:
        try:
            doc = ezdxf.recover.readfile(path)
        except Exception as recovery_exc:
            raise SystemExit(
                f"Unable to read DXF: {exc}; recovery failed: {recovery_exc}"
            )
        warnings.append(f"DXF required recovery mode: {exc}")
    msp = doc.modelspace()

    entity_counts = Counter(entity.dxftype() for entity in msp)
    layer_counts = Counter(entity.dxf.layer for entity in msp)

    layers = []
    for layer in doc.layers:
        try:
            color = layer.dxf.get("color", 7)
        except Exception:
            color = 7
        layers.append(
            {
                "name": layer.dxf.name,
                "color": color,
                "entity_count": layer_counts.get(layer.dxf.name, 0),
            }
        )

    extent, extent_warning = _extent_from_bbox(msp)
    if extent_warning:
        warnings.append(extent_warning)

    has_3d = any(name in entity_counts for name in THREE_D_TYPES)
    if extent and extent["span_z"] > 1e-9:
        has_3d = True
    if not has_3d:
        for entity in msp:
            if entity.dxftype() == "POLYLINE" and getattr(entity, "is_3d_polyline", False):
                has_3d = True
                break

    try:
        units_code = int(doc.header.get("$INSUNITS", 0) or 0)
    except (TypeError, ValueError):
        units_code = 0
    units_name = UNITS.get(units_code, f"Unknown ({units_code})")
    measurement = doc.header.get("$MEASUREMENT", None)

    block_names = [block.name for block in doc.blocks if not block.name.startswith("*")]
    proxy_count = sum(count for name, count in entity_counts.items() if name in PROXY_TYPES)

    if not entity_counts:
        warnings.append("Modelspace contains no entities.")
    if units_code == 0:
        warnings.append(
            "Drawing units are unitless ($INSUNITS=0); confirm units before modeling."
        )
    if not has_3d:
        warnings.append(
            "No 3D geometry detected; Z coordinates may be absent or all zero."
        )
    if proxy_count:
        warnings.append(
            f"{proxy_count} proxy entity/entities found; their geometry may not be inspectable."
        )

    clue = "UNKNOWN"
    if extent:
        clue = common.magnitude_clue(
            extent["min_x"], extent["min_y"], extent["max_x"], extent["max_y"]
        )

    return {
        "file": str(Path(path).name),
        "format": "DXF",
        "format_version": doc.dxfversion,
        "format_version_name": VERSIONS.get(doc.dxfversion, "Unknown"),
        "units": units_name,
        "units_code": units_code,
        "measurement": measurement,
        "coordinate_system": "UNKNOWN",
        "coordinate_clue": clue,
        "entity_total": sum(entity_counts.values()),
        "entity_statistics": dict(sorted(entity_counts.items())),
        "layers": layers,
        "blocks": {
            "defined": len(block_names),
            "inserts": entity_counts.get("INSERT", 0),
            "names": block_names[:50],
        },
        "text_entities": entity_counts.get("TEXT", 0) + entity_counts.get("MTEXT", 0),
        "has_3d_entities": has_3d,
        "extent": extent,
        "warnings": warnings,
        "source": common.source_manifest(path),
    }


def render_markdown(report: dict) -> str:
    extent = report.get("extent") or {}
    lines = [
        "# Data Inspection Report",
        "",
        f"- **File**: `{report['file']}`",
        f"- **Format**: DXF {report['format_version']} "
        f"({report['format_version_name']})",
        f"- **Units**: {report['units']} (code {report['units_code']})",
        f"- **Coordinate system**: {report['coordinate_system']}",
        f"- **Coordinate clue**: {report['coordinate_clue']}",
        f"- **Entities**: {report['entity_total']}",
        f"- **3D entities**: {'yes' if report['has_3d_entities'] else 'no'}",
        f"- **Text entities**: {report['text_entities']}",
    ]
    if extent:
        lines.append(
            f"- **Extent**: X {common.fmt(extent['min_x'])} .. {common.fmt(extent['max_x'])}, "
            f"Y {common.fmt(extent['min_y'])} .. {common.fmt(extent['max_y'])}, "
            f"Z {common.fmt(extent['min_z'])} .. {common.fmt(extent['max_z'])}"
        )
    else:
        lines.append("- **Extent**: not available")
    lines.extend(["", "## Entity statistics", "", "| Type | Count |", "|---|---:|"])
    for name, count in report["entity_statistics"].items():
        lines.append(f"| {name} | {count} |")
    lines.extend(["", "## Layers", "", "| Layer | Color | Entities |", "|---|---:|---:|"])
    for layer in report["layers"]:
        lines.append(f"| {layer['name']} | {layer['color']} | {layer['entity_count']} |")
    lines.extend(["", "## Warnings", ""])
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
    parser = argparse.ArgumentParser(description="Inspect a DXF drawing.")
    parser.add_argument("path", help="Path to the DXF file")
    parser.add_argument("--output", help="Write the JSON report to this path")
    parser.add_argument("--markdown", help="Write a Markdown report to this path")
    parser.add_argument("--manifest", help="Write a source manifest JSON to this path")
    args = parser.parse_args(argv)

    report = inspect_dxf(args.path)
    if args.output:
        common.write_json(args.output, report)
    if args.markdown:
        common.write_text(args.markdown, render_markdown(report))
    if args.manifest:
        common.write_json(args.manifest, report["source"])

    extent = report.get("extent") or {}
    print(
        f"Inspected {report['file']}: DXF {report['format_version']}, "
        f"{report['entity_total']} entities, {len(report['layers'])} layers, "
        f"Z {common.fmt(extent.get('min_z'))}..{common.fmt(extent.get('max_z'))}, "
        f"warnings: {len(report['warnings'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
