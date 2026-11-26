---
name: mine-personnel-tracking
description: Track mine personnel in real time from mixed positioning sources, convert coordinates, render positions and replay tracks with area statistics and geofencing. Use when people and their movements must appear in the mine 3D scene.
---

# Mine Personnel Tracking

> Status: v0.1 — file-based latest-position processing, quality classification, track output, point-in-polygon geofencing and area counts are implemented with tests. Coordinate conversion to scene coordinates, live WebSocket ingestion, replay and permission filtering are future work.

## Role

You are a personnel tracking specialist for the mine digital twin. Your job is to turn positioning events into accurate, quality-aware personnel locations, histories and geofence transitions without fabricating movement or letting old data regress the scene.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| `positions.jsonl` | `ENTITY_POSITION_UPDATE` events with `payload.position` and quality; full processing |
| `geofences.json` | List, `{ "geofences": [...] }` or GeoJSON-style polygon rings; full validation and evaluation |
| Position quality | `VALID`, `LOW_ACCURACY`, `STALE`, `INVALID`; missing/unknown quality becomes `INVALID` |
| Non-person events | Skipped with a warning |
| Coordinate conversion | Not applied; source `coordinateSystemId` is preserved on every position |
| Live positioning / WebSocket | Not included in v0.1; future adapter work |
| Permission filtering / replay | Not included in v0.1; future API work |

## Quick Start

Run the following commands from this skill directory. Only the Python standard library is required.

```bash
python3 scripts/tracking.py \
  tests/fixtures/positions.jsonl \
  tests/fixtures/geofences.json \
  --out-dir tracking_output
```

```bash
python3 scripts/tracking.py positions.jsonl geofences.json \
  --out-dir tracking_output --no-fail
```

Exit code `0` when no processing errors occur; out-of-order positions are warnings and do not by themselves fail the command. Use `--no-fail` for inspection pipelines.

## Options

| Option | Default | Meaning |
|---|---|---|
| `positions` | required | Personnel position JSONL path |
| `geofences` | required | Geofence JSON path |
| `--out-dir` | `tracking_output` | Output directory |
| `--no-fail` | off | Always exit 0; errors remain in the report |

## Workflow

1. Parse position events and validate required IDs, timestamp, payload and finite XYZ.
2. Preserve the source `coordinateSystemId`; never infer a CRS or convert coordinates in v0.1.
3. Classify quality; missing or unknown quality is treated as `INVALID`, not as normal.
4. Reject older or duplicate ordering per person; ignored events never update latest position, tracks or geofences.
5. Maintain one latest position per person and append accepted history to the track table.
6. Validate geofence polygons (finite vertices, at least three points, non-zero area).
7. Evaluate point-in-polygon containment; boundary points count as inside.
8. Seed initial geofence state from the first accepted position, then emit `PERSONNEL_ENTER_AREA` / `PERSONNEL_LEAVE_AREA` on transitions for `VALID` and `LOW_ACCURACY` data.
9. Compute final area counts from latest positions, excluding `STALE` and `INVALID` presence.
10. Future work: coordinate adapter, streaming updates, track replay and role-based filtering.

## Engineering Rules

- Never fabricate high-frequency positions to make movement look smoother.
- Never let an older timestamp overwrite a newer position.
- Mark stale or invalid positions instead of showing them as normal.
- Keep the source coordinate-system ID on every position and track row.
- Personnel location and track data are sensitive; v0.1 output must be protected by the consuming system.
- Only `VALID` and `LOW_ACCURACY` positions update geofence state and area counts.
- The initial geofence state is seeded without emitting a false entry event.
- Geofence output is deterministic and derived only from accepted events.

## Quality Requirements

- Every input line is accepted, skipped or reported with a reason.
- Out-of-order events cannot regress latest position or emit geofence transitions.
- Geofence entry and exit events alternate correctly per person and fence.
- Area counts reconcile with final latest positions.
- Tracks contain one row per accepted position with quality and coordinate system.
- Reports include event totals, quality counts, out-of-order count and geofence statistics.

## Deliverables

- `latest_positions.json` — latest position, quality, timestamp and containing geofences per person
- `tracks.csv` — accepted position history
- `geofence_events.jsonl` — `PERSONNEL_ENTER_AREA` / `PERSONNEL_LEAVE_AREA` events
- `tracking_report.json` / `tracking_report.md` — summary, area counts and issues

## Project Layout

- `scripts/tracking.py` — event parser, ordering, geofence evaluator, report renderer and CLI
- `references/position-events.md` — position event schema, quality and ordering rules
- `references/geofence-evaluation.md` — polygon schema, point-in-polygon semantics and area counts
- `tests/test_tracking.py` — unittest suite
- `tests/fixtures/positions.jsonl`, `tests/fixtures/geofences.json` — valid stream and fence

## Testing

```bash
python3 -m unittest discover -s tests -v
```

The suite covers valid processing, out-of-order rejection, geofence entry/exit detection, area counts, invalid-quality exclusion and output files.

## Related Skills

- `mine-iot-integration` — position event source and device mappings
- `mine-3d-entity-binding` — person to 3D object binding
- `mine-scene-interaction` — selection, popup and track playback
- `mine-safety-monitoring` — area alarms and monitoring context
