#!/usr/bin/env python3
"""Prepare and validate a GemPy-oriented geological model definition.

v0.1 does not run GemPy and does not interpolate surfaces. It reads geological
interface points (and optional borehole observations), validates the data, and
writes a JSON definition containing series, surfaces, interfaces, orientations,
extent and resolution, plus a validation report.

The JSON follows GemPy concepts but is not a GemPy project file. A separate
GemPy setup step must consume it and perform implicit interpolation.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

import common

GENERATOR = "open-mining-skills mine-geological-modeling v0.1"
DEFAULT_RESOLUTION = [50, 50, 50]

FIELD_ALIASES = {
    "x": {"x", "easting", "east", "东坐标", "x坐标"},
    "y": {"y", "northing", "north", "北坐标", "y坐标"},
    "z": {"z", "elevation", "elev", "height", "高程", "z坐标"},
    "series": {"series", "group", "sequence", "地层序列", "系"},
    "surface": {"surface", "interface", "horizon", "地层", "界面", "层位"},
    "dip": {"dip", "dip_deg", "dip_angle", "dip(deg)", "倾角"},
    "azimuth": {
        "azimuth",
        "azimuth_deg",
        "azimuth(deg)",
        "dip_direction",
        "dip_azimuth",
        "倾向",
    },
}

BOREHOLE_ALIASES = {
    "borehole_id": {"borehole_id", "borehole", "hole_id", "hole", "id", "钻孔编号", "钻孔"},
    "x": FIELD_ALIASES["x"],
    "y": FIELD_ALIASES["y"],
    "z": FIELD_ALIASES["z"],
    "series": FIELD_ALIASES["series"],
    "surface": FIELD_ALIASES["surface"],
}

REQUIRED_INTERFACE_FIELDS = ("x", "y", "z", "series", "surface")
REQUIRED_BOREHOLE_FIELDS = ("borehole_id", "x", "y", "z", "series", "surface")

EXTENT_ORDER = ["x_min", "x_max", "y_min", "y_max", "z_min", "z_max"]
ORIENTATION_CONVENTION = {
    "dip": "degrees from horizontal; 0 = horizontal, 90 = vertical",
    "azimuth": "degrees clockwise from +Y (north); 0 = north, 90 = east",
    "polarity": 1,
}

LIMITATIONS = [
    "GemPy is not invoked; no implicit scalar field or geological surface is generated.",
    "Ore-body extent, grade or tonnage cannot be inferred from these points alone.",
    "Borehole observations are recorded as evidence only and are not converted into interface points.",
    "No CRS or unit conversion is applied; both are recorded as UNKNOWN.",
    "Series order defaults to first appearance and must be verified against stratigraphy.",
    "Model extent and resolution are user decisions; the default extent equals the data bounds.",
]


# ---------------------------------------------------------------------------
# Table reading
# ---------------------------------------------------------------------------


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


def _read_table(
    path: str, delimiter: str | None, encoding: str | None
) -> tuple[list[tuple[int, str]], list[list[str]], str | None, str]:
    text, used_encoding = common.read_text(path, encoding)
    numbered = [
        (lineno, line.strip())
        for lineno, line in enumerate(text.splitlines(), 1)
        if line.strip() and not line.strip().startswith("#")
    ]
    if not numbered:
        raise SystemExit(f"{path}: file contains no data rows")
    sample_lines = [line for _, line in numbered[:50]]
    if delimiter is None:
        delimiter = detect_delimiter(sample_lines)
    sample_rows = [split_line(line, delimiter) for line in sample_lines]
    return numbered, sample_rows, delimiter, used_encoding


def _looks_like_header(row: list[str], aliases: dict[str, set[str]]) -> bool:
    known = set()
    for names in aliases.values():
        known |= names
    return any(token.strip().lower() in known for token in row)


def _map_header(
    header: list[str],
    aliases: dict[str, set[str]],
    required: tuple[str, ...],
    path: str,
) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for field, names in aliases.items():
        for position, name in enumerate(header):
            if name.strip().lower() in names:
                mapping[field] = position
                break
    missing = [field for field in required if field not in mapping]
    if missing:
        raise SystemExit(
            f"{path}: missing required columns: {', '.join(missing)}; "
            f"header was {header}"
        )
    return mapping


def _column_positions(mapping: dict[str, int], fields: set[str]) -> dict[str, int | None]:
    return {
        field: (mapping[field] + 1 if field in mapping else None) for field in fields
    }


def _text(row: list[str], mapping: dict[str, int], field: str) -> str:
    position = mapping.get(field)
    if position is None or position >= len(row):
        return ""
    return row[position].strip()


def _issue(
    code: str,
    message: str,
    line: int | None = None,
    field: str | None = None,
    **extra: object,
) -> dict:
    item: dict = {"code": code, "message": message}
    if line is not None:
        item["line"] = line
    if field is not None:
        item["field"] = field
    item.update(extra)
    return item


def _number(
    text: str,
    *,
    line: int,
    field: str,
    errors: list[dict],
    code: str,
    required: bool,
) -> float | None:
    if text == "":
        if required:
            errors.append(
                _issue("MISSING_VALUE", f"Missing value for {field}", line, field)
            )
        return None
    try:
        value = float(text)
    except ValueError:
        errors.append(
            _issue(code, f"Non-numeric {field} {text!r}", line, field, value=text)
        )
        return None
    if not math.isfinite(value):
        errors.append(
            _issue(code, f"Non-finite {field}", line, field, value=text)
        )
        return None
    return value


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_interfaces(
    path: str, delimiter: str | None = None, encoding: str | None = None
) -> dict:
    """Load and validate interface points without cross-row checks."""
    numbered, sample_rows, delimiter, used_encoding = _read_table(
        path, delimiter, encoding
    )
    has_header = _looks_like_header(sample_rows[0], FIELD_ALIASES)
    if has_header:
        header = sample_rows[0]
        mapping = _map_header(header, FIELD_ALIASES, REQUIRED_INTERFACE_FIELDS, path)
        data_rows = [
            (line, split_line(raw, delimiter)) for line, raw in numbered[1:]
        ]
        header_line = numbered[0][0]
    else:
        header = None
        header_line = None
        mapping = {"x": 0, "y": 1, "z": 2, "series": 3, "surface": 4, "dip": 5, "azimuth": 6}
        data_rows = [
            (line, split_line(raw, delimiter)) for line, raw in numbered
        ]

    points: list[dict] = []
    orientations: list[dict] = []
    errors: list[dict] = []
    warnings: list[dict] = []
    skipped = 0

    for line, row in data_rows:
        x = _number(
            _text(row, mapping, "x"),
            line=line,
            field="x",
            errors=errors,
            code="NON_NUMERIC_COORDINATE",
            required=True,
        )
        y = _number(
            _text(row, mapping, "y"),
            line=line,
            field="y",
            errors=errors,
            code="NON_NUMERIC_COORDINATE",
            required=True,
        )
        z = _number(
            _text(row, mapping, "z"),
            line=line,
            field="z",
            errors=errors,
            code="NON_NUMERIC_COORDINATE",
            required=True,
        )
        series = _text(row, mapping, "series")
        surface = _text(row, mapping, "surface")
        if not series:
            errors.append(
                _issue("MISSING_SERIES", "Series name is empty", line, "series")
            )
        if not surface:
            errors.append(
                _issue("MISSING_SURFACE", "Surface name is empty", line, "surface")
            )

        dip_text = _text(row, mapping, "dip")
        azimuth_text = _text(row, mapping, "azimuth")
        dip = _number(
            dip_text,
            line=line,
            field="dip",
            errors=errors,
            code="NON_NUMERIC_DIP",
            required=False,
        )
        azimuth = _number(
            azimuth_text,
            line=line,
            field="azimuth",
            errors=errors,
            code="NON_NUMERIC_AZIMUTH",
            required=False,
        )
        if dip is not None and not 0.0 <= dip <= 90.0:
            errors.append(
                _issue(
                    "DIP_OUT_OF_RANGE",
                    f"Dip {dip} is outside the valid range 0-90 degrees",
                    line,
                    "dip",
                    value=dip,
                )
            )
            dip = None
        if azimuth is not None and not 0.0 <= azimuth <= 360.0:
            errors.append(
                _issue(
                    "AZIMUTH_OUT_OF_RANGE",
                    f"Azimuth {azimuth} is outside the valid range 0-360 degrees",
                    line,
                    "azimuth",
                    value=azimuth,
                )
            )
            azimuth = None

        if x is None or y is None or z is None or not series or not surface:
            skipped += 1
            continue

        point = {
            "x": x,
            "y": y,
            "z": z,
            "series": series,
            "surface": surface,
            "source_line": line,
        }
        points.append(point)

        has_dip = dip_text != ""
        has_azimuth = azimuth_text != ""
        if has_dip and has_azimuth:
            if dip is not None and azimuth is not None:
                orientations.append(
                    {
                        "x": x,
                        "y": y,
                        "z": z,
                        "series": series,
                        "surface": surface,
                        "dip": dip,
                        "azimuth": azimuth,
                        "polarity": 1,
                        "source_line": line,
                    }
                )
        elif has_dip or has_azimuth:
            warnings.append(
                _issue(
                    "INCOMPLETE_ORIENTATION",
                    "Dip and azimuth must both be present to create an orientation; "
                    "this row contributes an interface point only",
                    line,
                    "dip" if has_dip else "azimuth",
                )
            )

    return {
        "points": points,
        "orientations": orientations,
        "errors": errors,
        "warnings": warnings,
        "row_count": len(data_rows),
        "skipped_rows": skipped,
        "has_header": has_header,
        "header_line": header_line,
        "delimiter": delimiter if delimiter is not None else "whitespace",
        "encoding": used_encoding,
        "columns": _column_positions(mapping, set(FIELD_ALIASES)),
    }


def load_boreholes(
    path: str, delimiter: str | None = None, encoding: str | None = None
) -> dict:
    """Load borehole observations as optional geological evidence."""
    numbered, sample_rows, delimiter, used_encoding = _read_table(
        path, delimiter, encoding
    )
    has_header = _looks_like_header(sample_rows[0], BOREHOLE_ALIASES)
    if has_header:
        header = sample_rows[0]
        mapping = _map_header(header, BOREHOLE_ALIASES, REQUIRED_BOREHOLE_FIELDS, path)
        data_rows = [
            (line, split_line(raw, delimiter)) for line, raw in numbered[1:]
        ]
        header_line = numbered[0][0]
    else:
        header = None
        header_line = None
        mapping = {
            "borehole_id": 0,
            "x": 1,
            "y": 2,
            "z": 3,
            "series": 4,
            "surface": 5,
        }
        data_rows = [
            (line, split_line(raw, delimiter)) for line, raw in numbered
        ]

    observations: list[dict] = []
    errors: list[dict] = []
    warnings: list[dict] = []
    skipped = 0

    for line, row in data_rows:
        borehole_id = _text(row, mapping, "borehole_id")
        series = _text(row, mapping, "series")
        surface = _text(row, mapping, "surface")
        if not borehole_id:
            errors.append(
                _issue(
                    "MISSING_BOREHOLE_ID",
                    "Borehole id is empty",
                    line,
                    "borehole_id",
                )
            )
        if not series:
            errors.append(
                _issue("MISSING_SERIES", "Series name is empty", line, "series")
            )
        if not surface:
            errors.append(
                _issue("MISSING_SURFACE", "Surface name is empty", line, "surface")
            )
        x = _number(
            _text(row, mapping, "x"),
            line=line,
            field="x",
            errors=errors,
            code="NON_NUMERIC_COORDINATE",
            required=True,
        )
        y = _number(
            _text(row, mapping, "y"),
            line=line,
            field="y",
            errors=errors,
            code="NON_NUMERIC_COORDINATE",
            required=True,
        )
        z = _number(
            _text(row, mapping, "z"),
            line=line,
            field="z",
            errors=errors,
            code="NON_NUMERIC_COORDINATE",
            required=True,
        )
        if not borehole_id or not series or not surface or x is None or y is None or z is None:
            skipped += 1
            continue
        observations.append(
            {
                "borehole_id": borehole_id,
                "x": x,
                "y": y,
                "z": z,
                "series": series,
                "surface": surface,
                "source_line": line,
            }
        )

    return {
        "observations": observations,
        "errors": errors,
        "warnings": warnings,
        "row_count": len(data_rows),
        "skipped_rows": skipped,
        "has_header": has_header,
        "header_line": header_line,
        "delimiter": delimiter if delimiter is not None else "whitespace",
        "encoding": used_encoding,
        "columns": _column_positions(mapping, set(BOREHOLE_ALIASES)),
    }


# ---------------------------------------------------------------------------
# Option parsing
# ---------------------------------------------------------------------------


def parse_extent(value: str) -> dict:
    """Parse GemPy-order extent ``xmin,xmax,ymin,ymax,zmin,zmax``."""
    tokens = [token for token in re.split(r"[,\s]+", value.strip()) if token]
    if len(tokens) != 6:
        raise SystemExit(
            "--extent requires six values in GemPy order: "
            "xmin,xmax,ymin,ymax,zmin,zmax"
        )
    try:
        values = [float(token) for token in tokens]
    except ValueError as exc:
        raise SystemExit(f"--extent contains a non-numeric value: {value!r}") from exc
    if not all(math.isfinite(number) for number in values):
        raise SystemExit("--extent values must be finite")
    xmin, xmax, ymin, ymax, zmin, zmax = values
    if xmax <= xmin or ymax <= ymin or zmax <= zmin:
        raise SystemExit("--extent must satisfy xmax > xmin, ymax > ymin and zmax > zmin")
    return {
        "min": [xmin, ymin, zmin],
        "max": [xmax, ymax, zmax],
        "gem_py": [xmin, xmax, ymin, ymax, zmin, zmax],
    }


def parse_resolution(value: str) -> list[int]:
    tokens = [token for token in re.split(r"[,\s]+", value.strip()) if token]
    if len(tokens) != 3:
        raise SystemExit("--resolution requires three values: nx,ny,nz")
    try:
        resolution = [int(token) for token in tokens]
    except ValueError as exc:
        raise SystemExit(f"--resolution must contain integers: {value!r}") from exc
    if any(number <= 0 for number in resolution):
        raise SystemExit("--resolution values must be greater than 0")
    return resolution


def parse_series_order(value: str) -> list[str]:
    tokens = [token for token in re.split(r"[,\s]+", value.strip()) if token]
    if not tokens:
        raise SystemExit("--series-order must contain at least one series name")
    if len(set(tokens)) != len(tokens):
        raise SystemExit("--series-order contains duplicate names")
    return tokens


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _bounds(points: list[dict]) -> tuple[list[float], list[float]]:
    minimum = [min(point[axis] for point in points) for axis in ("x", "y", "z")]
    maximum = [max(point[axis] for point in points) for axis in ("x", "y", "z")]
    return minimum, maximum


def _gem_py_extent(minimum: list[float], maximum: list[float]) -> list[float]:
    return [
        minimum[0],
        maximum[0],
        minimum[1],
        maximum[1],
        minimum[2],
        maximum[2],
    ]


def _outside_extent(
    point: dict, minimum: list[float], maximum: list[float], tolerance: float
) -> bool:
    coordinates = [point["x"], point["y"], point["z"]]
    return any(
        coordinates[axis] < minimum[axis] - tolerance
        or coordinates[axis] > maximum[axis] + tolerance
        for axis in range(3)
    )


def analyze(
    interfaces: dict,
    boreholes: dict | None,
    extent_arg: dict | None,
    resolution: list[int],
    series_order_arg: list[str] | None,
    duplicate_tolerance: float,
) -> dict:
    """Run cross-row validation and build a GemPy-oriented definition."""
    points = interfaces["points"]
    orientations = interfaces["orientations"]
    errors = [dict(item) for item in interfaces["errors"]]
    warnings = [dict(item) for item in interfaces["warnings"]]

    if boreholes is not None:
        errors.extend(dict(item) for item in boreholes["errors"])
        warnings.extend(dict(item) for item in boreholes["warnings"])

    if not points:
        errors.append(
            _issue(
                "NO_VALID_INTERFACES",
                "No valid interface points remain after validation",
            )
        )

    duplicate_pairs: list[dict] = []
    for first_index in range(len(points)):
        for second_index in range(first_index + 1, len(points)):
            first = points[first_index]
            second = points[second_index]
            differences = [
                abs(first["x"] - second["x"]),
                abs(first["y"] - second["y"]),
                abs(first["z"] - second["z"]),
            ]
            if max(differences) <= duplicate_tolerance:
                pair = {
                    "lines": [first["source_line"], second["source_line"]],
                    "coordinates": [first["x"], first["y"], first["z"]],
                    "surfaces": [first["surface"], second["surface"]],
                }
                duplicate_pairs.append(pair)
                errors.append(
                    _issue(
                        "DUPLICATE_INTERFACE",
                        "Duplicate interface point (or points within the tolerance)",
                        second["source_line"],
                        "x,y,z",
                        other_line=first["source_line"],
                        coordinates=pair["coordinates"],
                        tolerance=duplicate_tolerance,
                    )
                )

    surface_series: dict[str, set[str]] = {}
    for point in points:
        surface_series.setdefault(point["surface"], set()).add(point["series"])
    for surface in sorted(surface_series):
        series_names = sorted(surface_series[surface])
        if len(series_names) > 1:
            errors.append(
                _issue(
                    "SERIES_SURFACE_CONFLICT",
                    f"Surface {surface!r} is assigned to multiple series: "
                    f"{', '.join(series_names)}",
                    None,
                    "series,surface",
                    surface=surface,
                    series=series_names,
                )
            )

    appearance_order: list[str] = []
    for point in points:
        if point["series"] not in appearance_order:
            appearance_order.append(point["series"])

    effective_order = list(appearance_order)
    if series_order_arg is not None:
        missing = [series for series in appearance_order if series not in series_order_arg]
        unknown = [series for series in series_order_arg if series not in appearance_order]
        if missing or unknown:
            errors.append(
                _issue(
                    "SERIES_ORDER_INVALID",
                    "Series order must list every series exactly once",
                    None,
                    "series",
                    missing=missing,
                    unknown=unknown,
                )
            )
        else:
            effective_order = list(series_order_arg)
    elif appearance_order:
        warnings.append(
            _issue(
                "SERIES_ORDER_ASSUMED",
                "Series order is first appearance; GemPy treats the first series "
                "as the youngest. Verify stratigraphic order or pass --series-order.",
            )
        )

    series_records: list[dict] = []
    surfaces: list[dict] = []
    for order_index, series in enumerate(effective_order):
        surface_names: list[str] = []
        for point in points:
            if point["series"] == series and point["surface"] not in surface_names:
                surface_names.append(point["surface"])
        for surface in surface_names:
            surface_points = [
                point
                for point in points
                if point["series"] == series and point["surface"] == surface
            ]
            surface_orientations = [
                orientation
                for orientation in orientations
                if orientation["series"] == series
                and orientation["surface"] == surface
            ]
            surfaces.append(
                {
                    "name": surface,
                    "series": series,
                    "interface_count": len(surface_points),
                    "orientation_count": len(surface_orientations),
                }
            )
        series_records.append(
            {
                "name": series,
                "order": order_index + 1,
                "surfaces": surface_names,
            }
        )

    extent_info: dict = {
        "data": None,
        "model": None,
        "provided": extent_arg is not None,
        "expanded_axes": [],
        "gem_py_order": list(EXTENT_ORDER),
    }
    if points:
        data_min, data_max = _bounds(points)
        extent_info["data"] = {"min": data_min, "max": data_max}
        if extent_arg is not None:
            model_min = list(extent_arg["min"])
            model_max = list(extent_arg["max"])
            outside_points = [
                point
                for point in points
                if _outside_extent(point, model_min, model_max, duplicate_tolerance)
            ]
            if outside_points:
                errors.append(
                    _issue(
                        "EXTENT_DOES_NOT_CONTAIN_DATA",
                        f"{len(outside_points)} interface point(s) fall outside --extent",
                        outside_points[0]["source_line"],
                        "x,y,z",
                        count=len(outside_points),
                    )
                )
        else:
            model_min = list(data_min)
            model_max = list(data_max)
            for axis_index, axis_name in enumerate(("x", "y", "z")):
                if model_max[axis_index] <= model_min[axis_index]:
                    model_min[axis_index] -= 1.0
                    model_max[axis_index] += 1.0
                    extent_info["expanded_axes"].append(axis_name)
                    warnings.append(
                        _issue(
                            "EXTENT_AXIS_EXPANDED",
                            f"Extent axis {axis_name} had zero span and was expanded by ±1.0",
                            None,
                            axis_name,
                        )
                    )
            warnings.append(
                _issue(
                    "EXTENT_EQUALS_DATA_BOUNDS",
                    "Model extent equals the interface data bounds; GemPy models "
                    "often need a margin. Supply --extent to control it.",
                )
            )
        extent_info["model"] = {
            "min": model_min,
            "max": model_max,
            "gem_py": _gem_py_extent(model_min, model_max),
        }
    elif extent_arg is not None:
        extent_info["model"] = {
            "min": list(extent_arg["min"]),
            "max": list(extent_arg["max"]),
            "gem_py": list(extent_arg["gem_py"]),
        }

    borehole_summary = None
    if boreholes is not None:
        observations = boreholes["observations"]
        outside_boreholes = 0
        for observation in observations:
            known_series = surface_series.get(observation["surface"])
            if known_series is None:
                warnings.append(
                    _issue(
                        "BOREHOLE_UNKNOWN_UNIT",
                        f"Borehole unit {observation['surface']!r} is not defined "
                        "by any interface point",
                        observation["source_line"],
                        "surface",
                        surface=observation["surface"],
                    )
                )
            elif observation["series"] not in known_series:
                errors.append(
                    _issue(
                        "BOREHOLE_SERIES_CONFLICT",
                        f"Borehole assigns surface {observation['surface']!r} to "
                        f"series {observation['series']!r}, but interfaces use "
                        f"{', '.join(sorted(known_series))}",
                        observation["source_line"],
                        "series,surface",
                        surface=observation["surface"],
                        series=observation["series"],
                        expected_series=sorted(known_series),
                    )
                )
            if extent_info["model"] is not None and _outside_extent(
                observation,
                extent_info["model"]["min"],
                extent_info["model"]["max"],
                duplicate_tolerance,
            ):
                outside_boreholes += 1
        if outside_boreholes:
            warnings.append(
                _issue(
                    "BOREHOLE_OUTSIDE_EXTENT",
                    f"{outside_boreholes} borehole observation(s) fall outside the model extent",
                    None,
                    "x,y,z",
                    count=outside_boreholes,
                )
            )
        borehole_summary = {
            "observation_count": len(observations),
            "borehole_count": len({item["borehole_id"] for item in observations}),
            "observations": observations,
            "note": (
                "Borehole observations are included as evidence only; they are "
                "not converted into GemPy interface points or used for "
                "cross-validation in v0.1."
            ),
        }

    if points and len(points) < 3:
        warnings.append(
            _issue(
                "SPARSE_INTERFACES",
                "Fewer than 3 interface points; the implicit model will be poorly constrained",
            )
        )
    for surface in surfaces:
        if surface["interface_count"] < 3:
            warnings.append(
                _issue(
                    "SPARSE_SURFACE",
                    f"Surface {surface['name']!r} has only "
                    f"{surface['interface_count']} interface point(s)",
                    None,
                    "surface",
                    surface=surface["name"],
                )
            )
    if not orientations:
        warnings.append(
            _issue(
                "NO_ORIENTATIONS",
                "No dip/azimuth orientations were supplied; geometry relies on "
                "interface points alone",
            )
        )
    if surfaces and len(surfaces) < 2:
        warnings.append(
            _issue(
                "SINGLE_SURFACE",
                "Only one geological surface is defined; a multi-unit model needs more",
            )
        )

    status = "ok" if not errors else "invalid"
    counts = {
        "interface_rows": interfaces["row_count"],
        "interface_points": len(points),
        "orientations": len(orientations),
        "series": len(series_records),
        "surfaces": len(surfaces),
        "duplicate_pairs": len(duplicate_pairs),
        "skipped_interface_rows": interfaces["skipped_rows"],
        "borehole_observations": (
            len(boreholes["observations"]) if boreholes is not None else 0
        ),
        "boreholes": (
            len({item["borehole_id"] for item in boreholes["observations"]})
            if boreholes is not None
            else 0
        ),
        "skipped_borehole_rows": (
            boreholes["skipped_rows"] if boreholes is not None else 0
        ),
    }

    definition = None
    if status == "ok":
        definition = {
            "schema_version": "0.1",
            "skill": "mine-geological-modeling",
            "generator": GENERATOR,
            "target": {
                "software": "GemPy",
                "executed": False,
                "note": (
                    "GemPy-oriented definition only. Implicit interpolation, "
                    "surface extraction and ore-body estimation must be run "
                    "separately with GemPy and geological evidence."
                ),
            },
            "coordinate_system": {
                "units": "UNKNOWN",
                "crs": "UNKNOWN",
                "vertical_axis": "Z_UP",
                "orientation_convention": ORIENTATION_CONVENTION,
            },
            "extent_order": list(EXTENT_ORDER),
            "extent": extent_info["model"]["gem_py"],
            "resolution_order": ["x", "y", "z"],
            "resolution": resolution,
            "series": series_records,
            "surfaces": surfaces,
            "interfaces": [
                {
                    "x": point["x"],
                    "y": point["y"],
                    "z": point["z"],
                    "series": point["series"],
                    "surface": point["surface"],
                    "source_line": point["source_line"],
                }
                for point in points
            ],
            "orientations": [
                {
                    "x": orientation["x"],
                    "y": orientation["y"],
                    "z": orientation["z"],
                    "series": orientation["series"],
                    "surface": orientation["surface"],
                    "dip": orientation["dip"],
                    "azimuth": orientation["azimuth"],
                    "polarity": orientation["polarity"],
                    "source_line": orientation["source_line"],
                }
                for orientation in orientations
            ],
            "boreholes": borehole_summary,
            "notes": [
                "Series are ordered youngest to oldest as required by GemPy.",
                "No interpolation has been performed; all coordinates are source observations.",
                "Borehole rows are evidence and are not added to GemPy interfaces in v0.1.",
                "Units and CRS are UNKNOWN.",
            ],
        }

    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "counts": counts,
        "series": series_records,
        "surfaces": surfaces,
        "extent": extent_info,
        "resolution": resolution,
        "borehole_summary": borehole_summary,
        "duplicate_pairs": duplicate_pairs,
        "definition": definition,
    }


# ---------------------------------------------------------------------------
# Reporting and outputs
# ---------------------------------------------------------------------------


def build_report(
    analysis: dict,
    interfaces: dict,
    boreholes: dict | None,
    interfaces_path: str,
    boreholes_path: str | None,
    options: dict,
    definition_written: bool,
) -> dict:
    return {
        "schema_version": "0.1",
        "status": analysis["status"],
        "skill": "mine-geological-modeling",
        "generator": GENERATOR,
        "source": {
            "interfaces": common.source_manifest(interfaces_path),
            "boreholes": (
                common.source_manifest(boreholes_path) if boreholes_path else None
            ),
        },
        "inputs": {
            "interfaces": {
                "row_count": interfaces["row_count"],
                "skipped_rows": interfaces["skipped_rows"],
                "has_header": interfaces["has_header"],
                "header_line": interfaces["header_line"],
                "delimiter": interfaces["delimiter"],
                "encoding": interfaces["encoding"],
                "columns": interfaces["columns"],
            },
            "boreholes": (
                {
                    "row_count": boreholes["row_count"],
                    "skipped_rows": boreholes["skipped_rows"],
                    "has_header": boreholes["has_header"],
                    "header_line": boreholes["header_line"],
                    "delimiter": boreholes["delimiter"],
                    "encoding": boreholes["encoding"],
                    "columns": boreholes["columns"],
                }
                if boreholes is not None
                else None
            ),
        },
        "options": options,
        "counts": analysis["counts"],
        "series": analysis["series"],
        "surfaces": analysis["surfaces"],
        "extent": analysis["extent"],
        "resolution": analysis["resolution"],
        "orientation_convention": ORIENTATION_CONVENTION,
        "validation": {
            "errors": analysis["errors"],
            "warnings": analysis["warnings"],
            "duplicate_pairs": analysis["duplicate_pairs"],
        },
        "boreholes": analysis["borehole_summary"],
        "definition_written": definition_written,
        "limitations": LIMITATIONS,
    }


def render_markdown(report: dict) -> str:
    counts = report["counts"]
    extent = report["extent"]
    lines = [
        "# Geological Model Preparation Report",
        "",
        f"- **Status**: {report['status'].upper()}",
        f"- **Interfaces**: {counts['interface_points']} valid point(s) from "
        f"{counts['interface_rows']} row(s)",
        f"- **Orientations**: {counts['orientations']}",
        f"- **Series**: {counts['series']}",
        f"- **Surfaces**: {counts['surfaces']}",
        f"- **Boreholes**: {counts['boreholes']} hole(s), "
        f"{counts['borehole_observations']} observation(s)",
        f"- **Resolution**: {report['resolution']}",
    ]
    if extent["model"] is not None:
        lines.append(
            "- **Model extent (GemPy order "
            "xmin, xmax, ymin, ymax, zmin, zmax)**: "
            + ", ".join(common.fmt(value) for value in extent["model"]["gem_py"])
        )
        lines.append(
            "- **Model bounds (min / max)**: "
            + ", ".join(common.fmt(value) for value in extent["model"]["min"])
            + " / "
            + ", ".join(common.fmt(value) for value in extent["model"]["max"])
        )
    if extent["data"] is not None:
        lines.append(
            "- **Data bounds (min / max)**: "
            + ", ".join(common.fmt(value) for value in extent["data"]["min"])
            + " / "
            + ", ".join(common.fmt(value) for value in extent["data"]["max"])
        )
    lines.append(
        f"- **Definition written**: {'yes' if report['definition_written'] else 'no'}"
    )

    lines.extend(["", "## Series and surfaces", ""])
    if report["surfaces"]:
        lines.extend(
            [
                "| Series | Order | Surface | Interfaces | Orientations |",
                "|---|---:|---|---:|---:|",
            ]
        )
        series_order = {item["name"]: item["order"] for item in report["series"]}
        for surface in report["surfaces"]:
            lines.append(
                f"| {surface['series']} | {series_order.get(surface['series'], '-')} | "
                f"{surface['name']} | {surface['interface_count']} | "
                f"{surface['orientation_count']} |"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Errors", ""])
    if report["validation"]["errors"]:
        lines.extend(["| Code | Line | Message |", "|---|---:|---|"])
        for item in report["validation"]["errors"]:
            line = item.get("line", "-")
            lines.append(f"| {item['code']} | {line} | {item['message']} |")
    else:
        lines.append("- None")

    lines.extend(["", "## Warnings", ""])
    if report["validation"]["warnings"]:
        for item in report["validation"]["warnings"]:
            prefix = f"line {item['line']}: " if "line" in item else ""
            lines.append(f"- [{item['code']}] {prefix}{item['message']}")
    else:
        lines.append("- None")

    if report["boreholes"] is not None:
        lines.extend(
            [
                "",
                "## Boreholes",
                "",
                report["boreholes"]["note"],
            ]
        )

    lines.extend(["", "## v0.1 limitations and next steps", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(
        [
            "- Next step: run GemPy with this definition and an explicit "
            "interpolation/validation plan; do not publish an unvalidated model.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(
    analysis: dict,
    report: dict,
    out_dir: str,
) -> dict[str, str | None]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    definition_path = out / "model_definition.json"
    if analysis["status"] == "ok":
        common.write_json(definition_path, analysis["definition"])
        written_path: str | None = str(definition_path)
    else:
        if definition_path.exists():
            definition_path.unlink()
        written_path = None

    report_json = out / "geology_report.json"
    report_md = out / "geology_report.md"
    common.write_json(report_json, report)
    common.write_text(report_md, render_markdown(report))
    return {
        "definition": written_path,
        "report_json": str(report_json),
        "report_md": str(report_md),
    }


def prepare_geology(
    interfaces_path: str,
    boreholes_path: str | None = None,
    out_dir: str = "geology_output",
    extent_value: str | None = None,
    resolution_value: str | None = None,
    series_order_value: str | None = None,
    duplicate_tolerance: float = 1e-6,
    delimiter: str | None = None,
    encoding: str | None = None,
) -> dict:
    """Validate inputs, write reports and write the definition when valid."""
    if not Path(interfaces_path).is_file():
        raise SystemExit(f"Interfaces file not found: {interfaces_path}")
    if boreholes_path is not None and not Path(boreholes_path).is_file():
        raise SystemExit(f"Boreholes file not found: {boreholes_path}")
    if not math.isfinite(duplicate_tolerance) or duplicate_tolerance <= 0:
        raise SystemExit("--duplicate-tolerance must be a finite number greater than 0")

    extent_arg = parse_extent(extent_value) if extent_value else None
    resolution = (
        parse_resolution(resolution_value) if resolution_value else list(DEFAULT_RESOLUTION)
    )
    series_order_arg = (
        parse_series_order(series_order_value) if series_order_value else None
    )

    interfaces = load_interfaces(interfaces_path, delimiter=delimiter, encoding=encoding)
    boreholes = (
        load_boreholes(boreholes_path, delimiter=delimiter, encoding=encoding)
        if boreholes_path
        else None
    )
    analysis = analyze(
        interfaces,
        boreholes,
        extent_arg,
        resolution,
        series_order_arg,
        duplicate_tolerance,
    )
    options = {
        "duplicate_tolerance": duplicate_tolerance,
        "extent_provided": extent_value is not None,
        "series_order_provided": series_order_value is not None,
    }
    # Build the report once to capture definition status, then write outputs.
    report = build_report(
        analysis,
        interfaces,
        boreholes,
        interfaces_path,
        boreholes_path,
        options,
        definition_written=analysis["status"] == "ok",
    )
    paths = write_outputs(analysis, report, out_dir)
    return {
        "status": analysis["status"],
        "report": report,
        "definition": analysis["definition"],
        "paths": paths,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate geological interfaces and boreholes, then write a "
            "GemPy-oriented model definition. GemPy is not run."
        )
    )
    parser.add_argument("interfaces", help="Interface CSV file")
    parser.add_argument("--boreholes", help="Optional borehole observation CSV file")
    parser.add_argument("--out-dir", default="geology_output")
    parser.add_argument(
        "--extent",
        help="Model extent in GemPy order: xmin,xmax,ymin,ymax,zmin,zmax",
    )
    parser.add_argument(
        "--resolution", default="50,50,50", help="Grid resolution nx,ny,nz"
    )
    parser.add_argument(
        "--series-order",
        help="Comma-separated series names, youngest first",
    )
    parser.add_argument(
        "--duplicate-tolerance",
        type=float,
        default=1e-6,
        help="Absolute XYZ tolerance for duplicate interface detection",
    )
    parser.add_argument("--delimiter", choices=[",", ";", "tab"])
    parser.add_argument("--encoding")
    args = parser.parse_args(argv)

    delimiter = {"tab": "\t"}.get(args.delimiter, args.delimiter)
    result = prepare_geology(
        args.interfaces,
        boreholes_path=args.boreholes,
        out_dir=args.out_dir,
        extent_value=args.extent,
        resolution_value=args.resolution,
        series_order_value=args.series_order,
        duplicate_tolerance=args.duplicate_tolerance,
        delimiter=delimiter,
        encoding=args.encoding,
    )
    report = result["report"]
    counts = report["counts"]

    if result["status"] == "ok":
        print(
            f"Prepared geological definition: {counts['interface_points']} interfaces, "
            f"{counts['orientations']} orientations, {counts['series']} series, "
            f"{counts['surfaces']} surfaces."
        )
        if report["extent"]["model"] is not None:
            print(
                "Extent (xmin,xmax,ymin,ymax,zmin,zmax): "
                + ", ".join(
                    common.fmt(value, 6) for value in report["extent"]["model"]["gem_py"]
                )
            )
    else:
        print(
            f"Validation failed with {len(report['validation']['errors'])} error(s); "
            "model_definition.json was not written."
        )
        for item in report["validation"]["errors"][:10]:
            line = f" (line {item['line']})" if "line" in item else ""
            print(f"  [{item['code']}]{line} {item['message']}")
        if len(report["validation"]["errors"]) > 10:
            print("  ... see geology_report.json for the full list")
    print(
        "Outputs: "
        + ", ".join(path for path in result["paths"].values() if path)
    )
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
