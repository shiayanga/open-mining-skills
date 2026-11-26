# Device Mapping, Deduplication and Ordering (v0.1)

## Mapping formats

Preferred list form:

```json
{
  "devices": [
    {
      "sourceDeviceId": "TL-1001",
      "entityId": "PERSON-001",
      "entityType": "PERSON",
      "mineId": "MINE-001"
    }
  ]
}
```

Accepted alternatives:

- A top-level JSON list of mapping entries.
- `{ "mappings": [...] }`, `{ "deviceMapping": [...] }` or `{ "device_mappings": [...] }`.
- A source-ID-keyed object:

```json
{
  "TL-1001": {
    "entityId": "PERSON-001",
    "entityType": "PERSON",
    "mineId": "MINE-001"
  }
}
```

A source-ID-keyed value may also be just the entity ID string.

## Mapping validation

- `sourceDeviceId` must be non-empty and unique.
- `entityId` must be non-empty.
- `entityType` is strongly recommended; absence is a warning because type cross-checks are then impossible.
- `mineId` is optional but must be non-empty when present.
- Mapping entries may share a twin entity (for example a replaced tag); lookup by source remains unique.

Unknown device IDs are never invented. Events that cannot be tied to a mapping are errors.

## Event ID deduplication

`eventId` is optional but recommended. If present:

- First occurrence is recorded.
- A repeat is an `DUPLICATE_EVENT_ID` error and includes the original line number.
- Repeats do not update the latest-entity snapshot.

This is event-level deduplication. Device-level idempotency keys can be added by a future adapter.

## Timestamp and sequence ordering

For every event with a valid entity and timestamp, maintain:

```text
latest[entity] = { sourceTimestamp, sequence, eventType, eventId, line, sourceDeviceId }
```

Rules:

1. `sourceTimestamp` lower than latest → `OUT_OF_ORDER_EVENT` error; do not update latest.
2. Equal timestamp and `sequence <= latest.sequence` → `OUT_OF_ORDER_EVENT` error; do not update latest.
3. Equal timestamp and higher sequence → accepted.
4. Newer timestamp and sequence regression → accepted with a `SEQUENCE_REGRESSION` warning; sequence resets happen after reconnects.
5. Newer timestamp and increasing sequence → normal update.

The report includes `latest_by_entity`, which is the snapshot a WebSocket reconnect could use before resuming incremental events.

## Limits

- Ordering is per `(mineId, entityId)` within one file.
- Clock skew and source clock corrections are not modeled.
- Arrival time (`receivedAt`) is optional and not used for ordering.
- A future live adapter must preserve the same rules across reconnect and snapshot boundaries.
