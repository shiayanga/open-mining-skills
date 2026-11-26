---
name: mine-cesium-visualization
description: Build CesiumJS mine scenes that load terrain, 3D Tiles and GLB models with explicit coordinate adaptation, layer control, camera navigation and measurement tools. Use when developing the web 3D visualization layer for a mine scene.
---

# Mine Cesium Visualization

> Status: v0.1 — `viewer_config.json` / `scene_manifest.json` validation and Cesium reference patterns are implemented with tests. The Vue 3 + CesiumJS application (Viewer bootstrap, loaders, measurement and clipping runtime) is documented but not yet generated or executed by this skill.

## Role

You are a CesiumJS scene development specialist for mine 3D visualization. Your job is to assemble a stable, performant scene layer that consumes prepared terrain, 3D Tiles and models — not to embed business logic in Cesium.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| `viewer_config.json` | Validated: terrain/imagery providers, scene origin, coordinate system, axis convention, rendering and performance settings |
| `scene_manifest.json` | Validated: scene/mine IDs, terrain, unique layer IDs, tilesets with URIs and transforms, optional GLB models and camera bookmarks |
| Terrain / 3D Tiles / GLB assets | Referenced by URI; assets themselves are not fetched or inspected in v0.1 |
| Commercial provider URLs | Rejected when hardcoded (Cesium ion, Mapbox, Tianditu, ArcGIS Online and similar) |
| Vue 3 + CesiumJS app | Patterns in `references/cesium-scene-patterns.md`; application generation is future work |

## Quick Start

Run the following commands from this skill directory. The validator uses the Python standard library only.

```bash
python3 scripts/validate_scene.py \
  tests/fixtures/viewer_config.json \
  tests/fixtures/scene_manifest.json

# Writes scene_validation.json and scene_validation.md in the current directory.
```

Explicit output paths:

```bash
python3 scripts/validate_scene.py viewer_config.json scene_manifest.json \
  --output output/scene_validation.json \
  --markdown output/scene_validation.md
```

Exit code `0` when there are no errors, `1` when validation fails. Warnings do not fail the run.

## Options

| Option | Default | Meaning |
|---|---|---|
| `viewer_config` | required | Path to `viewer_config.json` |
| `scene_manifest` | required | Path to `scene_manifest.json` |
| `--output` | `scene_validation.json` | JSON report path |
| `--markdown` | `scene_validation.md` | Markdown report path |
| `--no-fail` | off | Exit `0` even when validation errors are found |

## Workflow

1. Confirm the viewer config declares a self-hosted terrain provider and imagery provider; reject hardcoded commercial services.
2. Confirm the scene origin, `coordinateSystemId` and axis convention are explicit and consistent between viewer and manifest.
3. Check rendering and performance settings for positive values and sane ranges.
4. Validate scene identity, terrain entry and layer definitions; enforce unique layer IDs.
5. Validate every tileset and model: non-empty URI, known layer reference, and a 16-number transform when present.
6. Validate camera bookmarks: unique ID, valid destination, numeric orientation.
7. Emit `scene_validation.json` and `scene_validation.md`; do not silently downgrade errors.
8. Use `references/cesium-scene-patterns.md` for the future Viewer, CoordinateAdapter, loader, measurement and clipping implementation.

## Engineering Rules

- Never feed local mine coordinates to geographic APIs without an explicit transform.
- Keep Cesium code in a dedicated scene module; UI components only call a scene service.
- Document axis conventions and scene origin; apply one transform per asset.
- Do not hardcode commercial terrain, imagery or tileset provider URLs.
- Do not poll business APIs from Cesium; realtime updates arrive through an event dispatcher.
- Use 3D Tiles and LOD for large datasets; never load a whole model at once.
- Treat the coordinate adapter as the single conversion boundary; validate `coordinateSystemId` on every incoming position.
- The skill validates configuration; it does not claim that a scene renders correctly.

## Quality Requirements

- Every tileset and model URI is present, non-empty and resolvable by the deployment environment.
- Layer IDs are unique and every `layerId` reference resolves.
- Scene manifest and viewer config agree on `coordinateSystemId` and axis convention.
- Transforms contain exactly 16 finite numbers.
- No hardcoded commercial provider URLs are present.
- Validation output is reproducible and records input SHA-256 checksums.
- The Vue/Cesium app remains out of scope until a runnable skeleton is added.

## Deliverables

- `scene_validation.json`
- `scene_validation.md`
- For project use: validated `viewer_config.json` and `scene_manifest.json` supplied by the scene owner

## Project Layout

- `scripts/validate_scene.py` — viewer/scene configuration validator and CLI
- `scripts/common.py` — JSON I/O, hashing and formatting helpers
- `references/cesium-scene-patterns.md` — TypeScript patterns for Viewer, coordinate adapter, loaders, measurement and clipping
- `references/scene-schema.md` — input schema, validation rules and report fields
- `tests/` — unittest suite and valid viewer/scene fixtures

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Run from this skill directory. No third-party packages are required.

## Related Skills

- `mine-3d-tiles` — tileset source
- `mine-3d-modeling` — GLB / glTF model source
- `mine-coordinate-registration` — coordinate systems and transform parameters
- `mine-scene-interaction` — business interaction layer
