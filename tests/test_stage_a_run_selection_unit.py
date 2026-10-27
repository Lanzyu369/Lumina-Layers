"""Regression for the multi-run selection policy that picks which
verification runs participate in the joint Beer-Lambert refit.

The selection has two layers:

1. **Bias filter** — drop historical runs that show known structural
   bias indicators (white_C0 average above 0.95, image_source=restored,
   substrate-flat flags, orientation unreliable). The fresh run (last
   in the list) is always kept; if dropping leaves zero historicals,
   the least-flagged historical survives so the fresh run still has a
   sample partner.
2. **Cross-validation** — when 3+ historicals survive the bias filter,
   each is scored by how well its own ``(E, k)`` predicts the OTHER
   surviving runs' samples; only the top half are kept.

These tests pin down the contract: which runs survive in each
scenario, which are excluded with which ``reason``/``bias_flags``,
and how the selection metadata is persisted into the saved archive.

Stage A 多 run 选择的回归测试：偏置硬过滤 + N>=3 时 cross-val 选最可
广化候选；新 run 始终入选；选择诊断写入存档供前端展示。
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
from core.single_stage.material_runs import (
    _BIAS_FLAG_BLACK_SUBSTRATE_FLAT,
    _BIAS_FLAG_C0_WHITE_HIGH,
    _BIAS_FLAG_C0_WHITE_LOW,
    _BIAS_FLAG_IMAGE_SOURCE_RESTORED,
    _BIAS_FLAG_MEAN_DE_HIGH,
    _BIAS_FLAG_ORIENTATION_UNRELIABLE,
    _BIAS_FLAG_WHITE_SUBSTRATE_FLAT,
    _aggregate_stage_a_runs,
    _score_run_bias,
    _select_runs_for_refit,
)


# --- Helpers (synthetic gradient-card data) -----------------------------


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
    image_source: str | None = None,
    white_substrate: np.ndarray | None = None,
    black_substrate: np.ndarray | None = None,
):
    """Run extract_stage_a_material_from_gradient_cards with optional
    overrides for substrate brightness so we can synthesise biased
    captures (e.g. C0_white pushed near 1.0 to mimic white-balanced
    inputs).
    """
    if white_substrate is None:
        white_substrate = np.array([0.86, 0.88, 0.9], dtype=np.float64)
    if black_substrate is None:
        black_substrate = np.array([0.08, 0.09, 0.1], dtype=np.float64)
    expected_e = np.array([0.22, 0.18, 0.15], dtype=np.float64)
    expected_k = np.array([1.7, 1.4, 1.2], dtype=np.float64)
    zip_path = tmp_path / f"kit_{suffix}.zip"
    _write_gradient_card_manifest(zip_path, spec)
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
        image_source=image_source,
    )


def _make_synthetic_samples(
    *,
    white_substrate: list[float],
    black_substrate: list[float],
    e_values: list[float] = (0.22, 0.18, 0.15),
    k_values: list[float] = (1.7, 1.4, 1.2),
    n_thicknesses: int = 6,
) -> dict:
    """Generate a Beer-Lambert-consistent samples block.
    生成符合 Beer-Lambert 模型的合成样本块。

    Used by tests that exercise ``_aggregate_stage_a_runs`` directly: the
    aggregator drives the joint refit through ``_collect_combined_run_samples``
    which expects ``thickness_mm`` / ``white_linear`` / ``black_linear``
    arrays of consistent shape. The samples produced here are noise-free
    so the refit is deterministic and the test can assert exact behaviour.
    """
    e_arr = np.asarray(e_values, dtype=np.float64)
    k_arr = np.asarray(k_values, dtype=np.float64)
    white_arr = np.asarray(white_substrate, dtype=np.float64)
    black_arr = np.asarray(black_substrate, dtype=np.float64)
    thicknesses = np.linspace(0.0, 0.5, n_thicknesses, dtype=np.float64)
    white_rows: list[list[float]] = []
    black_rows: list[list[float]] = []
    for t in thicknesses:
        decay = np.exp(-k_arr * t)
        white_rows.append((e_arr + (white_arr - e_arr) * decay).tolist())
        black_rows.append((e_arr + (black_arr - e_arr) * decay).tolist())
    return {
        "schema_version": "1.0",
        "thickness_mm": thicknesses.tolist(),
        "white_linear": white_rows,
        "black_linear": black_rows,
    }


def _make_synthetic_run(
    *,
    white_c0: list[float],
    image_source: str | None = None,
    flat_white: bool = False,
    flat_black: bool = False,
    orientation_reliable: bool = True,
    bias_flag_count_override: None | int = None,
    fit_samples: dict | None = None,
    mean_delta_e: float = 2.0,
) -> dict:
    """Build a fully-formed verification_run dict for unit tests that
    only exercise the run-selection logic (no real Stage A extraction
    needed). Defaults are bias-free.

    ``mean_delta_e`` is exposed because the ``mean_de_gt_3`` structural
    flag uses it as the input signal: tests for that rule need to push
    a run above / below the 3.0 threshold without rebuilding the whole
    fit_summary by hand.
    """
    run: dict = {
        "captured_at": "2026-04-28T07:00:00+00:00",
        "params": {
            "E": [0.22, 0.18, 0.15],
            "k": [1.7, 1.4, 1.2],
            "white_C0": white_c0,
            "black_C0": [0.05, 0.05, 0.05],
        },
        "fit_summary": {
            "overall_validation": {
                "mean_delta_e": mean_delta_e,
                "max_delta_e": max(4.0, mean_delta_e * 2.0),
                "rmse_linear": 0.02,
            },
            "orientation_ranking": {
                "orientation_reliable": orientation_reliable,
                "white_orientation_info": {"flat": flat_white},
                "black_orientation_info": {"flat": flat_black},
            },
            "warnings": [],
        },
        "material_summary": {
            "estimated_rgb": [200, 100, 100],
            "estimated_k": [1.7, 1.4, 1.2],
        },
        "source": {"image_source": image_source} if image_source is not None else {},
    }
    if fit_samples is not None:
        run["samples"] = fit_samples
    return run


# --- _score_run_bias unit tests -----------------------------------------


def test_score_run_bias_clean_run_has_zero_flags() -> None:
    run = _make_synthetic_run(white_c0=[0.85, 0.86, 0.87])
    score = _score_run_bias(run)
    assert score["bias_flag_count"] == 0
    assert score["bias_flags"] == []
    assert score["white_c0_avg"] is not None
    assert 0.84 < score["white_c0_avg"] < 0.88


def test_score_run_bias_detects_high_white_c0() -> None:
    run = _make_synthetic_run(white_c0=[0.97, 0.98, 0.96])
    score = _score_run_bias(run)
    assert _BIAS_FLAG_C0_WHITE_HIGH in score["bias_flags"]


def test_score_run_bias_detects_image_source_restored() -> None:
    run = _make_synthetic_run(white_c0=[0.85, 0.86, 0.87], image_source="restored")
    score = _score_run_bias(run)
    assert _BIAS_FLAG_IMAGE_SOURCE_RESTORED in score["bias_flags"]
    assert score["image_source"] == "restored"


def test_score_run_bias_skips_image_source_raw() -> None:
    run = _make_synthetic_run(white_c0=[0.85, 0.86, 0.87], image_source="raw")
    score = _score_run_bias(run)
    assert _BIAS_FLAG_IMAGE_SOURCE_RESTORED not in score["bias_flags"]


def test_score_run_bias_detects_flat_substrates() -> None:
    run = _make_synthetic_run(
        white_c0=[0.85, 0.86, 0.87],
        flat_white=True,
        flat_black=True,
    )
    score = _score_run_bias(run)
    assert _BIAS_FLAG_WHITE_SUBSTRATE_FLAT in score["bias_flags"]
    assert _BIAS_FLAG_BLACK_SUBSTRATE_FLAT in score["bias_flags"]


def test_score_run_bias_detects_orientation_unreliable() -> None:
    run = _make_synthetic_run(
        white_c0=[0.85, 0.86, 0.87],
        orientation_reliable=False,
    )
    score = _score_run_bias(run)
    assert _BIAS_FLAG_ORIENTATION_UNRELIABLE in score["bias_flags"]


def test_score_run_bias_detects_low_white_c0() -> None:
    """Underexposed captures land white_C0 well below the typical PLA
    white substrate range (0.85-0.92). When the average drops below
    0.60 the dynamic range is so squeezed that the LM fitter has to
    distort (E, k) — typically inflating ``k`` past 5 — to bend an
    exponential through nearly-step data. Surface this as a structural
    flag so such runs are kept out of joint refits.
    捕获过暗（白底均值<0.60）会压扁动态范围、迫使 (E, k) 失真，应作为
    结构性偏置标签隔离。"""
    run = _make_synthetic_run(white_c0=[0.34, 0.35, 0.32])
    score = _score_run_bias(run)
    assert _BIAS_FLAG_C0_WHITE_LOW in score["bias_flags"]
    assert _BIAS_FLAG_C0_WHITE_LOW in score["structural_flags"]


def test_score_run_bias_skips_low_white_c0_at_boundary() -> None:
    """A run whose white_C0 average is exactly at 0.60 must NOT be
    flagged. The threshold is "strictly below"; equality is still in
    the acceptable underexposed-but-recoverable band. This pins the
    contract so future tweaks don't silently swallow boundary cases.
    边界值 0.60 不算偏置，避免轻微欠曝光的 run 被误伤。"""
    run = _make_synthetic_run(white_c0=[0.60, 0.60, 0.60])
    score = _score_run_bias(run)
    assert _BIAS_FLAG_C0_WHITE_LOW not in score["bias_flags"]


def test_score_run_bias_detects_high_mean_delta_e() -> None:
    """``mean_delta_e > 3.0`` means the run's *own* fit is already
    untrustworthy: feeding its samples into a joint refit only drags
    other captures' parameters toward this run's distorted (E, k).
    The structural flag stops the joint refit from "averaging in
    garbage".
    单 run 自身 ΔE>3 即拟合不可信，应阻止其样本进入联合重拟。"""
    run = _make_synthetic_run(
        white_c0=[0.85, 0.86, 0.87],
        mean_delta_e=4.5,
    )
    score = _score_run_bias(run)
    assert _BIAS_FLAG_MEAN_DE_HIGH in score["bias_flags"]
    assert _BIAS_FLAG_MEAN_DE_HIGH in score["structural_flags"]


def test_score_run_bias_skips_high_mean_delta_e_at_boundary() -> None:
    """``mean_delta_e == 3.0`` is the "borderline acceptable" mark
    (printer slicer profiles aim for ΔE<2 ideal, <3 acceptable). The
    rule is strictly greater-than to keep this band usable.
    ΔE=3.0 视为可接受边界，不触发结构性标签。"""
    run = _make_synthetic_run(white_c0=[0.85, 0.86, 0.87], mean_delta_e=3.0)
    score = _score_run_bias(run)
    assert _BIAS_FLAG_MEAN_DE_HIGH not in score["bias_flags"]


def test_score_run_bias_handles_missing_overall_validation() -> None:
    """Legacy archives may store ``fit_summary`` without an
    ``overall_validation`` block (older schema). Detection must not
    KeyError; absent ΔE = no flag (we cannot punish unknown).
    缺 overall_validation 不报错也不打标签。"""
    run = _make_synthetic_run(white_c0=[0.85, 0.86, 0.87])
    run["fit_summary"].pop("overall_validation", None)
    score = _score_run_bias(run)
    assert _BIAS_FLAG_MEAN_DE_HIGH not in score["bias_flags"]


# --- _select_runs_for_refit unit tests ----------------------------------


def test_select_runs_keeps_fresh_when_only_one_run() -> None:
    fresh = _make_synthetic_run(white_c0=[0.85, 0.86, 0.87])
    selection = _select_runs_for_refit([fresh])
    assert selection["selected_indices"] == [0]
    assert selection["fresh_index"] == 0
    assert selection["excluded_runs"] == []


def test_select_runs_keeps_fresh_even_when_fresh_is_biased() -> None:
    """The user's most recent capture must never be silently dropped,
    even if it carries bias indicators. Surfacing it lets the operator
    see why their workflow is flagged instead of pretending it never
    happened."""
    historical = _make_synthetic_run(white_c0=[0.85, 0.86, 0.87])
    fresh_biased = _make_synthetic_run(
        white_c0=[0.97, 0.98, 0.99],
        image_source="restored",
    )
    selection = _select_runs_for_refit([historical, fresh_biased])
    assert 1 in selection["selected_indices"]


def test_select_runs_drops_high_c0_white_historical_when_clean_alternative_exists() -> None:
    biased_historical = _make_synthetic_run(white_c0=[0.97, 0.98, 0.99])
    clean_historical = _make_synthetic_run(white_c0=[0.85, 0.86, 0.87])
    fresh = _make_synthetic_run(white_c0=[0.85, 0.86, 0.87])
    selection = _select_runs_for_refit([biased_historical, clean_historical, fresh])
    assert 0 not in selection["selected_indices"]
    assert 1 in selection["selected_indices"]
    assert 2 in selection["selected_indices"]
    excluded_indices = [entry["index"] for entry in selection["excluded_runs"]]
    assert excluded_indices == [0]
    assert selection["excluded_runs"][0]["reason"] == "bias_filter"
    assert _BIAS_FLAG_C0_WHITE_HIGH in selection["excluded_runs"][0]["bias_flags"]


def test_select_runs_drops_all_historicals_strictly_worse_than_fresh() -> None:
    """When every historical carries strictly more bias flags than the
    fresh run, all of them are excluded and the joint refit falls back
    to a single-run fit on the fresh capture alone. This is the
    "accuracy over precision" trade-off: adding biased samples to the
    LM cost would corrupt ``(E, k)`` more than fewer-but-clean samples
    help precision."""
    severely_biased = _make_synthetic_run(
        white_c0=[0.99, 0.99, 0.99],
        image_source="restored",
        flat_white=True,
    )
    mildly_biased = _make_synthetic_run(
        white_c0=[0.85, 0.86, 0.87],
        image_source="restored",
    )
    fresh = _make_synthetic_run(white_c0=[0.85, 0.86, 0.87])  # zero flags
    selection = _select_runs_for_refit([severely_biased, mildly_biased, fresh])
    assert selection["selected_indices"] == [2]  # fresh-only refit
    excluded_indices = sorted(entry["index"] for entry in selection["excluded_runs"])
    assert excluded_indices == [0, 1]


def test_select_runs_keeps_historical_with_same_flag_count_as_fresh() -> None:
    """A historical with the SAME bias flags as the fresh run is kept
    so that "two restored captures" can still be jointly refit; both
    inputs share the same bias level so concatenating their samples
    does not introduce new bias asymmetry."""
    historical = _make_synthetic_run(
        white_c0=[0.85, 0.86, 0.87],
        image_source="restored",  # 1 flag
    )
    fresh = _make_synthetic_run(
        white_c0=[0.85, 0.86, 0.87],
        image_source="restored",  # 1 flag, same as historical
    )
    selection = _select_runs_for_refit([historical, fresh])
    assert selection["selected_indices"] == [0, 1]
    assert selection["excluded_runs"] == []


def test_select_runs_runs_cross_val_only_when_three_or_more_clean_historicals() -> None:
    historicals = [
        _make_synthetic_run(white_c0=[0.85, 0.86, 0.87]) for _ in range(3)
    ]
    fresh = _make_synthetic_run(white_c0=[0.85, 0.86, 0.87])
    runs = historicals + [fresh]
    selection = _select_runs_for_refit(runs)
    # Without samples on any run, cross-val cannot run even though there
    # are 3 surviving historicals — falls back to bias_filter_v1 only.
    # 没有 samples 时即使 ≥3 个 historical 也回退到 bias_filter_v1。
    assert selection["selection_strategy"] == "bias_filter_v1"


def test_select_runs_records_run_scores_for_every_run() -> None:
    runs = [
        _make_synthetic_run(white_c0=[0.97, 0.98, 0.99]),
        _make_synthetic_run(white_c0=[0.85, 0.86, 0.87]),
    ]
    selection = _select_runs_for_refit(runs)
    assert len(selection["run_scores"]) == 2
    score0 = selection["run_scores"][0]
    score1 = selection["run_scores"][1]
    assert score0["index"] == 0 and score1["index"] == 1
    assert score0["bias_flag_count"] == 1
    assert score1["bias_flag_count"] == 0
    assert score1["is_fresh"] is True


def test_select_runs_excludes_historical_with_white_c0_pairwise_mismatch() -> None:
    """Two runs whose white_C0 averages diverge by > 1.5x cannot be
    co-merged: the joint refit cost surface has no single (E, k) that
    explains both lighting conditions, so the resulting parameters are
    *worse* than either run alone (real-world: 品红 fresh@0.617 +
    historical@0.336 produced merged mean_dE 13 vs single-run 4.5).
    The pairwise check excludes the historical with reason
    ``c0_white_pairwise_mismatch`` and surfaces the ratio + values for
    the UI; the fresh run is never the one excluded by this rule.
    跨 run 的白底亮度差>1.5×即视为光照不一致，剔除历史 run 防止合并恶化。
    """
    historical_dark = _make_synthetic_run(white_c0=[0.34, 0.35, 0.32])
    fresh_normal = _make_synthetic_run(white_c0=[0.62, 0.64, 0.61])
    selection = _select_runs_for_refit([historical_dark, fresh_normal])
    assert selection["selected_indices"] == [1]
    assert len(selection["excluded_runs"]) == 1
    excluded = selection["excluded_runs"][0]
    assert excluded["index"] == 0
    # The exclusion reason must use the dedicated code so the UI can
    # localise it differently from the single-run ``bias_filter`` and
    # the cross-val tier.
    assert excluded["reason"] in {
        "c0_white_pairwise_mismatch",
        "bias_filter",  # also acceptable if the historical *also*
                        # carries a structural flag (low_white in this
                        # case) and gets caught at Layer 1 first
    }


def test_select_runs_pairwise_emits_dedicated_reason_when_only_pairwise_triggers() -> None:
    """Tighten the previous test: when the historical's single-run
    structural flag count is <= the fresh run's (so Layer 1 keeps it),
    the *only* reason it could still be excluded is the pairwise rule.
    Both runs sit safely above the 0.60 single-run threshold; the only
    issue is they disagree with each other by ~1.7x.
    单 run 各自合规、仅靠成对比较剔除时，必须使用专用 reason。"""
    # Both above single-run 0.60 threshold → no `c0_white_avg_lt_0_60`
    # on either; both at default mean_dE=2.0 → no `mean_de_gt_3`. The
    # ratio 1.04/0.61 ≈ 1.70 trips the pairwise rule cleanly.
    historical = _make_synthetic_run(white_c0=[0.61, 0.61, 0.61])
    fresh = _make_synthetic_run(white_c0=[1.04, 1.04, 1.04])
    selection = _select_runs_for_refit([historical, fresh])
    assert selection["selected_indices"] == [1]
    excluded = selection["excluded_runs"][0]
    assert excluded["index"] == 0
    assert excluded["reason"] == "c0_white_pairwise_mismatch"
    # The UI needs the actual numbers to render a meaningful message;
    # without them, the operator cannot tell *how* mismatched the runs
    # were.
    assert "fresh_white_c0_avg" in excluded
    assert "run_white_c0_avg" in excluded
    assert "ratio" in excluded
    assert excluded["ratio"] > 1.5


def test_select_runs_pairwise_keeps_runs_within_threshold() -> None:
    """When the white_C0 ratio stays within 1.5x, both runs survive
    the pairwise check. This pins the inclusive boundary so a benign
    "both runs slightly different lighting" pair is preserved (more
    samples = better refit precision when the bias is the same).
    比例≤1.5×应保留双方，避免轻微光照差异被误伤。"""
    # 0.85 vs 1.0 → ratio = 1.176 (well under 1.5x); both above 0.60
    # so single-run rules don't fire either.
    historical = _make_synthetic_run(white_c0=[0.85, 0.85, 0.85])
    fresh = _make_synthetic_run(white_c0=[1.00, 1.00, 1.00])
    selection = _select_runs_for_refit([historical, fresh])
    assert selection["selected_indices"] == [0, 1]
    assert selection["excluded_runs"] == []


def test_select_runs_pairwise_skipped_when_white_c0_missing() -> None:
    """Runs whose ``params.white_C0`` is missing (``white_c0_avg=None``)
    cannot be compared pairwise; the rule must short-circuit and let
    Layer-1 single-run flags decide instead. This protects legacy
    archives whose runs predate the white_C0 field.
    缺 white_C0 时跳过成对检查，回退到单 run 标签判定。"""
    historical_no_params = {
        # Minimal legacy run shape: only the bare-minimum fields.
        "captured_at": "2026-04-01T00:00:00+00:00",
    }
    fresh = _make_synthetic_run(white_c0=[0.85, 0.86, 0.87])
    selection = _select_runs_for_refit([historical_no_params, fresh])
    # Pairwise check skipped → historical survives.
    assert 0 in selection["selected_indices"]
    assert 1 in selection["selected_indices"]


def test_select_runs_pairwise_never_excludes_fresh_run() -> None:
    """Even if the FRESH run is the "outlier" (extreme white_C0
    relative to historicals), it must always be kept — the operator
    intentionally just captured it and needs to see it in the
    diagnostics. Historical runs are the only ones droppable by the
    pairwise rule.
    新 run 始终保留；成对比较只能剔除历史 run。"""
    # Three historicals clustered near 0.85, fresh at 0.34 (very dark).
    h1 = _make_synthetic_run(white_c0=[0.85, 0.85, 0.85])
    h2 = _make_synthetic_run(white_c0=[0.86, 0.86, 0.86])
    h3 = _make_synthetic_run(white_c0=[0.87, 0.87, 0.87])
    fresh_dark = _make_synthetic_run(white_c0=[0.34, 0.34, 0.34])
    selection = _select_runs_for_refit([h1, h2, h3, fresh_dark])
    assert selection["fresh_index"] == 3
    assert 3 in selection["selected_indices"]


# --- _aggregate_stage_a_runs integration tests --------------------------
#
# These tests exercise the aggregator + selection wiring directly with
# hand-crafted ``verification_runs``, bypassing the full Stage A pipeline.
# The end-to-end synthetic gradient card capture spuriously triggers
# ``orientation_unreliable`` on every run (small grids confuse the
# orientation ranker), which would mask the bias filter under test. By
# constructing runs ourselves we get clean control over which bias flags
# fire so the selection contract is verifiable.


def _minimal_params_payload() -> dict:
    return {
        "meta": {},
        "parameters": {
            "channels": [
                {
                    "channel_index": 0,
                    "color_name": "PLA Basic",
                    "E": [0.22, 0.18, 0.15],
                    "k": [1.7, 1.4, 1.2],
                }
            ],
            "substrates": [
                {"substrate_idx": 0, "substrate_id": "white", "C0": [0.88, 0.88, 0.88]},
                {"substrate_idx": 1, "substrate_id": "black", "C0": [0.05, 0.05, 0.05]},
            ],
        },
    }


def _minimal_fit_summary() -> dict:
    return {
        "substrate_count": 2,
        "channel_count": 1,
        "substrates": ["black", "white"],
        "colors": ["PLA Basic"],
        "overall_validation": {
            "mean_delta_e": 1.0,
            "max_delta_e": 2.0,
            "rmse_linear": 0.01,
        },
        "warnings": [],
    }


def _minimal_material_summary() -> dict:
    return {
        "estimated_rgb": [200, 100, 100],
        "estimated_k": [1.7, 1.4, 1.2],
        "white_zero_rgb": [255, 255, 255],
        "black_zero_rgb": [0, 0, 0],
    }


def test_aggregate_drops_high_c0_white_historical_when_fresh_is_clean() -> None:
    """A historical run flagged for ``c0_white_avg > 0.95`` must be dropped
    from the joint refit when the fresh run is clean; ``selected_indices``
    contains the fresh run only. Cross-checked end-to-end via the full
    aggregator so the selection metadata also flows into the output."""
    historical = _make_synthetic_run(
        white_c0=[0.97, 0.98, 0.99],
        fit_samples=_make_synthetic_samples(
            white_substrate=[0.97, 0.98, 0.99],
            black_substrate=[0.05, 0.05, 0.05],
        ),
    )
    fresh = _make_synthetic_run(
        white_c0=[0.86, 0.88, 0.9],
        fit_samples=_make_synthetic_samples(
            white_substrate=[0.86, 0.88, 0.9],
            black_substrate=[0.05, 0.05, 0.05],
        ),
    )
    runs = [historical, fresh]
    params, fit, msum = _aggregate_stage_a_runs(
        material_name="PLA Basic",
        params_payload=_minimal_params_payload(),
        fit_summary=_minimal_fit_summary(),
        material_summary=_minimal_material_summary(),
        verification_runs=runs,
    )
    selection = params["meta"]["selection"]
    assert selection["selected_indices"] == [1]
    assert [entry["index"] for entry in selection["excluded_runs"]] == [0]
    assert selection["excluded_runs"][0]["reason"] == "bias_filter"
    assert _BIAS_FLAG_C0_WHITE_HIGH in selection["excluded_runs"][0]["bias_flags"]
    # ``selected_run_count`` propagates so downstream UIs can render
    # "1 of 2 runs used" without re-evaluating the selection.
    assert msum["selected_run_count"] == 1
    assert msum["verification_count"] == 2
    assert fit["overall_validation"]["selected_run_count"] == 1


def test_aggregate_keeps_least_biased_historical_when_all_flagged() -> None:
    """Graceful degradation: when every historical run is flagged, the
    least-flagged one survives so the joint refit still has more than
    the fresh run alone. Severely flagged historicals are excluded with
    explicit reasons in ``aggregation.selection.excluded_runs``."""
    severely_biased = _make_synthetic_run(
        white_c0=[0.99, 0.99, 0.99],  # c0_white flag
        image_source="restored",       # restored flag
        flat_white=True,               # flat flag → 3 flags total
        fit_samples=_make_synthetic_samples(
            white_substrate=[0.99, 0.99, 0.99],
            black_substrate=[0.05, 0.05, 0.05],
        ),
    )
    mildly_biased = _make_synthetic_run(
        white_c0=[0.86, 0.88, 0.9],
        image_source="restored",       # 1 flag
        fit_samples=_make_synthetic_samples(
            white_substrate=[0.86, 0.88, 0.9],
            black_substrate=[0.05, 0.05, 0.05],
        ),
    )
    fresh = _make_synthetic_run(
        white_c0=[0.86, 0.88, 0.9],
        image_source="restored",       # 1 flag
        fit_samples=_make_synthetic_samples(
            white_substrate=[0.86, 0.88, 0.9],
            black_substrate=[0.05, 0.05, 0.05],
        ),
    )
    runs = [severely_biased, mildly_biased, fresh]
    params, _fit, _msum = _aggregate_stage_a_runs(
        material_name="PLA Basic",
        params_payload=_minimal_params_payload(),
        fit_summary=_minimal_fit_summary(),
        material_summary=_minimal_material_summary(),
        verification_runs=runs,
    )
    selection = params["meta"]["selection"]
    assert 2 in selection["selected_indices"]  # fresh always kept
    assert 1 in selection["selected_indices"]  # least-biased historical kept
    assert 0 not in selection["selected_indices"]
    excluded_indices = sorted(entry["index"] for entry in selection["excluded_runs"])
    assert excluded_indices == [0]


def test_score_run_bias_handles_minimal_legacy_run_without_crashing() -> None:
    """Pre-1.0 archives stored verification_runs with ONLY ``params``;
    later schema additions (``samples``, ``source.image_source``,
    ``fit_summary.orientation_ranking``) may be absent. The bias scorer
    must treat every absent field as "no flag" rather than KeyError —
    legacy archives are not penalized for fields that did not exist
    when they were captured.
    最小遗留 run（只含 params）必须无报错地拿到 0 个 flag。
    """
    minimal_legacy_run = {
        "params": {
            "E": [0.22, 0.18, 0.15],
            "k": [1.7, 1.4, 1.2],
            "white_C0": [0.86, 0.88, 0.9],
            "black_C0": [0.05, 0.05, 0.05],
        },
    }
    score = _score_run_bias(minimal_legacy_run)
    assert score["bias_flag_count"] == 0
    assert score["bias_flags"] == []
    assert score["structural_flag_count"] == 0
    assert score["image_source"] is None


def test_select_runs_treats_minimal_legacy_run_as_clean_against_fresh() -> None:
    """A real-world re-verification scenario: the user opens a
    materials archive that was saved long before today's bias-filter
    work (so the historical run lacks ``samples``, ``image_source``,
    and ``orientation_ranking``) and adds a fresh capture. The
    historical run must survive the structural filter so the joint
    refit can use both data points; only fresh-run-driven exclusions
    should kick in.
    重新校准旧档案：历史 run 信息不全也必须留住，只看新捕获的实际偏置。
    """
    minimal_legacy_run = {
        "params": {
            "E": [0.22, 0.18, 0.15],
            "k": [1.7, 1.4, 1.2],
            "white_C0": [0.84, 0.86, 0.88],
            "black_C0": [0.05, 0.05, 0.05],
        },
    }
    fresh = _make_synthetic_run(white_c0=[0.85, 0.86, 0.87])
    selection = _select_runs_for_refit([minimal_legacy_run, fresh])
    assert selection["selected_indices"] == [0, 1]
    assert selection["excluded_runs"] == []
    # Both runs surface in run_scores so the UI diagnostic still has a
    # complete view (no silent drops).
    assert len(selection["run_scores"]) == 2


def test_aggregate_minimal_legacy_run_plus_fresh_run_does_not_crash() -> None:
    """End-to-end backward compatibility: re-verifying a pre-1.0 archive
    where the historical run only carries ``params`` (no ``samples``,
    no ``source.image_source``, no ``orientation_ranking``) plus a
    fresh raw capture must run :func:`_aggregate_stage_a_runs` without
    any KeyError, fall back to the parameter-mean path (because the
    legacy run lacks per-cell samples), and surface BOTH runs in the
    selection diagnostic.
    最小遗留 + 新捕获的 E2E 兼容性：聚合不报错、回退到 mean、诊断里两个
    run 都可见。
    """
    minimal_legacy_run = {
        "params": {
            "E": [0.22, 0.18, 0.15],
            "k": [1.7, 1.4, 1.2],
            "white_C0": [0.84, 0.86, 0.88],
            "black_C0": [0.05, 0.05, 0.05],
        },
    }
    fresh = _make_synthetic_run(
        white_c0=[0.85, 0.86, 0.87],
        image_source="raw",
        # Note: no fit_samples on fresh either to keep the assertion
        # firmly on the mean-fallback branch the legacy run forces.
    )
    params, fit, msum = _aggregate_stage_a_runs(
        material_name="PLA Basic",
        params_payload=_minimal_params_payload(),
        fit_summary=_minimal_fit_summary(),
        material_summary=_minimal_material_summary(),
        verification_runs=[minimal_legacy_run, fresh],
    )
    # Mean-fallback because at least one run lacks samples; this also
    # exercises the legacy code path that real archives saved long
    # before today still hit when the user adds a verification.
    assert fit["overall_validation"]["aggregation_method"] == "mean"
    selection = params["meta"]["selection"]
    assert sorted(selection["selected_indices"]) == [0, 1]
    assert selection["excluded_runs"] == []
    assert len(selection["run_scores"]) == 2
    assert selection["run_scores"][0]["bias_flag_count"] == 0
    assert selection["run_scores"][1]["bias_flag_count"] == 0


def test_aggregate_legacy_run_without_samples_still_applies_bias_filter() -> None:
    """Legacy archives (no ``samples`` block) must still pass through the
    bias filter so the parameter-mean fallback averages only over
    bias-clean runs. Before this change, the fallback path silently
    included biased legacy runs in the average.
    """
    biased_legacy = _make_synthetic_run(
        white_c0=[0.97, 0.98, 0.99],
        # No fit_samples → forces the aggregator into the mean-fallback
        # path, but the bias filter still inspects the run's params.
    )
    fresh_clean = _make_synthetic_run(
        white_c0=[0.86, 0.88, 0.9],
        # fresh also lacks samples so the aggregator stays in mean-fallback
    )
    runs = [biased_legacy, fresh_clean]
    params, fit, msum = _aggregate_stage_a_runs(
        material_name="PLA Basic",
        params_payload=_minimal_params_payload(),
        fit_summary=_minimal_fit_summary(),
        material_summary=_minimal_material_summary(),
        verification_runs=runs,
    )
    assert fit["overall_validation"]["aggregation_method"] == "mean"
    selection = params["meta"]["selection"]
    assert selection["selected_indices"] == [1]
    assert selection["excluded_runs"][0]["index"] == 0
    assert _BIAS_FLAG_C0_WHITE_HIGH in selection["excluded_runs"][0]["bias_flags"]
    # The mean-fallback now averages only over the fresh (clean) run, so
    # the aggregated white_C0 must reflect run[1]'s value, NOT the
    # arithmetic mean of run[0] (biased) and run[1] (clean).
    parameters = params["parameters"]
    white_substrate = next(
        sub for sub in parameters["substrates"] if sub["substrate_id"] == "white"
    )
    fresh_white_c0_mean = float(np.mean([0.86, 0.88, 0.9]))
    assert abs(float(np.mean(white_substrate["C0"])) - fresh_white_c0_mean) < 0.01


# --- Persistence E2E (relies on synthetic extract pipeline) -------------


def test_aggregate_persists_selection_block_to_archive(tmp_path: Path) -> None:
    """Smoke-level E2E: the saved archive must contain the full
    ``aggregation.selection`` diagnostic block (including ``run_scores``
    and ``selection_strategy``). Asserts only the structural contract
    so the test is robust against the synthetic extract pipeline's
    spurious orientation flags."""
    spec = _make_spec()
    materials_root = tmp_path / "materials"

    first = _extract_run(
        tmp_path, spec, noise_seed=51, suffix="persist1", image_source="raw",
    )
    save_first = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=first.params_payload,
        fit_summary=first.fit_summary,
        source_summary=first.source_summary,
        material_summary=first.material_summary,
        materials_dir=str(materials_root),
    )
    second = _extract_run(
        tmp_path, spec, noise_seed=53, suffix="persist2", image_source="raw",
    )
    save_second = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=second.params_payload,
        fit_summary=second.fit_summary,
        source_summary=second.source_summary,
        material_summary=second.material_summary,
        materials_dir=str(materials_root),
        existing_directory_name=save_first.material_summary["directory_name"],
    )

    archive = json.loads(Path(save_second.archive_path).read_text(encoding="utf-8"))
    selection = archive["aggregation"]["selection"]
    assert selection["selection_strategy"] in {
        "bias_filter_v1",
        "bias_filter_v1+cross_val",
    }
    assert isinstance(selection["selected_indices"], list)
    assert selection["fresh_index"] == 1
    run_scores = selection["run_scores"]
    assert len(run_scores) == 2
    for entry in run_scores:
        assert "bias_flag_count" in entry
        assert "bias_flags" in entry
        assert "is_fresh" in entry
        assert "white_c0_avg" in entry
    # Saved stage_A_parameters.json mirrors the same block under meta.
    saved_payload = json.loads(
        Path(save_second.stage_a_params_path).read_text(encoding="utf-8")
    )
    assert (
        saved_payload["meta"]["selection"]["selection_strategy"]
        == selection["selection_strategy"]
    )
