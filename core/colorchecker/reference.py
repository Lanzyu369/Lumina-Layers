from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .calibration_core import (
    EXPOSURE_ANCHOR_PATCH_INDEX,
    EXPOSURE_ANCHOR_TARGET_SRGB,
    parse_colorchecker_desc,
)
from .color_metrics import (
    lab_to_linear_srgb,
    linear_srgb_to_lab,
    linear_to_srgb,
    srgb_to_linear,
)

DEFAULT_REFERENCE_DESC = Path(__file__).resolve().parent / "data" / "desc.txt"
REFERENCE_DATA_DIR = Path(__file__).resolve().parent / "data" / "references"
REFERENCE_PATCH_COUNT = 24
DEFAULT_REFERENCE_ID = "dafan"


class ReferenceValidationError(ValueError):
    """Raised when a ColorChecker reference cannot be normalized."""


def load_reference_patches(
    desc_path: str | Path = DEFAULT_REFERENCE_DESC,
    exposure_anchor_target_srgb: int = EXPOSURE_ANCHOR_TARGET_SRGB,
) -> list[dict[str, object]]:
    colors = parse_colorchecker_desc(desc_path)
    patches: list[dict[str, object]] = []
    for idx, (label, values) in enumerate(colors.items(), start=1):
        srgb = [int(v) for v in values.get("sRGB", [])]
        patches.append(
            {
                "index": idx,
                "label": label,
                "sRGB": srgb,
                "Lab_d50": [float(v) for v in values.get("Lab_d50", [])],
                "Lab_d65": [float(v) for v in values.get("Lab_d65", [])],
            }
        )
    return patches


def normalize_reference(
    patches: Sequence[Mapping[str, object]],
    source: Mapping[str, object] | None = None,
    *,
    source_type: str = "user_upload",
    source_name: str = "自定义校色基准",
) -> dict[str, object]:
    """Normalize partial ColorChecker reference patches.

    Each patch must provide one complete color triplet among sRGB, Lab D50, or
    Lab D65. Missing representations are derived with the shared color metric
    conversions so detection and calibration receive the same complete data.

    规范化前端解析出的色卡基准。每个色块至少需要一组三元组，其余色彩空间在
    后端统一补齐，供自动检测与最终拟合共用。
    """

    normalized_patches, warnings = normalize_reference_patches(patches)
    reference_hash = compute_reference_hash(normalized_patches)
    normalized_source = normalize_reference_source(
        source,
        source_type=source_type,
        source_name=source_name,
        patch_count=len(normalized_patches),
        reference_hash=reference_hash,
    )
    return {
        "patches": normalized_patches,
        "source": normalized_source,
        "reference_hash": reference_hash,
        "warnings": warnings,
    }


def normalize_reference_patches(
    patches: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[str]]:
    if not isinstance(patches, Sequence) or isinstance(patches, (str, bytes, bytearray)):
        raise ReferenceValidationError("reference patches must be a list.")
    if len(patches) != REFERENCE_PATCH_COUNT:
        raise ReferenceValidationError(
            f"校色基准必须包含 {REFERENCE_PATCH_COUNT} 个色块。"
        )

    by_index: dict[int, Mapping[str, object]] = {}
    for raw_patch in patches:
        if not isinstance(raw_patch, Mapping):
            raise ReferenceValidationError("每个色块必须是对象。")
        index = _coerce_patch_index(raw_patch)
        if index in by_index:
            raise ReferenceValidationError(f"校色基准包含重复编号 {index}。")
        by_index[index] = raw_patch

    expected = set(range(1, REFERENCE_PATCH_COUNT + 1))
    actual = set(by_index)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = []
        if missing:
            detail.append("缺少编号 " + ", ".join(str(item) for item in missing))
        if extra:
            detail.append("包含越界编号 " + ", ".join(str(item) for item in extra))
        raise ReferenceValidationError("校色基准编号必须为连续 1-24：" + "；".join(detail))

    normalized: list[dict[str, object]] = []
    warnings: list[str] = []
    for index in range(1, REFERENCE_PATCH_COUNT + 1):
        patch, patch_warnings = _normalize_patch(by_index[index], index)
        normalized.append(patch)
        warnings.extend(patch_warnings)
    labels: set[str] = set()
    for patch in normalized:
        label = str(patch["label"]).strip()
        if label in labels:
            raise ReferenceValidationError(f"校色基准包含重复色块名称：{label}")
        labels.add(label)
    return normalized, warnings


