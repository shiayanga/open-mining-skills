# Cesium Interaction Patterns

Concise TypeScript patterns for the mine interaction layer. These patterns
consume the `interaction_contract.json` contract and the bindings produced by
`mine-3d-entity-binding`; they are not a generated application.

> v0.1 scope: this skill validates the interaction contract and optional
> bindings, and documents the patterns below. It does not build, bundle or run a
> Vue/Cesium frontend. Permission checks shown here are UI guards only; the
> server must enforce the same rules for every REST and WebSocket call.

## Contract mapping

| Contract handler | Responsibility |
|---|---|
| `pick` | Convert a Cesium pick result into a stable scene object reference. |
| `select` | Maintain selection state and highlight; restore the previous object. |
| `flyTo` | Move the camera to an entity, bookmark or bounding sphere. |
| `track` | Fetch and replay a time-ordered track with clock controls. |
| `filter` | Build scene filters from allowed fields and entity types. |
| `panel` | Assemble an info panel for an entity type and fields. |

Keep all of these outside Vue page components. A scene service exposes methods;
Vue stores own the UI state.

## PickHandler

Cesium returns different shapes for entities, primitives and 3D Tiles features.
Resolve them through a registry, never by serialising a full business object
into the Cesium object.

```ts
import * as Cesium from "cesium";

export type EntityType = "PERSON" | "MONITOR_DEVICE" | "MACHINERY" | "INFRASTRUCTURE";

export interface PickResult {
  entityId: string;
  entityType: EntityType;
  objectId: string;
  sceneObjectId: string;
}

export interface SceneObjectLookup {
  bySceneObjectId(sceneObjectId: string): PickResult | undefined;
  byObjectId(objectId: string): PickResult | undefined;
}

export class PickHandler {
  private readonly handler: Cesium.ScreenSpaceEventHandler;

  constructor(
    private readonly viewer: Cesium.Viewer,
    private readonly lookup: SceneObjectLookup,
    private readonly onPick: (result: PickResult | null) => void,
  ) {
    this.handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    this.handler.setInputAction(
      (movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) =>
        this.handleClick(movement.position),
      Cesium.ScreenSpaceEventType.LEFT_CLICK,
    );
  }

  private handleClick(screenPosition: Cesium.Cartesian2): void {
    const picked = this.viewer.scene.pick(screenPosition);
    this.onPick(this.resolve(picked));
  }

  private resolve(picked: unknown): PickResult | null {
    if (!Cesium.defined(picked)) {
      return null;
    }
    const candidate = picked as {
      id?: Cesium.Entity | { id?: string; objectId?: string };
      primitive?: { id?: string; objectId?: string };
      getProperty?: (name: string) => unknown;
    };

    if (candidate instanceof Cesium.Cesium3DTileFeature) {
      const objectId = candidate.getProperty("objectId");
      return typeof objectId === "string" ? this.lookup.byObjectId(objectId) ?? null : null;
    }
    if (candidate.id instanceof Cesium.Entity) {
      return this.lookup.bySceneObjectId(String(candidate.id.id)) ?? null;
    }
    const objectId =
      candidate.id?.objectId ?? candidate.primitive?.objectId ?? candidate.primitive?.id;
    return typeof objectId === "string" ? this.lookup.byObjectId(objectId) ?? null : null;
  }

  destroy(): void {
    this.handler.destroy();
  }
}
```

Rules:
- Set a stable Cesium entity/primitive ID; keep the business payload in a store.
- Do not put tokens, full business records or personal data into Cesium properties.
- Validate `entityType` from the binding registry, not from arbitrary pick metadata.

## SelectionHandler

Selection state belongs to the store. The Cesium handler only applies and clears
visual state, and it must restore previous highlights.

