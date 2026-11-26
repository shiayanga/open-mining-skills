# Cesium Scene Patterns

Concise TypeScript patterns for a mine CesiumJS scene. These are reference
implementations, not a generated application.

> v0.1 scope: this skill validates `viewer_config.json` and `scene_manifest.json`
> and documents the patterns below. The Vue 3 + CesiumJS application
> (`CesiumViewer.ts`, loaders, interaction handlers, build pipeline) is future
> work and is not created or executed by this skill.

## Version caution

CesiumJS changed several async factory APIs around v1.104 (`fromUrl`,
`Model.fromGltfAsync`, `baseLayer` replacing `imageryProvider` in the Viewer
constructor). Verify the exact signatures against the CesiumJS version pinned
by the frontend project instead of copying them blindly.

## Viewer setup

```ts
import * as Cesium from "cesium";

export interface ViewerOptions {
  container: HTMLElement;
  terrainUrl: string;
  imageryUrl: string;
  requestRenderMode: boolean;
  maximumScreenSpaceError: number;
  resolutionScale: number;
}

export async function createMineViewer(options: ViewerOptions): Promise<Cesium.Viewer> {
  const viewer = new Cesium.Viewer(options.container, {
    // Cesium >= 1.104: false disables the default (Ion) base layer.
    baseLayer: false,
    animation: false,
    timeline: false,
    geocoder: false,
    baseLayerPicker: false,
    scene3DOnly: true,
    requestRenderMode: options.requestRenderMode,
    maximumRenderTimeChange: Infinity,
  });

  viewer.scene.globe.depthTestAgainstTerrain = true;
  viewer.scene.screenSpaceCameraController.enableCollisionDetection = true;
  viewer.scene.globe.maximumScreenSpaceError = options.maximumScreenSpaceError;
  viewer.resolutionScale = options.resolutionScale;

  const imagery = new Cesium.UrlTemplateImageryProvider({
    url: options.imageryUrl,
  });
  viewer.imageryLayers.addImageryProvider(imagery);

  return viewer;
}
```

Rules:
- Keep `terrainUrl` and `imageryUrl` in `viewer_config.json` or deployment
  configuration; never hardcode commercial provider URLs in source.
- Disable unneeded widgets and effects for deterministic performance.
- Do not put business logic in the Viewer bootstrap.

## CoordinateAdapter

The adapter is the only place allowed to convert mine coordinates into Cesium
world coordinates. A local engineering CRS is not WGS84.

```ts
import * as Cesium from "cesium";

export interface MineCoordinate {
  x: number;
  y: number;
  z: number;
  coordinateSystemId: string;
}

export interface ScenePosition {
  x: number;
  y: number;
  z: number;
}

export interface CoordinateAdapter {
  toScenePosition(position: MineCoordinate): ScenePosition;
  toWorldPosition(position: ScenePosition): Cesium.Cartesian3;
  readonly coordinateSystemId: string;
}

/**
 * Local mode: the registration step has already mapped mine XYZ into the
 * scene frame. `origin` is the geographic anchor supplied by the project,
 * and `sceneOffset` removes the mine local origin.
 */
export class LocalCoordinateAdapter implements CoordinateAdapter {
  private readonly enuFrame: Cesium.Matrix4;

  constructor(
    origin: Cesium.Cartesian3,
    private readonly sceneOffset: ScenePosition,
    readonly coordinateSystemId: string,
  ) {
    this.enuFrame = Cesium.Transforms.eastNorthUpToFixedFrame(origin);
  }

  toScenePosition(position: MineCoordinate): ScenePosition {
    if (position.coordinateSystemId !== this.coordinateSystemId) {
      throw new Error(
        `Coordinate system mismatch: expected ${this.coordinateSystemId}, ` +
          `received ${position.coordinateSystemId}`,
      );
    }
    return {
      x: position.x - this.sceneOffset.x,
      y: position.y - this.sceneOffset.y,
      z: position.z - this.sceneOffset.z,
    };
  }

  toWorldPosition(position: ScenePosition): Cesium.Cartesian3 {
    return Cesium.Matrix4.multiplyByPoint(
      this.enuFrame,
      new Cesium.Cartesian3(position.x, position.y, position.z),
      new Cesium.Cartesian3(),
    );
  }
}
```

