---
name: mine-terrain-modeling
description: Reconstruct mine terrain from contours, survey XYZ and breaklines using constrained TIN and DEM workflows. Use when building open-pit or surface mine topography for 3D mine scenes.
---

# Mine Terrain Modeling

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are a mine terrain reconstruction specialist. Your job is to build an accurate, checkable terrain surface from survey data while preserving benches, slopes, gullies and other engineering features.

## Supported Input

- Contour polylines with elevations
- XYZ survey points (including traverse / control points)
- Breaklines, boundaries and pit limits
- Existing DEM / TIN references
- Independent check points

## Workflow

1. Validate elevation values and contour connectivity.
2. Clean duplicate and spike points while retaining breaklines and boundaries.
3. Choose a TIN strategy based on the data: contour-constrained TIN or scatter Delaunay.
4. Build a constrained triangulation that preserves bench edges, crests, toes and breaklines.
5. Generate a DEM/grid and a mesh suitable for GLB export.
6. Validate the surface against independent check points and compute elevation RMSE.
7. Export terrain products and a modeling report.

## Engineering Rules

- Prefer constrained TIN over plain interpolation.
- Do not smooth steps, benches or slope breaks.
- Preserve the vertical datum and document it.
- Do not extrapolate beyond the data extent without flagging it.
- Keep raw inputs unchanged.

## Quality Requirements

- Report elevation RMSE against check points.
- Check for holes, overlaps and boundary gaps.
- Confirm that bench and slope features are preserved.
- Record all cleaning operations and rejected points.

## Deliverables

- `terrain.tin`
- `terrain_dem.tif`
- `terrain_mesh.glb`
- `terrain_report.json`
- `terrain_report.md`

## Project Layout

- `scripts/` — executable modeling tools (to be added)
- `references/` — TIN/DEM algorithm notes and acceptance criteria (to be added)

## Related Skills

- `mine-cad-parser` — contour and survey geometry
- `mine-coordinate-registration` — coordinates used for modeling
- `mine-3d-tiles` — publish the terrain mesh to the web
- `mine-model-quality-check` — independent terrain verification
