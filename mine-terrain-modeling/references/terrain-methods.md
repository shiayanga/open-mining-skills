# Terrain Methods (v0.1)

## Scope

v0.1 turns scattered survey points (XYZ/CSV) into:

- an unconstrained Delaunay TIN (`terrain.obj`)
- a square-cell DEM sampled from the points (`terrain_dem.asc`)
- optional elevation statistics against independent check points

It does **not** implement constrained triangulation, breaklines, contour
extraction or bench preservation. Those are required for production open-pit
terrain and are planned for a later version.

## Input reading

`scripts/terrain.py` detects the delimiter (`,` `;` tab or whitespace) and
whether the first row is a header. Recognised header aliases include
`X`/`Easting`/`东坐标`, `Y`/`Northing`/`北坐标` and `Z`/`Elevation`/`高程`.
Rows with missing, non-numeric or non-finite coordinates are skipped and
reported. Comments starting with `#` are ignored.

The reader never assigns units or a CRS. Coordinate magnitude is not proof of a
particular system.

## Point cleaning

- **Exact duplicate 3D points** are removed (first occurrence kept) and counted.
- **XY conflicts** — two points with the same XY but different Z — cannot both
  participate in a single-valued terrain surface. v0.1 keeps the first point in
  file order and reports the conflict count plus up to 10 examples.
- No spike, outlier or near-duplicate removal is performed.

A TIN requires at least 3 unique XY points and a non-collinear configuration.
Both violations raise `SystemExit` with a clear message.

## Delaunay TIN

`scipy.spatial.Delaunay` triangulates the XY coordinates. Qhull may return
either winding direction; the exporter swaps vertices where necessary so that
all triangles are counter-clockwise in XY (upward normals). This gives a
predictable OBJ winding.

For triangle vertices `v0, v1, v2`:

- cross product: `c = (v1 - v0) × (v2 - v0)`
- planar area: `0.5 * |c_z|`
- 3D surface area: `0.5 * |c|`
- slope angle: `atan2(sqrt(c_x² + c_y²), |c_z|)`, reported in degrees
- triangle count = number of Delaunay simplices retained

Triangles with zero/non-finite area are dropped and reported. Statistics
include min/max/mean/median/std/p95 slope, area-weighted mean slope, total
planar area, total 3D area, and Z range.

## DEM grid

The grid is anchored at the minimum X and Y of the data:

```
nx = floor(span_x / cell_size) + 1
ny = floor(span_y / cell_size) + 1
xs = min_x + i * cell_size
ys = min_y + j * cell_size
```

Consequences:

- cells are exactly `cell_size` square, in source units
- the grid never extends beyond the data maximum; a remainder smaller than one
  cell at the maximum X/Y edge is left uncovered (reported as
  `dem.uncovered_extent`)
- a span smaller than one cell produces a 1-row or 1-column grid, which is
  reported as a warning
- more than 25,000,000 nodes raises an error; increase `--cell-size`

`scipy.interpolate.griddata` samples the DEM:

| Method | Behaviour |
|---|---|
| `linear` | Delaunay-linear interpolation; nodes outside the TIN convex hull (and possibly some nodes exactly on the hull due to floating point) are NoData |
| `nearest` | nearest point value; fills the whole grid extent |

NoData is written as `-9999.0`. The report includes node count, valid cells,
NoData cells and coverage fraction. v0.1 does not extrapolate.

## ESRI ASCII export

```
ncols <nx>
nrows <ny>
xllcorner <min_x - cell_size/2>
yllcorner <min_y - cell_size/2>
cellsize <cell_size>
NODATA_value -9999.0
<row max Y> ... <row min Y>
```

Following the ESRI convention, `xllcorner`/`yllcorner` refer to the lower-left
corner of the lower-left cell, so the sample nodes (cell centres) are at
`min_x + i*cell_size` and `min_y + j*cell_size`. Rows are written north to
south.

## Check points

An independent XYZ point file is interpolated with
`scipy.interpolate.LinearNDInterpolator` on the same survey points used for the
TIN. For every evaluated point the report records `z_check`, `z_tin` and
`error = z_tin - z_check`. Summary fields:

- RMSE
- mean absolute error (MAE)
- maximum absolute error
- signed min/max/mean error and error standard deviation
- checked count and outside-hull count

Check points outside the TIN convex hull are **excluded**, not extrapolated.
If fewer than 4 points are evaluated, a warning says the RMSE is not a reliable
accuracy estimate.

## Limitations that affect fitness for use

A plain Delaunay TIN is not a substitute for a breakline-constrained terrain
model in an active mine:

- crests, toes, bench faces and ramps can be smoothed or bridged
- pit limits and property boundaries are not clipped
- contour vertices are not checked for connectivity or elevation consistency
- duplicate or spike survey points are only partially cleaned
- no vertical datum or geoid correction is applied

Do not use the output to certify slope geometry, volumes or safety-critical
bench positions. Use it for visualization, initial surfaces and as a baseline
for a later constrained TIN.

## Planned v0.2 work

- breakline/boundary-constrained triangulation
- contour extraction and elevation validation from `mine-cad-parser` output
- bench/crest/toe preservation controls
- GeoTIFF DEM export (GDAL) and GLB mesh export
- robust spike/outlier detection and uncertainty reporting

## Validation guidance

1. Check `tin.triangle_count` against the expected cardinality of a gridded
   sample (for a complete `m x n` grid it is `2*(m-1)*(n-1)`).
2. Verify `tin.total_area_xy` equals the convex hull area for a full grid.
3. Inspect `dem.coverage_fraction`; a low value with `linear` means a large part
   of the extent lies outside the survey coverage.
4. Use independent check points, not the modeling points, for RMSE.
5. Run `mine-model-quality-check` on `terrain.obj` with `--allow-boundary` to
   verify topology; orientation will remain UNKNOWN for an open surface.
