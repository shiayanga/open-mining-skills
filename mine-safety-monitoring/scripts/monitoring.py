#!/usr/bin/env python3
"""Evaluate dynamic monitoring metrics, device status and threshold alarms.

v0.1 is a file-based evaluator. Metric definitions are keyed by device type,
thresholds come only from configuration, repeated events are deduplicated,
alarms are created/cleared with traceable state, and stale devices are flagged.
A live ThingLinks/Spring Boot telemetry adapter and WebSocket publisher are
future work.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ACCEPTED_EVENT_TYPES = {
    "MONITOR_VALUE_UPDATE",
    "MONITOR_ALARM",
    "ENTITY_ONLINE",
    "ENTITY_OFFLINE",
}
ALARM_LEVELS = ("WARNING", "ALARM")


def as_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def read_json(path: str | Path) -> Any:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SystemExit(f"Unable to read {source}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {source}: {exc}") from exc


def read_jsonl(path: str | Path) -> list[dict]:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SystemExit(f"Unable to read {source}: {exc}") from exc
    records: list[dict] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            records.append({"_line": lineno, "_parse_error": f"Invalid JSON: {exc}"})
            continue
        if not isinstance(value, dict):
            records.append({"_line": lineno, "_parse_error": "Event line is not a JSON object."})
            continue
        record = dict(value)
        record.setdefault("_line", lineno)
        records.append(record)
    return records


def add_issue(issues: list[dict], severity: str, code: str, message: str, **context: Any) -> None:
    issue = {"severity": severity, "code": code, "message": message}
    for key, value in context.items():
        if value is not None:
            issue[key] = value
    issues.append(issue)


def _metric_list(raw: Any) -> list | None:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        metrics = raw.get("metrics", raw.get("definitions"))
        if isinstance(metrics, list):
            return metrics
    return None


def normalize_metric_definitions(data: Any) -> tuple[dict, list[dict]]:
    issues: list[dict] = []
    device_types: dict[str, dict[str, dict]] = {}

    if isinstance(data, dict):
        if isinstance(data.get("deviceTypes"), dict):
            raw_types = data["deviceTypes"]
        elif isinstance(data.get("device_types"), dict):
            raw_types = data["device_types"]
        elif isinstance(data.get("metrics"), list):
            raw_types = {}
            for index, entry in enumerate(data["metrics"]):
                context = {"recordType": "metricDefinition", "recordIndex": index}
                if not isinstance(entry, dict):
                    add_issue(issues, "error", "INVALID_METRIC_DEFINITION", "Metric definition must be an object.", **context)
                    continue
                device_type = as_id(entry.get("deviceType"))
                if not device_type:
                    add_issue(issues, "error", "MISSING_DEVICE_TYPE", "Metric definition requires deviceType.", **context)
                    continue
                raw_types.setdefault(device_type, []).append(entry)
        else:
            raw_types = data
    elif isinstance(data, list):
        raw_types = {}
        for index, entry in enumerate(data):
            context = {"recordType": "metricDefinition", "recordIndex": index}
            if not isinstance(entry, dict):
                add_issue(issues, "error", "INVALID_METRIC_DEFINITION", "Metric definition must be an object.", **context)
                continue
            device_type = as_id(entry.get("deviceType"))
            if not device_type:
                add_issue(issues, "error", "MISSING_DEVICE_TYPE", "Metric definition requires deviceType.", **context)
                continue
            raw_types.setdefault(device_type, []).append(entry)
    else:
        add_issue(issues, "error", "INVALID_METRIC_DEFINITIONS", "metrics.json must be an object or list.")
        return {"deviceTypes": {}}, issues

    if not isinstance(raw_types, dict):
        add_issue(issues, "error", "INVALID_METRIC_DEFINITIONS", "Device type definitions must be an object.")
        return {"deviceTypes": {}}, issues

    for raw_type, raw_defs in raw_types.items():
        device_type = as_id(raw_type)
        if not device_type:
            add_issue(issues, "error", "INVALID_DEVICE_TYPE", "Device type key must be non-empty.")
            continue
        metrics_raw = _metric_list(raw_defs)
        if metrics_raw is None:
            add_issue(
                issues,
                "error",
                "INVALID_METRIC_LIST",
                f"Device type '{device_type}' must define a metrics list.",
                deviceType=device_type,
            )
            continue
        metric_map: dict[str, dict] = {}
        for index, metric in enumerate(metrics_raw):
            context = {"deviceType": device_type, "metricIndex": index}
            if not isinstance(metric, dict):
                add_issue(issues, "error", "INVALID_METRIC_DEFINITION", "Metric definition must be an object.", **context)
                continue
            metric_code = as_id(metric.get("metricCode") or metric.get("code"))
            if not metric_code:
                add_issue(issues, "error", "MISSING_METRIC_CODE", "Metric definition requires metricCode.", **context)
                continue
            context["metricCode"] = metric_code
            if metric_code in metric_map:
                add_issue(
                    issues,
                    "error",
                    "DUPLICATE_METRIC_DEFINITION",
                    f"Metric '{metric_code}' is defined more than once for device type '{device_type}'.",
                    **context,
                )
                continue
            unit = metric.get("unit")
            if unit is not None and (not isinstance(unit, str) or not unit.strip()):
                add_issue(issues, "warning", "INVALID_METRIC_UNIT", "Metric unit must be a non-empty string when present.", **context)
                unit = None
            minimum = metric.get("min", metric.get("minValue"))
            maximum = metric.get("max", metric.get("maxValue"))
            if minimum is not None and not is_finite_number(minimum):
                add_issue(issues, "error", "INVALID_METRIC_RANGE", "Metric min must be a finite number.", **context)
                minimum = None
            if maximum is not None and not is_finite_number(maximum):
                add_issue(issues, "error", "INVALID_METRIC_RANGE", "Metric max must be a finite number.", **context)
                maximum = None
            if minimum is not None and maximum is not None and minimum > maximum:
                add_issue(issues, "error", "INVALID_METRIC_RANGE", "Metric min must be <= max.", **context)
            metric_map[metric_code] = {
                "metricCode": metric_code,
                "metricName": metric.get("metricName") or metric.get("name"),
                "unit": unit,
                "min": minimum,
                "max": maximum,
            }
        if not metric_map:
            add_issue(
                issues,
                "warning",
                "EMPTY_DEVICE_TYPE",
                f"Device type '{device_type}' has no usable metric definitions.",
                deviceType=device_type,
            )
        device_types[device_type] = metric_map

    if not device_types:
        add_issue(issues, "error", "NO_METRIC_DEFINITIONS", "No usable metric definitions were loaded.")
    return {"deviceTypes": device_types}, issues


def _threshold_value(rule: dict, *names: str):
    for name in names:
        value = rule.get(name)
        if value is not None:
            return value
    return None


def _nested_threshold_rules(data: dict) -> list[dict]:
    rules: list[dict] = []
    for device_type, metrics in data.items():
        if device_type in {"version", "thresholdVersion", "generatedAt"}:
            continue
        if not isinstance(metrics, dict):
            continue
        for metric_code, values in metrics.items():
            if not isinstance(values, dict):
                continue
            rules.append(
                {
                    "deviceType": device_type,
                    "metricCode": metric_code,
                    **values,
                }
            )
    return rules


def normalize_thresholds(data: Any) -> tuple[dict, list[dict]]:
    issues: list[dict] = []
    if isinstance(data, list):
        raw_rules = data
        version = "UNVERSIONED"
    elif isinstance(data, dict):
        version = as_id(data.get("version") or data.get("thresholdVersion")) or "UNVERSIONED"
        if isinstance(data.get("thresholds"), list):
            raw_rules = data["thresholds"]
        elif isinstance(data.get("rules"), list):
            raw_rules = data["rules"]
        elif isinstance(data.get("thresholds"), dict):
            raw_rules = _nested_threshold_rules(data["thresholds"])
        else:
            raw_rules = _nested_threshold_rules(data)
    else:
        add_issue(issues, "error", "INVALID_THRESHOLDS", "thresholds.json must be an object or list.")
        return {"version": "UNVERSIONED", "rules": [], "byKey": {}, "genericByKey": {}}, issues

    if not raw_rules:
        add_issue(issues, "error", "NO_THRESHOLD_RULES", "No threshold rules were loaded.")
    if version == "UNVERSIONED":
        add_issue(
            issues,
            "warning",
            "THRESHOLDS_UNVERSIONED",
            "Threshold configuration has no version; alarm traceability requires "
            "a versioned threshold set.",
        )

    rules: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_rules):
        context = {"recordType": "threshold", "recordIndex": index}
        if not isinstance(raw, dict):
            add_issue(issues, "error", "INVALID_THRESHOLD_RULE", "Threshold rule must be an object.", **context)
            continue
        device_type = as_id(raw.get("deviceType"))
        metric_code = as_id(raw.get("metricCode") or raw.get("code"))
        device_id = as_id(raw.get("deviceId") or raw.get("entityId"))
        if not device_type:
            add_issue(issues, "error", "MISSING_THRESHOLD_DEVICE_TYPE", "Threshold rule requires deviceType.", **context)
            continue
        if not metric_code:
            add_issue(issues, "error", "MISSING_THRESHOLD_METRIC", "Threshold rule requires metricCode.", **context, deviceType=device_type)
            continue
        context.update({"deviceType": device_type, "metricCode": metric_code})
        if device_id:
            context["deviceId"] = device_id
        rule_key = (device_type, device_id or "", metric_code)
        if rule_key in seen:
            add_issue(
                issues,
                "error",
                "DUPLICATE_THRESHOLD_RULE",
                "Threshold rule is defined more than once for the same device/metric.",
                **context,
            )
            continue
        seen.add(rule_key)

        values = {
            "warningLow": _threshold_value(raw, "warningLow", "warningMin"),
            "warningHigh": _threshold_value(raw, "warningHigh", "warningMax"),
            "alarmLow": _threshold_value(raw, "alarmLow", "alarmMin"),
            "alarmHigh": _threshold_value(raw, "alarmHigh", "alarmMax"),
        }
        if all(value is None for value in values.values()):
            add_issue(
                issues,
                "error",
                "EMPTY_THRESHOLD_RULE",
                "Threshold rule requires at least one warning or alarm threshold.",
                **context,
            )
            continue
        invalid = False
        for name, value in values.items():
            if value is not None and not is_finite_number(value):
                add_issue(issues, "error", "INVALID_THRESHOLD_VALUE", f"{name} must be a finite number.", **context, field=name)
                invalid = True
        if invalid:
            continue
        warning_low = values["warningLow"]
        warning_high = values["warningHigh"]
        alarm_low = values["alarmLow"]
        alarm_high = values["alarmHigh"]
        if warning_low is not None and warning_high is not None and warning_low >= warning_high:
            add_issue(issues, "error", "THRESHOLD_ORDER", "warningLow must be less than warningHigh.", **context)
            continue
        if alarm_low is not None and warning_low is not None and alarm_low > warning_low:
            add_issue(issues, "error", "THRESHOLD_ORDER", "alarmLow must be <= warningLow.", **context)
            continue
        if alarm_high is not None and warning_high is not None and alarm_high < warning_high:
            add_issue(issues, "error", "THRESHOLD_ORDER", "alarmHigh must be >= warningHigh.", **context)
            continue
        if alarm_low is not None and alarm_high is not None and alarm_low >= alarm_high:
            add_issue(issues, "error", "THRESHOLD_ORDER", "alarmLow must be less than alarmHigh.", **context)
            continue
        unit = raw.get("unit")
        if unit is not None and (not isinstance(unit, str) or not unit.strip()):
            add_issue(issues, "warning", "INVALID_THRESHOLD_UNIT", "Threshold unit must be non-empty when present.", **context)
            unit = None
        rule_version = as_id(raw.get("version") or raw.get("thresholdVersion")) or version
        rules.append(
            {
                "ruleId": f"TH-{len(rules) + 1:04d}",
                "deviceType": device_type,
                "deviceId": device_id,
                "metricCode": metric_code,
                "warningLow": warning_low,
                "warningHigh": warning_high,
                "alarmLow": alarm_low,
                "alarmHigh": alarm_high,
                "unit": unit,
                "version": rule_version,
            }
        )

    generic: dict[tuple[str, str], dict] = {}
    specific: dict[tuple[str, str, str], dict] = {}
    for rule in rules:
        if rule["deviceId"]:
            specific[(rule["deviceType"], rule["deviceId"], rule["metricCode"])] = rule
        else:
            generic[(rule["deviceType"], rule["metricCode"])] = rule
    return {
        "version": version,
        "rules": rules,
        "byKey": specific,
        "genericByKey": generic,
    }, issues


def lookup_threshold(config: dict, device_type: str, entity_id: str, metric_code: str) -> dict | None:
    return config["byKey"].get(
        (device_type, entity_id, metric_code)
    ) or config["genericByKey"].get((device_type, metric_code))


def evaluate_threshold(value: float, rule: dict) -> tuple[str, str | None, float | None]:
    if rule.get("alarmHigh") is not None and value >= rule["alarmHigh"]:
        return "ALARM", "HIGH", rule["alarmHigh"]
    if rule.get("warningHigh") is not None and value >= rule["warningHigh"]:
        return "WARNING", "HIGH", rule["warningHigh"]
    if rule.get("alarmLow") is not None and value <= rule["alarmLow"]:
        return "ALARM", "LOW", rule["alarmLow"]
    if rule.get("warningLow") is not None and value <= rule["warningLow"]:
        return "WARNING", "LOW", rule["warningLow"]
    return "NORMAL", None, None


def _parse_event(event: dict, index: int, issues: list[dict]) -> dict | None:
    line = index + 1
    try:
        line = int(event.get("_line", line))
    except (TypeError, ValueError):
        pass
    if event.get("_parse_error"):
        add_issue(issues, "error", "INVALID_EVENT_JSON", str(event["_parse_error"]), line=line)
        return None
    event_type = as_id(event.get("eventType"))
    if not event_type:
        add_issue(issues, "error", "MISSING_EVENT_TYPE", "Monitoring event requires eventType.", line=line)
        return None
    if event_type not in ACCEPTED_EVENT_TYPES:
        add_issue(
            issues,
            "warning",
            "SKIPPED_EVENT_TYPE",
            f"Event type '{event_type}' is not handled by the monitoring processor.",
            line=line,
            eventType=event_type,
        )
        return None
    entity_type = event.get("entityType")
    entity_type = entity_type.strip() if isinstance(entity_type, str) else entity_type
    if entity_type and entity_type != "MONITOR_DEVICE":
        add_issue(
            issues,
            "warning",
            "SKIPPED_NON_MONITOR_DEVICE",
            f"entityType '{entity_type}' is not MONITOR_DEVICE.",
            line=line,
            entityType=entity_type,
        )
        return None
    if not entity_type:
        add_issue(
            issues,
            "warning",
            "ASSUMED_MONITOR_DEVICE",
            "entityType is missing; the event is processed as MONITOR_DEVICE.",
            line=line,
        )
    entity_id = as_id(event.get("entityId"))
    mine_id = as_id(event.get("mineId"))
    object_id = as_id(event.get("objectId"))
    if not entity_id:
        add_issue(issues, "error", "MISSING_ENTITY_ID", "Monitoring event requires entityId.", line=line)
    if not mine_id:
        add_issue(issues, "error", "MISSING_MINE_ID", "Monitoring event requires mineId.", line=line)
    if not object_id:
        add_issue(
            issues,
            "warning",
            "MISSING_OBJECT_ID",
            "Monitoring event has no objectId; metric evaluation continues but the "
            "event cannot be scene-bound.",
            line=line,
            entityId=entity_id,
        )
    if not entity_id or not mine_id:
        return None
    timestamp = event.get("sourceTimestamp")
    if not is_finite_number(timestamp) or float(timestamp) < 0:
        add_issue(
            issues,
            "error",
            "INVALID_SOURCE_TIMESTAMP",
            "sourceTimestamp must be a non-negative epoch-millisecond number.",
            line=line,
            entityId=entity_id,
        )
        return None
    sequence = event.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        add_issue(
            issues,
            "warning",
            "INVALID_SEQUENCE",
            "sequence is missing or invalid; ordering falls back to sourceTimestamp.",
            line=line,
            entityId=entity_id,
        )
        sequence = 0
    payload = event.get("payload")
    if not isinstance(payload, dict):
        add_issue(issues, "error", "MISSING_PAYLOAD", "Monitoring event requires a payload object.", line=line, entityId=entity_id)
        return None
    return {
        "line": line,
        "eventId": as_id(event.get("eventId")),
        "eventType": event_type,
        "entityId": entity_id,
        "mineId": mine_id,
        "objectId": object_id,
        "sourceTimestamp": float(timestamp),
        "sequence": sequence,
        "payload": payload,
        "deviceType": as_id(event.get("deviceType") or payload.get("deviceType")),
    }


def _resolve_device_type(parsed: dict, definitions: dict, issues: list[dict]) -> str | None:
    device_types = definitions["deviceTypes"]
    declared = parsed.get("deviceType")
    if declared:
        if declared not in device_types:
            add_issue(
                issues,
                "error",
                "UNKNOWN_DEVICE_TYPE",
                f"Device type '{declared}' is not defined in metrics.json.",
                line=parsed["line"],
                entityId=parsed["entityId"],
                deviceType=declared,
            )
            return None
        return declared

    metrics = parsed["payload"].get("metrics")
    codes = []
    if isinstance(metrics, list):
        for metric in metrics:
            if isinstance(metric, dict):
                code = as_id(metric.get("metricCode"))
                if code:
                    codes.append(code)
    codes_set = set(codes)
    candidates = [
        device_type
        for device_type, metric_map in device_types.items()
        if codes_set and codes_set.issubset(metric_map.keys())
    ]
    if len(candidates) == 1:
        add_issue(
            issues,
            "warning",
            "INFERRED_DEVICE_TYPE",
            f"deviceType is missing; inferred '{candidates[0]}' from metric codes "
            f"{sorted(codes_set)}. Store deviceType explicitly in the event.",
            line=parsed["line"],
            entityId=parsed["entityId"],
            deviceType=candidates[0],
        )
        return candidates[0]
    if len(candidates) > 1:
        add_issue(
            issues,
            "error",
            "AMBIGUOUS_DEVICE_TYPE",
            "deviceType is missing and metric codes match multiple device types: "
            + ", ".join(candidates),
            line=parsed["line"],
            entityId=parsed["entityId"],
        )
    else:
        add_issue(
            issues,
            "error",
            "UNKNOWN_DEVICE_TYPE",
            "deviceType is missing and metric codes do not match any device type.",
            line=parsed["line"],
            entityId=parsed["entityId"],
        )
    return None


def _check_threshold_against_definitions(config: dict, definitions: dict, issues: list[dict]) -> None:
    for rule in config["rules"]:
        metric_map = definitions["deviceTypes"].get(rule["deviceType"])
        metric = metric_map.get(rule["metricCode"]) if metric_map else None
        if metric is None:
            add_issue(
                issues,
                "warning",
                "THRESHOLD_METRIC_UNKNOWN",
                f"Threshold rule {rule['ruleId']} targets an undefined metric.",
                deviceType=rule["deviceType"],
                metricCode=rule["metricCode"],
            )
            continue
        if rule.get("unit") and metric.get("unit") and rule["unit"] != metric["unit"]:
            add_issue(
                issues,
                "warning",
                "THRESHOLD_UNIT_MISMATCH",
                f"Threshold unit '{rule['unit']}' differs from metric unit "
                f"'{metric['unit']}' for {rule['deviceType']}/{rule['metricCode']}.",
                deviceType=rule["deviceType"],
                metricCode=rule["metricCode"],
            )


def _alarm_event(alarm: dict, parsed: dict, action: str, status: str, **extra: Any) -> dict:
    payload = {
        "alarmId": alarm["alarmId"],
        "alarmType": "THRESHOLD",
        "alarmLevel": alarm["alarmLevel"],
        "metricCode": alarm["metricCode"],
        "currentValue": alarm["lastValue"],
        "threshold": alarm["threshold"],
        "thresholdVersion": alarm["thresholdVersion"],
        "direction": alarm["direction"],
        "unit": alarm.get("unit"),
        "status": status,
        "action": action,
        "message": extra.pop("message"),
        "source": "THRESHOLD_EVALUATION",
    }
    payload.update(extra)
    return {
        "eventType": "MONITOR_ALARM",
        "alarmId": alarm["alarmId"],
        "mineId": parsed["mineId"],
        "entityId": parsed["entityId"],
        "entityType": "MONITOR_DEVICE",
        "objectId": parsed["objectId"],
        "sourceTimestamp": int(parsed["sourceTimestamp"]),
        "sequence": parsed["sequence"],
        "payload": payload,
    }


def process_monitoring(
    metrics_data: Any,
    threshold_data: Any,
    events: list[dict],
    stale_after_ms: int = 300000,
) -> dict:
    """Evaluate monitoring events and return latest values, alarms and a report."""
    issues: list[dict] = []
    definitions, definition_issues = normalize_metric_definitions(metrics_data)
    issues.extend(definition_issues)
    thresholds, threshold_issues = normalize_thresholds(threshold_data)
    issues.extend(threshold_issues)
    _check_threshold_against_definitions(thresholds, definitions, issues)

    devices: dict[str, dict] = {}
    last_ordering: dict[str, tuple[float, int]] = {}
    active_alarms: dict[tuple[str, str], dict] = {}
    generated_alarms: list[dict] = []
    upstream_alarms: list[dict] = []
    alarm_events_output: list[dict] = []
    alarm_counters = {
        "created": 0,
        "cleared": 0,
        "escalated": 0,
        "deescalated": 0,
    }
    alarm_sequence = 0
    seen_upstream_alarm_ids: set[str] = set()
    event_counts: Counter = Counter()
    out_of_order = 0
    accepted_events = 0
    metric_updates = 0
    unknown_metrics = 0
    upstream_alarm_count = 0
    generated_alarm_event_count = 0

    def get_device(parsed: dict, device_type: str | None = None) -> dict:
        state = devices.get(parsed["entityId"])
        if state is None:
            state = {
                "entityId": parsed["entityId"],
                "mineId": parsed["mineId"],
                "objectId": parsed["objectId"],
                "deviceType": device_type,
                "online": None,
                "lastSourceTimestamp": None,
                "lastSequence": None,
                "lastEventId": None,
                "lastEventType": None,
                "metrics": {},
            }
            devices[parsed["entityId"]] = state
        state["mineId"] = parsed["mineId"]
        state["objectId"] = parsed["objectId"]
        if device_type:
            state["deviceType"] = device_type
        state["lastSourceTimestamp"] = int(parsed["sourceTimestamp"])
        state["lastSequence"] = parsed["sequence"]
        state["lastEventId"] = parsed["eventId"]
        state["lastEventType"] = parsed["eventType"]
        return state

    def clear_alarm(key: tuple[str, str], alarm: dict, parsed: dict, value: float) -> None:
        nonlocal generated_alarm_event_count
        alarm.update(
            {
                "lastValue": value,
                "updatedAt": int(parsed["sourceTimestamp"]),
                "status": "CLEARED",
                "recoveredAt": int(parsed["sourceTimestamp"]),
                "eventCount": alarm["eventCount"] + 1,
            }
        )
        event = _alarm_event(
            alarm,
            parsed,
            "CLEARED",
            "CLEARED",
            message=(
                f"{alarm['metricCode']} returned to normal at {value}"
                f"{(' ' + alarm['unit']) if alarm.get('unit') else ''}; alarm cleared."
            ),
        )
        generated_alarms.append(event)
        alarm_events_output.append(event)
        generated_alarm_event_count += 1
        alarm_counters["cleared"] += 1
        active_alarms.pop(key, None)

    def create_or_update_alarm(
        key: tuple[str, str],
        parsed: dict,
        device_type: str,
        metric: dict,
        severity: str,
        direction: str | None,
        threshold: float | None,
        rule: dict | None,
    ) -> None:
        nonlocal generated_alarm_event_count, alarm_sequence
        value = metric["value"]
        active = active_alarms.get(key)
        if active is None:
            alarm_sequence += 1
            alarm = {
                "alarmId": f"ALM-{alarm_sequence:06d}",
                "mineId": parsed["mineId"],
                "entityId": parsed["entityId"],
                "entityType": "MONITOR_DEVICE",
                "objectId": parsed["objectId"],
                "deviceType": device_type,
                "metricCode": metric["metricCode"],
                "alarmLevel": severity,
                "threshold": threshold,
                "direction": direction,
                "unit": metric.get("unit"),
                "thresholdVersion": rule.get("version") if rule else thresholds["version"],
                "triggeredAt": int(parsed["sourceTimestamp"]),
                "updatedAt": int(parsed["sourceTimestamp"]),
                "lastValue": value,
                "firstEventId": parsed["eventId"],
                "eventCount": 1,
                "status": "ACTIVE",
            }
            active_alarms[key] = alarm
            event = _alarm_event(
                alarm,
                parsed,
                "CREATED",
                "ACTIVE",
                message=(
                    f"{alarm['metricCode']} value {value}"
                    f"{(' ' + alarm['unit']) if alarm.get('unit') else ''} crossed "
                    f"{severity.lower()} {direction.lower() if direction else ''} "
                    f"threshold {threshold}."
                ),
            )
            generated_alarms.append(event)
            alarm_events_output.append(event)
            generated_alarm_event_count += 1
            alarm_counters["created"] += 1
            return

        previous_level = active["alarmLevel"]
        active.update(
            {
                "lastValue": value,
                "updatedAt": int(parsed["sourceTimestamp"]),
                "eventCount": active["eventCount"] + 1,
                "threshold": threshold,
                "direction": direction,
                "alarmLevel": severity,
            }
        )
        if severity == previous_level:
            return
        action = "ESCALATED" if ALARM_LEVELS.index(severity) > ALARM_LEVELS.index(previous_level) else "DEESCALATED"
        alarm_counters["escalated" if action == "ESCALATED" else "deescalated"] += 1
        event = _alarm_event(
            active,
            parsed,
            action,
            "ACTIVE",
            previousLevel=previous_level,
            message=(
                f"{active['metricCode']} threshold alarm changed from "
                f"{previous_level} to {severity} at value {value}."
            ),
        )
        generated_alarms.append(event)
        alarm_events_output.append(event)
        generated_alarm_event_count += 1

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            add_issue(issues, "error", "INVALID_EVENT", "Monitoring event must be a JSON object.", line=index + 1)
            continue
        parsed = _parse_event(event, index, issues)
        if parsed is None:
            continue
        event_counts[parsed["eventType"]] += 1
        entity_id = parsed["entityId"]
        previous = last_ordering.get(entity_id)
        if previous and (
            parsed["sourceTimestamp"] < previous[0]
            or (
                parsed["sourceTimestamp"] == previous[0]
                and parsed["sequence"] <= previous[1]
            )
        ):
            out_of_order += 1
            add_issue(
                issues,
                "warning",
                "OUT_OF_ORDER_IGNORED",
                f"sourceTimestamp {parsed['sourceTimestamp']} / sequence "
                f"{parsed['sequence']} is not newer than the accepted "
                f"{previous[0]} / {previous[1]}; the event is ignored and cannot "
                "regress device state or alarms.",
                line=parsed["line"],
                entityId=entity_id,
            )
            continue
        if previous and parsed["sourceTimestamp"] > previous[0] and parsed["sequence"] <= previous[1]:
            add_issue(
                issues,
                "warning",
                "SEQUENCE_REGRESSION",
                f"sequence {parsed['sequence']} does not increase over "
                f"{previous[1]}; check device reconnect or sequence reset.",
                line=parsed["line"],
                entityId=entity_id,
            )
        last_ordering[entity_id] = (parsed["sourceTimestamp"], parsed["sequence"])
        accepted_events += 1

        if parsed["eventType"] == "ENTITY_ONLINE":
            state = get_device(parsed)
            state["online"] = True
            continue
        if parsed["eventType"] == "ENTITY_OFFLINE":
            state = get_device(parsed)
            state["online"] = False
            continue

        if parsed["eventType"] == "MONITOR_ALARM":
            payload = parsed["payload"]
            alarm_id = as_id(payload.get("alarmId")) or parsed["eventId"]
            if not alarm_id:
                alarm_id = f"UP-{upstream_alarm_count + 1:06d}"
                add_issue(
                    issues,
                    "warning",
                    "MISSING_ALARM_ID",
                    "Upstream alarm has no alarmId or eventId; a local identifier "
                    "was assigned and deduplication is limited.",
                    line=parsed["line"],
                    entityId=entity_id,
                )
            if alarm_id in seen_upstream_alarm_ids:
                add_issue(
                    issues,
                    "warning",
                    "DUPLICATE_ALARM_EVENT",
                    f"Upstream alarm '{alarm_id}' was already processed; duplicate suppressed.",
                    line=parsed["line"],
                    entityId=entity_id,
                    alarmId=alarm_id,
                )
                continue
            seen_upstream_alarm_ids.add(alarm_id)
            state = get_device(parsed)
            if isinstance(payload.get("online"), bool):
                state["online"] = payload["online"]
            elif state["online"] is None:
                state["online"] = True
            normalized_payload = dict(payload)
            normalized_payload["alarmId"] = alarm_id
            normalized_payload.setdefault("alarmType", "UPSTREAM")
            normalized_payload.setdefault("status", "ACTIVE")
            normalized_payload["source"] = "UPSTREAM"
            if parsed["eventId"]:
                normalized_payload["sourceEventId"] = parsed["eventId"]
            record = {
                "eventType": "MONITOR_ALARM",
                "alarmId": alarm_id,
                "mineId": parsed["mineId"],
                "entityId": entity_id,
                "entityType": "MONITOR_DEVICE",
                "objectId": parsed["objectId"],
                "sourceTimestamp": int(parsed["sourceTimestamp"]),
                "sequence": parsed["sequence"],
                "payload": normalized_payload,
            }
            upstream_alarms.append(record)
            alarm_events_output.append(record)
            upstream_alarm_count += 1
            continue

        # MONITOR_VALUE_UPDATE
        device_type = _resolve_device_type(parsed, definitions, issues)
        if device_type is None:
            continue
        metrics = parsed["payload"].get("metrics")
        if not isinstance(metrics, list) or not metrics:
            add_issue(
                issues,
                "error",
                "INVALID_METRICS",
                "MONITOR_VALUE_UPDATE payload requires a non-empty metrics array.",
                line=parsed["line"],
                entityId=entity_id,
                deviceType=device_type,
            )
            continue
        state = get_device(parsed, device_type)
        online = parsed["payload"].get("online")
        if isinstance(online, bool):
            state["online"] = online
        elif online is not None:
            add_issue(
                issues,
                "warning",
                "INVALID_ONLINE",
                "payload.online must be a boolean; the previous online state is kept.",
                line=parsed["line"],
                entityId=entity_id,
            )
        elif state["online"] is None:
            state["online"] = True

        # Validate the whole array before updating state so one bad metric does
        # not silently discard the rest of a multi-metric event.
        parsed_metrics: list[dict] = []
        metric_codes_seen: set[str] = set()
        for metric_index, raw_metric in enumerate(metrics):
            metric_context = {
                "line": parsed["line"],
                "entityId": entity_id,
                "deviceType": device_type,
                "metricIndex": metric_index,
            }
            if not isinstance(raw_metric, dict):
                add_issue(issues, "error", "INVALID_METRIC", "Metric entry must be an object.", **metric_context)
                continue
            metric_code = as_id(raw_metric.get("metricCode"))
            if not metric_code:
                add_issue(issues, "error", "MISSING_METRIC_CODE", "Metric requires metricCode.", **metric_context)
                continue
            metric_context["metricCode"] = metric_code
            if metric_code in metric_codes_seen:
                add_issue(
                    issues,
                    "error",
                    "DUPLICATE_METRIC_CODE",
                    f"Metric '{metric_code}' appears more than once in the same event.",
                    **metric_context,
                )
                continue
            metric_codes_seen.add(metric_code)
            definition = definitions["deviceTypes"].get(device_type, {}).get(metric_code)
            if definition is None:
                unknown_metrics += 1
                add_issue(
                    issues,
                    "error",
                    "UNKNOWN_METRIC",
                    f"Metric '{metric_code}' is not defined for device type '{device_type}'.",
                    **metric_context,
                )
                continue
            value = raw_metric.get("value")
            if not is_finite_number(value):
                add_issue(issues, "error", "INVALID_METRIC_VALUE", "Metric value must be a finite number.", **metric_context)
                continue
            unit = raw_metric.get("unit")
            if unit is not None and (not isinstance(unit, str) or not unit.strip()):
                add_issue(issues, "warning", "INVALID_METRIC_UNIT", "Metric unit must be a non-empty string when present.", **metric_context)
                unit = None
            if unit and definition.get("unit") and unit != definition["unit"]:
                add_issue(
                    issues,
                    "warning",
                    "UNIT_MISMATCH",
                    f"Event unit '{unit}' differs from configured unit "
                    f"'{definition['unit']}'.",
                    **metric_context,
                )
            if definition.get("min") is not None and value < definition["min"]:
                add_issue(
                    issues,
                    "warning",
                    "VALUE_OUTSIDE_DEFINITION_RANGE",
                    f"Value {value} is below configured minimum {definition['min']}.",
                    **metric_context,
                )
            if definition.get("max") is not None and value > definition["max"]:
                add_issue(
                    issues,
                    "warning",
                    "VALUE_OUTSIDE_DEFINITION_RANGE",
                    f"Value {value} is above configured maximum {definition['max']}.",
                    **metric_context,
                )
            rule = lookup_threshold(thresholds, device_type, entity_id, metric_code)
            if rule is None:
                severity, direction, threshold = "NORMAL", None, None
            else:
                severity, direction, threshold = evaluate_threshold(float(value), rule)
            parsed_metrics.append(
                {
                    "metricCode": metric_code,
                    "definition": definition,
                    "value": float(value),
                    "unit": unit or definition.get("unit"),
                    "sourceStatus": raw_metric.get("status"),
                    "severity": severity,
                    "direction": direction,
                    "threshold": threshold,
                    "rule": rule,
                }
            )

        for metric in parsed_metrics:
            metric_updates += 1
            rule = metric["rule"]
            state["metrics"][metric["metricCode"]] = {
                "metricCode": metric["metricCode"],
                "metricName": metric["definition"].get("metricName"),
                "value": metric["value"],
                "unit": metric["unit"],
                "sourceStatus": metric["sourceStatus"],
                "status": metric["severity"],
                "direction": metric["direction"],
                "threshold": metric["threshold"],
                "thresholdVersion": rule.get("version") if rule else None,
                "sourceTimestamp": int(parsed["sourceTimestamp"]),
                "sequence": parsed["sequence"],
            }
            key = (entity_id, metric["metricCode"])
            if metric["severity"] in ALARM_LEVELS:
                create_or_update_alarm(
                    key,
                    parsed,
                    device_type,
                    metric,
                    metric["severity"],
                    metric["direction"],
                    metric["threshold"],
                    rule,
                )
            else:
                active = active_alarms.get(key)
                if active is not None:
                    clear_alarm(key, active, parsed, metric["value"])

    monitored_devices = [state for state in devices.values() if state["metrics"]]
    reference_timestamp = max(
        (state["lastSourceTimestamp"] for state in monitored_devices),
        default=None,
    )
    stale_devices = 0
    for state in monitored_devices:
        if state["online"] is False:
            status = "OFFLINE"
        elif (
            reference_timestamp is not None
            and state["lastSourceTimestamp"] is not None
            and reference_timestamp - state["lastSourceTimestamp"] > stale_after_ms
        ):
            status = "STALE"
            stale_devices += 1
            add_issue(
                issues,
                "warning",
                "DEVICE_STALE",
                f"Device '{state['entityId']}' has no update for "
                f"{reference_timestamp - state['lastSourceTimestamp']} ms "
                f"(threshold {stale_after_ms} ms).",
                entityId=state["entityId"],
                lastSourceTimestamp=state["lastSourceTimestamp"],
            )
        else:
            status = "ONLINE"
        state["status"] = status

    online_devices = sum(1 for state in monitored_devices if state["status"] == "ONLINE")
    offline_devices = sum(1 for state in monitored_devices if state["status"] == "OFFLINE")

    latest_values = []
    for state in sorted(monitored_devices, key=lambda item: item["entityId"]):
        active_for_device = [
            {
                "alarmId": alarm["alarmId"],
                "metricCode": alarm["metricCode"],
                "alarmLevel": alarm["alarmLevel"],
                "threshold": alarm["threshold"],
                "lastValue": alarm["lastValue"],
                "triggeredAt": alarm["triggeredAt"],
                "updatedAt": alarm["updatedAt"],
            }
            for alarm in active_alarms.values()
            if alarm["entityId"] == state["entityId"]
        ]
        if any(alarm["alarmLevel"] == "ALARM" for alarm in active_for_device):
            alarm_status = "ALARM"
        elif active_for_device:
            alarm_status = "WARNING"
        else:
            alarm_status = "NORMAL"
        latest_values.append(
            {
                "entityId": state["entityId"],
                "mineId": state["mineId"],
                "objectId": state["objectId"],
                "deviceType": state["deviceType"],
                "status": state["status"],
                "online": state["online"] is not False,
                "alarmStatus": alarm_status,
                "lastSourceTimestamp": state["lastSourceTimestamp"],
                "lastSequence": state["lastSequence"],
                "lastEventId": state["lastEventId"],
                "lastEventType": state["lastEventType"],
                "metrics": [
                    {
                        "metricCode": metric["metricCode"],
                        "metricName": metric["metricName"],
                        "value": metric["value"],
                        "unit": metric["unit"],
                        "status": metric["status"],
                        "sourceStatus": metric["sourceStatus"],
                        "direction": metric["direction"],
                        "threshold": metric["threshold"],
                        "thresholdVersion": metric["thresholdVersion"],
                        "sourceTimestamp": metric["sourceTimestamp"],
                        "sequence": metric["sequence"],
                    }
                    for metric in sorted(
                        state["metrics"].values(), key=lambda item: item["metricCode"]
                    )
                ],
                "activeAlarms": sorted(
                    active_for_device, key=lambda item: item["metricCode"]
                ),
            }
        )

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    status = "FAIL" if error_count else "PASS_WITH_WARNINGS" if warning_count else "PASS"

    active_alarm_summary = [
        {
            "alarmId": alarm["alarmId"],
            "entityId": alarm["entityId"],
            "metricCode": alarm["metricCode"],
            "alarmLevel": alarm["alarmLevel"],
            "threshold": alarm["threshold"],
            "lastValue": alarm["lastValue"],
            "triggeredAt": alarm["triggeredAt"],
            "eventCount": alarm["eventCount"],
        }
        for alarm in sorted(active_alarms.values(), key=lambda item: (item["entityId"], item["metricCode"]))
    ]
    device_status = [
        {
            "entityId": item["entityId"],
            "deviceType": item["deviceType"],
            "status": item["status"],
            "alarmStatus": item["alarmStatus"],
            "lastSourceTimestamp": item["lastSourceTimestamp"],
            "metricCount": len(item["metrics"]),
        }
        for item in latest_values
    ]

    report = {
        "skill": "mine-safety-monitoring",
        "version": "v0.1",
        "status": status,
        "summary": {
            "events_total": len(events),
            "events_accepted": accepted_events,
            "event_types": dict(sorted(event_counts.items())),
            "devices_monitored": len(monitored_devices),
            "online_devices": online_devices,
            "offline_devices": offline_devices,
            "stale_devices": stale_devices,
            "metric_updates": metric_updates,
            "unknown_metrics": unknown_metrics,
            "out_of_order_ignored": out_of_order,
            "threshold_version": thresholds["version"],
            "threshold_rules": len(thresholds["rules"]),
            "alarms": {
                "generated_events": generated_alarm_event_count,
                "created": alarm_counters["created"],
                "cleared": alarm_counters["cleared"],
                "escalated": alarm_counters["escalated"],
                "deescalated": alarm_counters["deescalated"],
                "active": len(active_alarms),
                "upstream": upstream_alarm_count,
            },
            "errors": error_count,
            "warnings": warning_count,
        },
        "devices": device_status,
        "active_alarms": active_alarm_summary,
        "issues": issues,
    }

    return {
        "report": report,
        "latest_values": {
            "skill": "mine-safety-monitoring",
            "version": "v0.1",
            "staleAfterMs": stale_after_ms,
            "referenceTimestamp": reference_timestamp,
            "devices": latest_values,
        },
        "alarms": alarm_events_output,
        "generated_alarms": generated_alarms,
        "upstream_alarms": upstream_alarms,
    }


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    alarms = summary["alarms"]
    lines = [
        "# Safety Monitoring Report",
        "",
        f"- **Status**: {report['status']}",
        f"- **Events**: {summary['events_total']} "
        f"(accepted {summary['events_accepted']})",
        f"- **Devices**: {summary['devices_monitored']} "
        f"(online {summary['online_devices']}, offline {summary['offline_devices']}, "
        f"stale {summary['stale_devices']})",
        f"- **Metric updates**: {summary['metric_updates']}",
        f"- **Threshold version**: {summary['threshold_version']} "
        f"({summary['threshold_rules']} rules)",
        f"- **Alarms**: active {alarms['active']}, created {alarms['created']}, "
        f"cleared {alarms['cleared']}, escalated {alarms['escalated']}, "
        f"upstream {alarms['upstream']}",
        f"- **Errors**: {summary['errors']}, **warnings**: {summary['warnings']}",
        "",
        "## Devices",
        "",
    ]
    if report["devices"]:
        lines.extend(
            [
                "| Device | Type | Status | Alarm | Last source time | Metrics |",
                "|---|---|---|---|---|---|",
            ]
        )
        for device in report["devices"]:
            lines.append(
                f"| {device['entityId']} | {device['deviceType'] or '-'} | "
                f"{device['status']} | {device['alarmStatus']} | "
                f"{device['lastSourceTimestamp']} | {device['metricCount']} |"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Active alarms", ""])
    if report["active_alarms"]:
        lines.extend(
            [
                "| Alarm | Device | Metric | Level | Threshold | Value | Triggered |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for alarm in report["active_alarms"]:
            lines.append(
                f"| {alarm['alarmId']} | {alarm['entityId']} | {alarm['metricCode']} | "
                f"{alarm['alarmLevel']} | {alarm['threshold']} | {alarm['lastValue']} | "
                f"{alarm['triggeredAt']} |"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Issues", ""])
    if report["issues"]:
        lines.extend(["| Severity | Code | Line | Device | Message |", "|---|---|---|---|---|"])
        for issue in report["issues"]:
            message = str(issue.get("message", "")).replace("|", "\\|")
            lines.append(
                f"| {issue['severity']} | {issue['code']} | {issue.get('line', '-')} | "
                f"{issue.get('entityId', '-')} | {message} |"
            )
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- v0.1 evaluates files only; live ThingLinks/Spring Boot telemetry "
            "ingestion and WebSocket alarm publication are future work.",
            "- Thresholds come only from `thresholds.json`; no safety threshold is "
            "hardcoded in this script.",
            "- Online/offline/stale reflects the processed stream reference time; "
            "`STALE` is never presented as normal.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(result: dict, out_dir: str | Path) -> dict[str, str]:
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_path = output_dir / "latest_values.json"
    alarms_path = output_dir / "alarms.jsonl"
    report_path = output_dir / "monitoring_report.json"
    markdown_path = output_dir / "monitoring_report.md"

    latest_path.write_text(
        json.dumps(result["latest_values"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with alarms_path.open("w", encoding="utf-8") as fh:
        for alarm in result["alarms"]:
            fh.write(json.dumps(alarm, ensure_ascii=False) + "\n")
    report_path.write_text(
        json.dumps(result["report"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(result["report"]), encoding="utf-8")

    return {
        "latest_values": str(latest_path),
        "alarms": str(alarms_path),
        "report_json": str(report_path),
        "report_md": str(markdown_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate safety monitoring metrics, thresholds and alarms."
    )
    parser.add_argument("metrics", help="metrics.json (device type -> metric definitions)")
    parser.add_argument("thresholds", help="thresholds.json")
    parser.add_argument("events", help="events.jsonl (MONITOR_VALUE_UPDATE / MONITOR_ALARM)")
    parser.add_argument("--out-dir", default="monitoring_output", help="Output directory")
    parser.add_argument(
        "--stale-after-ms",
        type=int,
        default=300000,
        help="Mark online devices stale after this many milliseconds without data",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0; the report still records evaluation errors",
    )
    args = parser.parse_args(argv)
    if args.stale_after_ms <= 0:
        parser.error("--stale-after-ms must be positive")

    metrics_data = read_json(args.metrics)
    threshold_data = read_json(args.thresholds)
    events = read_jsonl(args.events)
    result = process_monitoring(
        metrics_data, threshold_data, events, stale_after_ms=args.stale_after_ms
    )
    paths = write_outputs(result, args.out_dir)
    summary = result["report"]["summary"]
    alarms = summary["alarms"]

    print(
        f"{result['report']['status']}: {summary['devices_monitored']} devices "
        f"({summary['online_devices']} online, {summary['offline_devices']} offline, "
        f"{summary['stale_devices']} stale), {summary['metric_updates']} metric updates, "
        f"active alarms {alarms['active']}, {summary['errors']} errors, "
        f"{summary['warnings']} warnings"
    )
    print(
        f"Reports: {paths['latest_values']}, {paths['alarms']}, "
        f"{paths['report_json']}, {paths['report_md']}",
        file=sys.stderr,
    )

    if summary["errors"] and not args.no_fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
