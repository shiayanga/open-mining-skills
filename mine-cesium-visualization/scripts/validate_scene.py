#!/usr/bin/env python3
"""Validate CesiumJS viewer configuration and scene manifest files.

The validator checks that a mine Web scene is configured with a self-hosted
terrain/imagery provider, explicit scene origin and axis convention, sane
rendering/performance settings, unique layer IDs, and well-formed tileset and
model entries. It does not start Cesium or fetch any remote resource.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

import common

KNOWN_AXIS_CONVENTIONS = {
    "X_EAST_Y_NORTH_Z_UP",
    "X_NORTH_Y_EAST_Z_UP",
    "X_EAST_Y_SOUTH_Z_UP",
    "LOCAL_RIGHT_HANDED_Z_UP",
    "ENU",
}

KNOWN_LAYER_TYPES = {
    "TERRAIN",
    "TILESET",
    "MODEL",
    "PERSON",
    "MONITOR_DEVICE",
    "MACHINERY",
    "INFRASTRUCTURE",
    "ANNOTATION",
    "ALARM",
    "OTHER",
}

NO_TERRAIN_URL_TYPES = {"EllipsoidTerrainProvider"}
NO_IMAGERY_URL_TYPES = {"GridImageryProvider", "TileCoordinatesImageryProvider"}

BOOL_RENDERING_KEYS = (
    "requestRenderMode",
    "fxaa",
    "shadows",
    "globeDepthTestAgainstTerrain",
    "showGroundAtmosphere",
)

# Commercial provider fingerprints. The skill requires providers to be
# self-hosted or injected at deployment time, never hardcoded in a scene config.
COMMERCIAL_PROVIDER_PATTERNS = [
    (re.compile(r"cesium\.com", re.IGNORECASE), "Cesium ion / Cesium commercial service"),
    (re.compile(r"cesium\s*ion", re.IGNORECASE), "Cesium ion"),
    (re.compile(r"ion(imagery|terrain|resource)provider", re.IGNORECASE), "Cesium ion provider"),
    (re.compile(r"ionassetid", re.IGNORECASE), "Cesium ion asset"),
    (re.compile(r"worldterrain", re.IGNORECASE), "Cesium World Terrain"),
    (re.compile(r"mapbox", re.IGNORECASE), "Mapbox"),
    (re.compile(r"tianditu|天地图", re.IGNORECASE), "天地图 / Tianditu"),
    (re.compile(r"arcgisonline", re.IGNORECASE), "Esri ArcGIS Online"),
    (re.compile(r"googleapis\.com/maps", re.IGNORECASE), "Google Maps"),
    (re.compile(r"virtualearth|bing\.com/maps", re.IGNORECASE), "Bing Maps"),
    (re.compile(r"\bhere\.com\b", re.IGNORECASE), "HERE"),
    (re.compile(r"maptiler", re.IGNORECASE), "MapTiler"),
    (re.compile(r"\bamap\.com\b|高德", re.IGNORECASE), "高德地图 / AMap"),
    (re.compile(r"\bmap\.baidu\.com\b|百度地图", re.IGNORECASE), "百度地图"),
]


class Issues:
    """Collect validation errors and warnings with a stable path/code."""

    def __init__(self) -> None:
        self.errors: list[dict] = []
        self.warnings: list[dict] = []

    def error(self, code: str, path: str, message: str) -> None:
        self.errors.append({"code": code, "path": path, "message": message})

    def warning(self, code: str, path: str, message: str) -> None:
        self.warnings.append({"code": code, "path": path, "message": message})


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _id_text(value: object) -> str | None:
    """Normalise an ID that may be a non-empty string or a number."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or None
    return None


