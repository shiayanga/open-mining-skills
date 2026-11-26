---
name: mine-scene-interaction
description: Implement Cesium scene interactions for the mine digital twin — picking, selection, popups, highlighting, fly-to, filtering, track playback and interaction panels. Use when users must inspect and operate 3D mine objects.
---

# Mine Scene Interaction

> Status: skeleton — the workflow below is the intended contract; scripts and reference notes will be added in later iterations.

## Role

You are a 3D interaction specialist for the mine digital twin. Your job is to turn scene objects and business bindings into usable interactions without mixing business logic into the rendering layer.

## Supported Input

- Cesium scene module from `mine-cesium-visualization`
- Entity bindings and scene object metadata
- Business APIs and WebSocket event streams
- UI panels, filters and permission configuration
- Track and alarm data

## Workflow

1. Implement picking and convert picked primitives to scene object and entity IDs.
2. Manage selection and highlight states, restoring previous states on change.
3. Assemble info-panel data by entity type (person, device, machinery, infrastructure).
4. Implement fly-to and view bookmarks for entities and areas.
5. Implement filtering by person, department, area, device type and machinery type.
6. Implement track playback with time controls and speed.
7. Apply realtime updates through the event dispatcher.
8. Apply permission-aware visibility and actions, and clean up listeners on unmount.

## Engineering Rules

- Keep interaction logic separate from scene rendering and from business APIs.
- Never poll business APIs directly from Cesium; use the event dispatcher or store.
- Throttle high-frequency updates and batch position changes.
- Dispose handlers, listeners and timers when panels or scenes are destroyed.
- Do not show data the current user is not authorized to see.

## Quality Requirements

- Picking returns the correct object under overlapping geometry.
- Info panels show data consistent with the source API.
- No leaked listeners or timers after scene switches.
- Interaction response and track playback meet the agreed performance budget.
- No console errors during selection, filtering or playback.

## Deliverables

- `src/cesium/interactions/` module (`PickHandler`, `SelectionHandler`, `FlyToHandler`, `TrackHandler`)
- `interaction_spec.md`
- `interaction_checklist.md`

## Project Layout

- `scripts/` — executable checks and interaction utilities (to be added)
- `references/` — interaction contracts, panel schemas and permission rules (to be added)

## Related Skills

- `mine-cesium-visualization` — rendering layer
- `mine-3d-entity-binding` — object and entity association
- `mine-personnel-tracking` / `mine-safety-monitoring` / `mine-machinery-management` — business data
