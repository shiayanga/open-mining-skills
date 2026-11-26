# Metric and Threshold Schema (v0.1)

## Metric definitions

Preferred form:

```json
{
  "deviceTypes": {
    "CH4_SENSOR": {
      "metrics": [
        {
          "metricCode": "CH4",
          "metricName": "Methane concentration",
          "unit": "%",
          "min": 0.0,
          "max": 5.0
        }
      ]
    }
  }
}
```

Accepted alternatives:

- A direct mapping: `{ "CH4_SENSOR": { "metrics": [...] } }`.
- A direct mapping of device type → metric array.
- A list of metric definition objects, each with `deviceType`.
- `{ "metrics": [...] }` at the top level, with `deviceType` on each entry.

Rules:

- `metricCode` is required and unique per device type.
- `metricName`, `unit`, `min` and `max` are optional.
- `min` and `max` must be finite and `min <= max`.
- Metric sets are dynamic; the script never assumes a fixed number of metrics per device.
- Definition ranges produce a `VALUE_OUTSIDE_DEFINITION_RANGE` warning, not an alarm. Safety thresholds are evaluated separately.

## Threshold configuration

Preferred form:

```json
{
  "version": "2026.11-v1",
  "thresholds": [
    {
      "deviceType": "CH4_SENSOR",
      "metricCode": "CH4",
      "deviceId": "MON-001",
      "warningHigh": 0.8,
      "alarmHigh": 1.0
    }
  ]
}
```

Accepted alternatives:

- A top-level list of rules (version becomes `UNVERSIONED`).
- `{ "rules": [...] }`.
- A nested mapping keyed by device type and metric code, optionally under `thresholds`.
- `warningMin` / `warningMax` / `alarmMin` / `alarmMax` alias the `Low` / `High` fields.
- `entityId` aliases `deviceId`.

Rules:

- `deviceType` and `metricCode` are required.
- At least one of `warningLow`, `warningHigh`, `alarmLow`, `alarmHigh` is required.
- All values must be finite numbers.
- Ordering constraints:
  - `warningLow < warningHigh`
  - `alarmLow <= warningLow`
  - `alarmHigh >= warningHigh`
  - `alarmLow < alarmHigh`
- A `deviceId` rule overrides the generic device-type rule for that device and metric.
- Duplicate rule keys are errors.
- A rule unit, when present, must match the metric definition unit; otherwise a warning is emitted.
- Threshold rules for undefined device types or metrics are warnings.
- A configuration without `version` / `thresholdVersion` is usable but warns `THRESHOLDS_UNVERSIONED`.

## Evaluation

Checked in this order:

1. `value >= alarmHigh` → `ALARM` / `HIGH`
2. `value >= warningHigh` → `WARNING` / `HIGH`
3. `value <= alarmLow` → `ALARM` / `LOW`
4. `value <= warningLow` → `WARNING` / `LOW`
5. otherwise `NORMAL`

The triggered threshold value and direction are stored on the alarm for traceability.

## Device type resolution

The event may declare `deviceType` at the top level or in the payload. If absent, the script infers a device type only when the event's metric codes are all defined for exactly one device type, and reports an `INFERRED_DEVICE_TYPE` warning. Zero candidates is `UNKNOWN_DEVICE_TYPE`; multiple candidates is `AMBIGUOUS_DEVICE_TYPE`. Production adapters should always store `deviceType` explicitly.

## Limitations

- No unit conversion. Values are compared in the declared metric unit.
- No rule expressions, rate-of-change, duration or composite alarms.
- No per-mine threshold sets; the file represents one configuration context.
- No history-store queries; threshold evaluation covers the supplied batch only.
