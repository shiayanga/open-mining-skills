# State-to-Animation Mapping (v0.1)

## Input

`state_map.json` maps telemetry state names to animation names:

```json
{
  "states": {
    "WORKING": {
      "animation": "Excavator_Work",
      "loop": true,
      "speedScale": 1.0
    },
    "IDLE": {
      "animation": "Excavator_Idle",
      "loop": true
    },
    "FAULT": {
      "animation": "Machinery_Fault",
      "loop": false
    }
  }
}
```

Accepted forms:

- `{ "states": { ... } }`
- `{ "stateMap": { ... } }`
- `{ "animationMapping": { ... } }`
- A direct state → animation object
- A list of `{ "state": "...", "animation": "..." }` records

A state value may be a string animation name or an object with `animation` / `name` / `clip` plus optional `loop` and `speedScale`.

Rules:

- State keys must be non-empty and unique.
- Animation names must be non-empty.
- `loop` must be a boolean when present.
- `speedScale` must be a finite number when present.
- At least one mapping is required for a clean run.

## Mapping behaviour

- The latest accepted telemetry `state` drives `animation`.
- If the state is not in the map, the state is retained, `animation` becomes `null`, and `UNKNOWN_STATE` warns. No animation is invented.
- A state change that occurs between events is reflected only when an event with the new state arrives.
- `animationConfig` carries `loop` and `speedScale` for the future scene layer.
- Tracks record the state and animation known after each accepted event.

## Real operation versus visual simulation

The governing rule is: **animation is a visualization of real telemetry state, not evidence of work.**

- Do not mark a machine as working because its model plays a working animation.
- Do not synthesize a state transition or animation to hide missing telemetry.
- A missing/unknown state must be visible as unanimated or marked state, not silently replaced by a default.
- Manual or simulated states must be distinguishable in the upstream system; v0.1 only maps whatever state the telemetry declares.

## Future scene integration

A Cesium/scene adapter should:

1. Resolve the machine's scene object through `mine-3d-entity-binding`.
2. Load the GLB/model and locate the bound node.
3. Apply position and heading/pitch/roll from the latest state.
4. Start/stop the mapped animation clip only on state changes.
5. Stop or freeze animation when the machine is stale or offline.

The v0.1 script stops at producing validated `latest_state.json`, `tracks.csv` and reports; it does not connect to Cesium or play animations.

## Limitations

- No blending, transition duration or animation graph.
- No per-model animation catalog validation; animation names are trusted from configuration.
- No interpolation or update throttling; these belong to the realtime scene layer.
