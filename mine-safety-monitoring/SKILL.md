---
name: mine-safety-monitoring
description: Manage mine safety monitoring devices, real-time metric arrays, thresholds, online status and alarms in the digital twin. Use when sensor values and alerts must be visualized on 3D mine objects.
---

# Mine Safety Monitoring

> Status: v0.1 — file-based dynamic metric evaluation, versioned thresholds, online/offline/stale status and deduplicated threshold alarms are implemented with tests. Live ThingLinks/Spring Boot ingestion, history queries and WebSocket alarm publication are future work.

## Role

You are a safety monitoring specialist for the mine digital twin. Your job is to keep device metrics, thresholds and alarms accurate, traceable and visible, using only configured thresholds and source telemetry — never frontend constants or invented values.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| `metrics.json` | Device type → metric definitions; wrapper, mapping or list forms; validates code, unit, min/max |
| `thresholds.json` | List or nested device/metric rules; versioned warning/alarm low/high thresholds |
| `events.jsonl` | `MONITOR_VALUE_UPDATE`, `MONITOR_ALARM`, `ENTITY_ONLINE`, `ENTITY_OFFLINE` |
| Dynamic metrics | Non-empty metric arrays; unknown metrics and duplicate codes are errors |
| Device state | `ONLINE`, `OFFLINE`, `STALE` derived from explicit status and the stream reference time |
| Upstream alarms | Validated and deduplicated by `alarmId`; not mixed with generated threshold alarms |
| Live telemetry / history | Not included in v0.1; ThingLinks time-series and WebSocket are future work |

## Quick Start

Run the following commands from this skill directory. Only the Python standard library is required.

```bash
python3 scripts/monitoring.py \
  tests/fixtures/metrics.json \
  tests/fixtures/thresholds.json \
  tests/fixtures/events.jsonl \
  --out-dir monitoring_output
```

Tighten the stale window for a fast-moving stream:

```bash
python3 scripts/monitoring.py metrics.json thresholds.json events.jsonl \
  --stale-after-ms 10000 --out-dir monitoring_output
```

Exit code `0` when no errors occur; stale devices and out-of-order data are warnings. Use `--no-fail` for inspection pipelines.

## Options

| Option | Default | Meaning |
|---|---|---|
| `metrics` | required | Device type → metric definitions JSON path |
| `thresholds` | required | Threshold configuration JSON path |
| `events` | required | Monitoring event JSONL path |
| `--stale-after-ms` | `300000` | Age after which an online device becomes `STALE` |
| `--out-dir` | `monitoring_output` | Output directory |
| `--no-fail` | off | Always exit 0; errors remain in the report |

## Workflow

1. Load metric definitions by device type and validate codes, units and measurement ranges.
2. Load versioned threshold rules; validate low/high ordering and device-type metric references.
3. Parse monitoring events and validate the unified envelope, device ID, timestamp, sequence and payload.
4. Resolve the device type from the event; if absent, infer only when the metric set is unambiguous, and report the inference.
5. Reject older telemetry per device so it cannot update metrics, status or alarms.
6. Validate every metric array entry against the dynamic definitions; preserve source units and values.
7. Evaluate configured thresholds, create an alarm on the first warning/alarm crossing, update without duplicating on repeats, escalate/de-escalate on level changes and clear when the value returns to normal.
8. Pass through and deduplicate upstream `MONITOR_ALARM` records by `alarmId`.
9. Derive `ONLINE` / `OFFLINE` / `STALE` and write latest values, alarm records and the report.
10. Future work: ThingLinks telemetry/history adapters, WebSocket alarm publication and device-area permissions.

## Engineering Rules

- Metric sets are dynamic per device type; never hardcode one field per metric.
- Thresholds come only from configuration; never hardcode a safety threshold in this skill or the frontend.
- Never treat stale data as normal.
- Deduplicate alarms and preserve the source event, metric code, value and threshold version.
- Never let older telemetry overwrite newer state or clear a newer alarm.
- Keep upstream alarms distinct from locally generated threshold alarms.
- An explicit `OFFLINE` device is not relabeled `STALE`.
- v0.1 evaluates a finite batch; live latency and false-positive measurement are future integration work.

## Quality Requirements

- Metric schemas validate for every device type appearing in the stream.
- Every metric update carries a finite value and a known metric definition.
- Alarm transitions are correct, ordered and traceable: created, updated silently, escalated/de-escalated, cleared.
- Repeated identical abnormal values do not produce duplicate alarm events.
- Online/offline/stale transitions are reported.
- Latest values reconcile with the latest accepted event per device.

## Deliverables

- `latest_values.json` — latest metric values, quality/status, device status and active alarms
- `alarms.jsonl` — generated threshold alarm events plus deduplicated upstream alarms
- `monitoring_report.json` / `monitoring_report.md` — summary, device status, active alarms and issues

## Project Layout

- `scripts/monitoring.py` — definitions, thresholds, event evaluation, alarm state machine, report renderer and CLI
- `references/metric-and-threshold-schema.md` — input schemas and threshold semantics
- `references/alarm-state-machine.md` — deduplication, transitions, stale handling and limitations
- `tests/test_monitoring.py` — unittest suite
- `tests/fixtures/metrics.json`, `thresholds.json`, `events.jsonl` — valid evaluation stream

## Testing

```bash
python3 -m unittest discover -s tests -v
```

The suite covers valid evaluation, threshold crossing creating an alarm, repeated events not duplicating alarms, return-to-normal clearing, stale device flagging, out-of-order rejection and output files.

## Related Skills

- `mine-iot-integration` — telemetry and alarm event source
- `mine-3d-entity-binding` — device to 3D object binding
- `mine-scene-interaction` — device popup, highlighting and alarm display
- `mine-personnel-tracking` — area presence for evacuation and access checks
