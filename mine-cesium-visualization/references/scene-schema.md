# Viewer and Scene Manifest Schema

`scripts/validate_scene.py` validates two JSON documents. IDs may be strings or
integers; they are normalised to strings for comparison. Unknown extra fields
are ignored so project-specific metadata can be added safely.

## viewer_config.json

```json
{
  "terrainProvider": {
    "type": "CesiumTerrainProvider",
    "url": "/terrain",
    "requestVertexNormals": true
  },
  "imageryProvider": {
    "type": "UrlTemplateImageryProvider",
    "url": "/imagery/{z}/{x}/{y}.png",
    "credit": "Mine self-hosted imagery"
  },
  "scene": {
    "origin": { "x": 523400.0, "y": 4187600.0, "z": 120.0 },
    "coordinateSystemId": "MINE-LOCAL-001",
    "axisConvention": "X_EAST_Y_NORTH_Z_UP"
  },
  "rendering": {
    "requestRenderMode": true,
    "maximumScreenSpaceError": 16,
    "resolutionScale": 1.0,
    "fxaa": true,
    "shadows": false,
    "globeDepthTestAgainstTerrain": false
  },
  "performance": {
    "tileCacheSize": 256,
    "maximumRequests": 12,
    "foveatedScreenSpaceError": true
  }
}
```

An optional top-level `viewer` wrapper is accepted, and `origin`,
`coordinateSystemId` and `axisConvention` may sit either inside `scene` or at
the top level. New files should use the explicit `scene` block.

### Validated fields

| Field | Rule |
|---|---|
| `terrainProvider.type` | Required non-empty string. |
| `terrainProvider.url` | Required unless the type is `EllipsoidTerrainProvider`. |
| `imageryProvider` | Object or array of objects; `type` required; `url` required except for `GridImageryProvider` / `TileCoordinatesImageryProvider`. |
| `scene.origin` | Required object with finite numeric `x`, `y`, `z`. |
| `scene.coordinateSystemId` | Required; must match the scene manifest. |
| `scene.axisConvention` | Required; unknown values warn. |
| `rendering` | Optional block; screen-space error and resolution scale must be positive; booleans must be real booleans. |
| `performance` | Optional block; cache size and request limits must be positive integers. |

Commercial provider fingerprints (Cesium ion, Cesium World Terrain, Mapbox,
Tianditu, ArcGIS Online, Google/Bing/HERE/MapTiler, AMap, Baidu) are rejected.
Self-hosted, relative and local-network URLs are accepted.

## scene_manifest.json

```json
{
  "sceneId": "SCENE-001",
  "mineId": "MINE-001",
  "coordinateSystemId": "MINE-LOCAL-001",
  "axisConvention": "X_EAST_Y_NORTH_Z_UP",
  "terrain": {
    "type": "cesium-terrain",
    "uri": "/terrain"
  },
  "layers": [
    { "id": "base-terrain", "name": "地表地形", "type": "TERRAIN", "visible": true },
    { "id": "pit", "name": "采坑与边坡", "type": "TILESET", "visible": true }
  ],
  "tilesets": [
    {
      "id": "pit-tileset",
      "layerId": "pit",
      "uri": "/tiles/pit/tileset.json",
      "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
      "maximumScreenSpaceError": 16
    }
  ],
  "models": [
    {
      "id": "excavator-01",
      "layerId": "equipment",
      "uri": "/models/excavator.glb",
      "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
      "scale": 1.0
    }
  ],
  "cameraBookmarks": [
    {
      "id": "pit-overview",
      "name": "采坑全景",
      "destination": { "x": 120.0, "y": -80.0, "z": 260.0 },
      "orientation": { "heading": 0, "pitch": -45, "roll": 0 }
    }
  ]
}
```

### Validated fields

| Field | Rule |
|---|---|
| `sceneId`, `mineId` | Required non-empty string or number. |
| `coordinateSystemId` | Required; must equal the viewer coordinate system. |
| `terrain` | Required; `uri` (or legacy `url`) required except for the ellipsoid type. |
| `layers` | Array; each layer needs a unique non-empty `id`. Known types are `TERRAIN`, `TILESET`, `MODEL`, `PERSON`, `MONITOR_DEVICE`, `MACHINERY`, `INFRASTRUCTURE`, `ANNOTATION`, `ALARM`, `OTHER`. |
| `layers[].parentId` | Must reference an existing layer. |
| `tilesets` | Optional array; unique `id`; non-empty `uri`; optional `layerId` must exist; optional `transform` must contain exactly 16 finite numbers. |
| `models` | Optional array; same rules as tilesets plus positive `scale` and numeric `heading`/`pitch`/`roll`. |
| `cameraBookmarks` | Optional array; unique `id`; destination may be `{x,y,z}` or `{longitude,latitude,height}`; orientation numeric when present. |

A transform is a flat, column-major 4×4 matrix in Cesium convention. When the
transform is omitted, the asset must already be positioned correctly by the
tiling/model pipeline. Layer IDs are scoped to one scene and are unique across
the whole `layers` array; tileset and model IDs are unique within their own
arrays.

## Output report

`scene_validation.json` contains:

- `status`: `PASS` when there are no errors, otherwise `FAIL`.
- `summary`: counts of errors, warnings, layers, tilesets, models and bookmarks.
- `viewer` / `scene`: normalised field summaries.
- `sources`: path, size and SHA-256 for each input file.
- `errors` / `warnings`: entries of `{code, path, message}`.

The Markdown companion `scene_validation.md` lists the same findings in a
human-readable form. Warnings do not fail the CLI; errors exit `1` unless
`--no-fail` is supplied.

## v0.1 limits

- JSON structure and rule validation only; no network fetches and no Cesium
  rendering.
- No schema for camera frustum details, styling, clipping planes or time-dynamic
  data yet.
- Commercial-provider detection is pattern-based; it is a guardrail, not a
  security scanner.
