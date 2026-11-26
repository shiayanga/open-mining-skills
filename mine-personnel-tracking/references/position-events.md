# Personnel Position Events (v0.1)

## Input event

`positions.jsonl` contains one `ENTITY_POSITION_UPDATE` event per line:

```json
{
  "eventId": "evt-p1",
  "eventType": "ENTITY_POSITION_UPDATE",
  "mineId": "MINE-001",
  "entityId": "PERSON-001",
  "entityType": "PERSON",
  "objectId": "OBJ-PERSON-001",
  "sourceTimestamp": 1795680000000,
  "sequence": 1,
  "payload": {
    "position": {
      "x": 2.0,
      "y": 2.0,
      "z": 320.0,
      "coordinateSystemId": 1001
    },
    "positionQuality": "VALID"
  }
}
```

Required for processing: `eventType`, `entityId`, `mineId`, `sourceTimestamp`, `payload`, `payload.position` with finite `x/y/z`, and `payload.position.coordinateSystemId`. `sequence` is optional but recommended; without it, same-timestamp ordering falls back to sequence `0`.

`entityType` is expected to be `PERSON`; a missing value is warned and processed as personnel because this file is the personnel stream. Explicit non-person types are skipped.

## Quality semantics

| Quality | Latest position | Track | Geofence/state | Area count |
|---|---|---|---|---|
| `VALID` | yes | yes | yes | yes |
| `LOW_ACCURACY` | yes | yes | yes, quality retained | yes |
| `STALE` | yes, marked stale | yes | no | no |
| `INVALID` | yes, marked invalid | yes | no | no |
| missing/unknown | classified `INVALID` | yes | no | no |

Missing or unknown quality never aborts the run; it is a warning and the position is classified `INVALID`.

## Ordering and rejection

Per `entityId`, accepted events must be strictly newer by:

1. `sourceTimestamp`, or
2. equal `sourceTimestamp` with a greater `sequence`.

An older timestamp or equal timestamp with an equal/lower sequence is ignored and reported as `OUT_OF_ORDER_IGNORED`. Ignored events:

- do not update latest position,
- do not append a track row,
- do not update geofence state,
- do not emit entry/exit events.

A newer timestamp with a lower sequence is accepted with a `SEQUENCE_REGRESSION` warning to reflect a likely device reconnect.

## Latest positions output

```json
{
  "skill": "mine-personnel-tracking",
  "version": "v0.1",
  "coordinatePolicy": "source coordinate system is preserved; no conversion is applied",
  "count": 1,
  "positions": [
    {
      "entityId": "PERSON-001",
      "mineId": "MINE-001",
      "objectId": "OBJ-PERSON-001",
      "position": {"x": 25.0, "y": 25.0, "z": 320.0, "coordinateSystemId": 1001},
      "positionQuality": "VALID",
      "sourceTimestamp": 1795680003000,
      "sequence": 3,
      "eventId": "evt-p4",
      "insideGeofences": []
    }
  ]
}
```

## Tracks CSV

Columns: `entity_id, mine_id, source_timestamp, sequence, x, y, z, coordinate_system_id, quality, inside_geofences`.

Rows are sorted by entity, timestamp and sequence. `inside_geofences` is a semicolon-separated ID list evaluated geometrically for that accepted position; it is not a geofence transition log.

## Engineering boundaries

- No coordinate transformation; the source `coordinateSystemId` stays attached to every row.
- No smoothing, interpolation or fabricated high-frequency points.
- No permission filtering in v0.1; outputs contain sensitive personnel data and must be protected by the consuming system.
- Live streams, replay APIs and batch scene updates are future work.