```ts
export interface Selectable {
  applyHighlight(): void;
  clearHighlight(): void;
}

export class SelectionHandler {
  private selected: { id: string; visual: Selectable } | null = null;

  constructor(private readonly onChange: (entityId: string | null) => void) {}

  select(id: string, visual: Selectable): void {
    if (this.selected?.id === id) {
      return;
    }
    this.selected?.visual.clearHighlight();
    this.selected = { id, visual };
    visual.applyHighlight();
    this.onChange(id);
  }

  clear(): void {
    this.selected?.visual.clearHighlight();
    this.selected = null;
    this.onChange(null);
  }

  destroy(): void {
    this.clear();
  }
}

export function entityHighlight(entity: Cesium.Entity): Selectable {
  return {
    applyHighlight(): void {
      if (entity.model) {
        entity.model.silhouetteColor = Cesium.Color.CYAN;
        entity.model.silhouetteSize = 2;
      }
    },
    clearHighlight(): void {
      if (entity.model) {
        entity.model.silhouetteColor = Cesium.Color.TRANSPARENT;
        entity.model.silhouetteSize = 1;
      }
    },
  };
}
```

For 3D Tiles features, store the original `feature.color` and restore it. If a
tileset uses `Cesium3DTileStyle`, prefer a style expression or a dedicated
highlight pass; assigning `feature.color` may conflict with the style.

## FlyToHandler

```ts
export class FlyToHandler {
  constructor(private readonly viewer: Cesium.Viewer) {}

  async flyToEntity(entity: Cesium.Entity, duration = 2.0): Promise<void> {
    const found = await this.viewer.flyTo(entity, { duration });
    if (!found) {
      // Too small or outside the scene; fall back to the object's cartographic position.
      const position = entity.position?.getValue(this.viewer.clock.currentTime);
      if (position) {
        this.flyToSphere(new Cesium.BoundingSphere(position, 80), duration);
      }
    }
  }

  flyToSphere(sphere: Cesium.BoundingSphere, duration = 2.0): void {
    this.viewer.camera.flyToBoundingSphere(sphere, {
      duration,
      offset: new Cesium.HeadingPitchRange(
        Cesium.Math.toRadians(30),
        Cesium.Math.toRadians(-35),
        sphere.radius * 3,
      ),
    });
  }

  flyToBookmark(
    destination: Cesium.Cartesian3,
    orientation: { heading: number; pitch: number; roll: number },
    duration = 2.0,
  ): void {
    this.viewer.camera.flyTo({
      destination,
      orientation: {
        heading: Cesium.Math.toRadians(orientation.heading),
        pitch: Cesium.Math.toRadians(orientation.pitch),
        roll: Cesium.Math.toRadians(orientation.roll),
      },
      duration,
    });
  }
}
```

`viewer.flyTo` returns `false` when the target is too small or not in view; do
not assume it always succeeds. Convert bookmark local coordinates through the
same CoordinateAdapter used for asset placement.

## TrackHandler

Track data is fetched from a time-series API, paginated by time and object, and
replayed with the Cesium clock. Do not poll the positioning API from Cesium.

```ts
export interface TrackPoint {
  time: string; // ISO-8601
  x: number;
  y: number;
  z: number;
}

export interface TrackService {
  fetchTrack(entityId: string, from: string, to: string, limit: number): Promise<TrackPoint[]>;
}

export class TrackHandler {
  private entity: Cesium.Entity | null = null;
  private property: Cesium.SampledPositionProperty | null = null;

  constructor(
    private readonly viewer: Cesium.Viewer,
    private readonly service: TrackService,
    private readonly toWorld: (point: TrackPoint) => Cesium.Cartesian3,
  ) {}

  async load(entityId: string, from: string, to: string, maxPoints: number): Promise<void> {
    this.clear();
    const points = await this.service.fetchTrack(entityId, from, to, maxPoints);
    if (points.length === 0) {
      return;
    }

    const property = new Cesium.SampledPositionProperty();
    let start: Cesium.JulianDate | undefined;
    let stop: Cesium.JulianDate | undefined;
    for (const point of points) {
      const time = Cesium.JulianDate.fromIso8601(point.time);
      property.addSample(time, this.toWorld(point));
      start = start ? Cesium.JulianDate.minimum(start, time) : time;
      stop = stop ? Cesium.JulianDate.maximum(stop, time) : time;
    }
    if (!start || !stop) {
      return;
    }

    this.property = property;
    this.entity = this.viewer.entities.add({
      id: `track:${entityId}`,
      availability: new Cesium.TimeIntervalCollection([
        new Cesium.TimeInterval({ start, stop }),
      ]),
      position: property,
      point: {
        pixelSize: 10,
        color: Cesium.Color.ORANGE,
      },
      path: {
        resolution: 1,
        width: 3,
        material: Cesium.Color.ORANGE.withAlpha(0.8),
      },
    });

    this.viewer.clock.startTime = start.clone();
    this.viewer.clock.stopTime = stop.clone();
    this.viewer.clock.currentTime = start.clone();
    this.viewer.clock.clockRange = Cesium.ClockRange.LOOP_STOP;
    this.viewer.clock.multiplier = 1;
    this.viewer.clock.shouldAnimate = true;
  }

  setSpeed(multiplier: number): void {
    if (multiplier > 0) {
      this.viewer.clock.multiplier = multiplier;
    }
  }

  pause(): void {
    this.viewer.clock.shouldAnimate = false;
  }

  play(): void {
    this.viewer.clock.shouldAnimate = true;
  }

  clear(): void {
    this.viewer.clock.shouldAnimate = false;
    if (this.entity) {
      this.viewer.entities.remove(this.entity);
    }
    this.entity = null;
    this.property = null;
  }

  destroy(): void {
    this.clear();
  }
}
```

