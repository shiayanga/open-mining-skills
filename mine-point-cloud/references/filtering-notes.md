# Point Cloud Filtering Notes (v0.1)

## Input

`scripts/pointcloud.py filter` reads XYZ, CSV, TSV or whitespace-delimited
points. Delimiter and header are detected automatically; header aliases include
`X`/`Easting`/`东坐标`, `Y`/`Northing`/`北坐标`, `Z`/`Elevation`/`高程`.
Malformed rows are skipped and reported. The reader never assumes units or a
CRS and loads the whole file into memory.

## Processing stages

The stages run in this fixed order:

1. **Z range filter** — keep `z_min <= z <= z_max` when either bound is supplied.
2. **Voxel downsample** — divide space into cubes of `--voxel-size`; keep the
   first point per non-empty voxel in file order.
3. **Ground candidates** — divide XY into cells of `--ground-cell-size`; keep
   the lowest-Z point per cell. Ties are resolved by source file order.

All stages report point counts and Z ranges before and after. The filtered CSV
contains the result of stages 1-2; ground candidates are selected from that
filtered set.

## Determinism

- Voxel keys are `floor(coordinate / voxel_size)`; negative coordinates behave
  correctly.
- Ground cells use `floor(x / cell_size)`, `floor(y / cell_size)`.
- Within a ground cell the selection key is `(z, source_index)`, so the result
  does not depend on NumPy sort stability.
- Output CSVs retain 1-based original row indices.

## What "ground candidate" means

It is only the lowest point in each XY cell. It is **not** a ground
classification:

- low vegetation, shadows, vehicles, cables, water returns or noise can become
  the lowest point
- a cell containing a steep bench face produces one candidate, not a surface
- increasing the cell size reduces noise sensitivity but removes detail
- decreasing it can make every point its own candidate

The report marks `ground_candidates.is_classification = false` and warns when
every point is in its own cell. Do not feed candidates into safety or volume
analysis as if they were classified ground.

## Parameter guidance

| Parameter | Guidance |
|---|---|
| `--z-min` / `--z-max` | Express in source Z units. Use to remove obvious outliers; document the reason. |
| `--voxel-size` | Relative to point spacing. For a 0.5 m UAV cloud, 0.25-1.0 m is a common starting range. |
| `--ground-cell-size` | Larger than noise spacing and smaller than terrain features you need. Start near the desired ground output resolution. |

The defaults (`--ground-cell-size 10`) are a starting point only. Because units
are unknown, always confirm that the number matches the source units.

## Output files

- `filtered_points.csv`: `index, x, y, z` (index is the 1-based source row)
- `ground_candidates.csv`: `index, cell_x, cell_y, x, y, z`
- `pointcloud_filter_report.json`: counts, Z ranges, parameters, warnings.
- `pointcloud_filter_report.md`: human-readable summary.

The inspector writes only the JSON/Markdown paths you request; if neither is
given it prints the JSON header report to stdout.

## Not implemented in v0.1

- LAZ decompression
- outlier/noise statistics (statistical outlier removal, radius filter)
- ground classification (PDAL SMRF, CSF, Open3D)
- point cloud registration and trajectory handling
- density maps, coverage rasters, surface reconstruction, GLB or 3D Tiles
- CRS parsing from VLRs

## Planned PDAL/Open3D pipeline (v0.2)

```text
readers.las -> filters.outlier -> filters.smrf -> filters.voxelcenternearestneighbor
            -> writers.las (cleaned/classified) -> surface reconstruction
```

Each run should record the PDAL/Open3D version, pipeline JSON, CRS and every
parameter. The current lowest-Z candidate remains useful as a cheap baseline
for regression tests against PDAL classifications.
