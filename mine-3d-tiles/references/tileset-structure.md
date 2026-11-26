# Minimal 3D Tiles 1.1 Structure (v0.1)

## Generated document

```json
{
  "asset": {
    "version": "1.1",
    "generator": "open-mining-skills mine-3d-tiles v0.1"
  },
  "geometricError": 11.874342087037917,
  "root": {
    "boundingVolume": {
      "box": [105, 202.5, 12,
              5, 0, 0,
              0, 2.5, 0,
              0, 0, 2]
    },
    "geometricError": 0,
    "refine": "ADD",
    "content": {"uri": "dummy.obj"}
  }
}
```

## Fields

| Field | Meaning in v0.1 |
|---|---|
| `asset.version` | Fixed to `1.1` for generated tilesets |
| `asset.generator` | Tool identification string |
| `geometricError` | Root-level error metric in the content's linear units (assumed metres by CesiumJS, but units are `UNKNOWN`), defaulting to the bbox diagonal |
| `root.geometricError` | `0`, because the single tile is a leaf |
| `root.refine` | `ADD` by default; `REPLACE` may be supplied |
| `root.boundingVolume.box` | Axis-aligned oriented box derived from the bbox |
| `root.content.uri` | Relative, URL-encoded file name next to `tileset.json` |

## The 12-value box

The `box` array is:

```text
[centre_x, centre_y, centre_z,
 half_axis_1_x, half_axis_1_y, half_axis_1_z,
 half_axis_2_x, half_axis_2_y, half_axis_2_z,
 half_axis_3_x, half_axis_3_y, half_axis_3_z]
```

For an axis-aligned bounding box with minimum `(minx, miny, minz)` and maximum
`(maxx, maxy, maxz)`:

```text
centre    = ((minx+maxx)/2, (miny+maxy)/2, (minz+maxz)/2)
half_axis_1 = ((maxx-minx)/2, 0, 0)
half_axis_2 = (0, (maxy-miny)/2, 0)
half_axis_3 = (0, 0, (maxz-minz)/2)
```

The validator checks the array length and that all values are finite. It warns
when a half-axis has zero length. The half-axes are not required to be
orthogonal by the validator, but this generator always writes an axis-aligned box.

## Bounds sources

| Content | Default bounds | Override |
|---|---|---|
| OBJ | Minimum and maximum of all `v` records | `--bbox` (warning recorded) |
| GLB | None; `--bbox` is mandatory in v0.1 | `--bbox` |

`geometricError` defaults to the Euclidean length of the bbox diagonal. This is
a conservative single-tile placeholder, not a screen-space error derived from a
LOD policy. Supply `--geometric-error` when the scene has a documented error
budget.

## Coordinate frame and units

The generator does not transform coordinates. The tileset box and content are
in the same frame as the content file, which v0.1 treats as `UNKNOWN` units and
`UNKNOWN` CRS.

For OBJ, the auto-computed box is in the OBJ frame (commonly Z-up). For GLB,
`--bbox` must be expressed in the GLB content frame, which is normally glTF
Y-up. A GLB exported by `mine-3d-modeling` has already been converted from
Z-up to Y-up; use `glb.position_bounds` from that skill's
`model_manifest.json` as `--bbox` instead of the Z-up merged bounds.

A CesiumJS scene that expects WGS84/ECEF must add an explicit georeferencing
transform outside this skill; do not assume the tileset is georeferenced.

## Content packaging

The content file is copied next to `tileset.json`; the URI is the URL-encoded
file name. The original source file is never modified. If the source already
lives in the output directory, no copy is made.

## Single-tile limitation

There are no children, no `contents` array, no external tilesets and no LOD.
The tileset loads one content file when the root is in view. This is sufficient
for small mine assets and for integration tests, not for large terrain or
point-cloud scenes.
