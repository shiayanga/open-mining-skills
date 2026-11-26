#!/usr/bin/env python3
"""Validate device mappings and digital-twin WebSocket events.

v0.1 validates the file contract: device-to-entity mapping, required event
envelope fields, position quality and coordinate systems, dynamic monitoring
metric arrays, event deduplication and per-entity timestamp ordering. A live
Spring Boot / ThingLinks adapter and WebSocket subscriber are future work.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ENTITY_TYPES = {"PERSON", "MONITOR_DEVICE", "MACHINERY", "INFRASTRUCTURE"}
POSITION_QUALITIES = {"VALID", "LOW_ACCURACY", "STALE", "INVALID"}
REQUIRED_FIELDS = (
    "eventType",
    "mineId",
    "entityId",
    "entityType",
    "objectId",
    "sourceTimestamp",
    "sequence",
    "payload",
)
DEVICE_EVENT_TYPES = {
    "ENTITY_POSITION_UPDATE",
    "ENTITY_STATUS_UPDATE",
    "ENTITY_PROPERTY_UPDATE",
    "ENTITY_ALARM",
    "ENTITY_ONLINE",
    "ENTITY_OFFLINE",
    "ENTITY_GEOFENCE_EVENT",
    "PERSONNEL_ENTER_AREA",
    "PERSONNEL_LEAVE_AREA",
    "MONITOR_VALUE_UPDATE",
    "MONITOR_ALARM",
    "MACHINERY_STATUS_UPDATE",
    "MACHINERY_ALARM",
}
KNOWN_EVENT_TYPES = DEVICE_EVENT_TYPES | {
    "ENTITY_BINDING_UPDATE",
    "SCENE_LAYER_UPDATE",
    "SCENE_OBJECT_UPDATE",
}
MAPPING_WRAPPER_KEYS = ("devices", "mappings", "deviceMapping", "device_mappings")


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


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_finite_number(value: Any) -> bool:
    return is_number(value) and math.isfinite(float(value))


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
    """Read JSON Lines, keeping malformed lines as parse-error records."""
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


def _mapping_entries(data: Any, issues: list[dict]) -> list[dict]:
    if isinstance(data, list):
        raw_entries = data
    elif isinstance(data, dict):
        wrapper = next(
            (data[key] for key in MAPPING_WRAPPER_KEYS if key in data), None
        )
        if isinstance(wrapper, list):
            raw_entries = wrapper
        elif isinstance(wrapper, dict):
            raw_entries = [
                {"sourceDeviceId": source_id, **(value if isinstance(value, dict) else {"entityId": value})}
                for source_id, value in wrapper.items()
            ]
        else:
            raw_entries = [
                {"sourceDeviceId": source_id, **(value if isinstance(value, dict) else {"entityId": value})}
                for source_id, value in data.items()
            ]
    else:
        add_issue(issues, "error", "INVALID_MAPPING", "Device mapping must be a list or object.")
        return []

    entries: list[dict] = []
    for index, raw in enumerate(raw_entries):
        context = {"recordType": "deviceMapping", "recordIndex": index}
        if not isinstance(raw, dict):
            add_issue(issues, "error", "INVALID_MAPPING_ENTRY", "Mapping entry must be an object.", **context)
            continue
        source_id = as_id(
            raw.get("sourceDeviceId") or raw.get("sourceId") or raw.get("deviceId")
        )
        entity_id = as_id(
            raw.get("entityId") or raw.get("twinEntityId") or raw.get("twinEntityID")
        )
        entity_type = raw.get("entityType") or raw.get("twinEntityType") or raw.get("type")
        entity_type = entity_type.strip() if isinstance(entity_type, str) else entity_type
        mine_id = as_id(raw.get("mineId"))
        if not source_id:
            add_issue(issues, "error", "MISSING_SOURCE_DEVICE_ID", "Mapping requires a sourceDeviceId.", **context)
        if not entity_id:
            add_issue(issues, "error", "MISSING_ENTITY_ID", "Mapping requires a twin entityId.", **context, sourceDeviceId=source_id)
        if not entity_type:
            add_issue(
                issues,
                "warning",
                "MISSING_ENTITY_TYPE",
                "Mapping has no entityType; event entityType cannot be cross-checked.",
                **context,
                sourceDeviceId=source_id,
                entityId=entity_id,
            )
        elif entity_type not in ENTITY_TYPES:
            add_issue(
                issues,
                "warning",
                "UNKNOWN_ENTITY_TYPE",
                f"Mapping entityType '{entity_type}' is outside the v0.1 catalog.",
                **context,
                sourceDeviceId=source_id,
                entityId=entity_id,
            )
        if raw.get("mineId") is not None and not mine_id:
            add_issue(issues, "error", "EMPTY_MINE_ID", "Mapping mineId must be non-empty when present.", **context, sourceDeviceId=source_id)
        if source_id and entity_id:
            entries.append(
                {
                    "sourceDeviceId": source_id,
                    "entityId": entity_id,
                    "entityType": entity_type,
                    "mineId": mine_id,
                }
            )
    return entries


def normalize_mapping(data: Any) -> dict:
    issues: list[dict] = []
    entries = _mapping_entries(data, issues)
    by_source: dict[str, dict] = {}
    by_entity: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        source_id = entry["sourceDeviceId"]
        if source_id in by_source:
            add_issue(
                issues,
                "error",
                "DUPLICATE_SOURCE_DEVICE",
                f"Source device '{source_id}' is mapped more than once.",
                recordType="deviceMapping",
                sourceDeviceId=source_id,
            )
            continue
        by_source[source_id] = entry
        by_entity[entry["entityId"]].append(entry)
    if not entries:
        add_issue(issues, "error", "NO_DEVICE_MAPPINGS", "Device mapping contains no usable entries.")
    return {
        "entries": entries,
        "by_source": by_source,
        "by_entity": dict(by_entity),
        "issues": issues,
    }


def _source_device_ids(event: dict, payload: dict) -> list[str]:
    found: list[str] = []
    for value in (
        event.get("sourceDeviceId"),
        payload.get("sourceDeviceId"),
        event.get("deviceId"),
        payload.get("deviceId"),
    ):
        source_id = as_id(value)
        if source_id and source_id not in found:
            found.append(source_id)
    return found


def _validate_position_payload(
    payload: dict,
    issues: list[dict],
    event_issue,
    line: int,
    context: dict,
) -> None:
    position = payload.get("position")
    if not isinstance(position, dict):
        event_issue("error", "MISSING_POSITION", "Position event payload requires a position object.", line=line, field="payload.position", **context)
        return
    for axis in ("x", "y", "z"):
        if not is_finite_number(position.get(axis)):
            event_issue(
                "error",
                "INVALID_POSITION",
                f"position.{axis} must be a finite number.",
                line=line,
                field=f"payload.position.{axis}",
                **context,
            )
    if as_id(position.get("coordinateSystemId")) is None:
        event_issue(
            "error",
            "MISSING_COORDINATE_SYSTEM",
            "Position requires payload.position.coordinateSystemId; coordinates "
            "must never be interpreted without a declared system.",
            line=line,
            field="payload.position.coordinateSystemId",
            **context,
        )
    quality = payload.get("positionQuality")
    if quality is None:
        event_issue(
            "error",
            "MISSING_POSITION_QUALITY",
            "ENTITY_POSITION_UPDATE requires payload.positionQuality.",
            line=line,
            field="payload.positionQuality",
            **context,
        )
    elif quality not in POSITION_QUALITIES:
        event_issue(
            "error",
            "INVALID_POSITION_QUALITY",
            f"positionQuality must be one of {sorted(POSITION_QUALITIES)}.",
            line=line,
            field="payload.positionQuality",
            **context,
        )
    orientation = payload.get("orientation")
    if orientation is not None:
        if not isinstance(orientation, dict):
            event_issue("error", "INVALID_ORIENTATION", "orientation must be an object.", line=line, field="payload.orientation", **context)
        else:
            for axis in ("heading", "pitch", "roll"):
                if axis in orientation and not is_finite_number(orientation[axis]):
                    event_issue(
                        "error",
                        "INVALID_ORIENTATION",
                        f"orientation.{axis} must be a finite number.",
                        line=line,
                        field=f"payload.orientation.{axis}",
                        **context,
                    )
    if "speed" in payload and not is_finite_number(payload["speed"]):
        event_issue("error", "INVALID_SPEED", "speed must be a finite number when present.", line=line, field="payload.speed", **context)


def _validate_monitor_payload(
    payload: dict,
    issues: list[dict],
    event_issue,
    line: int,
    context: dict,
) -> None:
    metrics = payload.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        event_issue(
            "error",
            "INVALID_METRICS",
            "MONITOR_VALUE_UPDATE payload requires a non-empty metrics array.",
            line=line,
            field="payload.metrics",
            **context,
        )
        return
    seen: set[str] = set()
    for metric_index, metric in enumerate(metrics):
        metric_context = {**context, "metricIndex": metric_index}
        if not isinstance(metric, dict):
            event_issue(
                "error",
                "INVALID_METRIC",
                "Each metric entry must be an object.",
                line=line,
                field=f"payload.metrics[{metric_index}]",
                **metric_context,
            )
            continue
        code = as_id(metric.get("metricCode"))
        if not code:
            event_issue(
                "error",
                "MISSING_METRIC_CODE",
                "Metric requires a non-empty metricCode.",
                line=line,
                field=f"payload.metrics[{metric_index}].metricCode",
                **metric_context,
            )
        elif code in seen:
            event_issue(
                "error",
                "DUPLICATE_METRIC_CODE",
                f"Metric '{code}' appears more than once in the same event.",
                line=line,
                field="payload.metrics",
                metricCode=code,
                **context,
            )
        else:
            seen.add(code)
        if not is_finite_number(metric.get("value")):
            event_issue(
                "error",
                "INVALID_METRIC_VALUE",
                "Metric value must be a finite number.",
                line=line,
                field=f"payload.metrics[{metric_index}].value",
                metricCode=code,
                **context,
            )
        unit = metric.get("unit")
        if unit is not None and (not isinstance(unit, str) or not unit.strip()):
            event_issue(
                "warning",
                "INVALID_METRIC_UNIT",
                "Metric unit must be a non-empty string when present.",
                line=line,
                field=f"payload.metrics[{metric_index}].unit",
                metricCode=code,
                **context,
            )
        elif unit is None:
            event_issue(
                "warning",
                "MISSING_METRIC_UNIT",
                "Metric has no unit; store the source unit with each value.",
                line=line,
                field=f"payload.metrics[{metric_index}].unit",
                metricCode=code,
                **context,
            )
        status = metric.get("status")
        if status is not None and (not isinstance(status, str) or not status.strip()):
            event_issue(
                "warning",
                "INVALID_METRIC_STATUS",
                "Metric status must be a non-empty string when present.",
                line=line,
                field=f"payload.metrics[{metric_index}].status",
                metricCode=code,
                **context,
            )
        elif status is None:
            event_issue(
                "warning",
                "MISSING_METRIC_STATUS",
                "Metric has no source status.",
                line=line,
                field=f"payload.metrics[{metric_index}].status",
                metricCode=code,
                **context,
            )
    online = payload.get("online")
    if online is not None and not isinstance(online, bool):
        event_issue("error", "INVALID_ONLINE", "payload.online must be a boolean.", line=line, field="payload.online", **context)


def _validate_alarm_payload(
    payload: dict,
    issues: list[dict],
    event_issue,
    line: int,
    context: dict,
) -> None:
    alarm_id = as_id(payload.get("alarmId"))
    if not alarm_id:
        event_issue(
            "warning",
            "MISSING_ALARM_ID",
            "MONITOR_ALARM should carry payload.alarmId for deduplication.",
            line=line,
            field="payload.alarmId",
            **context,
        )
    alarm_level = payload.get("alarmLevel")
    if alarm_level is not None and (not isinstance(alarm_level, str) or not alarm_level.strip()):
        event_issue("warning", "INVALID_ALARM_LEVEL", "alarmLevel must be a non-empty string.", line=line, field="payload.alarmLevel", **context)
    for field in ("currentValue", "threshold"):
        if field in payload and not is_finite_number(payload[field]):
            event_issue("error", "INVALID_ALARM_VALUE", f"payload.{field} must be a finite number.", line=line, field=f"payload.{field}", **context)


def validate_events(mapping_data: Any, events: list[dict]) -> dict:
    """Validate a device mapping and a list of unified twin events."""
    issues: list[dict] = []
    mapping = normalize_mapping(mapping_data)
    issues.extend(mapping["issues"])

    latest_by_key: dict[tuple[str, str], dict] = {}
    event_type_counts: Counter = Counter()
    quality_counts: Counter = Counter()
    line_errors: set[int] = set()
    seen_event_ids: dict[str, int] = {}
    unknown_device_ids: set[str] = set()
    valid_events = 0

    for index, raw_event in enumerate(events):
        line = int(raw_event.get("_line", index + 1)) if isinstance(raw_event, dict) else index + 1

        def event_issue(severity: str, code: str, message: str, **context: Any) -> None:
            context["line"] = line
            add_issue(issues, severity, code, message, **context)
            if severity == "error":
                line_errors.add(line)

        if not isinstance(raw_event, dict):
            event_issue("error", "INVALID_EVENT", "Event must be a JSON object.")
            continue
        if raw_event.get("_parse_error"):
            event_issue("error", "INVALID_EVENT_JSON", str(raw_event["_parse_error"]))
            continue

        payload = raw_event.get("payload")
        payload_dict = payload if isinstance(payload, dict) else {}
        event_type = raw_event.get("eventType")
        event_type_id = as_id(event_type)
        event_context = {
            "eventId": as_id(raw_event.get("eventId")),
            "eventType": event_type_id,
            "entityId": as_id(raw_event.get("entityId")),
            "entityType": raw_event.get("entityType"),
            "objectId": as_id(raw_event.get("objectId")),
        }

        missing_required = False
        for field in REQUIRED_FIELDS:
            value = raw_event.get(field)
            if field == "payload":
                if not isinstance(value, dict):
                    event_issue(
                        "error",
                        "INVALID_FIELD",
                        "payload must be a JSON object.",
                        field="payload",
                        **event_context,
                    )
                    missing_required = True
                continue
            if field == "sourceTimestamp":
                if not is_finite_number(value) or float(value) < 0:
                    event_issue(
                        "error",
                        "INVALID_FIELD",
                        "sourceTimestamp must be a non-negative epoch-millisecond number.",
                        field=field,
                        **event_context,
                    )
                    missing_required = True
                continue
            if field == "sequence":
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    event_issue(
                        "error",
                        "INVALID_FIELD",
                        "sequence must be a non-negative integer.",
                        field=field,
                        **event_context,
                    )
                    missing_required = True
                continue
            if field == "entityType":
                if not isinstance(value, str) or not value.strip():
                    event_issue("error", "MISSING_FIELD", "entityType is required.", field=field, **event_context)
                    missing_required = True
                elif value.strip() not in ENTITY_TYPES:
                    event_issue(
                        "warning",
                        "UNKNOWN_ENTITY_TYPE",
                        f"entityType '{value.strip()}' is outside the v0.1 catalog.",
                        field=field,
                        **event_context,
                    )
                event_context["entityType"] = value.strip() if isinstance(value, str) else value
                continue
            if field == "eventType":
                if not isinstance(value, str) or not value.strip():
                    event_issue("error", "MISSING_FIELD", "eventType is required.", field=field, **event_context)
                    missing_required = True
                else:
                    event_context["eventType"] = value.strip()
                continue
            if as_id(value) is None:
                event_issue(
                    "error",
                    "MISSING_FIELD",
                    f"{field} is required and must be non-empty.",
                    field=field,
                    **event_context,
                )
                missing_required = True

        if event_type_id:
            event_type_counts[event_type_id] += 1
            if event_type_id not in KNOWN_EVENT_TYPES:
                event_issue(
                    "warning",
                    "UNKNOWN_EVENT_TYPE",
                    f"Event type '{event_type_id}' is not in the v0.1 catalog.",
                    **event_context,
                )

        event_id = as_id(raw_event.get("eventId"))
        duplicate_event = False
        if not event_id:
            event_issue(
                "warning",
                "MISSING_EVENT_ID",
                "eventId is recommended for deduplication.",
                field="eventId",
                **event_context,
            )
        elif event_id in seen_event_ids:
            duplicate_event = True
            event_issue(
                "error",
                "DUPLICATE_EVENT_ID",
                f"eventId '{event_id}' was already seen on line {seen_event_ids[event_id]} "
                "and is suppressed from the latest snapshot.",
                field="eventId",
                **event_context,
            )
        else:
            seen_event_ids[event_id] = line

        entity_id = as_id(raw_event.get("entityId"))
        mine_id = as_id(raw_event.get("mineId"))
        entity_type = raw_event.get("entityType")
        entity_type = entity_type.strip() if isinstance(entity_type, str) else entity_type

        # Resolve the source device before event-specific checks.
        source_ids = _source_device_ids(raw_event, payload_dict)
        if len(source_ids) > 1:
            event_issue(
                "error",
                "SOURCE_DEVICE_CONFLICT",
                "Event declares conflicting source device IDs: " + ", ".join(source_ids),
                **event_context,
            )
        source_id = source_ids[0] if source_ids else None
        mapping_entry = mapping["by_source"].get(source_id) if source_id else None
        if source_id and not mapping_entry:
            unknown_device_ids.add(source_id)
            event_issue(
                "error",
                "UNKNOWN_DEVICE",
                f"Source device '{source_id}' is not present in device_mapping.",
                sourceDeviceId=source_id,
                **event_context,
            )
        elif mapping_entry:
            if entity_id and mapping_entry["entityId"] != entity_id:
                event_issue(
                    "error",
                    "DEVICE_ENTITY_MISMATCH",
                    f"Device '{source_id}' maps to entity '{mapping_entry['entityId']}', "
                    f"but the event uses entity '{entity_id}'.",
                    sourceDeviceId=source_id,
                    **event_context,
                )
            if (
                mapping_entry.get("entityType")
                and entity_type
                and mapping_entry["entityType"] != entity_type
            ):
                event_issue(
                    "error",
                    "DEVICE_ENTITY_TYPE_MISMATCH",
                    f"Device '{source_id}' maps to entity type "
                    f"'{mapping_entry['entityType']}', but the event uses '{entity_type}'.",
                    sourceDeviceId=source_id,
                    **event_context,
                )
            if mapping_entry.get("mineId") and mine_id and mapping_entry["mineId"] != mine_id:
                event_issue(
                    "error",
                    "DEVICE_MINE_MISMATCH",
                    f"Device '{source_id}' belongs to mine '{mapping_entry['mineId']}', "
                    f"but the event uses mine '{mine_id}'.",
                    sourceDeviceId=source_id,
                    **event_context,
                )
        elif event_type_id in DEVICE_EVENT_TYPES and entity_id:
            candidates = mapping["by_entity"].get(entity_id, [])
            if not candidates:
                unknown_device_ids.add(entity_id)
                event_issue(
                    "error",
                    "UNKNOWN_DEVICE",
                    f"Entity '{entity_id}' is not covered by device_mapping and the "
                    "event carries no sourceDeviceId.",
                    **event_context,
                )
            else:
                event_context["sourceDeviceId"] = candidates[0]["sourceDeviceId"]

        if not missing_required:
            if event_type_id == "ENTITY_POSITION_UPDATE":
                _validate_position_payload(payload_dict, issues, event_issue, line, event_context)
                quality = payload_dict.get("positionQuality")
                if quality in POSITION_QUALITIES and not duplicate_event:
                    quality_counts[quality] += 1
            elif event_type_id == "MONITOR_VALUE_UPDATE":
                _validate_monitor_payload(payload_dict, issues, event_issue, line, event_context)
            elif event_type_id == "MONITOR_ALARM":
                _validate_alarm_payload(payload_dict, issues, event_issue, line, event_context)

        # Timestamp ordering is tracked only for events with a usable entity and time.
        # Duplicate event IDs are suppressed and never update the latest snapshot.
        timestamp = raw_event.get("sourceTimestamp")
        sequence = raw_event.get("sequence")
        if (
            not duplicate_event
            and entity_id
            and is_finite_number(timestamp)
            and isinstance(sequence, int)
            and not isinstance(sequence, bool)
        ):
            key = (mine_id or "", entity_id)
            previous = latest_by_key.get(key)
            out_of_order = False
            if previous:
                if timestamp < previous["sourceTimestamp"]:
                    out_of_order = True
                elif timestamp == previous["sourceTimestamp"] and sequence <= previous["sequence"]:
                    out_of_order = True
            if out_of_order:
                event_issue(
                    "error",
                    "OUT_OF_ORDER_EVENT",
                    f"sourceTimestamp {timestamp} / sequence {sequence} is not newer "
                    f"than the latest {previous['sourceTimestamp']} / {previous['sequence']} "
                    f"seen on line {previous['line']}; the event must not overwrite "
                    "newer state.",
                    **event_context,
                )
            else:
                if previous and sequence <= previous["sequence"]:
                    event_issue(
                        "warning",
                        "SEQUENCE_REGRESSION",
                        f"sequence {sequence} does not increase over the previous "
                        f"{previous['sequence']} even though the timestamp is newer; "
                        "check device reconnect or sequence reset.",
                        **event_context,
                    )
                latest_by_key[key] = {
                    "mineId": mine_id,
                    "entityId": entity_id,
                    "sourceTimestamp": timestamp,
                    "sequence": sequence,
                    "eventType": event_type_id,
                    "eventId": event_id,
                    "line": line,
                    "sourceDeviceId": event_context.get("sourceDeviceId") or source_id,
                }

    if not line_errors:
        valid_events = sum(
            1
            for event in events
            if isinstance(event, dict)
            and not event.get("_parse_error")
        )
    else:
        valid_events = sum(
            1
            for index, event in enumerate(events)
            if isinstance(event, dict)
            and not event.get("_parse_error")
            and int(event.get("_line", index + 1)) not in line_errors
        )

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    status = "FAIL" if error_count else "PASS_WITH_WARNINGS" if warning_count else "PASS"

    latest = sorted(
        latest_by_key.values(),
        key=lambda item: (item.get("mineId") or "", item["entityId"]),
    )

    return {
        "skill": "mine-iot-integration",
        "version": "v0.1",
        "status": status,
        "summary": {
            "mapping_entries": len(mapping["entries"]),
            "devices_mapped": len(mapping["by_source"]),
            "entities_mapped": len(mapping["by_entity"]),
            "events_total": len(events),
            "valid_events": valid_events,
            "events_with_errors": len(line_errors),
            "errors": error_count,
            "warnings": warning_count,
            "unknown_devices": len(unknown_device_ids),
            "unknown_device_ids": sorted(unknown_device_ids),
            "out_of_order_events": sum(
                1 for issue in issues if issue["code"] == "OUT_OF_ORDER_EVENT"
            ),
            "event_types": dict(sorted(event_type_counts.items())),
            "position_qualities": dict(sorted(quality_counts.items())),
            "latest_entities": len(latest),
        },
        "issues": issues,
        "latest_by_entity": latest,
    }


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# IoT Integration Validation Report",
        "",
        f"- **Status**: {report['status']}",
        f"- **Mapped devices**: {summary['devices_mapped']}",
        f"- **Mapped twin entities**: {summary['entities_mapped']}",
        f"- **Events**: {summary['events_total']} "
        f"(valid {summary['valid_events']}, with errors {summary['events_with_errors']})",
        f"- **Errors**: {summary['errors']}",
        f"- **Warnings**: {summary['warnings']}",
        f"- **Out-of-order events**: {summary['out_of_order_events']}",
        f"- **Unknown devices**: {summary['unknown_devices']}",
        "",
        "## Event types",
        "",
    ]
    if summary["event_types"]:
        for name, count in summary["event_types"].items():
            lines.append(f"- `{name}`: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Position quality", ""])
    if summary["position_qualities"]:
        for name, count in summary["position_qualities"].items():
            lines.append(f"- `{name}`: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Latest event per entity", ""])
    if report["latest_by_entity"]:
        lines.extend(
            [
                "| Mine | Entity | Timestamp | Sequence | Event | Source device |",
                "|---|---|---|---|---|---|",
            ]
        )
        for item in report["latest_by_entity"]:
            lines.append(
                f"| {item.get('mineId') or '-'} | {item['entityId']} | "
                f"{item['sourceTimestamp']} | {item['sequence']} | "
                f"{item.get('eventType') or '-'} | {item.get('sourceDeviceId') or '-'} |"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Issues", ""])
    if report["issues"]:
        lines.extend(["| Severity | Code | Line | Entity | Message |", "|---|---|---|---|---|"])
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
            "- v0.1 validates files only. Live ThingLinks REST/MQTT adapters, "
            "authentication and WebSocket subscriptions are future work.",
            "- Events without `sourceDeviceId` are resolved through a unique "
            "entity mapping; ambiguous or missing mappings are reported.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: dict, out_dir: str | Path) -> dict[str, str]:
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_json = output_dir / "integration_report.json"
    report_md = output_dir / "integration_report.md"
    issues_csv = output_dir / "issues.csv"

    report_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report_md.write_text(render_markdown(report), encoding="utf-8")

    columns = [
        "severity",
        "code",
        "line",
        "eventId",
        "entityId",
        "sourceDeviceId",
        "field",
        "message",
    ]
    with issues_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for issue in report["issues"]:
            writer.writerow(
                {
                    "severity": issue.get("severity"),
                    "code": issue.get("code"),
                    "line": issue.get("line"),
                    "eventId": issue.get("eventId"),
                    "entityId": issue.get("entityId"),
                    "sourceDeviceId": issue.get("sourceDeviceId"),
                    "field": issue.get("field"),
                    "message": issue.get("message"),
                }
            )

    return {
        "report_json": str(report_json),
        "report_md": str(report_md),
        "issues_csv": str(issues_csv),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate device mappings and digital-twin events."
    )
    parser.add_argument("mapping", help="device_mapping.json")
    parser.add_argument("events", help="events.jsonl")
    parser.add_argument("--out-dir", default="integration_output", help="Output directory")
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0; the report still records validation errors",
    )
    args = parser.parse_args(argv)

    mapping = read_json(args.mapping)
    events = read_jsonl(args.events)
    report = validate_events(mapping, events)
    paths = write_outputs(report, args.out_dir)
    summary = report["summary"]

    print(
        f"{report['status']}: {summary['events_total']} events "
        f"({summary['valid_events']} valid), {summary['devices_mapped']} devices, "
        f"{summary['errors']} errors, {summary['warnings']} warnings; "
        f"out-of-order {summary['out_of_order_events']}, "
        f"unknown devices {summary['unknown_devices']}"
    )
    print(
        f"Reports: {paths['report_json']}, {paths['report_md']}, {paths['issues_csv']}",
        file=sys.stderr,
    )

    if summary["errors"] and not args.no_fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
