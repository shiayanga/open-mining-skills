---
name: mine-iot-integration
description: Integrate an existing Spring Boot or ThingLinks IoT platform with the mine digital twin — unify device IDs, telemetry, status, alerts and subscriptions. Use when real device data must feed the twin without rebuilding the IoT platform.
---

# Mine IoT Integration

> Status: v0.1 — device mapping validation, unified event schema checks, position/quality checks, metric-array checks and timestamp ordering are implemented with tests. Live ThingLinks REST/MQTT adapters, authentication, reconnect handling and WebSocket subscriptions are future work.

## Role

You are an IoT integration specialist for a mine digital twin. Your job is to adapt existing IoT data into a stable twin event model, not to rebuild device access, device registry or telemetry storage. In v0.1 you validate the adapter contract before data reaches the scene.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| `device_mapping.json` | List, `{ "devices": [...] }` or source-ID-keyed object; validates source device → twin entity/type/mine |
| `events.jsonl` | Unified event envelope; validates required fields, types, mapping, deduplication and timestamp order |
| Position updates | Requires `payload.position` with finite XYZ, `coordinateSystemId` and a `positionQuality` enum |
| Monitoring updates | Requires a non-empty dynamic `payload.metrics` array with metric code and numeric value |
| Upstream alarms | Validates basic alarm payload fields and carries alarm metadata |
| Live ThingLinks / MQTT / WebSocket | Not included in v0.1; adapter and subscriber are future work |
| Database persistence / replay | Not included in v0.1 |

## Quick Start

Run the following commands from this skill directory. Only the Python standard library is required.

```bash
python3 scripts/validate_events.py \
  tests/fixtures/device_mapping.json \
  tests/fixtures/events.jsonl \
  --out-dir integration_output
```

A failing batch still writes the report; `--no-fail` makes the command exit `0` for inspection pipelines.

```bash
python3 scripts/validate_events.py mapping.json events.jsonl \
  --out-dir integration_output --no-fail
```

## Options

| Option | Default | Meaning |
|---|---|---|
| `mapping` | required | `device_mapping.json` path |
| `events` | required | `events.jsonl` path |
| `--out-dir` | `integration_output` | Output directory |
| `--no-fail` | off | Always exit 0; errors remain in the report and `issues.csv` |

## Workflow

1. Normalise the device mapping and check duplicate source devices, missing entity IDs and unknown entity types.
2. Parse each JSONL line; malformed lines become explicit issues rather than being skipped silently.
3. Validate the required envelope fields: `eventType`, `mineId`, `entityId`, `entityType`, `objectId`, `sourceTimestamp`, `sequence` and `payload`.
4. Resolve the source device from `sourceDeviceId` (top level or payload) or from an unambiguous entity mapping; reject unknown devices and ID/type/mine mismatches.
5. Validate position payloads: finite XYZ, coordinate-system ID, quality enum and basic orientation/speed types.
6. Validate monitoring payloads as dynamic metric arrays, including duplicate metric codes and unit/status presence.
7. Deduplicate `eventId` values and compare `sourceTimestamp` / `sequence` with the latest accepted event per entity; older events never overwrite newer state.
8. Write the report, issue CSV and latest-entity snapshot; a live adapter is future work.

## Engineering Rules

- Reuse the existing IoT platform; do not duplicate device registry, protocol management or telemetry storage.
- Never invent device IDs; require an explicit source-device mapping.
- Preserve source timestamps and quality; never let older data overwrite newer data.
- Require a coordinate-system ID on every position; never assume all devices share one system.
- Accept only `VALID`, `LOW_ACCURACY`, `STALE` and `INVALID` as position quality values.
- Monitoring metrics remain a dynamic array; do not hardcode one field per metric.
- Never hardcode safety thresholds in the frontend or in this validator; threshold evaluation belongs to `mine-safety-monitoring`.
- v0.1 does not connect to live systems, store credentials or enforce remote permissions; those are production-adapter responsibilities.

## Quality Requirements

- Every in-scope source device has a complete mapping to a twin entity and type.
- Every event either validates or has a traceable line-level issue.
- Event IDs are unique; timestamp and sequence regressions are detected.
- Position events always carry a quality classification and coordinate-system ID.
- Metric arrays validate for every monitoring event.
- The report includes event-type counts, quality counts, unknown devices and the latest accepted event per entity.

## Deliverables

- `integration_report.json` — status, summary, issues and latest event per entity
- `integration_report.md` — human-readable summary and issue table
- `issues.csv` — flattened issue list for spreadsheet or CI triage

## Project Layout

- `scripts/validate_events.py` — mapping loader, event validator, report renderer and CLI
- `references/event-envelope.md` — unified event schema, required fields and examples
- `references/mapping-and-ordering.md` — ID mapping, deduplication, sequence and timestamp rules
- `tests/test_validate_events.py` — unittest suite
- `tests/fixtures/device_mapping.json`, `tests/fixtures/events.jsonl` — valid batch

## Testing

```bash
python3 -m unittest discover -s tests -v
```

The suite covers a valid batch, unknown source device, out-of-order event rejection, missing/invalid position quality, missing coordinate system, mapping/entity mismatch and output files.

## Related Skills

- `mine-personnel-tracking` — personnel position events
- `mine-safety-monitoring` — monitoring metrics and alarms
- `mine-machinery-management` — machinery telemetry
- `mine-3d-entity-binding` — device to 3D object binding
- `mine-scene-interaction` — realtime display in the scene
