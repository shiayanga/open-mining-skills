# Binding Model (v0.1)

## Three layers

The binding model separates business identity from spatial representation:

```text
Business Entity (PERSON-001, MACHINERY-001, MONITOR-001)
        entityId  <->  objectId
Scene Object (OBJ-PERSON-001, sceneId, placement)
        objectId  <->  modelId/modelNodeId
Model Asset (worker.glb, node Worker_Main)
```

A business entity can have several scene representations (for example a full model and a personnel marker), but one active representation should be primary. The binding row is the authority; model node names are never the only association key.

## Registries

### Entities

```json
{
  "entityId": "PERSON-001",
  "entityType": "PERSON",
  "mineId": "MINE-001",
  "sceneId": "SCENE-001",
  "name": "Miner A",
  "coordinateSystemId": 1001
}
```

Supported `entityType` values in v0.1: `PERSON`, `MONITOR_DEVICE`, `MACHINERY`, `INFRASTRUCTURE`. Unknown types are warnings so that future catalogs remain readable.

### Scene objects

```json
{
  "objectId": "OBJ-PERSON-001",
  "mineId": "MINE-001",
  "sceneId": "SCENE-001",
  "modelId": "MODEL-WORKER",
  "modelNodeId": "Worker_Main",
  "coordinateSystemId": 1001
}
```

`mineId` and `sceneId` are required. `modelId` and `modelNodeId` are optional at the scene-object level, but an `ENTITY_MODEL` binding must resolve a model from the binding or the scene object.

### Models

```json
{
  "modelId": "MODEL-WORKER",
  "mineId": "MINE-001",
  "assetUrl": "/models/worker.glb",
  "nodes": ["Worker_Main", "Worker_Lamp"],
  "coordinateSystemId": 1001
}
```

A model with no `mineId` is treated as global/reusable. If a model declares `mineId`, it must match the scene object mine. When `nodes` or `modelNodeIds` is present, any binding node reference must exist in that list.

### Bindings

```json
{
  "bindingId": "BIND-001",
  "entityId": "PERSON-001",
  "objectId": "OBJ-PERSON-001",
  "bindingType": "ENTITY_MODEL",
  "modelId": "MODEL-WORKER",
  "modelNodeId": "Worker_Main",
  "isPrimary": true,
  "active": true,
  "coordinateSystemId": 1001
}
```

`bindingType` is `ENTITY_MODEL` or `ENTITY_MARKER`. `isPrimary` defaults to `false`; `active` defaults to `true`.

## Scope and coordinate systems

- Entity and scene object mines must match.
- If both declare a scene, those scene IDs must match.
- Binding-level `mineId` / `sceneId` must match the referenced records.
- Explicit model mines must match the scene object mine.
- Coordinate-system declarations may use `coordinateSystemId`, `coordinateSystem` or `crs`; multiple declarations on one record must agree.
- Entity, scene object and binding coordinate systems must not conflict.
- Model asset coordinate systems are recorded; a difference from the scene object coordinate system is a warning (`MODEL_COORDINATE_SYSTEM_DIFFERS`) because the scene object placement is assumed to transform the local asset.

## Primary rule

At most one **active** binding with `isPrimary: true` is allowed per entity. Inactive primary rows do not conflict. A conflict is reported once with the entity and all conflicting binding IDs.

## Entity query

`--entity PERSON-001` returns:

```json
{
  "entityId": "PERSON-001",
  "entity": { "...": "..." },
  "objects": [ { "objectId": "OBJ-PERSON-001", "...": "..." } ],
  "bindings": [ { "bindingId": "BIND-001", "isPrimary": true, "...": "..." } ],
  "models": [ { "modelId": "MODEL-WORKER", "nodes": ["Worker_Main"] } ],
  "primaryBindingId": "BIND-001"
}
```

The query is also embedded in `binding_report.json` under `query`.

## v0.1 limitations

- File-based only; no PostgreSQL `mine_entity_binding` persistence.
- No REST API, optimistic locking or concurrent update handling.
- No binding change-audit history; the report captures the current set only.
- No automatic asset loading or node discovery from GLB files.
