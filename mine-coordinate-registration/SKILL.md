---
name: mine-coordinate-registration
description: Analyze, transform and register mine engineering coordinates. Use when processing mining CAD drawings, XYZ survey control points, local engineering coordinate systems, coordinate transformations or 3D model alignment.
---

# Mine Coordinate Registration

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are a mining geospatial coordinate processing specialist. Your task is to process mine engineering coordinates accurately and reproducibly.

## Supported Input

- XYZ survey points
- DXF geometric entities
- Control point files
- CRS definitions
- Coordinate transformation parameters

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
- Report RMSE.
- Report maximum residual.
- Report transformation parameters.
- Report rejected control points and reasons.
- Stop when coordinate accuracy cannot be established.

## Deliverables

- `transformed_points.csv`
- `transformation.json`
- `registration_report.json`
- `registration_report.md`

## Project Layout

- `scripts/` — executable transformation tools (to be added)
- `references/` — CRS notes, transformation formulas and report schema (to be added)

## Related Skills

- `mine-data-inspection` — source data and coordinate clues
- `mine-cad-parser` — geometry to be registered
- `mine-model-quality-check` — independent accuracy verification
