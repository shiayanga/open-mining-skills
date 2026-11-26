#!/usr/bin/env python3
"""Parse DXF drawings into GeoJSON, a feature index, layers and a report.

The parser preserves layer names, entity handles and Z coordinates, expands
block references, flattens curves to polylines and records every skipped
entity. It never edits the source drawing and never assumes units or a CRS.
"""

from __future__ import annotations

import argparse
import csv
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

CURVE_TYPES = {"LWPOLYLINE", "POLYLINE", "SPLINE", "ARC", "CIRCLE", "ELLIPSE"}
TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB"}
SUPPORTED_TYPES = {"POINT", "LINE", "INSERT"} | CURVE_TYPES | TEXT_TYPES


def require_ezdxf():
    try:
        import ezdxf  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "ezdxf is required for DXF parsing. Install it with:\n"
            "  python3 -m pip install ezdxf"
        ) from exc
    return __import__("ezdxf")


def _xyz(value) -> list[float]:
    if hasattr(value, "x"):
        return [float(value.x), float(value.y), float(value.z)]
    seq = list(value)
    return [
        float(seq[0]),
        float(seq[1]),
        float(seq[2]) if len(seq) > 2 else 0.0,
    ]


def _safe_dxf(entity, key: str, default=None):
    """Read a DXF attribute without raising for attributes invalid on this type."""
    try:
        return entity.dxf.get(key, default)
    except Exception:
        return default


def _round_point(point: list[float], precision: int) -> list[float]:
    return [round(float(value), precision) for value in point]


def _dedupe(points: list[list[float]], eps: float = 1e-9) -> list[list[float]]:
    cleaned: list[list[float]] = []
    for point in points:
        if not cleaned:
            cleaned.append(point)
            continue
        if any(abs(a - b) > eps for a, b in zip(point, cleaned[-1])):
            cleaned.append(point)
    return cleaned


def _flatten(entity, tolerance: float) -> list[list[float]]:
    from ezdxf import path as ezpath

    return [_xyz(vertex) for vertex in ezpath.make_path(entity).flattening(tolerance)]


def _is_closed(entity, entity_type: str) -> bool:
    if entity_type in {"CIRCLE", "ELLIPSE"}:
        return True
    value = getattr(entity, "closed", None)
    if value is None:
        value = getattr(entity, "is_closed", False)
    return bool(value)


def _curve_properties(entity, entity_type: str, precision: int) -> dict:
    props: dict = {}
    if entity_type in {"ARC", "CIRCLE"}:
        props["center"] = _round_point(_xyz(entity.dxf.center), precision)
        props["radius"] = float(entity.dxf.radius)
    if entity_type == "ARC":
        props["start_angle"] = float(entity.dxf.start_angle)
        props["end_angle"] = float(entity.dxf.end_angle)
    if entity_type == "ELLIPSE":
        props["center"] = _round_point(_xyz(entity.dxf.center), precision)
        props["major_axis"] = _round_point(_xyz(entity.dxf.major_axis), precision)
        props["ratio"] = float(entity.dxf.ratio)
    if entity_type == "SPLINE":
        props["degree"] = int(entity.dxf.degree)
    if entity_type == "LWPOLYLINE":
        props["source_vertex_count"] = len(entity.get_points("xy"))
    if entity_type == "POLYLINE":
        props["source_vertex_count"] = len(entity.vertices)
        props["is_3d"] = bool(getattr(entity, "is_3d_polyline", False))
    return props


def _text_value(entity, entity_type: str) -> str:
    if entity_type == "MTEXT":
        try:
            return entity.plain_text()
        except Exception:
            return str(getattr(entity, "text", ""))
    return str(_safe_dxf(entity, "text", "") or "")


