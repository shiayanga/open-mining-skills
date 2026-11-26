#!/usr/bin/env python3
"""Validate three-layer bindings between business entities, scene objects and models.

The validator is file based. It checks referential integrity, mine/scene scope,
coordinate-system compatibility, duplicate entity-object pairs and primary
binding conflicts. It never modifies the source JSON files.

A Spring Boot persistence/API adapter for ``mine_entity_binding`` is future work;
this script is the v0.1 contract check and query tool.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ENTITY_TYPES = {"PERSON", "MONITOR_DEVICE", "MACHINERY", "INFRASTRUCTURE"}
BINDING_TYPES = {"ENTITY_MODEL", "ENTITY_MARKER"}
SEVERITY_RANK = {"warning": 1, "error": 2}


def as_id(value: Any) -> str | None:
    """Return a non-empty identifier as a string, or None when invalid.

    Numeric IDs used by the database design are accepted and normalised to
    strings so that cross-file comparisons are type-stable.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def as_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def add_issue(
    issues: list[dict],
    severity: str,
    code: str,
    message: str,
    **context: Any,
) -> None:
    issue = {"severity": severity, "code": code, "message": message}
    for key, value in context.items():
        if value is not None:
            issue[key] = value
    issues.append(issue)


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


def load_collection(path: str | Path, keys: tuple[str, ...], label: str) -> list:
    """Load a JSON list or a wrapper object holding the list under one of keys."""
    data = read_json(path)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
    joined = ", ".join(keys)
    raise SystemExit(
        f"{label} file must be a JSON list or an object with one of "
        f"these list keys: {joined}"
    )


def declared_coordinate_systems(record: dict) -> list[tuple[str, str]]:
    """Return the non-empty coordinate-system declarations of a record."""
    declared: list[tuple[str, str]] = []
    for key in ("coordinateSystemId", "coordinateSystem", "crs"):
        value = record.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, dict):
            value = value.get("id") or value.get("code")
        normalized = as_id(value)
        if normalized:
            declared.append((key, normalized))
    return declared


def resolve_coordinate_system(record: dict, issues: list[dict], context: dict) -> str | None:
    declared = declared_coordinate_systems(record)
    values = {value for _, value in declared}
    if len(values) > 1:
        add_issue(
            issues,
            "error",
            "COORDINATE_SYSTEM_CONFLICT",
            "Record declares inconsistent coordinate systems: "
            + ", ".join(f"{key}={value}" for key, value in declared),
            **context,
        )
    return declared[0][1] if declared else None


def normalize_entity(record: Any, index: int, issues: list[dict]) -> dict | None:
    context = {"recordType": "entity", "recordIndex": index}
    if not isinstance(record, dict):
        add_issue(issues, "error", "INVALID_RECORD", "Entity entry must be an object.", **context)
        return None
    entity_id = as_id(record.get("entityId"))
    if not entity_id:
        add_issue(issues, "error", "MISSING_ENTITY_ID", "Entity requires a non-empty entityId.", **context)
    entity_type = record.get("entityType")
    entity_type = entity_type.strip() if isinstance(entity_type, str) else entity_type
    if not entity_type:
        add_issue(issues, "error", "MISSING_ENTITY_TYPE", "Entity requires an entityType.", **context, entityId=entity_id)
    elif entity_type not in ENTITY_TYPES:
        add_issue(
            issues,
            "warning",
            "UNKNOWN_ENTITY_TYPE",
            f"Entity type '{entity_type}' is outside the v0.1 catalog.",
            **context,
            entityId=entity_id,
            entityType=entity_type,
        )
    mine_id = as_id(record.get("mineId"))
    if not mine_id:
        add_issue(issues, "error", "MISSING_MINE_ID", "Entity requires a non-empty mineId.", **context, entityId=entity_id)
    scene_id = as_id(record.get("sceneId"))
    coordinate_system = resolve_coordinate_system(
        record, issues, {**context, "entityId": entity_id}
    )
    return {
        "entityId": entity_id,
        "entityType": entity_type,
        "mineId": mine_id,
        "sceneId": scene_id,
        "name": record.get("name"),
        "coordinateSystemId": coordinate_system,
        "source": record,
    }


