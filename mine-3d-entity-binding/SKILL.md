---
name: mine-3d-entity-binding
description: Maintain the three-layer binding between business entities, scene objects and model nodes in a mine digital twin. Use when people, sensors, machinery or infrastructure must be linked to 3D scene objects without hardcoding IDs in models.
---

# Mine 3D Entity Binding

> Status: v0.1 — file-based referential validation, primary-binding checks and entity queries are implemented with tests. Spring Boot persistence, the binding REST API and change-audit storage are future work.

## Role

You are the binding system specialist for the mine digital twin. Your job is to keep business entities, scene objects and model nodes linked reliably and independently, and to reject binding sets that would create ambiguous or cross-mine associations.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| Entity registry JSON | List or `{ "entities": [...] }`; validates ID, type, mine, scene and coordinate system |
| Scene object registry JSON | List or `{ "sceneObjects": [...] }`; validates ID, mine, scene, model reference and coordinate system |
| Model registry JSON | List or `{ "models": [...] }`; validates model IDs, optional mine scope, node list and coordinate system |
| Binding registry JSON | List or `{ "bindings": [...] }`; validates references, scope, model/node, duplicates and primary rule |
| Entity query | `--entity ID` prints the entity, its objects, bindings and models as JSON |
| Spring Boot / PostgreSQL | Not included in v0.1; `mine_entity_binding` persistence and REST endpoints are future work |

## Quick Start

Run the following commands from this skill directory. Only the Python standard library is required.

```bash
python3 scripts/binding.py \
  --entities tests/fixtures/entities.json \
  --objects tests/fixtures/scene_objects.json \
  --models tests/fixtures/models.json \
  --bindings tests/fixtures/bindings.json \
  --out-dir binding_output
```

Query one entity (the query JSON is printed to stdout and included in the report):

```bash
python3 scripts/binding.py \
  --entities tests/fixtures/entities.json \
  --objects tests/fixtures/scene_objects.json \
  --models tests/fixtures/models.json \
  --bindings tests/fixtures/bindings.json \
  --entity PERSON-001 --out-dir binding_output
```

Exit code `0` when validation has no errors; `1` when errors are present; use `--no-fail` to inspect a failing report while still exiting `0`.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--entities` | required | Entity registry JSON path |
| `--objects` | required | Scene object registry JSON path |
| `--models` | required | Model registry JSON path |
| `--bindings` | required | Binding registry JSON path |
| `--entity` | off | Print all objects, bindings and models for this entity ID |
| `--out-dir` | `binding_output` | Output directory |
| `--no-fail` | off | Always exit 0; errors remain in the report |

## Workflow

1. Load all four JSON files and normalise numeric or string IDs to stable strings.
2. Validate required fields, unique IDs and the `PERSON` / `MONITOR_DEVICE` / `MACHINERY` / `INFRASTRUCTURE` catalog.
3. Enforce mine and scene scope between entities, scene objects, models and bindings.
4. Check coordinate-system compatibility across entity, scene object and binding declarations.
5. Resolve the effective model and model node from the binding or scene object; validate node existence when the model declares nodes.
6. Reject duplicate entity-object pairs and more than one active primary binding per entity.
7. Build entity and object indexes, write the report and optionally answer an entity query.
8. Future work: persist bindings, expose `/bindings` and `/entities/{id}/objects`, and record before/after audit values.

## Engineering Rules

- Never hardcode business device IDs inside GLB / glTF model files.
- Keep business objects and 3D models independently maintainable and replaceable.
- Do not rely on model node names as the only association key; the binding row is the authority.
- Enforce referential integrity and mine/scene scope for every binding.
- Allow at most one active primary binding per entity; inactive primary flags do not conflict.
- A model without `mineId` is treated as a reusable/global asset; an explicit model mine must match the scene object mine.
- `modelNodeId` is optional but must be non-empty when present, and must exist when the model publishes a node list.
- Never modify source JSON files. Numeric IDs are normalised to strings only in outputs and comparisons.
- v0.1 is a single-process file checker; concurrent update safety belongs to the future persistence layer.

## Quality Requirements

- No binding references a missing entity, scene object or model.
- Entity, scene object and binding coordinate-system declarations do not conflict.
- Entity-object pairs are unique and primary-binding conflicts are reported.
- Every entity has a queryable object/binding index; every object reports its bound entity IDs.
- Every issue is traceable to a binding, entity, object or record index.
- Reports are deterministic and contain summary counts, full issue details and the optional query payload.

## Deliverables

- `binding_report.json` — status, summary, issues, entity/object indexes and optional query
- `binding_report.md` — human-readable summary and issue table
- Query JSON on stdout when `--entity` is used

## Project Layout

- `scripts/binding.py` — loader, validator, query builder, report renderer and CLI
- `references/binding-model.md` — three-layer model, ID rules, scope and query contract
- `references/validation-rules.md` — complete rule and issue-code reference
- `tests/test_binding.py` — unittest suite
- `tests/fixtures/` — valid entities, scene objects, models and bindings

## Testing

```bash
python3 -m unittest discover -s tests -v
```

The suite covers a valid binding set, entity query output, missing entity, conflicting primary bindings, cross-mine scope, duplicate entity-object pairs and empty/unknown model nodes.

## Related Skills

- `mine-iot-integration` — source of business entity IDs and device mappings
- `mine-cesium-visualization` — scene object and model node source
- `mine-scene-interaction` — uses bindings for picking and panels
- `mine-personnel-tracking` / `mine-safety-monitoring` / `mine-machinery-management` — entity types
