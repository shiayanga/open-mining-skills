# Interaction Contract Schema

`scripts/validate_interactions.py` validates `interaction_contract.json` and an
optional `bindings.json`. IDs may be strings or integers; they are normalised to
strings. Unknown extra fields are ignored.

## interaction_contract.json

```json
{
  "contractVersion": "0.1",
  "sceneId": "SCENE-001",
  "mineId": "MINE-001",
  "entities": [
    { "entityId": "PERSON-001", "entityType": "PERSON" }
  ],
  "handlers": [
    {
      "id": "pick-default",
      "type": "pick",
      "event": "LEFT_CLICK",
      "entityTypes": ["PERSON", "MONITOR_DEVICE", "MACHINERY", "INFRASTRUCTURE"]
    },
    {
      "id": "track-default",
      "type": "track",
      "entityTypes": ["PERSON", "MACHINERY"],
      "channelId": "twin-events",
      "playback": { "defaultSpeed": 1.0, "interpolation": "LINEAR" }
    }
  ],
  "permissionRules": [
    {
      "id": "person-track",
      "action": "VIEW_TRACK",
      "entityTypes": ["PERSON"],
      "roles": ["MINE_MANAGER", "DISPATCHER"],
      "scope": "MINE"
    }
  ],
  "eventChannels": [
    {
      "id": "twin-events",
      "name": "mine.twin.events",
      "transport": "WEBSOCKET",
      "eventTypes": ["ENTITY_POSITION_UPDATE", "ENTITY_STATUS_UPDATE", "ENTITY_ALARM"]
    }
  ],
  "trackPlayback": {
    "defaultSpeed": 2.0,
    "speedOptions": [0.5, 1, 2, 4, 8],
    "maxPoints": 5000,
    "interpolation": "LINEAR"
  }
}
```

### Handler types

| Type | Required / validated fields |
|---|---|
| `pick` | `entityTypes` optional; `event` may be `LEFT_CLICK`, `LEFT_DOUBLE_CLICK` or `RIGHT_CLICK`. |
| `select` | `entityTypes` optional; `highlight.color` string; `highlight.outlineWidth` non-negative. |
| `flyTo` | `entityTypes` optional; `duration` non-negative. |
| `track` | `entityTypes` recommended; `channelId` optional but must resolve; `playback` optional. |
| `filter` | `fields` required non-empty; unknown field names warn. |
| `panel` | `panels` required non-empty; each panel needs a unique `id`, a valid `entityType` and a non-empty `fields` array. |

Every handler needs a unique non-empty `id`. The type is case-insensitive for
`flyTo` aliases (`flyto`, `fly_to`, `fly-to`) but canonical output uses
`flyTo`. Entity types are exactly `PERSON`, `MONITOR_DEVICE`, `MACHINERY` and
`INFRASTRUCTURE`.

Handlers may also declare `entityIds`; each ID must exist in the contract
`entities` registry or in the supplied bindings.

### Permission rules

- `permissionRules` is required and must be non-empty.
- `action` must be one of the documented actions (`VIEW_OBJECT`, `VIEW_PERSON`,
  `VIEW_DEVICE`, `VIEW_MACHINERY`, `VIEW_INFRASTRUCTURE`, `VIEW_ALARM`,
  `VIEW_TRACK`, `VIEW_POSITION_HISTORY`, `VIEW_SENSITIVE`, `VIEW_VIDEO`,
  `EDIT_OBJECT`, `MANAGE_BINDING`, `EXPORT_DATA`).
- Every tracked entity type needs a `VIEW_TRACK` rule that covers it.
- `roles`, `scope` and per-field restrictions are validated when present. A rule
  without roles is allowed but warns, because it may grant access too broadly.
- UI permission rules never replace server-side enforcement.

### Event channels and playback

- Channel IDs are unique; `name` must be non-empty.
- Transports are `WEBSOCKET`, `SSE` or `POLLING`.
- Documented event types include `ENTITY_POSITION_UPDATE`,
  `ENTITY_STATUS_UPDATE`, `ENTITY_PROPERTY_UPDATE`, `ENTITY_ALARM`,
  `ENTITY_OFFLINE`, `ENTITY_ONLINE` and `ENTITY_GEOFENCE_EVENT`.
- `trackPlayback` (and per-handler overrides) use positive `defaultSpeed`,
  positive `speedOptions`, positive integer `maxPoints`, and `LINEAR`, `STEP` or
  `CATMULL_ROM` interpolation.

## bindings.json

```json
{
  "sceneId": "SCENE-001",
  "mineId": "MINE-001",
  "bindings": [
    {
      "bindingId": "BIND-PERSON-001",
      "entityId": "PERSON-001",
      "entityType": "PERSON",
      "objectId": "SCENE-OBJECT-PERSON-001",
      "modelId": "MODEL-PERSON-01"
    }
  ]
}
```

Each binding needs a unique `bindingId` (or `id`), a non-empty `entityId`,
`entityType` and `objectId`. When the contract has an `entities` registry,
every binding entity ID must exist there (error `UNKNOWN_ENTITY_ID`) and the
entity type must match (`ENTITY_TYPE_MISMATCH`). Multiple bindings may reference
the same business entity when one object has multiple model nodes.

## Output report

`interaction_validation.json` contains:

- `status`: `PASS` / `FAIL`.
- `summary`: counts for handlers, panels, permission rules, event channels,
  entities and bindings.
- `contract`: scene/mine IDs, handler summaries, permission summaries, channel
  summaries and track playback.
- `bindings`: whether a bindings file was supplied and how many entries it has.
- `sources`: file path, size and SHA-256.
- `errors` / `warnings`: entries of `{code, path, message}`.

`interaction_validation.md` is the human-readable companion. Errors exit `1`
unless `--no-fail` is supplied; warnings never fail the run.

## v0.1 limits

- Contract validation only; no frontend runtime, data fetching or permission
  enforcement exists yet.
- Handler behaviour is described in `interaction-patterns.md`, not executed.
- Panel field semantics and business API schemas are not validated.
- Event channel connectivity and authentication are out of scope.