def normalize_object(record: Any, index: int, issues: list[dict]) -> dict | None:
    context = {"recordType": "sceneObject", "recordIndex": index}
    if not isinstance(record, dict):
        add_issue(issues, "error", "INVALID_RECORD", "Scene object entry must be an object.", **context)
        return None
    object_id = as_id(record.get("objectId"))
    if not object_id:
        add_issue(issues, "error", "MISSING_OBJECT_ID", "Scene object requires a non-empty objectId.", **context)
    mine_id = as_id(record.get("mineId"))
    if not mine_id:
        add_issue(issues, "error", "MISSING_MINE_ID", "Scene object requires a non-empty mineId.", **context, objectId=object_id)
    scene_id = as_id(record.get("sceneId"))
    if not scene_id:
        add_issue(issues, "error", "MISSING_SCENE_ID", "Scene object requires a non-empty sceneId.", **context, objectId=object_id)
    model_id = as_id(record.get("modelId"))
    model_node_id = record.get("modelNodeId")
    if model_node_id is not None:
        if not as_id(model_node_id):
            add_issue(
                issues,
                "error",
                "EMPTY_MODEL_NODE_ID",
                "modelNodeId must be a non-empty string when present.",
                **context,
                objectId=object_id,
            )
        model_node_id = as_id(model_node_id)
    coordinate_system = resolve_coordinate_system(
        record, issues, {**context, "objectId": object_id}
    )
    return {
        "objectId": object_id,
        "mineId": mine_id,
        "sceneId": scene_id,
        "objectType": record.get("objectType"),
        "name": record.get("name"),
        "modelId": model_id,
        "modelNodeId": model_node_id,
        "coordinateSystemId": coordinate_system,
        "active": as_bool(record.get("active")),
        "source": record,
    }


def normalize_model(record: Any, index: int, issues: list[dict]) -> dict | None:
    context = {"recordType": "model", "recordIndex": index}
    if not isinstance(record, dict):
        add_issue(issues, "error", "INVALID_RECORD", "Model entry must be an object.", **context)
        return None
    model_id = as_id(record.get("modelId"))
    if not model_id:
        add_issue(issues, "error", "MISSING_MODEL_ID", "Model requires a non-empty modelId.", **context)
    mine_id = as_id(record.get("mineId"))
    if record.get("mineId") is not None and not mine_id:
        add_issue(issues, "error", "EMPTY_MINE_ID", "Model mineId must be non-empty when present.", **context, modelId=model_id)
    nodes: list[str] = []
    raw_nodes = record.get("nodes", record.get("modelNodeIds"))
    if raw_nodes is not None:
        if not isinstance(raw_nodes, list):
            add_issue(issues, "error", "INVALID_MODEL_NODES", "Model nodes must be a list.", **context, modelId=model_id)
        else:
            for node in raw_nodes:
                if isinstance(node, dict):
                    node = node.get("nodeId") or node.get("name") or node.get("id")
                node_id = as_id(node)
                if node_id:
                    nodes.append(node_id)
                else:
                    add_issue(
                        issues,
                        "warning",
                        "EMPTY_MODEL_NODE",
                        "Model contains an empty or invalid node entry.",
                        **context,
                        modelId=model_id,
                    )
    coordinate_system = resolve_coordinate_system(
        record, issues, {**context, "modelId": model_id}
    )
    return {
        "modelId": model_id,
        "mineId": mine_id,
        "name": record.get("name"),
        "assetUrl": record.get("assetUrl"),
        "nodes": nodes,
        "coordinateSystemId": coordinate_system,
        "source": record,
    }


