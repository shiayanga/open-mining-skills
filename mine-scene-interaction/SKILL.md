---
name: mine-scene-interaction
description: Implement Cesium scene interactions for the mine digital twin — picking, selection, popups, highlighting, fly-to, filtering, track playback and interaction panels. Use when users must inspect and operate 3D mine objects.
---

# Mine Scene Interaction

> Status: v0.1 — `interaction_contract.json` / `bindings.json` validation and reference interaction patterns are implemented with tests. The Vue/Cesium frontend (handlers, panels, track runtime and permission execution) is documented but not yet generated or run by this skill.

## Role

You are a 3D interaction specialist for the mine digital twin. Your job is to turn scene objects and business bindings into usable interactions without mixing business logic into the rendering layer.

## Supported Input

| Input | v0.1 behaviour |
|---|---|
| `interaction_contract.json` | Validated: handlers, entity types, panels, permission rules, event channels and track playback |
| `bindings.json` | Optional; entity IDs and types cross-checked against the contract registry |
| Vue/Cesium interaction module | Patterns in `references/interaction-patterns.md`; application generation is future work |
| Business APIs / WebSocket streams | Referenced conceptually; not called by v0.1 |
| Track and alarm data | Contract fields validated; no track data is fetched or replayed |
| Permissions | Rules validated structurally; runtime enforcement is the backend's responsibility |

## Quick Start

Run the following commands from this skill directory. The validator uses the Python standard library only.

```bash
python3 scripts/validate_interactions.py \
  tests/fixtures/interaction_contract.json \
  --bindings tests/fixtures/bindings.json

# Writes interaction_validation.json and interaction_validation.md
# in the current directory.
```

Explicit output paths:

```bash
python3 scripts/validate_interactions.py interaction_contract.json \
  --bindings bindings.json \
  --output output/interaction_validation.json \
  --markdown output/interaction_validation.md
```

Exit code `0` when there are no errors, `1` when validation fails. Warnings do not fail the run.

## Options

| Option | Default | Meaning |
|---|---|---|
| `contract` | required | Path to `interaction_contract.json` |
| `--bindings` | off | Optional path to `bindings.json` |
| `--output` | `interaction_validation.json` | JSON report path |
| `--markdown` | `interaction_validation.md` | Markdown report path |
| `--no-fail` | off | Exit `0` even when validation errors are found |

## Workflow

1. Confirm the contract has a scene ID, mine ID and contract version.
2. Validate handlers: unique IDs, supported types and valid entity types.
3. Validate panel definitions: valid entity type and non-empty field list.
4. Validate permission rules: known actions, valid entity types and track coverage.
5. Validate event channels: unique IDs, non-empty names and resolvable handler references.
6. Validate track playback defaults and per-handler overrides.
7. If bindings are supplied, verify that every binding entity ID exists in the contract registry and its type matches.
8. Emit `interaction_validation.json` and `interaction_validation.md`; use `references/interaction-patterns.md` for the future frontend implementation.

## Engineering Rules

- Keep interaction logic separate from scene rendering and from business APIs.
- Never poll business APIs directly from Cesium; use the event dispatcher or store.
- Throttle high-frequency updates and batch position changes.
- Dispose handlers, listeners and timers when panels or scenes are destroyed.
- Do not show data the current user is not authorized to see.
- Pick only stable IDs from Cesium objects; never embed full business objects in pick metadata.
- Treat personnel position and track data as sensitive by default.
- Permission rules in the contract are UI guards; the server must enforce access on REST and WebSocket calls.
- Do not claim the frontend is implemented until a runnable interaction module exists.

## Quality Requirements

- Every handler has a unique ID and a supported type.
- Every panel references a valid entity type and declares fields.
- Permission actions are known and every tracked entity type has a `VIEW_TRACK` rule.
- Realtime channel names are non-empty and all channel references resolve.
- Track playback values are positive and finite.
- Optional bindings reference existing entities with matching types.
- Validation output is reproducible and records input SHA-256 checksums.

## Deliverables

- `interaction_validation.json`
- `interaction_validation.md`
- For project use: validated `interaction_contract.json` and optional `bindings.json`

## Project Layout

- `scripts/validate_interactions.py` — contract/bindings validator and CLI
- `scripts/common.py` — JSON I/O, hashing and formatting helpers
- `references/interaction-patterns.md` — TypeScript patterns for pick, selection, fly-to, track, panels and permission-aware UI
- `references/interaction-schema.md` — contract/bindings schema, rules and report fields
- `tests/` — unittest suite and valid contract/bindings fixtures

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Run from this skill directory. No third-party packages are required.

## Related Skills

- `mine-cesium-visualization` — rendering layer
- `mine-3d-entity-binding` — object and entity association
- `mine-personnel-tracking` / `mine-safety-monitoring` / `mine-machinery-management` — business data
- `mine-iot-integration` — realtime channels and event contract
