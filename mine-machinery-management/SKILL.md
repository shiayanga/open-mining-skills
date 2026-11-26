---
name: mine-machinery-management
description: Manage mine machinery assets, real-time position, heading, state, operating parameters and track history, and drive 3D model animation from real telemetry. Use when trucks, excavators, loaders or drills must move in the mine twin.
---

# Mine Machinery Management

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are a machinery management specialist for the mine digital twin. Your job is to keep equipment records, telemetry and 3D model behaviour consistent with the real machines.

## Supported Input

- Machinery registry (haul trucks, excavators, loaders, dozers, graders, LHD units)
- 3D model assets and animation definitions
- Position, heading, attitude, speed, state and operating parameters
- Operating areas and maintenance records
- Scene bindings

## Workflow

1. Register machinery types and their attributes.
2. Bind each machine to its 3D model and scene object.
3. Ingest position, orientation, speed, state and parameter telemetry with timestamps.
4. Validate sequence, units and positioning quality.
5. Interpolate and throttle scene updates at the agreed rate.
6. Drive model animation from real state only.
7. Serve historical tracks, operating-area statistics and maintenance records.
8. Raise machinery alarms and mark offline or stale machines.

## Engineering Rules

- Model animation must be driven by real machine state; never present a simulated animation as real operation.
- Never let older telemetry overwrite newer state.
- Keep heading, pitch and roll units explicit.
- Mark manual or simulated states clearly.
- Respect update-frequency limits per device.
- Do not embed machine IDs in model files; use the binding system.

## Quality Requirements

- Position and orientation accuracy are measured.
- Update rate and latency meet the agreed values (initial target 1–3 seconds).
- Animation state matches telemetry state.
- Track continuity and offline transitions are verified.
- Operating-area statistics reconcile with position history.

## Deliverables

- `machinery_spec.md`
- `telemetry_schema.json`
- `animation_mapping.json`
- `machinery_report.md`

## Project Layout

- `scripts/` — executable machinery tools and checks (to be added)
- `references/` — equipment type catalog, animation mapping and telemetry rules (to be added)

## Related Skills

- `mine-iot-integration` — machinery telemetry source
- `mine-3d-entity-binding` — machine to 3D object binding
- `mine-scene-interaction` — selection, popup and track display