def normalize_binding(record: Any, index: int, issues: list[dict]) -> dict | None:
    context = {"recordType": "binding", "recordIndex": index}
    if not isinstance(record, dict):
        add_issue(issues, "error", "INVALID_RECORD", "Binding entry must be an object.", **context)
        return None
    binding_id = as_id(record.get("bindingId")) or f"BINDING-{index + 1:04d}"
    entity_id = as_id(record.get("entityId"))
    object_id = as_id(record.get("objectId"))
    if not entity_id:
        add_issue(issues, "error", "MISSING_ENTITY_ID", "Binding requires a non-empty entityId.", **context, bindingId=binding_id)
    if not object_id:
        add_issue(issues, "error", "MISSING_OBJECT_ID", "Binding requires a non-empty objectId.", **context, bindingId=binding_id)
    binding_type = record.get("bindingType")
    binding_type = binding_type.strip() if isinstance(binding_type, str) else binding_type
    if not binding_type:
        add_issue(issues, "error", "MISSING_BINDING_TYPE", "Binding requires a bindingType.", **context, bindingId=binding_id)
    elif binding_type not in BINDING_TYPES:
        add_issue(
            issues,
            "error",
            "INVALID_BINDING_TYPE",
            f"bindingType must be one of {sorted(BINDING_TYPES)}.",
            **context,
            bindingId=binding_id,
            bindingType=binding_type,
        )
    model_id = as_id(record.get("modelId"))
    if record.get("modelId") is not None and not model_id:
        add_issue(issues, "error", "EMPTY_MODEL_ID", "Binding modelId must be non-empty when present.", **context, bindingId=binding_id)
    model_node_id = record.get("modelNodeId")
    if model_node_id is not None:
        if not as_id(model_node_id):
            add_issue(
                issues,
                "error",
                "EMPTY_MODEL_NODE_ID",
                "modelNodeId must be a non-empty string when present.",
                **context,
                bindingId=binding_id,
            )
        model_node_id = as_id(model_node_id)
    is_primary = as_bool(record.get("isPrimary", False))
    if is_primary is None:
        add_issue(issues, "error", "INVALID_IS_PRIMARY", "isPrimary must be a boolean.", **context, bindingId=binding_id)
        is_primary = False
    active = as_bool(record.get("active", True))
    if active is None:
        add_issue(issues, "error", "INVALID_ACTIVE", "active must be a boolean.", **context, bindingId=binding_id)
        active = True
    coordinate_system = resolve_coordinate_system(
        record, issues, {**context, "bindingId": binding_id}
    )
    mine_id = as_id(record.get("mineId"))
    scene_id = as_id(record.get("sceneId"))
    return {
        "bindingId": binding_id,
        "entityId": entity_id,
        "objectId": object_id,
        "bindingType": binding_type,
        "modelId": model_id,
        "modelNodeId": model_node_id,
        "isPrimary": is_primary,
        "active": active,
        "mineId": mine_id,
        "sceneId": scene_id,
        "coordinateSystemId": coordinate_system,
        "source": record,
    }


def _index_unique(
    records: list[dict | None],
    id_key: str,
    issues: list[dict],
    record_type: str,
) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for record in records:
        if not record:
            continue
        record_id = record.get(id_key)
        if not record_id:
            continue
        if record_id in index:
            add_issue(
                issues,
                "error",
                "DUPLICATE_ID",
                f"Duplicate {record_type} identifier '{record_id}'.",
                recordType=record_type,
                **{id_key: record_id},
            )
            continue
        index[record_id] = record
    return index


def _check_scope_pair(
    left: dict,
    right: dict,
    left_label: str,
    right_label: str,
    issues: list[dict],
    **context: Any,
) -> None:
    left_mine = left.get("mineId")
    right_mine = right.get("mineId")
    if left_mine and right_mine and left_mine != right_mine:
        add_issue(
            issues,
            "error",
            "CROSS_MINE",
            f"{left_label} belongs to mine '{left_mine}' but {right_label} "
            f"belongs to mine '{right_mine}'.",
            **context,
        )
    left_scene = left.get("sceneId")
    right_scene = right.get("sceneId")
    if left_scene and right_scene and left_scene != right_scene:
        add_issue(
            issues,
            "error",
            "CROSS_SCENE",
            f"{left_label} belongs to scene '{left_scene}' but {right_label} "
            f"belongs to scene '{right_scene}'.",
            **context,
        )


def _check_coordinate_pair(
    left: dict,
    right: dict,
    left_label: str,
    right_label: str,
    issues: list[dict],
    **context: Any,
) -> None:
    left_cs = left.get("coordinateSystemId")
    right_cs = right.get("coordinateSystemId")
    if left_cs and right_cs and left_cs != right_cs:
        add_issue(
            issues,
            "error",
            "COORDINATE_SYSTEM_MISMATCH",
            f"{left_label} uses coordinate system '{left_cs}' but "
            f"{right_label} uses '{right_cs}'.",
            **context,
        )


