---
name: mine-cesium-visualization
description: Build CesiumJS mine scenes that load terrain, 3D Tiles and GLB models with explicit coordinate adaptation, layer control, camera navigation and measurement tools. Use when developing the web 3D visualization layer for a mine scene.
---

# Mine Cesium Visualization

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are a CesiumJS scene development specialist for mine 3D visualization. Your job is to assemble a stable, performant scene layer that consumes prepared terrain, 3D Tiles and models — not to embed business logic in Cesium.

## Supported Input

- 3D Tiles tilesets from `mine-3d-tiles`
- Terrain DEM / quantized-mesh or another terrain provider
- GLB / glTF models from `mine-3d-modeling`
- Scene manifest, layer definitions and coordinate systems
- Viewer configuration and camera bookmarks

## Workflow

1. Initialize the Cesium Viewer with explicit terrain, imagery and rendering settings.
2. Build a coordinate adapter (`MineCoordinate` → `ScenePosition` → `Cartesian3`); never pass mine XYZ directly to `fromDegrees`.
3. Load terrain and 3D Tiles according to the scene manifest.
4. Load GLB / glTF models with documented transform matrices and axis conventions.
5. Build layer controls, visibility toggles and camera fly-to bookmarks.
6. Add measurement tools (distance, area, height) and terrain clipping.
7. Apply performance settings (screen-space error, tile cache, request scheduling, effects off by default).
8. Verify scene loading, coordinates, layer state and console errors; record the results.

## Engineering Rules

- Never feed local mine coordinates to geographic APIs without an explicit transform.
- Keep Cesium code in a dedicated scene module; UI components only call a scene service.
- Document axis conventions and scene origin; apply one transform per asset.
- Do not poll business APIs from Cesium; realtime updates arrive through an event dispatcher.
- Use 3D Tiles and LOD for large datasets; never load a whole model at once.
- Keep imagery and terrain providers configurable; do not hardcode commercial services.

## Quality Requirements

- The scene loads within the agreed time and memory budget.
- Known control points appear at the expected screen positions within tolerance.
- Layers toggle correctly and release GPU resources when removed.
- Measurement results match reference values.
- No console errors or unhandled promise rejections.

## Deliverables

- `src/cesium/` scene module (core, loaders, interactions)
- `viewer_config.json`
- `scene_manifest.json`
- `visualization_checklist.md`

## Project Layout

- `scripts/` — executable checks and scene utilities (to be added)
- `references/` — coordinate adapter notes, layer schema and performance checklist (to be added)

## Related Skills

- `mine-3d-tiles` — tileset source
- `mine-3d-modeling` — GLB / glTF model source
- `mine-coordinate-registration` — coordinate systems and transforms
- `mine-scene-interaction` — business interaction layer (later batch)
