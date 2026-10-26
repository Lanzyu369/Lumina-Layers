"""Native ChromaPrint3D source helpers.

Detect and consume reference-repo assets directly:
- ColorDB JSON
- Stage A / Stage B parameter JSON
- Representative recipe JSON
- ModelPackage v2 msgpack
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import os
import sys
import json

import msgpack
import numpy as np
import cv2

from config import get_asset_path

REFERENCE_REPO_ROOT = Path("reference/ChromaPrint3D").resolve()
REFERENCE_DATA_ROOT = REFERENCE_REPO_ROOT / "data"
_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1
REFERENCE_DB_ROOT = REFERENCE_DATA_ROOT / "dbs"
REFERENCE_MODEL_PACK_ROOT = REFERENCE_DATA_ROOT / "model_packs"
REFERENCE_FORWARD_MODEL_ROOT = REFERENCE_DATA_ROOT / "models" / "forward"
_BUNDLED_REFERENCE_REPO_RELATIVE = os.path.join("native_sources", "ChromaPrint3D")

SOURCE_KIND_LEGACY = "legacy_lookup"
SOURCE_KIND_COLORD_DB = "colordb_backed"
SOURCE_KIND_STAGE_MODEL = "predictive_stage_model"
SOURCE_KIND_PACKAGE = "predictive_package"


@dataclass(frozen=True)
class NativeReferenceContext:
    """Discovered native reference assets associated with one selected source."""

    source_kind: str
    primary_path: str
    package_path: str | None = None
    stage_model_path: str | None = None
    recipe_path: str | None = None
    db_paths: tuple[str, ...] = ()
    supported_modes: tuple[dict[str, Any], ...] = ()
    channel_keys: tuple[str, ...] = ()
    vendor: str | None = None
    material_type: str | None = None


def _resolve_bundled_reference_repo_root() -> Path | None:
    try:
        return Path(get_asset_path(os.path.join(_BUNDLED_REFERENCE_REPO_RELATIVE, "data"))).resolve().parent
    except FileNotFoundError:
        candidate = Path("assets", _BUNDLED_REFERENCE_REPO_RELATIVE).resolve()
        if candidate.joinpath("data").exists():
            return candidate
    return None


def iter_reference_repo_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = [REFERENCE_REPO_ROOT]
    bundled_root = _resolve_bundled_reference_repo_root()
    if bundled_root is not None and bundled_root not in candidates:
        candidates.append(bundled_root)
    return tuple(candidates)


def get_reference_repo_root() -> Path:
    for candidate in iter_reference_repo_candidates():
        if candidate.joinpath("data").exists():
            return candidate.resolve()
    return REFERENCE_REPO_ROOT


def get_reference_data_root() -> Path:
    return get_reference_repo_root() / "data"


def get_reference_db_root() -> Path:
    return get_reference_data_root() / "dbs"


def get_reference_model_pack_root() -> Path:
    return get_reference_data_root() / "model_packs"


def get_reference_forward_model_root() -> Path:
    return get_reference_data_root() / "models" / "forward"


def ensure_reference_repo_importable() -> None:
    """Add the local reference repo root to ``sys.path`` if needed."""
    reference_repo_root = get_reference_repo_root()
    ref_root = str(reference_repo_root)
    if ref_root not in sys.path and reference_repo_root.exists():
        sys.path.insert(0, ref_root)


def build_channel_key(color: str, material: str) -> str:
    return f"{str(color).strip()}|{str(material).strip()}"


def split_channel_key(key: str) -> tuple[str, str]:
    if "|" not in key:
        return key, "PLA Basic"
    color, material = key.split("|", 1)
    return color, material


def _normalize_channel_token(value: str) -> str:
    return "".join(str(value).strip().lower().split())


def normalize_channel_key(key: str) -> str:
    color, material = split_channel_key(str(key))
    return f"{_normalize_channel_token(color)}|{_normalize_channel_token(material)}"


def _normalize_channel_keys(keys: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for key in keys:
        normalized_key = normalize_channel_key(str(key))
        if not normalized_key or normalized_key in seen:
            continue
        seen.add(normalized_key)
        normalized.append(normalized_key)
    return tuple(normalized)


def supported_mode_dict(
    color_layers: int,
    layer_height_mm: float,
    *,
    layer_order: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "color_layers": int(color_layers),
        "layer_height_mm": float(layer_height_mm),
        "mode_key": f"{float(layer_height_mm):.2f}x{int(color_layers)}",
    }
    if layer_order:
        payload["layer_order"] = str(layer_order)
    return payload


def derive_color_mode_from_palette_size(size: int, fallback: str = "Merged") -> str:
    if size <= 0:
        return fallback
    if size == 2:
        return "BW (Black & White)"
    if size == 4:
        return "4-Color (RYBW)"
    if size == 5:
        return "5-Color Extended"
    if size == 6:
        return "6-Color (CMYWGK 1296)"
    if size >= 8:
        return "8-Color Max"
    return fallback


def derive_color_mode_from_palette_entries(entries: Iterable[Any], fallback: str = "Merged") -> str:
    """Infer color mode from palette/channel contents, falling back to size-based inference."""
    normalized_colors: set[str] = set()
    entry_count = 0
    for entry in entries:
        entry_count += 1
        if isinstance(entry, str):
            color_name = split_channel_key(entry)[0]
        elif isinstance(entry, dict):
            color_name = str(entry.get("color") or entry.get("color_name") or "")
        else:
            color_name = str(getattr(entry, "color", "") or getattr(entry, "color_name", "") or "")
        token = _normalize_channel_token(color_name)
        if token:
            normalized_colors.add(token)

    if entry_count == 2:
        return "BW (Black & White)"

    if entry_count == 4:
        if {"cyan", "magenta"} & normalized_colors:
            return "4-Color (CMYW)"
        if {"red", "blue"} & normalized_colors:
            return "4-Color (RYBW)"

    if entry_count == 5:
        return "5-Color Extended"

    if entry_count == 6:
        if {"cyan", "magenta"} & normalized_colors:
            return "6-Color (CMYWGK 1296)"
        if {"red", "blue"} & normalized_colors:
            return "6-Color (RYBWGK 1296)"

    if entry_count >= 8:
        return "8-Color Max"

    return derive_color_mode_from_palette_size(entry_count, fallback)


def opencv_lab_to_rgb_uint8(lab_array: np.ndarray) -> np.ndarray:
    """Convert OpenCV Lab values to RGB uint8 for either float or uint8 encodings.
    将 OpenCV Lab 数值转换为 RGB uint8，兼容 float 空间与旧版 uint8 编码。
    """
    if lab_array.size == 0:
        return np.zeros((0, 3), dtype=np.uint8)

    lab = np.asarray(lab_array, dtype=np.float32).reshape(-1, 3)
    encoding = detect_opencv_lab_encoding(lab)
    if encoding == "float":
        lab_for_cv = lab.reshape(1, -1, 3).astype(np.float32, copy=False)
    else:
        lab_for_cv = np.clip(np.rint(lab), 0, 255).astype(np.uint8).reshape(1, -1, 3)

    bgr = cv2.cvtColor(lab_for_cv, cv2.COLOR_Lab2BGR)
    if bgr.dtype != np.uint8:
        bgr = np.clip(np.rint(bgr * 255.0), 0, 255).astype(np.uint8)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).reshape(-1, 3).astype(np.uint8)


def rgb_to_opencv_lab_float_space(rgb_array: np.ndarray) -> np.ndarray:
    """Convert RGB uint8 colors to float-space OpenCV Lab used by native runtimes.
    将 RGB uint8 颜色转换为原生运行时使用的 float 空间 OpenCV Lab。
    """
    if np.asarray(rgb_array).size == 0:
        return np.zeros((0, 3), dtype=np.float32)
    rgb = np.asarray(rgb_array, dtype=np.uint8).reshape(1, -1, 3)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR).astype(np.float32) / 255.0
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).reshape(-1, 3).astype(np.float32)


def detect_opencv_lab_encoding(lab_array: np.ndarray) -> str:
    """Infer whether an OpenCV Lab payload uses float-space or uint8-style encoding.
    推断 OpenCV Lab 载荷使用 float 空间还是旧版 uint8 风格编码。
    """
    if lab_array.size == 0:
        return "uint8"

    lab = np.asarray(lab_array, dtype=np.float32).reshape(-1, 3)
    l_channel = lab[:, 0]
    ab_channels = lab[:, 1:]

    if np.any(l_channel < -1e-3) or np.any(ab_channels < -1e-3):
        return "float"
    if np.any(l_channel > 100.5) or np.any(ab_channels > 127.5):
        return "uint8"

    if np.any(np.abs(lab - np.rint(lab)) > 1e-3):
        return "float"

    rgb_from_float = opencv_lab_to_rgb_uint8_float_space(lab)
    rgb_from_uint8 = opencv_lab_to_rgb_uint8_legacy(lab)
    float_score = np.mean((rgb_to_opencv_lab_float_space(rgb_from_float) - lab) ** 2)
    uint8_score = np.mean((rgb_to_opencv_lab_uint8_space(rgb_from_uint8) - lab) ** 2)
    return "float" if float_score <= uint8_score else "uint8"


def opencv_lab_to_rgb_uint8_float_space(lab_array: np.ndarray) -> np.ndarray:
    lab = np.asarray(lab_array, dtype=np.float32).reshape(1, -1, 3)
    bgr = cv2.cvtColor(lab, cv2.COLOR_Lab2BGR)
    return np.clip(np.rint(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).reshape(-1, 3) * 255.0), 0, 255).astype(np.uint8)


def opencv_lab_to_rgb_uint8_legacy(lab_array: np.ndarray) -> np.ndarray:
    lab_uint8 = np.clip(np.rint(lab_array), 0, 255).astype(np.uint8).reshape(1, -1, 3)
    bgr = cv2.cvtColor(lab_uint8, cv2.COLOR_Lab2BGR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).reshape(-1, 3).astype(np.uint8)


def rgb_to_opencv_lab_uint8_space(rgb_array: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb_array, dtype=np.uint8).reshape(1, -1, 3)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).reshape(-1, 3).astype(np.float32)


def standard_lab_to_rgb_uint8(lab_array: np.ndarray) -> np.ndarray:
    """Convert standard L/a/b values to RGB uint8 through OpenCV Lab."""
    if lab_array.size == 0:
        return np.zeros((0, 3), dtype=np.uint8)
    lab = np.asarray(lab_array, dtype=np.float32).copy()
    lab[:, 0] = np.clip(lab[:, 0] * 255.0 / 100.0, 0, 255)
    lab[:, 1] = np.clip(lab[:, 1] + 128.0, 0, 255)
    lab[:, 2] = np.clip(lab[:, 2] + 128.0, 0, 255)
    return opencv_lab_to_rgb_uint8(lab)


def looks_like_reference_colordb(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    entries = data.get("entries")
    palette = data.get("palette")
    return isinstance(entries, list) and isinstance(palette, list) and any(
        isinstance(entry, dict)
        and isinstance(entry.get("recipe"), list)
        and all(not isinstance(v, str) for v in entry.get("recipe", []))
        for entry in entries
    )


def looks_like_reference_stage_model(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    params = data.get("parameters", {})
    channels = params.get("channels") if isinstance(params, dict) else None
    return isinstance(channels, list) and bool(channels)


def looks_like_reference_recipe_set(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    recipes = data.get("recipes")
    pred_lab = data.get("predicted_lab_opencv")
    return isinstance(recipes, list) and isinstance(pred_lab, list) and bool(recipes)


def looks_like_model_package(path: str) -> bool:
    return Path(path).suffix.lower() == ".msgpack"


def _parse_model_package_payload(payload: Any, path: str) -> NativeReferenceContext:
    if not isinstance(payload, dict):
        raise ValueError("Invalid model package payload")
    modes_raw = payload.get("modes", [])
    supported_modes: list[dict[str, Any]] = []
    if isinstance(modes_raw, list):
        for item in modes_raw:
            if not isinstance(item, dict):
                continue
            try:
                supported_modes.append(
                    supported_mode_dict(
                        int(item.get("color_layers", 0)),
                        float(item.get("layer_height_mm", 0.0)),
                        layer_order=str(item.get("layer_order", "Top2Bottom")),
                    )
                )
            except (TypeError, ValueError):
                continue
    scope = payload.get("scope", {}) if isinstance(payload.get("scope"), dict) else {}
    channel_keys = tuple(str(item) for item in payload.get("channel_keys", []) if str(item))
    vendor = (str(scope.get("vendor")) if scope.get("vendor") is not None else None)
    material_type = (str(scope.get("material_type")) if scope.get("material_type") is not None else None)
    stage_model_path = _global_stage_model_for(vendor, material_type)
    if stage_model_path and not _is_compatible_stage_model(stage_model_path, channel_keys):
        stage_model_path = None
    explicit_db_paths = payload.get("selected_db_paths")
    if isinstance(explicit_db_paths, list) and explicit_db_paths:
        db_paths = tuple(
            str(Path(item).resolve())
            for item in explicit_db_paths
            if str(item)
        )
    else:
        db_paths = tuple(
            _filter_compatible_paths(
                _global_dbs_for(vendor, material_type),
                channel_keys,
                _is_compatible_colordb,
            )
        )
    return NativeReferenceContext(
        source_kind=SOURCE_KIND_PACKAGE,
        primary_path=path,
        package_path=path,
        stage_model_path=stage_model_path,
        db_paths=db_paths,
        supported_modes=tuple(supported_modes),
        channel_keys=channel_keys,
        vendor=vendor,
        material_type=material_type,
    )


def parse_model_package_file(path: str) -> NativeReferenceContext:
    payload = msgpack.unpackb(Path(path).read_bytes(), raw=False)
    return _parse_model_package_payload(payload, path)


def _find_nearby_json(path: str, predicate) -> list[str]:
    file_path = Path(path)
    search_roots: list[Path] = []
    if file_path.is_dir():
        search_roots.append(file_path)
    else:
        search_roots.append(file_path.parent)
        if file_path.parent.parent != file_path.parent:
            search_roots.append(file_path.parent.parent)

    results: list[str] = []
    seen: set[str] = set()
    for root in search_roots:
        if not root.exists():
            continue
        for candidate in root.glob("*.json"):
            if str(candidate.resolve()) in seen:
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            if predicate(data):
                resolved = str(candidate.resolve())
                seen.add(resolved)
                results.append(resolved)
    return sorted(results)


def _find_nearby_msgpack(path: str) -> list[str]:
    file_path = Path(path)
    search_roots = [file_path.parent]
    if file_path.parent.parent != file_path.parent:
        search_roots.append(file_path.parent.parent)
    results: list[str] = []
    seen: set[str] = set()
    for root in search_roots:
        if not root.exists():
            continue
        for candidate in root.glob("*.msgpack"):
            resolved = str(candidate.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            results.append(resolved)
    return sorted(results)


def _infer_vendor_material_from_db_path(path: str) -> tuple[str | None, str | None]:
    file_path = Path(path).resolve()
    try:
        rel_parts = file_path.relative_to(get_reference_db_root()).parts
    except ValueError:
        return None, None
    if len(rel_parts) >= 3:
        return rel_parts[1], rel_parts[0]
    return None, None


def _infer_vendor_material_from_stage_path(path: str) -> tuple[str | None, str | None]:
    file_path = Path(path).resolve()
    stem = file_path.stem.lower()
    if stem.endswith("_stage_b"):
        stem = stem[:-8]
    parts = stem.split("_")
    if len(parts) >= 2:
        return parts[0].replace("bambulab", "BambuLab"), parts[1].upper()
    return None, None


def _global_stage_model_for(vendor: str | None, material_type: str | None) -> str | None:
    if not vendor or not material_type:
        return None
    vendor_token = vendor.lower().replace(" ", "")
    material_token = material_type.lower()
    candidate = get_reference_forward_model_root() / f"{vendor_token}_{material_token}_stage_B.json"
    if candidate.exists():
        return str(candidate.resolve())
    return None


def _global_model_pack_for(vendor: str | None, material_type: str | None) -> str | None:
    if not vendor or not material_type:
        return None
    vendor_token = vendor.lower().replace(" ", "")
    material_token = material_type.lower()
    candidate = get_reference_model_pack_root() / f"{vendor_token}_{material_token}.msgpack"
    if candidate.exists():
        return str(candidate.resolve())
    return None


def _global_dbs_for(vendor: str | None, material_type: str | None) -> tuple[str, ...]:
    if not material_type:
        return ()
    material_root = get_reference_db_root() / material_type
    if vendor:
        vendor_root = material_root / vendor
        if vendor_root.exists():
            return tuple(str(path.resolve()) for path in sorted(vendor_root.glob("*.json")))
    if material_root.exists():
        return tuple(str(path.resolve()) for path in sorted(material_root.rglob("*.json")))
    return ()


def _channel_key_sets_match(expected_keys: Iterable[str], candidate_keys: Iterable[str]) -> bool:
    expected = _normalize_channel_keys(expected_keys)
    candidate = _normalize_channel_keys(candidate_keys)
    return bool(expected) and len(expected) == len(candidate) and set(expected) == set(candidate)


def _channel_key_set_contains(expected_keys: Iterable[str], candidate_keys: Iterable[str]) -> bool:
    expected = set(_normalize_channel_keys(expected_keys))
    candidate = set(_normalize_channel_keys(candidate_keys))
    return bool(expected) and bool(candidate) and candidate.issubset(expected)


def _extract_stage_model_channel_keys(data: Any) -> tuple[str, ...]:
    if not isinstance(data, dict):
        return ()

    explicit_keys = data.get("channel_keys")
    if isinstance(explicit_keys, list):
        return tuple(str(item) for item in explicit_keys if str(item))

    params = data.get("parameters", {})
    channels = params.get("channels") if isinstance(params, dict) else None
    if not isinstance(channels, list):
        return ()

    inferred_keys: list[str] = []
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        color_name = str(channel.get("color_name", "")).strip()
        material_name = str(channel.get("material", "PLA Basic")).strip() or "PLA Basic"
        if color_name:
            inferred_keys.append(build_channel_key(color_name, material_name))
    return tuple(inferred_keys)


def _extract_colordb_channel_keys(data: Any) -> tuple[str, ...]:
    if not isinstance(data, dict):
        return ()

    palette = data.get("palette")
    if not isinstance(palette, list):
        return ()

    channel_keys: list[str] = []
    for item in palette:
        if not isinstance(item, dict):
            continue
        color_name = str(item.get("color", "")).strip()
        material_name = str(item.get("material", "PLA Basic")).strip() or "PLA Basic"
        if color_name:
            channel_keys.append(build_channel_key(color_name, material_name))
    return tuple(channel_keys)


def _is_compatible_model_package(path: str, expected_channel_keys: Iterable[str]) -> bool:
    try:
        package_ctx = parse_model_package_file(path)
    except Exception:
        return False
    return _channel_key_sets_match(expected_channel_keys, package_ctx.channel_keys)


def _is_compatible_stage_model(path: str, expected_channel_keys: Iterable[str]) -> bool:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return False
    return _channel_key_sets_match(expected_channel_keys, _extract_stage_model_channel_keys(data))


def _is_compatible_colordb(path: str, expected_channel_keys: Iterable[str]) -> bool:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return False
    return _channel_key_set_contains(expected_channel_keys, _extract_colordb_channel_keys(data))


def _filter_compatible_paths(
    paths: Iterable[str],
    expected_channel_keys: Iterable[str],
    compatibility_check,
) -> list[str]:
    compatible: list[str] = []
    for path in paths:
        if compatibility_check(path, expected_channel_keys):
            compatible.append(path)
    return compatible


def select_native_db_paths_for_mode(
    db_paths: Iterable[str],
    *,
    color_layers: int,
    layer_height_mm: float,
    expected_channel_keys: Iterable[str] | None = None,
    layer_order: str | None = None,
) -> tuple[str, ...]:
    """Return compatible ColorDBs that exactly match one requested layer mode."""
    matched_paths: list[str] = []
    expected_keys = tuple(expected_channel_keys or ())
    target_layers = int(color_layers)
    target_height = float(layer_height_mm)
    target_order = str(layer_order) if layer_order else None

    for path in db_paths:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue
        if not looks_like_reference_colordb(data):
            continue
        if expected_keys and not _channel_key_set_contains(expected_keys, _extract_colordb_channel_keys(data)):
            continue

        db_layers = int(
            data.get(
                "max_color_layers",
                len(data.get("entries", [])[0].get("recipe", [])) if data.get("entries") else 0,
            )
        )
        db_height = float(data.get("layer_height_mm", 0.08))
        db_order = str(data.get("layer_order", "Top2Bottom"))
        if db_layers != target_layers:
            continue
        if abs(db_height - target_height) > 1e-3:
            continue
        if target_order and db_order != target_order:
            continue
        matched_paths.append(str(Path(path).resolve()))

    return tuple(sorted(dict.fromkeys(matched_paths)))


def discover_native_reference_context(path: str, data: Any | None = None) -> NativeReferenceContext | None:
    """Discover direct/native reference assets associated with ``path``."""
    resolved_path = str(Path(path).resolve())
    if looks_like_model_package(resolved_path):
        return parse_model_package_file(resolved_path)

    if data is None and Path(resolved_path).suffix.lower() == ".json":
        try:
            data = json.loads(Path(resolved_path).read_text(encoding="utf-8"))
        except Exception:
            return None

    if looks_like_reference_recipe_set(data):
        meta = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
        palette = data.get("palette", []) if isinstance(data.get("palette"), list) else []
        channel_keys = tuple(
            build_channel_key(str(item.get("color", "")), str(item.get("material", "PLA Basic")))
            for item in palette
            if isinstance(item, dict)
        )
        return NativeReferenceContext(
            source_kind=SOURCE_KIND_PACKAGE,
            primary_path=resolved_path,
            recipe_path=resolved_path,
            supported_modes=(
                supported_mode_dict(
                    _recipe_color_layers(data.get("recipes", []), meta),
                    float(meta.get("layer_height_mm", 0.08)),
                    layer_order=str(meta.get("layer_order", "Top2Bottom")),
                ),
            ),
            channel_keys=channel_keys,
        )

    if looks_like_reference_colordb(data):
        vendor, material_type = _infer_vendor_material_from_db_path(resolved_path)
        palette = data.get("palette", [])
        channel_keys = tuple(
            build_channel_key(str(item.get("color", "")), str(item.get("material", "PLA Basic")))
            for item in palette
            if isinstance(item, dict)
        )
        db_modes = (
            supported_mode_dict(
                int(data.get("max_color_layers", len(data.get("entries", [])[0].get("recipe", [])) if data.get("entries") else 0)),
                float(data.get("layer_height_mm", 0.08)),
                layer_order=str(data.get("layer_order", "Top2Bottom")),
            ),
        )
        return NativeReferenceContext(
            source_kind=SOURCE_KIND_COLORD_DB,
            primary_path=resolved_path,
            package_path=None,
            stage_model_path=None,
            db_paths=(resolved_path,),
            supported_modes=db_modes,
            channel_keys=channel_keys,
            vendor=vendor,
            material_type=material_type,
        )

    if looks_like_reference_stage_model(data):
        vendor, material_type = _infer_vendor_material_from_stage_path(resolved_path)
        channel_keys = _extract_stage_model_channel_keys(data)
        selected_db_paths = data.get("selected_db_paths") if isinstance(data, dict) else None
        if isinstance(selected_db_paths, list) and selected_db_paths:
            db_paths = [str(Path(item).resolve()) for item in selected_db_paths if str(item)]
            packages = []
        else:
            packages = _find_nearby_msgpack(resolved_path)
            db_paths = _find_nearby_json(resolved_path, looks_like_reference_colordb)
        global_package = _global_model_pack_for(vendor, material_type)
        if global_package and global_package not in packages:
            packages.insert(0, global_package)
        if not selected_db_paths:
            global_dbs = _global_dbs_for(vendor, material_type)
            if global_dbs:
                db_paths = list(dict.fromkeys([*global_dbs, *db_paths]))
        packages = _filter_compatible_paths(packages, channel_keys, _is_compatible_model_package)
        db_paths = _filter_compatible_paths(db_paths, channel_keys, _is_compatible_colordb)
        supported_modes: list[dict[str, Any]] = []
        if packages:
            supported_modes = list(parse_model_package_file(packages[0]).supported_modes)
        return NativeReferenceContext(
            source_kind=SOURCE_KIND_STAGE_MODEL,
            primary_path=resolved_path,
            package_path=(packages[0] if packages else None),
            stage_model_path=resolved_path,
            db_paths=tuple(db_paths),
            supported_modes=tuple(supported_modes),
            channel_keys=channel_keys,
            vendor=vendor,
            material_type=material_type,
        )
    return None


def _parse_reference_recipe_integer(value: Any) -> int | None:
    if isinstance(value, (bool, np.bool_)):
        return None
    if isinstance(value, str):
        stripped_value = value.strip()
        digits = stripped_value[1:] if stripped_value[:1] in ("+", "-") else stripped_value
        if not digits or not digits.isdigit():
            return None
        try:
            integer_value = int(stripped_value)
        except ValueError:
            return None
        if _INT32_MIN <= integer_value <= _INT32_MAX:
            return integer_value
        return None
    if isinstance(value, (int, np.integer)):
        integer_value = int(value)
        if _INT32_MIN <= integer_value <= _INT32_MAX:
            return integer_value
    return None


def _recipe_color_layers(raw_recipes: Any, meta: dict[str, Any]) -> int:
    try:
        color_layers = int(meta.get("color_layers", 0))
    except (TypeError, ValueError):
        color_layers = 0
    if color_layers > 0:
        return color_layers
    valid_row_length_counts: dict[int, int] = {}
    structural_row_lengths: list[int] = []
    if isinstance(raw_recipes, list):
        for row in raw_recipes:
            if not isinstance(row, (list, tuple)) or not row:
                continue
            structural_row_lengths.append(len(row))
            parsed_row = [_parse_reference_recipe_integer(value) for value in row]
            if any(value is None for value in parsed_row):
                continue
            valid_row_length_counts[len(row)] = valid_row_length_counts.get(len(row), 0) + 1
    if 5 in structural_row_lengths:
        return 5
    if valid_row_length_counts:
        max_count = max(valid_row_length_counts.values())
        candidates = [
            length for length, count in valid_row_length_counts.items()
            if count == max_count
        ]
        return max(candidates)
    if structural_row_lengths:
        return max(structural_row_lengths)
    if isinstance(raw_recipes, list) and raw_recipes:
        return 5
    return 0


def _normalize_reference_recipe_rows(raw_recipes: Any, color_layers: int) -> np.ndarray:
    if color_layers <= 0 or not isinstance(raw_recipes, list):
        raise ValueError("Invalid reference recipe payload")
    invalid_row = [-1] * color_layers
    normalized_rows: list[list[int]] = []
    for row in raw_recipes:
        if not isinstance(row, (list, tuple)) or len(row) != color_layers:
            normalized_rows.append(list(invalid_row))
            continue
        parsed_row = [_parse_reference_recipe_integer(value) for value in row]
        if any(value is None for value in parsed_row):
            normalized_rows.append(list(invalid_row))
        else:
            normalized_rows.append([int(value) for value in parsed_row])
    if not normalized_rows:
        raise ValueError("Invalid reference recipe payload")
    return np.asarray(normalized_rows, dtype=np.int32)


def build_recipe_runtime_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Convert a reference recipe JSON to a Lumina-style runtime package payload."""
    meta = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
    raw_recipes = data.get("recipes", [])
    color_layers = _recipe_color_layers(raw_recipes, meta)
    recipes = _normalize_reference_recipe_rows(raw_recipes, color_layers)
    pred_lab = np.asarray(data.get("predicted_lab_opencv", []), dtype=np.float32)
    if recipes.ndim != 2 or pred_lab.ndim != 2 or pred_lab.shape != (recipes.shape[0], 3):
        raise ValueError("Invalid reference recipe payload")
    mode = supported_mode_dict(
        recipes.shape[1],
        float(meta.get("layer_height_mm", 0.08)),
        layer_order=str(meta.get("layer_order", "Top2Bottom")),
    )
    return {
        "defaults": {"threshold": 5.0, "margin": 0.7},
        "modes": {
            mode["mode_key"]: {
                "layer_height_mm": mode["layer_height_mm"],
                "color_layers": mode["color_layers"],
                "layer_order": mode.get("layer_order", "Top2Bottom"),
                "candidate_recipes": recipes.tolist(),
                "pred_lab": pred_lab.tolist(),
                "threshold": 5.0,
                "margin": 0.7,
            }
        },
    }


