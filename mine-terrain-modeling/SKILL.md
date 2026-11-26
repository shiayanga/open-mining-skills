---
name: mine-terrain-modeling
description: Reconstruct mine terrain from contours, survey XYZ and breaklines using constrained TIN and DEM workflows. Use when building open-pit or surface mine topography for 3D mine scenes.
---

# Mine Terrain Modeling

> Status: v0.1 — XYZ/CSV survey points to an unconstrained Delaunay TIN, ESRI ASCII DEM, OBJ mesh and optional check-point RMSE are implemented with tests. Breakline-constrained TIN, contour handling and bench preservation are NOT implemented.

## Role

You are a mine terrain reconstruction specialist. Your job is to build an accurate, checkable terrain surface from survey data while preserving benches, slopes, gullies and other engineering features. In v0.1 you must also state clearly when the unconstrained TIN is not adequate for that goal.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| XYZ / CSV / TSV / whitespace survey points | Full: delimiter and header detection, exact duplicate removal, XY-conflict reporting, Delaunay TIN |
| Independent check points (XYZ) | Full: TIN elevation comparison with RMSE, MAE and maximum error |
| Contour polylines with elevations | Not read directly; export contour vertices with `mine-cad-parser` and supply them as points |
| Breaklines, pit limits, boundaries | NOT enforced in v0.1; the Delaunay TIN is unconstrained |
| Existing DEM / TIN / GeoTIFF | Not read |
| LAS / LAZ point clouds | Not read; use `mine-point-cloud` to produce ground candidates first |

## Quick Start

Run the following commands from this skill directory.

```bash
python3 -m pip install -r requirements.txt
```

```bash
# TIN + DEM + reports
python3 scripts/terrain.py tests/fixtures/survey_hill.csv \
  --out-dir terrain_output --cell-size 10

# Add independent check points
python3 scripts/terrain.py tests/fixtures/survey_hill.csv \
  --out-dir terrain_output --cell-size 10 \
  --check-points tests/fixtures/check_points.xyz
```

Exit code `0` on success. Fewer than 3 unique XY points, collinear points, an invalid DEM size or an unreadable input raise `SystemExit` with a message.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--out-dir` | `terrain_output` | Output directory |
| `--cell-size` | `1.0` | DEM cell size in source units; must be greater than 0 |
| `--method` | `linear` | DEM interpolation: `linear` or `nearest` |
| `--check-points` | off | Independent XYZ check point file |
| `--x-col` / `--y-col` / `--z-col` | `1,2,3` | 1-based coordinate columns |
| `--delimiter` | auto | `,`, `;` or tab; otherwise auto-detected |
| `--encoding` | auto | Text encoding override |

The check point file uses the same column options and delimiter as the survey
file. Units and CRS are never assumed; the cell size is in whatever units the
source coordinates use.

## Workflow

1. Inspect the source data with `mine-data-inspection`; establish units and CRS with the data owner before interpreting results.
2. Read survey points, auto-detecting delimiter and header, and report skipped rows.
3. Remove exact duplicate points and XY conflicts; keep the first occurrence and report each cleaning action.
4. Build an unconstrained Delaunay TIN in XY, enforce upward-facing winding, drop zero-area triangles and compute triangle count, planar/3D area and slope statistics.
5. Generate a square-cell DEM anchored at the minimum X/Y; use `linear` with NoData outside the hull or `nearest` to fill the extent.
6. If check points are supplied, interpolate the TIN at their XY and report RMSE, MAE, maximum error and outside-hull exclusions.
7. Export the OBJ mesh, ESRI ASCII DEM and JSON/Markdown reports.
8. Validate the mesh with `mine-model-quality-check --allow-boundary`; note that orientation remains UNKNOWN for an open surface.

## Engineering Rules

- Preserve original X, Y and Z values in the TIN and OBJ; never silently smooth or snap benchmarks.
- Do not smooth benches, slope breaks, crests or toes. If they matter, stop: v0.1 cannot preserve them without breakline constraints.
- Never assume or relabel units or a coordinate reference system.
- Do not extrapolate the linear DEM beyond the TIN convex hull.
- Exclude check points outside the convex hull from RMSE and report the exclusion.
- Never modify source files.
- Keep every cleaning and fallback operation visible in the report.
- Treat the whole input as loaded in memory; split very large surveys first.

## Quality Requirements

- Report TIN vertex/triangle counts, planar and 3D area, slope distribution and Z range.
- Report DEM shape, valid/NoData cells, coverage fraction, grid extent and uncovered remainder.
- Report RMSE, MAE, maximum absolute error and the evaluated/outside check point counts.
- Warn when fewer than 4 check points are evaluated, when a DEM axis has fewer than 2 nodes, when linear coverage is incomplete, or when duplicates/conflicts were removed.
- Every output labels units and CRS as `UNKNOWN`.
- Never claim bench accuracy, volume accuracy or slope safety from an unconstrained TIN.

## Deliverables

- `terrain.obj` — unconstrained Delaunay TIN mesh
- `terrain_dem.asc` — ESRI ASCII DEM with NoData `-9999.0`
- `terrain_report.json` — full statistics and provenance
- `terrain_report.md` — human-readable report

Not produced in v0.1: `terrain.tin`, GeoTIFF DEM, GLB mesh, breakline-constrained surfaces.

## Project Layout

- `scripts/terrain.py` — XYZ reader, TIN, DEM, check points, OBJ/ASC export and CLI
- `references/terrain-methods.md` — TIN/DEM algorithms, grid conventions and limitations
- `references/output-schema.md` — output files, fields and guarantees
- `tests/test_terrain.py` — unittest suite
- `tests/fixtures/survey_hill.csv` — synthetic gridded hill survey points
- `tests/fixtures/check_points.xyz` — independent check points
- `requirements.txt` — `numpy`, `scipy`

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Tests cover TIN counts/area/slope, DEM shape and values, check point RMSE, OBJ
coordinate preservation, ESRI ASCII structure, duplicate cleaning, invalid
inputs and the full CLI output set.

## Related Skills

- `mine-data-inspection` — source format, extents and coordinate clues
- `mine-cad-parser` — contour and survey geometry extraction
- `mine-point-cloud` — ground candidates from LiDAR/UAV point clouds
- `mine-coordinate-registration` — coordinates used for modeling
- `mine-model-quality-check` — independent topology and accuracy verification
- `mine-3d-tiles` — later publication of the mesh to the web