def _commercial_labels(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    return [
        label
        for pattern, label in COMMERCIAL_PROVIDER_PATTERNS
        if pattern.search(value)
    ]


def _check_commercial(issues: Issues, value: object, path: str) -> None:
    for label in _commercial_labels(value):
        issues.error(
            "COMMERCIAL_PROVIDER",
            path,
            f"Hardcoded commercial provider detected ({label}). Self-host the "
            "service or inject the provider URL at deployment time.",
        )


def _check_transform(issues: Issues, value: object, path: str) -> bool:
    if not isinstance(value, list) or len(value) != 16:
        issues.error(
            "INVALID_TRANSFORM",
            path,
            "Transform must be a flat array of 16 finite numbers.",
        )
        return False
    if not all(_is_number(item) for item in value):
        issues.error(
            "INVALID_TRANSFORM",
            path,
            "Transform contains a non-numeric or non-finite value.",
        )
        return False
    return True


def _uri_field(obj: dict) -> tuple[str | None, str | None]:
    """Return (uri, key) preferring ``uri`` over the legacy ``url`` key."""
    for key in ("uri", "url"):
        value = obj.get(key)
        if _is_nonempty_str(value):
            return value.strip(), key
    return None, None


def _validate_imagery_provider(provider: object, path: str, issues: Issues) -> dict:
    info: dict = {}
    if not isinstance(provider, dict):
        issues.error("INVALID_IMAGERY_PROVIDER", path, "Imagery provider must be an object.")
        return info
    provider_type = provider.get("type")
    if not _is_nonempty_str(provider_type):
        issues.error("MISSING_IMAGERY_TYPE", f"{path}.type", "Imagery provider type is required.")
    else:
        provider_type = provider_type.strip()
        info["type"] = provider_type
        _check_commercial(issues, provider_type, f"{path}.type")
    url = provider.get("url")
    if _is_nonempty_str(url):
        info["url"] = url.strip()
        _check_commercial(issues, url, f"{path}.url")
    elif provider_type not in NO_IMAGERY_URL_TYPES:
        issues.error(
            "MISSING_IMAGERY_URL",
            f"{path}.url",
            "Imagery provider URL is required unless the provider is a local "
            "grid/tile-coordinate debug provider.",
        )
    elif url is not None and not isinstance(url, str):
        issues.error("INVALID_IMAGERY_URL", f"{path}.url", "Imagery URL must be a string.")
    credit = provider.get("credit")
    if credit is not None and not isinstance(credit, str):
        issues.warning("INVALID_IMAGERY_CREDIT", f"{path}.credit", "Imagery credit should be a string.")
    return info


def validate_viewer_config(config: object, issues: Issues) -> dict:
    """Validate viewer_config.json and return a normalised summary."""
    info: dict = {"present": False, "imageryProviders": []}
    if not isinstance(config, dict):
        issues.error("INVALID_VIEWER_CONFIG", "viewer", "Viewer config root must be a JSON object.")
        return info

    viewer = config.get("viewer") if isinstance(config.get("viewer"), dict) else config
    info["present"] = True
    if "viewer" in config and not isinstance(config["viewer"], dict):
        issues.error("INVALID_VIEWER_BLOCK", "viewer", "The optional viewer block must be an object.")

    scene = viewer.get("scene")
    if scene is not None and not isinstance(scene, dict):
        issues.error("INVALID_SCENE_BLOCK", "scene", "The scene block must be an object.")
        scene = {}
    scene = scene or {}

    coordinate_value = scene.get("coordinateSystemId", viewer.get("coordinateSystemId"))
    coordinate_id = _id_text(coordinate_value)
    if coordinate_id is None:
        issues.error(
            "MISSING_COORDINATE_SYSTEM_ID",
            "scene.coordinateSystemId",
            "coordinateSystemId is required; never treat mine XYZ as WGS84 implicitly.",
        )
    else:
        info["coordinateSystemId"] = coordinate_id

    axis_value = scene.get("axisConvention", viewer.get("axisConvention"))
    if not _is_nonempty_str(axis_value):
        issues.error(
            "MISSING_AXIS_CONVENTION",
            "scene.axisConvention",
            "axisConvention is required (for example X_EAST_Y_NORTH_Z_UP).",
        )
    else:
        axis = axis_value.strip()
        info["axisConvention"] = axis
        if axis not in KNOWN_AXIS_CONVENTIONS:
            issues.warning(
                "UNKNOWN_AXIS_CONVENTION",
                "scene.axisConvention",
                f"Unrecognised axis convention '{axis}'; document its handedness and axis order.",
            )

    origin = scene.get("origin", viewer.get("origin", viewer.get("sceneOrigin")))
    if origin is None:
        issues.error(
            "MISSING_SCENE_ORIGIN",
            "scene.origin",
            "A scene origin with numeric x/y/z is required for local mine coordinates.",
        )
    elif not isinstance(origin, dict):
        issues.error("INVALID_SCENE_ORIGIN", "scene.origin", "Scene origin must be an object.")
    else:
        valid = True
        for axis_name in ("x", "y", "z"):
            if not _is_number(origin.get(axis_name)):
                valid = False
                issues.error(
                    "INVALID_SCENE_ORIGIN",
                    f"scene.origin.{axis_name}",
                    f"Origin {axis_name} must be a finite number.",
                )
        if valid:
            info["origin"] = {key: float(origin[key]) for key in ("x", "y", "z")}

    terrain = viewer.get("terrainProvider")
    if not isinstance(terrain, dict):
        issues.error(
            "MISSING_TERRAIN_PROVIDER",
            "terrainProvider",
            "terrainProvider is required; configure a self-hosted terrain service "
            "or the ellipsoid fallback explicitly.",
        )
    else:
        terrain_type = terrain.get("type")
        terrain_type_text = None
        if not _is_nonempty_str(terrain_type):
            issues.error("MISSING_TERRAIN_TYPE", "terrainProvider.type", "Terrain provider type is required.")
        else:
            terrain_type_text = terrain_type.strip()
            info["terrainProviderType"] = terrain_type_text
            _check_commercial(issues, terrain_type_text, "terrainProvider.type")
        terrain_url = terrain.get("url")
        if _is_nonempty_str(terrain_url):
            info["terrainUrl"] = terrain_url.strip()
            _check_commercial(issues, terrain_url, "terrainProvider.url")
        elif terrain_type_text not in NO_TERRAIN_URL_TYPES:
            issues.error(
                "MISSING_TERRAIN_URL",
                "terrainProvider.url",
                "Terrain provider URL is required unless EllipsoidTerrainProvider is used.",
            )
        elif terrain_url is not None and not isinstance(terrain_url, str):
            issues.error("INVALID_TERRAIN_URL", "terrainProvider.url", "Terrain URL must be a string.")
        for key in ("requestVertexNormals", "requestWaterMask"):
            if key in terrain and not isinstance(terrain[key], bool):
                issues.error(
                    "INVALID_TERRAIN_OPTION",
                    f"terrainProvider.{key}",
                    f"{key} must be a boolean.",
                )

    imagery = viewer.get("imageryProvider")
    if imagery is None:
        issues.warning(
            "MISSING_IMAGERY_PROVIDER",
            "imageryProvider",
            "No imagery provider configured; the scene will have no base imagery.",
        )
    elif isinstance(imagery, dict):
        info["imageryProviders"].append(_validate_imagery_provider(imagery, "imageryProvider", issues))
    elif isinstance(imagery, list):
        if not imagery:
            issues.warning(
                "MISSING_IMAGERY_PROVIDER",
                "imageryProvider",
                "imageryProvider list is empty; the scene will have no base imagery.",
            )
        for index, provider in enumerate(imagery):
            info["imageryProviders"].append(
                _validate_imagery_provider(provider, f"imageryProvider[{index}]", issues)
            )
    else:
        issues.error(
            "INVALID_IMAGERY_PROVIDER",
            "imageryProvider",
            "imageryProvider must be an object or a non-empty array of objects.",
        )

    rendering = viewer.get("rendering")
    if rendering is None:
        issues.warning(
            "MISSING_RENDERING_SETTINGS",
            "rendering",
            "No rendering settings block; Cesium defaults will be used implicitly.",
        )
    elif not isinstance(rendering, dict):
        issues.error("INVALID_RENDERING_SETTINGS", "rendering", "rendering must be an object.")
    else:
        mse = rendering.get("maximumScreenSpaceError")
        if mse is not None:
            if not _is_number(mse) or float(mse) <= 0:
                issues.error(
                    "INVALID_SCREEN_SPACE_ERROR",
                    "rendering.maximumScreenSpaceError",
                    "maximumScreenSpaceError must be a positive number.",
                )
            else:
                if float(mse) > 64:
                    issues.warning(
                        "COARSE_SCREEN_SPACE_ERROR",
                        "rendering.maximumScreenSpaceError",
                        "maximumScreenSpaceError is above 64; terrain may look excessively coarse.",
                    )
                elif float(mse) < 1:
                    issues.warning(
                        "AGGRESSIVE_SCREEN_SPACE_ERROR",
                        "rendering.maximumScreenSpaceError",
                        "maximumScreenSpaceError is below 1; tile requests may overload the client.",
                    )
                info["maximumScreenSpaceError"] = float(mse)
        resolution = rendering.get("resolutionScale")
        if resolution is not None:
            if not _is_number(resolution) or float(resolution) <= 0:
                issues.error(
                    "INVALID_RESOLUTION_SCALE",
                    "rendering.resolutionScale",
                    "resolutionScale must be a positive number.",
                )
            else:
                if float(resolution) > 2:
                    issues.warning(
                        "HIGH_RESOLUTION_SCALE",
                        "rendering.resolutionScale",
                        "resolutionScale above 2 significantly increases GPU load.",
                    )
                info["resolutionScale"] = float(resolution)
        for key in BOOL_RENDERING_KEYS:
            if key in rendering and not isinstance(rendering[key], bool):
                issues.error(
                    "INVALID_RENDERING_SETTING",
                    f"rendering.{key}",
                    f"{key} must be a boolean.",
                )

    performance = viewer.get("performance")
    if performance is None:
        issues.warning(
            "MISSING_PERFORMANCE_SETTINGS",
            "performance",
            "No performance settings block; tile cache and request limits are implicit.",
        )
    elif not isinstance(performance, dict):
        issues.error("INVALID_PERFORMANCE_SETTINGS", "performance", "performance must be an object.")
    else:
        tile_cache = performance.get("tileCacheSize")
        if tile_cache is not None:
            if not isinstance(tile_cache, int) or isinstance(tile_cache, bool) or tile_cache <= 0:
                issues.error(
                    "INVALID_TILE_CACHE_SIZE",
                    "performance.tileCacheSize",
                    "tileCacheSize must be a positive integer.",
                )
            else:
                if tile_cache > 4096:
                    issues.warning(
                        "LARGE_TILE_CACHE",
                        "performance.tileCacheSize",
                        "tileCacheSize above 4096 may exceed browser memory budgets.",
                    )
                info["tileCacheSize"] = tile_cache
        maximum_requests = performance.get("maximumRequests")
        if maximum_requests is not None:
            if (
                not isinstance(maximum_requests, int)
                or isinstance(maximum_requests, bool)
                or maximum_requests <= 0
            ):
                issues.error(
                    "INVALID_MAXIMUM_REQUESTS",
                    "performance.maximumRequests",
                    "maximumRequests must be a positive integer.",
                )
            else:
                if maximum_requests > 100:
                    issues.warning(
                        "HIGH_MAXIMUM_REQUESTS",
                        "performance.maximumRequests",
                        "maximumRequests above 100 may saturate browser connections.",
                    )
                info["maximumRequests"] = maximum_requests
        if "foveatedScreenSpaceError" in performance and not isinstance(
            performance["foveatedScreenSpaceError"], bool
        ):
            issues.error(
                "INVALID_PERFORMANCE_SETTING",
                "performance.foveatedScreenSpaceError",
                "foveatedScreenSpaceError must be a boolean.",
            )
    return info


def _validate_layers(manifest: dict, issues: Issues) -> tuple[list[str], int]:
    layers = manifest.get("layers")
    if not isinstance(layers, list):
        issues.error("INVALID_LAYERS", "layers", "layers must be an array.")
        return [], 0
    if not layers:
        issues.warning("NO_LAYERS", "layers", "The scene manifest has no layers.")

    ids: list[str] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    parent_refs: list[tuple[int, str]] = []

    for index, layer in enumerate(layers):
        path = f"layers[{index}]"
        if not isinstance(layer, dict):
            issues.error("INVALID_LAYER", path, "Layer must be an object.")
            continue
        layer_id = _id_text(layer.get("id"))
        if layer_id is None:
            issues.error("MISSING_LAYER_ID", f"{path}.id", "Layer id is required.")
        else:
            ids.append(layer_id)
            if layer_id in seen:
                duplicates.add(layer_id)
            seen.add(layer_id)
        name = layer.get("name")
        if not _is_nonempty_str(name):
            issues.warning("MISSING_LAYER_NAME", f"{path}.name", "Layer name is missing.")
        layer_type = layer.get("type")
        if not _is_nonempty_str(layer_type):
            issues.warning("MISSING_LAYER_TYPE", f"{path}.type", "Layer type is missing.")
        elif layer_type.strip().upper() not in KNOWN_LAYER_TYPES:
            issues.warning(
                "UNKNOWN_LAYER_TYPE",
                f"{path}.type",
                f"Layer type '{layer_type}' is not in the documented set.",
            )
        if "visible" in layer and not isinstance(layer["visible"], bool):
            issues.error("INVALID_LAYER_VISIBILITY", f"{path}.visible", "visible must be a boolean.")
        if "opacity" in layer:
            opacity = layer["opacity"]
            if not _is_number(opacity) or not 0.0 <= float(opacity) <= 1.0:
                issues.error(
                    "INVALID_LAYER_OPACITY",
                    f"{path}.opacity",
                    "opacity must be a number between 0 and 1.",
                )
        parent_id = layer.get("parentId")
        if parent_id is not None:
            parent_text = _id_text(parent_id)
            if parent_text is None:
                issues.error("INVALID_PARENT_LAYER", f"{path}.parentId", "parentId must be a non-empty ID.")
            else:
                parent_refs.append((index, parent_text))
    for layer_id in sorted(duplicates):
        issues.error(
            "DUPLICATE_LAYER_ID",
            "layers",
            f"Layer id '{layer_id}' is used more than once; layer ids must be unique.",
        )
    for index, parent_text in parent_refs:
        if parent_text not in seen:
            issues.error(
                "UNKNOWN_PARENT_LAYER",
                f"layers[{index}].parentId",
                f"Parent layer '{parent_text}' does not exist.",
            )
    return ids, len(layers)


def _validate_assets(
    manifest: dict,
    key: str,
    kind: str,
    layer_ids: set[str],
    issues: Issues,
) -> int:
    assets = manifest.get(key)
    if assets is None:
        return 0
    if not isinstance(assets, list):
        issues.error(f"INVALID_{kind.upper()}S", key, f"{key} must be an array.")
        return 0

    seen: set[str] = set()
    for index, asset in enumerate(assets):
        path = f"{key}[{index}]"
        if not isinstance(asset, dict):
            issues.error(f"INVALID_{kind.upper()}", path, f"{kind} entry must be an object.")
            continue
        asset_id = _id_text(asset.get("id"))
        if asset_id is None:
            issues.error(
                f"MISSING_{kind.upper()}_ID",
                f"{path}.id",
                f"{kind} id is required.",
            )
        elif asset_id in seen:
            issues.error(
                f"DUPLICATE_{kind.upper()}_ID",
                f"{path}.id",
                f"{kind} id '{asset_id}' is duplicated.",
            )
        else:
            seen.add(asset_id)

        uri, uri_key = _uri_field(asset)
        if uri is None:
            issues.error(
                f"MISSING_{kind.upper()}_URI",
                f"{path}.uri",
                f"{kind} uri must be present and non-empty.",
            )
        else:
            _check_commercial(issues, uri, f"{path}.{uri_key}")

        if "transform" in asset:
            _check_transform(issues, asset["transform"], f"{path}.transform")

        layer_id = asset.get("layerId")
        if layer_id is None:
            issues.warning(
                f"MISSING_{kind.upper()}_LAYER",
                f"{path}.layerId",
                f"{kind} is not assigned to a scene layer.",
            )
        else:
            layer_text = _id_text(layer_id)
            if layer_text is None:
                issues.error(
                    "INVALID_LAYER_REF",
                    f"{path}.layerId",
                    "layerId must be a non-empty ID.",
                )
            elif layer_text not in layer_ids:
                issues.error(
                    "UNKNOWN_LAYER_REF",
                    f"{path}.layerId",
                    f"Layer '{layer_text}' is not declared in layers.",
                )

        if key == "tilesets":
            mse = asset.get("maximumScreenSpaceError")
            if mse is not None and (not _is_number(mse) or float(mse) <= 0):
                issues.error(
                    "INVALID_SCREEN_SPACE_ERROR",
                    f"{path}.maximumScreenSpaceError",
                    "maximumScreenSpaceError must be a positive number.",
                )
        if key == "models":
            scale = asset.get("scale")
            if scale is not None and (not _is_number(scale) or float(scale) <= 0):
                issues.error(
                    "INVALID_MODEL_SCALE",
                    f"{path}.scale",
                    "Model scale must be a positive number.",
                )
            for key_name in ("heading", "pitch", "roll"):
                if key_name in asset and not _is_number(asset[key_name]):
                    issues.error(
                        "INVALID_MODEL_ORIENTATION",
                        f"{path}.{key_name}",
                        f"{key_name} must be a finite number.",
                    )
    return len(assets)


def _validate_camera_bookmarks(manifest: dict, issues: Issues) -> int:
    bookmarks = manifest.get("cameraBookmarks")
    if bookmarks is None:
        return 0
    if not isinstance(bookmarks, list):
        issues.error("INVALID_CAMERA_BOOKMARKS", "cameraBookmarks", "cameraBookmarks must be an array.")
        return 0

    seen: set[str] = set()
    for index, bookmark in enumerate(bookmarks):
        path = f"cameraBookmarks[{index}]"
        if not isinstance(bookmark, dict):
            issues.error("INVALID_CAMERA_BOOKMARK", path, "Camera bookmark must be an object.")
            continue
        bookmark_id = _id_text(bookmark.get("id"))
        if bookmark_id is None:
            issues.error("MISSING_BOOKMARK_ID", f"{path}.id", "Camera bookmark id is required.")
        elif bookmark_id in seen:
            issues.error(
                "DUPLICATE_BOOKMARK_ID",
                f"{path}.id",
                f"Camera bookmark id '{bookmark_id}' is duplicated.",
            )
        else:
            seen.add(bookmark_id)
        if not _is_nonempty_str(bookmark.get("name")):
            issues.warning("MISSING_BOOKMARK_NAME", f"{path}.name", "Camera bookmark name is missing.")

        destination = bookmark.get("destination")
        if isinstance(destination, list):
            if len(destination) != 3 or not all(_is_number(value) for value in destination):
                issues.error(
                    "INVALID_BOOKMARK_DESTINATION",
                    f"{path}.destination",
                    "Array destinations must contain exactly 3 finite numbers.",
                )
        elif isinstance(destination, dict):
            local_ok = all(_is_number(destination.get(axis)) for axis in ("x", "y", "z"))
            geo_ok = _is_number(destination.get("longitude")) and _is_number(
                destination.get("latitude")
            )
            if "height" in destination and not _is_number(destination["height"]):
                geo_ok = False
            if not local_ok and not geo_ok:
                issues.error(
                    "INVALID_BOOKMARK_DESTINATION",
                    f"{path}.destination",
                    "Destination needs numeric x/y/z or longitude/latitude (and optional height).",
                )
        else:
            issues.error(
                "MISSING_BOOKMARK_DESTINATION",
                f"{path}.destination",
                "Camera bookmark destination is required.",
            )

        orientation = bookmark.get("orientation")
        if orientation is not None:
            if not isinstance(orientation, dict):
                issues.error(
                    "INVALID_BOOKMARK_ORIENTATION",
                    f"{path}.orientation",
                    "orientation must be an object.",
                )
            else:
                for axis in ("heading", "pitch", "roll"):
                    if axis in orientation and not _is_number(orientation[axis]):
                        issues.error(
                            "INVALID_BOOKMARK_ORIENTATION",
                            f"{path}.orientation.{axis}",
                            f"{axis} must be a finite number.",
                        )
    return len(bookmarks)


def validate_scene_manifest(manifest: object, viewer_info: dict, issues: Issues) -> dict:
    """Validate scene_manifest.json and return a normalised summary."""
    info: dict = {
        "present": False,
        "layerCount": 0,
        "tilesetCount": 0,
        "modelCount": 0,
        "cameraBookmarkCount": 0,
        "layerIds": [],
    }
    if not isinstance(manifest, dict):
        issues.error("INVALID_SCENE_MANIFEST", "scene", "Scene manifest root must be a JSON object.")
        return info
    info["present"] = True

    scene_id = _id_text(manifest.get("sceneId"))
    if scene_id is None:
        issues.error("MISSING_SCENE_ID", "sceneId", "sceneId is required.")
    else:
        info["sceneId"] = scene_id
    mine_id = _id_text(manifest.get("mineId"))
    if mine_id is None:
        issues.error("MISSING_MINE_ID", "mineId", "mineId is required.")
    else:
        info["mineId"] = mine_id

    coordinate_value = manifest.get("coordinateSystemId")
    coordinate_id = _id_text(coordinate_value)
    if coordinate_id is None:
        issues.error(
            "MISSING_COORDINATE_SYSTEM_ID",
            "coordinateSystemId",
            "coordinateSystemId is required in the scene manifest.",
        )
    else:
        info["coordinateSystemId"] = coordinate_id
        viewer_coordinate = viewer_info.get("coordinateSystemId")
        if viewer_coordinate and viewer_coordinate != coordinate_id:
            issues.error(
                "COORDINATE_SYSTEM_MISMATCH",
                "coordinateSystemId",
                f"Scene manifest uses '{coordinate_id}' but viewer config uses "
                f"'{viewer_coordinate}'.",
            )

    axis_value = manifest.get("axisConvention")
    if axis_value is not None:
        if not _is_nonempty_str(axis_value):
            issues.error(
                "INVALID_AXIS_CONVENTION",
                "axisConvention",
                "axisConvention must be a non-empty string when present.",
            )
        else:
            axis = axis_value.strip()
            info["axisConvention"] = axis
            viewer_axis = viewer_info.get("axisConvention")
            if viewer_axis and viewer_axis != axis:
                issues.error(
                    "AXIS_CONVENTION_MISMATCH",
                    "axisConvention",
                    f"Manifest axis '{axis}' differs from viewer axis '{viewer_axis}'.",
                )
            if axis not in KNOWN_AXIS_CONVENTIONS:
                issues.warning(
                    "UNKNOWN_AXIS_CONVENTION",
                    "axisConvention",
                    f"Unrecognised axis convention '{axis}'.",
                )

    terrain = manifest.get("terrain")
    if terrain is None:
        issues.error(
            "MISSING_SCENE_TERRAIN",
            "terrain",
            "Scene manifest terrain entry is required.",
        )
    elif not isinstance(terrain, dict):
        issues.error("INVALID_SCENE_TERRAIN", "terrain", "terrain must be an object.")
    else:
        terrain_type = terrain.get("type")
        terrain_type_text = (
            terrain_type.strip() if _is_nonempty_str(terrain_type) else None
        )
        if terrain_type_text:
            info["terrainType"] = terrain_type_text
            _check_commercial(issues, terrain_type_text, "terrain.type")
        uri, uri_key = _uri_field(terrain)
        if uri is None:
            if terrain_type_text not in NO_TERRAIN_URL_TYPES:
                issues.error(
                    "MISSING_TERRAIN_URI",
                    "terrain.uri",
                    "terrain uri must be present and non-empty.",
                )
        else:
            info["terrainUri"] = uri
            _check_commercial(issues, uri, f"terrain.{uri_key}")

    layer_ids, layer_count = _validate_layers(manifest, issues)
    info["layerIds"] = layer_ids
    info["layerCount"] = layer_count
    layer_id_set = set(layer_ids)

    info["tilesetCount"] = _validate_assets(manifest, "tilesets", "TILESET", layer_id_set, issues)
    info["modelCount"] = _validate_assets(manifest, "models", "MODEL", layer_id_set, issues)
    info["cameraBookmarkCount"] = _validate_camera_bookmarks(manifest, issues)

    if info["tilesetCount"] == 0 and info["modelCount"] == 0:
        issues.warning(
            "NO_SCENE_CONTENT",
            "tilesets",
            "No tilesets or models are declared; the scene will only contain terrain.",
        )
    return info


def validate_scene(
    viewer_config: object,
    scene_manifest: object,
    sources: dict | None = None,
) -> dict:
    """Validate both configuration files and return a machine-readable report."""
    issues = Issues()
    viewer_info = validate_viewer_config(viewer_config, issues)
    scene_info = validate_scene_manifest(scene_manifest, viewer_info, issues)

    errors = issues.errors
    warnings = issues.warnings
    return {
        "status": "FAIL" if errors else "PASS",
        "validator": "mine-cesium-visualization/validate_scene",
        "rulesVersion": "0.1",
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "layers": scene_info.get("layerCount", 0),
            "tilesets": scene_info.get("tilesetCount", 0),
            "models": scene_info.get("modelCount", 0),
            "cameraBookmarks": scene_info.get("cameraBookmarkCount", 0),
        },
        "viewer": viewer_info,
        "scene": scene_info,
        "sources": sources or {},
        "errors": errors,
        "warnings": warnings,
    }


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    viewer = report["viewer"]
    scene = report["scene"]
    lines = [
        "# Cesium Scene Validation Report",
        "",
        f"- **Status**: {report['status']}",
        f"- **Errors**: {summary['errors']}",
        f"- **Warnings**: {summary['warnings']}",
        f"- **Layers**: {summary['layers']}",
        f"- **Tilesets**: {summary['tilesets']}",
        f"- **Models**: {summary['models']}",
        f"- **Camera bookmarks**: {summary['cameraBookmarks']}",
    ]
    if scene.get("sceneId"):
        lines.append(f"- **Scene**: `{scene['sceneId']}`")
    if scene.get("mineId"):
        lines.append(f"- **Mine**: `{scene['mineId']}`")
    if viewer.get("coordinateSystemId"):
        lines.append(f"- **Coordinate system**: `{viewer['coordinateSystemId']}`")
    if viewer.get("axisConvention"):
        lines.append(f"- **Axis convention**: `{viewer['axisConvention']}`")

    lines.extend(["", "## Errors", ""])
    if report["errors"]:
        lines.extend(
            f"- `{entry['code']}` at `{entry['path']}` — {entry['message']}"
            for entry in report["errors"]
        )
    else:
        lines.append("- None")

    lines.extend(["", "## Warnings", ""])
    if report["warnings"]:
        lines.extend(
            f"- `{entry['code']}` at `{entry['path']}` — {entry['message']}"
            for entry in report["warnings"]
        )
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Viewer Settings",
            "",
            f"- Terrain provider: `{viewer.get('terrainProviderType', '-')}`",
            f"- Terrain URL: `{viewer.get('terrainUrl', '-')}`",
            f"- Imagery providers: "
            f"{', '.join(provider.get('type', '-') for provider in viewer.get('imageryProviders', [])) or '-'}",
            f"- Maximum screen-space error: {common.fmt(viewer.get('maximumScreenSpaceError'))}",
            f"- Resolution scale: {common.fmt(viewer.get('resolutionScale'))}",
            f"- Tile cache size: {common.fmt(viewer.get('tileCacheSize'))}",
            f"- Maximum requests: {common.fmt(viewer.get('maximumRequests'))}",
            "",
            "## Scene Layers",
            "",
        ]
    )
    if scene.get("layerIds"):
        lines.extend(f"- `{layer_id}`" for layer_id in scene["layerIds"])
    else:
        lines.append("- None declared")

    sources = report.get("sources") or {}
    if sources:
        lines.extend(["", "## Sources", ""])
        for label, source in sources.items():
            lines.append(
                f"- **{label}**: `{source.get('path', '-')}` "
                f"(SHA-256 `{source.get('sha256', '-')}`)"
            )

    lines.extend(
        [
            "",
            "## Rules Checked",
            "",
            "- Terrain and imagery providers are explicit and not commercial hardcoded services.",
            "- Scene origin, coordinateSystemId and axis convention are present and consistent.",
            "- Layer IDs are unique and layer references resolve.",
            "- Tileset/model URIs are non-empty and transforms contain 16 finite numbers.",
            "- Camera bookmarks have a valid destination and orientation.",
            "- Rendering and performance settings are within a sane range.",
            "",
            "> This report validates configuration only. It does not start a Cesium "
            "Viewer, fetch tilesets or verify visual output.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: dict, output_path: str, markdown_path: str) -> dict[str, str]:
    common.write_json(output_path, report)
    common.write_text(markdown_path, render_markdown(report))
    return {"json": str(Path(output_path)), "markdown": str(Path(markdown_path))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Cesium viewer and scene manifest configuration."
    )
    parser.add_argument("viewer_config", help="Path to viewer_config.json")
    parser.add_argument("scene_manifest", help="Path to scene_manifest.json")
    parser.add_argument(
        "--output",
        default="scene_validation.json",
        help="JSON validation report path (default: scene_validation.json)",
    )
    parser.add_argument(
        "--markdown",
        default="scene_validation.md",
        help="Markdown validation report path (default: scene_validation.md)",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Exit 0 even when validation errors are found.",
    )
    args = parser.parse_args(argv)

    viewer_config = common.load_json(args.viewer_config)
    scene_manifest = common.load_json(args.scene_manifest)
    sources = {
        "viewerConfig": common.source_manifest(args.viewer_config),
        "sceneManifest": common.source_manifest(args.scene_manifest),
    }
    report = validate_scene(viewer_config, scene_manifest, sources=sources)
    paths = write_outputs(report, args.output, args.markdown)

    summary = report["summary"]
    print(
        f"Scene validation: {report['status']} — {summary['errors']} error(s), "
        f"{summary['warnings']} warning(s), {summary['layers']} layer(s), "
        f"{summary['tilesets']} tileset(s), {summary['models']} model(s)."
    )
    for entry in report["errors"][:10]:
        print(f"  ERROR {entry['code']}: {entry['path']} — {entry['message']}")
    print("Outputs: " + ", ".join(paths.values()))

    if report["errors"] and not args.no_fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