def build_feature(entity, entity_type: str, block_name: str | None, options: dict):
    """Return (feature, None) or (None, skip_reason)."""
    precision = options["precision"]
    props = {
        "entity_type": entity_type,
        "layer": _safe_dxf(entity, "layer", "0"),
        "handle": _safe_dxf(entity, "handle", ""),
        "block_name": block_name,
    }

    if entity_type == "POINT":
        point = _round_point(_xyz(entity.dxf.location), precision)
        props["geometry_source"] = "entity_point"
        return (
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": point},
                "properties": props,
            },
            None,
        )

    if entity_type == "LINE":
        points = [
            _round_point(_xyz(entity.dxf.start), precision),
            _round_point(_xyz(entity.dxf.end), precision),
        ]
        props.update({"geometry_source": "entity_vertices", "closed": False})
        return (
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": points},
                "properties": props,
            },
            None,
        )

    if entity_type in TEXT_TYPES:
        if not options["include_text"]:
            return None, "text excluded by --no-text"
        insert = _round_point(_xyz(entity.dxf.insert), precision)
        props["geometry_source"] = "insertion_point"
        props["text"] = _text_value(entity, entity_type)
        height = _safe_dxf(entity, "height")
        if height is None:
            height = _safe_dxf(entity, "char_height")
        if height is not None:
            props["height"] = float(height)
        rotation = _safe_dxf(entity, "rotation")
        if rotation is not None:
            props["rotation"] = float(rotation)
        return (
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": insert},
                "properties": props,
            },
            None,
        )

    if entity_type in CURVE_TYPES:
        try:
            points = _dedupe(_flatten(entity, options["tolerance"]))
        except Exception as exc:
            return None, f"flattening failed: {exc}"
        if len(points) < 2:
            return None, "fewer than 2 points after flattening"
        points = [_round_point(point, precision) for point in points]

        closed = _is_closed(entity, entity_type)
        distinct = 0
        if closed:
            if points[0] != points[-1]:
                points.append(points[0])
            distinct = len({tuple(point) for point in points[:-1]})

        props["geometry_source"] = "flattened"
        props["closed"] = closed
        props["output_vertex_count"] = len(points) - (1 if closed else 0)
        props.update(_curve_properties(entity, entity_type, precision))

        if closed and distinct >= 3:
            geometry = {"type": "Polygon", "coordinates": [points]}
        else:
            geometry = {"type": "LineString", "coordinates": points}
        return {"type": "Feature", "geometry": geometry, "properties": props}, None

    return None, "unsupported entity type"


def _iter_coordinates(feature: dict):
    geometry = feature["geometry"]
    if geometry["type"] == "Point":
        yield geometry["coordinates"]
    elif geometry["type"] == "LineString":
        yield from geometry["coordinates"]
    elif geometry["type"] == "Polygon":
        yield from geometry["coordinates"][0]


def _extent(features: list[dict]) -> tuple[dict | None, dict | None]:
    xs, ys, zs = [], [], []
    for feature in features:
        for point in _iter_coordinates(feature):
            xs.append(point[0])
            ys.append(point[1])
            zs.append(point[2])
    if not xs:
        return None, None
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
    z_range = {"min": min(zs), "max": max(zs), "span": max(zs) - min(zs)}
    return extent, z_range


def _layer_records(doc, source_counts: Counter, feature_counts: Counter) -> list[dict]:
    records = []
    for layer in doc.layers:
        name = layer.dxf.name
        try:
            is_on = bool(layer.is_on())
        except Exception:
            is_on = None
        try:
            is_frozen = bool(layer.is_frozen())
        except Exception:
            is_frozen = None
        try:
            is_locked = bool(layer.is_locked())
        except Exception:
            is_locked = None
        records.append(
            {
                "name": name,
                "color": layer.dxf.get("color", 7),
                "linetype": layer.dxf.get("linetype", ""),
                "is_on": is_on,
                "is_frozen": is_frozen,
                "is_locked": is_locked,
                "source_entity_count": source_counts.get(name, 0),
                "feature_count": feature_counts.get(name, 0),
            }
        )
    return records


