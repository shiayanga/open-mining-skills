---
name: mine-data-inspection
description: Inspect raw mine data files and report format, layers, entity types, coordinate clues, extents and data quality issues. Use when receiving DWG/DXF, XYZ survey points, point clouds or other mine datasets, before parsing, coordinate registration or modeling.
---

# Mine Data Inspection

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are the data intake specialist for a mine 3D modeling pipeline. Your job is to describe what the received data actually contains and to surface uncertainty — never to guess.

## Supported Input

- DWG / DXF drawings
- XYZ / CSV survey points
- LAS / LAZ / PLY point clouds
- SHP / GeoJSON / DEM
- Sidecar metadata and field notes

## Workflow

1. Detect file format and version from file content, not only from the extension.
2. Inventory layers, entity types and block references.
3. Compute 2D and 3D extents, plus elevation ranges.
4. Detect whether true 3D geometry exists (Z values, 3DFACE, 3DPOLYLINE).
5. Collect unit and CRS clues from drawing units, coordinate magnitude, metadata and control point notes.
6. Run completeness checks: empty layers, zero-length entities, duplicate features, missing elevations.
7. Emit a machine-readable inspection report; list every unknown explicitly.

## Engineering Rules

- Read-only: never modify source files.
- Never assume units or coordinate system.
- Never fabricate values; unknown fields must be `null` or `UNKNOWN` with a reason.
- Preserve original file names and record a checksum.
- Stream large files instead of loading everything into memory.

## Quality Requirements

- The report covers format, version, layers, entity statistics, extents, Z range, 3D presence, unit/CRS clues and warnings.
- Every warning references a file, layer or entity.
- No interpretation without evidence.

## Deliverables

- `data_inspection_report.json`
- `data_inspection_report.md`
- `source_manifest.json` (path, size, sha256)

## Project Layout

- `scripts/` — executable inspection tools (to be added)
- `references/` — data format notes and inspection checklist (to be added)

## Related Skills

- `mine-cad-parser` — next step for DWG/DXF geometry extraction
- `mine-coordinate-registration` — coordinate analysis after inspection
