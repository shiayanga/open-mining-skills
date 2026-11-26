# Machinery Registry and Telemetry Schema (v0.1)

## Registry

```json
{
  "machinery": [
    {
      "machineryId": "EXC-001",
      "machineryType": "EXCAVATOR",
      "model": "excavator.glb",
      "modelNodeId": "Excavator_Main",
      "mineId": "MINE-001",
      "name": "Excavator 1"
    }
  ]
}
```

Accepted forms: a top-level list, `{ "machinery": [...] }`, `{ "machines": [...] }`, `{ "items": [...] }`, or a machinery-ID-keyed object.

Rules:

- `machineryId` (aliases `entityId`, `id`) is required and unique.
- `machineryType` (aliases `type`, `equipmentType`) is required.
- `model` (alias `modelId`) is required and must be a non-empty string; a model object may expose `modelId`/`id`.
- `mineId` is optional; when both registry and telemetry declare one, they must match.
- `modelNodeId` is optional but must be non-empty when present.

## Telemetry

Envelope form:

```json
{
  "eventId": "mach-001",
  "eventType": "MACHINERY_STATUS_UPDATE",
  "machineryId": "EXC-001",
  "mineId": "MINE-001",
  "sourceTimestamp": 1795680000000,
  "sequence": 1,
  "payload": {
    "position": {"x": 100.0, "y": 200.0, "z": 300.0, "coordinateSystemId": 1001},
    "orientation": {"heading": 90.0, "pitch": 0.0, "roll": 0.0},
    "speed": 5.0,
    "state": "WORKING",
    "params": {"fuelLevel": 80.0}
  }
}
```

Flat form is also accepted: `position`, `orientation`, `speed`, `state` and `params` may sit at the top level instead of inside `payload`.

## Field rules

| Field | Rule |
|---|---|
| Machinery ID | `machineryId` or envelope `entityId`; conflicting values are an error |
| `sourceTimestamp` | Non-negative epoch milliseconds; required |
| `sequence` | Non-negative integer; required |
| At least one telemetry field | Required among position, orientation, speed, state, params |
| `position` | Object with finite `x`, `y`, `z`; optional non-empty `coordinateSystemId` (warning when absent) |
| `orientation` | Object with finite `heading`, `pitch`, `roll`; units are degrees when declared |
| Heading | `[0, 360)` degrees |
| Pitch | `[-90, 90]` degrees |
| Roll | `[-180, 180]` degrees |
| `speed` | Finite, non-negative |
| `state` | Non-empty string; unknown states warn and map to no animation |
| `params` | Object; values are passed through and merged into latest state |

Supported event types when `eventType` is present: `MACHINERY_STATUS_UPDATE`, `MACHINERY_ALARM`, `ENTITY_POSITION_UPDATE`, `ENTITY_STATUS_UPDATE`, `ENTITY_PROPERTY_UPDATE`. Other event types are skipped with a warning. An event without `eventType` is treated as flat telemetry.

## Partial updates

Each event is a partial assertion:

- A state-only event updates state and animation while retaining the previous position, orientation, speed and params.
- A position-only event adds a track row and retains the previous state.
- `params` are merged key-by-key.
- The latest state is built only from accepted events; older telemetry is ignored.

## Ordering

Per machinery, accepted events must be strictly newer by timestamp, or have an equal timestamp and greater sequence. Older events produce `OUT_OF_ORDER_IGNORED` and cannot change latest state or tracks. A newer timestamp with a non-increasing sequence is accepted with `SEQUENCE_REGRESSION` warning.

## Outputs

- `latest_state.json` — registry identity, merged position/orientation/speed/params, state, animation, last accepted timestamp/sequence and event count.
- `tracks.csv` — one row per accepted event that contains a position.
- `machinery_report.json` / `.md` — summary, state/animation counts and issues.

## v0.1 limitations

- No update throttling, interpolation or scene update scheduling.
- No coordinate conversion; the source coordinate system is preserved.
- No maintenance records or operating-area statistics.
- No live adapter, driver authentication or command/control channel.
