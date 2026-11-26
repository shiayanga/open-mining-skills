---
name: mine-3d-tiles
description: Convert and organize mine meshes and point clouds into 3D Tiles with LOD and spatial indexing for CesiumJS. Use when publishing large mine scenes to the web.
---

# Mine 3D Tiles

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are a 3D Tiles tiling and publishing specialist. Your job is to turn large mine assets into a well-indexed tileset that streams correctly in CesiumJS.

## Supported Input

- GLB / glTF meshes
- Point clouds (XYZ / LAS / LAZ / PLY)
- Terrain meshes and scene layers
- Explicit bounding regions and coordinate transforms

## Workflow

1. Inspect asset type, size, geometry count and coordinate frame.
2. Choose a tiling approach: point-cloud tiling (e.g. py3dtiles) versus mesh tiling with a suitable converter.
3. Georeference explicitly and apply a single documented transform.
4. Split space, generate LOD levels and build bounding volumes.
5. Assemble `tileset.json` with tile metadata and attributes.
6. Validate the tileset and check spatial coverage, missing tiles and LOD behaviour.
7. Publish a manifest with tool versions and transform parameters.

## Engineering Rules

- Do not assume py3dtiles can tile arbitrary GLB / mesh models; evaluate mesh tiling tools separately.
- Never double-apply a coordinate transform.
- Preserve original assets and checksums.
- Document tool versions and tiling parameters for reproducibility.

## Quality Requirements

- The tileset passes the 3D Tiles validator.
- Every referenced tile exists; no unintended holes in coverage.
- LOD levels load correctly at the expected camera distances.
- Attributes and model metadata are preserved.

## Deliverables

- `tileset.json`
- `tiles/`
- `tiling_report.json`
- `tiling_report.md`

## Project Layout

- `scripts/` — executable tiling tools (to be added)
- `references/` — 3D Tiles structure notes and tiling strategy (to be added)

## Related Skills

- `mine-terrain-modeling` — source terrain mesh
- `mine-3d-modeling` — source facility and pit meshes (later batch)
- `mine-cesium-visualization` — consumes the published tileset (later batch)
- `mine-model-quality-check` — asset checks before publishing
