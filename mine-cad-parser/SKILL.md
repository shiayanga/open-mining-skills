---
name: mine-cad-parser
description: Parse DWG/DXF mine drawings into structured geometry and metadata including layers, 3D polylines, blocks, text and annotations. Use when extracting CAD geometry for terrain reconstruction, roads, pits, facilities or coordinate registration.
---

# Mine CAD Parser

> Status: v0.1 — DXF parsing to GeoJSON, CSV and reports is implemented with tests. DWG requires conversion to DXF; HATCH, DIMENSION, 3DSOLID and proxy entities are not exported.

## Role

You are a mine CAD parsing specialist. Your job is to convert mine drawings into structured, traceable geometry without losing Z values, layer semantics or provenance.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| DXF drawings | Parsed via `ezdxf`; modelspace entities and block references |
| Supported entities | `POINT`, `LINE`, `LWPOLYLINE`, `POLYLINE` (2D/3D), `SPLINE`, `ARC`, `CIRCLE`, `ELLIPSE`, `TEXT`, `MTEXT`, `ATTRIB`, `INSERT` |
| DWG | Not parsed directly; convert to DXF first (see `references/dwg-notes.md`) |
| Unsupported | `HATCH`, `DIMENSION`, `LEADER`, `MLINE`, `3DSOLID`, `REGION`, `MESH`, proxy entities — recorded in `skipped_details` |

## Quick Start

Run the following commands from this skill directory.

```bash
python3 -m pip install -r requirements.txt
```

```bash
python3 scripts/parse_dxf.py tests/fixtures/cad_sample.dxf --out-dir cad_output
```

Options:

| Option | Default | Meaning |
|---|---|---|
| `--out-dir` | `cad_parse_output` | Output directory |
| `--no-text` | off | Exclude TEXT / MTEXT / ATTRIB |
| `--tolerance` | `0.5` | Curve flattening tolerance in drawing units |
| `--max-block-depth` | `5` | Nested block expansion depth |
| `--precision` | `6` | Exported coordinate decimals |

## Workflow

1. Open the drawing read-only and verify format and version.
2. Enumerate layers, blocks and entity types.
3. Extract supported modelspace entities, expanding `INSERT` blocks into world coordinates.
4. Preserve X, Y and Z coordinates; never drop Z silently.
5. Flatten curves to polylines with a documented tolerance.
6. Detect closed polylines and elevation attributes; export them as polygons when valid.
7. Normalize geometry to GeoJSON/CSV with layer names and source entity handles.
8. Report unsupported entity types and every skipped entity with a reason.

## Engineering Rules

- Treat `ezdxf` as a DXF parser, not a native DWG parser; DWG requires a dedicated converter such as ODA File Converter, whose licensing must be verified before deployment.
- Never edit source drawings.
- Keep original layer names and entity handles.
- Do not assume drawing units or coordinate systems.
- Record every skipped or unsupported entity.

## Quality Requirements

- Entity counts reconcile with the inspection report; source and exported statistics are both reported.
- Vertex counts and Z ranges are consistent after export.
- Block-expanded features retain their `block_name` and transformed coordinates.
- Unsupported entities are listed explicitly.
- GeoJSON, CSV, layers and report files agree on feature counts.

## Deliverables

- `geometry.geojson`
- `geometry_index.csv`
- `layers.json`
- `parse_report.json`
- `parse_report.md`

## Project Layout

- `scripts/parse_dxf.py` — parser and CLI
- `scripts/common.py` — hashing, JSON output and shared helpers
- `references/entity-mapping.md` — entity to geometry mapping and block expansion
- `references/dwg-notes.md` — DWG conversion flow and licensing cautions
- `references/output-schema.md` — output files, fields and guarantees
- `tests/` — unittest suite and `cad_sample.dxf` fixture
- `requirements.txt` — `ezdxf`

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Tests are skipped automatically when `ezdxf` is not installed.

## Related Skills

- `mine-data-inspection` — input inventory and quality warnings
- `mine-coordinate-registration` — coordinate handling after extraction
- `mine-terrain-modeling` — consumes contours and survey geometry
