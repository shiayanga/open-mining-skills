---
name: mine-3d-tiles
description: Convert and organize mine meshes and point clouds into 3D Tiles with LOD and spatial indexing for CesiumJS. Use when publishing large mine scenes to the web.
---

# Mine 3D Tiles

> Status: v0.1 — single-tile 3D Tiles 1.1 tileset generation for OBJ/GLB and local structural validation are implemented with tests. Point-cloud tiling, spatial subdivision and LOD generation are not implemented; py3dtiles is documented as the future path.

## Role

You are a 3D Tiles tiling and publishing specialist. Your job is to package mine assets into a correctly structured, verifiable tileset — and to be explicit when a single tile is a placeholder rather than a true spatial index.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| OBJ content | Bounding box computed from `v` records; content copied beside `tileset.json` |
| GLB content | Header magic/version/length checked; `--bbox` is required because GLB buffers are not parsed. Supply the box in the GLB content frame (glTF Y-up); for models from `mine-3d-modeling`, use `glb.position_bounds` in its manifest |
| `.gltf` (separate JSON + BIN) | Not supported; pack to GLB or supply a supported OBJ |
| LAS / LAZ / PLY / XYZ point clouds | Not tiled; planned via py3dtiles |
| Spatial subdivision | Not implemented; one root tile |
| LOD generation | Not implemented; one content level |
| Tileset validation | Single root only: asset version, root, box (12 values), geometricError, local content existence |
| Multiple `contents` / child tiles / external tilesets | Not validated in v0.1 |

## Quick Start

Run the following commands from this skill directory. No third-party packages are required.

```bash
# OBJ: bounds are read from the vertices
python3 scripts/make_tileset.py tests/fixtures/dummy.obj --out-dir tiles_output

# GLB: supply the bounding box explicitly
python3 scripts/make_tileset.py model.glb \
  --bbox 0,0,0,100,50,20 --out-dir tiles_output

# Structural validation; exits 0 on pass and 1 on failure
python3 scripts/validate_tileset.py tiles_output/tileset.json
python3 scripts/validate_tileset.py tiles_output/tileset.json --json
```

## Options

`make_tileset.py`:

| Option | Default | Meaning |
|---|---|---|
| `--bbox` | none | `minx,miny,minz,maxx,maxy,maxz`; required for GLB, optional override for OBJ |
| `--out-dir` | `tiles_output` | Output directory |
| `--geometric-error` | bbox diagonal | Top-level `geometricError` |
| `--refine` | `ADD` | Root tile `refine` method (`ADD` or `REPLACE`) |

`validate_tileset.py`:

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print the full machine-readable validation result |

## Workflow

1. Identify the content type and size; reject formats not supported in v0.1.
2. For OBJ, compute the bounding box from all `v` records; for GLB, verify the header and require `--bbox` in the GLB content frame (typically glTF Y-up, not the source Z-up frame).
3. Decide the coordinate frame and units. v0.1 does not transform coordinates; the tileset, content and bounding box all remain in the content frame.
4. Copy the content file next to `tileset.json` so the package is self-contained.
5. Emit a 3D Tiles 1.1 document: `asset.version`, top-level `geometricError`, a root tile with a 12-value axis-aligned `boundingVolume.box`, root `geometricError` 0, `refine`, and a relative `content.uri`.
6. Write `tiling_report.json` and `tiling_report.md`, recording the bbox source, checksums, warnings and limitations.
7. Run `validate_tileset.py`; fix every reported error before publishing.
8. Treat this as a single-tile package until real spatial tiling and LOD are implemented.

## Engineering Rules

- Do not assume py3dtiles can tile arbitrary GLB/mesh models; evaluate mesh tiling tools separately.
- Never double-apply a coordinate transform. The tileset does not georeference content in v0.1.
- Preserve the original content file and record its SHA-256.
- Keep content URIs relative and local; remote or absolute URIs are rejected by the validator.
- Do not claim LOD or spatial indexing when only a single tile exists.
- Record the origin of every bounding box (OBJ vertices, explicit `--bbox`, or override).
- Do not present a structurally valid tileset as a validated visual scene.

## Quality Requirements

- `tileset.json` parses as JSON and declares `asset.version` `1.1`.
- Top-level and root `geometricError` are present and non-negative.
- `boundingVolume.box` contains exactly 12 finite numbers with non-degenerate half-axes.
- The root content URI is relative, and the referenced file exists in the tileset directory.
- The bounding box agrees with OBJ vertex bounds or the explicitly supplied `--bbox`.
- The content checksum in the report matches the copied file.
- `validate_tileset.py` exits `0` with no errors before the tileset is published.
- Warnings (single tile, no LOD, unknown units/CRS) are reported with the deliverable.

## Deliverables

- `tileset.json`
- copied content file (e.g. `model.glb` or `terrain.obj`)
- `tiling_report.json`
- `tiling_report.md`

## Project Layout

- `scripts/make_tileset.py` — OBJ bounds, GLB header check, bbox handling, tileset assembly and CLI
- `scripts/validate_tileset.py` — local single-root structural validator and CLI
- `scripts/common.py` — hashing, JSON/text output and formatting helpers
- `references/tileset-structure.md` — 3D Tiles 1.1 single-tile structure and box semantics
- `references/validation-rules.md` — checks, error codes, exit codes and coverage limits
- `references/tiling-roadmap.md` — py3dtiles, mesh tiling and LOD path beyond v0.1
- `tests/fixtures/dummy.obj`
- `tests/test_tileset.py` — unittest suite

No third-party dependencies are used, so there is no `requirements.txt`.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

The suite covers OBJ bbox extraction, OBJ/GLB tileset generation, bbox overrides and parse errors, and validation failures for missing content, malformed boxes, missing geometricError values, unsupported asset versions and missing roots.

## Related Skills

- `mine-terrain-modeling` — source terrain mesh
- `mine-3d-modeling` — source facility and pit meshes
- `mine-cesium-visualization` — consumes the published tileset
- `mine-model-quality-check` — asset checks before publishing
