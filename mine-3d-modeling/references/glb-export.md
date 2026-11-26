# Minimal GLB Export (v0.1)

## Container layout

`model.glb` is a glTF 2.0 binary file:

| Part | Content |
|---|---|
| Header (12 bytes) | Magic `glTF`, version `2`, total file length |
| JSON chunk | Chunk length and type `JSON` (`0x4E4F534A`), padded with spaces |
| BIN chunk | Chunk length and type `BIN\0` (`0x004E4942`), padded with zero bytes |

The JSON document contains one buffer (the BIN chunk), three buffer views
(POSITION, NORMAL, indices), one mesh, one node and one scene. Buffer 0 has no
URI because it is supplied by the GLB BIN chunk.

## Accessors

| Accessor | Type | Component | Content |
|---|---|---|---|
| POSITION | `VEC3` | `FLOAT` (5126) | One position per merged vertex, with min/max |
| NORMAL | `VEC3` | `FLOAT` (5126) | One unit normal per merged vertex |
| Indices | `SCALAR` | `UNSIGNED_INT` (5125) | Three indices per triangle |

Indices are 32-bit as required by the v0.1 contract. glTF permits `UNSIGNED_INT`
in core 2.0, but some older viewers prefer `UNSIGNED_SHORT`; a future version
can choose the smallest valid index type.

## Axis conversion

Mine engineering data is normally Z-up; glTF is Y-up and right-handed. The
exporter applies:

```text
position: (x, y, z) -> (x, z, -y)
normal:   (nx, ny, nz) -> (nx, nz, -ny)
```

This is a proper rotation (determinant `+1`), so triangle winding is preserved.
The mapping is written into `asset.extras` and `model_manifest.json`. No
georeferencing or unit conversion is applied.

When tiling this GLB with `mine-3d-tiles`, pass the Y-up
`glb.position_bounds` (min/max) from `model_manifest.json` as `--bbox`. Do not
pass the Z-up `merged.bounds`, which would misplace the 3D Tiles bounding box.

## Float32 precision

glTF positions are 32-bit floats. At a coordinate magnitude of `1e5` the
spacing is about 0.01 m; at `4e6` (a typical northing) it is about 0.25 m. This
matters for mine coordinates in a projected CRS.

The exporter reports `position_abs_max` and emits a warning when it exceeds
`1e5`. For survey-grade work, recenter the model near a local origin and carry
the origin as a georeferencing transform, or use an RTC/ECEF-aware pipeline.
v0.1 does not add `CESIUM_RTC`, `RTC_CENTER` or a root tile transform.

## Normals

Normals are area-weighted per vertex: non-normalized face normals are summed
into their three vertices and normalized. Box faces do not share vertices, so
box edges remain hard; shared terrain vertices are smooth-shaded. Vertices with
a zero accumulated normal fall back to `(0, 0, 1)`.

The exporter does not recompute or flip source winding, so inconsistent input
winding will produce inconsistent normals.

## What is not exported

- materials, textures, UVs, vertex colors
- tangents, morph targets, skinning, animations
- LOD levels, Draco/meshopt compression, 3D Tiles metadata
- cameras, lights or georeferencing extensions

Viewers apply the glTF default material, so the model renders in a neutral
color.

## Validation performed by the test suite

- magic is `glTF`, version is `2`, header length equals the file size
- both chunk types are present and the total length is 4-byte aligned
- `asset.version` is `2.0`
- POSITION and NORMAL counts equal the merged vertex count
- index count equals three times the merged triangle count
- buffer byte length matches the three accessors and fits the BIN chunk
- POSITION min/max equal the merged bounds after axis conversion

## Future work

A production pipeline can replace or extend this exporter with Blender's Python
API or Trimesh for:

- UV unwrapping, PBR materials and texture baking
- mesh simplification and LOD generation
- non-manifold and duplicate-vertex repair
- clipping to the pit boundary and terrain conformance
- glTF validator integration and Draco compression

Those tools are optional processing engines, not required to reproduce the v0.1
geometry. Blender is not invoked by this skill.
