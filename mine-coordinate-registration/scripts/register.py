#!/usr/bin/env python3
"""Register mine control points and apply a similarity transformation.

Supports a 3D seven-parameter similarity (Umeyama / SVD) and a 2D
four-parameter similarity (least squares). The transformation convention is:

    dst = scale * R * src + translation

The tool never assumes units or a CRS and never modifies source files.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter
from pathlib import Path

import common

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - environment dependent
    raise SystemExit(
        "numpy is required. Install it with:\n"
        "  python3 -m pip install -r requirements.txt"
    ) from exc


SRC_X = {"sx", "source_x", "from_x", "src_x", "x1", "x_src", "源x", "源_x"}
SRC_Y = {"sy", "source_y", "from_y", "src_y", "y1", "y_src", "源y", "源_y"}
SRC_Z = {"sz", "source_z", "from_z", "src_z", "z1", "z_src", "源z", "源_z"}
DST_X = {"tx", "target_x", "to_x", "dst_x", "x2", "x_tgt", "目标x", "目标_x"}
DST_Y = {"ty", "target_y", "to_y", "dst_y", "y2", "y_tgt", "目标y", "目标_y"}
DST_Z = {"tz", "target_z", "to_z", "dst_z", "z2", "z_tgt", "目标z", "目标_z"}

XYZ_X = {"x", "easting", "east", "东坐标", "x坐标"}
XYZ_Y = {"y", "northing", "north", "北坐标", "y坐标"}
XYZ_Z = {"z", "elevation", "elev", "height", "高程", "z坐标"}


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


def _read_table(path: str, delimiter: str | None, encoding: str | None):
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
    return numbered, sample_rows, delimiter, has_header, used_encoding


def _find_column(header: list[str], names: set[str]) -> int | None:
    for index, name in enumerate(header):
        if name.strip().lower() in names:
            return index + 1
    return None


def _parse_columns(value: str | None) -> list[int] | None:
    if not value:
        return None
    try:
        columns = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise SystemExit(f"Invalid column list: {value}") from exc
    if len(columns) != 3:
        raise SystemExit(f"Expected 3 columns, got {len(columns)}: {value}")
    return columns


def load_control_points(
    path: str,
    src_cols: list[int] | None = None,
    dst_cols: list[int] | None = None,
    delimiter: str | None = None,
    encoding: str | None = None,
) -> dict:
    numbered, sample_rows, delimiter, has_header, used_encoding = _read_table(
        path, delimiter, encoding
    )
    header = sample_rows[0] if has_header else None

    if src_cols is None or dst_cols is None:
        if header:
            sx = _find_column(header, SRC_X)
            sy = _find_column(header, SRC_Y)
            sz = _find_column(header, SRC_Z)
            tx = _find_column(header, DST_X)
            ty = _find_column(header, DST_Y)
            tz = _find_column(header, DST_Z)
            if None not in (sx, sy, sz, tx, ty, tz):
                src_cols = [sx, sy, sz]
                dst_cols = [tx, ty, tz]
        if src_cols is None:
            src_cols = [1, 2, 3]
        if dst_cols is None:
            dst_cols = [4, 5, 6]

    start = 1 if has_header else 0
    points: list[list[float]] = []
    skipped: list[dict] = []
    for lineno, line in numbered[start:]:
        tokens = split_line(line, delimiter)
        try:
            values = [float(tokens[col - 1]) for col in src_cols + dst_cols]
        except (ValueError, IndexError):
            skipped.append({"line": lineno, "reason": "missing or non-numeric coordinate"})
            continue
        if not all(math.isfinite(value) for value in values):
            skipped.append({"line": lineno, "reason": "non-finite coordinate"})
            continue
        points.append(values)

    if len(points) < 2:
        raise SystemExit("At least 2 valid control points are required")

    return {
        "points": np.asarray(points, dtype=float),
        "src_cols": src_cols,
        "dst_cols": dst_cols,
        "delimiter": delimiter if delimiter is not None else "whitespace",
        "encoding": used_encoding,
        "has_header": has_header,
        "header": header,
        "skipped": skipped,
    }


def load_points(
    path: str,
    x_col: int = 1,
    y_col: int = 2,
    z_col: int = 3,
    delimiter: str | None = None,
    encoding: str | None = None,
) -> dict:
    numbered, sample_rows, delimiter, has_header, used_encoding = _read_table(
        path, delimiter, encoding
    )
    if has_header:
        header = sample_rows[0]
        x = _find_column(header, XYZ_X)
        y = _find_column(header, XYZ_Y)
        z = _find_column(header, XYZ_Z)
        if None not in (x, y, z) and (x_col, y_col, z_col) == (1, 2, 3):
            x_col, y_col, z_col = x, y, z

    start = 1 if has_header else 0
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

    return {
        "points": np.asarray(points, dtype=float) if points else np.empty((0, 3)),
        "columns": [x_col, y_col, z_col],
        "delimiter": delimiter if delimiter is not None else "whitespace",
        "encoding": used_encoding,
        "has_header": has_header,
        "skipped": skipped,
    }


def _check_geometry(src: np.ndarray, mode: str) -> None:
    if mode == "3d":
        centered = src - src.mean(axis=0)
        if np.linalg.matrix_rank(centered) < 2:
            raise SystemExit(
                "Control points are coincident or collinear; a 3D similarity "
                "cannot be determined."
            )
    else:
        distinct = np.unique(src[:, :2], axis=0)
        if len(distinct) < 2:
            raise SystemExit("At least 2 distinct control points are required for 2D.")


def _fit_3d(src: np.ndarray, dst: np.ndarray) -> dict:
    n = len(src)
    mu_src = src.mean(axis=0)
    mu_dst = dst.mean(axis=0)
    src_centered = src - mu_src
    dst_centered = dst - mu_dst
    cov = (dst_centered.T @ src_centered) / n
    u, d, vt = np.linalg.svd(cov)
    s = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        s[2, 2] = -1
    rotation = u @ s @ vt
    variance = float((src_centered ** 2).sum() / n)
    if variance <= 0:
        raise SystemExit("Source control points have zero variance.")
    scale = float(np.trace(np.diag(d) @ s) / variance)
    if not math.isfinite(scale) or scale <= 0:
        raise SystemExit("Computed scale is invalid; check control point pairs.")
    translation = mu_dst - scale * (rotation @ mu_src)
    return {
        "method": "3d_similarity_umeyama",
        "scale": scale,
        "rotation_matrix": rotation,
        "translation": translation,
    }


def _fit_2d(src: np.ndarray, dst: np.ndarray) -> dict:
    x, y = src[:, 0], src[:, 1]
    target_x, target_y = dst[:, 0], dst[:, 1]
    n = len(src)
    a_matrix = np.zeros((2 * n, 4), dtype=float)
    b_vector = np.zeros(2 * n, dtype=float)
    a_matrix[0::2, 0] = x
    a_matrix[0::2, 1] = -y
    a_matrix[0::2, 2] = 1.0
    a_matrix[1::2, 0] = y
    a_matrix[1::2, 1] = x
    a_matrix[1::2, 3] = 1.0
    b_vector[0::2] = target_x
    b_vector[1::2] = target_y
    solution, *_ = np.linalg.lstsq(a_matrix, b_vector, rcond=None)
    a, b, tx, ty = [float(value) for value in solution]
    scale = math.hypot(a, b)
    if scale <= 0 or not math.isfinite(scale):
        raise SystemExit("Computed scale is invalid; check control point pairs.")
    cos_theta = a / scale
    sin_theta = b / scale
    rotation = np.eye(3)
    rotation[0, 0] = cos_theta
    rotation[0, 1] = -sin_theta
    rotation[1, 0] = sin_theta
    rotation[1, 1] = cos_theta
    tz = float(np.mean(dst[:, 2] - src[:, 2]))
    return {
        "method": "2d_similarity_least_squares",
        "scale": scale,
        "rotation_matrix": rotation,
        "translation": np.array([tx, ty, tz], dtype=float),
        "rotation_deg_2d": math.degrees(math.atan2(b, a)),
    }


def fit_similarity(src: np.ndarray, dst: np.ndarray, mode: str = "3d") -> dict:
    if mode not in {"2d", "3d"}:
        raise SystemExit(f"Unsupported mode: {mode}")
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 3:
        raise SystemExit("Control point arrays must both be N x 3")
    minimum = 3 if mode == "3d" else 2
    if len(src) < minimum:
        raise SystemExit(f"At least {minimum} control points are required for {mode} similarity")
    _check_geometry(src, mode)
    return _fit_3d(src, dst) if mode == "3d" else _fit_2d(src, dst)


def apply_transform(points: np.ndarray, parameters: dict, mode: str = "3d") -> np.ndarray:
    points = np.asarray(points, dtype=float)
    scale = float(parameters["scale"])
    rotation = np.asarray(parameters["rotation_matrix"], dtype=float)
    translation = np.asarray(parameters["translation"], dtype=float)
    if mode == "3d":
        return scale * (points @ rotation.T) + translation
    result = np.empty_like(points)
    result[:, :2] = scale * (points[:, :2] @ rotation[:2, :2].T) + translation[:2]
    result[:, 2] = points[:, 2] + translation[2]
    return result


def _residuals(src: np.ndarray, dst: np.ndarray, parameters: dict, mode: str):
    transformed = apply_transform(src, parameters, mode)
    diff = transformed - dst
    if mode == "2d":
        residual = np.linalg.norm(diff[:, :2], axis=1)
    else:
        residual = np.linalg.norm(diff, axis=1)
    return residual, diff


def _euler_zyx_deg(rotation: np.ndarray) -> dict:
    sy = math.hypot(rotation[0, 0], rotation[1, 0])
    if sy > 1e-9:
        rx = math.atan2(rotation[2, 1], rotation[2, 2])
        ry = math.atan2(-rotation[2, 0], sy)
        rz = math.atan2(rotation[1, 0], rotation[0, 0])
    else:
        rx = math.atan2(-rotation[1, 2], rotation[1, 1])
        ry = math.atan2(-rotation[2, 0], sy)
        rz = 0.0
    return {
        "rx": math.degrees(rx),
        "ry": math.degrees(ry),
        "rz": math.degrees(rz),
    }


def register_control_points(
    src: np.ndarray,
    dst: np.ndarray,
    mode: str = "3d",
    reject_above: float | None = None,
) -> dict:
    if reject_above is not None and reject_above <= 0:
        raise SystemExit("--reject-above must be greater than 0")

    minimum = 3 if mode == "3d" else 2
    if len(src) < minimum:
        raise SystemExit(f"At least {minimum} control points are required for {mode} similarity")

    keep = np.ones(len(src), dtype=bool)
    rejected: list[dict] = []
    parameters = None

    while True:
        indexes = np.nonzero(keep)[0]
        if len(indexes) < minimum:
            raise SystemExit("Too few control points remain after rejection")
        parameters = fit_similarity(src[indexes], dst[indexes], mode)
        residual, _ = _residuals(src, dst, parameters, mode)

        if reject_above is None:
            break
        over = indexes[residual[indexes] > reject_above]
        if len(over) == 0:
            break
        worst = int(over[np.argmax(residual[over])])
        if len(indexes) - 1 < minimum:
            break
        rejected.append(
            {
                "index": worst + 1,
                "residual": float(residual[worst]),
                "reason": f"residual {residual[worst]:.6f} exceeds {reject_above}",
            }
        )
        keep[worst] = False

    transformed = apply_transform(src, parameters, mode)
    diff = transformed - dst
    residual = (
        np.linalg.norm(diff[:, :2], axis=1)
        if mode == "2d"
        else np.linalg.norm(diff, axis=1)
    )
    used = keep
    used_residual = residual[used]

    point_rows = []
    for index in range(len(src)):
        row = {
            "index": index + 1,
            "source": [round(float(v), 6) for v in src[index]],
            "target": [round(float(v), 6) for v in dst[index]],
            "transformed": [round(float(v), 6) for v in transformed[index]],
            "dx": float(diff[index, 0]),
            "dy": float(diff[index, 1]),
            "dz": float(diff[index, 2]),
            "residual": float(residual[index]),
            "used": bool(keep[index]),
            "rejected": not bool(keep[index]),
        }
        rejection = next((item for item in rejected if item["index"] == index + 1), None)
        if rejection:
            row["rejection_residual"] = rejection["residual"]
            row["rejection_reason"] = rejection["reason"]
        point_rows.append(row)

    rmse = float(np.sqrt(np.mean(used_residual ** 2))) if len(used_residual) else None
    max_residual = float(np.max(used_residual)) if len(used_residual) else None
    mean_residual = float(np.mean(used_residual)) if len(used_residual) else None
    per_axis_rmse = {
        "x": float(np.sqrt(np.mean(diff[used, 0] ** 2))) if len(used_residual) else None,
        "y": float(np.sqrt(np.mean(diff[used, 1] ** 2))) if len(used_residual) else None,
        "z": float(np.sqrt(np.mean(diff[used, 2] ** 2))) if len(used_residual) else None,
    }

    warnings: list[str] = []
    if int(used.sum()) < 4 and mode == "3d":
        warnings.append(
            "Fewer than 4 used control points; the RMSE is not a reliable accuracy estimate."
        )
    if int(used.sum()) < 3 and mode == "2d":
        warnings.append(
            "Fewer than 3 used control points; the RMSE is not a reliable accuracy estimate."
        )
    if parameters["scale"] < 0.5 or parameters["scale"] > 2.0:
        warnings.append(
            "Scale factor is outside 0.5–2.0; verify units and control point pairs."
        )
    if rejected:
        warnings.append(
            f"{len(rejected)} control point(s) were rejected; review the residuals and reasons."
        )
    if max_residual is not None and rmse and max_residual > 5 * rmse and not rejected:
        warnings.append(
            "A residual is more than 5× RMSE; consider --reject-above or review the point pair."
        )
    if mode == "2d":
        warnings.append(
            "2D mode only fits horizontal coordinates; Z receives a constant mean offset."
        )

    parameters_out = {
        "method": parameters["method"],
        "convention": "dst = scale * R * src + translation",
        "scale": parameters["scale"],
        "rotation_matrix": parameters["rotation_matrix"].tolist(),
        "translation": [float(v) for v in parameters["translation"]],
        "rmse": rmse,
        "max_residual": max_residual,
        "used_control_points": int(used.sum()),
        "control_point_count": len(src),
    }
    if mode == "3d":
        parameters_out["euler_angles_deg_zyx"] = _euler_zyx_deg(
            parameters["rotation_matrix"]
        )
    else:
        parameters_out["rotation_deg_2d"] = parameters["rotation_deg_2d"]

    return {
        "parameters": parameters_out,
        "diagnostics": {
            "mode": mode,
            "rmse": rmse,
            "mean_residual": mean_residual,
            "max_residual": max_residual,
            "per_axis_rmse": per_axis_rmse,
            "used_control_points": int(used.sum()),
            "rejected_control_points": rejected,
            "points": point_rows,
            "warnings": warnings,
        },
        "internal": parameters,
        "used_mask": used,
    }


def render_markdown(report: dict) -> str:
    params = report["parameters"]
    diag = report["diagnostics"]
    lines = [
        "# Coordinate Registration Report",
        "",
        f"- **Mode**: {diag['mode']}",
        f"- **Method**: {params['method']}",
        f"- **Scale**: {common.fmt(params['scale'], 9)}",
        f"- **Translation**: "
        f"({common.fmt(params['translation'][0], 4)}, "
        f"{common.fmt(params['translation'][1], 4)}, "
        f"{common.fmt(params['translation'][2], 4)})",
    ]
    if "euler_angles_deg_zyx" in params:
        angles = params["euler_angles_deg_zyx"]
        lines.append(
            f"- **Euler angles (deg, ZYX)**: "
            f"rx {common.fmt(angles['rx'], 6)}, "
            f"ry {common.fmt(angles['ry'], 6)}, "
            f"rz {common.fmt(angles['rz'], 6)}"
        )
    else:
        lines.append(f"- **2D rotation (deg)**: {common.fmt(params['rotation_deg_2d'], 6)}")
    lines.extend(
        [
            f"- **RMSE**: {common.fmt(diag['rmse'], 6)}",
            f"- **Max residual**: {common.fmt(diag['max_residual'], 6)}",
            f"- **Used control points**: {diag['used_control_points']} / "
            f"{params['control_point_count']}",
            "",
            "## Control point residuals",
            "",
            "| # | Source | Target | Transformed | Residual | Used |",
            "|---:|---|---|---|---:|---|",
        ]
    )
    for point in diag["points"]:
        source = ", ".join(common.fmt(value, 4) for value in point["source"])
        target = ", ".join(common.fmt(value, 4) for value in point["target"])
        transformed = ", ".join(common.fmt(value, 4) for value in point["transformed"])
        lines.append(
            f"| {point['index']} | {source} | {target} | {transformed} | "
            f"{common.fmt(point['residual'], 6)} | {point['used']} |"
        )
    lines.extend(["", "## Warnings", ""])
    if diag["warnings"]:
        lines.extend(f"- {warning}" for warning in diag["warnings"])
    else:
        lines.append("- None")
    lines.extend(["", "## Convention", "", params["convention"], ""])
    return "\n".join(lines)


def write_outputs(
    result: dict,
    out_dir: str,
    source_control: str,
    source_points: str | None,
    transformed: np.ndarray | None,
    points_metadata: dict | None,
    source_crs: str,
    target_crs: str,
    options: dict,
) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    params = dict(result["parameters"])
    params["source_crs"] = source_crs
    params["target_crs"] = target_crs
    params["source_control_points"] = common.source_manifest(source_control)
    if source_points:
        params["source_points"] = common.source_manifest(source_points)

    skipped_control_rows = options.get("skipped_control_rows", [])
    skipped_point_rows = options.get("skipped_point_rows", [])
    report_options = {
        key: value
        for key, value in options.items()
        if key not in {"skipped_control_rows", "skipped_point_rows"}
    }
    report = {
        "parameters": params,
        "diagnostics": result["diagnostics"],
        "options": report_options,
        "source_control_points": common.source_manifest(source_control),
        "source_points": common.source_manifest(source_points) if source_points else None,
        "skipped_control_rows": skipped_control_rows,
        "skipped_point_rows": skipped_point_rows,
    }
    if points_metadata:
        report["points_input"] = {
            key: value for key, value in points_metadata.items() if key != "points"
        }

    paths = {
        "transformation": str(out / "transformation.json"),
        "report_json": str(out / "registration_report.json"),
        "report_md": str(out / "registration_report.md"),
        "residuals_csv": str(out / "residuals.csv"),
    }
    common.write_json(paths["transformation"], params)
    common.write_json(paths["report_json"], report)
    common.write_text(paths["report_md"], render_markdown(report))

    with open(paths["residuals_csv"], "w", encoding="utf-8-sig", newline="") as fh:
        fields = [
            "index",
            "source_x",
            "source_y",
            "source_z",
            "target_x",
            "target_y",
            "target_z",
            "transformed_x",
            "transformed_y",
            "transformed_z",
            "dx",
            "dy",
            "dz",
            "residual",
            "used",
            "rejected",
        ]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for point in result["diagnostics"]["points"]:
            writer.writerow(
                {
                    "index": point["index"],
                    "source_x": point["source"][0],
                    "source_y": point["source"][1],
                    "source_z": point["source"][2],
                    "target_x": point["target"][0],
                    "target_y": point["target"][1],
                    "target_z": point["target"][2],
                    "transformed_x": point["transformed"][0],
                    "transformed_y": point["transformed"][1],
                    "transformed_z": point["transformed"][2],
                    "dx": point["dx"],
                    "dy": point["dy"],
                    "dz": point["dz"],
                    "residual": point["residual"],
                    "used": point["used"],
                    "rejected": point["rejected"],
                }
            )

    if transformed is not None and points_metadata is not None:
        points_path = str(out / "transformed_points.csv")
        paths["transformed_points"] = points_path
        original = points_metadata["points"]
        with open(points_path, "w", encoding="utf-8-sig", newline="") as fh:
            fields = [
                "source_x",
                "source_y",
                "source_z",
                "x",
                "y",
                "z",
                "delta_x",
                "delta_y",
                "delta_z",
            ]
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for index in range(len(transformed)):
                delta_x = transformed[index, 0] - original[index, 0]
                delta_y = transformed[index, 1] - original[index, 1]
                delta_z = transformed[index, 2] - original[index, 2]
                writer.writerow(
                    {
                        "source_x": original[index, 0],
                        "source_y": original[index, 1],
                        "source_z": original[index, 2],
                        "x": transformed[index, 0],
                        "y": transformed[index, 1],
                        "z": transformed[index, 2],
                        "delta_x": delta_x,
                        "delta_y": delta_y,
                        "delta_z": delta_z,
                    }
                )
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fit a similarity transformation from control points and optionally apply it."
    )
    parser.add_argument("control_points", help="CSV/XYZ file with source and target control points")
    parser.add_argument("--points", help="Optional XYZ/CSV file to transform")
    parser.add_argument("--out-dir", default="registration_output")
    parser.add_argument("--mode", choices=["3d", "2d"], default="3d")
    parser.add_argument("--src-cols", help="1-based source columns, e.g. 1,2,3")
    parser.add_argument("--dst-cols", help="1-based target columns, e.g. 4,5,6")
    parser.add_argument("--x-col", type=int, default=1)
    parser.add_argument("--y-col", type=int, default=2)
    parser.add_argument("--z-col", type=int, default=3)
    parser.add_argument("--reject-above", type=float, help="Reject control points above this residual")
    parser.add_argument("--source-crs", default="UNKNOWN")
    parser.add_argument("--target-crs", default="UNKNOWN")
    parser.add_argument("--delimiter", choices=[",", ";", "tab"])
    parser.add_argument("--encoding")
    args = parser.parse_args(argv)

    delimiter = {"tab": "\t"}.get(args.delimiter, args.delimiter)
    control = load_control_points(
        args.control_points,
        src_cols=_parse_columns(args.src_cols),
        dst_cols=_parse_columns(args.dst_cols),
        delimiter=delimiter,
        encoding=args.encoding,
    )
    points = None
    if args.points:
        points = load_points(
            args.points,
            x_col=args.x_col,
            y_col=args.y_col,
            z_col=args.z_col,
            delimiter=delimiter,
            encoding=args.encoding,
        )
        if len(points["points"]) == 0:
            raise SystemExit("Points file contains no valid coordinates")

    data = control["points"]
    result = register_control_points(
        data[:, 0:3],
        data[:, 3:6],
        mode=args.mode,
        reject_above=args.reject_above,
    )
    transformed = None
    if points is not None:
        transformed = apply_transform(points["points"], result["internal"], args.mode)

    options = {
        "mode": args.mode,
        "reject_above": args.reject_above,
        "source_crs": args.source_crs,
        "target_crs": args.target_crs,
        "control_columns": {
            "source": control["src_cols"],
            "target": control["dst_cols"],
        },
        "control_input": {
            "delimiter": control["delimiter"],
            "encoding": control["encoding"],
            "has_header": control["has_header"],
        },
        "skipped_control_rows": control["skipped"],
        "skipped_point_rows": points["skipped"] if points else [],
    }
    paths = write_outputs(
        result,
        args.out_dir,
        args.control_points,
        args.points,
        transformed,
        points,
        args.source_crs,
        args.target_crs,
        options,
    )

    params = result["parameters"]
    diag = result["diagnostics"]
    print(
        f"Registered {diag['used_control_points']} control points "
        f"({diag['mode']}), scale {common.fmt(params['scale'], 9)}, "
        f"RMSE {common.fmt(diag['rmse'], 6)}, max {common.fmt(diag['max_residual'], 6)}; "
        f"rejected: {len(diag['rejected_control_points'])}"
    )
    print("Outputs: " + ", ".join(paths.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
