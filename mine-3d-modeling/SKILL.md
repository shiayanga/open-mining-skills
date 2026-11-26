---
name: mine-3d-modeling
description: Generate and assemble mine 3D meshes from TIN/DEM terrain, roads, buildings, pit benches and slopes, then optimize and export GLB/glTF. Use when converting terrain and CAD-derived geometry into web-ready 3D mine models.
---

# Mine 3D Modeling

> Status: v0.1 — merging a terrain OBJ with rotated footprint boxes and exporting OBJ, a minimal GLB and a manifest is implemented with tests. DEM/TIN conversion, roads, pit benches, slopes, clipping, mesh simplification, UVs, textures and materials are not yet implemented; Blender/Trimesh processing is documented as future work.

## Role

You are a mine 3D mesh generation specialist. Your job is to turn terrain surfaces and registered CAD geometry into clean, correctly georeferenced, web-ready models — and to state clearly which geometry is real and which is a placeholder.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| Terrain OBJ | `v` vertices and `f` faces; polygons fan-triangulated; `vt`, `vn`, materials and groups are ignored |
| Footprints CSV | `id,x,y,width,depth,height,rotation_deg`, optional `base_z` (or `z`) |
| Footprint geometry | One box per footprint, rotated around +Z; `x,y` is the footprint centre |
| Base elevation | Explicit `base_z` when present, otherwise the nearest terrain vertex in XY |
| GLB export | glTF 2.0 binary with POSITION, NORMAL and uint32 indices; source Z-up converted to glTF Y-up |
| DEM / TIN, roads, pit benches, slopes | Not yet modeled |
| Textures, UVs, materials, LOD, clipping | Not exported |
| Blender / Trimesh pipeline | Not used in v0.1; see `references/glb-export.md` |

## Quick Start

Run the following commands from this skill directory. No third-party packages are required.

```bash
python3 scripts/build_model.py tests/fixtures/terrain.obj \
  tests/fixtures/footprints.csv --out-dir model_output
```

Exit code `0` on success. Invalid inputs (missing columns, non-numeric values, non-positive dimensions, bad OBJ indices) exit non-zero with a file and line reference.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--out-dir` | `model_output` | Output directory |
| `--precision` | `6` | Decimal places written to `model.obj` (GLB is always float32) |

## Workflow

1. Read the terrain OBJ subset (`v`, `f`) and confirm that at least one valid triangle exists.
2. Read and validate the footprints CSV; reject duplicate ids, non-numeric fields and non-positive dimensions.
3. Determine each footprint base elevation from `base_z`, or infer it from the nearest terrain vertex and record that the value was inferred.
4. Build one 24-vertex, 12-triangle box per footprint, applying Z rotation and translation.
5. Merge terrain triangles and box triangles without welding unrelated surfaces.
6. Write the merged OBJ in source Z-up coordinates, with `o terrain` and one object group per footprint.
7. Export a minimal GLB: convert Z-up to glTF Y-up, compute area-weighted per-vertex normals and store uint32 indices.
8. Write `model_manifest.json`, a machine-readable report and a short Markdown report; list every inferred value and limitation.

## Engineering Rules

- Never assume units or a CRS; both are recorded as `UNKNOWN` until the project supplies evidence.
- Preserve source coordinates, names and provenance checksums.
- Do not present boxes as surveyed buildings or CAD/BIM geometry; they are massing placeholders.
- Do not weld terrain to boxes, and do not smooth bench or slope breaks.
- Document the axis convention of every export. Source and OBJ are Z-up; GLB is Y-up using `(x, y, z) -> (x, z, -y)`.
- Do not silently drop degenerate triangles or unreferenced vertices; count them and report them.
- Keep the v0.1 implementation dependency-free and reproducible.

## Quality Requirements

- Merged vertex and triangle counts equal terrain counts plus 24 vertices and 12 triangles per box; unreferenced terrain vertices are retained and included in the merged bounds.
- Rotated box bounds match the closed-form rotated rectangle bounds within 1e-5.
- The GLB has a valid `glTF` header, version 2, correct chunk lengths and a JSON chunk with a 2.0 asset.
- GLB accessors agree with the merged mesh: one POSITION and one NORMAL per merged vertex, three indices per triangle.
- POSITION accessor min/max equal the merged bounds after the Z-up to Y-up conversion.
- Positions above 1e5 in absolute value trigger a float32 precision warning in the manifest.
- Every inferred base elevation, removed triangle and orphan vertex is listed in the manifest and report.
- No unit, CRS or accuracy claim is made without source evidence.

## Deliverables

- `model.obj` — merged terrain and footprint boxes, Z-up
- `model.glb` — minimal glTF 2.0 binary
- `model_manifest.json` — sources, axis convention, counts, bounds, footprints, GLB metadata
- `modeling_report.json`
- `modeling_report.md`

## Project Layout

- `scripts/build_model.py` — OBJ/footprints parsing, box generation, merge, OBJ/GLB export and CLI
- `scripts/common.py` — hashing, JSON/text output and formatting helpers
- `references/obj-subset.md` — supported OBJ records, triangulation and winding assumptions
- `references/footprint-schema.md` — CSV fields, box construction, base elevations and bounds
- `references/glb-export.md` — GLB layout, axis conversion, normals, validation and future work
- `tests/fixtures/terrain.obj`, `tests/fixtures/footprints.csv`
- `tests/test_build_model.py` — unittest suite

No third-party dependencies are used, so there is no `requirements.txt`.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

The suite checks merged OBJ counts, GLB magic/version/chunks/accessors, manifest contents, rotated box bounds from both the manifest and the merged OBJ, explicit base elevations and invalid dimensions.

## Related Skills

- `mine-terrain-modeling` — source terrain surface
- `mine-cad-parser` — source roads, buildings and pit geometry
- `mine-coordinate-registration` — georeferencing parameters
- `mine-3d-tiles` — tiles the exported GLB
- `mine-model-quality-check` — independent model verification
