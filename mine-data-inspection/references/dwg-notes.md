# DWG Handling Notes

`ezdxf` reads DXF files, not DWG files. DWG must be converted before inspection or parsing.

## Recommended flow

1. Keep the original DWG file unchanged and record its checksum.
2. Convert a copy to DXF with a licensed converter, for example ODA File Converter or a vendor-provided tool.
3. Verify the converter license before deployment; do not assume it is free for commercial use.
4. Record the converter name, version and conversion settings in the run manifest.
5. Inspect the converted DXF with `inspect_dxf.py`.
6. Compare the DXF layer and entity inventory with the DWG source (or a manual check) to catch conversion loss.

## Known conversion risks

- Proxy objects and custom objects may be dropped or flattened.
- 3D solids, surfaces and some block references may lose geometry or attributes.
- Text styles, fonts and annotation scales may change.
- XREFs may not be resolved.
- Very large drawings may hit converter limits.

## Why not parse DWG directly

Native DWG parsers are usually proprietary or incomplete. A licensed converter plus DXF inspection is the most reproducible route and keeps the pipeline auditable.

## Command after conversion

```bash
python3 scripts/inspect_dxf.py converted.dxf --output converted.json --markdown converted.md
```
