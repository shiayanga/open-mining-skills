# DXF Inspection Notes

## What the inspector reads

| Item | Source |
|---|---|
| DXF version | `$ACADVER` / `doc.dxfversion` |
| Units | `$INSUNITS` and `$MEASUREMENT` |
| Layers | layer table plus per-layer modelspace entity counts |
| Entities | entity type statistics from modelspace |
| Extents | `ezdxf.bbox.extents()` over modelspace |
| 3D presence | 3D entity types and a non-zero Z span |
| Blocks | block definitions and `INSERT` count |
| Text | `TEXT` / `MTEXT` counts |
| Proxies | `ACAD_PROXY_ENTITY` / `ACAD_PROXY_OBJECT` counts |

## Unit codes (`$INSUNITS`)

| Code | Unit |
|---:|---|
| 0 | Unitless |
| 1 | Inches |
| 2 | Feet |
| 3 | Miles |
| 4 | Millimeters |
| 5 | Centimeters |
| 6 | Meters |
| 7 | Kilometers |
| 10 | Yards |
| 14 | Decimeters |

`$MEASUREMENT` is reported alongside: `0` = imperial, `1` = metric.

## Important limitations

- DXF has no standard CRS field. The inspector reports `coordinate_system: UNKNOWN` and only a coordinate magnitude clue.
- `ezdxf` is a DXF library, not a native DWG parser. DWG files must be converted first (for example with ODA File Converter); verify its license before deployment.
- XREFs and proxy entities may not expose computable geometry.
- Bounding boxes depend on entity support in `ezdxf.bbox`; unsupported entities may be skipped.
- v0.1 reads the whole drawing into memory. For very large drawings, convert or split the file first.

## What is deliberately not done

- No unit conversion and no CRS assignment.
- No geometry repair or layer renaming.
- No assumption that Z values are elevations in metres.

## Command

```bash
python3 scripts/inspect_dxf.py site.dxf --output site.json --markdown site.md
```
