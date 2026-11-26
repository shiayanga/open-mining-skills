# Interface and Borehole Schema (v0.1)

## Interfaces CSV

Required logical fields:

| Field | Type | Meaning |
|---|---|---|
| `x` | number | Easting or local X |
| `y` | number | Northing or local Y |
| `z` | number | Elevation or local Z |
| `series` | string | Stratigraphic series / group name |
| `surface` | string | Geological surface / horizon name |
| `dip` | number, optional | Degrees from horizontal, 0–90 |
| `azimuth` | number, optional | Degrees clockwise from +Y (north), 0–360 |

The writer accepts common header aliases (`easting`, `northing`, `elevation`,
`group`, `horizon`, `dip_deg`, `dip_direction`, and several Chinese variants).
Column names are matched case-insensitively after trimming.

### Header and delimiter detection

- The delimiter is detected from `,`, `;` or tab; whitespace is used when none
  is found.
- A first row is treated as a header when it contains a known field alias.
- With a header, missing required columns are a fatal error.
- Without a header, the positional order is
  `x,y,z,series,surface,dip,azimuth`; `dip` and `azimuth` are optional.
- Quoted fields containing the delimiter are not supported in v0.1.

### Orientation rules

- `dip` and `azimuth` are independent optional fields.
- An orientation is emitted only when both are present and valid.
- If only one of the pair is present, the row still contributes an interface
  point and an `INCOMPLETE_ORIENTATION` warning is recorded.
- `dip` must satisfy `0 <= dip <= 90`; `azimuth` must satisfy
  `0 <= azimuth <= 360`.
- Every orientation is written with `polarity = 1` and shares the X, Y and Z
  position of its interface point.
- Azimuth is a dip direction (not a strike) measured clockwise from +Y
  (north); dip is measured from horizontal.
- An azimuth of exactly 360 is accepted and retained; GemPy may normalize it.

## Boreholes CSV

v0.1 accepts a flat observation table, not a full collar + interval log:

| Field | Type | Meaning |
|---|---|---|
| `borehole_id` | string | Hole identifier (may repeat across observations) |
| `x` | number | Hole or sample X |
| `y` | number | Hole or sample Y |
| `z` | number | Sample or pick elevation |
| `series` | string | Series name |
| `surface` | string | Unit or horizon name |

Aliases include `borehole`, `hole_id`, `hole`, `id` and Chinese variants.
Without a header the positional order is
`borehole_id,x,y,z,series,surface`.

Borehole observations are evidence only in v0.1. They are validated and
recorded in the definition and report, but are not converted into GemPy
interface points. Using them for interpolation or validation requires a later,
explicit step.

## Cross-row validation

- **Duplicates**: two interface points whose X, Y and Z differ by at most
  `--duplicate-tolerance` (default `1e-6`) are reported as a duplicate pair
  with both line numbers. Detection is pairwise, so very large files should be
  split or deduplicated first.
- **Series/surface consistency**: a surface name may belong to exactly one
  series. The same surface under two series is a `SERIES_SURFACE_CONFLICT`.
- **Series order**: each series must have at least one surface. The default
  order is first appearance; `--series-order` overrides it and must list every
  series exactly once.
- **Extent**: all interface points must fall inside an explicit `--extent`.
  The default extent equals the data bounds, with zero-span axes expanded by
  ±1.0 and a warning.
- **Boreholes**: a borehole unit unknown to the interfaces produces
  `BOREHOLE_UNKNOWN_UNIT`; a unit assigned to a different series produces
  `BOREHOLE_SERIES_CONFLICT`.

## Limits

- One surface name cannot represent two different stratigraphic units; rename
  it or use separate series.
- The schema has no fault, cross-section, grade or assay fields.
- No unit conversion is performed; mixing metres and feet is not detected.
- No CRS is assumed or transformed.
- Quoted CSV fields are not parsed; series/surface names containing the
  delimiter are not supported.
- Header detection is heuristic: a headerless first row that contains a token
  such as `x`, `series` or `surface` can be mistaken for a header.