Never do this for mine data:

```ts
// WRONG: mine X/Y/Z are not longitude/latitude/height.
Cesium.Cartesian3.fromDegrees(mine.x, mine.y, mine.z);
```

The transform parameters must come from `mine-coordinate-registration` (or an
equivalent controlled survey process). If no georeferencing evidence exists,
use a clearly labelled local scene and do not claim real-world positioning
accuracy.

## TerrainLoader

```ts
export interface TerrainConfig {
  url: string;
  requestVertexNormals?: boolean;
  requestWaterMask?: boolean;
}

export class TerrainLoader {
  constructor(private readonly viewer: Cesium.Viewer) {}

  async load(config: TerrainConfig): Promise<Cesium.CesiumTerrainProvider> {
    const provider = await Cesium.CesiumTerrainProvider.fromUrl(config.url, {
      requestVertexNormals: config.requestVertexNormals ?? true,
      requestWaterMask: config.requestWaterMask ?? false,
    });
    this.viewer.terrainProvider = provider;
    return provider;
  }
}
```

Load terrain before flying to a bookmark; otherwise the camera may target the
ellipsoid and appear underground.

## TilesetLoader

```ts
export interface TilesetConfig {
  id: string;
  uri: string;
  layerId: string;
  transform?: number[];
  maximumScreenSpaceError?: number;
}

export class TilesetLoader {
  private readonly loaded = new Map<string, Cesium.Cesium3DTileset>();

  constructor(private readonly viewer: Cesium.Viewer) {}

  async load(config: TilesetConfig): Promise<Cesium.Cesium3DTileset> {
    const tileset = await Cesium.Cesium3DTileset.fromUrl(config.uri, {
      maximumScreenSpaceError: config.maximumScreenSpaceError ?? 16,
    });
    if (config.transform) {
      if (config.transform.length !== 16) {
        throw new Error(`Tileset ${config.id} transform must contain 16 numbers`);
      }
      tileset.modelMatrix = Cesium.Matrix4.fromArray(config.transform);
    }
    this.viewer.scene.primitives.add(tileset);
    this.loaded.set(config.id, tileset);
    return tileset;
  }

  setVisible(id: string, visible: boolean): void {
    const tileset = this.loaded.get(id);
    if (tileset) {
      tileset.show = visible;
    }
  }

  remove(id: string): void {
    const tileset = this.loaded.get(id);
    if (!tileset) {
      return;
    }
    this.viewer.scene.primitives.remove(tileset);
    this.loaded.delete(id);
  }
}
```

Do not load every tileset at scene start. Respect layer visibility and the
camera frustum, and release primitives when a layer or scene is destroyed.

## GlbLoader

```ts
export interface GlbConfig {
  id: string;
  uri: string;
  position: Cesium.Cartesian3;
  heading?: number;
  pitch?: number;
  roll?: number;
  scale?: number;
}

export class GlbLoader {
  constructor(private readonly viewer: Cesium.Viewer) {}

  load(config: GlbConfig): Cesium.Entity {
    return this.viewer.entities.add({
      id: config.id,
      position: config.position,
      orientation: Cesium.Transforms.headingPitchRollQuaternion(
        config.position,
        new Cesium.HeadingPitchRoll(
          Cesium.Math.toRadians(config.heading ?? 0),
          Cesium.Math.toRadians(config.pitch ?? 0),
          Cesium.Math.toRadians(config.roll ?? 0),
        ),
      ),
      model: {
        uri: config.uri,
        scale: config.scale ?? 1,
        minimumPixelSize: 32,
      },
    });
  }
}
```

For many identical machines or people, do not create one high-detail GLB per
object. Use point/billboard collections or instanced primitives, and keep a
stable `entityId` in the pick metadata rather than serialising the whole
business object.

## Measurement

