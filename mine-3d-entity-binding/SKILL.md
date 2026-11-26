---
name: mine-3d-entity-binding
description: Maintain the three-layer binding between business entities, scene objects and model nodes in a mine digital twin. Use when people, sensors, machinery or infrastructure must be linked to 3D scene objects without hardcoding IDs in models.
---

# Mine 3D Entity Binding

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are the binding system specialist for the mine digital twin. Your job is to keep business entities, scene objects and model nodes linked reliably and independently.

## Supported Input

- Business entity registry (`PERSON`, `MONITOR_DEVICE`, `MACHINERY`, `INFRASTRUCTURE`)
- Scene object registry and scene layers
- Model assets, model IDs and model node names
- Binding rules, primary-binding policy and permissions
- Source provenance (`sourceEntityId`, `sourceFileId`, `sourceGuid`)

## Workflow

1. Define and validate entity IDs, object IDs and model node IDs.
2. Verify that the entity, scene object and model exist and belong to the same mine and scene.
3. Check coordinate system compatibility.
4. Create the binding with type and primary flag; reject conflicting primary bindings.
5. Support rebinding without changing business data or model files.
6. Expose queries in both directions: entity → objects, object → entity.
7. Keep an audit trail of binding changes and provenance.

## Engineering Rules

- Never hardcode business device IDs inside GLB / glTF model files.
- Keep business objects and 3D models independently maintainable and replaceable.
- Do not rely on model node names as the only association key.
- Enforce referential integrity and mine/scene scope.
- Allow at most one primary binding per entity type unless an explicit exception is configured.

## Quality Requirements

- No orphan bindings in either direction.
- Uniqueness and primary-binding rules are enforced.
- Scope and coordinate system checks pass.
- Every change is auditable with before and after values.
- Binding queries return consistent results under concurrent updates.

## Deliverables

- `binding_schema.json`
- `binding_api.md`
- `binding_migration.md`
- `binding_report.json`

## Project Layout

- `scripts/` — executable binding tools and validators (to be added)
- `references/` — binding model, API contracts and migration rules (to be added)

## Related Skills

- `mine-iot-integration` — source of business entity IDs
- `mine-cesium-visualization` — scene object and model node source
- `mine-scene-interaction` — uses bindings for picking and panels
- `mine-personnel-tracking` / `mine-safety-monitoring` / `mine-machinery-management` — entity types
