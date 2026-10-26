"""Regression for the cross-material session-level white_C0 consistency check.
跨材料 session 级白底一致性检查（Layer 1.7）的回归测试。

The selection pipeline runs four layers in order:

1. **Bias filter** — drops historicals that carry strictly more
   structural flags than the fresh run.
2. **Pairwise C0 mismatch vs fresh** — drops historicals whose
   ``white_C0`` average differs from the fresh run's by more than 1.5×.
3. **Cross-validation** — N>=3 → keep the top-half-by-RMSE.
4. **Session-level C0 consistency** (this layer) — uses the *median
   ``white_C0`` of OTHER materials in the same session* as an objective
   reference; any selected run (including the fresh one) whose
   per-channel deviation exceeds the absolute or relative threshold is
   excluded with reason ``"c0_session_outlier"``.

This last layer is intentionally *not* fresh-canonical: a wrong white
substrate sample cannot be salvaged by force-keeping, because the
resulting (E, k) would absorb the lighting offset and bias every
downstream multi-material colour prediction. The earlier layers stay
fresh-canonical because comparing within a single material is
inherently subjective; the session median provides an objective
physical reference.

These tests pin down:

- The pure helpers (``_parse_iso_datetime``,
  ``_compute_session_white_c0_reference``,
  ``_check_run_against_session_c0``).
- The integration of the new layer into ``_select_runs_for_refit``
  (legacy ``None`` reference → no behaviour change; fresh outlier →
  fresh dropped; historical outlier → historical dropped; both clean
  → both kept).
- End-to-end integration through ``save_stage_a_material_archive``
  with a real on-disk materials root containing a sibling material
  whose ``white_C0`` anchors the session median.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from core.single_stage.material_runs import (
    _BIAS_FLAG_C0_SESSION_OUTLIER,
    _C0_SESSION_OUTLIER_ABS_THRESHOLD,
    _C0_SESSION_WINDOW_HOURS,
    _check_run_against_session_c0,
    _collect_session_white_c0_samples,
    _compute_session_white_c0_reference,
    _parse_iso_datetime,
    _select_runs_for_refit,
)


# ---------------------------------------------------------------------------
# Helpers (synthetic verification runs and on-disk material archives)
# ---------------------------------------------------------------------------


def _make_run(
    *,
    white_c0: list[float],
    captured_at: str = "2026-04-30T04:00:00+00:00",
    image_source: str | None = "raw",
    mean_delta_e: float = 2.0,
) -> dict[str, Any]:
    """Minimal verification_run dict for selection-layer unit tests."""
    return {
        "captured_at": captured_at,
        "params": {
            "E": [0.22, 0.18, 0.15],
            "k": [1.7, 1.4, 1.2],
            "white_C0": list(white_c0),
            "black_C0": [0.05, 0.05, 0.05],
        },
        "fit_summary": {
            "overall_validation": {
                "mean_delta_e": mean_delta_e,
                "max_delta_e": max(4.0, mean_delta_e * 2.0),
                "rmse_linear": 0.02,
            },
            "orientation_ranking": {
                "orientation_reliable": True,
                "white_orientation_info": {"flat": False},
                "black_orientation_info": {"flat": False},
            },
            "warnings": [],
        },
        "material_summary": {"estimated_rgb": [200, 100, 100]},
        "source": (
            {"image_source": image_source} if image_source is not None else {}
        ),
    }


def _write_material_archive(
    materials_root: Path,
    *,
    directory: str,
    runs: list[dict[str, Any]],
    image_source: str | None = "raw",
) -> Path:
    """Write a minimal but schema-faithful material.json on disk."""
    material_dir = materials_root / directory
    material_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.1",
        "material_name": directory,
        "verification_count": len(runs),
        "verification_runs": runs,
        "aggregation": {
            "image_source": image_source,
        },
    }
    archive_path = material_dir / "material.json"
    archive_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return material_dir


# ---------------------------------------------------------------------------
# _parse_iso_datetime
# ---------------------------------------------------------------------------


def test_parse_iso_datetime_handles_offset_and_z_suffix():
    """Both '+00:00' and 'Z' suffixes parse to UTC-aware datetimes.
    两种后缀都解析为带时区的 datetime。"""
    a = _parse_iso_datetime("2026-04-30T04:26:47.155883+00:00")
    b = _parse_iso_datetime("2026-04-30T04:26:47.155883Z")
    assert a is not None and b is not None
    assert a == b
    assert a.tzinfo is not None


def test_parse_iso_datetime_returns_none_for_invalid_inputs():
    """Non-strings and malformed strings return None, not raise.
    非字符串和畸形字符串返回 None，不抛异常。"""
    for bad in (None, "", "   ", "not a date", 12345, ["2026-04-30"]):
        assert _parse_iso_datetime(bad) is None


def test_parse_iso_datetime_naive_input_assumed_utc():
    """Timezone-naive ISO strings are treated as UTC for window math.
    无时区的 ISO 字符串按 UTC 处理，便于窗口计算。"""
    parsed = _parse_iso_datetime("2026-04-30T04:00:00")
    assert parsed is not None
    assert parsed.tzinfo is timezone.utc


# ---------------------------------------------------------------------------
# _collect_session_white_c0_samples
# ---------------------------------------------------------------------------


def test_collect_session_skips_self_and_filters_by_image_source(tmp_path):
    """Self-directory excluded; image_source mismatch excludes the run."""
    skin_dir = _write_material_archive(
        tmp_path,
        directory="skin",
        runs=[
            _make_run(
                white_c0=[0.880, 0.917, 0.823],
                image_source="raw",
            )
        ],
    )
    _write_material_archive(
        tmp_path,
        directory="restored_red",
        runs=[
            _make_run(
                white_c0=[0.500, 0.500, 0.500],
                image_source="restored",
            )
        ],
    )
    captured_at = _parse_iso_datetime("2026-04-30T04:00:00+00:00")
    raw_samples = _collect_session_white_c0_samples(
        tmp_path,
        image_source="raw",
        captured_at=captured_at,
        exclude_directory=skin_dir,
    )
    # Skin is excluded by exclude_directory; restored_red is excluded by
    # image_source mismatch → no samples remain. (skin 自排除；restored
    # 因来源不匹配排除)
    assert raw_samples == []


def test_collect_session_respects_window(tmp_path):
    """Captures outside the time window are skipped.
    超出时间窗口的捕获被跳过。"""
    inside = "2026-04-30T03:00:00+00:00"
    outside = "2026-04-15T03:00:00+00:00"  # 15 days earlier
    _write_material_archive(
        tmp_path,
        directory="inside",
        runs=[_make_run(white_c0=[0.88, 0.92, 0.82], captured_at=inside)],
    )
    _write_material_archive(
        tmp_path,
        directory="outside",
        runs=[_make_run(white_c0=[0.55, 0.55, 0.55], captured_at=outside)],
    )
    samples = _collect_session_white_c0_samples(
        tmp_path,
        image_source="raw",
        captured_at=_parse_iso_datetime("2026-04-30T04:00:00+00:00"),
        window_hours=24.0,
    )
    assert len(samples) == 1
    assert samples[0]["white_C0"] == [0.88, 0.92, 0.82]


def test_collect_session_handles_missing_root_gracefully(tmp_path):
    """Missing materials_root returns empty list, not raises.
    materials_root 不存在时返回空列表，不抛异常。"""
    result = _collect_session_white_c0_samples(
        tmp_path / "does_not_exist",
        image_source="raw",
        captured_at=None,
    )
    assert result == []


# ---------------------------------------------------------------------------
# _compute_session_white_c0_reference
# ---------------------------------------------------------------------------


def test_compute_session_reference_returns_none_with_no_samples(tmp_path):
    """No qualifying samples → None (signals 'skip the layer').
    无可用样本时返回 None（selection 层会跳过）。"""
    ref = _compute_session_white_c0_reference(
        tmp_path,
        image_source="raw",
        captured_at_iso="2026-04-30T04:00:00+00:00",
    )
    assert ref is None


def test_compute_session_reference_per_channel_median(tmp_path):
    """Per-channel median is computed across multiple sibling materials.
    跨多个兄弟材料按通道独立取中位数。"""
    for idx, c0 in enumerate(
        [
            [0.85, 0.90, 0.80],
            [0.88, 0.92, 0.82],
            [0.91, 0.94, 0.84],  # median row when sorted per channel
        ]
    ):
        _write_material_archive(
            tmp_path,
            directory=f"mat_{idx}",
            runs=[_make_run(white_c0=c0)],
        )
    ref = _compute_session_white_c0_reference(
        tmp_path,
        image_source="raw",
        captured_at_iso="2026-04-30T04:00:00+00:00",
    )
    assert ref is not None
    assert ref["sample_count"] == 3
    # Median of [0.85, 0.88, 0.91] = 0.88; [0.90, 0.92, 0.94] = 0.92;
    # [0.80, 0.82, 0.84] = 0.82
    assert ref["median"] == pytest.approx([0.88, 0.92, 0.82])
    assert ref["abs_threshold"] == _C0_SESSION_OUTLIER_ABS_THRESHOLD
    assert ref["window_hours"] == _C0_SESSION_WINDOW_HOURS


# ---------------------------------------------------------------------------
# _check_run_against_session_c0
# ---------------------------------------------------------------------------


def test_check_run_within_threshold_returns_none():
    """A run within both thresholds returns None (no outlier).
    通过阈值返回 None。"""
    reference = {
        "median": [0.88, 0.92, 0.82],
        "sample_count": 3,
        "abs_threshold": 0.05,
        "rel_threshold": 0.05,
    }
    run = _make_run(white_c0=[0.879, 0.918, 0.823])  # within 0.005 abs
    assert _check_run_against_session_c0(run, reference) is None


def test_check_run_beyond_abs_threshold_flags_outlier():
    """Run whose channel exceeds abs threshold returns diagnostic dict.
    超出绝对阈值返回诊断字典。"""
    reference = {
        "median": [0.88, 0.92, 0.82],
        "sample_count": 3,
        "abs_threshold": 0.05,
        "rel_threshold": 0.05,
    }
    # The yellow-bug-reproduction case: white_C0 ~0.16 below the median.
    run = _make_run(white_c0=[0.71, 0.77, 0.71])
    diag = _check_run_against_session_c0(run, reference)
    assert diag is not None
    assert diag["run_white_c0"] == [0.71, 0.77, 0.71]
    assert diag["session_median"] == [0.88, 0.92, 0.82]
    assert diag["max_abs_diff"] == pytest.approx(0.17)
    assert diag["max_rel_diff"] > 0.05
    assert diag["sample_count"] == 3


# ---------------------------------------------------------------------------
# _select_runs_for_refit + session reference
# ---------------------------------------------------------------------------


def test_session_reference_none_preserves_legacy_selection():
    """Default ``session_white_c0_reference=None`` doesn't change behaviour.
    默认 None 时与旧逻辑等价（向后兼容关键）。"""
    runs = [
        _make_run(white_c0=[0.71, 0.77, 0.71]),  # historical (outlier vs session)
        _make_run(white_c0=[0.88, 0.92, 0.82]),  # fresh
    ]
    result = _select_runs_for_refit(runs)  # no session reference
    # Both kept (no Layer 1.7 active, no other rule trips on 0.71 vs 0.88
    # because pairwise ratio is 1.24x < 1.5x threshold)
    assert result["selected_indices"] == [0, 1]
    assert "session_c0" not in result["selection_strategy"]


def test_session_layer_excludes_historical_outlier():
    """Historical run with off-session white_C0 is excluded; fresh is kept.
    历史 run 白底偏离即排除；fresh 保留。"""
    runs = [
        _make_run(white_c0=[0.71, 0.77, 0.71]),  # outlier vs session median
        _make_run(white_c0=[0.88, 0.92, 0.82]),  # fresh, matches session
    ]
    reference = {
        "median": [0.88, 0.92, 0.82],
        "sample_count": 3,
        "abs_threshold": 0.05,
        "rel_threshold": 0.05,
    }
    result = _select_runs_for_refit(
        runs,
        session_white_c0_reference=reference,
    )
    assert result["selected_indices"] == [1]
    assert "session_c0" in result["selection_strategy"]
    excluded = [e for e in result["excluded_runs"] if e["index"] == 0]
    assert len(excluded) == 1
    assert excluded[0]["reason"] == "c0_session_outlier"
    assert _BIAS_FLAG_C0_SESSION_OUTLIER in excluded[0]["structural_flags"]
    assert excluded[0]["max_abs_diff"] == pytest.approx(0.17)
    # The run_scores diagnostic also carries the new flag so the UI
    # has a single source of truth. (run_scores 也带上新标签)
    score_for_outlier = next(
        s for s in result["run_scores"] if s["index"] == 0
    )
    assert _BIAS_FLAG_C0_SESSION_OUTLIER in score_for_outlier["structural_flags"]


def test_session_layer_excludes_fresh_outlier():
    """Fresh run is NOT force-kept by Layer 1.7 — wrong white reference
    cannot be salvaged. (fresh 在本层不享受强留)"""
    runs = [
        _make_run(white_c0=[0.88, 0.92, 0.82]),  # historical, OK
        _make_run(white_c0=[0.71, 0.77, 0.71]),  # fresh, outlier
    ]
    reference = {
        "median": [0.88, 0.92, 0.82],
        "sample_count": 3,
        "abs_threshold": 0.05,
        "rel_threshold": 0.05,
    }
    result = _select_runs_for_refit(
        runs,
        session_white_c0_reference=reference,
    )
    assert result["selected_indices"] == [0]
    assert result["fresh_index"] == 1  # diagnostic still surfaces fresh idx
    excluded = [e for e in result["excluded_runs"] if e["index"] == 1]
    assert len(excluded) == 1
    assert excluded[0]["reason"] == "c0_session_outlier"


def test_session_layer_excludes_all_when_all_outliers():
    """When every selected run is an outlier the result is empty.
    全部 run 都越界时返回空（aggregator 会落到 fallback）。"""
    runs = [
        _make_run(white_c0=[0.50, 0.55, 0.50]),
        _make_run(white_c0=[0.51, 0.54, 0.49]),
    ]
    reference = {
        "median": [0.88, 0.92, 0.82],
        "sample_count": 3,
        "abs_threshold": 0.05,
        "rel_threshold": 0.05,
    }
    result = _select_runs_for_refit(
        runs,
        session_white_c0_reference=reference,
    )
    assert result["selected_indices"] == []
    assert "session_c0" in result["selection_strategy"]
    assert len(result["excluded_runs"]) == 2


def test_session_layer_keeps_all_when_all_consistent():
    """No exclusions when every run is within tolerance.
    全在阈值内时不排除任何 run，selection_strategy 不带 session_c0 后缀。"""
    runs = [
        _make_run(white_c0=[0.879, 0.918, 0.823]),
        _make_run(white_c0=[0.882, 0.921, 0.821]),
    ]
    reference = {
        "median": [0.88, 0.92, 0.82],
        "sample_count": 3,
        "abs_threshold": 0.05,
        "rel_threshold": 0.05,
    }
    result = _select_runs_for_refit(
        runs,
        session_white_c0_reference=reference,
    )
    assert result["selected_indices"] == [0, 1]
    assert "session_c0" not in result["selection_strategy"]
    assert all(
        e["reason"] != "c0_session_outlier"
        for e in result["excluded_runs"]
    )


# ---------------------------------------------------------------------------
# End-to-end: yellow-bug reproduction with one sibling skin material
# ---------------------------------------------------------------------------


def test_yellow_bug_reproduction_excludes_outlier_historical(tmp_path):
    """Reproduces the actual yellow incident.

    Two PLA yellow runs: a 2026-04-16 historical with a clearly wrong
    white_C0 (~0.71 / 0.77 / 0.71) and a 2026-04-30 fresh with a
    correct one (~0.88 / 0.89 / 0.82). A sibling skin material in the
    same materials root anchors the session median near (0.88, 0.92,
    0.82). Without Layer 1.7 the bias filter and pairwise C0 layers
    cannot tell which yellow run is "right" because both are
    self-consistent and the pairwise ratio (~1.24×) is below the 1.5×
    threshold. With Layer 1.7 the historical is correctly excluded.
    复现实际黄色事件：两次黄 run 自洽且配对比 < 1.5×；引入肤色作为
    session 锚后，错的历史 run 被 Layer 1.7 正确排除。"""
    # Skin sibling — anchors the session median.
    _write_material_archive(
        tmp_path,
        directory="skin",
        runs=[
            _make_run(
                white_c0=[0.880, 0.917, 0.823],
                captured_at="2026-04-30T03:00:00+00:00",
            )
        ],
    )

    yellow_runs = [
        _make_run(
            white_c0=[0.710, 0.766, 0.715],  # bad historical (run 0)
            captured_at="2026-04-30T03:30:00+00:00",
            mean_delta_e=2.58,  # low δE on its own biased reference
        ),
        _make_run(
            white_c0=[0.880, 0.888, 0.823],  # correct fresh (run 1)
            captured_at="2026-04-30T04:00:00+00:00",
            mean_delta_e=7.72,
        ),
    ]
    yellow_dir = tmp_path / "yellow"
    yellow_dir.mkdir()  # exclude_directory must exist for Path.resolve

    reference = _compute_session_white_c0_reference(
        tmp_path,
        image_source="raw",
        captured_at_iso="2026-04-30T04:00:00+00:00",
        exclude_directory=yellow_dir,
    )
    assert reference is not None
    assert reference["sample_count"] == 1  # only skin contributes
    assert reference["median"] == [0.88, 0.917, 0.823]

    result = _select_runs_for_refit(
        yellow_runs,
        session_white_c0_reference=reference,
    )
    # Historical excluded; fresh kept.
    assert result["selected_indices"] == [1]
    excluded = [e for e in result["excluded_runs"] if e["index"] == 0]
    assert len(excluded) == 1
    assert excluded[0]["reason"] == "c0_session_outlier"


# ---------------------------------------------------------------------------
# Edge case: session reference disables itself when reference shape is wrong
# ---------------------------------------------------------------------------


def test_check_run_returns_none_when_reference_is_malformed():
    """Defensive: malformed reference dict short-circuits to None.
    防御性：参考字典格式异常时短路返回 None，不抛异常。"""
    run = _make_run(white_c0=[0.50, 0.50, 0.50])
    for bad_reference in (
        {"median": [0.88, 0.92]},  # wrong length
        {"median": "not a list"},  # wrong type
        {},  # missing key
    ):
        assert _check_run_against_session_c0(run, bad_reference) is None
