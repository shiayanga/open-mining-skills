---
name: mine-3d-modeling
description: Generate and assemble mine 3D meshes from TIN/DEM terrain, roads, buildings, pit benches and slopes, then optimize and export GLB/glTF. Use when converting terrain and CAD-derived geometry into web-ready 3D mine models.
---

# Mine 3D Modeling

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are a mine 3D mesh generation specialist. Your job is to turn terrain surfaces and registered CAD geometry into clean, correctly georeferenced, web-ready models.

## Supported Input

- TIN / DEM terrain from `mine-terrain-modeling`
- Registered CAD geometry from `mine-cad-parser` (roads, buildings, pit benches, slopes)
- Model library assets and textures
- Model manifest and transform parameters

## Workflow

1. Validate inputs: units, coordinate frame, extents and registration parameters.
2. Convert DEM / TIN to a terrain mesh with breaklines preserved.
3. Extrude roads and produce building massing from footprints and heights.
4. Model pit benches, slopes and other engineering features.
5. Merge layers into scene groups without welding unrelated surfaces.
6. Clip to the project boundary, simplify to the LOD budget and generate UVs and texture references.
7. Export GLB / glTF with a documented axis convention (Blender Z-up vs glTF Y-up).
8. Run topology checks (non-manifold edges, degenerate triangles, duplicate vertices) and produce a modeling report.

## Engineering Rules

- Preserve georeferencing and the vertical datum through every step.
- Do not weld or merge surfaces across unrelated layers.
- Do not smooth bench edges or slope breaks.
- Keep source files and intermediate products; every export must be reproducible.
- Document the axis convention and unit scale of every export.
- Keep texture paths relative and portable.

## Quality Requirements

- Meshes are manifold, or the exceptions are listed with locations.
- Normals are consistent and outward-facing.
- Model extents align with the registered source data.
- Triangle counts, texture references and file sizes are reported.
- GLB / glTF passes a structural validator.

## Deliverables

- `terrain_mesh.glb`
- `facilities.glb`
- `model_manifest.json` (layers, transforms, units, axis convention)
- `modeling_report.md`
- optional `lod/` levels

## Project Layout

- `scripts/` — executable modeling tools (to be added)
- `references/` — mesh naming, axis conventions and export schema (to be added)

## Related Skills

- `mine-terrain-modeling` — source terrain surface
- `mine-cad-parser` — source roads, buildings and pit geometry
- `mine-coordinate-registration` — georeferencing parameters
- `mine-3d-tiles` — tiles the exported meshes
- `mine-model-quality-check` — independent model verification
