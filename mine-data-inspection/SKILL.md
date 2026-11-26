---
name: mine-data-inspection
description: Inspect raw mine data files and report format, layers, entity types, coordinate clues, extents and data quality issues. Use when receiving DWG/DXF, XYZ survey points, point clouds or other mine datasets, before parsing, coordinate registration or modeling.
---

# Mine Data Inspection

> Status: v0.1 — DXF and XYZ/CSV inspection are implemented with scripts and tests. DWG (requires conversion), LAS/LAZ point clouds and SHP are not yet inspected.

## Role

You are the data intake specialist for a mine 3D modeling pipeline. Your job is to describe what the received data actually contains and to surface uncertainty — never to guess.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| DXF drawings | Full inspection via `ezdxf` (layers, entities, extents, units, 3D presence, blocks, text) |
| XYZ / CSV / TSV / whitespace points | Full inspection (columns, extents, duplicates, quality warnings) |
| DWG | Not parsed directly; convert to DXF first (see `references/dwg-notes.md`) |
| LAS / LAZ / PLY / E57 | Not yet inspected; planned for v0.2 with PDAL |
| SHP / GeoJSON / DEM | Not yet inspected |

## Quick Start

Run the following commands from this skill directory.

```bash
python3 -m pip install -r requirements.txt

# Dispatch by file type (DXF and XYZ)
python3 scripts/inspect_file.py tests/fixtures/sample.dxf \
  --output data_inspection_report.json --markdown data_inspection_report.md

python3 scripts/inspect_file.py tests/fixtures/survey.xyz \
  --output survey_report.json --markdown survey_report.md
```

Specific inspectors:

```bash
python3 scripts/inspect_dxf.py site.dxf --output site.json --markdown site.md
python3 scripts/inspect_xyz.py survey.xyz --output survey.json \
  --x-col 2 --y-col 3 --z-col 4
```

Exit code `0` on success. Fatal errors (missing `ezdxf`, no valid rows) exit non-zero with a message.

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
- v0.1 reads the whole file; split very large files before inspection.

## Quality Requirements

- The report covers format, version, layers, entity statistics, extents, Z range, 3D presence, unit/CRS clues and warnings.
- Every warning is traceable to a file, line, layer or entity.
- No interpretation without evidence.

## Deliverables

- `data_inspection_report.json`
- `data_inspection_report.md`
- optional `source_manifest.json` via `--manifest`

## Project Layout

- `scripts/inspect_file.py` — format dispatcher (DXF / XYZ / unsupported)
- `scripts/inspect_dxf.py` — DXF inspector
- `scripts/inspect_xyz.py` — XYZ / CSV inspector
- `scripts/common.py` — hashing, JSON output and shared helpers
- `references/dxf-inspection.md` — DXF checks, unit codes and limitations
- `references/dwg-notes.md` — DWG conversion flow and licensing cautions
- `references/xyz-inspection.md` — detection rules, options and heuristics
- `references/report-schema.md` — report field reference and example
- `tests/` — unittest suite and fixtures (`sample.dxf`, `survey.xyz`)
- `requirements.txt` — `ezdxf`

## Testing

```bash
python3 -m unittest discover -s tests -v
```

DXF tests are skipped automatically when `ezdxf` is not installed; XYZ and dispatcher tests still run.

## Related Skills

- `mine-cad-parser` — next step for DWG/DXF geometry extraction
- `mine-coordinate-registration` — coordinate analysis after inspection
