# Tiling Roadmap Beyond v0.1

The v0.1 skill deliberately stops at a single-tile package. This note records
the intended path to real spatial indexing, LOD and point-cloud tiling so that
future work is not confused with current capability.

## Why not tile meshes in v0.1

- Spatial subdivision needs a tiling policy: quadtree, octree or k-d tree,
  maximum tile size, maximum depth and bounding-volume padding.
- LOD needs simplification with error metrics and a validation strategy for
  cracks and attribute preservation.
- Mesh tiling is not a solved single-tool operation. py3dtiles is strongest for
  point clouds; its mesh support must be evaluated against the actual GLB/OBJ
  content rather than assumed.

Shipping a fake or unverified subdivision would make the tileset appear more
capable than it is. v0.1 therefore emits one honest root tile and validates it.

## py3dtiles path for point clouds

py3dtiles can convert XYZ, LAS, LAZ and PLY point clouds into 3D Tiles and can
build a tileset with a spatial index. A future version of this skill should:

1. Verify the installed py3dtiles version and its supported input formats.
2. Convert the point cloud with an explicit CRS and unit decision.
3. Generate a tileset with a documented geometric-error policy.
4. Validate the output with both the appropriate py3dtiles checks and
   `validate_tileset.py`.
5. Preserve a manifest with tool versions and parameters.

Do not use py3dtiles as a claimed mesh/GLB tiler without a separate evaluation.

## Mesh tiling path

Candidate approaches to evaluate:

- Cesium's glTF-to-3D-Tiles tooling and `3d-tiles-tools`
- py3dtilers for OBJ/GeoJSON-derived content
- Custom tiling with a documented octree/quadtree, tile size threshold and LOD
  simplification metric

Every candidate must be checked for:

- correct handling of mine coordinates and Z-up/Y-up conventions
- material/texture preservation
- bounding-volume correctness and coverage gaps
- attribute/metadata preservation
- performance with the target mine scene size

## LOD policy sketch

A defensible LOD policy needs:

- a root-to-leaf geometric error schedule (for example halving per level)
- a maximum screen-space error and maximum memory budget
- simplification that preserves pit benches and slope breaks
- validation that adjacent LOD levels do not create visible cracks or holes

Only after these are implemented should `mine-3d-tiles` claim LOD support.

## Compatibility note

The current generator writes `root.content.uri`, the 3D Tiles 1.1 single-content
form. Future multi-content support should use `contents` and update the validator
at the same time.
