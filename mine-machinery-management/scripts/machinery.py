#!/usr/bin/env python3
"""Validate machinery telemetry, merge latest state and map state to animation.

v0.1 is a file-based processor. It enforces registry references, sequence
ordering, position/orientation speed and range checks, maps real telemetry state
to animation names, and never lets older telemetry overwrite newer state. Live
machinery adapters and Cesium animation playback are future work.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ACCEPTED_EVENT_TYPES = {
    "MACHINERY_STATUS_UPDATE",
    "MACHINERY_ALARM",
    "ENTITY_POSITION_UPDATE",
    "ENTITY_STATUS_UPDATE",
    "ENTITY_PROPERTY_UPDATE",
}


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
            records.append({"_line": lineno, "_parse_error": "Telemetry line is not a JSON object."})
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


def normalize_registry(data: Any) -> tuple[dict[str, dict], list[dict]]:
    issues: list[dict] = []
    if isinstance(data, list):
        raw_entries = data
    elif isinstance(data, dict):
        for key in ("machinery", "machines", "items"):
            if isinstance(data.get(key), list):
                raw_entries = data[key]
                break
        else:
            if all(isinstance(value, dict) for value in data.values()) and data:
                raw_entries = [
                    {"machineryId": key, **value} for key, value in data.items()
                ]
            else:
                add_issue(
                    issues,
                    "error",
                    "INVALID_REGISTRY",
                    "registry.json must be a list or an object with a machinery array.",
                )
                return {}, issues
    else:
        add_issue(issues, "error", "INVALID_REGISTRY", "registry.json must be a list or object.")
        return {}, issues

    registry: dict[str, dict] = {}
    for index, raw in enumerate(raw_entries):
        context = {"recordType": "machinery", "recordIndex": index}
        if not isinstance(raw, dict):
            add_issue(issues, "error", "INVALID_REGISTRY_ENTRY", "Machinery entry must be an object.", **context)
            continue
        machinery_id = as_id(
            raw.get("machineryId") or raw.get("entityId") or raw.get("id")
        )
        machinery_type = raw.get("machineryType") or raw.get("type") or raw.get("equipmentType")
        machinery_type = machinery_type.strip() if isinstance(machinery_type, str) else machinery_type
        model_value = raw.get("model", raw.get("modelId"))
        if isinstance(model_value, dict):
            model_value = model_value.get("modelId") or model_value.get("id")
        model = as_id(model_value)
        if not machinery_id:
            add_issue(issues, "error", "MISSING_MACHINERY_ID", "Machinery requires a non-empty machineryId.", **context)
            continue
        context["machineryId"] = machinery_id
        if not machinery_type:
            add_issue(issues, "error", "MISSING_MACHINERY_TYPE", "Machinery requires a machineryType.", **context)
        if not model:
            add_issue(issues, "error", "MISSING_MODEL", "Machinery requires a non-empty model.", **context)
        if machinery_id in registry:
            add_issue(
                issues,
                "error",
                "DUPLICATE_MACHINERY_ID",
                f"Machinery '{machinery_id}' is registered more than once.",
                **context,
            )
            continue
        model_node_id = raw.get("modelNodeId")
        if model_node_id is not None and not as_id(model_node_id):
            add_issue(issues, "error", "EMPTY_MODEL_NODE_ID", "modelNodeId must be non-empty when present.", **context)
            model_node_id = None
        mine_id = as_id(raw.get("mineId"))
        if raw.get("mineId") is not None and not mine_id:
            add_issue(issues, "error", "EMPTY_MINE_ID", "Machinery mineId must be non-empty when present.", **context)
        registry[machinery_id] = {
            "machineryId": machinery_id,
            "machineryType": machinery_type,
            "model": model,
            "modelNodeId": as_id(model_node_id),
            "mineId": mine_id,
            "name": raw.get("name"),
        }
    if not registry:
        add_issue(issues, "error", "EMPTY_REGISTRY", "No usable machinery registry entries were loaded.")
    return registry, issues


def normalize_state_map(data: Any) -> tuple[dict[str, dict], list[dict]]:
    issues: list[dict] = []
    if isinstance(data, dict):
        for key in ("states", "stateMap", "animationMapping"):
            if isinstance(data.get(key), dict):
                raw = data[key]
                break
        else:
            raw = data
        entries = list(raw.items())
    elif isinstance(data, list):
        entries = []
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                add_issue(issues, "error", "INVALID_STATE_MAP_ENTRY", "State map entry must be an object.", recordIndex=index)
                continue
            entries.append((item.get("state"), item))
    else:
        add_issue(issues, "error", "INVALID_STATE_MAP", "state_map.json must be an object or list.")
        return {}, issues

    state_map: dict[str, dict] = {}
    for state_value, config_value in entries:
        state = as_id(state_value)
        if not state:
            add_issue(issues, "error", "MISSING_STATE", "State map key must be non-empty.")
            continue
        if state in state_map:
            add_issue(issues, "error", "DUPLICATE_STATE", f"State '{state}' is mapped more than once.", state=state)
            continue
        if isinstance(config_value, str):
            animation = config_value.strip()
            config = {}
        elif isinstance(config_value, dict):
            animation = config_value.get("animation") or config_value.get("name") or config_value.get("clip")
            animation = animation.strip() if isinstance(animation, str) else animation
            config = {
                "loop": config_value.get("loop"),
                "speedScale": config_value.get("speedScale"),
            }
        else:
            add_issue(issues, "error", "INVALID_STATE_MAPPING", "State mapping must be a string or object.", state=state)
            continue
        if not animation:
            add_issue(issues, "error", "MISSING_ANIMATION", f"State '{state}' has no animation name.", state=state)
            continue
        loop = config.get("loop")
        if loop is not None and not isinstance(loop, bool):
            add_issue(issues, "warning", "INVALID_ANIMATION_LOOP", "animation loop must be a boolean when present.", state=state)
            loop = None
        speed_scale = config.get("speedScale")
        if speed_scale is not None and not is_finite_number(speed_scale):
            add_issue(issues, "warning", "INVALID_ANIMATION_SPEED", "speedScale must be a finite number when present.", state=state)
            speed_scale = None
        state_map[state] = {
            "animation": animation,
            "loop": loop,
            "speedScale": speed_scale,
        }
    if not state_map:
        add_issue(issues, "error", "EMPTY_STATE_MAP", "No usable state-to-animation mappings were loaded.")
    return state_map, issues


def _pick(event: dict, payload: dict, field: str) -> Any:
    if field in event and event[field] is not None:
        return event[field]
    return payload.get(field)


def _validate_orientation(orientation: dict, issues: list[dict], line: int, machinery_id: str) -> None:
    context = {"line": line, "machineryId": machinery_id}
    units = orientation.get("units") or orientation.get("unit") or orientation.get("angleUnit")
    if units is not None and str(units).strip().lower() not in {"deg", "degree", "degrees"}:
        add_issue(
            issues,
            "error",
            "INVALID_ORIENTATION_UNITS",
            "Orientation units must be degrees; units are explicit and never guessed.",
            **context,
        )
    ranges = {"heading": (0.0, 360.0), "pitch": (-90.0, 90.0), "roll": (-180.0, 180.0)}
    for axis, (minimum, maximum) in ranges.items():
        value = orientation.get(axis)
        if not is_finite_number(value):
            add_issue(
                issues,
                "error",
                "MISSING_ORIENTATION_AXIS",
                f"orientation.{axis} must be a finite number.",
                field=f"orientation.{axis}",
                **context,
            )
            continue
        value = float(value)
        if axis == "heading":
            valid = minimum <= value < maximum
        else:
            valid = minimum <= value <= maximum
        if not valid:
            add_issue(
                issues,
                "error",
                "ORIENTATION_OUT_OF_RANGE",
                f"orientation.{axis}={value} is outside [{minimum}, {maximum}"
                f"{')' if axis == 'heading' else ']'} degrees.",
                field=f"orientation.{axis}",
                **context,
            )


def _parse_telemetry(event: dict, index: int, issues: list[dict]) -> dict | None:
    line = index + 1
    try:
        line = int(event.get("_line", line))
    except (TypeError, ValueError):
        pass
    if event.get("_parse_error"):
        add_issue(issues, "error", "INVALID_TELEMETRY_JSON", str(event["_parse_error"]), line=line)
        return None
    event_type = event.get("eventType")
    if event_type is not None:
        event_type_id = as_id(event_type)
        if not event_type_id:
            add_issue(issues, "error", "INVALID_EVENT_TYPE", "eventType must be a non-empty string.", line=line)
            return None
        if event_type_id not in ACCEPTED_EVENT_TYPES:
            add_issue(
                issues,
                "warning",
                "SKIPPED_EVENT_TYPE",
                f"Event type '{event_type_id}' is not a machinery telemetry event.",
                line=line,
                eventType=event_type_id,
            )
            return None
    payload = event.get("payload")
    if payload is None:
        payload = {}
    elif not isinstance(payload, dict):
        add_issue(issues, "error", "INVALID_PAYLOAD", "payload must be an object when present.", line=line)
        return None

    id_values = []
    for raw_id in (
        event.get("machineryId"),
        payload.get("machineryId"),
        event.get("entityId"),
    ):
        normalized = as_id(raw_id)
        if normalized and normalized not in id_values:
            id_values.append(normalized)
    if len(id_values) > 1:
        add_issue(
            issues,
            "error",
            "MACHINERY_ID_MISMATCH",
            "Telemetry declares conflicting machinery IDs: " + ", ".join(id_values),
            line=line,
        )
        return None
    machinery_id = id_values[0] if id_values else None
    if not machinery_id:
        add_issue(issues, "error", "MISSING_MACHINERY_ID", "Telemetry requires machineryId or entityId.", line=line)
        return None

    timestamp = _pick(event, payload, "sourceTimestamp")
    if not is_finite_number(timestamp) or float(timestamp) < 0:
        add_issue(
            issues,
            "error",
            "INVALID_SOURCE_TIMESTAMP",
            "sourceTimestamp must be a non-negative epoch-millisecond number.",
            line=line,
            machineryId=machinery_id,
        )
        return None
    sequence = _pick(event, payload, "sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        add_issue(
            issues,
            "error",
            "INVALID_SEQUENCE",
            "sequence must be a non-negative integer.",
            line=line,
            machineryId=machinery_id,
        )
        return None

    position = _pick(event, payload, "position")
    orientation = _pick(event, payload, "orientation")
    speed = _pick(event, payload, "speed")
    state = _pick(event, payload, "state")
    params = _pick(event, payload, "params")
    mine_id = as_id(_pick(event, payload, "mineId"))
    if not any(value is not None for value in (position, orientation, speed, state, params)):
        add_issue(
            issues,
            "error",
            "NO_TELEMETRY_FIELDS",
            "Telemetry event requires at least one of position, orientation, "
            "speed, state or params.",
            line=line,
            machineryId=machinery_id,
        )
        return None

    if position is not None:
        if not isinstance(position, dict):
            add_issue(issues, "error", "INVALID_POSITION", "position must be an object.", line=line, machineryId=machinery_id)
            position = None
        else:
            if not all(is_finite_number(position.get(axis)) for axis in ("x", "y", "z")):
                add_issue(
                    issues,
                    "error",
                    "INVALID_POSITION",
                    "position x, y and z must be finite numbers.",
                    line=line,
                    machineryId=machinery_id,
                )
                position = None
            else:
                position = {
                    "x": float(position["x"]),
                    "y": float(position["y"]),
                    "z": float(position["z"]),
                    "coordinateSystemId": as_id(position.get("coordinateSystemId")),
                }
                if not position["coordinateSystemId"]:
                    add_issue(
                        issues,
                        "warning",
                        "MISSING_COORDINATE_SYSTEM",
                        "Position has no coordinateSystemId; the source coordinate "
                        "system should be explicit.",
                        line=line,
                        machineryId=machinery_id,
                    )
    if orientation is not None:
        if not isinstance(orientation, dict):
            add_issue(issues, "error", "INVALID_ORIENTATION", "orientation must be an object.", line=line, machineryId=machinery_id)
            orientation = None
        else:
            _validate_orientation(orientation, issues, line, machinery_id)
            orientation = {
                "heading": float(orientation["heading"]) if is_finite_number(orientation.get("heading")) else orientation.get("heading"),
                "pitch": float(orientation["pitch"]) if is_finite_number(orientation.get("pitch")) else orientation.get("pitch"),
                "roll": float(orientation["roll"]) if is_finite_number(orientation.get("roll")) else orientation.get("roll"),
            }
    if speed is not None:
        if not is_finite_number(speed) or float(speed) < 0:
            add_issue(
                issues,
                "error",
                "INVALID_SPEED",
                "speed must be a finite non-negative number.",
                line=line,
                machineryId=machinery_id,
            )
            speed = None
        else:
            speed = float(speed)
    if state is not None:
        state = state.strip() if isinstance(state, str) else state
        if not as_id(state):
            add_issue(issues, "error", "INVALID_STATE", "state must be a non-empty string.", line=line, machineryId=machinery_id)
            state = None
        else:
            state = str(state)
    if params is not None and not isinstance(params, dict):
        add_issue(issues, "error", "INVALID_PARAMS", "params must be an object.", line=line, machineryId=machinery_id)
        params = None

    return {
        "line": line,
        "eventId": as_id(event.get("eventId")),
        "eventType": as_id(event_type),
        "machineryId": machinery_id,
        "mineId": mine_id,
        "sourceTimestamp": float(timestamp),
        "sequence": sequence,
        "position": position,
        "orientation": orientation,
        "speed": speed,
        "state": state,
        "params": params,
    }


def process_machinery(registry_data: Any, state_data: Any, events: list[dict]) -> dict:
    issues: list[dict] = []
    registry, registry_issues = normalize_registry(registry_data)
    issues.extend(registry_issues)
    state_map, state_issues = normalize_state_map(state_data)
    issues.extend(state_issues)

    latest: dict[str, dict] = {}
    tracks: list[dict] = []
    last_ordering: dict[str, tuple[float, int]] = {}
    state_counts: Counter = Counter()
    animation_counts: Counter = Counter()
    accepted = 0
    out_of_order = 0
    unknown_machinery = 0
    skipped_event_type = 0

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            add_issue(issues, "error", "INVALID_TELEMETRY", "Telemetry line must be a JSON object.", line=index + 1)
            continue
        parsed = _parse_telemetry(event, index, issues)
        if parsed is None:
            event_type_id = as_id(event.get("eventType")) if isinstance(event, dict) else None
            if event_type_id and event_type_id not in ACCEPTED_EVENT_TYPES:
                skipped_event_type += 1
            continue
        machinery_id = parsed["machineryId"]
        entry = registry.get(machinery_id)
        if entry is None:
            unknown_machinery += 1
            add_issue(
                issues,
                "error",
                "UNKNOWN_MACHINERY",
                f"Machinery '{machinery_id}' is not present in registry.json.",
                line=parsed["line"],
                machineryId=machinery_id,
            )
            continue
        if parsed["mineId"] and entry.get("mineId") and parsed["mineId"] != entry["mineId"]:
            add_issue(
                issues,
                "error",
                "MINE_MISMATCH",
                f"Telemetry mine '{parsed['mineId']}' differs from registry mine "
                f"'{entry['mineId']}' for machinery '{machinery_id}'.",
                line=parsed["line"],
                machineryId=machinery_id,
            )
            continue

        previous = last_ordering.get(machinery_id)
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
                f"{previous[0]} / {previous[1]}; the telemetry is ignored and "
                "cannot regress machinery state.",
                line=parsed["line"],
                machineryId=machinery_id,
            )
            continue
        if previous and parsed["sourceTimestamp"] > previous[0] and parsed["sequence"] <= previous[1]:
            add_issue(
                issues,
                "warning",
                "SEQUENCE_REGRESSION",
                f"sequence {parsed['sequence']} does not increase over {previous[1]}; "
                "check device reconnect or sequence reset.",
                line=parsed["line"],
                machineryId=machinery_id,
            )
        last_ordering[machinery_id] = (parsed["sourceTimestamp"], parsed["sequence"])
        accepted += 1

        machine = latest.get(machinery_id)
        if machine is None:
            machine = {
                "machineryId": machinery_id,
                "machineryType": entry.get("machineryType"),
                "model": entry.get("model"),
                "modelNodeId": entry.get("modelNodeId"),
                "name": entry.get("name"),
                "mineId": parsed["mineId"] or entry.get("mineId"),
                "state": None,
                "animation": None,
                "animationConfig": None,
                "stateChangedAt": None,
                "position": None,
                "orientation": None,
                "speed": None,
                "params": {},
                "lastSourceTimestamp": None,
                "lastSequence": None,
                "lastEventId": None,
                "lastUpdatedAt": None,
                "eventCount": 0,
            }
            latest[machinery_id] = machine
        if parsed["mineId"]:
            machine["mineId"] = parsed["mineId"]
        if parsed["position"] is not None:
            machine["position"] = parsed["position"]
        if parsed["orientation"] is not None:
            machine["orientation"] = parsed["orientation"]
        if parsed["speed"] is not None:
            machine["speed"] = parsed["speed"]
        if parsed["params"] is not None:
            machine["params"].update(parsed["params"])
        if parsed["state"] is not None:
            if parsed["state"] != machine["state"]:
                machine["stateChangedAt"] = int(parsed["sourceTimestamp"])
            machine["state"] = parsed["state"]
            animation_config = state_map.get(parsed["state"])
            if animation_config is None:
                add_issue(
                    issues,
                    "warning",
                    "UNKNOWN_STATE",
                    f"State '{parsed['state']}' has no animation mapping; the state "
                    "is kept but no animation will be driven.",
                    line=parsed["line"],
                    machineryId=machinery_id,
                    state=parsed["state"],
                )
                machine["animation"] = None
                machine["animationConfig"] = None
            else:
                machine["animation"] = animation_config["animation"]
                machine["animationConfig"] = {
                    "loop": animation_config["loop"],
                    "speedScale": animation_config["speedScale"],
                }
            state_counts[parsed["state"]] += 1
            if machine["animation"]:
                animation_counts[machine["animation"]] += 1
        machine["lastSourceTimestamp"] = int(parsed["sourceTimestamp"])
        machine["lastSequence"] = parsed["sequence"]
        machine["lastEventId"] = parsed["eventId"]
        machine["lastUpdatedAt"] = int(parsed["sourceTimestamp"])
        machine["eventCount"] += 1

        if parsed["position"] is not None:
            position = parsed["position"]
            orientation = machine["orientation"] or {}
            tracks.append(
                {
                    "machinery_id": machinery_id,
                    "machinery_type": machine.get("machineryType") or "",
                    "model": machine.get("model") or "",
                    "mine_id": machine.get("mineId") or "",
                    "source_timestamp": int(parsed["sourceTimestamp"]),
                    "sequence": parsed["sequence"],
                    "x": position["x"],
                    "y": position["y"],
                    "z": position["z"],
                    "coordinate_system_id": position.get("coordinateSystemId") or "",
                    "heading": orientation.get("heading", ""),
                    "pitch": orientation.get("pitch", ""),
                    "roll": orientation.get("roll", ""),
                    "speed": machine["speed"] if machine["speed"] is not None else "",
                    "state": machine["state"] or "",
                    "animation": machine["animation"] or "",
                }
            )

    tracks.sort(
        key=lambda row: (row["machinery_id"], row["source_timestamp"], row["sequence"])
    )
    latest_rows = sorted(latest.values(), key=lambda item: item["machineryId"])

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    status = "FAIL" if error_count else "PASS_WITH_WARNINGS" if warning_count else "PASS"

    report = {
        "skill": "mine-machinery-management",
        "version": "v0.1",
        "status": status,
        "summary": {
            "registry_machinery": len(registry),
            "machinery_types": dict(
                Counter(
                    entry.get("machineryType")
                    for entry in registry.values()
                    if entry.get("machineryType")
                )
            ),
            "telemetry_events": len(events),
            "accepted_events": accepted,
            "tracks_written": len(tracks),
            "machines_updated": len(latest),
            "unknown_machinery": unknown_machinery,
            "skipped_event_type": skipped_event_type,
            "out_of_order_ignored": out_of_order,
            "state_counts": dict(sorted(state_counts.items())),
            "animation_counts": dict(sorted(animation_counts.items())),
            "errors": error_count,
            "warnings": warning_count,
        },
        "machinery": [
            {
                "machineryId": item["machineryId"],
                "machineryType": item.get("machineryType"),
                "model": item.get("model"),
                "state": item.get("state"),
                "animation": item.get("animation"),
                "lastSourceTimestamp": item.get("lastSourceTimestamp"),
                "eventCount": item.get("eventCount"),
            }
            for item in latest_rows
        ],
        "issues": issues,
    }

    return {
        "report": report,
        "latest_state": {
            "skill": "mine-machinery-management",
            "version": "v0.1",
            "coordinatePolicy": "source position and orientation are preserved; no conversion is applied",
            "count": len(latest_rows),
            "machinery": latest_rows,
        },
        "tracks": tracks,
    }


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# Machinery Management Report",
        "",
        f"- **Status**: {report['status']}",
        f"- **Registered machinery**: {summary['registry_machinery']}",
        f"- **Telemetry events**: {summary['telemetry_events']} "
        f"(accepted {summary['accepted_events']})",
        f"- **Machines updated**: {summary['machines_updated']}",
        f"- **Track rows**: {summary['tracks_written']}",
        f"- **Out-of-order telemetry ignored**: {summary['out_of_order_ignored']}",
        f"- **Unknown machinery**: {summary['unknown_machinery']}",
        f"- **Errors**: {summary['errors']}, **warnings**: {summary['warnings']}",
        "",
        "## Latest states",
        "",
    ]
    if report["machinery"]:
        lines.extend(
            [
                "| Machinery | Type | State | Animation | Last source time | Events |",
                "|---|---|---|---|---|---|",
            ]
        )
        for item in report["machinery"]:
            lines.append(
                f"| {item['machineryId']} | {item.get('machineryType') or '-'} | "
                f"{item.get('state') or '-'} | {item.get('animation') or '-'} | "
                f"{item.get('lastSourceTimestamp')} | {item.get('eventCount')} |"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## State counts", ""])
    if summary["state_counts"]:
        for state, count in summary["state_counts"].items():
            lines.append(f"- `{state}`: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Animation counts", ""])
    if summary["animation_counts"]:
        for animation, count in summary["animation_counts"].items():
            lines.append(f"- `{animation}`: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Issues", ""])
    if report["issues"]:
        lines.extend(["| Severity | Code | Line | Machinery | Message |", "|---|---|---|---|---|"])
        for issue in report["issues"]:
            message = str(issue.get("message", "")).replace("|", "\\|")
            lines.append(
                f"| {issue['severity']} | {issue['code']} | {issue.get('line', '-')} | "
                f"{issue.get('machineryId', '-')} | {message} |"
            )
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- v0.1 processes files only; live machinery adapters and Cesium "
            "animation playback are future work.",
            "- Animation is driven only by the telemetry `state` and the configured "
            "`state_map.json`; visual animation is never treated as proof of work.",
            "- Heading is validated in degrees on [0, 360); pitch on [-90, 90]; "
            "roll on [-180, 180].",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(result: dict, out_dir: str | Path) -> dict[str, str]:
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_path = output_dir / "latest_state.json"
    tracks_path = output_dir / "tracks.csv"
    report_path = output_dir / "machinery_report.json"
    markdown_path = output_dir / "machinery_report.md"

    latest_path.write_text(
        json.dumps(result["latest_state"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with tracks_path.open("w", encoding="utf-8-sig", newline="") as fh:
        columns = [
            "machinery_id",
            "machinery_type",
            "model",
            "mine_id",
            "source_timestamp",
            "sequence",
            "x",
            "y",
            "z",
            "coordinate_system_id",
            "heading",
            "pitch",
            "roll",
            "speed",
            "state",
            "animation",
        ]
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(result["tracks"])
    report_path.write_text(
        json.dumps(result["report"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(result["report"]), encoding="utf-8")

    return {
        "latest_state": str(latest_path),
        "tracks_csv": str(tracks_path),
        "report_json": str(report_path),
        "report_md": str(markdown_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate machinery telemetry and map state to animation."
    )
    parser.add_argument("registry", help="registry.json")
    parser.add_argument("telemetry", help="telemetry.jsonl")
    parser.add_argument("state_map", help="state_map.json")
    parser.add_argument("--out-dir", default="machinery_output", help="Output directory")
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0; the report still records validation errors",
    )
    args = parser.parse_args(argv)

    registry = read_json(args.registry)
    state_map = read_json(args.state_map)
    events = read_jsonl(args.telemetry)
    result = process_machinery(registry, state_map, events)
    paths = write_outputs(result, args.out_dir)
    summary = result["report"]["summary"]

    print(
        f"{result['report']['status']}: {summary['registry_machinery']} machines, "
        f"{summary['accepted_events']} telemetry events, "
        f"{summary['tracks_written']} track rows, "
        f"{summary['errors']} errors, {summary['warnings']} warnings; "
        f"out-of-order ignored {summary['out_of_order_ignored']}, "
        f"unknown machinery {summary['unknown_machinery']}"
    )
    print(
        f"Reports: {paths['latest_state']}, {paths['tracks_csv']}, "
        f"{paths['report_json']}, {paths['report_md']}",
        file=sys.stderr,
    )

    if summary["errors"] and not args.no_fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
