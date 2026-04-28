"""Regression for the multi-run combined-samples refitting path.

Re-verification ("再次验证") aggregation now prefers concatenating the
per-run linear-RGB samples and re-running ``_fit_component`` on the
combined set, instead of arithmetically averaging Beer-Lambert
``(E, k)``. Averaging non-linear parameters is statistically
unsound; combined-sample refitting is the only way "more captures =
more accurate parameters" actually holds.

The fallback path (parameter mean) must still kick in when any run
lacks ``samples`` so old archives saved before the new schema keep
loading.

再次验证聚合优先走"合并样本重拟合"，对参数做算术平均在 Beer-Lambert
模型下统计无意义；缺样本时回退到参数均值，保证向后兼容。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np

from core.single_stage import (
    extract_stage_a_material_from_gradient_cards,
    save_stage_a_material_archive,
)
from core.single_stage.kit import SingleStageSpec


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
    *,
    noise_seed: int | None = None,
    noise_amplitude: float = 0.0,
) -> np.ndarray:
    """Build a synthetic gradient card capture with optional per-cell noise.

    ``noise_seed`` together with ``noise_amplitude`` simulate camera shot
    noise / illumination unevenness across a re-capture: each grid cell
    receives an independent linear-RGB perturbation that survives
    ``_srgb_to_linear`` round-trip in the fitter.
    用 ``noise_seed`` + ``noise_amplitude`` 模拟一次重拍带来的逐格扰动。
    """
    rng = np.random.default_rng(noise_seed) if noise_seed is not None else None
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
            if rng is not None and noise_amplitude > 0.0:
                linear_rgb = np.clip(
                    linear_rgb + rng.uniform(-noise_amplitude, noise_amplitude, 3),
                    0.0,
                    1.0,
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


def _extract_run(
    tmp_path: Path,
    spec: SingleStageSpec,
    *,
    noise_seed: int | None,
    suffix: str,
):
    zip_path = tmp_path / f"kit_{suffix}.zip"
    _write_gradient_card_manifest(zip_path, spec)
    white_substrate = np.array([0.86, 0.88, 0.9], dtype=np.float64)
    black_substrate = np.array([0.08, 0.09, 0.1], dtype=np.float64)
    expected_e = np.array([0.22, 0.18, 0.15], dtype=np.float64)
    expected_k = np.array([1.7, 1.4, 1.2], dtype=np.float64)
    white_capture = _build_gradient_card_capture(
        spec, white_substrate, expected_e, expected_k,
        noise_seed=noise_seed, noise_amplitude=0.01,
    )
    black_capture = _build_gradient_card_capture(
        spec, black_substrate, expected_e, expected_k,
        noise_seed=None if noise_seed is None else noise_seed + 1000,
        noise_amplitude=0.01,
    )
    corners = [
        [0, 0],
        [white_capture.shape[1] - 1, 0],
        [white_capture.shape[1] - 1, white_capture.shape[0] - 1],
        [0, white_capture.shape[0] - 1],
    ]
    return extract_stage_a_material_from_gradient_cards(
        white_capture, black_capture,
        corners, corners, str(zip_path),
        output_path=str(tmp_path / f"stage_a_{suffix}.json"),
    )


def test_fit_payload_writes_fit_samples_block(tmp_path: Path) -> None:
    """`_build_fit_payload` must persist the linear-RGB sample matrices and
    matching thickness vector inside ``material_summary`` so downstream
    re-aggregation can re-fit on the combined sample set."""
    spec = _make_spec()
    result = _extract_run(tmp_path, spec, noise_seed=1, suffix="seed1")
    samples = result.material_summary.get("fit_samples")
    assert isinstance(samples, dict)
    thickness = samples["thickness_mm"]
    white = samples["white_linear"]
    black = samples["black_linear"]
    assert isinstance(thickness, list) and len(thickness) == spec.grid_rows * spec.grid_cols
    assert isinstance(white, list) and len(white) == len(thickness)
    assert isinstance(black, list) and len(black) == len(thickness)
    assert all(isinstance(row, list) and len(row) == 3 for row in white)
    assert all(isinstance(row, list) and len(row) == 3 for row in black)


def test_aggregate_uses_refit_combined_samples_when_all_runs_have_samples(
    tmp_path: Path,
) -> None:
    """Two consecutive captures of the same material must aggregate via the
    combined-samples refit path, and the archive must record this method."""
    spec = _make_spec()
    materials_root = tmp_path / "materials"

    first = _extract_run(tmp_path, spec, noise_seed=11, suffix="run1")
    save_first = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=first.params_payload,
        fit_summary=first.fit_summary,
        source_summary=first.source_summary,
        material_summary=first.material_summary,
        materials_dir=str(materials_root),
    )
    second = _extract_run(tmp_path, spec, noise_seed=23, suffix="run2")
    save_second = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=second.params_payload,
        fit_summary=second.fit_summary,
        source_summary=second.source_summary,
        material_summary=second.material_summary,
        materials_dir=str(materials_root),
        existing_directory_name=save_first.material_summary["directory_name"],
    )

    assert save_second.material_summary["verification_count"] == 2
    archive_payload = json.loads(
        Path(save_second.archive_path).read_text(encoding="utf-8")
    )
    assert archive_payload["aggregation"]["method"] == "refit_combined_samples"

    saved_payload = json.loads(
        Path(save_second.stage_a_params_path).read_text(encoding="utf-8")
    )
    assert saved_payload["meta"]["aggregation_method"] == "refit_combined_samples"
    assert (
        archive_payload["fit_summary"]["overall_validation"]["aggregation_method"]
        == "refit_combined_samples"
    )

    runs = archive_payload["verification_runs"]
    assert len(runs) == 2
    for run in runs:
        assert "samples" in run, run
        assert isinstance(run["samples"]["thickness_mm"], list)
        assert len(run["samples"]["white_linear"]) == len(run["samples"]["thickness_mm"])
        assert len(run["samples"]["black_linear"]) == len(run["samples"]["thickness_mm"])

    expected_e = np.array([0.22, 0.18, 0.15], dtype=np.float64)
    expected_k = np.array([1.7, 1.4, 1.2], dtype=np.float64)
    aggregated_e = np.asarray(
        saved_payload["parameters"]["channels"][0]["E"], dtype=np.float64
    )
    aggregated_k = np.asarray(
        saved_payload["parameters"]["channels"][0]["k"], dtype=np.float64
    )
    # Combined refit on noisy synthetic data still recovers ground truth
    # within the same loose tolerances used for single-run noise-free fits.
    # 合并样本重拟合在带噪声合成数据上仍能恢复真值（与单 run 同等容差）。
    assert np.allclose(aggregated_e, expected_e, atol=1e-2)
    assert np.allclose(aggregated_k, expected_k, atol=1e-1)


def test_aggregate_falls_back_to_mean_when_legacy_run_lacks_samples(
    tmp_path: Path,
) -> None:
    """If any verification run lacks ``samples`` (legacy archive) the
    aggregation must fall back to the parameter-mean path so old archives
    keep working without losing the ability to re-aggregate."""
    spec = _make_spec()
    materials_root = tmp_path / "materials"

    first = _extract_run(tmp_path, spec, noise_seed=31, suffix="legacy1")
    # Strip fit_samples to simulate a pre-schema-update archive: the run
    # written to disk won't carry ``samples``.
    legacy_summary = dict(first.material_summary)
    legacy_summary.pop("fit_samples", None)
    save_first = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=first.params_payload,
        fit_summary=first.fit_summary,
        source_summary=first.source_summary,
        material_summary=legacy_summary,
        materials_dir=str(materials_root),
    )

    second = _extract_run(tmp_path, spec, noise_seed=37, suffix="legacy2")
    save_second = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=second.params_payload,
        fit_summary=second.fit_summary,
        source_summary=second.source_summary,
        material_summary=second.material_summary,
        materials_dir=str(materials_root),
        existing_directory_name=save_first.material_summary["directory_name"],
    )

    archive_payload = json.loads(
        Path(save_second.archive_path).read_text(encoding="utf-8")
    )
    assert archive_payload["aggregation"]["method"] == "mean"
    saved_payload = json.loads(
        Path(save_second.stage_a_params_path).read_text(encoding="utf-8")
    )
    assert saved_payload["meta"]["aggregation_method"] == "mean"


def test_aggregate_falls_back_to_mean_when_samples_shape_is_invalid(
    tmp_path: Path,
) -> None:
    """A malformed ``fit_samples`` block (wrong row count) must not crash
    the aggregator; it must transparently degrade to parameter-mean."""
    spec = _make_spec()
    materials_root = tmp_path / "materials"

    first = _extract_run(tmp_path, spec, noise_seed=41, suffix="bad1")
    save_first = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=first.params_payload,
        fit_summary=first.fit_summary,
        source_summary=first.source_summary,
        material_summary=first.material_summary,
        materials_dir=str(materials_root),
    )

    second = _extract_run(tmp_path, spec, noise_seed=43, suffix="bad2")
    bad_summary = dict(second.material_summary)
    bad_samples = dict(bad_summary["fit_samples"])
    # Drop one row from white_linear so shape no longer matches thickness_mm.
    bad_samples["white_linear"] = bad_samples["white_linear"][:-1]
    bad_summary["fit_samples"] = bad_samples
    save_second = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=second.params_payload,
        fit_summary=second.fit_summary,
        source_summary=second.source_summary,
        material_summary=bad_summary,
        materials_dir=str(materials_root),
        existing_directory_name=save_first.material_summary["directory_name"],
    )

    archive_payload = json.loads(
        Path(save_second.archive_path).read_text(encoding="utf-8")
    )
    assert archive_payload["aggregation"]["method"] == "mean"


def test_single_run_save_records_aggregation_method(tmp_path: Path) -> None:
    """Even a fresh first save (single run) must write a deterministic
    ``aggregation_method``. With samples present, the single-run archive
    is recorded as ``refit_combined_samples`` because the refit path runs
    on the one available sample set; this keeps the archive's aggregation
    method always-set and avoids special-casing the singleton case in
    downstream code."""
    spec = _make_spec()
    materials_root = tmp_path / "materials"
    result = _extract_run(tmp_path, spec, noise_seed=51, suffix="single")
    save_result = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=result.params_payload,
        fit_summary=result.fit_summary,
        source_summary=result.source_summary,
        material_summary=result.material_summary,
        materials_dir=str(materials_root),
    )
    archive_payload = json.loads(
        Path(save_result.archive_path).read_text(encoding="utf-8")
    )
    assert archive_payload["aggregation"]["method"] == "refit_combined_samples"
    assert archive_payload["verification_count"] == 1
    assert "samples" in archive_payload["verification_runs"][0]
