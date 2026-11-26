# DWG Handling Notes

`ezdxf` reads DXF files, not DWG files. Convert DWG to DXF before parsing.

## Recommended flow

1. Keep the original DWG unchanged and record its checksum.
2. Convert a copy to DXF with a licensed converter, for example ODA File Converter or a vendor-provided tool.
3. Verify the converter license before deployment; do not assume it is free for commercial use.
4. Record the converter name, version and settings.
5. Run `mine-data-inspection` on the converted DXF.
6. Run `parse_dxf.py` and compare layer/entity counts with the source to catch conversion loss.

## Known conversion risks

- Proxy and custom objects may be dropped or flattened.
- 3D solids, surfaces and some block references may lose geometry or attributes.
- Text styles, fonts and annotation scales may change.
- XREFs may not be resolved.
- Very large drawings may hit converter limits.

## Why not parse DWG directly

Native DWG parsers are usually proprietary or incomplete. A licensed converter plus DXF parsing is the most reproducible and auditable route.

## Command after conversion

```bash
python3 scripts/parse_dxf.py converted.dxf --out-dir cad_output
```
