from __future__ import annotations

from pathlib import Path

from .calibration_core import (
    EXPOSURE_ANCHOR_PATCH_INDEX,
    EXPOSURE_ANCHOR_TARGET_SRGB,
    parse_colorchecker_desc,
)

DEFAULT_REFERENCE_DESC = Path(__file__).resolve().parent / "data" / "desc.txt"


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


BRAND_DEFINITIONS = [
    {
        "id": "dafan",
        "name": "大凡光学",
        "description": "24 色 ColorChecker，4×6 / 3×8 排列均可使用",
        "reference_file": DEFAULT_REFERENCE_DESC,
    },
]


def build_brand(
    definition: dict[str, object],
    *,
    exposure_anchor_target_srgb: int = EXPOSURE_ANCHOR_TARGET_SRGB,
) -> dict[str, object]:
    patches = load_reference_patches(
        Path(definition["reference_file"]),
        exposure_anchor_target_srgb=exposure_anchor_target_srgb,
    )
    return {
        "id": str(definition["id"]),
        "name": str(definition["name"]),
        "description": str(definition.get("description") or ""),
        "patches": patches,
        "color_map": build_color_map(patches),
        "reference_source": {
            "source_type": "built_in",
            "source_name": str(definition["name"]),
            "serial_number": None,
            "patch_count": len(patches),
            "lab_white_point": "D50",
        },
        "exposure_anchor_patch_index": EXPOSURE_ANCHOR_PATCH_INDEX,
        "exposure_anchor_target_srgb": int(exposure_anchor_target_srgb),
    }


def _build_brand_registry() -> dict[str, dict[str, object]]:
    registry: dict[str, dict[str, object]] = {}
    for definition in BRAND_DEFINITIONS:
        registry[str(definition["id"])] = build_brand(definition)
    return registry


BRAND_REGISTRY = _build_brand_registry()
BRAND_DEFINITION_MAP = {str(definition["id"]): definition for definition in BRAND_DEFINITIONS}
DEFAULT_BRAND_ID = next(iter(BRAND_REGISTRY))


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


def list_brand_summaries() -> list[dict[str, object]]:
    return [
        {
            "id": brand["id"],
            "name": brand["name"],
            "description": brand["description"],
            "patchCount": len(brand["patches"]),
        }
        for brand in BRAND_REGISTRY.values()
    ]
