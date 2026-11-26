# Validation Rules and Issue Codes (v0.1)

## Severity and status

| Severity | Effect |
|---|---|
| `error` | Report status becomes `FAIL`; CLI exits `1` unless `--no-fail` |
| `warning` | Report status becomes `PASS_WITH_WARNINGS`; CLI still exits `0` |

Report status values: `PASS`, `PASS_WITH_WARNINGS`, `FAIL`.

All secrets and source files are read-only. IDs may be strings or integers in input; they are normalised to strings for comparison and output. Boolean values are never accepted as IDs.

## Required fields

| Record | Required | Optional but validated |
|---|---|---|
| Entity | `entityId`, `entityType`, `mineId` | `sceneId`, `coordinateSystemId`/`coordinateSystem`/`crs` |
| Scene object | `objectId`, `mineId`, `sceneId` | `modelId`, `modelNodeId`, coordinate-system fields |
| Model | `modelId` | `mineId`, `nodes`/`modelNodeIds`, coordinate-system fields |
| Binding | `entityId`, `objectId`, `bindingType` | `bindingId`, `modelId`, `modelNodeId`, `isPrimary`, `active`, `mineId`, `sceneId`, coordinate-system fields |

## Rule-to-code map

| Rule | Code | Severity |
|---|---|---|
| Entry is not an object | `INVALID_RECORD` | error |
| Required ID/type/mine/scene missing | `MISSING_*`, `EMPTY_*` | error |
| Duplicate entity/object/model/binding ID | `DUPLICATE_ID` | error |
| Unknown entity type | `UNKNOWN_ENTITY_TYPE` | warning |
| `modelNodeId` present but empty | `EMPTY_MODEL_NODE_ID` | error |
| Model nodes not a list / empty node | `INVALID_MODEL_NODES` / `EMPTY_MODEL_NODE` | error / warning |
| Binding type missing or unknown | `MISSING_BINDING_TYPE` / `INVALID_BINDING_TYPE` | error |
| `isPrimary` or `active` not boolean | `INVALID_IS_PRIMARY` / `INVALID_ACTIVE` | error |
| One record declares conflicting coordinate systems | `COORDINATE_SYSTEM_CONFLICT` | error |
| Entity/object/binding scopes differ | `CROSS_MINE`, `CROSS_SCENE` | error |
| Entity/object/binding coordinate systems differ | `COORDINATE_SYSTEM_MISMATCH` | error |
| Binding-level mine/scene disagrees with referenced record | `BINDING_SCOPE_MISMATCH` | error |
| Binding references missing entity/object/model | `MISSING_ENTITY`, `MISSING_SCENE_OBJECT`, `MISSING_MODEL` | error |
| Binding model differs from scene-object model | `MODEL_MISMATCH` | error |
| `ENTITY_MODEL` has no resolvable model | `MODEL_REQUIRED` | error |
| Binding and object node differ | `MODEL_NODE_MISMATCH` | error |
| Node not declared by model | `UNKNOWN_MODEL_NODE` | error |
| Node given without a resolvable model | `MODEL_NODE_WITHOUT_MODEL` | error |
| Same entity-object pair repeated | `DUPLICATE_ENTITY_OBJECT` | error |
| Multiple active primary bindings for one entity | `CONFLICTING_PRIMARY` | error |
| `--entity` target not found | `ENTITY_NOT_FOUND` | error |
| Model has explicit mine different from scene object mine | `CROSS_MINE` | error |
| Model coordinate system differs from scene object (local asset placement) | `MODEL_COORDINATE_SYSTEM_DIFFERS` | warning |

## Output schema

`binding_report.json`:

| Field | Description |
|---|---|
| `skill`, `version`, `status` | Identity and overall validation result |
| `summary` | Entity/object/model/binding counts, active/primary counts, error/warning counts, type histograms |
| `issues` | Every issue with severity, code, message and record context |
| `entity_index` | Entity → object IDs, binding IDs and resolved primary binding |
| `object_index` | Object → bound entity IDs |
| `query` | Entity query object when `--entity` is used, otherwise `null` |

`binding_report.md` repeats the summary, issues and optional query in a readable form.

## Determinism

- Registries are indexed in input order; report indexes are sorted by ID.
- Normalised numeric IDs appear as strings.
- The same inputs produce the same JSON and Markdown, subject only to Python dictionary ordering guarantees used by the implementation.
