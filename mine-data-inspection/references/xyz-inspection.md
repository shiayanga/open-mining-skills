# XYZ / CSV Inspection Notes

## Auto-detection

- **Delimiter**: comma, semicolon, tab or whitespace, chosen from the first 50 non-empty lines.
- **Encoding**: `utf-8-sig` → `utf-8` → `gbk` → `latin-1`.
- **Header**: a first row is treated as a header when any of the first five rows contains a non-numeric token.
- **Column names**: `X` / `Easting` / `东坐标`, `Y` / `Northing` / `北坐标`, `Z` / `Elevation` / `高程`.

## Column options

`--x-col`, `--y-col`, `--z-col` are **1-based** and override header inference.

| Option | Meaning |
|---|---|
| `--delimiter ,` / `;` / `tab` | Force a delimiter |
| `--header` / `--no-header` | Force header handling |
| `--x-col N` | 1-based X column |
| `--y-col N` | 1-based Y column |
| `--z-col N` | 1-based Z column |
| `--encoding` | Force a text encoding |

## Reported checks

- valid point count and skipped rows (with line numbers and reasons)
- extents and Z span
- duplicate coordinates (exact tuple match)
- all-zero Z (possible 2D data)
- coordinate magnitude clue: `DEGREE_CANDIDATE`, `PROJECTED_METER_CANDIDATE` or `LOCAL_OR_UNKNOWN`
- very large Z span warning (possible unit mismatch)

## Limits

- Units are never inferred; `units` is always `UNKNOWN`.
- Duplicate detection uses exact coordinate tuples; no rounding is applied.
- v0.1 reads the whole file into memory. Split very large files first.
- Only the first 50 skipped rows are kept in `skipped_details`.

## Command

```bash
python3 scripts/inspect_xyz.py survey.xyz --output survey.json --markdown survey.md
```