def normalize_reference_source(
    source: Mapping[str, object] | None,
    *,
    source_type: str,
    source_name: str,
    patch_count: int,
    reference_hash: str,
) -> dict[str, object]:
    raw = source if isinstance(source, Mapping) else {}
    return {
        "source_type": str(
            _first_present(raw, "source_type", "sourceType") or source_type
        ),
        "source_name": str(
            _first_present(raw, "source_name", "sourceName", "name") or source_name
        ),
        "serial_number": _optional_str(
            _first_present(raw, "serial_number", "serialNumber")
        ),
        "patch_count": int(patch_count),
        "lab_white_point": str(
            _first_present(raw, "lab_white_point", "labWhitePoint") or "D50"
        ),
        "reference_hash": str(reference_hash),
    }


def compute_reference_hash(patches: Sequence[Mapping[str, object]]) -> str:
    payload = []
    for patch in patches:
        payload.append(
            {
                "index": int(patch["index"]),
                "sRGB": [int(v) for v in patch["sRGB"]],  # type: ignore[index]
                "Lab_d50": [_round_lab_value(v) for v in patch["Lab_d50"]],  # type: ignore[index]
                "Lab_d65": [_round_lab_value(v) for v in patch["Lab_d65"]],  # type: ignore[index]
            }
        )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sanitize_exposure_anchor_target(
    raw: object,
    *,
    fallback: int = EXPOSURE_ANCHOR_TARGET_SRGB,
) -> int:
    if raw in {None, ""}:
        return int(fallback)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("22 号灰块锚定曝光值必须是 1~254 之间的整数。") from exc
    if not (1 <= value <= 254):
        raise ValueError("22 号灰块锚定曝光值必须落在 1~254 区间。")
    return value


def build_color_map(patches: list[dict[str, object]]) -> dict[str, dict[str, list[float]]]:
    return {
        str(item["label"]): {
            "sRGB": list(item["sRGB"]),
            "Lab_d50": list(item["Lab_d50"]),
            "Lab_d65": list(item["Lab_d65"]),
        }
        for item in patches
    }


