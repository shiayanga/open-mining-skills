# GemPy-Oriented Model Definition (v0.1)

`model_definition.json` is a validated, GemPy-oriented description of the input
data. It is **not** a GemPy project file and does not contain an interpolated
model. A separate setup step must create the GemPy model, run interpolation and
extract surfaces.

## Top-level structure

```json
{
  "schema_version": "0.1",
  "skill": "mine-geological-modeling",
  "generator": "open-mining-skills mine-geological-modeling v0.1",
  "target": {
    "software": "GemPy",
    "executed": false,
    "note": "..."
  },
  "coordinate_system": {
    "units": "UNKNOWN",
    "crs": "UNKNOWN",
    "vertical_axis": "Z_UP",
    "orientation_convention": {
      "dip": "degrees from horizontal; 0 = horizontal, 90 = vertical",
      "azimuth": "degrees clockwise from +Y (north); 0 = north, 90 = east",
      "polarity": 1
    }
  },
  "extent_order": ["x_min", "x_max", "y_min", "y_max", "z_min", "z_max"],
  "extent": [100, 500, 100, 700, 88, 121],
  "resolution_order": ["x", "y", "z"],
  "resolution": [50, 50, 50],
  "series": [...],
  "surfaces": [...],
  "interfaces": [...],
  "orientations": [...],
  "boreholes": {...},
  "notes": [...]
}
```

## Extent order

GemPy uses **`[x_min, x_max, y_min, y_max, z_min, z_max]`**, which is not the
same as the min-xyz/max-xyz order used by some bounding-box tools. `--extent`
uses the same GemPy order. The report always prints the field names and also
shows the min/max bounds separately to avoid ambiguity.

## Series and surfaces

- `series` is an ordered array. GemPy treats the first series as the youngest,
  so order matters.
- Each series record has `name`, `order` (1-based) and a `surfaces` array.
- `surfaces` is a flat array of records with `name`, `series`,
  `interface_count` and `orientation_count`.
- The default series order is first appearance in the interface file. The tool
  emits a `SERIES_ORDER_ASSUMED` warning because first appearance is not
  stratigraphic evidence. Use `--series-order` to state the order explicitly.
- Every surface belongs to exactly one series after validation.

## Interfaces and orientations

Each interface record contains:

```json
{"x": 100, "y": 100, "z": 120, "series": "overburden",
 "surface": "topsoil", "source_line": 2}
```

Each orientation record adds `dip`, `azimuth`, `polarity` and the same source
line. `source_line` is retained for traceability; a GemPy adapter can ignore it.

## Boreholes

When supplied, the definition contains:

```json
{
  "observation_count": 3,
  "borehole_count": 2,
  "observations": [...],
  "note": "Borehole observations are included as evidence only; ..."
}
```

These observations are not GemPy interface points in v0.1. A future adapter may
convert formation picks into interfaces or use them only as validation targets,
but that choice needs an explicit geological decision.

## Resolution

`resolution` is `[nx, ny, nz]` grid cells. The default `50,50,50` is a generic
starting point, not an accuracy guarantee. Model resolution must be justified
against data density, target feature size and compute budget.

## Future GemPy pipeline

1. Read the definition and confirm units, CRS and orientation convention.
2. Build a GemPy `GeoModel` with the same extent and resolution.
3. Add series in order, then surfaces with their interface and orientation
   points.
4. Optionally add faults, topography and surface constraints from other skills.
5. Run interpolation and check residuals and warnings.
6. Extract surfaces/meshes and validate against boreholes and at least one
   independent section.
7. Export meshes for `mine-3d-modeling`/`mine-3d-tiles` only after validation.

## Hard limits

- No implicit scalar field is computed by this skill.
- No geological surface mesh is produced.
- No fault network, unconformity, fold or anisotropy is modeled.
- No ore body, grade shell, tonnage or resource classification is produced.
- A clean validation result means "the inputs are internally consistent", not
  "the geology is correct".
