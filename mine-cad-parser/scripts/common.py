"""Shared helpers for the mine CAD parser."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def file_sha256(path: str | os.PathLike[str], chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest(path: str | os.PathLike[str]) -> dict[str, Any]:
    p = Path(path)
    return {
        "path": str(p.resolve()),
        "name": p.name,
        "size_bytes": p.stat().st_size,
        "sha256": file_sha256(p),
    }


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


def magnitude_clue(min_x: float, min_y: float, max_x: float, max_y: float) -> str:
    abs_max = max(abs(v) for v in (min_x, min_y, max_x, max_y))
    in_degree_range = (
        -180.0 <= min_x <= max_x <= 180.0
        and -90.0 <= min_y <= max_y <= 90.0
    )
    if in_degree_range:
        return "DEGREE_CANDIDATE"
    if abs_max >= 100000.0:
        return "PROJECTED_METER_CANDIDATE"
    return "LOCAL_OR_UNKNOWN"


def fmt(value: float | int | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)
