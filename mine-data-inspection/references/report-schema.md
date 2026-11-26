# Inspection Report Schema (v0.1)

All reports are UTF-8 JSON. Unknown values are reported as `UNKNOWN`; the inspector never guesses units or a CRS.

## Common fields

| Field | Type | Description |
|---|---|---|
| `file` | string | Source file name |
| `format` | string | `DXF`, `XYZ` or an unsupported format name |
| `status` | string | Present only for unsupported files (`UNSUPPORTED`) |
| `units` | string | Unit label; `UNKNOWN` when not provable |
| `coordinate_system` | string | Always `UNKNOWN` in v0.1 |
| `warnings` | array of strings | Human-readable data quality warnings |
| `source` | object | `path`, `name`, `size_bytes`, `sha256` |

## XYZ report

| Field | Type | Description |
|---|---|---|
| `format_detail.delimiter` | string | Detected delimiter or `whitespace` |
| `format_detail.encoding` | string | Encoding actually used |
| `format_detail.has_header` | boolean | Header detection result |
| `format_detail.header_columns` | array or null | Header tokens, if any |
| `format_detail.column_mapping` | object | 1-based `x`, `y`, `z` columns |
| `point_count` | integer | Valid coordinate rows |
| `skipped_rows` | integer | Rows that could not be parsed |
| `skipped_details` | array | Up to 50 `{line, reason}` entries |
| `extent` | object | `min_x`, `min_y`, `min_z`, `max_x`, `max_y`, `max_z`, `span_x`, `span_y`, `span_z` |
| `z_range` | object | `min`, `max`, `span` |
| `duplicate_coordinates` | integer | Extra rows with an identical coordinate tuple |
| `zero_z_count` | integer | Points with `abs(z) < 1e-9` |
| `coordinate_clue` | string | Coarse magnitude clue, never a CRS |

## DXF report

| Field | Type | Description |
|---|---|---|
| `format_version` | string | DXF version code, e.g. `AC1024` |
| `format_version_name` | string | Friendly version, e.g. `AutoCAD 2010` |
| `units_code` | integer | `$INSUNITS` value |
| `measurement` | integer or null | `$MEASUREMENT` value |
| `entity_total` | integer | Modelspace entity count |
| `entity_statistics` | object | Entity type to count |
| `layers` | array | `{name, color, entity_count}` |
| `blocks` | object | `defined`, `inserts`, `names` (first 50) |
| `text_entities` | integer | `TEXT` + `MTEXT` count |
| `has_3d_entities` | boolean | 3D types present or non-zero Z span |
| `extent` | object or null | Same shape as the XYZ extent |
| `coordinate_clue` | string | Coarse magnitude clue |

## Unsupported report

Contains `file`, `format`, `status: "UNSUPPORTED"`, `warnings`, and `source`. DWG requires conversion; point clouds are planned for v0.2.

## Example — XYZ

```json
{
  "file": "survey.xyz",
  "format": "XYZ",
  "format_detail": {
    "delimiter": ",",
    "encoding": "utf-8-sig",
    "has_header": true,
    "header_columns": ["X", "Y", "Z"],
    "column_mapping": {"x": 1, "y": 2, "z": 3}
  },
  "point_count": 7,
  "skipped_rows": 1,
  "extent": {
    "min_x": 500000.0, "min_y": 4000000.0, "min_z": 120.5,
    "max_x": 500050.0, "max_y": 4000020.0, "max_z": 123.0,
    "span_x": 50.0, "span_y": 20.0, "span_z": 2.5
  },
  "z_range": {"min": 120.5, "max": 123.0, "span": 2.5},
  "duplicate_coordinates": 1,
  "zero_z_count": 0,
  "units": "UNKNOWN",
  "coordinate_system": "UNKNOWN",
  "coordinate_clue": "PROJECTED_METER_CANDIDATE",
  "warnings": ["1 row(s) skipped; see skipped_details."],
  "source": {"path": "/data/survey.xyz", "name": "survey.xyz", "size_bytes": 231, "sha256": "..."}
}
```
