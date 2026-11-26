"""Shared helpers for the mine Cesium visualization scripts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def file_sha256(path: str | os.PathLike[str], chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 checksum of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Return a small provenance manifest for a source file."""
    p = Path(path)
    return {
        "path": str(p.resolve()),
        "name": p.name,
        "size_bytes": p.stat().st_size,
        "sha256": file_sha256(p),
    }


def load_json(path: str | os.PathLike[str]) -> Any:
    """Read a JSON file, raising a user-facing SystemExit on failure."""
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise SystemExit(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    except OSError as exc:
        raise SystemExit(f"Unable to read {path}: {exc}") from exc


def write_json(path: str | os.PathLike[str], data: Any) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_text(path: str | os.PathLike[str], text: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def fmt(value: float | int | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)
