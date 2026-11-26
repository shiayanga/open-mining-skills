# Input and Output Schema (v0.1)

## Control point file

CSV, TSV, semicolon or whitespace-separated. A header row is detected automatically.

Preferred header:

```csv
sx,sy,sz,tx,ty,tz
0.000000000,0.000000000,0.000000000,1200.500000000,-800.250000000,35.750000000
```

Recognised aliases (case-insensitive):

| Role | Aliases |
|---|---|
| Source X | `sx`, `source_x`, `from_x`, `src_x`, `x1`, `x_src`, `源x` |
| Source Y | `sy`, `source_y`, `from_y`, `src_y`, `y1`, `y_src`, `源y` |
| Source Z | `sz`, `source_z`, `from_z`, `src_z`, `z1`, `z_src`, `源z` |
| Target X | `tx`, `target_x`, `to_x`, `dst_x`, `x2`, `x_tgt`, `目标x` |
| Target Y | `ty`, `target_y`, `to_y`, `dst_y`, `y2`, `y_tgt`, `目标y` |
| Target Z | `tz`, `target_z`, `to_z`, `dst_z`, `z2`, `z_tgt`, `目标z` |

If aliases are not found, columns default to `1,2,3` (source) and `4,5,6` (target). Override with `--src-cols` and `--dst-cols` (1-based).

Rows with missing or non-numeric values are skipped and reported.

## Points file

`XYZ`, `CSV`, `TSV` or whitespace-separated. Header aliases: `X/Easting/东坐标`, `Y/Northing/北坐标`, `Z/Elevation/高程`. Override with `--x-col`, `--y-col`, `--z-col` (1-based).

## Command

```bash
python3 scripts/register.py control_points.csv \
  --points survey.xyz \
  --out-dir registration_output
```

| Option | Default | Meaning |
|---|---|---|
| `--mode` | `3d` | `3d` seven-parameter or `2d` four-parameter similarity |
| `--src-cols` / `--dst-cols` | auto | 1-based control point columns |
| `--x-col` / `--y-col` / `--z-col` | 1,2,3 | Points file columns |
| `--reject-above` | off | Absolute residual threshold for iterative rejection |
| `--source-crs` / `--target-crs` | `UNKNOWN` | Labels only; no CRS transformation is performed |
| `--delimiter` | auto | `,`, `;` or `tab` |
| `--out-dir` | `registration_output` | Output directory |

## Outputs

### `transformation.json`

```json
{
  "method": "3d_similarity_umeyama",
  "convention": "dst = scale * R * src + translation",
  "scale": 1.02,
  "rotation_matrix": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
  "translation": [1200.5, -800.25, 35.75],
  "euler_angles_deg_zyx": {"rx": 5.0, "ry": 10.0, "rz": 30.0},
  "rmse": 0.0,
  "max_residual": 0.0,
  "used_control_points": 8,
  "control_point_count": 8,
  "source_crs": "UNKNOWN",
  "target_crs": "UNKNOWN",
  "source_control_points": {}
}
```

2D mode replaces `euler_angles_deg_zyx` with `rotation_deg_2d`.

### `registration_report.json`

Contains `parameters`, `diagnostics`, `options`, source manifests, skipped input rows and points metadata. Diagnostics include per-point residuals, per-axis RMSE, rejected points and warnings.

### `residuals.csv`

UTF-8 with BOM. Columns:

`index, source_x, source_y, source_z, target_x, target_y, target_z, transformed_x, transformed_y, transformed_z, dx, dy, dz, residual, used, rejected`

`dx/dy/dz` are **residual components** (transformed minus target).

### `transformed_points.csv`

Written only when `--points` is provided. Columns:

`source_x, source_y, source_z, x, y, z, delta_x, delta_y, delta_z`

`delta_*` is the coordinate shift (transformed minus source), not a residual.

### `registration_report.md`

Human-readable summary with parameters, control point residual table and warnings.

## Guarantees

- Source files are read-only.
- Units and CRS are never inferred; CRS labels are metadata only.
- Every skipped control/point row and every rejected control point is reported.
- Parameters are exported in a form that can be applied with `dst = scale * R * src + translation`.
