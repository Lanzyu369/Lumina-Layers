"""Portable encoding of the existing authoritative editor checkpoint.

将现有权威编辑快照编码为可携带的项目素材，不携带会话路径或可执行对象。
"""

from __future__ import annotations

from copy import deepcopy
import gzip
import hashlib
from io import BytesIO
import json
from typing import Any
import zlib

import numpy as np

from api.preview_cache_artifacts import hydrate_preview_cache_for_worker
from api.replacement_history import (
    REPLACEMENT_CACHE_METADATA_FIELDS, REPLACEMENT_SESSION_FIELDS,
    snapshot_replacement_state,
)
from api.selection_state import pack_applied_region_mask, resolve_recipe_override_masks
from api.session_value_codec import decode_session_value, encode_session_value
from core.material_lut_synthesis import infer_material_archive_base_channel_idx

EDITOR_PROJECT_MAX_BYTES = 512 * 1024 * 1024
_ARRAY_FIELDS = frozenset({
    "matched_rgb", "material_matrix", "mask_solid", "quantized_image",
    "height_identity_rgb", "original_matched_rgb", "original_material_matrix",
    "original_quantized_image",
})
_METADATA_FIELDS = REPLACEMENT_CACHE_METADATA_FIELDS


def _cache(session: dict[str, Any]) -> dict[str, Any]:
    cache = session.get("preview_cache")
    if not isinstance(cache, dict):
        raise ValueError("Preview data is unavailable; run preview before saving project edits")
    return hydrate_preview_cache_for_worker(cache, mmap=False)


def _source_sha256(session: dict[str, Any]) -> str:
    # image_path is the working upload: crops and rotations replace its content.
    # Only the digest travels with the checkpoint, never a filename/session path.
    source_path = session.get("image_path")
    if source_path:
        try:
            with open(source_path, "rb") as source:
                return hashlib.file_digest(source, "sha256").hexdigest()
        except OSError as exc:
            raise ValueError("Project edit source image is unavailable; run preview again") from exc
    raise ValueError("Project edit source image is unavailable; run preview again")


def _binding(session: dict[str, Any], cache: dict[str, Any]) -> dict[str, Any]:
    metadata = cache.get("lut_metadata")
    metadata = metadata.to_dict() if hasattr(metadata, "to_dict") else metadata or {}
    selected_materials = session.get("selected_materials") or []
    if session.get("material_source") == "material_archive":
        # Recipe editing adds LUTMetadata to material caches. Bind both the
        # fresh preview and edited checkpoint to the original material channels.
        slot_names = list(cache.get("slot_names") or selected_materials)[:len(selected_materials)]
        base_index = session.get("material_backing_material_index")
        if base_index is None:
            base_index = infer_material_archive_base_channel_idx(
                selected_materials, slot_names, cache.get("preview_colors") or {},
            )
        metadata = {
            "palette": {
                str(slot): {"material": str(material)}
                for slot, material in zip(slot_names, selected_materials, strict=True)
            },
            "base_channel_idx": int(base_index),
            "layer_order": "Top2Bottom",
        }
    return {
        "source_sha256": _source_sha256(session),
        "width": cache.get("target_w"),
        "height": cache.get("target_h"),
        "target_width_mm": cache.get("target_width_mm"),
        "pixel_scale": cache.get("pixel_scale"),
        "modeling_mode": cache.get("modeling_mode", session.get("modeling_mode")),
        "material_source": session.get("material_source", "lut"),
        "selected_materials": selected_materials,
        "lut_source_kind": session.get("lut_source_kind", "legacy_single"),
        "palette": metadata.get("palette", {}),
        "base_channel_idx": metadata.get("base_channel_idx", 0),
        "layer_order": metadata.get("layer_order", "Top2Bottom"),
    }


def _validate_codec(value: Any) -> None:
    """Allow the existing data codec, excluding its trusted-storage pickle escape."""
    if isinstance(value, list):
        for item in value:
            _validate_codec(item)
    elif isinstance(value, dict):
        kind = value.get("__lumina_session_type__")
        if kind == "pickle":
            raise ValueError("Project edit assets cannot contain executable objects")
        if kind == "ndarray" and np.dtype(value["dtype"]).kind not in "biuf":
            raise ValueError("Project edit assets require numeric arrays")
        for item in value.values():
            _validate_codec(item)


