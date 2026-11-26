# LAS Header Notes (v0.1)

## What is read

`scripts/pointcloud.py inspect` reads the first 375 bytes of an LAS file and
parses the standard header for LAS 1.0 through 1.4. It never reads point
records, VLR payloads or EVLR payloads.

| Offset | Size | Field | Reported as |
|---:|---:|---|---|
| 0 | 4 | File signature `LASF` | `signature` (validated) |
| 4 | 2 | File source ID | not reported |
| 6 | 2 | Global encoding | not reported |
| 24 | 1 | Version major | `version_major` |
| 25 | 1 | Version minor | `version_minor` |
| 26 | 32 | System identifier | `system_identifier` |
| 58 | 32 | Generating software | `generating_software` |
| 90 | 2 | Creation day of year | `creation.day_of_year` |
| 92 | 2 | Creation year | `creation.year` |
| 94 | 2 | Header size | `header_size` |
| 96 | 4 | Offset to point data | `point_data_offset` |
| 100 | 4 | Number of VLRs | `vlr_count` |
| 104 | 1 | Point data format (bit 7 = LAZ) | `point_format.id/raw/compressed` |
| 105 | 2 | Point record length | `point_format.record_length` |
| 107 | 4 | Legacy point count | `legacy_point_count` |
| 111 | 5 x 4 | Legacy points by return | `points_by_return.legacy` |
| 131 | 3 x 8 | X/Y/Z scale | `scale` |
| 155 | 3 x 8 | X/Y/Z offset | `offset` |
| 179 | 6 x 8 | Max X, Min X, Max Y, Min Y, Max Z, Min Z | `bounds` |
| 227 | 8 | Start of waveform data (1.3+) | `waveform_data_offset` |
| 235 | 8 | Start of first EVLR (1.4) | `evlr.offset` |
| 243 | 4 | Number of EVLRs (1.4) | `evlr.count` |
| 247 | 8 | Extended point count (1.4) | `extended_point_count` |
| 255 | 15 x 8 | Extended points by return (1.4) | `points_by_return.extended` |

Standard header sizes: 227 (1.0-1.2), 235 (1.3), 375 (1.4).

## Point count selection

- LAS 1.4 with a complete 375-byte header: prefer the extended count; fall back
  to the legacy count only if the extended count is zero and the legacy count
  is non-zero. The chosen origin is reported as `point_count_source`.
- LAS 1.0-1.3: use the legacy count.
- A mismatch between non-zero legacy and extended counts is warned about.

## Compression (LAZ)

LAZ is LAS with compressed point records. The common LAZ convention sets bit 7
(`0x80`) of the point data format byte, so the inspector masks the format with
`0x7f` and reports `compressed = true`.

**v0.1 does not decompress LAZ records.** It reports the header and warns that
PDAL, laszip or LAStools is required for point-level processing. A `.laz`
extension without the compression bit also produces a warning.

## Consistency checks

The inspector warns when:

- the signature is not `LASF` (fatal `SystemExit`)
- the version is outside 1.0-1.4
- the header is shorter than the standard for its version
- the file is smaller than the declared header size
- the point data offset is before the header or beyond the file
- scale factors contain zero
- min/max bounds are inverted
- a point format outside 0-10 is declared
- formats 6-10 are used with an LAS version older than 1.4
- the header declares zero points
- the uncompressed file is too short for `point_count * record_length`

Header min/max values are copied as declared. No point-level verification is
performed in v0.1, so an incorrect header bound is not detected.

## Limitations that matter

- The header can lie. Point count, bounds and scale/offset are not validated
  against records because records are not decoded.
- VLRs may contain CRS definitions (WKT or GeoTIFF keys), but v0.1 does not
  parse them. CRS stays `UNKNOWN`.
- Extra dimensions, classifications, intensity and GPS time are not inspected.
- LAZ compressed sizes cannot be predicted from the uncompressed record length.

## Planned PDAL integration (v0.2)

1. Run `pdal info` / `pdal pipelines` for point-level statistics and CRS.
2. Decompress LAZ to LAS only when the user explicitly requests it.
3. Use PDAL filters for outlier removal, `SMRF` ground classification and
   voxel downsampling, recording the pipeline JSON and PDAL version.
4. Validate PDAL-produced ground points against this skill's simple lowest-Z
   candidates and report differences.
5. Export cleaned/classified LAZ with the source CRS preserved.