def validate_binding_set(
    entities: list,
    scene_objects: list,
    models: list,
    bindings: list,
    query_entity_id: str | None = None,
) -> dict:
    """Validate all four registries and return a report dictionary."""
    issues: list[dict] = []

    entity_rows = [normalize_entity(item, index, issues) for index, item in enumerate(entities)]
    object_rows = [normalize_object(item, index, issues) for index, item in enumerate(scene_objects)]
    model_rows = [normalize_model(item, index, issues) for index, item in enumerate(models)]
    binding_rows = [normalize_binding(item, index, issues) for index, item in enumerate(bindings)]

    entity_index = _index_unique(entity_rows, "entityId", issues, "entity")
    object_index = _index_unique(object_rows, "objectId", issues, "sceneObject")
    model_index = _index_unique(model_rows, "modelId", issues, "model")
    binding_index = _index_unique(binding_rows, "bindingId", issues, "binding")

    entity_bindings: dict[str, list[dict]] = defaultdict(list)
    object_bindings: dict[str, list[dict]] = defaultdict(list)
    entity_objects: dict[str, list[str]] = defaultdict(list)
    object_entities: dict[str, list[str]] = defaultdict(list)
    primary_by_entity: dict[str, list[str]] = defaultdict(list)
    pair_seen: dict[tuple[str, str], str] = {}

    for binding in binding_rows:
        if not binding:
            continue
        binding_id = binding["bindingId"]
        entity_id = binding["entityId"]
        object_id = binding["objectId"]
        context = {
            "recordType": "binding",
            "bindingId": binding_id,
            "entityId": entity_id,
            "objectId": object_id,
        }

        entity = entity_index.get(entity_id) if entity_id else None
        scene_object = object_index.get(object_id) if object_id else None
        if entity_id and not entity:
            add_issue(
                issues,
                "error",
                "MISSING_ENTITY",
                f"Binding references unknown entity '{entity_id}'.",
                **context,
            )
        if object_id and not scene_object:
            add_issue(
                issues,
                "error",
                "MISSING_SCENE_OBJECT",
                f"Binding references unknown scene object '{object_id}'.",
                **context,
            )

        if entity and scene_object:
            _check_scope_pair(entity, scene_object, "Entity", "scene object", issues, **context)
            _check_coordinate_pair(
                entity,
                scene_object,
                "Entity",
                "scene object",
                issues,
                **context,
            )

        if binding.get("mineId"):
            expected_mine = scene_object.get("mineId") if scene_object else entity.get("mineId") if entity else None
            if expected_mine and binding["mineId"] != expected_mine:
                add_issue(
                    issues,
                    "error",
                    "BINDING_SCOPE_MISMATCH",
                    f"Binding mineId '{binding['mineId']}' does not match "
                    f"the referenced record mine '{expected_mine}'.",
                    **context,
                )
        if binding.get("sceneId"):
            expected_scene = scene_object.get("sceneId") if scene_object else entity.get("sceneId") if entity else None
            if expected_scene and binding["sceneId"] != expected_scene:
                add_issue(
                    issues,
                    "error",
                    "BINDING_SCOPE_MISMATCH",
                    f"Binding sceneId '{binding['sceneId']}' does not match "
                    f"the referenced record scene '{expected_scene}'.",
                    **context,
                )

        if entity:
            _check_coordinate_pair(entity, binding, "Entity", "binding", issues, **context)
        if scene_object:
            _check_coordinate_pair(scene_object, binding, "Scene object", "binding", issues, **context)

        effective_model_id = binding.get("modelId") or (
            scene_object.get("modelId") if scene_object else None
        )
        if binding.get("modelId") and scene_object and scene_object.get("modelId"):
            if binding["modelId"] != scene_object["modelId"]:
                add_issue(
                    issues,
                    "error",
                    "MODEL_MISMATCH",
                    f"Binding model '{binding['modelId']}' differs from scene "
                    f"object model '{scene_object['modelId']}'.",
                    **context,
                    modelId=binding["modelId"],
                )
        model = model_index.get(effective_model_id) if effective_model_id else None
        if effective_model_id and not model:
            add_issue(
                issues,
                "error",
                "MISSING_MODEL",
                f"Binding references unknown model '{effective_model_id}'.",
                **context,
                modelId=effective_model_id,
            )
        if binding.get("bindingType") == "ENTITY_MODEL" and not effective_model_id:
            add_issue(
                issues,
                "error",
                "MODEL_REQUIRED",
                "ENTITY_MODEL bindings require a modelId on the binding or scene object.",
                **context,
            )
        if model:
            if model.get("mineId") and scene_object and scene_object.get("mineId"):
                if model["mineId"] != scene_object["mineId"]:
                    add_issue(
                        issues,
                        "error",
                        "CROSS_MINE",
                        f"Model '{model['modelId']}' belongs to mine "
                        f"'{model['mineId']}' but scene object belongs to "
                        f"'{scene_object['mineId']}'.",
                        **context,
                        modelId=model["modelId"],
                    )
            if (
                model.get("coordinateSystemId")
                and scene_object
                and scene_object.get("coordinateSystemId")
                and model["coordinateSystemId"] != scene_object["coordinateSystemId"]
            ):
                add_issue(
                    issues,
                    "warning",
                    "MODEL_COORDINATE_SYSTEM_DIFFERS",
                    f"Model '{model['modelId']}' declares coordinate system "
                    f"'{model['coordinateSystemId']}' while the scene object uses "
                    f"'{scene_object['coordinateSystemId']}'. Model coordinates are "
                    "treated as local to the scene object placement; confirm the "
                    "asset transform.",
                    **context,
                    modelId=model["modelId"],
                )
            node_id = binding.get("modelNodeId") or (
                scene_object.get("modelNodeId") if scene_object else None
            )
            if binding.get("modelNodeId") and scene_object and scene_object.get("modelNodeId"):
                if binding["modelNodeId"] != scene_object["modelNodeId"]:
                    add_issue(
                        issues,
                        "error",
                        "MODEL_NODE_MISMATCH",
                        f"Binding node '{binding['modelNodeId']}' differs from "
                        f"scene object node '{scene_object['modelNodeId']}'.",
                        **context,
                    )
            if node_id and model.get("nodes") and node_id not in model["nodes"]:
                add_issue(
                    issues,
                    "error",
                    "UNKNOWN_MODEL_NODE",
                    f"Model '{model['modelId']}' does not declare node '{node_id}'.",
                    **context,
                    modelId=model["modelId"],
                    modelNodeId=node_id,
                )
        elif binding.get("modelNodeId"):
            add_issue(
                issues,
                "error",
                "MODEL_NODE_WITHOUT_MODEL",
                "modelNodeId requires a resolvable modelId.",
                **context,
            )

        pair = (entity_id, object_id)
        if all(pair):
            if pair in pair_seen:
                add_issue(
                    issues,
                    "error",
                    "DUPLICATE_ENTITY_OBJECT",
                    f"Entity '{entity_id}' and scene object '{object_id}' are "
                    f"bound more than once (first binding '{pair_seen[pair]}').",
                    **context,
                )
            else:
                pair_seen[pair] = binding_id

        if binding.get("active") and binding.get("isPrimary"):
            primary_by_entity[entity_id].append(binding_id)
        if entity_id:
            entity_bindings[entity_id].append(binding)
            if object_id and object_id not in entity_objects[entity_id]:
                entity_objects[entity_id].append(object_id)
        if object_id:
            object_bindings[object_id].append(binding)
            if entity_id and entity_id not in object_entities[object_id]:
                object_entities[object_id].append(entity_id)

    for entity_id, binding_ids in primary_by_entity.items():
        if len(binding_ids) > 1:
            add_issue(
                issues,
                "error",
                "CONFLICTING_PRIMARY",
                f"Entity '{entity_id}' has multiple active primary bindings: "
                + ", ".join(binding_ids),
                recordType="binding",
                entityId=entity_id,
                bindingIds=binding_ids,
            )

    query = None
    if query_entity_id is not None:
        query = build_entity_query(
            query_entity_id,
            entity_index,
            object_index,
            model_index,
            entity_bindings,
        )
        if query["entity"] is None:
            add_issue(
                issues,
                "error",
                "ENTITY_NOT_FOUND",
                f"Query entity '{query_entity_id}' does not exist.",
                recordType="query",
                entityId=str(query_entity_id),
            )

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    status = "FAIL" if error_count else "PASS_WITH_WARNINGS" if warning_count else "PASS"

    entity_summaries = []
    for entity_id, entity in sorted(entity_index.items()):
        binding_ids = [row["bindingId"] for row in entity_bindings.get(entity_id, [])]
        primary_ids = [
            row["bindingId"]
            for row in entity_bindings.get(entity_id, [])
            if row.get("active") and row.get("isPrimary")
        ]
        entity_summaries.append(
            {
                "entityId": entity_id,
                "entityType": entity.get("entityType"),
                "mineId": entity.get("mineId"),
                "objectIds": entity_objects.get(entity_id, []),
                "bindingIds": binding_ids,
                "primaryBindingId": primary_ids[0] if len(primary_ids) == 1 else None,
            }
        )

    object_summaries = [
        {
            "objectId": object_id,
            "mineId": scene_object.get("mineId"),
            "sceneId": scene_object.get("sceneId"),
            "entityIds": object_entities.get(object_id, []),
        }
        for object_id, scene_object in sorted(object_index.items())
    ]

    return {
        "skill": "mine-3d-entity-binding",
        "version": "v0.1",
        "status": status,
        "summary": {
            "entities": len(entity_index),
            "scene_objects": len(object_index),
            "models": len(model_index),
            "bindings": len(binding_index),
            "active_bindings": sum(1 for row in binding_rows if row and row.get("active")),
            "primary_bindings": sum(
                1 for row in binding_rows if row and row.get("active") and row.get("isPrimary")
            ),
            "errors": error_count,
            "warnings": warning_count,
            "entity_types": dict(
                Counter(
                    entity.get("entityType")
                    for entity in entity_index.values()
                    if entity.get("entityType")
                )
            ),
            "binding_types": dict(
                Counter(
                    row.get("bindingType")
                    for row in binding_index.values()
                    if row.get("bindingType")
                )
            ),
        },
        "issues": issues,
        "entity_index": entity_summaries,
        "object_index": object_summaries,
        "query": query,
    }


