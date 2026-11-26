---
name: mine-point-cloud
description: Process mine point clouds from LiDAR or UAV photogrammetry — denoise, classify ground, downsample, register and rebuild surfaces, then prepare them for 3D Tiles. Use when raw LAS/LAZ/PLY point clouds must become clean terrain or scene geometry.
---

# Mine Point Cloud

> Status: v0.1 — LAS 1.0-1.4 header inspection and XYZ/CSV Z-filter, voxel downsampling and lowest-Z ground candidates are implemented with tests. LAZ point records are NOT decompressed, ground classification and surface reconstruction are NOT implemented, and PDAL/Open3D integration is planned.

## Role

You are a mine point cloud processing specialist. Your job is to turn raw scans into clean, classified, georeferenced point clouds and surface products without destroying engineering features. In v0.1 you must be explicit that header inspection and lowest-Z candidates are not a substitute for a real PDAL/Open3D classification pipeline.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| LAS 1.0-1.4 | Header parsed with `struct`: version, point format, record length, counts, scale/offset, bounds, creation, compression flag |
| LAZ | Header parsed; `compressed` reported; point records are NOT decompressed. Use PDAL or laszip |
| XYZ / CSV / TSV / whitespace points | `filter` subcommand: Z range, voxel downsample, ground candidates |
| PLY / E57 / PCD | Not supported |
| Ground classification | Lowest-Z point per XY cell only; explicitly NOT a classifier |
| Multi-scan registration | Not implemented; use `mine-coordinate-registration` |
| Surface reconstruction / 3D Tiles | Not implemented; hand ground candidates to `mine-terrain-modeling` |

## Quick Start

Run the following commands from this skill directory.

```bash
python3 -m pip install -r requirements.txt
```

```bash
# LAS header report
python3 scripts/pointcloud.py inspect cloud.las \
  --output las_header.json --markdown las_header.md

# XYZ filtering and simple ground candidates
python3 scripts/pointcloud.py filter tests/fixtures/survey_points.xyz \
  --out-dir pointcloud_output --voxel-size 1 \
  --z-min 95 --z-max 106 --ground-cell-size 2
```

`inspect` prints the JSON report to stdout when neither `--output` nor
`--markdown` is supplied. Exit code is `0` on success; missing files, invalid
signatures and invalid parameters raise `SystemExit`.

## Options

### `inspect`

| Option | Default | Meaning |
|---|---|---|
| `path` | required | LAS or LAZ file |
| `--output` | off | Write the JSON header report |
| `--markdown` | off | Write the Markdown header report |

### `filter`

| Option | Default | Meaning |
|---|---|---|
| `--out-dir` | `pointcloud_output` | Output directory |
| `--voxel-size` | off | Voxel edge length in source units; greater than 0 |
| `--z-min` / `--z-max` | off | Inclusive Z range filter |
| `--ground-cell-size` | `10.0` | XY cell size for lowest-Z candidates |
| `--x-col` / `--y-col` / `--z-col` | `1,2,3` | 1-based coordinate columns |
| `--delimiter` | auto | `,`, `;` or tab |
| `--encoding` | auto | Text encoding override |

## Workflow

1. Run `inspect` and record LAS version, point format, compression, point counts, scale/offset, bounds and every warning.
2. If the file is LAZ, stop point-level work and decompress with PDAL/laszip outside this skill; do not treat the header as point data.
3. For XYZ/CSV input, load points with automatic delimiter/header detection and report skipped rows.
4. Apply the optional Z range filter.
5. Apply optional voxel downsampling (first point per voxel in file order).
6. Derive simple ground candidates: lowest Z per XY cell, with deterministic tie-breaking.
7. Write filtered points, ground candidates, JSON/Markdown reports and stage counts.
8. Hand ground candidates to `mine-terrain-modeling`, and verify any derived surface with `mine-model-quality-check`.
9. State clearly that classification, denoising, registration and surface reconstruction were not performed.

## Engineering Rules

- Never assume units or a coordinate reference system; do not relabel header bounds as a CRS.
- Do not decompress LAZ inside this tool; use PDAL or laszip and record the pipeline/version.
- Never present lowest-Z candidates as classified ground.
- Preserve raw files; every output must be reproducible from the source and parameters.
- Report counts and Z ranges before and after every stage.
- Keep voxel and ground-cell selection deterministic.
- The whole XYZ/CSV input is loaded into memory; split very large clouds first.
- Do not claim point-level statistics from a LAS header alone.

## Quality Requirements

- The header report covers signature, version, header size, point data offset, VLR/EVLR counts, point format, record length, compression, point counts, scale, offset, bounds, creation metadata and warnings.
- Point counts must state whether they came from the legacy or extended fields.
- Skip/truncation/compression warnings must be visible and traceable.
- Filter reports must show input, Z-filtered, voxel-downsampled and ground-candidate counts and Z ranges.
- Every output labels units and CRS as `UNKNOWN`.
- Do not claim classification accuracy, density or surface accuracy that was not measured.

## Deliverables

`inspect`:

- `las_header.json` (or the requested path)
- `las_header.md` (or the requested path)

`filter`:

- `filtered_points.csv` — `index, x, y, z`
- `ground_candidates.csv` — `index, cell_x, cell_y, x, y, z`
- `pointcloud_filter_report.json`
- `pointcloud_filter_report.md`

Not produced in v0.1: `cleaned.laz`, `ground.laz`, `classified.laz`,
`pointcloud_mesh.glb`, density rasters or 3D Tiles.

## Project Layout

- `scripts/pointcloud.py` — LAS header inspector, XYZ filter and CLI
- `references/las-header.md` — LAS header offsets, LAZ rules, warnings and PDAL plan
- `references/filtering-notes.md` — stage definitions, determinism, parameter guidance and limitations
- `tests/test_pointcloud.py` — unittest suite and in-test LAS writer
- `tests/fixtures/survey_points.xyz` — filter fixture
- `requirements.txt` — `numpy`

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Tests build LAS 1.2, LAS 1.4 and compressed-LAZ headers with `struct`, assert
header fields and warnings, exercise invalid signatures, and cover XYZ
filter/voxel/ground-candidate counts, validation errors, CLI output files and
CSV contents.

## Related Skills

- `mine-data-inspection` — source inventory and coordinate clues
- `mine-coordinate-registration` — scan and coordinate registration
- `mine-terrain-modeling` — consumes classified or candidate ground points
- `mine-3d-tiles` — publishes point clouds after PDAL-based processing
- `mine-model-quality-check` — independent verification of derived products
