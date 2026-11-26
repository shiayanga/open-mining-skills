---
name: mine-geological-modeling
description: Build implicit 3D geological models of strata, faults and ore bodies from geological interfaces, dip data and boreholes using GemPy. Use when a mine needs subsurface geology beyond the surface terrain model.
---

# Mine Geological Modeling

> Status: v0.1 — interface/borehole validation and a GemPy-oriented `model_definition.json` are implemented with tests. GemPy is not invoked; implicit interpolation, surface meshes, fault modeling, ore-body estimation and resource classification are not implemented.

## Role

You are a mine geological modeling specialist. Your job is to prepare defensible subsurface model inputs from geological evidence — never to infer geology, ore bodies or resources from terrain or point-cloud data alone.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| Interfaces CSV | `x,y,z,series,surface,dip,azimuth`; `dip` and `azimuth` optional |
| Interface validation | Numeric checks, dip 0–90, azimuth 0–360, duplicates, series/surface consistency, extent, counts |
| Boreholes CSV | Optional evidence: `borehole_id,x,y,z,series,surface`; recorded but not interpolated |
| GemPy model definition | JSON with series, surfaces, interfaces, orientations, extent and resolution |
| GemPy execution / interpolation | Not implemented; run GemPy separately |
| Faults, cross-sections, geological maps | Not yet parsed |
| Ore-body estimation, grade, tonnage | Not implemented and must not be inferred from these points alone |
| Terrain top surface | Not yet integrated |

## Quick Start

Run the following commands from this skill directory. No third-party packages are required.

```bash
python3 scripts/prepare_geology.py tests/fixtures/interfaces_valid.csv \
  --boreholes tests/fixtures/boreholes_valid.csv --out-dir geology_output
```

With an explicit GemPy-order extent (`xmin,xmax,ymin,ymax,zmin,zmax`), resolution and series order:

```bash
python3 scripts/prepare_geology.py interfaces.csv --boreholes boreholes.csv \
  --extent 0,600,0,800,50,150 --resolution 60,60,40 \
  --series-order overburden,ore --out-dir geology_output
```

Exit code `0` when validation passes and `model_definition.json` is written. Exit code `1` when validation errors exist: reports are still written, but no model definition is produced.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--boreholes` | none | Optional borehole observation CSV |
| `--out-dir` | `geology_output` | Output directory |
| `--extent` | data bounds | Model extent in GemPy order: `xmin,xmax,ymin,ymax,zmin,zmax` |
| `--resolution` | `50,50,50` | GemPy grid resolution `nx,ny,nz` |
| `--series-order` | first appearance | Comma-separated series names, youngest first |
| `--duplicate-tolerance` | `1e-6` | Absolute XYZ tolerance for duplicate interface detection |
| `--delimiter` | auto | `,`, `;` or `tab` |
| `--encoding` | auto | Text encoding |

## Workflow

1. Read interfaces, detect the delimiter and header, and map the required columns.
2. Validate every row: numeric coordinates, non-empty series/surface, dip 0–90 and azimuth 0–360 when present.
3. Flag duplicate interface points within the tolerance and record both source lines.
4. Check that each surface belongs to exactly one series and resolve the series order.
5. Load optional borehole observations and check their unit/series consistency against the interfaces.
6. Determine the model extent and resolution; verify all data lies inside an explicit extent.
7. Build the GemPy-oriented definition: series youngest first, surfaces, interface points, dip/azimuth orientations and borehole evidence.
8. Write `model_definition.json` only when validation has no errors; always write `geology_report.json` and `geology_report.md`.
9. Hand the definition to a separate GemPy step for implicit interpolation and validate the resulting model against boreholes and independent sections.
10. Never present the definition or an unvalidated model as an ore reserve.

## Engineering Rules

- Do not infer ore bodies from terrain or point-cloud data alone; require geological evidence.
- GemPy is a modeling engine, not an ore-estimation or resource-classification tool. Do not claim grade, tonnage or reserves from this skill.
- Do not run GemPy implicitly or silently; v0.1 stops at a validated definition.
- Document orientation conventions: dip from horizontal, azimuth clockwise from +Y (north), polarity +1.
- State the extent order explicitly: GemPy uses `xmin,xmax,ymin,ymax,zmin,zmax`.
- Series order matters: GemPy treats the first series as the youngest. First-appearance order is only a default and is reported as an assumption.
- Preserve original coordinates, names, line numbers and source checksums.
- Do not assume units or a CRS; both remain `UNKNOWN` until evidence is supplied.
- Report duplicate points and conflicting series/surface assignments with line numbers.

## Quality Requirements

- Every validation error and warning has a stable code, and row-level issues include a source line.
- Dip and azimuth ranges are enforced exactly; invalid values are never passed into the definition.
- Duplicate interface points are detected within a documented tolerance and reported as pairs.
- Each surface maps to exactly one series.
- The model extent contains every interface point and is reported in both min/max and GemPy order.
- Counts for interfaces, orientations, series, surfaces, boreholes and skipped rows agree across the definition and report.
- `model_definition.json` is written only for a clean validation result; a stale definition from an earlier run is removed when validation fails.
- Limitations (no GemPy, no interpolation, no ore estimation) are stated in the deliverables.

## Deliverables

- `model_definition.json` — GemPy-oriented series, surfaces, interfaces, orientations, extent, resolution (written only when valid)
- `geology_report.json`
- `geology_report.md`

## Project Layout

- `scripts/prepare_geology.py` — loaders, validation, definition assembly, reports and CLI
- `scripts/common.py` — hashing, JSON/text output and formatting helpers
- `references/interfaces-schema.md` — CSV columns, aliases, validation and orientation conventions
- `references/gempy-definition.md` — definition structure, GemPy ordering/axis conventions and future pipeline
- `references/validation-rules.md` — error/warning codes, extent rules and exit behaviour
- `tests/fixtures/interfaces_valid.csv`, `tests/fixtures/boreholes_valid.csv`, `tests/fixtures/interfaces_invalid.csv`
- `tests/test_prepare_geology.py` — unittest suite

No third-party dependencies are used, so there is no `requirements.txt`. GemPy is required only for the future interpolation step.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

The suite verifies valid-dataset counts (9 interfaces, 5 orientations, 2 series, 3 surfaces, 3 borehole observations), the GemPy-order extent, series overrides, extent containment, invalid dip/azimuth detection, duplicate detection, series/surface conflicts, non-numeric coordinates, exit codes and stale-definition removal.

## Related Skills

- `mine-terrain-modeling` — surface terrain boundary for the top of the model
- `mine-coordinate-registration` — coordinates and datums
- `mine-3d-modeling` — surface and facility meshes
- `mine-3d-tiles` — publishes geological meshes
- `mine-model-quality-check` — independent validation
