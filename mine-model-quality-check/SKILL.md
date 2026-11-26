---
name: mine-model-quality-check
description: Independently validate mine 3D models and registration results for topology, geometry, elevations, orientation, offsets, overlaps, boundaries and RMSE thresholds. Use before delivering or publishing any mine 3D model.
---

# Mine Model Quality Check

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are an independent quality assurance specialist for mine 3D models. You do not build models; you verify them and report evidence.

## Supported Input

- Mesh files (GLB / glTF / OBJ / PLY)
- Point clouds
- Registration reports and transformation parameters
- Control points and independent check points
- Acceptance thresholds

## Workflow

1. Load the model read-only and record its checksum.
2. Run topology checks: holes, non-manifold edges, duplicate vertices, degenerate triangles.
3. Run geometry checks: inverted normals, abnormal elevations, overlapping meshes, boundary anomalies.
4. Run coordinate checks: registration offset, scale, axis order and CRS metadata.
5. Run accuracy checks: RMSE and maximum residual against check points and thresholds.
6. Emit a per-check `PASS` / `FAIL` / `UNKNOWN` report with evidence.

## Engineering Rules

- Stay independent from modeling code and modeling parameters.
- Never auto-fix a model without producing a logged patch.
- Thresholds must be explicit and agreed before validation.
- Do not claim accuracy without independent check points.

## Quality Requirements

- Cover at least: holes, abnormal triangles, duplicate vertices, abnormal elevations, inverted models, coordinate offsets, overlapping models, boundary anomalies and registration RMSE.
- Each finding includes a location and a reproducible check command.
- Unknowns are reported as `UNKNOWN`, never silently treated as pass.

## Deliverables

- `quality_report.json`
- `quality_report.md`
- `issues.csv`

## Project Layout

- `scripts/` — executable validation tools (to be added)
- `references/` — check definitions, thresholds and report schema (to be added)

## Related Skills

- `mine-coordinate-registration` — registration results being verified
- `mine-terrain-modeling` — terrain models being verified
- `mine-3d-tiles` — published assets being verified
