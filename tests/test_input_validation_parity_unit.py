"""s01/p01 input-validation parity tests (Phase 0 Sub-PR C).
s01/p01 输入验证契约测试（Phase 0 Sub-PR C）。

These tests pin the behaviour of the shared helpers extracted into
``core/pipeline/_input_validation_common.py`` so future refactors cannot
silently drift either S01 or P01 away from the intended common behaviour.

Coverage:
- ``_clamp_quantize_colors`` clamps to [8, 8192] inclusive (matches the
  API schema ``le=8192`` and the frontend unlock slider ceiling).
- ``_resolve_lut_path_or_error`` accepts str / file-like / None and rejects
  the rest with the canonical error message.
- ``_apply_material_archive_branch`` writes the canonical key set into ctx,
  uses the caller's ``event_prefix`` (so s01 keeps emitting
  ``s01_material_archive_validated`` and p01 keeps emitting
  ``p01_material_archive_validated``), and clamps unsupported
  ``material_grid_resolution`` values back to default.
- S01 and P01 produce the same ``actual_lut_path`` for a given LUT path
  format (string vs file-like).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _clamp_quantize_colors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 8),
        (1, 8),
        (7, 8),
        (8, 8),
        (32, 32),
        (256, 256),
        (257, 257),
        (1024, 1024),
        (8192, 8192),
        (8193, 8192),
        (10_000, 8192),
    ],
)
def test_clamp_quantize_colors_pins_range(value: int, expected: int) -> None:
    """量化颜色数必须夹紧到 [8, 8192]，与 API schema 及前端解锁滑条上限对齐。"""
    from core.pipeline._input_validation_common import _clamp_quantize_colors

    assert _clamp_quantize_colors(value) == expected


# ---------------------------------------------------------------------------
# _resolve_lut_path_or_error
# ---------------------------------------------------------------------------


def test_resolve_lut_path_or_error_string() -> None:
    """str 路径 -> 直接返回。"""
    from core.pipeline._input_validation_common import _resolve_lut_path_or_error

    path, err = _resolve_lut_path_or_error(
        {"lut_path": "/tmp/x.npy"},
        error_prefix="[WARNING] Please select or upload",
    )
    assert path == "/tmp/x.npy"
    assert err is None


def test_resolve_lut_path_or_error_file_like_with_name() -> None:
    """file-like (具备 .name 属性) -> 取 .name。"""
    from core.pipeline._input_validation_common import _resolve_lut_path_or_error

    class FakeFile:
        name = "/tmp/upload.json"

    path, err = _resolve_lut_path_or_error(
        {"lut_path": FakeFile()},
        error_prefix="[WARNING] x",
    )
    assert path == "/tmp/upload.json"
    assert err is None


def test_resolve_lut_path_or_error_none() -> None:
    """None -> 返回 (None, error_prefix)。"""
    from core.pipeline._input_validation_common import _resolve_lut_path_or_error

    path, err = _resolve_lut_path_or_error(
        {"lut_path": None},
        error_prefix="[WARNING] Please select or upload calibration file",
    )
    assert path is None
    assert err == "[WARNING] Please select or upload calibration file"


def test_resolve_lut_path_or_error_invalid_object() -> None:
    """既不是 str 又没有 .name -> 返回 (None, '[ERROR] Invalid LUT file format')。"""
    from core.pipeline._input_validation_common import _resolve_lut_path_or_error

    path, err = _resolve_lut_path_or_error(
        {"lut_path": 12345},
        error_prefix="[WARNING] x",
    )
    assert path is None
    assert err == "[ERROR] Invalid LUT file format"


# ---------------------------------------------------------------------------
# _apply_material_archive_branch event-prefix preservation
# ---------------------------------------------------------------------------


def _fake_load_multiple_materials(names):
    """Stub used by the parity tests to avoid loading real material profiles."""
    return [{"name": n, "channel": idx} for idx, n in enumerate(names)]


def _fake_build_material_slot_names(materials):
    return [m["name"] for m in materials]


def _fake_build_material_preview_colors(materials):
    # Bright deterministic palette so downstream key checks are easy.
    return {idx: [0, 128, 255, 255] for idx in range(len(materials))}


@pytest.mark.parametrize(
    ("event_prefix", "expected_event"),
    [
        ("s01", "s01_material_archive_validated"),
        ("p01", "p01_material_archive_validated"),
    ],
)
def test_material_archive_branch_uses_event_prefix(
    event_prefix: str,
    expected_event: str,
) -> None:
    """material_archive 验证事件必须带上调用方的前缀。
    Material-archive validated event must carry the caller's prefix so the
    governance whitelist (s01_* vs p01_*) keeps matching.
    """
    from core.pipeline import _input_validation_common as common

    # Use a Mock logger so we can inspect the exact ``extra={...}`` payload
    # passed to ``log.debug``. The structured_logging wrapper renames events
    # on non-lumina-prefixed loggers when records propagate to root, which
    # makes ``caplog``-based assertions brittle here.
    log = MagicMock(spec=logging.Logger)

    with patch.object(common, "load_materials", _fake_load_multiple_materials), \
         patch.object(common, "build_material_slot_names", _fake_build_material_slot_names), \
         patch.object(common, "build_material_preview_colors", _fake_build_material_preview_colors):
        ctx: dict = {
            "selected_materials": ["mat_red", "mat_blue"],
            "material_layer_count": 6,
            "material_layer_height_mm": 0.10,
        }
        outcome = common._apply_material_archive_branch(
            ctx,
            log=log,
            event_prefix=event_prefix,
        )

    assert outcome == "validated"

    # Inspect the ``extra={"event": ...}`` payload of every log.debug call.
    debug_events: list[str | None] = []
    for call in log.debug.call_args_list:
        extra = call.kwargs.get("extra") or {}
        debug_events.append(extra.get("event"))
    assert expected_event in debug_events, (
        f"Expected `{expected_event}` to be emitted under prefix `{event_prefix}`; "
        f"got {debug_events}"
    )

    # Canonical keys present.
    assert ctx["actual_lut_path"] == "__material_archive__"
    assert ctx["material_source"] == "material_archive"
    assert ctx["color_layers"] == 6
    assert ctx["layer_height_mm"] == pytest.approx(0.10)
    assert ctx["color_conf"]["name"] == "Material"
    assert ctx["slot_names"] == ["mat_red", "mat_blue"]


def test_material_archive_branch_empty_selection_writes_error() -> None:
    """``selected_materials`` 为空 -> 写 ctx['error'] 并返回 'error'。"""
    from core.pipeline import _input_validation_common as common

    log = logging.getLogger("lumina.test.empty")
    ctx: dict = {"selected_materials": []}
    outcome = common._apply_material_archive_branch(
        ctx,
        log=log,
        event_prefix="s01",
    )
    assert outcome == "error"
    assert "No materials selected" in ctx["error"]


def test_material_archive_branch_unsupported_grid_falls_back() -> None:
    """不支持的 ``material_grid_resolution`` -> 回落到默认并打 warning。"""
    from core.material_cache import DEFAULT_GRID_RESOLUTION
    from core.pipeline import _input_validation_common as common

    log = MagicMock(spec=logging.Logger)

    with patch.object(common, "load_materials", _fake_load_multiple_materials), \
         patch.object(common, "build_material_slot_names", _fake_build_material_slot_names), \
         patch.object(common, "build_material_preview_colors", _fake_build_material_preview_colors):
        ctx: dict = {
            "selected_materials": ["mat_red"],
            "material_grid_resolution": 9999,  # not in ALLOWED_GRID_RESOLUTIONS
        }
        common._apply_material_archive_branch(
            ctx,
            log=log,
            event_prefix="p01",
        )
    assert ctx["grid_resolution"] == int(DEFAULT_GRID_RESOLUTION)
    # Helper must emit a single warning whose first positional arg contains
    # the canonical "ignoring unsupported" phrase.
    assert log.warning.called
    warning_args = log.warning.call_args[0]
    assert any("ignoring unsupported" in str(arg) for arg in warning_args)


# ---------------------------------------------------------------------------
# Cross-module parity: s01 + p01 LUT path resolution agrees
# ---------------------------------------------------------------------------


def test_s01_and_p01_resolve_lut_path_identically_for_string() -> None:
    """s01 与 p01 在给定字符串 LUT 路径时必须解析出相同的 actual_lut_path。
    s01 and p01 must resolve identical actual_lut_path for the same string
    input — pinning that the shared helper is wired into both modules.
    """
    from core.pipeline import s01_input_validation, p01_preview_validation

    # Both modules import _resolve_lut_path_or_error from the common module —
    # asserting the import binding exists is enough; behaviour is locked by
    # the helper-direct tests above.
    assert hasattr(s01_input_validation, "_resolve_lut_path_or_error")
    assert hasattr(p01_preview_validation, "_resolve_lut_path_or_error")
    assert (
        s01_input_validation._resolve_lut_path_or_error
        is p01_preview_validation._resolve_lut_path_or_error
    )