```ts
export type MeasureMode = "distance" | "area" | "height";

export class MeasurementHandler {
  private readonly handler: Cesium.ScreenSpaceEventHandler;
  private readonly worldPoints: Cesium.Cartesian3[] = [];
  private readonly scenePoints: ScenePosition[] = [];

  constructor(
    private readonly viewer: Cesium.Viewer,
    private readonly mode: MeasureMode,
    /** Supplied by the scene manager; uses the same adapter as asset placement. */
    private readonly toScene: (world: Cesium.Cartesian3) => ScenePosition,
    private readonly onResult: (result: { distance?: number; area?: number; height?: number }) => void,
  ) {
    this.handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    this.handler.setInputAction(
      (event: Cesium.ScreenSpaceEventHandler.PositionedEvent) =>
        this.addPoint(event.position),
      Cesium.ScreenSpaceEventType.LEFT_CLICK,
    );
    this.handler.setInputAction(
      () => this.reset(),
      Cesium.ScreenSpaceEventType.RIGHT_CLICK,
    );
  }

  private addPoint(screenPosition: Cesium.Cartesian2): void {
    // For terrain-aware picking use pickPosition; ensure the scene supports it.
    const picked = this.viewer.scene.pickPosition(screenPosition);
    if (!Cesium.defined(picked)) {
      return;
    }
    this.worldPoints.push(picked);
    this.scenePoints.push(this.toScene(picked));

    if (this.mode === "distance" && this.worldPoints.length >= 2) {
      let total = 0;
      for (let i = 1; i < this.worldPoints.length; i += 1) {
        total += Cesium.Cartesian3.distance(
          this.worldPoints[i - 1],
          this.worldPoints[i],
        );
      }
      this.onResult({ distance: total });
    }
    if (this.mode === "height" && this.scenePoints.length >= 2) {
      // Scene-frame Z, not ECEF Z.
      this.onResult({
        height: Math.abs(this.scenePoints[0].z - this.scenePoints[1].z),
      });
    }
    if (this.mode === "area" && this.scenePoints.length >= 3) {
      // Local mine excavation: shoelace formula on scene-frame X/Y.
      // Do not apply a spherical area formula to mine local coordinates.
      this.onResult({ area: planarArea(this.scenePoints) });
    }
  }

  private reset(): void {
    this.worldPoints.length = 0;
    this.scenePoints.length = 0;
  }

  destroy(): void {
    this.handler.destroy();
  }
}

export function planarArea(points: ScenePosition[]): number {
  let twiceArea = 0;
  for (let i = 0; i < points.length; i += 1) {
    const current = points[i];
    const next = points[(i + 1) % points.length];
    twiceArea += current.x * next.y - next.x * current.y;
  }
  return Math.abs(twiceArea) / 2;
}
```

Area measurement is only valid after an explicit projection into the scene
plane. Do not treat raw ECEF coordinates as a planar polygon.

## Clipping

```ts
export function setTilesetClipping(
  tileset: Cesium.Cesium3DTileset,
  plane: Cesium.ClippingPlane,
  enabled: boolean,
): void {
  tileset.clippingPlanes = enabled
    ? new Cesium.ClippingPlaneCollection({
        planes: [plane],
        edgeColor: Cesium.Color.WHITE.withAlpha(0.5),
        edgeWidth: 2,
      })
    : undefined;
}

export function setGlobeClipping(
  viewer: Cesium.Viewer,
  plane: Cesium.ClippingPlane | undefined,
): void {
  viewer.scene.globe.clippingPlanes = plane
    ? new Cesium.ClippingPlaneCollection({ planes: [plane] })
    : undefined;
}
```

Clipping planes are expressed in world coordinates. Build them through the
coordinate adapter; do not hand-write ECEF constants. Always provide a way to
disable clipping and restore the unclipped view.

## Checklist

- Viewer, terrain and imagery URLs come from configuration.
- One CoordinateAdapter instance is shared by loaders and interaction handlers.
- Every asset transform is a 16-number column-major matrix or is omitted.
- Layers can be hidden and destroyed without leaking GPU resources.
- Measurement and clipping use the same coordinate adapter.
- Cesium code stays in the scene module; Vue components call a service.
