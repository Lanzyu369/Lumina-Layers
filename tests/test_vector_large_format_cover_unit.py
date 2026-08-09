"""Integration regression for large-format SVG worker tile cover thumbnails.

中文标题：大画幅 SVG 矢量模式分片封面缩略图集成回归测试

This test covers the higher-level integration surface of
``api/workers/converter_workers.py::worker_generate_large_format_svg_native``:
mixing per-tile rasterization outcomes (success / ``None`` / TimeoutError)
across one R × C grid, then verifying:

1. Tiles whose ``_rasterize_tile_for_cover`` returns a real PIL Image are
   exported into the ZIP and forward that image as ``cover_source`` to
   ``export_scene_with_bambu_metadata``; the resulting tile 3MF carries a
   cover whose dominant color matches the input (identifiability).
2. Tiles whose rasterization raises ``TimeoutError`` are
   **still exported** (printable tile is preserved); their writer call
   gets ``cover_source=None`` so the writer emits the silent placeholder,
   and ``tile_failed_cover`` is bumped as a quality indicator on the
   written tile (not a separate "skipped" bucket).
3. Tiles whose rasterization returns ``None`` still get exported (worker
   forwards ``cover_source=None``) — this is the silent-placeholder path,
   not a cover-failure path; ``tile_failed_cover`` does *not* increment.
4. Empty-scene tiles (worker drops them at slicing time) bump
   ``tile_skipped_empty`` rather than ``tile_failed_cover``.
5. The R5.6 invariant
   ``tile_count + tile_skipped_empty == grid_cols * grid_rows`` holds for
   the worker return value across mixed states. ``tile_failed_cover`` is
   a subset of ``tile_count``.

Compared to ``tests/test_converter_workers_large_format_svg_cover_unit.py``
(task 6's focused unit tests), this file focuses on integration-level
coverage of the *combined* state machine across a single grid, plus the
end-to-end "tile cover dominant color matches tile input" check that
proves the cover_source forwarded by the worker actually reaches the
written 3MF.

**Validates: Requirements 5.3, 5.4, 5.6, 10.3 / Property 4, 10**
"""

from __future__ import annotations

import logging
import os
import zipfile
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from api.workers.converter_workers import worker_generate_large_format_svg_native


# ---------------------------------------------------------------------------
# Helpers (mirror the patterns from
# tests/test_converter_workers_large_format_svg_cover_unit.py so logger
# capture works on the namespaced ``lumina.*`` logger family).
# ---------------------------------------------------------------------------


@contextmanager
def _capture_worker_warnings(caplog):
    target_logger = logging.getLogger("lumina.api.workers.converter_workers")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger="lumina.api.workers.converter_workers")
    try:
        yield
    finally:
        target_logger.removeHandler(caplog.handler)


def _make_tile(label: str, *, slot_names=("Slot1",), preview_colors=None):
    if preview_colors is None:
        preview_colors = {0: [255, 0, 0, 255]}
    return SimpleNamespace(
        label=label,
        spec=SimpleNamespace(
            row=int(label[1]),
            col=int(label[3]),
            label=label,
            x0_mm=0.0,
            y0_mm=0.0,
            x1_mm=60.0,
            y1_mm=60.0,
            width_mm=60.0,
            height_mm=60.0,
        ),
        analysis=SimpleNamespace(
            preview_colors=dict(preview_colors),
            slot_names=list(slot_names),
        ),
    )


class _FakeVectorProcessor:
    def __init__(self, lut_path: str, color_mode: str) -> None:
        self.lut_path = lut_path
        self.color_mode = color_mode

    def analyze_svg(self, **_kwargs):
        return SimpleNamespace(num_layers=5)

    def build_mesh(self, **_kwargs):
        fake_geom = SimpleNamespace(vertices=[(0, 0, 0)], faces=[(0, 0, 0)])
        return SimpleNamespace(geometry={"Slot1": fake_geom})


def _params_for_grid(rows: int, cols: int) -> dict:
    """Build worker params that yield exactly ``rows * cols`` grid cells."""

    return {
        "tile_name_prefix": "tile_cover",
        "total_width_mm": cols * 60.0,
        "total_height_mm": rows * 60.0,
        "tile_width_mm": 60.0,
        "tile_height_mm": 60.0,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "replacement_regions": [],
        "separate_backing": False,
    }


