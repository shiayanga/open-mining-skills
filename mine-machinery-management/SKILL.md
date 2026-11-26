---
name: mine-machinery-management
description: Manage mine machinery assets, real-time position, heading, state, operating parameters and track history, and drive 3D model animation from real telemetry. Use when trucks, excavators, loaders or drills must move in the mine twin.
---

# Mine Machinery Management

> Status: v0.1 — file-based machinery registry validation, telemetry checks, sequence ordering, latest-state merging, track export and state-to-animation mapping are implemented with tests. Live machinery adapters, update throttling and Cesium animation playback are future work.

## Role

You are a machinery management specialist for the mine digital twin. Your job is to keep equipment records, telemetry and 3D model behaviour consistent with the real machines, driving animation only from real state.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| `registry.json` | List or `{ "machinery": [...] }`; validates machinery ID, type, model and optional mine/node |
| `telemetry.jsonl` | Unified envelope or flat telemetry; position, orientation, speed, state and params are merged |
| `state_map.json` | State → animation mapping (string or object); full validation |
| Position | Finite XYZ with optional coordinate-system ID |
| Orientation | Degrees; heading `[0, 360)`, pitch `[-90, 90]`, roll `[-180, 180]` |
| State / animation | Unknown states are kept with a warning and no animation |
| Live adapters / Cesium | Not included in v0.1; telemetry ingestion and scene playback are future work |
| Maintenance records / operating-area statistics | Not included in v0.1 |

## Quick Start

Run the following commands from this skill directory. Only the Python standard library is required.

```bash
python3 scripts/machinery.py \
  tests/fixtures/registry.json \
  tests/fixtures/telemetry.jsonl \
  tests/fixtures/state_map.json \
  --out-dir machinery_output
```

Exit code `0` when no errors occur; out-of-order telemetry and unknown states are warnings. Use `--no-fail` for inspection pipelines.

## Options

| Option | Default | Meaning |
|---|---|---|
| `registry` | required | Machinery registry JSON path |
| `telemetry` | required | Machinery telemetry JSONL path |
| `state_map` | required | State → animation mapping JSON path |
| `--out-dir` | `machinery_output` | Output directory |
| `--no-fail` | off | Always exit 0; errors remain in the report |

## Workflow

1. Load and validate the machinery registry; reject missing IDs, types or models.
2. Load the state-to-animation map; validate non-empty animation names and optional loop/speed settings.
3. Parse each telemetry line and resolve the machinery ID from `machineryId` or the envelope `entityId`.
4. Reject unknown machinery and registry/telemetry mine mismatches.
5. Validate the base fields, timestamp and sequence; require at least one telemetry assertion per event.
6. Validate position coordinates and orientation ranges, speed and `params` object.
7. Reject older telemetry per machine so it cannot overwrite newer state or tracks.
8. Merge partial updates into the latest state, map the real state to an animation name and write a track row when position is present.
9. Future work: live adapter, update throttling/interpolation, offline transitions, maintenance records, operating-area statistics and Cesium animation.

## Engineering Rules

- Model animation must be driven by real machine state; never present a simulated animation as real operation.
- Never let older telemetry overwrite newer state.
- Keep heading, pitch and roll units explicit; v0.1 accepts degrees only.
- Validate heading on `[0, 360)`, pitch on `[-90, 90]` and roll on `[-180, 180]`.
- Mark manual, simulated or unknown states clearly; an unknown state drives no animation.
- Do not embed machine IDs in model files; use the binding system.
- Keep source positions and the coordinate-system ID; do not transform coordinates in v0.1.
- A state-only or position-only event is a valid partial update; omitted fields retain the latest accepted value.

## Quality Requirements

- Every telemetry event either updates a registered machine or reports unknown machinery.
- Sequence and timestamp ordering is explicit; regressions are reported.
- Orientation and speed ranges are validated before state is used for animation.
- Latest state and track rows agree on position, orientation, speed, state and animation.
- Animation names come only from `state_map.json`.
- Reports include state/animation counts, accepted event counts and every issue.

## Deliverables

- `latest_state.json` — merged latest state, position, orientation, params and mapped animation per machine
- `tracks.csv` — accepted telemetry positions with orientation, speed, state and animation
- `machinery_report.json` / `machinery_report.md` — summary, latest-state table, state/animation counts and issues

## Project Layout

- `scripts/machinery.py` — registry/state-map loaders, telemetry parser, state merger, report renderer and CLI
- `references/telemetry-schema.md` — registry and telemetry schemas, field and range rules
- `references/animation-mapping.md` — state mapping semantics, real-vs-simulated boundaries and future playback
- `tests/test_machinery.py` — unittest suite
- `tests/fixtures/registry.json`, `telemetry.jsonl`, `state_map.json` — valid machinery stream

## Testing

```bash
python3 -m unittest discover -s tests -v
```

The suite covers valid state mapping, out-of-order telemetry rejection, unknown machinery, orientation range validation, unknown-state handling and output files.

## Related Skills

- `mine-iot-integration` — machinery telemetry source
- `mine-3d-entity-binding` — machine to 3D object binding
- `mine-scene-interaction` — selection, popup and track display
- `mine-safety-monitoring` — machinery alarms and safety context
