# OBJ Subset and Merge Rules (v0.1)

The model builder implements a deliberately small, dependency-free OBJ reader.
It is designed for terrain meshes exported by `mine-terrain-modeling`, not for
general-purpose asset conversion.

## Supported records

| Record | v0.1 behaviour |
|---|---|
| `v x y z [w]` | Read as a vertex; `w` is ignored |
| `f ...` | Read as a polygon; fan-triangulated |
| `#` comments and blank lines | Ignored |
| `vt`, `vn` | Counted but not used |
| `o`, `g`, `s`, `usemtl`, `mtllib`, `l`, `p` and other records | Counted as `other` and ignored |

## Face rules

- Face references may be positive (`1`-based) or negative (relative to the
  vertices defined so far). Reference `0` is invalid.
- A face must reference vertices that have already been defined. Forward
  references are not supported in v0.1.
- Faces with fewer than three vertices are rejected.
- Polygons are fan-triangulated: a face `a b c d` becomes `a b c` and `a c d`.
- Triangles with repeated indices, or with a squared area at or below `1e-24`
  in source units, are removed and counted as
  `degenerate_triangles_removed`. The threshold is absolute, not scale-relative.
- Vertex winding is preserved. Counter-clockwise is assumed to be the front
  face for normals; the tool does not repair inconsistent winding.

## Merge behaviour

- Terrain vertices and triangles are kept first, in source order.
- Each footprint contributes 24 vertices and 12 triangles. Every box face has
  its own four vertices, so box edges stay hard when normals are generated.
- No welding, duplicate-vertex removal, hole filling or topology repair is
  performed.
- The merged OBJ contains only `v` and `f` records plus `o` groups. Source
  UVs, normals, materials, smoothing groups and object names are not preserved.
- Unreferenced terrain vertices are kept and reported as `orphan_vertex_count`.

## Units and axes

- Units are `UNKNOWN`; the tool never rescales geometry.
- Coordinates remain in the source frame (assumed Z-up for mine engineering
  data).
- The merged OBJ does not add a CRS or a georeferencing transform.