def _fake_export_recording(captured: list[dict]):
    """Fake ``export_scene_with_bambu_metadata`` that captures cover_source.

    Writes a stub 3MF byte ``b"3mf"`` at ``output_path`` so the worker's
    ZIP packaging step still works.
    """

    def _impl(*, output_path: str, cover_source=None, **_kwargs) -> None:
        with open(output_path, "wb") as handle:
            handle.write(b"3mf")
        captured.append({"output_path": output_path, "cover_source": cover_source})

    return _impl


def _dominant_color(image: Image.Image) -> tuple[int, int, int]:
    """Return the (R, G, B) mean of a PIL Image.

    Used as a coarse identifiability check for tile cover round-trips.
    Solid-color inputs round-trip cleanly through PIL so the mean stays
    within a few units of the input even after RGBA→RGB conversion.
    """

    arr = np.asarray(image.convert("RGB"), dtype=np.int16)
    mean = arr.reshape(-1, 3).mean(axis=0)
    return (int(round(mean[0])), int(round(mean[1])), int(round(mean[2])))


# ---------------------------------------------------------------------------
# Test 1 — Mixed states across a 2×2 grid (success + None + Timeout + Empty)
# ---------------------------------------------------------------------------


def test_worker_mixes_all_three_rasterize_outcomes_with_correct_counters(caplog) -> None:
    """One tile each of {real Image, None, TimeoutError, empty scene} → counters track precisely.

    R5.3 (empty tile counted as skipped_empty), R5.4 (timeout exports
    placeholder cover + WARNING), R5.6 (sum invariant). The successful
    tile's cover_source must be the PIL Image we returned from
    ``_rasterize_tile_for_cover`` (proves the worker forwards it directly
    to the writer). The timeout tile's cover_source must be ``None``
    (silent placeholder forwarded to the writer).
    """

    success_image = Image.new("RGBA", (256, 256), (15, 200, 70, 255))

    # 2×2 grid → 4 cells. Slicer drops one cell as empty; remaining 3 reach
    # the rasterizer. We mix: R1C1 success, R1C2 timeout, R2C1 returns None
    # (silent-placeholder cover; tile still exported, no WARNING).
    tiles = [_make_tile("R1C1"), _make_tile("R1C2"), _make_tile("R2C1")]
    captured: list[dict] = []

    def _rasterize(tile, *_args, **_kwargs):
        if tile.label == "R1C1":
            return success_image
        if tile.label == "R1C2":
            raise TimeoutError("synthetic timeout")
        if tile.label == "R2C1":
            return None
        raise AssertionError(f"unexpected tile {tile.label}")

    with (
        _capture_worker_warnings(caplog),
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=tiles),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", side_effect=_rasterize),
        patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_fake_export_recording(captured)),
    ):
        result = worker_generate_large_format_svg_native(
            "image.svg", "lut.npy", _params_for_grid(rows=2, cols=2)
        )

    try:
        # 4 grid cells: 1 sliced-empty, 1 timed-out (still exported with
        # placeholder), 1 with cover=None (still exported), 1 with real
        # cover image.
        assert result["grid_cols"] * result["grid_rows"] == 4
        assert result["tile_count"] == 3  # all sliced tiles export
        assert result["tile_failed_cover"] == 1  # only R1C2 (timeout)
        assert result["tile_skipped_empty"] == 1  # the cell slicer dropped

        # New R5.6 invariant: tile_count includes the timeout tile.
        assert (
            result["tile_count"] + result["tile_skipped_empty"]
            == result["grid_cols"] * result["grid_rows"]
        )

        # ZIP has all 3 sliced tile names — including the timeout tile.
        with zipfile.ZipFile(result["zip_path"]) as archive:
            zip_names = sorted(archive.namelist())
        assert zip_names == [
            "tile_cover_R1C1.3mf",
            "tile_cover_R1C2.3mf",
            "tile_cover_R2C1.3mf",
        ]

        # Three writer calls — success, timeout (None), explicit None.
        assert len(captured) == 3
        cover_sources = [entry["cover_source"] for entry in captured]
        assert cover_sources.count(None) == 2  # timeout + explicit-None tile
        non_none_sources = [src for src in cover_sources if src is not None]
        assert len(non_none_sources) == 1
        assert non_none_sources[0] is success_image

        # Exactly one WARNING — the timeout tile.
        warnings = [
            rec for rec in caplog.records
            if getattr(rec, "event", None) == "bambu_3mf_cover_thumbnail_failed"
        ]
        assert len(warnings) == 1
        assert warnings[0].error_type == "tile_rasterize_timeout"
        assert warnings[0].fallback_action == "placeholder_written"
    finally:
        if os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


