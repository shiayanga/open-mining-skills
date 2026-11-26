# Validation Rules (v0.1)

## Status and exit codes

| Status | Exit code | Meaning |
|---|---|---|
| `ok` | `0` | No validation errors; `model_definition.json` written |
| `invalid` | `1` | At least one error; reports written, no definition |

Warnings never change the exit code. Structural problems (missing file, missing
required header columns, bad CLI option) raise `SystemExit` with a message
before any report is written.

## Error codes

| Code | Trigger |
|---|---|
| `MISSING_VALUE` | A required coordinate field is empty |
| `NON_NUMERIC_COORDINATE` | x/y/z cannot be parsed or is not finite |
| `NON_NUMERIC_DIP` | Dip is present but non-numeric or not finite |
| `NON_NUMERIC_AZIMUTH` | Azimuth is present but non-numeric or not finite |
| `DIP_OUT_OF_RANGE` | Dip is outside 0–90 degrees |
| `AZIMUTH_OUT_OF_RANGE` | Azimuth is outside 0–360 degrees |
| `MISSING_SERIES` | Series name is empty |
| `MISSING_SURFACE` | Surface name is empty |
| `MISSING_BOREHOLE_ID` | Borehole id is empty |
| `NO_VALID_INTERFACES` | No interface row survived validation |
| `DUPLICATE_INTERFACE` | Two points are within `--duplicate-tolerance` |
| `SERIES_SURFACE_CONFLICT` | One surface name appears under multiple series |
| `SERIES_ORDER_INVALID` | `--series-order` omits or invents a series |
| `EXTENT_DOES_NOT_CONTAIN_DATA` | An interface point lies outside `--extent` |
| `BOREHOLE_SERIES_CONFLICT` | A borehole assigns a known surface to another series |

## Warning codes

| Code | Trigger |
|---|---|
| `INCOMPLETE_ORIENTATION` | Only one of dip/azimuth is present |
| `SERIES_ORDER_ASSUMED` | No `--series-order`; first-appearance order used |
| `EXTENT_EQUALS_DATA_BOUNDS` | Default extent has no margin around the data |
| `EXTENT_AXIS_EXPANDED` | A zero-span extent axis was expanded by ±1.0 |
| `SPARSE_INTERFACES` | Fewer than 3 interface points in total |
| `SPARSE_SURFACE` | A surface has fewer than 3 interface points |
| `NO_ORIENTATIONS` | No dip/azimuth orientations were produced |
| `SINGLE_SURFACE` | Only one geological surface is defined |
| `BOREHOLE_UNKNOWN_UNIT` | Borehole unit is not defined by any interface |
| `BOREHOLE_OUTSIDE_EXTENT` | Borehole observation lies outside the model extent |

## Extent rules

- Default: extent equals the interface data bounds. Any axis with zero span is
  expanded by ±1.0 and reported.
- Explicit: `--extent` uses GemPy order `xmin,xmax,ymin,ymax,zmin,zmax` and
  must have positive span in all three axes.
- Every interface point must be inside the explicit extent within the
  duplicate tolerance; otherwise validation fails.
- Borehole observations outside the extent are warnings, because they are not
  interpolated in v0.1.

## Duplicate rules

Two interface points are duplicates when:

```text
max(|dx|, |dy|, |dz|) <= duplicate_tolerance
```

The default tolerance is `1e-6` in source coordinate units. The check is
pairwise and reports both source lines plus the shared coordinates.

## What is not validated

- CRS, units or vertical datum correctness
- Geological plausibility, stratigraphic age or fault consistency
- Dip/azimuth reliability or structural measurements from oriented core
- Borehole collar/depth consistency (the schema is a flat observation table)
- Interpolation residuals (GemPy has not run)
- Ore grade, continuity, tonnage or resource classification

A passing report means the dataset is internally consistent with this schema,
not that the geological model is valid.