Rules:
- Cap `maxPoints` from the contract and page long histories; never load an
  unbounded track.
- Track visibility is permission-sensitive, especially for personnel. Check the
  `VIEW_TRACK` rule before fetching, and enforce it again on the server.
- Stop replay and remove the entity when switching object or scene.

## Panel data assembly

Panels are driven by the contract's `panels` entries, not by hardcoded Vue
conditionals. The pick result only supplies IDs; business fields come from APIs.

```ts
export interface PanelRow {
  key: string;
  label: string;
  value: string | number | boolean | null;
}

export interface PanelData {
  entityId: string;
  entityType: EntityType;
  title: string;
  rows: PanelRow[];
  actions: string[];
  fetchedAt: string;
  stale: boolean;
}

export interface PanelLoader {
  supports(entityType: EntityType): boolean;
  load(entityId: string): Promise<PanelData>;
}

export class PanelAssembler {
  constructor(
    private readonly loaders: PanelLoader[],
    private readonly permissions: PermissionService,
  ) {}

  async assemble(pick: PickResult): Promise<PanelData | null> {
    const loader = this.loaders.find((item) => item.supports(pick.entityType));
    if (!loader) {
      return null;
    }
    if (!this.permissions.can("VIEW_OBJECT", pick.entityType)) {
      return null;
    }
    const data = await loader.load(pick.entityId);
    return {
      ...data,
      rows: data.rows.filter((row) =>
        this.permissions.canField(pick.entityType, row.key),
      ),
    };
  }
}
```

Rules:
- Show loading, error and stale states; never substitute placeholder values for
  missing business data.
- Display the source timestamp and data age for realtime values.
- Keep panel actions permission-filtered; a hidden button is not authorization.

## Permission-aware UI

```ts
export interface PermissionService {
  can(action: string, entityType: EntityType, entityId?: string): boolean;
  canField(entityType: EntityType, field: string): boolean;
}

export interface HandlerContract {
  id: string;
  type: string;
  entityTypes: EntityType[];
}

export function visibleHandlers(
  handlers: HandlerContract[],
  permissions: PermissionService,
): HandlerContract[] {
  return handlers.filter((handler) =>
    handler.entityTypes.every((type) => permissions.can("VIEW_OBJECT", type)),
  );
}
```

Required behaviour:
- Hide or disable UI the user cannot use, but re-check permissions server-side.
- Apply mine-scene and mine-level isolation to every subscription.
- Treat personnel locations and tracks as sensitive; do not expose them to all
  roles by default.
- Filter WebSocket events by mine, scene and permission before updating a store.

## Realtime update path

```text
WebSocketClient -> EventDispatcher -> TwinEntityStore -> CesiumSceneManager
```

Do not update Cesium objects directly from a Vue component or from the raw
socket callback. Batch position updates, ignore stale timestamps and sequence
numbers, and rehydrate a snapshot after reconnect.

## Cleanup checklist

- `ScreenSpaceEventHandler.destroy()` on scene unmount.
- Restore all highlight state and remove temporary entities.
- Stop the Cesium clock and clear track entities.
- Abort in-flight requests and unsubscribe from channels.
- Clear timers and animation frames.
- Verify no listeners survive a mine scene switch.
