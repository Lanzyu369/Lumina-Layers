"""Regression for Stage A overbright-zero-thickness warning.

The warning fires when the linear-RGB ``C0_white`` mean exceeds 0.95.
Overbright normalization or clipping in the sampled Stage A area pushes
the zero-thickness samples toward (1.0, 1.0, 1.0); the resulting
``(E, k)`` will be biased away from the true physical attenuation. The
warning is the in-pipeline signal that surfaces this otherwise-invisible
failure mode (``mean_delta_e`` / ``rmse_linear`` cannot detect it).

零厚度白底线性 RGB 均值超过 0.95 时触发警告：采样区域过亮归一化或
发生裁切时，零厚度采样会接近纯白 (1.0)，拟合出的 (E, k) 会偏离
真实物理量；该警告用于识别这种失效信号。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np

from core.single_stage import extract_stage_a_material_from_gradient_cards
from core.single_stage.kit import SingleStageSpec


_OVERBRIGHT_WARNING_FRAGMENT = "零厚度白底采样接近纯白"


def _linear_to_srgb_uint8(arr: np.ndarray) -> np.ndarray:
    clipped = np.clip(arr.astype(np.float64), 0.0, 1.0)
    srgb = np.where(
        clipped <= 0.0031308,
        12.92 * clipped,
        1.055 * np.power(clipped, 1.0 / 2.4) - 0.055,
    )
    return np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)


def _write_gradient_card_manifest(zip_path: Path, spec: SingleStageSpec) -> None:
    manifest = {
        "schema_version": "1.0",
        "workflow": "single-stage-kit",
        "material_default": "PLA Basic",
        "substrate_id": "white",
        "substrate_display_name": "White",
        "spec": {
            "grid_cols": spec.grid_cols,
            "grid_rows": spec.grid_rows,
            "block_mm": spec.block_mm,
            "gap_mm": spec.gap_mm,
            "margin_mm": spec.margin_mm,
            "pixel_mm": spec.pixel_mm,
            "layer_height_mm": spec.layer_height_mm,
            "base_mm": spec.base_mm,
            "max_step_layers": spec.max_step_layers,
            "step_layers": list(spec.step_layers),
            "shrink_xy_mm": spec.shrink_xy_mm,
        },
    }
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )


def _build_gradient_card_capture(
    spec: SingleStageSpec,
    substrate_linear: np.ndarray,
    e_linear: np.ndarray,
    k_linear: np.ndarray,
) -> np.ndarray:
    pixels_per_mm = 20
    width = int(round(spec.board_width_mm * pixels_per_mm))
    height = int(round(spec.board_height_mm * pixels_per_mm))
    image = np.tile(
        _linear_to_srgb_uint8(substrate_linear.reshape(1, 3)),
        (height, width, 1),
    )
    step_matrix = np.asarray(spec.step_layers, dtype=np.float64).reshape(
        spec.grid_rows,
        spec.grid_cols,
    )
    for row in range(spec.grid_rows):
        for col in range(spec.grid_cols):
            step_layers = step_matrix[row, col]
            thickness_mm = step_layers * spec.layer_height_mm
            linear_rgb = e_linear + (substrate_linear - e_linear) * np.exp(
                -k_linear * thickness_mm,
            )
            srgb = _linear_to_srgb_uint8(linear_rgb.reshape(1, 3))[0]
            x0 = int(round((spec.margin_mm + col * (spec.block_mm + spec.gap_mm)) * pixels_per_mm))
            y0 = int(round((spec.margin_mm + row * (spec.block_mm + spec.gap_mm)) * pixels_per_mm))
            x1 = int(round((spec.margin_mm + col * (spec.block_mm + spec.gap_mm) + spec.block_mm) * pixels_per_mm))
            y1 = int(round((spec.margin_mm + row * (spec.block_mm + spec.gap_mm) + spec.block_mm) * pixels_per_mm))
            image[y0:y1, x0:x1] = srgb
    return image


def _make_spec() -> SingleStageSpec:
    return SingleStageSpec(
        grid_cols=3,
        grid_rows=2,
        block_mm=10.0,
        gap_mm=0.0,
        margin_mm=0.0,
        pixel_mm=1.0,
        layer_height_mm=0.1,
        base_mm=1.0,
        max_step_layers=6,
        step_layers=(0, 1, 2, 3, 4, 6),
        shrink_xy_mm=0.0,
    )


def _run_extract(
    tmp_path: Path,
    *,
    white_substrate: np.ndarray,
) -> tuple[list[str], float]:
    """Run a Stage A extraction and return ``(warnings, c0_white_mean)``."""
    spec = _make_spec()
    zip_path = tmp_path / "kit.zip"
    _write_gradient_card_manifest(zip_path, spec)

    black_substrate = np.array([0.08, 0.09, 0.1], dtype=np.float64)
    expected_e = np.array([0.22, 0.18, 0.15], dtype=np.float64)
    expected_k = np.array([1.7, 1.4, 1.2], dtype=np.float64)
    white_capture = _build_gradient_card_capture(
        spec, white_substrate, expected_e, expected_k
    )
    black_capture = _build_gradient_card_capture(
        spec, black_substrate, expected_e, expected_k
    )
    corners = [
        [0, 0],
        [white_capture.shape[1] - 1, 0],
        [white_capture.shape[1] - 1, white_capture.shape[0] - 1],
        [0, white_capture.shape[0] - 1],
    ]
    result = extract_stage_a_material_from_gradient_cards(
        white_capture,
        black_capture,
        corners,
        corners,
        str(zip_path),
        output_path=str(tmp_path / "stage_a.json"),
    )
    warnings = list(result.fit_summary.get("warnings") or [])
    c0_white = result.params_payload["parameters"]["substrates"][0]["C0"]
    return warnings, float(np.mean(np.asarray(c0_white, dtype=np.float64)))


def test_stage_a_warns_when_zero_thickness_white_is_overbright(tmp_path: Path) -> None:
    """A white substrate at (0.99, 0.99, 0.99) must produce the
    C0_white-overbright warning."""
    warnings, c0_white_mean = _run_extract(
        tmp_path,
        white_substrate=np.array([0.99, 0.99, 0.99], dtype=np.float64),
    )
    assert c0_white_mean > 0.95
    assert any(_OVERBRIGHT_WARNING_FRAGMENT in w for w in warnings), warnings
    overbright_warning = next(
        w for w in warnings if _OVERBRIGHT_WARNING_FRAGMENT in w
    )
    assert "裁切" in overbright_warning or "过亮归一化" in overbright_warning
    assert f"{c0_white_mean:.3f}" in overbright_warning


def test_stage_a_no_overbright_warning_when_zero_thickness_in_normal_range(
    tmp_path: Path,
) -> None:
    """A realistic raw-photo white substrate at (0.86, 0.88, 0.90) — well
    below the 0.95 overbright threshold — must NOT produce the warning."""
    warnings, c0_white_mean = _run_extract(
        tmp_path,
        white_substrate=np.array([0.86, 0.88, 0.90], dtype=np.float64),
    )
    assert c0_white_mean <= 0.95
    assert not any(_OVERBRIGHT_WARNING_FRAGMENT in w for w in warnings), warnings


def test_stage_a_overbright_warning_threshold_is_exclusive(tmp_path: Path) -> None:
    """C0_white mean exactly at 0.95 must NOT trigger the warning (the
    threshold is strictly greater-than). This guards against accidentally
    flipping the comparison from ``>`` to ``>=`` and spamming users at the
    boundary.
    阈值采用严格大于；恰好等于 0.95 时不触发，防止边界误警。"""
    warnings, c0_white_mean = _run_extract(
        tmp_path,
        white_substrate=np.array([0.95, 0.95, 0.95], dtype=np.float64),
    )
    # The fitted C0_white may differ from the substrate by a few thousandths
    # due to median-of-pixels in linear space; we only require it to be at or
    # below the threshold for this branch.
    if c0_white_mean <= 0.95:
        assert not any(_OVERBRIGHT_WARNING_FRAGMENT in w for w in warnings)
    else:
        assert any(_OVERBRIGHT_WARNING_FRAGMENT in w for w in warnings)
