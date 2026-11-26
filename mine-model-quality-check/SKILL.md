---
name: mine-model-quality-check
description: Independently validate mine 3D models and registration results for topology, geometry, elevations, orientation, offsets, overlaps, boundaries and RMSE thresholds. Use before delivering or publishing any mine 3D model.
---

# Mine Model Quality Check

> Status: v0.1 — OBJ topology/geometry checks (duplicate vertices, degenerate triangles, boundary/non-manifold edges, boundary loops, signed volume/orientation, bbox/Z range) and registration RMSE thresholds are implemented with tests. GLB/glTF/PLY, overlap and coordinate-offset checks are NOT implemented.

## Role

You are an independent quality assurance specialist for mine 3D models. You do not build or repair models; you verify them and report evidence. Unknown results must remain `UNKNOWN` and must never be presented as a pass.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| OBJ mesh | Full: `v` and `f` (including `i/j/k` tokens), polygon fan triangulation, negative indices |
| Closed meshes | Boundary/non-manifold checks, signed volume and orientation |
| Open surfaces (terrain) | Topology and bbox checks with `--allow-boundary`; orientation remains `UNKNOWN` |
| GLB / glTF / PLY | Not supported in v0.1 |
| Registration report JSON | Optional RMSE and max-residual evidence; `--max-rmse` threshold required |
| Registration check points | Not read directly; use the RMSE from `mine-coordinate-registration` |
| Multiple models / overlap and inter-model offsets | Not supported in v0.1 |
| CRS metadata / unit detection | Not performed; units and CRS are `UNKNOWN` |

## Quick Start

Run the following commands from this skill directory.

```bash
python3 -m pip install -r requirements.txt
```

```bash
# Closed model: PASS expected
python3 scripts/check_model.py tests/fixtures/cube.obj --out-dir quality_output

# Broken model: exits 1 on FAIL
python3 scripts/check_model.py tests/fixtures/cube_broken.obj --out-dir quality_output

# Open terrain plus registration accuracy
python3 scripts/check_model.py terrain.obj --allow-boundary \
  --registration registration_output/registration_report.json --max-rmse 0.05 \
  --out-dir quality_output
```

Exit code is `1` when the overall status is `FAIL` unless `--no-fail` is given.
`UNKNOWN` exits `0` but requires manual review.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--out-dir` | `quality_output` | Output directory |
| `--allow-boundary` | off | Accept boundary edges for legitimately open surfaces |
| `--round-decimals` | `6` | Decimal places for duplicate vertex grouping |
| `--area-epsilon` | `1e-12` | Absolute degenerate-area threshold in source units squared |
| `--registration` | off | Registration report JSON to verify |
| `--max-rmse` | off | Required with `--registration`; RMSE must be `<=` this value |
| `--no-fail` | off | Always exit `0`, even on `FAIL` |

## Workflow

1. Record the model checksum and read the OBJ read-only.
2. Parse `v` and `f` elements, resolve negative indices, fan-triangulate polygons and record invalid face references.
3. Detect duplicate vertices by rounded position; do not merge them.
4. Detect degenerate triangles from repeated indices, zero/near-zero area and non-finite coordinates.
5. Build undirected edge counts; classify boundary, manifold and non-manifold edges.
6. Trace boundary edges into closed loops and open chains; count holes for closed meshes.
7. For closed meshes, compute signed volume and orientation; for open meshes mark orientation `UNKNOWN`.
8. Report bounding box and Z range.
9. If a registration report is supplied, extract RMSE/max residual and compare RMSE against `--max-rmse`.
10. Emit per-check `PASS`/`FAIL`/`UNKNOWN`, an overall status, JSON/Markdown/CSV outputs and a reproduction command.

## Engineering Rules

- Stay independent from modeling code, parameters and assumptions.
- Never auto-fix or modify the model; the checker is read-only.
- Thresholds must be explicit and agreed before validation; registration accuracy requires `--max-rmse`.
- Do not claim accuracy without independent check points or a registration report.
- Interpret boundary loops as holes only for closed meshes; use `--allow-boundary` for terrain and review the outer loop.
- Remember that units and CRS are unknown; area, volume and Z values carry source units.
- Fan triangulation is not valid for strongly concave polygons; flag this limitation.
- Duplicate detection is position-only; UV/normal seams are not modelled.
- Report `UNKNOWN` explicitly and never silently convert it to pass.

## Quality Requirements

- Cover duplicate vertices, degenerate triangles, boundary and non-manifold edges, boundary loops/holes, signed volume/orientation for closed meshes, bbox/Z range and optional registration RMSE.
- Every check produces a status, summary, value and threshold where applicable.
- Issues carry a location (OBJ line, triangle, vertex or edge) and the report carries a reproduction command.
- JSON, Markdown and `issues.csv` must agree on counts and overall status.
- Detail lists are capped at 100 entries but metric counts remain complete.
- Truncation, invalid faces, ambiguous boundary vertices and open meshes are warned about.
- Never claim GLB/PLY, overlap, multi-model offset or CRS checks that v0.1 does not perform.

## Deliverables

- `quality_report.json`
- `quality_report.md`
- `issues.csv`

## Project Layout

- `scripts/check_model.py` — OBJ parser, checks, registration comparison, outputs and CLI
- `references/checks.md` — check definitions, statuses, formulas and limitations
- `references/output-schema.md` — JSON, Markdown and CSV fields, exit codes and guarantees
- `tests/test_check_model.py` — unittest suite
- `tests/fixtures/cube.obj` — closed outward-oriented cube (quads)
- `tests/fixtures/cube_broken.obj` — missing face, duplicate vertex and degenerate triangle
- `tests/fixtures/nonmanifold.obj` — three triangles sharing one edge
- `requirements.txt` — `numpy`

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Tests cover fan triangulation, negative indices, invalid face references, a
passing cube, a broken cube (hole, degenerate face, duplicate vertex,
non-manifold edge), inverted winding, non-manifold edge detection, registration
threshold pass/fail/unknown and CLI exit codes (`FAIL` -> 1, `--no-fail` -> 0).

## Related Skills

- `mine-coordinate-registration` — produces the registration report being verified
- `mine-terrain-modeling` — produces OBJ terrain to check with `--allow-boundary`
- `mine-cad-parser` — geometry source for mesh construction
- `mine-3d-tiles` — published assets that must pass this gate before release
