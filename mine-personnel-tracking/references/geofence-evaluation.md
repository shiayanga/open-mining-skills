# Geofence Evaluation (v0.1)

## Input formats

Preferred:

```json
{
  "geofences": [
    {
      "geofenceId": "GF-001",
      "name": "Working face A",
      "mineId": "MINE-001",
      "polygon": [
        [10.0, 10.0],
        [20.0, 10.0],
        [20.0, 20.0],
        [10.0, 20.0]
      ]
    }
  ]
}
```

Accepted polygon shapes:

- `polygon` / `ring` as `[[x, y], ...]`.
- A GeoJSON `Polygon` object: `{ "type": "Polygon", "coordinates": [[[x, y], ...]] }`.
- An object with `coordinates` holding a ring or a list of rings; the outer ring is used.
- A top-level list of geofence objects.
- A `geofences` or `areas` array wrapper.

Aliases for the identifier are `geofenceId`, `id` and `areaId`. `enabled: false` fences are loaded for validation but excluded from evaluation.

## Polygon validation

- Each vertex is `[x, y]` or `{ "x": ..., "y": ... }` with finite numbers.
- Consecutive duplicates and a closing first/last duplicate are removed.
- At least three distinct vertices are required.
- Shoelace area must be non-zero.
- Duplicate geofence IDs are errors.
- `mineId` is optional; when present it scopes evaluation and area counts to that mine.

## Point-in-polygon

The implementation uses ray casting over the X/Y plane:

- A point exactly on a polygon edge is treated as **inside** (with a small tolerance).
- Z is ignored; geofences are 2D X/Y areas.
- Self-intersecting polygons are not detected; validate them upstream.

## State transitions

For each `(person, geofence)` pair:

1. The first evaluated position seeds the state and emits **no** event. A person already inside at stream start therefore does not create a false entry alarm.
2. An outside → inside change emits `PERSONNEL_ENTER_AREA`.
3. An inside → outside change emits `PERSONNEL_LEAVE_AREA`.
4. Only `VALID` and `LOW_ACCURACY` positions update geofence state. `STALE` and `INVALID` positions do not cause transitions.

Event fields:

```json
{
  "eventId": "GEO-000001",
  "eventType": "PERSONNEL_ENTER_AREA",
  "mineId": "MINE-001",
  "entityId": "PERSON-001",
  "entityType": "PERSON",
  "geofenceId": "GF-001",
  "geofenceName": "Working face A",
  "sourceTimestamp": 1795680001000,
  "sequence": 2,
  "position": {"x": 12.0, "y": 12.0, "z": 320.0, "coordinateSystemId": 1001},
  "positionQuality": "VALID"
}
```

## Area counts

Area counts are computed from the **final latest position per person**, not from history:

- Quality must be `VALID` or `LOW_ACCURACY`.
- The fence must have no `mineId` or match the person's mine.
- The point must be inside the polygon.
- Overlapping fences count a person in each fence.
- `positions_inside_any` counts distinct persons in at least one fence; `positions_outside_all` is the remainder of tracked persons.

## v0.1 limitations

- No unauthorized-entry rules, dwell-time or capacity thresholds; these belong to future alarm configuration.
- No 3D geofences or vertical layers.
- No coordinate transformation; fences and positions must share the mine coordinate system.
- No permission filtering; personnel and area results are sensitive.
- No false-positive or alarm-latency measurement yet.
