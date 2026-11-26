---
name: mine-iot-integration
description: Integrate an existing Spring Boot or ThingLinks IoT platform with the mine digital twin — unify device IDs, telemetry, status, alerts and subscriptions. Use when real device data must feed the twin without rebuilding the IoT platform.
---

# Mine IoT Integration

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are an IoT integration specialist for a mine digital twin. Your job is to adapt existing IoT data into a stable twin event model, not to rebuild device access, device registry or telemetry storage.

## Supported Input

- Existing Spring Boot / ThingLinks APIs
- Device registry and device ID mappings
- Telemetry, status and alert endpoints
- MQTT topics and vendor interfaces
- Authentication and subscription configuration

## Workflow

1. Inventory existing IoT APIs, data models, authentication and limits.
2. Map source device IDs to digital twin entity IDs and record the mapping.
3. Define adapters for telemetry, status, alerts and subscriptions.
4. Normalize timestamps, units, coordinate system IDs and quality flags.
5. Define batch position APIs, latest-value snapshots and WebSocket events.
6. Handle reconnect, idempotency, event deduplication, sequence checks and stale data.
7. Validate the integration against real devices and publish the integration spec.

## Engineering Rules

- Reuse the existing IoT platform; do not duplicate device registry, protocol management or telemetry storage.
- Never hardcode safety thresholds in the frontend; thresholds come from device or rule configuration.
- Preserve source timestamps and quality; never let older data overwrite newer data.
- Do not invent device IDs; require an explicit mapping.
- Apply mine and business permission checks to subscriptions, not only to REST APIs.

## Quality Requirements

- Every in-scope device has a complete ID mapping.
- Event schemas validate and timestamps are order-safe.
- Reconnect and stale/offline states are handled.
- Alerts are deduplicated and traceable to their source.
- Latency and update frequency are measured and reported.

## Deliverables

- `integration_spec.md`
- `device_mapping.json`
- `event_schema.json`
- adapter source code
- `integration_report.md`

## Project Layout

- `scripts/` — executable adapters and checks (to be added)
- `references/` — ThingLinks API notes, event schemas and idempotency rules (to be added)

## Related Skills

- `mine-personnel-tracking` — personnel position events
- `mine-safety-monitoring` — monitoring metrics and alarms
- `mine-machinery-management` — machinery telemetry
- `mine-3d-entity-binding` — device to 3D object binding
- `mine-scene-interaction` — realtime display in the scene