def parse_dxf(
    path: str,
    include_text: bool = True,
    tolerance: float = 0.5,
    max_block_depth: int = 5,
    precision: int = 6,
) -> dict:
    if tolerance <= 0:
        raise SystemExit("--tolerance must be greater than 0")
    if precision < 0:
        raise SystemExit("--precision must be zero or greater")

    ezdxf = require_ezdxf()
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
    source_counts = Counter(entity.dxftype() for entity in msp)
    features: list[dict] = []
    skipped: list[dict] = []
    feature_counts: Counter = Counter()
    layer_feature_counts: Counter = Counter()
    options = {
        "include_text": include_text,
        "tolerance": tolerance,
        "precision": precision,
    }

    def record_skip(entity, entity_type: str, block_name, reason: str) -> None:
        skipped.append(
            {
                "entity_type": entity_type,
                "handle": _safe_dxf(entity, "handle", "") if hasattr(entity, "dxf") else "",
                "layer": _safe_dxf(entity, "layer", "0") if hasattr(entity, "dxf") else "",
                "block_name": block_name,
                "reason": reason,
            }
        )

    def process(entity, block_name, depth: int) -> None:
        entity_type = entity.dxftype()

        if entity_type == "INSERT":
            if depth >= max_block_depth:
                record_skip(entity, entity_type, block_name, "maximum block expansion depth reached")
                return
            name = _safe_dxf(entity, "name", block_name)
            try:
                children = list(entity.virtual_entities())
            except Exception as exc:
                record_skip(entity, entity_type, block_name, f"block expansion failed: {exc}")
                return
            if not children:
                record_skip(entity, entity_type, block_name, "block reference produced no entities")
                return
            for child in children:
                process(child, name, depth + 1)
            return

        if entity_type not in SUPPORTED_TYPES:
            record_skip(entity, entity_type, block_name, "unsupported entity type")
            return

        feature, reason = build_feature(entity, entity_type, block_name, options)
        if feature is None:
            record_skip(entity, entity_type, block_name, reason or "not exported")
            return

        feature["properties"]["feature_id"] = f"F{len(features) + 1:06d}"
        features.append(feature)
        feature_counts[entity_type] += 1
        layer_feature_counts[feature["properties"]["layer"]] += 1

    for entity in msp:
        process(entity, None, 0)

    extent, z_range = _extent(features)
    try:
        units_code = int(doc.header.get("$INSUNITS", 0) or 0)
    except (TypeError, ValueError):
        units_code = 0
    units_name = UNITS.get(units_code, f"Unknown ({units_code})")
    measurement = doc.header.get("$MEASUREMENT", None)
    clue = "UNKNOWN"
    if extent:
        clue = common.magnitude_clue(
            extent["min_x"], extent["min_y"], extent["max_x"], extent["max_y"]
        )

    unsupported_types = Counter(
        item["entity_type"]
        for item in skipped
        if item["reason"] == "unsupported entity type"
    )

    if not features:
        warnings.append("No features were extracted from modelspace.")
    if skipped:
        warnings.append(
            f"{len(skipped)} entity/entities were not exported; see skipped_details."
        )
    if unsupported_types:
        warnings.append(
            "Unsupported entity types: "
            + ", ".join(f"{name} ({count})" for name, count in sorted(unsupported_types.items()))
            + "."
        )
    if units_code == 0:
        warnings.append(
            "Drawing units are unitless ($INSUNITS=0); confirm units before modeling."
        )
    if features and z_range and z_range["span"] < 1e-9:
        warnings.append("All exported geometry has the same Z value; check for missing elevations.")
    if clue == "DEGREE_CANDIDATE":
        warnings.append(
            "Coordinates fall within geographic degree ranges; confirm whether they are longitude/latitude."
        )
    elif clue == "LOCAL_OR_UNKNOWN":
        warnings.append(
            "Coordinates look like a local or engineering grid; the CRS is unknown."
        )

    report = {
        "file": Path(path).name,
        "format": "DXF",
        "format_version": doc.dxfversion,
        "format_version_name": VERSIONS.get(doc.dxfversion, "Unknown"),
        "units": units_name,
        "units_code": units_code,
        "measurement": measurement,
        "coordinate_system": "UNKNOWN",
        "coordinate_clue": clue,
        "source_entity_statistics": dict(sorted(source_counts.items())),
        "source_entity_total": sum(source_counts.values()),
        "feature_entity_statistics": dict(sorted(feature_counts.items())),
        "feature_count": len(features),
        "skipped_count": len(skipped),
        "skipped_details": skipped[:100],
        "unsupported_types": dict(sorted(unsupported_types.items())),
        "extent": extent,
        "z_range": z_range,
        "options": options
        | {"max_block_depth": max_block_depth},
        "warnings": warnings,
        "source": common.source_manifest(path),
    }
    return {
        "features": features,
        "layers": _layer_records(doc, source_counts, layer_feature_counts),
        "report": report,
    }


def render_markdown(result: dict) -> str:
    report = result["report"]
    extent = report.get("extent") or {}
    lines = [
        "# CAD Parse Report",
        "",
        f"- **File**: `{report['file']}`",
        f"- **Format**: DXF {report['format_version']} ({report['format_version_name']})",
        f"- **Units**: {report['units']} (code {report['units_code']})",
        f"- **Coordinate system**: {report['coordinate_system']}",
        f"- **Coordinate clue**: {report['coordinate_clue']}",
        f"- **Features exported**: {report['feature_count']}",
        f"- **Entities skipped**: {report['skipped_count']}",
    ]
    if extent:
        lines.append(
            f"- **Extent**: X {common.fmt(extent['min_x'])} .. {common.fmt(extent['max_x'])}, "
            f"Y {common.fmt(extent['min_y'])} .. {common.fmt(extent['max_y'])}, "
            f"Z {common.fmt(extent['min_z'])} .. {common.fmt(extent['max_z'])}"
        )
    lines.extend(
        [
            "",
            "## Options",
            "",
            f"- Text included: {report['options']['include_text']}",
            f"- Flatten tolerance: {report['options']['tolerance']}",
            f"- Max block depth: {report['options']['max_block_depth']}",
            f"- Coordinate precision: {report['options']['precision']}",
            "",
            "## Source entity statistics",
            "",
            "| Type | Count |",
            "|---|---:|",
        ]
    )
    for name, count in report["source_entity_statistics"].items():
        lines.append(f"| {name} | {count} |")
    lines.extend(
        [
            "",
            "## Exported feature statistics",
            "",
            "| Type | Count |",
            "|---|---:|",
        ]
    )
    for name, count in report["feature_entity_statistics"].items():
        lines.append(f"| {name} | {count} |")
    lines.extend(
        [
            "",
            "## Layers",
            "",
            "| Layer | Color | Source entities | Features |",
            "|---|---:|---:|---:|",
        ]
    )
    for layer in result["layers"]:
        lines.append(
            f"| {layer['name']} | {layer['color']} | "
            f"{layer['source_entity_count']} | {layer['feature_count']} |"
        )
    lines.extend(["", "## Skipped entities", ""])
    if report["skipped_details"]:
        lines.extend(["| Type | Layer | Handle | Reason |", "|---|---|---|---|"])
        for item in report["skipped_details"]:
            lines.append(
                f"| {item['entity_type']} | {item['layer']} | "
                f"{item['handle']} | {item['reason']} |"
            )
    else:
        lines.append("- None")
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