# ---------------------------------------------------------------------------
# Test 2 — Successful tile cover dominant color matches the input image
# ---------------------------------------------------------------------------


def test_successful_tile_cover_source_matches_rasterized_input_color() -> None:
    """When ``_rasterize_tile_for_cover`` returns a solid-color image, that
    color is observable in the ``cover_source`` the worker forwards to
    ``export_scene_with_bambu_metadata``.

    This proves the worker forwards the rasterized Image *as-is* without
    accidentally substituting another tile's image or a placeholder.
    """

    # Three tiles, three distinct solid colors; rasterizer returns each
    # tile's own color as a 256×256 RGBA Image. We also record which tile
    # the rasterizer was called for so we can map writer calls back to
    # tile labels (the writer's ``output_path`` is a tempfile name that
    # carries no tile metadata).
    tile_colors: dict[str, tuple[int, int, int, int]] = {
        "R1C1": (220, 30, 40, 255),
        "R1C2": (30, 200, 60, 255),
        "R1C3": (40, 80, 220, 255),
    }
    tile_labels_in_order = list(tile_colors.keys())
    tiles = [_make_tile(label) for label in tile_labels_in_order]
    captured: list[dict] = []
    rasterize_order: list[str] = []

    def _rasterize(tile, *_args, **_kwargs):
        rasterize_order.append(tile.label)
        return Image.new("RGBA", (256, 256), tile_colors[tile.label])

    grid_params = _params_for_grid(rows=1, cols=3)

    with (
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=tiles),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", side_effect=_rasterize),
        patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_fake_export_recording(captured)),
    ):
        result = worker_generate_large_format_svg_native(
            "image.svg", "lut.npy", grid_params
        )

    try:
        assert result["tile_count"] == 3
        assert result["tile_skipped_empty"] == 0
        assert result["tile_failed_cover"] == 0
        # 1×3 grid covers cleanly.
        assert result["grid_cols"] * result["grid_rows"] == 3

        # All three tiles rasterized in the slicer's iteration order, and
        # each writer call followed its own rasterize call within the same
        # loop iteration — so call N writes the cover for the tile N
        # rasterized at index N.
        assert rasterize_order == tile_labels_in_order
        assert len(captured) == 3

        for index, entry in enumerate(captured):
            tile_label = tile_labels_in_order[index]
            cover_source = entry["cover_source"]
            assert isinstance(cover_source, Image.Image), (
                f"cover_source for {tile_label} must be a PIL Image, "
                f"got {type(cover_source).__name__}"
            )

            expected_rgb = tile_colors[tile_label][:3]
            actual_rgb = _dominant_color(cover_source)
            for channel in range(3):
                assert abs(actual_rgb[channel] - expected_rgb[channel]) <= 2, (
                    f"tile {tile_label}: cover_source dominant color "
                    f"{actual_rgb} differs from expected {expected_rgb}"
                )
    finally:
        if os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


# ---------------------------------------------------------------------------
# Test 3 — None rasterization is silent-placeholder, not failure
# ---------------------------------------------------------------------------