def build_model_package_runtime_payload(path: str, payload: Any | None = None) -> dict[str, Any]:
    """Convert a native reference ModelPackage v2 msgpack into Lumina runtime_package shape."""
    if payload is None:
        payload = msgpack.unpackb(Path(path).read_bytes(), raw=False)
    if not isinstance(payload, dict):
        raise ValueError("Invalid model package payload")
    modes_raw = payload.get("modes", [])
    if not isinstance(modes_raw, list) or not modes_raw:
        raise ValueError("Model package contains no modes")

    defaults = payload.get("defaults", {}) if isinstance(payload.get("defaults"), dict) else {}
    runtime_modes: dict[str, Any] = {}
    for item in modes_raw:
        if not isinstance(item, dict):
            continue
        try:
            color_layers = int(item.get("color_layers", 0))
            layer_height_mm = float(item.get("layer_height_mm", 0.0))
            layer_order = str(item.get("layer_order", "Top2Bottom"))
            num_candidates = int(item.get("num_candidates", 0))
        except (TypeError, ValueError):
            continue
        if color_layers <= 0 or layer_height_mm <= 0 or num_candidates <= 0:
            continue

        try:
            candidate_recipes = np.frombuffer(item.get("candidate_recipes", b""), dtype=np.uint8)
            pred_lab = np.frombuffer(item.get("pred_lab", b""), dtype="<f4")
        except (TypeError, ValueError):
            continue
        if candidate_recipes.size != num_candidates * color_layers:
            continue
        if pred_lab.size != num_candidates * 3:
            continue

        candidate_recipes = candidate_recipes.reshape(num_candidates, color_layers).astype(np.int32)
        pred_lab = pred_lab.reshape(num_candidates, 3).astype(np.float32)
        mode = supported_mode_dict(color_layers, layer_height_mm, layer_order=layer_order)
        try:
            threshold = float(item.get("threshold", defaults.get("threshold", 5.0)))
        except (TypeError, ValueError):
            threshold = float(defaults.get("threshold", 5.0))
        try:
            margin = float(item.get("margin", defaults.get("margin", 0.7)))
        except (TypeError, ValueError):
            margin = float(defaults.get("margin", 0.7))
        runtime_modes[mode["mode_key"]] = {
            "layer_height_mm": mode["layer_height_mm"],
            "color_layers": mode["color_layers"],
            "layer_order": mode.get("layer_order", "Top2Bottom"),
            "candidate_recipes": candidate_recipes.tolist(),
            "pred_lab": pred_lab.tolist(),
            "threshold": threshold,
            "margin": margin,
        }

    if not runtime_modes:
        raise ValueError("Model package contains no usable runtime modes")

    return {
        "defaults": {
            "threshold": float(defaults.get("threshold", 5.0)),
            "margin": float(defaults.get("margin", 0.7)),
        },
        "modes": runtime_modes,
    }