def _feature_z_range(feature: dict) -> tuple[float | None, float | None]:
    zs = [point[2] for point in _iter_coordinates(feature)]
    if not zs:
        return None, None
    return min(zs), max(zs)


def _vertex_count(feature: dict) -> int:
    props = feature["properties"]
    if "output_vertex_count" in props:
        return int(props["output_vertex_count"])
    return sum(1 for _ in _iter_coordinates(feature))


def write_outputs(result: dict, out_dir: str) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = result["report"]

    geojson = {
        "type": "FeatureCollection",
        "mine_metadata": {
            "generated_by": "mine-cad-parser v0.1",
            "source": report["source"],
            "units": report["units"],
            "coordinate_system": report["coordinate_system"],
            "coordinate_clue": report["coordinate_clue"],
        },
        "features": result["features"],
    }
    layers_doc = {
        "generated_by": "mine-cad-parser v0.1",
        "source": report["source"],
        "layers": result["layers"],
    }

    paths = {
        "geojson": str(out / "geometry.geojson"),
        "layers": str(out / "layers.json"),
        "report": str(out / "parse_report.json"),
        "markdown": str(out / "parse_report.md"),
        "csv": str(out / "geometry_index.csv"),
    }
    common.write_json(paths["geojson"], geojson)
    common.write_json(paths["layers"], layers_doc)
    common.write_json(paths["report"], report)
    common.write_text(paths["markdown"], render_markdown(result))

    fields = [
        "feature_id",
        "entity_type",
        "layer",
        "handle",
        "block_name",
        "geometry_type",
        "vertex_count",
        "closed",
        "min_z",
        "max_z",
        "text",
    ]
    with open(paths["csv"], "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for feature in result["features"]:
            props = feature["properties"]
            min_z, max_z = _feature_z_range(feature)
            writer.writerow(
                {
                    "feature_id": props.get("feature_id", ""),
                    "entity_type": props.get("entity_type", ""),
                    "layer": props.get("layer", ""),
                    "handle": props.get("handle", ""),
                    "block_name": props.get("block_name") or "",
                    "geometry_type": feature["geometry"]["type"],
                    "vertex_count": _vertex_count(feature),
                    "closed": props.get("closed", ""),
                    "min_z": min_z,
                    "max_z": max_z,
                    "text": props.get("text", ""),
                }
            )
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse a DXF drawing into GeoJSON and reports.")
    parser.add_argument("path", help="Path to the DXF file")
    parser.add_argument("--out-dir", default="cad_parse_output", help="Output directory")
    parser.add_argument("--no-text", dest="include_text", action="store_false", default=True)
    parser.add_argument("--tolerance", type=float, default=0.5, help="Curve flattening tolerance in drawing units")
    parser.add_argument("--max-block-depth", type=int, default=5)
    parser.add_argument("--precision", type=int, default=6)
    args = parser.parse_args(argv)

    result = parse_dxf(
        args.path,
        include_text=args.include_text,
        tolerance=args.tolerance,
        max_block_depth=args.max_block_depth,
        precision=args.precision,
    )
    paths = write_outputs(result, args.out_dir)
    report = result["report"]
    print(
        f"Parsed {report['file']}: {report['feature_count']} features, "
        f"{report['skipped_count']} skipped, {len(result['layers'])} layers; "
        f"warnings: {len(report['warnings'])}"
    )
    print(f"Outputs: {paths['geojson']}, {paths['csv']}, {paths['layers']}, {paths['report']}, {paths['markdown']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
