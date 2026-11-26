# Alarm State Machine and Device Status (v0.1)

## Threshold alarm identity

A generated threshold alarm is keyed by:

```text
(entityId, metricCode)
```

Only one active threshold alarm exists per device metric at a time, regardless of direction or level. This prevents a warning and an alarm for the same metric from duplicating.

## Transitions

| Current active alarm | New severity | Action |
|---|---|---|
| none | `NORMAL` | none |
| none | `WARNING` or `ALARM` | create alarm; emit `CREATED` / `ACTIVE` |
| active | same severity | update value/timestamp/event count; **no new alarm event** |
| active | different severity | update level and threshold; emit `ESCALATED` or `DEESCALATED` / `ACTIVE` |
| active | `NORMAL` | clear alarm; emit `CLEARED` / `CLEARED`; remove from active map |

Actions and statuses are carried in `payload.action` and `payload.status`.

## Generated alarm envelope

```json
{
  "eventType": "MONITOR_ALARM",
  "alarmId": "ALM-000001",
  "mineId": "MINE-001",
  "entityId": "MON-001",
  "entityType": "MONITOR_DEVICE",
  "objectId": "OBJ-MON-001",
  "sourceTimestamp": 1795680001000,
  "sequence": 2,
  "payload": {
    "alarmId": "ALM-000001",
    "alarmType": "THRESHOLD",
    "alarmLevel": "WARNING",
    "metricCode": "CH4",
    "currentValue": 0.9,
    "threshold": 0.8,
    "thresholdVersion": "2026.11-v1",
    "direction": "HIGH",
    "unit": "%",
    "status": "ACTIVE",
    "action": "CREATED",
    "message": "CH4 value 0.9 % crossed warning high threshold 0.8.",
    "source": "THRESHOLD_EVALUATION"
  }
}
```

Alarm IDs are sequential in processing order. The first triggering event ID is stored in the internal alarm state (`firstEventId`); report-level active alarms show the current value and event count.

## Deduplication

- Repeated abnormal values update the active alarm only; no duplicate `alarms.jsonl` record is written.
- A different severity produces one update event, not a second active alarm.
- A metric that disappears from later events keeps its last value and any active alarm; absence is not treated as normal.
- Out-of-order events are ignored before evaluation, so they cannot create, update or clear an alarm.

## Upstream alarms

`MONITOR_ALARM` events from ThingLinks/Spring Boot are passed through with `payload.source: "UPSTREAM"` after basic validation. They are deduplicated by `payload.alarmId` (or `eventId` when no alarm ID exists). A duplicate is suppressed with a warning. Upstream alarms do not mutate the generated threshold-alarm state in v0.1.

## Device status

| Status | Rule |
|---|---|
| `OFFLINE` | Explicit `ENTITY_OFFLINE` or `payload.online: false` |
| `STALE` | Device has metrics, is not explicitly offline, and has no update for more than `--stale-after-ms` relative to the latest device timestamp in the file |
| `ONLINE` | Otherwise |

Only devices that have received at least one metric update appear in `latest_values.json`. Stale devices are reported with a `DEVICE_STALE` warning and are never presented as normal. An explicit offline device is not relabeled stale.

## Outputs

- `latest_values.json` — latest metric values, source status, derived threshold status, device status and active alarms.
- `alarms.jsonl` — generated threshold transitions plus deduplicated upstream alarms, in processing order.
- `monitoring_report.json` / `.md` — counts, device table, active alarms and issues.

## v0.1 limitations

- Batch reference time is the latest timestamp in the supplied file; live clock handling is future work.
- No alarm acknowledgement, suppression windows, flood control or notification delivery.
- No duration-based thresholds, history curve queries or persisted alarm database.
- Threshold versions are recorded but not resolved against a version history.
