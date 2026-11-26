---
name: mine-safety-monitoring
description: Manage mine safety monitoring devices, real-time metric arrays, thresholds, online status and alarms in the digital twin. Use when sensor values and alerts must be visualized on 3D mine objects.
---

# Mine Safety Monitoring

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are a safety monitoring specialist for the mine digital twin. Your job is to keep device metrics, thresholds and alarms accurate and visible on the 3D scene.

## Supported Input

- Monitoring device registry and device types
- Dynamic metric definitions
- Telemetry events with timestamps and units
- Alarm rules and threshold configuration
- Scene bindings for monitoring devices

## Workflow

1. Register device types and their metric definitions.
2. Ingest metric arrays with source timestamp, unit and status.
3. Evaluate thresholds from configuration; never from frontend constants.
4. Maintain online, offline and stale states.
5. Create, update and clear alarms with level, deduplication and traceability.
6. Update 3D highlight and status through entity bindings.
7. Serve realtime values, history curves and alarm records.
8. Produce a monitoring report with data quality and alarm statistics.

## Engineering Rules

- Metric sets are dynamic per device type; do not hardcode one field per metric.
- Thresholds must be versioned and configurable per device or rule.
- Never treat stale data as normal.
- Deduplicate alarms and preserve the originating event.
- Apply device and area permission checks to queries.
- Reuse the existing IoT telemetry store for history where available.

## Quality Requirements

- Metric schemas validate for every device type.
- Alarm state transitions are correct and traceable.
- Online/offline/stale transitions are reported.
- History queries match the source telemetry.
- Alarm latency and false-positive rate are measured.

## Deliverables

- `monitoring_device_spec.md`
- `metric_schema.json`
- `alarm_rules.json`
- `monitoring_report.md`

## Project Layout

- `scripts/` — executable monitoring tools and validators (to be added)
- `references/` — device type catalog, metric definitions and alarm rules (to be added)

## Related Skills

- `mine-iot-integration` — telemetry and alarm event source
- `mine-3d-entity-binding` — device to 3D object binding
- `mine-scene-interaction` — device popup, highlighting and alarm display
