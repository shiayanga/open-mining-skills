#!/usr/bin/env python3
"""Process personnel position events into latest positions, tracks and geofence events.

v0.1 is a deterministic file processor. It rejects older timestamps, classifies
position quality, evaluates point-in-polygon geofences, writes crossing events
and area counts. Coordinate conversion and live WebSocket ingestion are future
work; positions are always kept in their declared source coordinate system.
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

POSITION_QUALITIES = {"VALID", "LOW_ACCURACY", "STALE", "INVALID"}
EVALUABLE_QUALITIES = {"VALID", "LOW_ACCURACY"}


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
            records.append({"_line": lineno, "_parse_error": "Position line is not a JSON object."})
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


def _ring_from_record(record: dict) -> list | None:
    raw = record.get("polygon", record.get("ring"))
    if raw is None:
        raw = record.get("coordinates")
    if isinstance(raw, dict):
        if raw.get("type") == "Polygon":
            coordinates = raw.get("coordinates")
        else:
            coordinates = raw.get("coordinates")
        if not isinstance(coordinates, list):
            return None
        raw = coordinates
    if not isinstance(raw, list):
        return None
    # Unwrap a list of rings when the first element is itself a list of points.
    if (
        raw
        and isinstance(raw[0], list)
        and raw[0]
        and isinstance(raw[0][0], (list, tuple, dict))
    ):
        raw = raw[0]
    return raw


def _normalize_ring(raw: list, issues: list[dict], context: dict) -> list[list[float]] | None:
    points: list[list[float]] = []
    for index, point in enumerate(raw):
        if isinstance(point, dict):
            x, y = point.get("x"), point.get("y")
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            x, y = point[0], point[1]
        else:
            add_issue(
                issues,
                "error",
                "INVALID_GEOFENCE_POINT",
                f"Geofence vertex {index} must be [x, y] or an object with x/y.",
                **context,
                vertexIndex=index,
            )
            return None
        if not is_finite_number(x) or not is_finite_number(y):
            add_issue(
                issues,
                "error",
                "INVALID_GEOFENCE_POINT",
                f"Geofence vertex {index} has non-finite coordinates.",
                **context,
                vertexIndex=index,
            )
            return None
        points.append([float(x), float(y)])
    if len(points) >= 2 and points[0] == points[-1]:
        points.pop()
    deduped: list[list[float]] = []
    for point in points:
        if not deduped or point != deduped[-1]:
            deduped.append(point)
    if len(deduped) < 3:
        add_issue(
            issues,
            "error",
            "GEOFENCE_TOO_FEW_VERTICES",
            "Geofence requires at least 3 distinct vertices.",
            **context,
        )
        return None
    area = abs(
        sum(
            deduped[i][0] * deduped[(i + 1) % len(deduped)][1]
            - deduped[(i + 1) % len(deduped)][0] * deduped[i][1]
            for i in range(len(deduped))
        )
        / 2.0
    )
    if area <= 1e-12:
        add_issue(
            issues,
            "error",
            "GEOFENCE_ZERO_AREA",
            "Geofence polygon has zero area.",
            **context,
        )
        return None
    return deduped


def normalize_geofences(data: Any) -> tuple[list[dict], list[dict]]:
    issues: list[dict] = []
    if isinstance(data, list):
        raw_fences = data
    elif isinstance(data, dict):
        raw_fences = data.get("geofences", data.get("areas"))
        if not isinstance(raw_fences, list):
            if all(isinstance(value, dict) for value in data.values()):
                raw_fences = [
                    {"geofenceId": key, **value} for key, value in data.items()
                ]
            else:
                add_issue(
                    issues,
                    "error",
                    "INVALID_GEOFENCES",
                    "Geofence file must be a list or an object with a geofences array.",
                )
                return [], issues
    else:
        add_issue(issues, "error", "INVALID_GEOFENCES", "Geofence file must be a list or object.")
        return [], issues

    fences: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_fences):
        context = {"geofenceIndex": index}
        if not isinstance(raw, dict):
            add_issue(issues, "error", "INVALID_GEOFENCE", "Geofence entry must be an object.", **context)
            continue
        geofence_id = as_id(raw.get("geofenceId") or raw.get("id") or raw.get("areaId"))
        if not geofence_id:
            add_issue(issues, "error", "MISSING_GEOFENCE_ID", "Geofence requires a non-empty geofenceId.", **context)
            continue
        context["geofenceId"] = geofence_id
        if geofence_id in seen:
            add_issue(
                issues,
                "error",
                "DUPLICATE_GEOFENCE_ID",
                f"Geofence '{geofence_id}' is defined more than once.",
                **context,
            )
            continue
        seen.add(geofence_id)
        ring = _ring_from_record(raw)
        if ring is None:
            add_issue(issues, "error", "MISSING_GEOFENCE_POLYGON", "Geofence requires a polygon.", **context)
            continue
        normalized_ring = _normalize_ring(ring, issues, context)
        if normalized_ring is None:
            continue
        mine_id = as_id(raw.get("mineId"))
        if raw.get("mineId") is not None and not mine_id:
            add_issue(issues, "error", "EMPTY_GEOFENCE_MINE_ID", "Geofence mineId must be non-empty when present.", **context)
        if raw.get("enabled") is False:
            continue
        fences.append(
            {
                "geofenceId": geofence_id,
                "name": raw.get("name") or raw.get("areaName"),
                "mineId": mine_id,
                "ring": normalized_ring,
                "vertexCount": len(normalized_ring),
            }
        )
    if not fences and not issues:
        add_issue(issues, "warning", "NO_GEOFENCES", "No enabled geofences were loaded.")
    return fences, issues


def point_in_polygon(x: float, y: float, ring: list[list[float]]) -> bool:
    """Ray casting with boundary points treated as inside."""
    inside = False
    count = len(ring)
    for index in range(count):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % count]
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        tolerance = 1e-9 * max(1.0, abs(x2 - x1) + abs(y2 - y1))
        if (
            abs(cross) <= tolerance
            and min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9
            and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9
        ):
            return True
        if (y1 > y) != (y2 > y):
            intersection_x = x1 + (x2 - x1) * (y - y1) / (y2 - y1)
            if x < intersection_x:
                inside = not inside
    return inside


def _inside_fences(entity_mine: str | None, x: float, y: float, fences: list[dict]) -> list[str]:
    inside: list[str] = []
    for fence in fences:
        if fence.get("mineId") and entity_mine and fence["mineId"] != entity_mine:
            continue
        if point_in_polygon(x, y, fence["ring"]):
            inside.append(fence["geofenceId"])
    return inside


def _parse_position_event(event: dict, index: int, issues: list[dict]) -> dict | None:
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
        add_issue(issues, "error", "MISSING_EVENT_TYPE", "Position event requires eventType.", line=line)
        return None
    if event_type != "ENTITY_POSITION_UPDATE":
        add_issue(
            issues,
            "warning",
            "SKIPPED_EVENT_TYPE",
            f"Event type '{event_type}' is not ENTITY_POSITION_UPDATE.",
            line=line,
            eventType=event_type,
        )
        return None

    entity_type = event.get("entityType")
    entity_type = entity_type.strip() if isinstance(entity_type, str) else entity_type
    if entity_type and entity_type != "PERSON":
        add_issue(
            issues,
            "warning",
            "SKIPPED_NON_PERSON",
            f"entityType '{entity_type}' is not PERSON.",
            line=line,
            entityType=entity_type,
        )
        return None
    if not entity_type:
        add_issue(
            issues,
            "warning",
            "ASSUMED_PERSON",
            "entityType is missing; the position is processed as PERSON because "
            "this file is the personnel position stream.",
            line=line,
        )

    entity_id = as_id(event.get("entityId"))
    mine_id = as_id(event.get("mineId"))
    if not entity_id:
        add_issue(issues, "error", "MISSING_ENTITY_ID", "Position event requires entityId.", line=line)
    if not mine_id:
        add_issue(issues, "error", "MISSING_MINE_ID", "Position event requires mineId.", line=line)
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
        add_issue(issues, "error", "MISSING_PAYLOAD", "Position event requires a payload object.", line=line, entityId=entity_id)
        return None
    position = payload.get("position")
    if not isinstance(position, dict):
        add_issue(
            issues,
            "error",
            "MISSING_POSITION",
            "Position event payload requires a position object.",
            line=line,
            entityId=entity_id,
        )
        return None
    for axis in ("x", "y", "z"):
        if not is_finite_number(position.get(axis)):
            add_issue(
                issues,
                "error",
                "INVALID_POSITION",
                f"position.{axis} must be a finite number.",
                line=line,
                entityId=entity_id,
                field=f"position.{axis}",
            )
            return None
    coordinate_system_id = as_id(position.get("coordinateSystemId"))
    if not coordinate_system_id:
        add_issue(
            issues,
            "error",
            "MISSING_COORDINATE_SYSTEM",
            "Position requires coordinateSystemId; personnel coordinates must "
            "never be interpreted without a declared system.",
            line=line,
            entityId=entity_id,
        )
        return None
    quality = payload.get("positionQuality")
    if quality not in POSITION_QUALITIES:
        if quality is None:
            add_issue(
                issues,
                "warning",
                "MISSING_POSITION_QUALITY",
                "positionQuality is missing; the position is classified INVALID.",
                line=line,
                entityId=entity_id,
            )
        else:
            add_issue(
                issues,
                "warning",
                "UNKNOWN_POSITION_QUALITY",
                f"positionQuality '{quality}' is not one of {sorted(POSITION_QUALITIES)}; "
                "the position is classified INVALID.",
                line=line,
                entityId=entity_id,
            )
        quality = "INVALID"

    return {
        "line": line,
        "eventId": as_id(event.get("eventId")),
        "entityId": entity_id,
        "mineId": mine_id,
        "objectId": as_id(event.get("objectId")),
        "sourceTimestamp": float(timestamp) if timestamp is not None else None,
        "sequence": sequence,
        "position": {
            "x": float(position["x"]),
            "y": float(position["y"]),
            "z": float(position["z"]),
            "coordinateSystemId": coordinate_system_id,
        },
        "quality": quality,
        "insideGeofences": [],
        "order": index,
    }


def process_tracking(events: list[dict], geofence_data: Any) -> dict:
    """Process position events and geofences, returning all derived outputs."""
    issues: list[dict] = []
    fences, fence_issues = normalize_geofences(geofence_data)
    issues.extend(fence_issues)

    latest: dict[str, dict] = {}
    tracks: list[dict] = []
    geofence_events: list[dict] = []
    fence_state: dict[tuple[str, str], bool] = {}
    last_ordering: dict[str, tuple[float, int]] = {}
    quality_counts: Counter = Counter()
    event_total = 0
    out_of_order = 0
    accepted = 0
    skipped_non_person = 0
    skipped_event_type = 0

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            add_issue(issues, "error", "INVALID_EVENT", "Position event must be a JSON object.", line=index + 1)
            continue
        event_total += 1
        code_before = len(issues)
        parsed = _parse_position_event(event, index, issues)
        if parsed is None:
            if any(issue["code"] == "SKIPPED_NON_PERSON" for issue in issues[code_before:]):
                skipped_non_person += 1
            if any(issue["code"] == "SKIPPED_EVENT_TYPE" for issue in issues[code_before:]):
                skipped_event_type += 1
            continue

        entity_id = parsed["entityId"]
        timestamp = parsed["sourceTimestamp"]
        sequence = parsed["sequence"]
        if entity_id and timestamp is not None:
            previous = last_ordering.get(entity_id)
            if previous and (
                timestamp < previous[0]
                or (timestamp == previous[0] and sequence <= previous[1])
            ):
                out_of_order += 1
                add_issue(
                    issues,
                    "warning",
                    "OUT_OF_ORDER_IGNORED",
                    f"sourceTimestamp {timestamp} / sequence {sequence} is not newer "
                    f"than the accepted {previous[0]} / {previous[1]}; the event is "
                    "ignored and cannot regress the latest position.",
                    line=parsed["line"],
                    entityId=entity_id,
                )
                continue
            if previous and timestamp > previous[0] and sequence <= previous[1]:
                add_issue(
                    issues,
                    "warning",
                    "SEQUENCE_REGRESSION",
                    f"sequence {sequence} does not increase over {previous[1]}; "
                    "check device reconnect or sequence reset.",
                    line=parsed["line"],
                    entityId=entity_id,
                )
            last_ordering[entity_id] = (timestamp, sequence)

        accepted += 1
        quality_counts[parsed["quality"]] += 1
        x = parsed["position"]["x"]
        y = parsed["position"]["y"]
        inside = _inside_fences(parsed["mineId"], x, y, fences)
        parsed["insideGeofences"] = inside
        latest[entity_id] = {
            "entityId": entity_id,
            "mineId": parsed["mineId"],
            "objectId": parsed["objectId"],
            "position": parsed["position"],
            "positionQuality": parsed["quality"],
            "sourceTimestamp": int(timestamp) if timestamp is not None else None,
            "sequence": sequence,
            "eventId": parsed["eventId"],
            "insideGeofences": inside,
        }
        tracks.append(
            {
                "entity_id": entity_id,
                "mine_id": parsed["mineId"],
                "source_timestamp": int(timestamp) if timestamp is not None else "",
                "sequence": sequence,
                "x": x,
                "y": y,
                "z": parsed["position"]["z"],
                "coordinate_system_id": parsed["position"]["coordinateSystemId"],
                "quality": parsed["quality"],
                "inside_geofences": ";".join(inside),
            }
        )

        if parsed["quality"] not in EVALUABLE_QUALITIES:
            continue
        for fence in fences:
            if fence.get("mineId") and parsed["mineId"] and fence["mineId"] != parsed["mineId"]:
                continue
            key = (entity_id, fence["geofenceId"])
            inside_fence = fence["geofenceId"] in inside
            previous_state = fence_state.get(key)
            if previous_state is None:
                fence_state[key] = inside_fence
                continue
            if inside_fence == previous_state:
                continue
            fence_state[key] = inside_fence
            event_type = (
                "PERSONNEL_ENTER_AREA" if inside_fence else "PERSONNEL_LEAVE_AREA"
            )
            geofence_events.append(
                {
                    "eventId": f"GEO-{len(geofence_events) + 1:06d}",
                    "eventType": event_type,
                    "mineId": parsed["mineId"],
                    "entityId": entity_id,
                    "entityType": "PERSON",
                    "geofenceId": fence["geofenceId"],
                    "geofenceName": fence.get("name"),
                    "sourceTimestamp": int(timestamp) if timestamp is not None else None,
                    "sequence": sequence,
                    "position": parsed["position"],
                    "positionQuality": parsed["quality"],
                }
            )

    # Area counts derive from the final latest position, never from history.
    area_counts = []
    inside_any = 0
    for fence in fences:
        members = [
            entity_id
            for entity_id, item in sorted(latest.items())
            if item["positionQuality"] in EVALUABLE_QUALITIES
            and (not fence.get("mineId") or fence["mineId"] == item["mineId"])
            and point_in_polygon(
                item["position"]["x"], item["position"]["y"], fence["ring"]
            )
        ]
        area_counts.append(
            {
                "geofenceId": fence["geofenceId"],
                "name": fence.get("name"),
                "count": len(members),
                "entityIds": members,
            }
        )
    for item in latest.values():
        if any(
            item["positionQuality"] in EVALUABLE_QUALITIES
            and (not fence.get("mineId") or fence["mineId"] == item["mineId"])
            and point_in_polygon(
                item["position"]["x"], item["position"]["y"], fence["ring"]
            )
            for fence in fences
        ):
            inside_any += 1

    tracks.sort(key=lambda row: (row["entity_id"], row["source_timestamp"], row["sequence"]))
    latest_positions = sorted(latest.values(), key=lambda item: item["entityId"])
    enter_count = sum(1 for item in geofence_events if item["eventType"] == "PERSONNEL_ENTER_AREA")
    exit_count = sum(1 for item in geofence_events if item["eventType"] == "PERSONNEL_LEAVE_AREA")

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    status = "FAIL" if error_count else "PASS_WITH_WARNINGS" if warning_count else "PASS"

    report = {
        "skill": "mine-personnel-tracking",
        "version": "v0.1",
        "status": status,
        "summary": {
            "events_total": event_total,
            "positions_accepted": accepted,
            "tracks_written": len(tracks),
            "out_of_order_ignored": out_of_order,
            "skipped_non_person": skipped_non_person,
            "skipped_event_type": skipped_event_type,
            "persons_tracked": len(latest),
            "geofences": len(fences),
            "geofence_events": len(geofence_events),
            "geofence_enters": enter_count,
            "geofence_exits": exit_count,
            "positions_inside_any": inside_any,
            "positions_outside_all": len(latest) - inside_any,
            "quality_counts": dict(sorted(quality_counts.items())),
            "errors": error_count,
            "warnings": warning_count,
        },
        "geofences": [
            {
                "geofenceId": fence["geofenceId"],
                "name": fence.get("name"),
                "mineId": fence.get("mineId"),
                "vertexCount": fence["vertexCount"],
            }
            for fence in fences
        ],
        "area_counts": area_counts,
        "issues": issues,
    }

    return {
        "report": report,
        "latest_positions": {
            "skill": "mine-personnel-tracking",
            "version": "v0.1",
            "coordinatePolicy": "source coordinate system is preserved; no conversion is applied",
            "count": len(latest_positions),
            "positions": latest_positions,
        },
        "tracks": tracks,
        "geofence_events": geofence_events,
    }


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# Personnel Tracking Report",
        "",
        f"- **Status**: {report['status']}",
        f"- **Events**: {summary['events_total']} "
        f"(accepted {summary['positions_accepted']})",
        f"- **Persons tracked**: {summary['persons_tracked']}",
        f"- **Out-of-order events ignored**: {summary['out_of_order_ignored']}",
        f"- **Geofences**: {summary['geofences']}",
        f"- **Geofence events**: {summary['geofence_events']} "
        f"(enter {summary['geofence_enters']}, exit {summary['geofence_exits']})",
        f"- **Errors**: {summary['errors']}, **warnings**: {summary['warnings']}",
        "",
        "## Quality",
        "",
    ]
    if summary["quality_counts"]:
        for quality, count in summary["quality_counts"].items():
            lines.append(f"- `{quality}`: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Area counts", ""])
    if report["area_counts"]:
        lines.extend(["| Geofence | Name | Count | Entities |", "|---|---|---|---|"])
        for item in report["area_counts"]:
            lines.append(
                f"| {item['geofenceId']} | {item.get('name') or '-'} | "
                f"{item['count']} | {', '.join(item['entityIds']) or '-'} |"
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
            "- v0.1 preserves the declared source coordinate system; coordinate "
            "conversion to scene coordinates is future work.",
            "- Only `VALID` and `LOW_ACCURACY` positions update geofence state and "
            "area counts. `STALE` and `INVALID` positions remain visible in tracks "
            "but are not treated as normal presence.",
            "- The initial geofence state is seeded from the first accepted position; "
            "no entry event is emitted for a person already inside at stream start.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(result: dict, out_dir: str | Path) -> dict[str, str]:
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_path = output_dir / "latest_positions.json"
    tracks_path = output_dir / "tracks.csv"
    geofence_events_path = output_dir / "geofence_events.jsonl"
    report_path = output_dir / "tracking_report.json"
    markdown_path = output_dir / "tracking_report.md"

    latest_path.write_text(
        json.dumps(result["latest_positions"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with tracks_path.open("w", encoding="utf-8-sig", newline="") as fh:
        columns = [
            "entity_id",
            "mine_id",
            "source_timestamp",
            "sequence",
            "x",
            "y",
            "z",
            "coordinate_system_id",
            "quality",
            "inside_geofences",
        ]
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(result["tracks"])
    with geofence_events_path.open("w", encoding="utf-8") as fh:
        for event in result["geofence_events"]:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    report_path.write_text(
        json.dumps(result["report"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(result["report"]), encoding="utf-8")

    return {
        "latest_positions": str(latest_path),
        "tracks_csv": str(tracks_path),
        "geofence_events": str(geofence_events_path),
        "report_json": str(report_path),
        "report_md": str(markdown_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Process personnel positions, tracks and geofences."
    )
    parser.add_argument("positions", help="positions.jsonl (ENTITY_POSITION_UPDATE events)")
    parser.add_argument("geofences", help="geofences.json")
    parser.add_argument("--out-dir", default="tracking_output", help="Output directory")
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0; the report still records processing errors",
    )
    args = parser.parse_args(argv)

    events = read_jsonl(args.positions)
    geofence_data = read_json(args.geofences)
    result = process_tracking(events, geofence_data)
    paths = write_outputs(result, args.out_dir)
    summary = result["report"]["summary"]

    print(
        f"{result['report']['status']}: {summary['persons_tracked']} persons, "
        f"{summary['tracks_written']} track points, "
        f"{summary['geofence_events']} geofence events, "
        f"{summary['errors']} errors, {summary['warnings']} warnings; "
        f"out-of-order ignored {summary['out_of_order_ignored']}"
    )
    print(
        "Reports: " + ", ".join(paths[key] for key in (
            "latest_positions",
            "tracks_csv",
            "geofence_events",
            "report_json",
            "report_md",
        )),
        file=sys.stderr,
    )

    if summary["errors"] and not args.no_fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
