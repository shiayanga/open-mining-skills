#!/usr/bin/env python3
"""Validate a local, single-root 3D Tiles tileset.

v0.1 checks the asset version, root tile, geometricError values, a
``boundingVolume.box`` of 12 finite values, and that the single root content
file exists locally. It does not traverse child tiles, validate multiple
``contents`` entries, or inspect GLB internals.

Exit code 0 means all required checks passed; 1 means at least one failed.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
from pathlib import Path

SUPPORTED_VERSIONS = {"1.0", "1.1"}


def _is_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(number)


def validate_tileset(path: str) -> dict:
    """Validate one tileset file and return a machine-readable result."""
    tileset_path = Path(path)
    result: dict = {
        "tileset": str(tileset_path),
        "ok": False,
        "asset_version": None,
        "checks": [],
        "errors": [],
        "warnings": [],
    }

    def record(name: str, ok: bool, detail: str = "") -> None:
        result["checks"].append({"name": name, "ok": ok, "detail": detail})

    def error(code: str, message: str) -> None:
        result["errors"].append({"code": code, "message": message})

    def warning(code: str, message: str) -> None:
        result["warnings"].append({"code": code, "message": message})

    if not tileset_path.is_file():
        error("FILE_NOT_FOUND", f"Tileset file not found: {tileset_path}")
        record("file exists", False, str(tileset_path))
        return result
    record("file exists", True, str(tileset_path))

    try:
        data = json.loads(tileset_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        error("JSON_INVALID", f"Unable to parse tileset JSON: {exc}")
        record("JSON parses", False)
        return result
    record("JSON parses", True)

    if not isinstance(data, dict):
        error("ROOT_OBJECT_INVALID", "Tileset JSON must be an object")
        record("JSON is an object", False)
        return result
    record("JSON is an object", True)

    asset = data.get("asset")
    if not isinstance(asset, dict):
        error("ASSET_MISSING", "Tileset asset object is missing")
        record("asset", False)
    else:
        record("asset", True)
        version = asset.get("version")
        normalized_version = version.strip() if isinstance(version, str) else ""
        if not normalized_version:
            error("ASSET_VERSION_MISSING", "asset.version must be a non-empty string")
            record("asset.version", False)
        elif normalized_version not in SUPPORTED_VERSIONS:
            error(
                "ASSET_VERSION_UNSUPPORTED",
                f"asset.version {version!r} is not supported; expected 1.0 or 1.1",
            )
            record("asset.version", False, version)
        else:
            result["asset_version"] = normalized_version
            record("asset.version", True, normalized_version)

    root = data.get("root")
    if not isinstance(root, dict):
        error("ROOT_MISSING", "Tileset root tile is missing")
        record("root", False)
        root = None
    else:
        record("root", True)

    top_error = data.get("geometricError")
    if not _is_number(top_error):
        error(
            "GEOMETRIC_ERROR_MISSING",
            "Top-level geometricError must be present and numeric",
        )
        record("geometricError", False)
        top_error = None
    elif float(top_error) < 0:
        error("GEOMETRIC_ERROR_NEGATIVE", "Top-level geometricError must be non-negative")
        record("geometricError", False)
        top_error = None
    else:
        record("geometricError", True, str(top_error))

    if root is not None:
        root_error = root.get("geometricError")
        if not _is_number(root_error):
            error(
                "ROOT_GEOMETRIC_ERROR_MISSING",
                "root.geometricError must be present and numeric",
            )
            record("root.geometricError", False)
        elif float(root_error) < 0:
            error(
                "ROOT_GEOMETRIC_ERROR_NEGATIVE",
                "root.geometricError must be non-negative",
            )
            record("root.geometricError", False)
        else:
            record("root.geometricError", True, str(root_error))
            if top_error is not None and float(root_error) > float(top_error):
                warning(
                    "ROOT_ERROR_ABOVE_TILESET",
                    "root.geometricError exceeds the top-level geometricError",
                )

        bounding_volume = root.get("boundingVolume")
        if not isinstance(bounding_volume, dict):
            error("BOUNDING_VOLUME_MISSING", "root.boundingVolume is missing")
            record("root.boundingVolume", False)
        else:
            box = bounding_volume.get("box")
            if not isinstance(box, list) or len(box) != 12:
                error(
                    "BOX_LENGTH_INVALID",
                    "root.boundingVolume.box must be an array of exactly 12 numbers",
                )
                record("boundingVolume.box", False)
            elif not all(_is_number(value) for value in box):
                error(
                    "BOX_VALUE_INVALID",
                    "root.boundingVolume.box must contain only finite numbers",
                )
                record("boundingVolume.box", False)
            else:
                record("boundingVolume.box", True, "12 numbers")
                axes = [box[3:6], box[6:9], box[9:12]]
                axis_lengths = [
                    math.sqrt(sum(float(value) ** 2 for value in axis))
                    for axis in axes
                ]
                if any(length == 0 for length in axis_lengths):
                    warning(
                        "BOX_DEGENERATE",
                        "One or more boundingVolume.box half-axes have zero length",
                    )

        content = root.get("content")
        if content is None:
            if "contents" in root:
                error(
                    "MULTIPLE_CONTENTS_UNSUPPORTED",
                    "v0.1 validates a single root.content only; root.contents is not supported",
                )
            else:
                error("CONTENT_MISSING", "root.content is missing")
            record("root.content", False)
        elif not isinstance(content, dict):
            error("CONTENT_INVALID", "root.content must be an object")
            record("root.content", False)
        else:
            uri = content.get("uri")
            if not isinstance(uri, str) or not uri.strip():
                if isinstance(content.get("url"), str) and content["url"].strip():
                    uri = content["url"]
                    warning(
                        "LEGACY_CONTENT_URL",
                        "root.content uses legacy 'url'; prefer 'uri' in 3D Tiles 1.1",
                    )
                else:
                    error(
                        "CONTENT_URI_MISSING",
                        "root.content.uri must be a non-empty string",
                    )
                    record("root.content.uri", False)
                    uri = None
            if uri is not None:
                record("root.content.uri", True, uri)
                parsed = urllib.parse.urlparse(uri)
                if parsed.scheme or parsed.netloc:
                    error(
                        "CONTENT_URI_REMOTE",
                        f"Content URI {uri!r} is remote and cannot be verified locally",
                    )
                    record("content file exists", False)
                elif parsed.path.startswith("/"):
                    error(
                        "CONTENT_URI_ABSOLUTE",
                        f"Content URI {uri!r} must be relative to the tileset directory",
                    )
                    record("content file exists", False)
                else:
                    if parsed.query or parsed.fragment:
                        warning(
                            "CONTENT_URI_QUERY",
                            "Content URI contains a query or fragment; only the path is checked",
                        )
                    local_path = (
                        tileset_path.parent / urllib.parse.unquote(parsed.path)
                    ).resolve()
                    base_dir = tileset_path.parent.resolve()
                    if not local_path.is_file():
                        error(
                            "CONTENT_FILE_MISSING",
                            f"Content file does not exist: {local_path}",
                        )
                        record("content file exists", False, str(local_path))
                    else:
                        record("content file exists", True, str(local_path))
                        if local_path.stat().st_size == 0:
                            warning("CONTENT_EMPTY", "Content file is empty")
                        try:
                            local_path.relative_to(base_dir)
                        except ValueError:
                            warning(
                                "CONTENT_OUTSIDE_TILESET_DIR",
                                "Content file is outside the tileset directory",
                            )

    result["ok"] = not result["errors"]
    return result


def render_human(result: dict) -> str:
    lines = [f"Tileset: {result['tileset']}", ""]
    for check in result["checks"]:
        status = "PASS" if check["ok"] else "FAIL"
        detail = f" — {check['detail']}" if check.get("detail") else ""
        lines.append(f"[{status}] {check['name']}{detail}")
    if result["warnings"]:
        lines.extend(["", "Warnings:"])
        lines.extend(
            f"- [{item['code']}] {item['message']}" for item in result["warnings"]
        )
    if result["errors"]:
        lines.extend(["", "Errors:"])
        lines.extend(
            f"- [{item['code']}] {item['message']}" for item in result["errors"]
        )
    lines.extend(
        [
            "",
            "RESULT: PASS" if result["ok"] else f"RESULT: FAIL ({len(result['errors'])} error(s))",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a local single-root 3D Tiles tileset."
    )
    parser.add_argument("tileset", help="Path to tileset.json")
    parser.add_argument(
        "--json", action="store_true", help="Print the full machine-readable result"
    )
    args = parser.parse_args(argv)

    result = validate_tileset(args.tileset)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_human(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
