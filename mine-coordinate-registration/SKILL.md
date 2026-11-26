---
name: mine-coordinate-registration
description: Analyze, transform and register mine engineering coordinates. Use when processing mining CAD drawings, XYZ survey control points, local engineering coordinate systems, coordinate transformations or 3D model alignment.
---

# Mine Coordinate Registration

> Status: v0.1 — 3D seven-parameter and 2D four-parameter similarity registration are implemented with tests. EPSG-based CRS transforms (`pyproj`) are not yet implemented; CRS labels are metadata only.

## Role

You are a mining geospatial coordinate processing specialist. Your task is to process mine engineering coordinates accurately and reproducibly.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| Control point file | CSV/TSV/whitespace with source XYZ and target XYZ columns |
| Points to transform | XYZ/CSV/TSV, optional |
| 3D mode | Seven-parameter similarity (translation, rotation, scale) via Umeyama/SVD |
| 2D mode | Four-parameter horizontal similarity plus a constant Z offset |
| CRS labels | `--source-crs` / `--target-crs` recorded as metadata; no CRS transformation |
| DXF geometry | Feed `mine-cad-parser` output points; direct DXF parsing is out of scope |

## Quick Start

Run the following commands from this skill directory.

```bash
python3 -m pip install -r requirements.txt
```

```bash
python3 scripts/register.py tests/fixtures/control_points_3d.csv \
  --points tests/fixtures/points_to_transform.xyz \
  --out-dir registration_output
```

2D mode with iterative outlier rejection:

```bash
python3 scripts/register.py control_points.csv --mode 2d \
  --reject-above 0.05 --out-dir registration_output
```

Options:

| Option | Default | Meaning |
|---|---|---|
| `--mode` | `3d` | `3d` seven-parameter or `2d` four-parameter similarity |
| `--src-cols` / `--dst-cols` | auto | 1-based control point columns |
| `--x-col` / `--y-col` / `--z-col` | 1,2,3 | Points file columns |
| `--reject-above` | off | Absolute residual threshold for rejection |
| `--source-crs` / `--target-crs` | `UNKNOWN` | Labels only |
| `--delimiter` | auto | `,`, `;` or `tab` |
| `--out-dir` | `registration_output` | Output directory |

## Workflow

1. Inspect source coordinate ranges.
2. Identify coordinate units and axis order.
3. Determine whether the source uses a known CRS or a local engineering CRS.
4. Never assume an unknown CRS.
5. Ask for missing control information when required.
6. Calculate coordinate transformations (translation, rotation, scale, 7-parameter).
7. Calculate residual errors and RMSE.
8. Export transformed coordinates and transformation metadata.

## Engineering Rules

- Preserve original coordinates.
- Never overwrite source files.
- Never silently change coordinate units.
- Do not treat local coordinates as WGS84.
- Distinguish horizontal and vertical datums.
- Use double precision for coordinate calculations.
- Keep transformation parameters reproducible.

## Quality Requirements

- Report control point residuals.
- Report RMSE, mean and maximum residual.
- Report transformation parameters, including the rotation matrix and Euler angles.
- Report rejected control points and reasons.
- Stop when coordinate accuracy cannot be established (too few, collinear or coincident points).

## Deliverables

- `transformation.json`
- `registration_report.json`
- `registration_report.md`
- `residuals.csv`
- `transformed_points.csv` (when `--points` is provided)

## Project Layout

- `scripts/register.py` — similarity fitting, rejection, transformation and CLI
- `scripts/common.py` — hashing, JSON output and formatting helpers
- `references/transformation-model.md` — 3D/2D models, Umeyama steps and limitations
- `references/io-schema.md` — input formats, options and output schema
- `tests/` — unittest suite and control point fixtures
- `requirements.txt` — `numpy`

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Tests are skipped automatically when `numpy` is not installed.

## Related Skills

- `mine-data-inspection` — source data and coordinate clues
- `mine-cad-parser` — geometry to be registered
- `mine-model-quality-check` — independent accuracy verification
