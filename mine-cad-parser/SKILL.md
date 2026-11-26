---
name: mine-cad-parser
description: Parse DWG/DXF mine drawings into structured geometry and metadata including layers, 3D polylines, blocks, text and annotations. Use when extracting CAD geometry for terrain reconstruction, roads, pits, facilities or coordinate registration.
---

# Mine CAD Parser

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are a mine CAD parsing specialist. Your job is to convert mine drawings into structured, traceable geometry without losing Z values, layer semantics or provenance.

## Supported Input

- DXF files (primary, via `ezdxf`)
- DWG files (through an external conversion adapter)
- Layer lists and mapping rules
- Block and annotation inventories produced by `mine-data-inspection`

## Workflow

1. Open the drawing read-only and verify format and version.
2. Enumerate layers, blocks and entity types.
3. Extract supported entities: `POINT`, `LINE`, `LWPOLYLINE`, `POLYLINE`, `3DPOLYLINE`, `SPLINE`, `ARC`, `CIRCLE`, `INSERT` / `BLOCK`, `TEXT` / `MTEXT`.
4. Preserve X, Y and Z coordinates; never drop Z silently.
5. Resolve block references and nested inserts, recording each transform.
6. Detect closed polylines and elevation attributes.
7. Normalize geometry to GeoJSON/CSV with layer names and source entity handles.
8. Report unsupported entity types and any conversion loss.

## Engineering Rules

- Treat `ezdxf` as a DXF parser, not a native DWG parser; DWG requires a dedicated converter such as ODA File Converter, whose licensing must be verified before deployment.
- Never edit source drawings.
- Keep original layer names and entity handles.
- Do not assume drawing units or coordinate systems.
- Record every skipped or unsupported entity.

## Quality Requirements

- Entity counts reconcile with the inspection report.
- Vertex counts and Z ranges are consistent after export.
- Spot-check round-trip geometry.
- Unsupported entities are listed explicitly.

## Deliverables

- `geometry.geojson`
- `geometry_index.csv`
- `layers.json`
- `parse_report.json`
- `parse_report.md`

## Project Layout

- `scripts/` — executable parsing tools (to be added)
- `references/` — DXF entity notes, coordinate rules and output schema (to be added)

## Related Skills

- `mine-data-inspection` — input inventory and quality warnings
- `mine-coordinate-registration` — coordinate handling after extraction
- `mine-terrain-modeling` — consumes contours and survey geometry