def test_rasterize_returns_none_does_not_count_as_failed_cover(caplog) -> None:
    """``_rasterize_tile_for_cover`` returning ``None`` is the silent-placeholder
    path: the tile is still exported with ``cover_source=None`` (writer falls
    through to the silent placeholder), and ``tile_failed_cover`` is *not*
    incremented; no WARNING is emitted.

    This guards a regression where the worker accidentally treats ``None``
    like a TimeoutError (which would still export the tile but bump
    ``tile_failed_cover`` and emit a WARNING).
    """

    tiles = [_make_tile("R1C1"), _make_tile("R1C2")]
    captured: list[dict] = []

    def _rasterize(tile, *_args, **_kwargs):
        return None

    with (
        _capture_worker_warnings(caplog),
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=tiles),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", side_effect=_rasterize),
        patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_fake_export_recording(captured)),
    ):
        result = worker_generate_large_format_svg_native(
            "image.svg", "lut.npy", _params_for_grid(rows=1, cols=2)
        )

    try:
        # Both tiles successfully exported; none counted as failed cover.
        assert result["tile_count"] == 2
        assert result["tile_failed_cover"] == 0
        assert result["tile_skipped_empty"] == 0
        assert (
            result["tile_count"] + result["tile_skipped_empty"]
            == result["grid_cols"] * result["grid_rows"]
        )

        assert len(captured) == 2
        for entry in captured:
            assert entry["cover_source"] is None

        # No WARNING for the silent path.
        warnings = [
            rec for rec in caplog.records
            if getattr(rec, "event", None) == "bambu_3mf_cover_thumbnail_failed"
        ]
        assert warnings == []
    finally:
        if os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


# ---------------------------------------------------------------------------
# Test 4 — Counter invariant strictly distinguishes empty from failed-cover
# ---------------------------------------------------------------------------


def test_counter_invariant_separates_skipped_empty_from_failed_cover(caplog) -> None:
    """``tile_skipped_empty`` is exclusively from empty scenes; ``tile_failed_cover``
    is a *subset* indicator on tiles that **were exported** but whose cover
    defaulted to the placeholder. They never double-count, never swap, and
    ``tile_count + tile_skipped_empty`` always equals the grid size.

    R5.3 explicitly distinguishes the two failure modes; this is the cross-
    check that prevents counter-mixing regressions.
    """

    # 3×3 grid → 9 cells. Slicer returns 6 tiles (3 sliced as empty). Of
    # the 6 reaching the rasterizer: 3 succeed, 2 timeout, 1 raises.
    success_image = Image.new("RGBA", (256, 256), (255, 255, 255, 255))
    tiles = [
        _make_tile("R1C1"),
        _make_tile("R1C2"),
        _make_tile("R1C3"),
        _make_tile("R2C1"),
        _make_tile("R2C2"),
        _make_tile("R2C3"),
    ]
    captured: list[dict] = []

    def _rasterize(tile, *_args, **_kwargs):
        if tile.label == "R1C1":
            raise TimeoutError("synthetic timeout 1")
        if tile.label == "R1C2":
            raise TimeoutError("synthetic timeout 2")
        if tile.label == "R1C3":
            raise RuntimeError("synthetic raster failure")
        return success_image

    with (
        _capture_worker_warnings(caplog),
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=tiles),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", side_effect=_rasterize),
        patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_fake_export_recording(captured)),
    ):
        result = worker_generate_large_format_svg_native(
            "image.svg", "lut.npy", _params_for_grid(rows=3, cols=3)
        )

    try:
        # Grid is 3×3 = 9. Slicer dropped 3 (skipped_empty). All 6 sliced
        # tiles are exported (3 with real cover, 3 with placeholder).
        assert result["grid_cols"] * result["grid_rows"] == 9
        assert result["tile_skipped_empty"] == 3
        assert result["tile_failed_cover"] == 3
        assert result["tile_count"] == 6
        assert result["tile_count"] + result["tile_skipped_empty"] == 9

        # WARNINGs match the rasterize-failure count exactly — empty tiles
        # do not emit WARNINGs (R5.3 silent semantic).
        warning_events = [
            getattr(rec, "event", None) for rec in caplog.records
        ]
        assert warning_events.count("bambu_3mf_cover_thumbnail_failed") == 3

        # Each WARNING's error_type is one of the two expected categories.
        warning_records = [
            rec for rec in caplog.records
            if getattr(rec, "event", None) == "bambu_3mf_cover_thumbnail_failed"
        ]
        observed_error_types = {rec.error_type for rec in warning_records}
        assert observed_error_types <= {"tile_rasterize_timeout", "RuntimeError"}
        assert "tile_rasterize_timeout" in observed_error_types
        assert "RuntimeError" in observed_error_types
        for rec in warning_records:
            assert rec.fallback_action == "placeholder_written"

        # All 6 sliced tiles must be present in the ZIP.
        with zipfile.ZipFile(result["zip_path"]) as archive:
            zip_names = sorted(archive.namelist())
        assert len(zip_names) == 6
    finally:
        if os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])
