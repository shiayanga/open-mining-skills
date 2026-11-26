# Check Definitions (v0.1)

## Status semantics

Every check returns one of:

| Status | Meaning |
|---|---|
| `PASS` | The check ran and found no violation. |
| `FAIL` | The check found a violation of an explicit requirement. |
| `UNKNOWN` | The check could not be evaluated with the available input. |

Overall status: `FAIL` if any check fails; otherwise `UNKNOWN` if any check is
unknown; otherwise `PASS`. The CLI exits `1` on overall `FAIL` unless
`--no-fail` is supplied. `UNKNOWN` exits `0` but must be reviewed manually; it
is never silently converted to pass.

## Duplicate vertices

Vertices are rounded to `--round-decimals` (default 6), then grouped by exact
rounded position. A group with two or more vertices produces a failure; the
metric is the number of extra vertices, not the number of groups.

- Only positions are compared. UV seams, normal seams and material splits that
  legitimately duplicate positions are not modelled in OBJ v0.1, so they also
  fail.
- No merging or repair occurs.
- Rounding can merge very close but intentionally distinct points. Lower
  `--round-decimals` when this matters.

## Degenerate triangles

A triangle is degenerate when any of:

- two or three vertex indices are identical
- its 3D area is `<= --area-epsilon` (default `1e-12`, source units squared)
- its area is not finite

Every degenerate triangle fails the check. The report records the triangle
index, OBJ line, vertex indices, area and reason.

## Edges

Faces are fan-triangulated first. For each triangle, three undirected vertex
pairs are collected, sorted and counted. Self-edges from repeated indices are
excluded from edge counts (the triangle is already reported as degenerate).

| Count | Classification |
|---:|---|
| 1 | boundary edge |
| 2 | manifold interior edge |
| greater than 2 | non-manifold edge |

- Any non-manifold edge is a failure.
- Boundary edges fail when the mesh is expected to be closed (default).
- `--allow-boundary` accepts boundary edges for open surfaces such as terrain.

## Boundary loops and holes

Boundary edges are traced through vertex adjacency into:

- **closed loops** — each is interpreted as one hole for a closed mesh
- **open chains** — a boundary path that does not close, often caused by a
  missing face configuration, a pinch point or a non-manifold vertex

`hole_count = boundary_loop_count` for reporting. For an open terrain sheet the
outer boundary is also a closed loop, so it is not automatically a defect; use
`--allow-boundary` and review the loop size and location. Boundary vertices with
degree greater than 2 generate a warning because loop tracing may be ambiguous.

## Signed volume and orientation

For a closed mesh (no boundary edges, no non-manifold edges, at least one face):

```
V = (1/6) * sum over triangles of dot(v0, cross(v1, v2))
```

- `V > 0`: outward orientation under the right-hand rule (`OUTWARD`, passes)
- `V < 0`: inverted winding (`INWARD`, fails)
- `V = 0`: orientation cannot be established (`ZERO`, fails)

If the mesh is not closed, signed volume is still reported but orientation is
`UNKNOWN`; the value is not physically meaningful. The check uses net volume
only. A closed mesh with mixed local winding may still produce the correct
global sign and is not reliably detected. Self-intersections are not checked.

## Bounding box and Z range

The checker reports finite vertex extents and spans in X, Y and Z. Non-finite
coordinates fail `coordinate_extent`. No elevation threshold is applied because
units and the expected datum are unknown. Provide an external threshold if an
elevation acceptance criterion exists.

## Face references

OBJ face tokens may be `i`, `i/j`, `i/j/k` or `i//k`. Negative indices are
resolved relative to the vertices read so far. Zero, non-integer and
out-of-range indices make that face element invalid; invalid faces are excluded
from topology checks and fail `face_indices`.

## Registration RMSE

`--registration <report.json>` requires `--max-rmse <value>`. The checker looks
for `rmse` and `max_residual` in:

1. a `diagnostics` object
2. a `parameters` object
3. the top level

This matches `mine-coordinate-registration` output. `PASS` requires
`rmse <= max_rmse`. A missing numeric RMSE yields `UNKNOWN`. `max_residual` is
reported as evidence but is not thresholded by this option. The RMSE units are
whatever the registration report used; confirm they match the model units.

## Limits and thresholds

- `--area-epsilon` is absolute and in source units squared; it is not scaled by
  model size. For very small or very large models, set it explicitly.
- Duplicate rounding is absolute in source units.
- Triangle area is true 3D area; perimeter or edge-length degeneracy is not
  checked separately.
- The checker reads one model per run. Overlaps, offsets between models, CRS
  metadata, texture/normal validity and attribute completeness are not checked
  in v0.1.
- Detail arrays in JSON/Markdown/CSV are capped at 100 entries; the metrics
  counts are complete.
- The checker is read-only and never repairs the model.

## Reproduction

Every report includes a `reproduction_command` built from the model path and the
active options. Run it from this skill directory to reproduce the same
`PASS`/`FAIL`/`UNKNOWN` result. Each issue entry includes an OBJ line, triangle
index, vertex index or edge endpoints as its location.
