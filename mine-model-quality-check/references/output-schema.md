# Quality Output Schema (v0.1)

Outputs are written to `--out-dir` (default `quality_output`). They are UTF-8;
`issues.csv` includes a BOM for spreadsheet compatibility. Source models are
never modified.

## `quality_report.json`

| Field | Description |
|---|---|
| `file`, `source` | Source name and `path`/`name`/`size_bytes`/`sha256` |
| `format` | `OBJ` |
| `encoding` | Encoding actually used to read the OBJ |
| `units`, `crs` | Always `UNKNOWN` |
| `status` | Overall `PASS`, `FAIL` or `UNKNOWN` |
| `options` | `expect_closed`, `round_decimals`, `area_epsilon`, `registration_report`, `max_rmse` |
| `metrics` | Complete numeric summary (see below) |
| `checks` | Ordered list of check objects |
| `duplicate_vertex_groups` | Groups of 1-based vertex indices with rounded-equal positions (capped) |
| `degenerate_triangles` | Triangle index, OBJ line, vertices, area, reason (capped) |
| `non_manifold_edges` | Edge endpoints and adjacent face count (capped) |
| `boundary_loops` | Closed loop edge/vertex count and 1-based vertices (capped) |
| `open_boundary_chains` | Open chain edge/vertex count and vertices (capped) |
| `invalid_faces` | OBJ line, reason, referenced indices (capped) |
| `details_truncated` | Per-category booleans; `detail_limit` is 100 |
| `registration` | `null` or registration report evidence and status |
| `warnings` | Human-readable warnings, including parse issues |
| `limitations` | Static v0.1 limitations |
| `reproduction_command` | Exact command to rerun the checks |

### `metrics` fields

| Field | Description |
|---|---|
| `vertex_count` | Vertex rows parsed |
| `referenced_vertex_count` | Distinct vertices used by valid faces |
| `source_polygon_count`, `polygon_vertex_counts` | OBJ face elements before fan triangulation |
| `triangle_count` | Triangles after fan triangulation |
| `edge_count` | Unique undirected edges excluding self-edges |
| `boundary_edge_count` | Edges used by one face |
| `non_manifold_edge_count` | Edges used by more than two faces |
| `boundary_loop_count`, `open_boundary_chain_count`, `hole_count` | Boundary topology |
| `boundary_vertex_degree_gt_2_count` | Ambiguous boundary vertices |
| `closed` | Boundary and non-manifold counts are zero with at least one face |
| `duplicate_vertex_count`, `duplicate_vertex_group_count` | Extra and grouped duplicate vertices |
| `degenerate_triangle_count` | Degenerate triangles |
| `invalid_face_count` | Unparseable/out-of-range face elements |
| `non_finite_vertex_count` | Vertices with NaN/Inf coordinates |
| `triangle_area_total` | Sum of 3D triangle areas, source units squared |
| `signed_volume`, `absolute_volume` | Source units cubed; meaningful only for closed meshes |
| `orientation` | `OUTWARD`, `INWARD`, `ZERO` or `UNKNOWN` |
| `orientation_note` | Explanation of the orientation result |
| `bbox` | Finite vertex extents and X/Y/Z spans |
| `z_range` | `min`, `max`, `span` |

### `checks` entries

```json
{
  "id": "boundary",
  "status": "FAIL",
  "summary": "6 boundary edge(s) in 1 loop(s) and 1 open chain(s) (closed mesh expected).",
  "value": 6,
  "threshold": 0
}
```

Check ids: `vertices_present`, `duplicate_vertices`, `degenerate_triangles`,
`non_manifold_edges`, `boundary`, `orientation`, `face_indices`,
`coordinate_extent`, and optional `registration_rmse`.

## `quality_report.md`

Human-readable report with overall status, a check table, metrics, registration
evidence, issue lists (first 20 per category), warnings, limitations and the
reproduction command.

## `issues.csv`

Columns:

`check, status, code, message, location, value, threshold`

Status values in the CSV are `PASS`, `FAIL`, `UNKNOWN`, `INFO` (boundary
details allowed by `--allow-boundary`) and `WARNING` (general warnings). Codes:

- `CHECK` — one row per check summary
- `DUPLICATE_VERTEX_GROUP`
- `DEGENERATE_TRIANGLE`
- `NON_MANIFOLD_EDGE`
- `BOUNDARY_LOOP`
- `OPEN_BOUNDARY_CHAIN`
- `INVALID_FACE`
- `WARNING`

`location` contains OBJ lines, triangle numbers, vertex indices or edge
endpoints where applicable. `value` and `threshold` are written as plain
numbers or left empty.

## Exit codes

| Situation | Exit code |
|---|---|
| Overall `PASS` | 0 |
| Overall `UNKNOWN` | 0 (manual review required) |
| Overall `FAIL` | 1 |
| Overall `FAIL` with `--no-fail` | 0 |
| Invalid arguments, unreadable input or missing `--max-rmse` | non-zero via `SystemExit` |

## Guarantees

- The model is opened read-only and every run records its SHA-256.
- Detailed issues include locations where applicable, and every report includes
  a reproduction command.
- Truncated detail lists never change the metric counts.
- Unknown checks remain visible as `UNKNOWN`.
- v0.1 does not check GLB/glTF/PLY, multiple-model overlaps or CRS metadata.