def build_entity_query(
    entity_id: str,
    entity_index: dict[str, dict],
    object_index: dict[str, dict],
    model_index: dict[str, dict],
    entity_bindings: dict[str, list[dict]],
) -> dict:
    normalized_id = as_id(entity_id)
    entity = entity_index.get(normalized_id) if normalized_id else None
    if entity is None:
        return {
            "entityId": normalized_id or str(entity_id),
            "entity": None,
            "objects": [],
            "bindings": [],
            "models": [],
            "primaryBindingId": None,
        }

    bindings = []
    object_ids: list[str] = []
    model_ids: list[str] = []
    for binding in entity_bindings.get(normalized_id, []):
        object_id = binding.get("objectId")
        scene_object = object_index.get(object_id)
        model_id = binding.get("modelId") or (
            scene_object.get("modelId") if scene_object else None
        )
        if object_id and object_id not in object_ids:
            object_ids.append(object_id)
        if model_id and model_id not in model_ids:
            model_ids.append(model_id)
        bindings.append(
            {
                "bindingId": binding.get("bindingId"),
                "entityId": binding.get("entityId"),
                "objectId": object_id,
                "bindingType": binding.get("bindingType"),
                "modelId": model_id,
                "modelNodeId": binding.get("modelNodeId") or (
                    scene_object.get("modelNodeId") if scene_object else None
                ),
                "isPrimary": binding.get("isPrimary"),
                "active": binding.get("active"),
                "coordinateSystemId": binding.get("coordinateSystemId"),
            }
        )

    primary_binding_ids = [
        binding.get("bindingId")
        for binding in entity_bindings.get(normalized_id, [])
        if binding.get("active") and binding.get("isPrimary")
    ]
    return {
        "entityId": normalized_id,
        "entity": {
            "entityId": entity.get("entityId"),
            "entityType": entity.get("entityType"),
            "mineId": entity.get("mineId"),
            "sceneId": entity.get("sceneId"),
            "name": entity.get("name"),
            "coordinateSystemId": entity.get("coordinateSystemId"),
        },
        "objects": [
            {
                "objectId": scene_object.get("objectId"),
                "mineId": scene_object.get("mineId"),
                "sceneId": scene_object.get("sceneId"),
                "objectType": scene_object.get("objectType"),
                "name": scene_object.get("name"),
                "modelId": scene_object.get("modelId"),
                "modelNodeId": scene_object.get("modelNodeId"),
                "coordinateSystemId": scene_object.get("coordinateSystemId"),
            }
            for object_id in object_ids
            if (scene_object := object_index.get(object_id)) is not None
        ],
        "bindings": bindings,
        "models": [
            {
                "modelId": model.get("modelId"),
                "mineId": model.get("mineId"),
                "name": model.get("name"),
                "assetUrl": model.get("assetUrl"),
                "nodes": model.get("nodes", []),
            }
            for model_id in model_ids
            if (model := model_index.get(model_id)) is not None
        ],
        "primaryBindingId": primary_binding_ids[0] if len(primary_binding_ids) == 1 else None,
    }


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# 3D Entity Binding Report",
        "",
        f"- **Status**: {report['status']}",
        f"- **Entities**: {summary['entities']}",
        f"- **Scene objects**: {summary['scene_objects']}",
        f"- **Models**: {summary['models']}",
        f"- **Bindings**: {summary['bindings']} "
        f"(active {summary['active_bindings']}, primary {summary['primary_bindings']})",
        f"- **Errors**: {summary['errors']}",
        f"- **Warnings**: {summary['warnings']}",
        "",
        "## Issues",
        "",
    ]
    if report["issues"]:
        lines.extend(["| Severity | Code | Record | Message |", "|---|---|---|---|"])
        for issue in report["issues"]:
            record = issue.get("bindingId") or issue.get("entityId") or issue.get("objectId") or issue.get("recordType", "-")
            message = str(issue.get("message", "")).replace("|", "\\|")
            lines.append(f"| {issue['severity']} | {issue['code']} | {record} | {message} |")
    else:
        lines.append("- None")

    query = report.get("query")
    if query is not None:
        lines.extend(
            [
                "",
                "## Entity Query",
                "",
                f"Query entity: `{query.get('entityId')}`",
                "",
                f"- Objects: {len(query.get('objects', []))}",
                f"- Bindings: {len(query.get('bindings', []))}",
                f"- Primary binding: {query.get('primaryBindingId') or 'none'}",
                "",
                "```json",
                json.dumps(query, ensure_ascii=False, indent=2),
                "```",
            ]
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- v0.1 is a file-based validator; Spring Boot persistence and the "
            "binding REST API are future work.",
            "- A global model (no `mineId`) may be reused across mines; explicit "
            "model mines must match the scene object mine.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: dict, out_dir: str | Path) -> dict[str, str]:
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "binding_report.json"
    markdown_path = output_dir / "binding_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return {"report_json": str(json_path), "report_md": str(markdown_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate business entity / scene object / model bindings."
    )
    parser.add_argument("--entities", required=True, help="Entity registry JSON")
    parser.add_argument("--objects", required=True, help="Scene object registry JSON")
    parser.add_argument("--models", required=True, help="Model asset registry JSON")
    parser.add_argument("--bindings", required=True, help="Binding registry JSON")
    parser.add_argument("--entity", help="Print all objects and bindings for this entity ID")
    parser.add_argument("--out-dir", default="binding_output", help="Output directory")
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0; the report still records validation errors",
    )
    args = parser.parse_args(argv)

    entities = load_collection(args.entities, ("entities",), "Entity")
    scene_objects = load_collection(args.objects, ("sceneObjects", "objects"), "Scene object")
    models = load_collection(args.models, ("models", "modelAssets"), "Model")
    bindings = load_collection(args.bindings, ("bindings",), "Binding")

    report = validate_binding_set(
        entities,
        scene_objects,
        models,
        bindings,
        query_entity_id=args.entity,
    )
    paths = write_outputs(report, args.out_dir)
    summary = report["summary"]

    if args.entity is not None:
        print(json.dumps(report["query"], ensure_ascii=False, indent=2))
    else:
        print(
            f"{report['status']}: {summary['entities']} entities, "
            f"{summary['scene_objects']} objects, {summary['models']} models, "
            f"{summary['bindings']} bindings; "
            f"{summary['errors']} errors, {summary['warnings']} warnings"
        )
    print(f"Reports: {paths['report_json']}, {paths['report_md']}", file=sys.stderr)

    if summary["errors"] and not args.no_fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