def synthesize_rgb_and_stacks_from_model_package(path: str) -> tuple[np.ndarray, np.ndarray]:
    payload = msgpack.unpackb(Path(path).read_bytes(), raw=False)
    rgb, stacks, _mode = synthesize_rgb_and_stacks_from_model_package_payload(path, payload)
    return rgb, stacks


def synthesize_rgb_and_stacks_from_model_package_payload(
    path: str,
    payload: Any,
    preferred_mode: dict[str, Any] | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any] | None]:
    _parse_model_package_payload(payload, path)
    modes = payload.get("modes", [])
    if not isinstance(modes, list) or not modes:
        return np.zeros((0, 3), dtype=np.uint8), np.zeros((0, 0), dtype=np.int32), None
    ordered_modes = [mode for mode in modes if isinstance(mode, dict)]
    if preferred_mode is not None:
        def _matches_preferred(mode: dict[str, Any]) -> bool:
            try:
                return (
                    int(mode.get("color_layers", 0)) == int(preferred_mode.get("color_layers", 0))
                    and float(mode.get("layer_height_mm", 0.0)) == float(preferred_mode.get("layer_height_mm", 0.0))
                    and str(mode.get("layer_order", "Top2Bottom")) == str(preferred_mode.get("layer_order", "Top2Bottom"))
                )
            except (TypeError, ValueError):
                return False

        ordered_modes = [
            *(mode for mode in ordered_modes if _matches_preferred(mode)),
            *(mode for mode in ordered_modes if not _matches_preferred(mode)),
        ]
    for mode in ordered_modes:
        try:
            recipes = np.frombuffer(mode.get("candidate_recipes", b""), dtype=np.uint8)
            color_layers = int(mode.get("color_layers", 0))
            num_candidates = int(mode.get("num_candidates", 0))
            pred_lab = np.frombuffer(mode.get("pred_lab", b""), dtype="<f4")
        except (TypeError, ValueError):
            continue
        if num_candidates <= 0 or color_layers <= 0:
            continue
        if recipes.size != num_candidates * color_layers:
            continue
        if pred_lab.size != num_candidates * 3:
            continue
        recipes = recipes.reshape(num_candidates, color_layers).astype(np.int32)
        pred_lab = pred_lab.reshape(num_candidates, 3)
        rgb = opencv_lab_to_rgb_uint8(pred_lab)
        return rgb, recipes, mode
    return np.zeros((0, 3), dtype=np.uint8), np.zeros((0, 0), dtype=np.int32), None