def _load_brand_definitions() -> list[dict[str, object]]:
    definitions: list[dict[str, object]] = []
    if REFERENCE_DATA_DIR.exists():
        for path in sorted(REFERENCE_DATA_DIR.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ReferenceValidationError(
                    f"无法读取校色基准文件 {path.name}: {exc}"
                ) from exc
            if not isinstance(payload, dict):
                raise ReferenceValidationError(
                    f"校色基准文件 {path.name} 必须是 JSON 对象。"
                )
            payload.setdefault("reference_document", path)
            definitions.append(payload)

    if not any(str(item.get("id")) == DEFAULT_REFERENCE_ID for item in definitions):
        definitions.append(
            {
                "id": DEFAULT_REFERENCE_ID,
                "name": "大凡光学",
                "description": "24 色 ColorChecker，4×6 / 3×8 排列均可使用",
                "reference_file": DEFAULT_REFERENCE_DESC,
            }
        )
    return definitions


BRAND_DEFINITIONS = _load_brand_definitions()


def build_brand(
    definition: dict[str, object],
    *,
    exposure_anchor_target_srgb: int = EXPOSURE_ANCHOR_TARGET_SRGB,
) -> dict[str, object]:
    if isinstance(definition.get("patches"), list):
        normalized = normalize_reference(
            definition["patches"],  # type: ignore[arg-type]
            _definition_source(definition),
            source_type="built_in",
            source_name=str(definition.get("name") or definition.get("id") or ""),
        )
        patches = normalized["patches"]
        reference_source = normalized["source"]
        reference_hash = str(normalized["reference_hash"])
    else:
        patches = load_reference_patches(
            Path(definition["reference_file"]),
            exposure_anchor_target_srgb=exposure_anchor_target_srgb,
        )
        reference_hash = compute_reference_hash(patches)
        reference_source = normalize_reference_source(
            _definition_source(definition),
            source_type="built_in",
            source_name=str(definition["name"]),
            patch_count=len(patches),
            reference_hash=reference_hash,
        )
    patch_list = list(patches)  # type: ignore[arg-type]
    return {
        "id": str(definition["id"]),
        "name": str(definition["name"]),
        "description": str(definition.get("description") or ""),
        "patches": patch_list,
        "color_map": build_color_map(patch_list),
        "reference_source": reference_source,
        "reference_hash": reference_hash,
        "exposure_anchor_patch_index": EXPOSURE_ANCHOR_PATCH_INDEX,
        "exposure_anchor_target_srgb": int(exposure_anchor_target_srgb),
    }


def _build_brand_registry() -> dict[str, dict[str, object]]:
    registry: dict[str, dict[str, object]] = {}
    for definition in BRAND_DEFINITIONS:
        registry[str(definition["id"])] = build_brand(definition)
    return registry


def get_brand(
    brand_id: object,
    *,
    exposure_anchor_target_srgb: int = EXPOSURE_ANCHOR_TARGET_SRGB,
) -> dict[str, object]:
    key = str(brand_id) if brand_id else DEFAULT_BRAND_ID
    if key not in BRAND_DEFINITION_MAP:
        raise ValueError(f"未知的校色卡品牌：{key}")
    if exposure_anchor_target_srgb == EXPOSURE_ANCHOR_TARGET_SRGB:
        return BRAND_REGISTRY[key]
    return build_brand(
        BRAND_DEFINITION_MAP[key],
        exposure_anchor_target_srgb=exposure_anchor_target_srgb,
    )


def resolve_reference(
    *,
    reference_id: object = None,
    reference_patches: Sequence[Mapping[str, object]] | None = None,
    reference_source: Mapping[str, object] | None = None,
    exposure_anchor_target_srgb: int = EXPOSURE_ANCHOR_TARGET_SRGB,
) -> dict[str, object]:
    if reference_patches is None:
        return get_brand(
            reference_id,
            exposure_anchor_target_srgb=exposure_anchor_target_srgb,
        )
    normalized = normalize_reference(
        reference_patches,
        reference_source,
        source_type="user_upload",
        source_name="自定义校色基准",
    )
    source = normalized["source"]
    patches = list(normalized["patches"])  # type: ignore[arg-type]
    return {
        "id": None,
        "name": str(source.get("source_name") or "自定义校色基准"),  # type: ignore[union-attr]
        "description": "",
        "patches": patches,
        "color_map": build_color_map(patches),
        "reference_source": source,
        "reference_hash": str(normalized["reference_hash"]),
        "warnings": list(normalized["warnings"]),  # type: ignore[arg-type]
        "exposure_anchor_patch_index": EXPOSURE_ANCHOR_PATCH_INDEX,
        "exposure_anchor_target_srgb": int(exposure_anchor_target_srgb),
    }


def list_brand_summaries() -> list[dict[str, object]]:
    return [
        {
            "id": brand["id"],
            "name": brand["name"],
            "description": brand["description"],
            "patchCount": len(brand["patches"]),
            "source": brand.get("reference_source"),
            "serialNumber": (
                brand.get("reference_source", {}).get("serial_number")
                if isinstance(brand.get("reference_source"), dict)
                else None
            ),
            "labWhitePoint": (
                brand.get("reference_source", {}).get("lab_white_point")
                if isinstance(brand.get("reference_source"), dict)
                else "D50"
            ),
            "referenceHash": brand.get("reference_hash"),
        }
        for brand in BRAND_REGISTRY.values()
    ]


def _normalize_patch(
    raw_patch: Mapping[str, object],
    index: int,
) -> tuple[dict[str, object], list[str]]:
    label = str(raw_patch.get("label") or raw_patch.get("name") or f"Patch {index}").strip()
    if not label:
        label = f"Patch {index}"
    srgb = _coerce_srgb(_first_present(raw_patch, "sRGB", "srgb", "rgb"), index)
    lab_d50 = _coerce_lab(_first_present(raw_patch, "Lab_d50", "labD50", "lab_d50"), index, "D50")
    lab_d65 = _coerce_lab(_first_present(raw_patch, "Lab_d65", "labD65", "lab_d65"), index, "D65")

    if srgb is None and lab_d50 is None and lab_d65 is None:
        raise ReferenceValidationError(
            f"色块 {index} 至少需要完整 sRGB、Lab D50 或 Lab D65 三元组之一。"
        )

    warnings: list[str] = []
    if srgb is None:
        source_lab = lab_d65 if lab_d65 is not None else lab_d50
        source_white = "D65" if lab_d65 is not None else "D50"
        if source_lab is None:
            raise ReferenceValidationError(
                f"色块 {index} 至少需要完整 sRGB、Lab D50 或 Lab D65 三元组之一。"
            )
        srgb, clipped = _lab_to_srgb(source_lab, source_white)
        if clipped:
            warnings.append(f"Patch {index} {source_white} Lab clipped to sRGB gamut.")

    linear = srgb_to_linear(_as_unit_rgb(srgb))
    if lab_d65 is None:
        lab_d65 = _lab_triplet(linear_srgb_to_lab(linear, white="D65"))
    if lab_d50 is None:
        lab_d50 = _lab_triplet(linear_srgb_to_lab(linear, white="D50"))

    return (
        {
            "index": index,
            "label": label,
            "sRGB": srgb,
            "Lab_d50": lab_d50,
            "Lab_d65": lab_d65,
        },
        warnings,
    )


def _definition_source(definition: Mapping[str, object]) -> dict[str, object]:
    source = definition.get("source")
    raw = source if isinstance(source, Mapping) else {}
    return {
        "source_type": raw.get("source_type") or raw.get("sourceType") or "built_in",
        "source_name": raw.get("source_name") or raw.get("sourceName") or definition.get("name"),
        "serial_number": raw.get("serial_number") or raw.get("serialNumber"),
        "lab_white_point": raw.get("lab_white_point") or raw.get("labWhitePoint") or "D50",
    }


def _first_present(raw: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in raw:
            return raw[key]
    return None


def _coerce_patch_index(raw_patch: Mapping[str, object]) -> int:
    raw = _first_present(raw_patch, "index", "number", "No", "no")
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ReferenceValidationError("每个色块必须包含整数编号。") from exc
    if not (1 <= value <= REFERENCE_PATCH_COUNT):
        raise ReferenceValidationError(f"色块编号 {value} 超出 1-24 范围。")
    return value


def _coerce_srgb(raw: object, index: int) -> list[int] | None:
    values = _coerce_triplet(raw, index=index, name="sRGB")
    if values is None:
        return None
    result: list[int] = []
    for value in values:
        if not (0.0 <= value <= 255.0):
            raise ReferenceValidationError(f"色块 {index} 的 sRGB 必须在 0-255 范围内。")
        result.append(int(round(value)))
    return result


def _coerce_lab(raw: object, index: int, white_point: str) -> list[float] | None:
    values = _coerce_triplet(raw, index=index, name=f"Lab {white_point}")
    if values is None:
        return None
    if not (0.0 <= values[0] <= 100.0):
        raise ReferenceValidationError(f"色块 {index} 的 Lab {white_point} L* 必须在 0-100 范围内。")
    if not (-150.0 <= values[1] <= 150.0 and -150.0 <= values[2] <= 150.0):
        raise ReferenceValidationError(f"色块 {index} 的 Lab {white_point} a*/b* 超出支持范围。")
    return [_round_lab_value(v) for v in values]


def _coerce_triplet(raw: object, *, index: int, name: str) -> list[float] | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise ReferenceValidationError(f"色块 {index} 的 {name} 必须是三元组。")
    values = list(raw)
    if len(values) < 3:
        if all(item in (None, "") for item in values):
            return None
        raise ReferenceValidationError(f"色块 {index} 的 {name} 必须包含 3 个数值。")
    if all(item in (None, "") for item in values[:3]):
        return None
    if any(item in (None, "") for item in values[:3]):
        raise ReferenceValidationError(f"色块 {index} 的 {name} 三元组不完整。")
    try:
        return [float(item) for item in values[:3]]
    except (TypeError, ValueError) as exc:
        raise ReferenceValidationError(f"色块 {index} 的 {name} 必须是数字。") from exc


def _as_unit_rgb(srgb: Sequence[int]) -> Any:
    import numpy as np

    return np.asarray([float(v) / 255.0 for v in srgb[:3]], dtype=np.float64)


def _lab_to_srgb(lab: Sequence[float], white_point: str) -> tuple[list[int], bool]:
    import numpy as np

    linear = lab_to_linear_srgb(np.asarray(lab[:3], dtype=np.float64), white=white_point)
    clipped = bool(np.any(linear < -1e-6) or np.any(linear > 1.0 + 1e-6))
    srgb = linear_to_srgb(np.clip(linear, 0.0, 1.0))
    rgb = np.clip(np.rint(srgb * 255.0), 0.0, 255.0).astype(int)
    return [int(v) for v in rgb.tolist()], clipped


def _lab_triplet(values: object) -> list[float]:
    import numpy as np

    arr = np.asarray(values, dtype=np.float64).reshape(-1)
    return [_round_lab_value(v) for v in arr[:3].tolist()]


def _round_lab_value(value: object) -> float:
    return round(float(value), 4)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


BRAND_REGISTRY = _build_brand_registry()
BRAND_DEFINITION_MAP = {str(definition["id"]): definition for definition in BRAND_DEFINITIONS}
DEFAULT_BRAND_ID = next(iter(BRAND_REGISTRY))
