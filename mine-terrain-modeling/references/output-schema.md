# Terrain Output Schema (v0.1)

All outputs are written to `--out-dir` (default `terrain_output`). Source files
are opened read-only. Units and CRS are always `UNKNOWN` in v0.1.

## `terrain.obj`

Wavefront OBJ containing the TIN:

```
# mine-terrain-modeling v0.1 - unconstrained Delaunay TIN
# coordinates are original survey values; units and CRS UNKNOWN
o terrain_tin
v <x> <y> <z>
...
f <i> <j> <k>
...
```

- one `v` per unique XY survey point, using round-trip Python float `repr`
- one triangular `f` per Delaunay simplex, 1-based indices
- vertices are counter-clockwise in XY (upward-facing normals)
- no normals, texture coordinates, CRS or unit metadata

## `terrain_dem.asc`

ESRI ASCII grid with square cells, `NODATA_value -9999.0`, and rows ordered
north to south. See `terrain-methods.md` for the corner convention. Values are
written with 6 decimal places.

## `terrain_report.json`

Top-level fields:

| Field | Description |
|---|---|
| `file` | Source point file name |
| `source` | `path`, `name`, `size_bytes`, `sha256` |
| `format` | `XYZ` |
| `units`, `crs` | Always `UNKNOWN` |
| `input` | Parsing and cleaning evidence: point count, skipped rows and details, delimiter, encoding, header/columns, extent, exact duplicates removed, XY conflicts removed and examples |
| `tin` | TIN statistics, dropped degenerate count, used extent, output name |
| `dem` | DEM method, cell size, shape, node/valid/NoData counts, coverage fraction, grid and uncovered extents, Z statistics, NoData value, output name |
| `check_points` | `null` when not requested; otherwise counts, RMSE/MAE/max errors, signed error statistics and per-point rows |
| `check_point_input` | Check file name and parsing metadata (`null` when absent) |
| `options` | Cell size, method, column mapping, check point path |
| `warnings` | Human-readable warnings |
| `limitations` | Static v0.1 limitations |

### TIN fields

| Field | Description |
|---|---|
| `vertex_count` | Unique points used |
| `triangle_count` | Triangles retained |
| `total_area_xy` | Sum of planar triangle areas |
| `total_area_3d` | Sum of true 3D triangle areas |
| `surface_to_planar_area_ratio` | `total_area_3d / total_area_xy` |
| `slope_deg_min/max/mean/median/std/p95` | Triangle slope distribution (degrees) |
| `slope_deg_area_weighted_mean` | Planar-area-weighted mean slope |
| `triangle_area_xy_min/max` | Planar triangle area range |
| `z_min`, `z_max`, `z_span` | Elevation range of the TIN vertices |
| `degenerate_triangles_dropped` | Zero/non-finite area triangles removed |
| `used_extent` | Extent of the cleaned points |

### DEM fields

| Field | Description |
|---|---|
| `method` | `linear` or `nearest` |
| `cell_size` | Requested cell size, source units |
| `shape` | `[rows, columns]` |
| `node_count` | `rows * columns` |
| `valid_cells`, `nodata_cells`, `coverage_fraction` | Finite vs NoData nodes |
| `grid_extent` | Node extent actually produced |
| `uncovered_extent` | Remainder at max X/Y smaller than one cell |
| `z_min`, `z_max`, `z_mean` | Statistics of finite DEM nodes |
| `nodata_value` | `-9999.0` |
| `output` | `terrain_dem.asc` |

### Check point fields

| Field | Description |
|---|---|
| `check_point_count` | Valid rows in the check file |
| `checked_count` | Points inside the TIN convex hull |
| `outside_hull_count` | Points excluded |
| `rmse`, `mae`, `max_abs_error` | Error metrics |
| `max_error`, `min_error`, `mean_error`, `std_error` | Signed error statistics |
| `points` | Per-point `x`, `y`, `z_check`, `z_tin`, `error` |
| `warnings` | Exclusion and low-sample-count warnings |

## `terrain_report.md`

Human-readable rendering of the same report: summary, TIN, DEM, check point
table (first 100 rows), warnings and limitations.

## Guarantees and non-guarantees

- Original X/Y/Z values are preserved in the TIN and OBJ.
- Source files are never modified.
- Units and CRS are never inferred.
- No breakline, bench, boundary or outlier handling is applied.
- The DEM is not extrapolated beyond the convex hull with `linear`.
- The OBJ is geometry only; use a separate conversion step for GLB/3D Tiles.
