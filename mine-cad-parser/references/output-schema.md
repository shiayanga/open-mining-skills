# CAD Parser Output Schema (v0.1)

The parser writes five files into `--out-dir`.

## `geometry.geojson`

A `FeatureCollection` with a `mine_metadata` foreign member:

```json
{
  "type": "FeatureCollection",
  "mine_metadata": {
    "generated_by": "mine-cad-parser v0.1",
    "source": {"path": "...", "name": "...", "size_bytes": 0, "sha256": "..."},
    "units": "Meters",
    "coordinate_system": "UNKNOWN",
    "coordinate_clue": "PROJECTED_METER_CANDIDATE"
  },
  "features": []
}
```

Feature properties:

| Field | Type | Description |
|---|---|---|
| `feature_id` | string | `F000001` style identifier |
| `entity_type` | string | Source DXF entity type |
| `layer` | string | Original layer name |
| `handle` | string | Original DXF handle |
| `block_name` | string or null | Immediate block for expanded features |
| `geometry_source` | string | `entity_point`, `entity_vertices`, `flattened` or `insertion_point` |
| `closed` | boolean | Present for curves |
| `output_vertex_count` | integer | Exported vertices, excluding the closing duplicate |
| `source_vertex_count` | integer | Original polyline vertex count |
| `center` / `radius` / angles | mixed | Arc, circle and ellipse metadata |
| `major_axis` / `ratio` | mixed | Ellipse metadata |
| `degree` | integer | Spline degree |
| `text` / `height` / `rotation` | mixed | Text metadata |

Coordinates are `[x, y, z]` in drawing units. They are **not** WGS84.

## `geometry_index.csv`

UTF-8 with BOM. One row per feature:

`feature_id, entity_type, layer, handle, block_name, geometry_type, vertex_count, closed, min_z, max_z, text`

## `layers.json`

```json
{
  "generated_by": "mine-cad-parser v0.1",
  "source": {},
  "layers": [
    {
      "name": "SURVEY",
      "color": 7,
      "linetype": "CONTINUOUS",
      "is_on": true,
      "is_frozen": false,
      "is_locked": false,
      "source_entity_count": 4,
      "feature_count": 4
    }
  ]
}
```

## `parse_report.json`

| Field | Description |
|---|---|
| `file`, `format`, `format_version`, `format_version_name` | Source metadata |
| `units`, `units_code`, `measurement` | Drawing unit metadata |
| `coordinate_system`, `coordinate_clue` | Always `UNKNOWN` CRS; magnitude clue |
| `source_entity_statistics`, `source_entity_total` | Modelspace entities before block expansion |
| `feature_entity_statistics`, `feature_count` | Exported features after expansion |
| `skipped_count`, `skipped_details` | Up to 100 skipped entities with reasons |
| `unsupported_types` | Counts of unsupported entity types |
| `extent`, `z_range` | Exported geometry extents |
| `options` | Text, tolerance, block depth, precision |
| `warnings` | Data quality and conversion warnings |
| `source` | Path, size and SHA-256 |

## `parse_report.md`

Human-readable version of the report with entity, layer and skipped-entity tables.

## Guarantees

- Source drawing is read-only and never modified.
- Layer names, handles and Z values are preserved.
- Every skipped entity is recorded with a reason.
- Units and CRS are never inferred.
