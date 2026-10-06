"""LUT parsing helpers for details aggregation.
LUT 详情聚合所需的 LUT 解析辅助。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PureWindowsPath
from typing import Any

import cv2
import msgpack
import numpy as np

from config import LUTMetadata
from core.native_reference import opencv_lab_to_rgb_uint8, standard_lab_to_rgb_uint8
from core.predictive_lut import load_predictive_modes
from utils.lut_manager import LUTManager


@dataclass(frozen=True)
class ParsedLut:
    """Parsed LUT detail payload.
    解析后的 LUT 详情载荷。
    """

    name: str
    path: Path
    color_mode: str
    color_count: int
    source_kind: str
    compatibility_key: str
    rgb: np.ndarray
    lab: np.ndarray
    metadata: LUTMetadata
    raw_metadata: dict[str, Any]


class LutParser:
    """Parse LUT files into detail-ready data.
    将 LUT 文件解析为可用于详情展示的数据。
    """

    def parse(self, *, name: str, path: Path) -> ParsedLut:
        """Parse one LUT file into a detail payload.
        解析单个 LUT 文件为详情载荷。

        Args:
            name: Display name. (显示名称)
            path: LUT file path. (LUT 文件路径)

        Returns:
            ParsedLut: Parsed payload. (解析后的载荷)
        """

        resolved_path = Path(path).resolve()
        raw_payload = self._load_raw_payload(resolved_path)
        suffix = resolved_path.suffix.lower()
        loaded_model_package = False
        if suffix == ".json" and raw_payload is not None:
            rgb, _stacks, metadata = LUTManager._load_keyed_payload(
                raw_payload, name, str(resolved_path),
                skip_malformed_recipes=True,
            )
        elif suffix == ".msgpack" and isinstance(raw_payload, dict):
            if LUTManager._is_model_package_payload(raw_payload):
                try:
                    rgb, _stacks, metadata = LUTManager._load_model_package_from_payload(str(resolved_path), name, raw_payload)
                    loaded_model_package = True
                except Exception:
                    if isinstance(raw_payload.get("entries"), list):
                        rgb, _stacks, metadata = LUTManager._load_keyed_payload(
                            raw_payload, name, str(resolved_path),
                            skip_malformed_recipes=True,
                        )
                    else:
                        raise
            else:
                rgb, _stacks, metadata = LUTManager._load_keyed_payload(
                    raw_payload, name, str(resolved_path),
                    skip_malformed_recipes=True,
                )
        else:
            rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(str(resolved_path))
        rgb = np.asarray(rgb if rgb is not None else np.zeros((0, 3), dtype=np.uint8), dtype=np.uint8).reshape(-1, 3)
        if loaded_model_package:
            rgb, metadata = self._hydrate_model_package_display_payload(rgb, metadata)
        color_mode = metadata.color_mode or LUTManager.infer_color_mode(name, str(resolved_path))
        detected_count = int(rgb.shape[0])
        lab = self._extract_lab_points(raw_payload, rgb)
        if rgb.shape[0] == 0 and lab.shape[0] > 0:
            rgb = standard_lab_to_rgb_uint8(lab.astype(np.float32))
        color_count = int(detected_count or rgb.shape[0] or lab.shape[0])
        raw_metadata = self._sanitize_raw_metadata(raw_payload, metadata)
        return ParsedLut(
            name=name,
            path=resolved_path,
            color_mode=color_mode,
            color_count=color_count,
            source_kind=metadata.get_source_kind(),
            compatibility_key=LUTManager.legacy_multi_compatibility_key(metadata),
            rgb=rgb,
            lab=lab,
            metadata=metadata,
            raw_metadata=raw_metadata,
        )

    def _load_raw_payload(self, path: Path) -> Any:
        suffix = path.suffix.lower()
        if suffix == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        if suffix == ".msgpack":
            return msgpack.unpackb(path.read_bytes(), raw=False)
        return None

    def _extract_lab_points(self, raw_payload: Any, rgb: np.ndarray) -> np.ndarray:
        if isinstance(raw_payload, dict):
            entries = raw_payload.get("entries")
            if isinstance(entries, list):
                if rgb.size > 0:
                    lab_img = self._lab_from_rgb(rgb)
                    has_explicit_lab = False
                    rgb_index = 0
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        if not self._entry_contributes_rgb(entry):
                            continue
                        if rgb_index >= lab_img.shape[0]:
                            break
                        lab_triplet = self._coerce_lab_triplet(entry.get("lab"))
                        if lab_triplet is not None:
                            lab_img[rgb_index] = lab_triplet
                            has_explicit_lab = True
                        rgb_index += 1
                    return lab_img

                lab_points = [
                    lab_triplet.tolist()
                    for entry in entries
                    if isinstance(entry, dict) and self._entry_has_valid_recipe(entry)
                    for lab_triplet in [self._coerce_lab_triplet(entry.get("lab"))]
                    if lab_triplet is not None
                ]
                if lab_points:
                    return np.asarray(lab_points, dtype=np.float32)
        if rgb.size == 0:
            return np.zeros((0, 3), dtype=np.float32)
        return self._lab_from_rgb(rgb)

    def _hydrate_model_package_display_payload(
        self,
        rgb: np.ndarray,
        metadata: LUTMetadata,
    ) -> tuple[np.ndarray, LUTMetadata]:
        """Populate detail-view display points from the first usable predictive runtime mode.
        从首个可用的预测式 runtime 模式补齐详情视图所需的展示点。
        """
        runtime_modes = list(load_predictive_modes(metadata).values())
        if not runtime_modes:
            return rgb, metadata

        metadata.extensions["supported_modes"] = [
            {
                "mode_key": mode.mode_key,
                "color_layers": int(mode.color_layers),
                "layer_height_mm": float(mode.layer_height_mm),
                "layer_order": str(mode.layer_order),
            }
            for mode in runtime_modes
        ]
        preferred_mode = next((mode for mode in runtime_modes if int(mode.color_layers) == 5), runtime_modes[0])
        metadata.max_color_layers = int(preferred_mode.color_layers)
        metadata.layer_height_mm = float(preferred_mode.layer_height_mm)
        metadata.layer_order = str(preferred_mode.layer_order)
        if rgb.size == 0:
            rgb = opencv_lab_to_rgb_uint8(preferred_mode.pred_lab)
        return rgb, metadata

    def _lab_from_rgb(self, rgb: np.ndarray) -> np.ndarray:
        rgb_img = rgb.reshape(1, -1, 3).astype(np.uint8)
        bgr_img = cv2.cvtColor(rgb_img, cv2.COLOR_RGB2BGR)
        lab_img = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
        lab_img[:, 0] = lab_img[:, 0] * 100.0 / 255.0
        lab_img[:, 1] = lab_img[:, 1] - 128.0
        lab_img[:, 2] = lab_img[:, 2] - 128.0
        return lab_img

    def _coerce_lab_triplet(self, value: Any) -> np.ndarray | None:
        if not isinstance(value, list) or len(value) < 3:
            return None
        try:
            lab_triplet = np.asarray([float(component) for component in value[:3]], dtype=np.float32)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(lab_triplet).all():
            return None
        return lab_triplet

    def _entry_contributes_rgb(self, entry: dict[str, Any]) -> bool:
        if not isinstance(entry.get("recipe"), (list, tuple)):
            return False
        rgb_val = entry.get("rgb")
        if isinstance(rgb_val, list) and len(rgb_val) == 3:
            try:
                [int(component) for component in rgb_val[:3]]
                return self._entry_has_valid_recipe(entry)
            except (TypeError, ValueError):
                return False
        return self._coerce_lab_triplet(entry.get("lab")) is not None and self._entry_has_valid_recipe(entry)

    def _entry_has_valid_recipe(self, entry: dict[str, Any]) -> bool:
        recipe = entry.get("recipe")
        if not isinstance(recipe, (list, tuple)):
            return False
        for value in recipe:
            if isinstance(value, str):
                continue
            try:
                int(value)
            except (TypeError, ValueError):
                return False
        return True

    def _sanitize_raw_metadata(self, raw_payload: Any, metadata: LUTMetadata) -> dict[str, Any]:
        if isinstance(raw_payload, dict):
            sanitized: dict[str, Any] = {}
            for key, value in raw_payload.items():
                if key in {"entries", "runtime_package", "stage_model", "measured_db", "modes"}:
                    continue
                key_text = str(key)
                sanitized[key_text] = self._json_safe_value(value, key=key_text)
            return sanitized
        metadata_dict = metadata.to_dict()
        for heavy_key in ("runtime_package", "stage_model", "measured_db"):
            metadata_dict.pop(heavy_key, None)
        return {
            str(key): self._json_safe_value(value, key=str(key))
            for key, value in metadata_dict.items()
        }

    def _json_safe_value(self, value: Any, *, key: str | None = None) -> Any:
        if isinstance(value, bytes):
            return f"<{len(value)} bytes>"
        if isinstance(value, dict):
            return {
                str(item_key): self._json_safe_value(item, key=str(item_key))
                for item_key, item in value.items()
            }
        if isinstance(value, list):
            return [self._json_safe_value(item, key=key) for item in value]
        if isinstance(value, tuple):
            return [self._json_safe_value(item, key=key) for item in value]
        if isinstance(value, str) and self._is_sensitive_local_path(value, key=key):
            return "<local path>"
        return value

    def _is_sensitive_local_path(self, value: str, *, key: str | None = None) -> bool:
        text = value.strip()
        if not text:
            return False
        if self._looks_like_local_path(text):
            return True
        return self._is_path_like_metadata_key(key) and text.lower().startswith("file:")

    def _is_path_like_metadata_key(self, key: str | None) -> bool:
        if not key:
            return False
        normalized = key.replace("-", "_").lower()
        return any(
            token in normalized
            for token in ("path", "file", "dir", "folder", "url", "uri")
        )

    def _looks_like_local_path(self, value: str) -> bool:
        normalized = value.replace("\\", "/")
        lower = normalized.lower()
        if lower.startswith("file://"):
            return True
        if normalized.startswith("~/") or normalized == "~":
            return True
        if value.startswith("\\\\") or value.startswith("//"):
            return True
        windows_path = PureWindowsPath(value)
        if windows_path.drive:
            return True
        return normalized.startswith("/")
