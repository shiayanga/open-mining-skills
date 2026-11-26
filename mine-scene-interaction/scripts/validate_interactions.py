#!/usr/bin/env python3
"""Validate a mine scene interaction contract and optional entity bindings.

The contract describes handlers, panels, permissions, realtime channels and
track playback. The optional bindings file maps business entity IDs to scene
objects. Validation is static: no Cesium scene is started and no API is called.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import common

SUPPORTED_HANDLER_TYPES = {"pick", "select", "flyTo", "track", "filter", "panel"}
HANDLER_ALIASES = {
    "pick": "pick",
    "select": "select",
    "flyto": "flyTo",
    "fly_to": "flyTo",
    "fly-to": "flyTo",
    "track": "track",
    "filter": "filter",
    "panel": "panel",
}
SUPPORTED_ENTITY_TYPES = {"PERSON", "MONITOR_DEVICE", "MACHINERY", "INFRASTRUCTURE"}

KNOWN_PERMISSION_ACTIONS = {
    "VIEW_OBJECT",
    "VIEW_PERSON",
    "VIEW_DEVICE",
    "VIEW_MACHINERY",
    "VIEW_INFRASTRUCTURE",
    "VIEW_ALARM",
    "VIEW_TRACK",
    "VIEW_POSITION_HISTORY",
    "VIEW_SENSITIVE",
    "VIEW_VIDEO",
    "EDIT_OBJECT",
    "MANAGE_BINDING",
    "EXPORT_DATA",
}
KNOWN_SCOPES = {"MINE", "SCENE", "LAYER", "ENTITY"}
KNOWN_TRANSPORTS = {"WEBSOCKET", "SSE", "POLLING"}
KNOWN_EVENT_TYPES = {
    "ENTITY_POSITION_UPDATE",
    "ENTITY_STATUS_UPDATE",
    "ENTITY_PROPERTY_UPDATE",
    "ENTITY_ALARM",
    "ENTITY_OFFLINE",
    "ENTITY_ONLINE",
    "ENTITY_GEOFENCE_EVENT",
}
KNOWN_FILTER_FIELDS = {
    "entityType",
    "status",
    "online",
    "alarm",
    "areaId",
    "departmentId",
    "layerId",
    "machineryType",
    "deviceType",
    "personnelType",
    "metricCode",
}
KNOWN_INTERPOLATIONS = {"LINEAR", "STEP", "CATMULL_ROM"}
KNOWN_PICK_EVENTS = {"LEFT_CLICK", "LEFT_DOUBLE_CLICK", "RIGHT_CLICK"}


class Issues:
    def __init__(self) -> None:
        self.errors: list[dict] = []
        self.warnings: list[dict] = []

    def error(self, code: str, path: str, message: str) -> None:
        self.errors.append({"code": code, "path": path, "message": message})

    def warning(self, code: str, path: str, message: str) -> None:
        self.warnings.append({"code": code, "path": path, "message": message})


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _id_text(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or None
    return None


def _validate_entity_types(value: object, path: str, issues: Issues) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, list):
        issues.error("INVALID_ENTITY_TYPES", path, "entityTypes must be an array.")
        return set()
    if not value:
        issues.error("EMPTY_ENTITY_TYPES", path, "entityTypes must not be empty when present.")
        return set()

    result: set[str] = set()
    for index, item in enumerate(value):
        if not _is_nonempty_str(item):
            issues.error(
                "INVALID_ENTITY_TYPE",
                f"{path}[{index}]",
                "Entity type must be a non-empty string.",
            )
            continue
        entity_type = item.strip().upper()
        if entity_type not in SUPPORTED_ENTITY_TYPES:
            issues.error(
                "UNKNOWN_ENTITY_TYPE",
                f"{path}[{index}]",
                f"Entity type '{item}' is not supported; use one of "
                f"{', '.join(sorted(SUPPORTED_ENTITY_TYPES))}.",
            )
            continue
        if entity_type in result:
            issues.warning(
                "DUPLICATE_ENTITY_TYPE",
                f"{path}[{index}]",
                f"Entity type '{entity_type}' is listed more than once.",
            )
        result.add(entity_type)
    return result


def _validate_playback(playback: object, path: str, issues: Issues) -> dict:
    info: dict = {}
    if not isinstance(playback, dict):
        issues.error("INVALID_TRACK_PLAYBACK", path, "Track playback settings must be an object.")
        return info
    if "defaultSpeed" in playback:
        speed = playback["defaultSpeed"]
        if not _is_number(speed) or float(speed) <= 0:
            issues.error(
                "INVALID_PLAYBACK_SPEED",
                f"{path}.defaultSpeed",
                "defaultSpeed must be a positive number.",
            )
        else:
            info["defaultSpeed"] = float(speed)
    if "speedOptions" in playback:
        options = playback["speedOptions"]
        if not isinstance(options, list) or not options:
            issues.error(
                "INVALID_SPEED_OPTIONS",
                f"{path}.speedOptions",
                "speedOptions must be a non-empty array of positive numbers.",
            )
        else:
            valid = True
            for index, option in enumerate(options):
                if not _is_number(option) or float(option) <= 0:
                    valid = False
                    issues.error(
                        "INVALID_SPEED_OPTION",
                        f"{path}.speedOptions[{index}]",
                        "Each speed option must be a positive number.",
                    )
            if valid:
                info["speedOptions"] = [float(option) for option in options]
    if "maxPoints" in playback:
        max_points = playback["maxPoints"]
        if not _is_positive_int(max_points):
            issues.error(
                "INVALID_MAX_POINTS",
                f"{path}.maxPoints",
                "maxPoints must be a positive integer.",
            )
        else:
            info["maxPoints"] = max_points
    if "interpolation" in playback:
        interpolation = playback["interpolation"]
        if not _is_nonempty_str(interpolation):
            issues.error(
                "INVALID_INTERPOLATION",
                f"{path}.interpolation",
                "interpolation must be a non-empty string.",
            )
        else:
            key = interpolation.strip().upper()
            if key not in KNOWN_INTERPOLATIONS:
                issues.warning(
                    "UNKNOWN_INTERPOLATION",
                    f"{path}.interpolation",
                    f"Interpolation '{interpolation}' is not in the documented set.",
                )
            info["interpolation"] = interpolation.strip()
    return info


def _validate_panels(
    handler: dict,
    path: str,
    handler_types: set[str],
    panel_ids: set[str],
    issues: Issues,
) -> int:
    panels = handler.get("panels")
    if not isinstance(panels, list) or not panels:
        issues.error(
            "MISSING_PANELS",
            f"{path}.panels",
            "A panel handler needs a non-empty panels array.",
        )
        return 0

    for index, panel in enumerate(panels):
        panel_path = f"{path}.panels[{index}]"
        if not isinstance(panel, dict):
            issues.error("INVALID_PANEL", panel_path, "Panel must be an object.")
            continue
        panel_id = _id_text(panel.get("id"))
        if panel_id is None:
            issues.error("MISSING_PANEL_ID", f"{panel_path}.id", "Panel id is required.")
        elif panel_id in panel_ids:
            issues.error(
                "DUPLICATE_PANEL_ID",
                f"{panel_path}.id",
                f"Panel id '{panel_id}' is already used.",
            )
        else:
            panel_ids.add(panel_id)

        entity_type_value = panel.get("entityType")
        panel_type: str | None = None
        if not _is_nonempty_str(entity_type_value):
            issues.error(
                "MISSING_PANEL_ENTITY_TYPE",
                f"{panel_path}.entityType",
                "Panel entityType is required; panel fields must reference a known entity type.",
            )
        else:
            panel_type = entity_type_value.strip().upper()
            if panel_type not in SUPPORTED_ENTITY_TYPES:
                issues.error(
                    "UNKNOWN_ENTITY_TYPE",
                    f"{panel_path}.entityType",
                    f"Panel entity type '{entity_type_value}' is not supported.",
                )
                panel_type = None
            elif handler_types and panel_type not in handler_types:
                issues.warning(
                    "PANEL_TYPE_NOT_IN_HANDLER",
                    f"{panel_path}.entityType",
                    f"Panel type '{panel_type}' is not listed in the handler entityTypes.",
                )

        fields = panel.get("fields")
        if not isinstance(fields, list) or not fields:
            issues.error(
                "MISSING_PANEL_FIELDS",
                f"{panel_path}.fields",
                "Panel fields must be a non-empty array of field names.",
            )
        else:
            for field_index, field in enumerate(fields):
                if not _is_nonempty_str(field):
                    issues.error(
                        "INVALID_PANEL_FIELD",
                        f"{panel_path}.fields[{field_index}]",
                        "Panel field must be a non-empty string.",
                    )
        if "title" in panel and not _is_nonempty_str(panel["title"]):
            issues.warning(
                "INVALID_PANEL_TITLE",
                f"{panel_path}.title",
                "Panel title should be a non-empty string.",
            )
    return len(panels)


def _validate_handlers(
    handlers: object, issues: Issues
) -> tuple[list[dict], int, list[tuple[int, str]], set[str], list[str], set[str]]:
    """Validate handler shape and return summaries and deferred references."""
    handler_info: list[dict] = []
    channel_refs: list[tuple[int, str]] = []
    entity_id_refs: list[str] = []
    panel_ids: set[str] = set()
    tracked_types: set[str] = set()
    panel_count = 0
    if not isinstance(handlers, list) or not handlers:
        issues.error("MISSING_HANDLERS", "handlers", "At least one interaction handler is required.")
        return handler_info, panel_count, channel_refs, panel_ids, entity_id_refs, tracked_types

    seen_ids: set[str] = set()
    for index, handler in enumerate(handlers):
        path = f"handlers[{index}]"
        if not isinstance(handler, dict):
            issues.error("INVALID_HANDLER", path, "Handler must be an object.")
            continue
        handler_id = _id_text(handler.get("id"))
        if handler_id is None:
            issues.error("MISSING_HANDLER_ID", f"{path}.id", "Handler id is required.")
            continue
        if handler_id in seen_ids:
            issues.error(
                "DUPLICATE_HANDLER_ID",
                f"{path}.id",
                f"Handler id '{handler_id}' is duplicated; handler ids must be unique.",
            )
        seen_ids.add(handler_id)

        raw_type = handler.get("type")
        canonical_type: str | None = None
        if not _is_nonempty_str(raw_type):
            issues.error("MISSING_HANDLER_TYPE", f"{path}.type", "Handler type is required.")
        else:
            canonical_type = HANDLER_ALIASES.get(raw_type.strip().lower())
            if canonical_type is None:
                issues.error(
                    "UNKNOWN_HANDLER_TYPE",
                    f"{path}.type",
                    f"Handler type '{raw_type}' is not supported; use one of "
                    f"{', '.join(sorted(SUPPORTED_HANDLER_TYPES))}.",
                )

        entity_types = _validate_entity_types(handler.get("entityTypes"), f"{path}.entityTypes", issues)
        entity_ids = handler.get("entityIds")
        if entity_ids is not None:
            if not isinstance(entity_ids, list) or not entity_ids:
                issues.error(
                    "INVALID_HANDLER_ENTITY_IDS",
                    f"{path}.entityIds",
                    "entityIds must be a non-empty array when present.",
                )
            else:
                for entity_index, entity_id in enumerate(entity_ids):
                    entity_text = _id_text(entity_id)
                    if entity_text is None:
                        issues.error(
                            "INVALID_HANDLER_ENTITY_ID",
                            f"{path}.entityIds[{entity_index}]",
                            "entityId must be a non-empty string or number.",
                        )
                    else:
                        entity_id_refs.append(entity_text)

        channel_id = handler.get("channelId")
        if channel_id is not None:
            channel_text = _id_text(channel_id)
            if channel_text is None:
                issues.error(
                    "INVALID_CHANNEL_REF",
                    f"{path}.channelId",
                    "channelId must be a non-empty ID.",
                )
            else:
                channel_refs.append((index, channel_text))

        if canonical_type == "pick":
            event = handler.get("event")
            if event is not None:
                if not _is_nonempty_str(event):
                    issues.error("INVALID_PICK_EVENT", f"{path}.event", "Pick event must be a string.")
                elif event.strip().upper() not in KNOWN_PICK_EVENTS:
                    issues.warning(
                        "UNKNOWN_PICK_EVENT",
                        f"{path}.event",
                        f"Pick event '{event}' is not in the documented set.",
                    )
        elif canonical_type == "select":
            highlight = handler.get("highlight")
            if highlight is not None:
                if not isinstance(highlight, dict):
                    issues.error(
                        "INVALID_HIGHLIGHT",
                        f"{path}.highlight",
                        "highlight must be an object.",
                    )
                else:
                    color = highlight.get("color")
                    if color is not None and not _is_nonempty_str(color):
                        issues.error(
                            "INVALID_HIGHLIGHT_COLOR",
                            f"{path}.highlight.color",
                            "Highlight color must be a non-empty string.",
                        )
                    width = highlight.get("outlineWidth")
                    if width is not None and (not _is_number(width) or float(width) < 0):
                        issues.error(
                            "INVALID_OUTLINE_WIDTH",
                            f"{path}.highlight.outlineWidth",
                            "outlineWidth must be a non-negative number.",
                        )
        elif canonical_type == "flyTo":
            duration = handler.get("duration")
            if duration is not None and (not _is_number(duration) or float(duration) < 0):
                issues.error(
                    "INVALID_FLY_DURATION",
                    f"{path}.duration",
                    "Fly-to duration must be a non-negative number.",
                )
        elif canonical_type == "track":
            if "playback" in handler:
                _validate_playback(handler["playback"], f"{path}.playback", issues)
            tracked_types.update(entity_types)
            if not entity_types:
                issues.warning(
                    "TRACK_WITHOUT_ENTITY_TYPES",
                    f"{path}.entityTypes",
                    "Track handler does not declare which entity types it can replay.",
                )
        elif canonical_type == "filter":
            fields = handler.get("fields")
            if not isinstance(fields, list) or not fields:
                issues.error(
                    "MISSING_FILTER_FIELDS",
                    f"{path}.fields",
                    "Filter handler needs a non-empty fields array.",
                )
            else:
                for field_index, field in enumerate(fields):
                    if not _is_nonempty_str(field):
                        issues.error(
                            "INVALID_FILTER_FIELD",
                            f"{path}.fields[{field_index}]",
                            "Filter field must be a non-empty string.",
                        )
                    elif field.strip() not in KNOWN_FILTER_FIELDS:
                        issues.warning(
                            "UNKNOWN_FILTER_FIELD",
                            f"{path}.fields[{field_index}]",
                            f"Filter field '{field}' is not in the documented set.",
                        )
        elif canonical_type == "panel":
            panel_count += _validate_panels(handler, path, entity_types, panel_ids, issues)

        if canonical_type:
            handler_info.append(
                {
                    "id": handler_id,
                    "type": canonical_type,
                    "entityTypes": sorted(entity_types),
                }
            )
    return handler_info, panel_count, channel_refs, panel_ids, entity_id_refs, tracked_types


def _validate_permission_rules(
    rules: object,
    tracked_types: set[str],
    issues: Issues,
) -> tuple[list[dict], int]:
    info: list[dict] = []
    if rules is None or (isinstance(rules, list) and not rules):
        issues.error(
            "MISSING_PERMISSION_RULES",
            "permissionRules",
            "Permission rules are required; interactions must be permission-aware.",
        )
        return info, 0
    if not isinstance(rules, list):
        issues.error("INVALID_PERMISSION_RULES", "permissionRules", "permissionRules must be an array.")
        return info, 0

    seen_ids: set[str] = set()
    track_actions: list[tuple[set[str], str]] = []
    for index, rule in enumerate(rules):
        path = f"permissionRules[{index}]"
        if not isinstance(rule, dict):
            issues.error("INVALID_PERMISSION_RULE", path, "Permission rule must be an object.")
            continue
        rule_id = _id_text(rule.get("id"))
        if rule_id is None:
            issues.error("MISSING_PERMISSION_ID", f"{path}.id", "Permission rule id is required.")
        elif rule_id in seen_ids:
            issues.error(
                "DUPLICATE_PERMISSION_ID",
                f"{path}.id",
                f"Permission rule id '{rule_id}' is duplicated.",
            )
        else:
            seen_ids.add(rule_id)

        action_value = rule.get("action")
        action: str | None = None
        if not _is_nonempty_str(action_value):
            issues.error("MISSING_PERMISSION_ACTION", f"{path}.action", "Permission action is required.")
        else:
            action = action_value.strip().upper()
            if action not in KNOWN_PERMISSION_ACTIONS:
                issues.error(
                    "UNKNOWN_PERMISSION_ACTION",
                    f"{path}.action",
                    f"Permission action '{action_value}' is not known.",
                )
                action = None

        entity_types = _validate_entity_types(rule.get("entityTypes"), f"{path}.entityTypes", issues)
        roles = rule.get("roles")
        roles_info: list[str] = []
        if roles is None:
            issues.warning(
                "PERMISSION_RULE_WITHOUT_ROLES",
                f"{path}.roles",
                "Permission rule has no roles; this may grant the action too broadly.",
            )
        elif not isinstance(roles, list) or not roles:
            issues.error(
                "INVALID_PERMISSION_ROLES",
                f"{path}.roles",
                "roles must be a non-empty array when present.",
            )
        else:
            for role_index, role in enumerate(roles):
                if not _is_nonempty_str(role):
                    issues.error(
                        "INVALID_PERMISSION_ROLE",
                        f"{path}.roles[{role_index}]",
                        "Role must be a non-empty string.",
                    )
                else:
                    roles_info.append(role.strip())

        scope = rule.get("scope")
        if scope is not None:
            if not _is_nonempty_str(scope):
                issues.error("INVALID_PERMISSION_SCOPE", f"{path}.scope", "Scope must be a string.")
            elif scope.strip().upper() not in KNOWN_SCOPES:
                issues.warning(
                    "UNKNOWN_PERMISSION_SCOPE",
                    f"{path}.scope",
                    f"Permission scope '{scope}' is not in the documented set.",
                )

        fields = rule.get("fields")
        if fields is not None:
            if not isinstance(fields, list) or not fields:
                issues.error(
                    "INVALID_PERMISSION_FIELDS",
                    f"{path}.fields",
                    "fields must be a non-empty array when present.",
                )
            else:
                for field_index, field in enumerate(fields):
                    if not _is_nonempty_str(field):
                        issues.error(
                            "INVALID_PERMISSION_FIELD",
                            f"{path}.fields[{field_index}]",
                            "Permission field must be a non-empty string.",
                        )

        if action == "VIEW_TRACK":
            track_actions.append((entity_types, rule_id or path))
        info.append(
            {
                "id": rule_id or path,
                "action": action or "-",
                "entityTypes": sorted(entity_types),
                "roles": roles_info,
                "scope": scope.strip().upper() if _is_nonempty_str(scope) else None,
            }
        )

    for tracked_type in sorted(tracked_types):
        covered = any(
            not entity_types or tracked_type in entity_types
            for entity_types, _ in track_actions
        )
        if not covered:
            issues.error(
                "MISSING_TRACK_PERMISSION",
                "permissionRules",
                f"Track playback for {tracked_type} requires a VIEW_TRACK permission rule.",
            )
    return info, len(rules)


def _validate_event_channels(channels: object, issues: Issues) -> tuple[list[dict], set[str]]:
    info: list[dict] = []
    if channels is None:
        issues.warning(
            "NO_EVENT_CHANNELS",
            "eventChannels",
            "No realtime channels declared; track and live status updates need a channel.",
        )
        return info, set()
    if not isinstance(channels, list):
        issues.error("INVALID_EVENT_CHANNELS", "eventChannels", "eventChannels must be an array.")
        return info, set()

    seen_ids: set[str] = set()
    for index, channel in enumerate(channels):
        path = f"eventChannels[{index}]"
        if not isinstance(channel, dict):
            issues.error("INVALID_EVENT_CHANNEL", path, "Event channel must be an object.")
            continue
        channel_id = _id_text(channel.get("id"))
        if channel_id is None:
            issues.error("MISSING_CHANNEL_ID", f"{path}.id", "Event channel id is required.")
        elif channel_id in seen_ids:
            issues.error(
                "DUPLICATE_CHANNEL_ID",
                f"{path}.id",
                f"Event channel id '{channel_id}' is duplicated.",
            )
        else:
            seen_ids.add(channel_id)

        name = channel.get("name")
        if not _is_nonempty_str(name):
            issues.error(
                "MISSING_CHANNEL_NAME",
                f"{path}.name",
                "Realtime channel name must be present and non-empty.",
            )
        transport = channel.get("transport")
        if transport is not None:
            if not _is_nonempty_str(transport):
                issues.error("INVALID_CHANNEL_TRANSPORT", f"{path}.transport", "transport must be a string.")
            elif transport.strip().upper() not in KNOWN_TRANSPORTS:
                issues.warning(
                    "UNKNOWN_CHANNEL_TRANSPORT",
                    f"{path}.transport",
                    f"Transport '{transport}' is not in the documented set.",
                )
        event_types = channel.get("eventTypes")
        event_type_info: list[str] = []
        if event_types is not None:
            if not isinstance(event_types, list) or not event_types:
                issues.error(
                    "INVALID_CHANNEL_EVENT_TYPES",
                    f"{path}.eventTypes",
                    "eventTypes must be a non-empty array when present.",
                )
            else:
                for event_index, event_type in enumerate(event_types):
                    if not _is_nonempty_str(event_type):
                        issues.error(
                            "INVALID_CHANNEL_EVENT_TYPE",
                            f"{path}.eventTypes[{event_index}]",
                            "Event type must be a non-empty string.",
                        )
                    else:
                        event_text = event_type.strip().upper()
                        if event_text not in KNOWN_EVENT_TYPES:
                            issues.warning(
                                "UNKNOWN_EVENT_TYPE",
                                f"{path}.eventTypes[{event_index}]",
                                f"Event type '{event_type}' is not in the documented set.",
                            )
                        event_type_info.append(event_text)
        url = channel.get("url")
        if url is not None and not _is_nonempty_str(url):
            issues.error("INVALID_CHANNEL_URL", f"{path}.url", "Channel URL must be a non-empty string.")
        info.append(
            {
                "id": channel_id or path,
                "name": name.strip() if _is_nonempty_str(name) else None,
                "transport": transport.strip().upper() if _is_nonempty_str(transport) else None,
                "eventTypes": event_type_info,
            }
        )
    return info, seen_ids


def _validate_entities(entities: object, issues: Issues) -> tuple[dict[str, str], int]:
    registry: dict[str, str] = {}
    if entities is None:
        return registry, 0
    if not isinstance(entities, list):
        issues.error("INVALID_ENTITIES", "entities", "entities must be an array.")
        return registry, 0
    if not entities:
        issues.warning("EMPTY_ENTITY_REGISTRY", "entities", "Entity registry is empty.")
    for index, entity in enumerate(entities):
        path = f"entities[{index}]"
        if not isinstance(entity, dict):
            issues.error("INVALID_ENTITY", path, "Entity must be an object.")
            continue
        entity_id = _id_text(entity.get("entityId"))
        if entity_id is None:
            issues.error("MISSING_ENTITY_ID", f"{path}.entityId", "entityId is required.")
            continue
        if entity_id in registry:
            issues.error(
                "DUPLICATE_ENTITY_ID",
                f"{path}.entityId",
                f"Entity id '{entity_id}' is duplicated.",
            )
            continue
        entity_type_value = entity.get("entityType")
        if not _is_nonempty_str(entity_type_value):
            issues.error("MISSING_ENTITY_TYPE", f"{path}.entityType", "entityType is required.")
            continue
        entity_type = entity_type_value.strip().upper()
        if entity_type not in SUPPORTED_ENTITY_TYPES:
            issues.error(
                "UNKNOWN_ENTITY_TYPE",
                f"{path}.entityType",
                f"Entity type '{entity_type_value}' is not supported.",
            )
            continue
        registry[entity_id] = entity_type
    return registry, len(entities)


def _extract_bindings(data: object, issues: Issues) -> list[dict] | None:
    if data is None:
        return None
    if isinstance(data, list):
        bindings = data
    elif isinstance(data, dict):
        bindings = data.get("bindings")
        if not isinstance(bindings, list):
            issues.error(
                "INVALID_BINDINGS",
                "bindings",
                "bindings.json must contain a bindings array.",
            )
            return []
    else:
        issues.error("INVALID_BINDINGS", "bindings", "bindings.json root must be an object or array.")
        return []

    result: list[dict] = []
    seen_ids: set[str] = set()
    for index, binding in enumerate(bindings):
        path = f"bindings[{index}]"
        if not isinstance(binding, dict):
            issues.error("INVALID_BINDING", path, "Binding must be an object.")
            continue
        binding_id = _id_text(binding.get("bindingId", binding.get("id")))
        if binding_id is None:
            issues.error("MISSING_BINDING_ID", f"{path}.bindingId", "Binding id is required.")
        elif binding_id in seen_ids:
            issues.error(
                "DUPLICATE_BINDING_ID",
                f"{path}.bindingId",
                f"Binding id '{binding_id}' is duplicated.",
            )
        else:
            seen_ids.add(binding_id)

        entity_id = _id_text(binding.get("entityId"))
        if entity_id is None:
            issues.error("MISSING_BINDING_ENTITY_ID", f"{path}.entityId", "Binding entityId is required.")
        object_id = _id_text(binding.get("objectId"))
        if object_id is None:
            issues.error("MISSING_OBJECT_ID", f"{path}.objectId", "Binding objectId is required.")

        entity_type_value = binding.get("entityType")
        entity_type = None
        if not _is_nonempty_str(entity_type_value):
            issues.error("MISSING_BINDING_ENTITY_TYPE", f"{path}.entityType", "entityType is required.")
        else:
            entity_type = entity_type_value.strip().upper()
            if entity_type not in SUPPORTED_ENTITY_TYPES:
                issues.error(
                    "UNKNOWN_ENTITY_TYPE",
                    f"{path}.entityType",
                    f"Entity type '{entity_type_value}' is not supported.",
                )
                entity_type = None
        if entity_id:
            result.append(
                {
                    "bindingId": binding_id,
                    "entityId": entity_id,
                    "entityType": entity_type,
                    "objectId": object_id,
                }
            )
    return result


def _validate_bindings(
    bindings: list[dict] | None,
    registry: dict[str, str],
    issues: Issues,
) -> int:
    if bindings is None:
        return 0
    if not registry:
        issues.warning(
            "NO_ENTITY_REGISTRY",
            "entities",
            "No entity registry in the contract; binding entity IDs cannot be cross-checked.",
        )
    for index, binding in enumerate(bindings):
        entity_id = binding["entityId"]
        if registry and entity_id not in registry:
            issues.error(
                "UNKNOWN_ENTITY_ID",
                f"bindings[{index}].entityId",
                f"Binding references entity '{entity_id}', which is not in the contract registry.",
            )
            continue
        if registry and binding["entityType"] and registry[entity_id] != binding["entityType"]:
            issues.error(
                "ENTITY_TYPE_MISMATCH",
                f"bindings[{index}].entityType",
                f"Binding says {binding['entityType']} but registry says {registry[entity_id]} "
                f"for entity '{entity_id}'.",
            )
    return len(bindings)


def validate_interactions(
    contract: object,
    bindings_data: object | None = None,
    sources: dict | None = None,
) -> dict:
    """Validate an interaction contract and optional bindings, returning a report."""
    issues = Issues()
    contract_info: dict = {
        "sceneId": None,
        "mineId": None,
        "contractVersion": None,
        "handlerCount": 0,
        "panelCount": 0,
        "permissionRuleCount": 0,
        "eventChannelCount": 0,
        "entityCount": 0,
        "handlers": [],
        "permissions": [],
        "channels": [],
        "trackPlayback": {},
    }
    if not isinstance(contract, dict):
        issues.error("INVALID_CONTRACT", "contract", "Interaction contract root must be a JSON object.")
        return _build_report(issues, contract_info, None, 0, sources)

    contract_info["sceneId"] = _id_text(contract.get("sceneId"))
    if contract_info["sceneId"] is None:
        issues.error("MISSING_SCENE_ID", "sceneId", "sceneId is required.")
    contract_info["mineId"] = _id_text(contract.get("mineId"))
    if contract_info["mineId"] is None:
        issues.error("MISSING_MINE_ID", "mineId", "mineId is required.")
    version = contract.get("contractVersion")
    if version is not None:
        if not _is_nonempty_str(version):
            issues.error("INVALID_CONTRACT_VERSION", "contractVersion", "contractVersion must be a string.")
        else:
            contract_info["contractVersion"] = version.strip()
    else:
        issues.warning(
            "MISSING_CONTRACT_VERSION",
            "contractVersion",
            "contractVersion is missing; record the contract version explicitly.",
        )

    registry, entity_count = _validate_entities(contract.get("entities"), issues)
    contract_info["entityCount"] = entity_count

    (
        handler_info,
        panel_count,
        channel_refs,
        _panel_ids,
        entity_id_refs,
        tracked_types,
    ) = _validate_handlers(contract.get("handlers"), issues)
    contract_info["handlers"] = handler_info
    contract_info["handlerCount"] = len(handler_info)
    contract_info["panelCount"] = panel_count

    permission_info, permission_count = _validate_permission_rules(
        contract.get("permissionRules"), tracked_types, issues
    )
    contract_info["permissions"] = permission_info
    contract_info["permissionRuleCount"] = permission_count

    channel_info, channel_ids = _validate_event_channels(contract.get("eventChannels"), issues)
    contract_info["channels"] = channel_info
    contract_info["eventChannelCount"] = len(channel_info)

    for handler_index, channel_id in channel_refs:
        if channel_id not in channel_ids:
            issues.error(
                "UNKNOWN_CHANNEL_REF",
                f"handlers[{handler_index}].channelId",
                f"Handler references channel '{channel_id}', which is not declared.",
            )

    playback = contract.get("trackPlayback")
    if playback is None:
        if tracked_types:
            issues.warning(
                "MISSING_TRACK_PLAYBACK",
                "trackPlayback",
                "Track handlers exist but no default track playback settings are declared.",
            )
    else:
        contract_info["trackPlayback"] = _validate_playback(playback, "trackPlayback", issues)

    bindings = _extract_bindings(bindings_data, issues)
    binding_count = _validate_bindings(bindings, registry, issues)

    if entity_id_refs:
        allowed_ids = set(registry)
        if bindings:
            allowed_ids.update(
                binding["entityId"]
                for binding in bindings
                if not registry or binding["entityId"] in registry
            )
        if not allowed_ids:
            for entity_id in entity_id_refs:
                issues.error(
                    "UNRESOLVED_ENTITY_ID",
                    "handlers",
                    f"Handler references entity '{entity_id}' but no registry or bindings exist.",
                )
        else:
            for entity_id in entity_id_refs:
                if entity_id not in allowed_ids:
                    issues.error(
                        "UNKNOWN_ENTITY_REF",
                        "handlers",
                        f"Handler references entity '{entity_id}', which is not declared.",
                    )

    return _build_report(issues, contract_info, bindings, binding_count, sources)


def _build_report(
    issues: Issues,
    contract_info: dict,
    bindings: list[dict] | None,
    binding_count: int,
    sources: dict | None,
) -> dict:
    errors = issues.errors
    warnings = issues.warnings
    return {
        "status": "FAIL" if errors else "PASS",
        "validator": "mine-scene-interaction/validate_interactions",
        "rulesVersion": "0.1",
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "handlers": contract_info.get("handlerCount", 0),
            "panels": contract_info.get("panelCount", 0),
            "permissionRules": contract_info.get("permissionRuleCount", 0),
            "eventChannels": contract_info.get("eventChannelCount", 0),
            "entities": contract_info.get("entityCount", 0),
            "bindings": binding_count,
        },
        "contract": contract_info,
        "bindings": {
            "provided": bindings is not None,
            "count": binding_count,
        },
        "sources": sources or {},
        "errors": errors,
        "warnings": warnings,
    }


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    contract = report["contract"]
    lines = [
        "# Scene Interaction Validation Report",
        "",
        f"- **Status**: {report['status']}",
        f"- **Errors**: {summary['errors']}",
        f"- **Warnings**: {summary['warnings']}",
        f"- **Handlers**: {summary['handlers']}",
        f"- **Panels**: {summary['panels']}",
        f"- **Permission rules**: {summary['permissionRules']}",
        f"- **Event channels**: {summary['eventChannels']}",
        f"- **Registered entities**: {summary['entities']}",
        f"- **Bindings**: {summary['bindings']}",
    ]
    if contract.get("sceneId"):
        lines.append(f"- **Scene**: `{contract['sceneId']}`")
    if contract.get("mineId"):
        lines.append(f"- **Mine**: `{contract['mineId']}`")

    lines.extend(
        [
            "",
            "## Handlers",
            "",
            "| ID | Type | Entity types |",
            "|---|---|---|",
        ]
    )
    for handler in contract.get("handlers", []):
        entity_types = ", ".join(handler.get("entityTypes", [])) or "-"
        lines.append(f"| `{handler.get('id')}` | {handler.get('type')} | {entity_types} |")
    if not contract.get("handlers"):
        lines.append("| - | - | - |")

    lines.extend(
        [
            "",
            "## Permission Rules",
            "",
            "| ID | Action | Entity types | Roles | Scope |",
            "|---|---|---|---|---|",
        ]
    )
    for rule in contract.get("permissions", []):
        entity_types = ", ".join(rule.get("entityTypes", [])) or "-"
        roles = ", ".join(rule.get("roles", [])) or "-"
        lines.append(
            f"| `{rule.get('id')}` | {rule.get('action')} | {entity_types} | "
            f"{roles} | {rule.get('scope') or '-'} |"
        )
    if not contract.get("permissions"):
        lines.append("| - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## Event Channels",
            "",
            "| ID | Name | Transport | Event types |",
            "|---|---|---|---|",
        ]
    )
    for channel in contract.get("channels", []):
        event_types = ", ".join(channel.get("eventTypes", [])) or "-"
        lines.append(
            f"| `{channel.get('id')}` | {channel.get('name') or '-'} | "
            f"{channel.get('transport') or '-'} | {event_types} |"
        )
    if not contract.get("channels"):
        lines.append("| - | - | - | - |")

    lines.extend(["", "## Errors", ""])
    if report["errors"]:
        lines.extend(
            f"- `{entry['code']}` at `{entry['path']}` — {entry['message']}"
            for entry in report["errors"]
        )
    else:
        lines.append("- None")

    lines.extend(["", "## Warnings", ""])
    if report["warnings"]:
        lines.extend(
            f"- `{entry['code']}` at `{entry['path']}` — {entry['message']}"
            for entry in report["warnings"]
        )
    else:
        lines.append("- None")

    sources = report.get("sources") or {}
    if sources:
        lines.extend(["", "## Sources", ""])
        for label, source in sources.items():
            lines.append(
                f"- **{label}**: `{source.get('path', '-')}` "
                f"(SHA-256 `{source.get('sha256', '-')}`)"
            )

    lines.extend(
        [
            "",
            "## Rules Checked",
            "",
            "- Handler IDs are unique and every handler uses a supported type.",
            "- Handler and panel entity types are PERSON, MONITOR_DEVICE, MACHINERY or INFRASTRUCTURE.",
            "- Panels declare an entity type and a non-empty field list.",
            "- Permission rules use known actions and cover track playback.",
            "- Realtime channels have non-empty names and valid references.",
            "- Track playback settings are positive and finite.",
            "- Optional bindings reference entities that exist in the contract registry.",
            "",
            "> This report validates a contract and bindings only. It does not run a "
            "Vue/Cesium frontend, fetch business data or enforce permissions at runtime.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: dict, output_path: str, markdown_path: str) -> dict[str, str]:
    common.write_json(output_path, report)
    common.write_text(markdown_path, render_markdown(report))
    return {"json": str(Path(output_path)), "markdown": str(Path(markdown_path))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a mine scene interaction contract and optional bindings."
    )
    parser.add_argument("contract", help="Path to interaction_contract.json")
    parser.add_argument("--bindings", help="Optional path to bindings.json")
    parser.add_argument(
        "--output",
        default="interaction_validation.json",
        help="JSON validation report path (default: interaction_validation.json)",
    )
    parser.add_argument(
        "--markdown",
        default="interaction_validation.md",
        help="Markdown validation report path (default: interaction_validation.md)",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Exit 0 even when validation errors are found.",
    )
    args = parser.parse_args(argv)

    contract = common.load_json(args.contract)
    bindings = common.load_json(args.bindings) if args.bindings else None
    sources = {"contract": common.source_manifest(args.contract)}
    if args.bindings:
        sources["bindings"] = common.source_manifest(args.bindings)
    report = validate_interactions(contract, bindings_data=bindings, sources=sources)
    paths = write_outputs(report, args.output, args.markdown)

    summary = report["summary"]
    print(
        f"Interaction validation: {report['status']} — {summary['errors']} error(s), "
        f"{summary['warnings']} warning(s), {summary['handlers']} handler(s), "
        f"{summary['permissionRules']} permission rule(s), {summary['bindings']} binding(s)."
    )
    for entry in report["errors"][:10]:
        print(f"  ERROR {entry['code']}: {entry['path']} — {entry['message']}")
    print("Outputs: " + ", ".join(paths.values()))

    if report["errors"] and not args.no_fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
