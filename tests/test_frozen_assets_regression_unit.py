"""Frozen raster regression suite (high-fidelity + pixel only).

SVG/vector regression is intentionally paused for now.
暂时停用 SVG 回归，只覆盖 raster 模式。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ModelingMode
from core.converter import generate_final_model, generate_preview_cached

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FROZEN_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "frozen_assets"
MANIFEST_PATH = FROZEN_ROOT / "manifest.sha256.json"
BASELINES_DIR = FROZEN_ROOT / "baselines"
BASELINE_JSON_PATH = BASELINES_DIR / "raster_regression_baseline.json"
BASELINE_ARRAYS_DIR = BASELINES_DIR / "arrays"

FIXED_PARAMS = {
    "target_width_mm": 60.0,
    "spacer_thick": 1.2,
    "quantize_colors": 48,
    "enable_cleanup": True,
    "hue_weight": 0.0,
    "chroma_gate": 15.0,
}

THRESHOLDS = {
    "mask_solid_diff_ratio": 0.002,
    "material_matrix_diff_ratio": 0.003,
    "recipe_top10_coverage_abs_diff": 0.005,
    "recipe_top10_distribution_l1": 0.02,
    "bbox_extent_abs_diff_mm": 0.08,
    "recipe_unique_count_abs_diff": 5,
}

LUT_SPECS = [
    {
        "lut_id": "2c_bw",
        "lut_rel": "luts/2c/Bambulab&PLA&BW&白-黑.npy",
        "color_mode": "BW (Black & White)",
    },
    {
        "lut_id": "4c_rybw",
        "lut_rel": "luts/4c/Aliz&PLA&4色RYBW&20260211.npy",
        "color_mode": "4-Color (RYBW)",
    },
    {
        "lut_id": "4c_cmyw",
        "lut_rel": "luts/4c/Aliz&PLA&4色CMYW&20260223.npy",
        "color_mode": "4-Color (CMYW)",
    },
    {
        "lut_id": "6c_rybw",
        "lut_rel": "luts/6c/Aliz&PLA&RYBW&红-蓝-黄-绿-白-黑&20260211.npy",
        "color_mode": "6-Color (RYBWGK 1296)",
    },
    {
        "lut_id": "6c_cmyw",
        "lut_rel": "luts/6c/Aliz&PLA&CMYW&品红-青-黄-绿-白-黑&20260223.npy",
        "color_mode": "6-Color (CMYWGK 1296)",
    },
    {
        "lut_id": "8c",
        "lut_rel": "luts/8c/Aliz&PLA&8色红-黄-蓝-品红-青-白-绿-黑&20260213.npy",
        "color_mode": "8-Color Max",
    },
]

CASES: list[dict[str, Any]] = []
for mode_name, mode_enum in [
    ("high-fidelity", ModelingMode.HIGH_FIDELITY),
    ("pixel", ModelingMode.PIXEL),
]:
    for lut in LUT_SPECS:
        CASES.append(
            {
                "case_id": f"{mode_name}__{lut['lut_id']}",
                "modeling_mode_name": mode_name,
                "modeling_mode": mode_enum,
                "lut_id": lut["lut_id"],
                "lut_rel": lut["lut_rel"],
                "color_mode": lut["color_mode"],
            }
        )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        raise AssertionError(f"Missing manifest: {MANIFEST_PATH}")
    with MANIFEST_PATH.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if "version" not in data or "generated_at" not in data or "files" not in data:
        raise AssertionError("Manifest must include version, generated_at, files")
    if not isinstance(data["files"], list) or not data["files"]:
        raise AssertionError("Manifest files must be a non-empty list")
    return data


def _validate_manifest_integrity_strict() -> None:
    manifest = _load_manifest()
    for idx, item in enumerate(manifest["files"]):
        for key in ("path", "sha256", "kind", "source"):
            if key not in item:
                raise AssertionError(f"Manifest files[{idx}] missing key: {key}")
        if item["kind"] not in {"image", "lut"}:
            raise AssertionError(f"Manifest files[{idx}] invalid kind: {item['kind']}")

        rel_path = str(item["path"]).replace("\\", "/")
        abs_path = FROZEN_ROOT / rel_path
        if not abs_path.is_file():
            raise AssertionError(f"Frozen asset missing: {rel_path}")

        expected = str(item["sha256"]).lower().strip()
        actual = _sha256_file(abs_path)
        if expected != actual:
            raise AssertionError("SHA256 mismatch for " f"{rel_path}: expected={expected}, actual={actual}")


def _compute_recipe_stats(material_matrix: np.ndarray, mask_solid: np.ndarray) -> dict[str, Any]:
    solid_stacks = material_matrix[mask_solid]
    if solid_stacks.size == 0:
        return {
            "recipe_top10_coverage": 0.0,
            "recipe_top10_distribution": [0.0] * 10,
            "recipe_unique_count": 0,
        }

    _, counts = np.unique(solid_stacks, axis=0, return_counts=True)
    counts = np.sort(counts)[::-1]
    total = int(counts.sum())

    top10 = counts[:10].astype(np.float64) / float(total)
    dist = top10.tolist()
    if len(dist) < 10:
        dist.extend([0.0] * (10 - len(dist)))

    return {
        "recipe_top10_coverage": float(np.sum(top10)),
        "recipe_top10_distribution": [float(x) for x in dist],
        "recipe_unique_count": int(len(counts)),
    }


def _bbox_extents_from_glb(glb_path: str | None) -> list[float] | None:
    if not glb_path or not os.path.exists(glb_path):
        return None
    try:
        import trimesh

        loaded = trimesh.load(glb_path, force="scene")
        bounds = np.asarray(loaded.bounds, dtype=np.float64)
        if bounds.shape != (2, 3):
            return None
        extents = np.abs(bounds[1] - bounds[0])
        return [float(extents[0]), float(extents[1]), float(extents[2])]
    except Exception:
        return None


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    image_path = FROZEN_ROOT / "images" / "logo.png"
    lut_path = FROZEN_ROOT / case["lut_rel"]

    display, cache, status_msg = generate_preview_cached(
        image_path=str(image_path),
        lut_path=str(lut_path),
        target_width_mm=FIXED_PARAMS["target_width_mm"],
        color_mode=case["color_mode"],
        modeling_mode=case["modeling_mode"],
        quantize_colors=FIXED_PARAMS["quantize_colors"],
        enable_cleanup=FIXED_PARAMS["enable_cleanup"],
        is_dark=True,
        hue_weight=FIXED_PARAMS["hue_weight"],
        chroma_gate=FIXED_PARAMS["chroma_gate"],
    )

    if display is None or cache is None:
        raise RuntimeError(f"Preview failed for {case['case_id']}: {status_msg}")

    material_matrix = cache["material_matrix"]
    mask_solid = cache["mask_solid"]

    threemf_path, glb_path, _preview_img, generate_msg, _recipe_path = generate_final_model(
        image_path=str(image_path),
        lut_path=str(lut_path),
        target_width_mm=FIXED_PARAMS["target_width_mm"],
        spacer_thick=FIXED_PARAMS["spacer_thick"],
        structure_mode="Double-sided",
        color_mode=case["color_mode"],
        add_loop=False,
        loop_width=4.0,
        loop_length=8.0,
        loop_hole=2.5,
        loop_pos=None,
        modeling_mode=case["modeling_mode"],
        quantize_colors=FIXED_PARAMS["quantize_colors"],
        color_replacements=None,
        replacement_regions=None,
        separate_backing=False,
        enable_relief=False,
        color_height_map=None,
        height_mode="color",
        heightmap_path=None,
        heightmap_max_height=None,
        enable_cleanup=FIXED_PARAMS["enable_cleanup"],
        enable_outline=False,
        outline_width=2.0,
        enable_cloisonne=False,
        wire_width_mm=0.4,
        wire_height_mm=0.4,
        free_color_set=None,
        enable_coating=False,
        coating_height_mm=0.08,
        hue_weight=FIXED_PARAMS["hue_weight"],
        chroma_gate=FIXED_PARAMS["chroma_gate"],
        matched_rgb_path=None,
        loop_angle=0.0,
        loop_offset_x=0.0,
        loop_offset_y=0.0,
        loop_position_preset="top-center",
        printer_id="bambu-h2d",
        slicer="BambuStudio",
        relief_global_max_height=None,
    )

    recipe_stats = _compute_recipe_stats(material_matrix, mask_solid)

    return {
        "case_id": case["case_id"],
        "mode": case["modeling_mode_name"],
        "lut_id": case["lut_id"],
        "lut_rel": case["lut_rel"],
        "color_mode": case["color_mode"],
        "preview_status": status_msg,
        "generate_status": generate_msg,
        "threemf_exists": bool(threemf_path and os.path.exists(threemf_path)),
        "glb_exists": bool(glb_path and os.path.exists(glb_path)),
        "bbox_extents_mm": _bbox_extents_from_glb(glb_path),
        "effective_layers": int(material_matrix.shape[2]),
        "recipe_top10_coverage": recipe_stats["recipe_top10_coverage"],
        "recipe_top10_distribution": recipe_stats["recipe_top10_distribution"],
        "recipe_unique_count": recipe_stats["recipe_unique_count"],
        "arrays": {
            "mask_solid": mask_solid,
            "material_matrix": material_matrix,
        },
    }


def _array_diff_ratio(current: np.ndarray, baseline: np.ndarray) -> float:
    if current.shape != baseline.shape:
        return 1.0
    total = current.size
    if total == 0:
        return 0.0
    diff = int(np.count_nonzero(current != baseline))
    return float(diff / total)


def _load_baseline() -> dict[str, Any] | None:
    if not BASELINE_JSON_PATH.is_file():
        return None
    with BASELINE_JSON_PATH.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _baseline_environment() -> dict[str, str]:
    """Capture runtime versions needed to reproduce raster baselines."""
    import cv2
    import scipy
    from PIL import __version__ as pillow_version

    return {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "opencv": cv2.__version__,
        "pillow": pillow_version,
    }


def _load_baseline_arrays(case_id: str) -> tuple[np.ndarray, np.ndarray]:
    npz_path = BASELINE_ARRAYS_DIR / f"{case_id}.npz"
    if not npz_path.is_file():
        raise AssertionError(f"Missing baseline arrays: {npz_path}")
    data = np.load(npz_path)
    return data["mask_solid"], data["material_matrix"]


def _compare_case_result(
    case_id: str,
    current: dict[str, Any],
    baseline_case: dict[str, Any],
    baseline_mask_solid: np.ndarray,
    baseline_material_matrix: np.ndarray,
) -> list[str]:
    issues: list[str] = []

    current_mask = current["arrays"]["mask_solid"]
    current_matrix = current["arrays"]["material_matrix"]

    mask_ratio = _array_diff_ratio(current_mask, baseline_mask_solid)
    if mask_ratio > THRESHOLDS["mask_solid_diff_ratio"]:
        issues.append(f"{case_id}: mask_solid diff ratio {mask_ratio:.6f} > {THRESHOLDS['mask_solid_diff_ratio']:.6f}")

    matrix_ratio = _array_diff_ratio(current_matrix, baseline_material_matrix)
    if matrix_ratio > THRESHOLDS["material_matrix_diff_ratio"]:
        issues.append(
            f"{case_id}: material_matrix diff ratio {matrix_ratio:.6f} > {THRESHOLDS['material_matrix_diff_ratio']:.6f}"
        )

    coverage_diff = abs(float(current["recipe_top10_coverage"]) - float(baseline_case["recipe_top10_coverage"]))
    if coverage_diff > THRESHOLDS["recipe_top10_coverage_abs_diff"]:
        issues.append(
            f"{case_id}: recipe top10 coverage abs diff {coverage_diff:.6f} > "
            f"{THRESHOLDS['recipe_top10_coverage_abs_diff']:.6f}"
        )

    current_dist = np.array(current["recipe_top10_distribution"], dtype=np.float64)
    baseline_dist = np.array(baseline_case["recipe_top10_distribution"], dtype=np.float64)
    if current_dist.shape != baseline_dist.shape:
        issues.append(f"{case_id}: recipe top10 distribution shape mismatch")
    else:
        l1 = float(np.sum(np.abs(current_dist - baseline_dist)))
        if l1 > THRESHOLDS["recipe_top10_distribution_l1"]:
            issues.append(
                f"{case_id}: recipe top10 distribution L1 {l1:.6f} > "
                f"{THRESHOLDS['recipe_top10_distribution_l1']:.6f}"
            )

    current_bbox = current.get("bbox_extents_mm")
    baseline_bbox = baseline_case.get("bbox_extents_mm")
    if current_bbox is None or baseline_bbox is None:
        issues.append(f"{case_id}: bbox extents unavailable")
    else:
        cur = np.array(current_bbox, dtype=np.float64)
        base = np.array(baseline_bbox, dtype=np.float64)
        if cur.shape != (3,) or base.shape != (3,):
            issues.append(f"{case_id}: bbox extents must be length-3")
        else:
            axis_diff = np.abs(cur - base)
            max_diff = float(np.max(axis_diff))
            if max_diff > THRESHOLDS["bbox_extent_abs_diff_mm"]:
                issues.append(
                    f"{case_id}: bbox extents abs diff max {max_diff:.6f}mm > "
                    f"{THRESHOLDS['bbox_extent_abs_diff_mm']:.6f}mm"
                )

    if int(current["effective_layers"]) != int(baseline_case["effective_layers"]):
        issues.append(
            f"{case_id}: effective_layers changed "
            f"{current['effective_layers']} != {baseline_case['effective_layers']}"
        )

    if bool(current["threemf_exists"]) is not True or bool(baseline_case["threemf_exists"]) is not True:
        issues.append(f"{case_id}: threemf_exists must be true")
    if bool(current["glb_exists"]) is not True or bool(baseline_case["glb_exists"]) is not True:
        issues.append(f"{case_id}: glb_exists must be true")

    unique_diff = abs(int(current["recipe_unique_count"]) - int(baseline_case["recipe_unique_count"]))
    if unique_diff > THRESHOLDS["recipe_unique_count_abs_diff"]:
        issues.append(
            f"{case_id}: recipe unique count abs diff {unique_diff} > " f"{THRESHOLDS['recipe_unique_count_abs_diff']}"
        )

    return issues


def generate_baseline() -> None:
    _validate_manifest_integrity_strict()

    BASELINE_ARRAYS_DIR.mkdir(parents=True, exist_ok=True)

    cases_out: dict[str, Any] = {}
    for idx, case in enumerate(CASES, start=1):
        print(f"[{idx}/{len(CASES)}] generating baseline: {case['case_id']}")
        result = _run_case(case)
        case_id = result["case_id"]

        np.savez_compressed(
            BASELINE_ARRAYS_DIR / f"{case_id}.npz",
            mask_solid=result["arrays"]["mask_solid"],
            material_matrix=result["arrays"]["material_matrix"],
        )

        payload = {k: v for k, v in result.items() if k != "arrays"}
        cases_out[case_id] = payload

    baseline_doc = {
        "version": "1.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "regression_scope": "raster_only",
        "svg_regression": "paused",
        "generator_environment": _baseline_environment(),
        "fixed_params": FIXED_PARAMS,
        "thresholds": THRESHOLDS,
        "cases": cases_out,
    }

    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    with BASELINE_JSON_PATH.open("w", encoding="utf-8-sig") as f:
        json.dump(baseline_doc, f, indent=2, ensure_ascii=False)

    print(f"Baseline JSON written: {BASELINE_JSON_PATH}")
    print(f"Baseline arrays written: {BASELINE_ARRAYS_DIR}")


def verify_against_baseline() -> bool:
    _validate_manifest_integrity_strict()

    baseline = _load_baseline()
    if baseline is None:
        print(f"ERROR: Baseline file not found: {BASELINE_JSON_PATH}")
        return False

    cases_baseline = baseline.get("cases", {})
    all_issues: list[str] = []

    for idx, case in enumerate(CASES, start=1):
        case_id = case["case_id"]
        print(f"[{idx}/{len(CASES)}] verifying case: {case_id}")

        baseline_case = cases_baseline.get(case_id)
        if baseline_case is None:
            all_issues.append(f"{case_id}: missing in baseline JSON")
            continue

        baseline_mask, baseline_matrix = _load_baseline_arrays(case_id)
        current = _run_case(case)
        issues = _compare_case_result(
            case_id=case_id,
            current=current,
            baseline_case=baseline_case,
            baseline_mask_solid=baseline_mask,
            baseline_material_matrix=baseline_matrix,
        )
        if issues:
            all_issues.extend(issues)

    if all_issues:
        print("\nVerification FAILED:")
        for issue in all_issues:
            print(f"  - {issue}")
        return False

    print("\nVerification PASSED: all 12 raster cases are within thresholds.")
    return True


def test_frozen_manifest_integrity() -> None:
    _validate_manifest_integrity_strict()


def test_frozen_baseline_parameters_and_thresholds_match_runner() -> None:
    baseline = _load_baseline()
    assert baseline is not None, "Frozen raster baseline must be present"
    assert baseline["fixed_params"] == FIXED_PARAMS
    assert baseline["thresholds"] == THRESHOLDS


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_raster_case_against_baseline(case: dict[str, Any]) -> None:
    _validate_manifest_integrity_strict()

    baseline = _load_baseline()
    if baseline is None:
        pytest.skip(
            "Frozen raster baseline not generated. "
            "Run: python tests/test_frozen_assets_regression_unit.py --generate"
        )

    case_id = case["case_id"]
    baseline_case = baseline.get("cases", {}).get(case_id)
    if baseline_case is None:
        raise AssertionError(f"Missing baseline JSON entry for case: {case_id}")

    baseline_mask, baseline_matrix = _load_baseline_arrays(case_id)
    current = _run_case(case)

    issues = _compare_case_result(
        case_id=case_id,
        current=current,
        baseline_case=baseline_case,
        baseline_mask_solid=baseline_mask,
        baseline_material_matrix=baseline_matrix,
    )
    assert not issues, "\n".join(issues)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Frozen raster regression (high-fidelity + pixel; SVG paused)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", action="store_true", help="Generate frozen raster baseline")
    group.add_argument("--verify", action="store_true", help="Verify current output against frozen baseline")
    args = parser.parse_args()

    if args.generate:
        generate_baseline()
        raise SystemExit(0)

    ok = verify_against_baseline()
    raise SystemExit(0 if ok else 1)
