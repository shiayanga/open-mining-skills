# DXF Entity Mapping

## Supported entities

| DXF entity | GeoJSON geometry | Key properties | Notes |
|---|---|---|---|
| `POINT` | `Point` | `entity_point` | X, Y, Z preserved |
| `LINE` | `LineString` | start/end | X, Y, Z preserved |
| `LWPOLYLINE` | `LineString` or `Polygon` | `closed`, `source_vertex_count` | Z comes from the polyline elevation |
| `POLYLINE` | `LineString` or `Polygon` | `closed`, `is_3d`, `source_vertex_count` | 2D and 3D polylines |
| `SPLINE` | `LineString` | `degree`, `closed` | Flattened to a polyline |
| `ARC` | `LineString` | `center`, `radius`, angles | Flattened to a polyline |
| `CIRCLE` | `Polygon` | `center`, `radius` | Flattened to a closed ring |
| `ELLIPSE` | `Polygon` | `center`, `major_axis`, `ratio` | Flattened to a closed ring |
| `TEXT` | `Point` | `text`, `height`, `rotation` | Insertion point |
| `MTEXT` | `Point` | `text`, `height`, `rotation` | Uses plain text |
| `ATTRIB` | `Point` | `text`, `height` | Block attribute text |
| `INSERT` | expanded | `block_name` on children | Block references are expanded recursively |

Closed polylines, circles and ellipses with at least three distinct points become `Polygon`; otherwise they remain `LineString`.

## Block expansion

- `INSERT` entities are replaced by their block geometry through `ezdxf` virtual entities, so coordinates are transformed into modelspace.
- Each expanded feature records `block_name` (the immediate block) and keeps its own entity handle.
- Nested blocks are expanded recursively up to `--max-block-depth` (default 5).
- Empty or unresolvable blocks are listed in `skipped_details`.

## Flattening

- Curves are flattened with `--tolerance` (default 0.5 drawing units).
- Smaller tolerance means more vertices and a larger file.
- Original vertex counts are reported where available (`source_vertex_count`) and the exported count is `output_vertex_count`.

## Z and coordinates

- Z values are preserved; no projection or unit conversion is applied.
- Coordinates are rounded to `--precision` (default 6 decimals) only at export.
- The output is **not** in WGS84. The GeoJSON `mine_metadata` records `units` and `coordinate_system: UNKNOWN`.

## Not supported in v0.1

- `HATCH`, `DIMENSION`, `LEADER`, `MLINE`, `3DSOLID`, `REGION`, `MESH`, proxy entities.
- Native DWG parsing; convert to DXF first (see `mine-data-inspection/references/dwg-notes.md`).
- True arcs in GeoJSON; all curves are flattened.

Every skipped entity is recorded in `parse_report.json` with type, layer, handle and reason.