def _validate_checkpoint(checkpoint: dict[str, Any], shape: tuple[int, int]) -> None:
    fields = checkpoint["session_fields"]
    arrays = checkpoint["preview_cache_arrays"]
    if not isinstance(fields, dict) or not set(fields).issubset(REPLACEMENT_SESSION_FIELDS):
        raise ValueError("Project edit fields are invalid")
    if not isinstance(arrays, dict) or not set(arrays).issubset(_ARRAY_FIELDS | _METADATA_FIELDS):
        raise ValueError("Project edit arrays are invalid")
    for name, value in arrays.items():
        if name in _METADATA_FIELDS:
            continue
        if not isinstance(value, np.ndarray) or value.dtype.hasobject:
            raise ValueError(f"Project edit array is invalid: {name}")
        if value.shape[:2] != shape:
            raise ValueError(f"Project edit coordinates do not match: {name}")
        if name in {"material_matrix", "original_material_matrix"}:
            valid = value.ndim == 3 and value.dtype.kind in "iu"
        elif name == "mask_solid":
            valid = value.ndim == 2 and value.dtype == np.bool_
        else:
            valid = value.ndim == 3 and value.shape[2] == 3 and value.dtype == np.uint8
        if not valid:
            raise ValueError(f"Project edit array shape or dtype is invalid: {name}")
    if not {"matched_rgb", "material_matrix", "mask_solid"}.issubset(arrays):
        raise ValueError("Project edit asset is missing editable image/material data")
    selection = fields.get("editor_selection_mask")
    if selection is not None and (
        not isinstance(selection, np.ndarray) or selection.shape != shape or selection.dtype != np.bool_
    ):
        raise ValueError("Project selection mask does not match the image")
    resolved = resolve_recipe_override_masks(fields, fields.get("recipe_overrides"), shape)
    fields["recipe_override_count"] = len(fields.get("recipe_overrides") or [])
    fields["recipe_override_applied_masks"] = {
        region: pack_applied_region_mask(mask) for region, mask in resolved.items()
    }


def build_editor_project(session: dict[str, Any]) -> bytes:
    """Encode current editable pixels, materials and spatial masks without paths.

    使用既有快照与编解码机制保存可编辑像素、材料和空间掩码，不保存会话路径。

    Args:
        session: Authoritative editor session. 权威编辑会话。

    Returns:
        Compressed, path-free checkpoint data. 不含路径的压缩快照数据。
    """
    cache = _cache(session)
    checkpoint = snapshot_replacement_state(session, label="project", include_preview_cache=False)
    checkpoint = {
        "session_fields": checkpoint["session_fields"],
        "preview_cache_arrays": {
            key: value for key, value in cache.items()
            if key in _ARRAY_FIELDS | _METADATA_FIELDS
        },
    }
    _validate_checkpoint(checkpoint, np.asarray(cache["mask_solid"]).shape)
    encoded = encode_session_value(checkpoint)
    _validate_codec(encoded)
    document = {
        "format": "lumina-editor-checkpoint", "version": 1,
        "binding": _binding(session, cache), "checkpoint": encoded,
    }
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > EDITOR_PROJECT_MAX_BYTES:
        raise ValueError("Project edit data exceeds the 512 MiB asset limit")
    return gzip.compress(raw, mtime=0)


def decode_editor_project(payload: bytes, session: dict[str, Any]) -> dict[str, Any]:
    """Validate a portable checkpoint and bind it to a fresh source preview.

    校验可携带快照并绑定新会话的原始预览；保留新会话资源身份，不信任旧路径。

    Args:
        payload: Embedded compressed checkpoint. 内嵌压缩快照。
        session: Newly generated source preview. 新生成的原始预览会话。

    Returns:
        Validated checkpoint using the fresh session's cache resources.
        复用新会话缓存资源的已校验快照。
    """
    try:
        if len(payload) > EDITOR_PROJECT_MAX_BYTES:
            raise ValueError("Project edit asset is too large")
        with gzip.GzipFile(fileobj=BytesIO(payload)) as compressed:
            raw = compressed.read(EDITOR_PROJECT_MAX_BYTES + 1)
        if len(raw) > EDITOR_PROJECT_MAX_BYTES:
            raise ValueError("Project edit asset expands beyond the size limit")
        document = json.loads(raw)
        if document["format"] != "lumina-editor-checkpoint" or document["version"] != 1:
            raise ValueError("Unsupported project edit asset")
        cache = _cache(session)
        if document["binding"] != _binding(session, cache):
            raise ValueError("Project edit source or coordinates do not match the current preview")
        _validate_codec(document["checkpoint"])
        checkpoint = decode_session_value(document["checkpoint"])
        shape = np.asarray(cache["mask_solid"]).shape
        _validate_checkpoint(checkpoint, shape)
        if not np.array_equal(checkpoint["preview_cache_arrays"]["mask_solid"], cache["mask_solid"]):
            raise ValueError("Project edit image footprint does not match the current preview")
    except (OSError, EOFError, zlib.error, UnicodeError, json.JSONDecodeError, KeyError, TypeError, RecursionError) as exc:
        raise ValueError("Project edit asset is damaged or unsupported") from exc
    return {
        "label": "project", "kind": "content",
        "session_fields": checkpoint["session_fields"],
        "preview_cache_arrays": {**deepcopy(cache), **checkpoint["preview_cache_arrays"]},
    }
