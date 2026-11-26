# Footprint CSV and Box Construction (v0.1)

## Required columns

| Column | Type | Meaning |
|---|---|---|
| `id` | string | Unique footprint identifier; becomes the OBJ object name |
| `x` | number | Footprint centre X in source coordinates |
| `y` | number | Footprint centre Y in source coordinates |
| `width` | number | Box size along local X; must be > 0 |
| `depth` | number | Box size along local Y; must be > 0 |
| `height` | number | Box height upward from the base; must be > 0 |
| `rotation_deg` | number | Counter-clockwise rotation around +Z in degrees |

## Optional base elevation

`base_z` is optional. `z` is accepted as an alias. When present and non-empty,
the value is used directly and `base_z_source` is `footprints_csv`.

When absent, the base is taken from the terrain vertex nearest to `(x, y)` in
plan view; `base_z_source` is `nearest_terrain_vertex`. This is a v0.1
approximation: on a slope the box base is horizontal and does not follow the
terrain, and a single elevation cannot represent cut-and-fill.

## Box construction

Let `theta = radians(rotation_deg)`, `hx = width / 2`, `hy = depth / 2`, and
`base = base_z`. A local point `(lx, ly, lz)` maps to:

```text
x = x_centre + cos(theta) * lx - sin(theta) * ly
y = y_centre + sin(theta) * lx + cos(theta) * ly
z = base + lz
```

The box spans `lx in [-hx, hx]`, `ly in [-hy, hy]`, `lz in [0, height]`.
Each of the six faces is emitted as two triangles with outward winding.

## Bounds

For a rectangle rotated by `theta`, the plan-view half extents are:

```text
half_x = |hx * cos(theta)| + |hy * sin(theta)|
half_y = |hx * sin(theta)| + |hy * cos(theta)|
```

The Z range is `base_z` to `base_z + height`. These are the values written to
the manifest and checked by the tests.

## Limits

- A footprint is a rectangle, not an arbitrary CAD polygon.
- Only vertical extrusion is supported; roofs, overhangs and terrain clipping
  are not modeled.
- Footprints are not deduplicated or checked for overlap.
- Rotation is stored in degrees but computed in radians; no reorientation of
  the source axes is performed.
