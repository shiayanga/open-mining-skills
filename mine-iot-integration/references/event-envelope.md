# Unified Event Envelope and Validation (v0.1)

## Required envelope

| Field | Type | Rule |
|---|---|---|
| `eventType` | string | Non-empty; known types receive semantic checks, unknown types warn |
| `mineId` | string/int | Non-empty; compared with mapping mine |
| `entityId` | string/int | Non-empty; compared with mapping entity |
| `entityType` | string | Non-empty; v0.1 catalog is `PERSON`, `MONITOR_DEVICE`, `MACHINERY`, `INFRASTRUCTURE` |
| `objectId` | string/int | Non-empty; ties the event to a scene object |
| `sourceTimestamp` | number | Non-negative epoch milliseconds; ordering key |
| `sequence` | integer | Non-negative; tie-breaker and duplicate detector |
| `payload` | object | Event-specific data |

`eventId` is recommended, not in the required list. Missing `eventId` is a warning; duplicate `eventId` is an error.

## Position event

```json
{
  "eventId": "evt-001",
  "eventType": "ENTITY_POSITION_UPDATE",
  "mineId": "MINE-001",
  "entityId": "PERSON-001",
  "entityType": "PERSON",
  "objectId": "OBJ-PERSON-001",
  "sourceTimestamp": 1795680000000,
  "sequence": 1,
  "payload": {
    "sourceDeviceId": "TL-1001",
    "position": {
      "x": 1200.5,
      "y": 850.2,
      "z": 320.5,
      "coordinateSystemId": 1001
    },
    "orientation": {"heading": 90, "pitch": 0, "roll": 0},
    "speed": 1.2,
    "positionQuality": "VALID"
  }
}
```

Position checks:

- `x`, `y`, `z` are finite numbers.
- `payload.position.coordinateSystemId` is present and non-empty.
- `positionQuality` is required for `ENTITY_POSITION_UPDATE` and must be `VALID`, `LOW_ACCURACY`, `STALE` or `INVALID`.
- Orientation is optional; present axis values must be finite numbers.
- Speed, when present, must be a finite number.

## Monitoring event

```json
{
  "eventType": "MONITOR_VALUE_UPDATE",
  "mineId": "MINE-001",
  "entityId": "MONITOR-001",
  "entityType": "MONITOR_DEVICE",
  "objectId": "OBJ-MONITOR-001",
  "sourceTimestamp": 1795680002000,
  "sequence": 1,
  "payload": {
    "sourceDeviceId": "TL-3001",
    "metrics": [
      {
        "metricCode": "CH4",
        "metricName": "Methane concentration",
        "value": 0.35,
        "unit": "%",
        "status": "NORMAL"
      }
    ],
    "online": true
  }
}
```

Metric checks:

- `metrics` is a non-empty array.
- Each entry is an object with a non-empty `metricCode`.
- `value` is a finite number.
- Duplicate metric codes in one event are errors.
- Unit and status are validated when present and warned when absent.

## Alarm event

`MONITOR_ALARM` payloads are checked for `alarmId`, a non-empty `alarmLevel` when present, and finite `currentValue` / `threshold` when present. Full alarm lifecycle evaluation belongs to `mine-safety-monitoring`.

## Supported event types

`ENTITY_POSITION_UPDATE`, `ENTITY_STATUS_UPDATE`, `ENTITY_PROPERTY_UPDATE`, `ENTITY_ALARM`, `ENTITY_ONLINE`, `ENTITY_OFFLINE`, `ENTITY_GEOFENCE_EVENT`, `PERSONNEL_ENTER_AREA`, `PERSONNEL_LEAVE_AREA`, `MONITOR_VALUE_UPDATE`, `MONITOR_ALARM`, `MACHINERY_STATUS_UPDATE`, `MACHINERY_ALARM`, `ENTITY_BINDING_UPDATE`, `SCENE_LAYER_UPDATE`, `SCENE_OBJECT_UPDATE`.

Device-originated types must resolve a source mapping. Scene/binding update events may be backend-originated and do not require a device mapping.

## Source device resolution

`sourceDeviceId` may appear at the top level or in the payload. Legacy `deviceId` is accepted. Conflicting source IDs in one event are errors.

If no source device ID is present, the validator looks up the entity in the mapping. A device-originated event with no mapped entity and no source device is an `UNKNOWN_DEVICE` error. Multiple mappings for one entity are allowed (for example a replacement tag), and the first is used for reporting.

## Mapping mismatch checks

- Source device → event entity ID must agree.
- Source device → event entity type must agree when the mapping declares a type.
- Source device → event mine must agree when the mapping declares a mine.

## v0.1 limitations

- No live ThingLinks REST or MQTT call.
- No authentication, permission or tenant enforcement.
- No WebSocket reconnect/snapshot implementation; only event-file validation.
- No unit normalisation or coordinate transformation.
