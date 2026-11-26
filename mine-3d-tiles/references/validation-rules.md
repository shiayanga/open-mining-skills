# Tileset Validation Rules (v0.1)

`validate_tileset.py` validates one local tileset file with a single root tile.
It prints a check list, warnings and errors, and exits `1` if any required check
fails.

## Required checks

| Check | Failure code |
|---|---|
| Tileset file exists and is a file | `FILE_NOT_FOUND` |
| JSON parses as UTF-8 | `JSON_INVALID` |
| Top-level value is an object | `ROOT_OBJECT_INVALID` |
| `asset` object exists | `ASSET_MISSING` |
| `asset.version` is a non-empty string | `ASSET_VERSION_MISSING` |
| `asset.version` is `1.0` or `1.1` | `ASSET_VERSION_UNSUPPORTED` |
| `root` object exists | `ROOT_MISSING` |
| Top-level `geometricError` is numeric and non-negative | `GEOMETRIC_ERROR_MISSING`, `GEOMETRIC_ERROR_NEGATIVE` |
| `root.geometricError` is numeric and non-negative | `ROOT_GEOMETRIC_ERROR_MISSING`, `ROOT_GEOMETRIC_ERROR_NEGATIVE` |
| `root.boundingVolume` object exists | `BOUNDING_VOLUME_MISSING` |
| `root.boundingVolume.box` has exactly 12 values | `BOX_LENGTH_INVALID` |
| Every box value is finite and numeric | `BOX_VALUE_INVALID` |
| `root.content` object exists | `CONTENT_MISSING`, `CONTENT_INVALID` |
| A single `content` is used, not a `contents` array | `MULTIPLE_CONTENTS_UNSUPPORTED` |
| Content URI is present | `CONTENT_URI_MISSING` |
| Content URI is local and relative | `CONTENT_URI_REMOTE`, `CONTENT_URI_ABSOLUTE` |
| Content file exists | `CONTENT_FILE_MISSING` |

## Warnings (do not fail validation)

| Code | Meaning |
|---|---|
| `ROOT_ERROR_ABOVE_TILESET` | Root geometricError is greater than the top-level value |
| `BOX_DEGENERATE` | At least one box half-axis has zero length |
| `LEGACY_CONTENT_URL` | Content uses `url` instead of `uri` |
| `CONTENT_URI_QUERY` | URI contains a query or fragment |
| `CONTENT_OUTSIDE_TILESET_DIR` | Content resolves outside the tileset directory |
| `CONTENT_EMPTY` | Content file has zero bytes |

## Accepted shape

- `asset.version` may be `1.0` or `1.1`.
- A single `root.content` object is validated; `root.contents` arrays are
  rejected as unsupported.
- `content.uri` is preferred; a legacy non-empty `content.url` is accepted with
  a warning.
- The URI may be percent-encoded; it is decoded before the file check.
- Only `boundingVolume.box` is checked. `region` and `sphere` are not validated.

## Not checked

- Child tiles and nested `children` arrays
- External tilesets and implicit tiling
- GLB/glTF internal validity, buffer lengths or accessor bounds
- Coordinate reference systems, units or height datums
- Visual correctness, texture availability, attribute metadata
- CesiumJS runtime behaviour or LOD switching

## Exit codes

| Code | Meaning |
|---|---|
| `0` | All required checks passed (warnings may exist) |
| `1` | Missing file, invalid JSON, or at least one required check failed |

## Reproducing a failure

```bash
python3 scripts/validate_tileset.py tiles_output/tileset.json
# remove or rename the content file, then re-run
python3 scripts/validate_tileset.py tiles_output/tileset.json --json
```
