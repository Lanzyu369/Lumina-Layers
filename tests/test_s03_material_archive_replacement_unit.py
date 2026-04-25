"""Regression tests for S03 global color replacements in material-archive mode.

Historically, when ``ctx["material_source"] == "material_archive"`` (no LUT
processor) every queued color replacement was dropped with a warning, which
made the picker silently ignore replacements for material-archive workflows.
This module locks in the new behavior: the S03 step re-solves every
``(orig_hex → repl_hex)`` pair against the saved ``MaterialParams`` palette
and writes both ``matched_rgb`` and ``material_matrix`` atomically.
"""

from __future__ import annotations

import os
import pickle
from unittest.mock import patch

import numpy as np
import pytest

from core.material_color_solver import MaterialParams
from core.pipeline.s03_color_replacement import (
    _apply_material_archive_color_replacements,
    run,
)


def _mat(name: str, E: tuple, k: tuple) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(E, dtype=np.float64),
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.asarray((1.0, 1.0, 1.0), dtype=np.float64),
        estimated_rgb=np.asarray(
            [int(round(255 * c)) for c in E], dtype=np.uint8
        ),
    )


_SMALL_PALETTE = [
    _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0)),
    _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0)),
    _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5)),
]


def _make_material_archive_ctx(
    color_replacements: dict[str, str] | None = None,
) -> dict:
    """Mirror ``s01_input_validation`` outputs for material-archive mode."""
    h, w = 3, 4
    matched_rgb = np.full((h, w, 3), [200, 100, 50], dtype=np.uint8)
    # First column stays "Blue-ish" so we can exercise selective replacement.
    matched_rgb[:, 0] = [50, 70, 200]
    material_matrix = np.zeros((h, w, 5), dtype=np.int32)
    mask_solid = np.ones((h, w), dtype=bool)

    return {
        "matched_rgb": matched_rgb,
        "material_matrix": material_matrix,
        "mask_solid": mask_solid,
        "processor": None,  # material-archive has no LUT processor
        "color_replacements": color_replacements,
        "replacement_regions": None,
        "matched_rgb_path": None,
        "material_matrix_path": None,
        "material_source": "material_archive",
        "_material_params": _SMALL_PALETTE,
        "color_layers": 5,
        "layer_height_mm": 0.08,
        "material_substrate": "white",
    }


class TestApplyMaterialArchiveColorReplacements:
    """Unit tests for the helper that performs the actual solve + write."""

    def test_empty_replacements_returns_inputs(self):
        matched = np.full((2, 2, 3), 100, dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)
        out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
            matched, mat, mask, {}, _SMALL_PALETTE, 5, 0.08, "white",
        )
        assert applied == 0
        assert out_rgb is matched
        assert out_mat is mat

    def test_empty_materials_returns_inputs(self):
        matched = np.full((2, 2, 3), 100, dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)
        out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
            matched, mat, mask, {"#646464": "#c80000"}, [], 5, 0.08, "white",
        )
        assert applied == 0
        assert out_rgb is matched
        assert out_mat is mat

    def test_skips_orig_not_present(self):
        matched = np.full((2, 2, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)
        out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
            # orig=rgb(10,20,30) never appears in matched
            matched, mat, mask, {"#0a141e": "#ff0000"},
            _SMALL_PALETTE, 5, 0.08, "white",
        )
        assert applied == 0
        np.testing.assert_array_equal(out_rgb, matched)
        np.testing.assert_array_equal(out_mat, mat)

    def test_replaces_matching_pixels_and_updates_material_matrix(self):
        matched = np.full((3, 4, 3), [200, 100, 50], dtype=np.uint8)
        # One column of a different color to check selectivity.
        matched[:, 0] = [50, 70, 200]
        mat = np.zeros((3, 4, 5), dtype=np.int32)
        mask = np.ones((3, 4), dtype=bool)
        out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
            matched, mat, mask, {"#c86432": "#14c814"},
            _SMALL_PALETTE, 5, 0.08, "white",
        )
        assert applied == 1
        # Non-matching pixel (col 0) stays untouched.
        np.testing.assert_array_equal(out_rgb[:, 0], matched[:, 0])
        np.testing.assert_array_equal(out_mat[:, 0], mat[:, 0])
        # Matching pixels (cols 1..3) have been updated to the solver result.
        updated_rgb = out_rgb[:, 1:]
        updated_mat = out_mat[:, 1:]
        # All updated pixels have the same achieved color (single solve per target).
        assert np.all(updated_rgb == updated_rgb[0, 0])
        # Material indices must be valid.
        assert np.all(updated_mat >= 0)
        assert np.all(updated_mat < len(_SMALL_PALETTE))
        # And the recipe should not be entirely zeros (implying an actual solve).
        assert np.any(updated_mat != 0)

    def test_ignores_invalid_hex_pairs(self):
        matched = np.full((2, 2, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)
        out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
            matched, mat, mask,
            {"not-a-hex": "#ff0000", "#c86432": "also-bad"},
            _SMALL_PALETTE, 5, 0.08, "white",
        )
        # Both pairs rejected → no change.
        assert applied == 0
        np.testing.assert_array_equal(out_rgb, matched)
        np.testing.assert_array_equal(out_mat, mat)

    def test_solver_failure_does_not_crash(self):
        matched = np.full((2, 2, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)
        with patch(
            "core.material_lut_synthesis.solve_image_colors_optimal",
            side_effect=RuntimeError("fake solver failure"),
        ), patch(
            "core.material_cache.load_material_solver_cache",
            return_value=None,
        ):
            out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
                matched, mat, mask, {"#c86432": "#14c814"},
                _SMALL_PALETTE, 5, 0.08, "white",
            )
        assert applied == 0
        np.testing.assert_array_equal(out_rgb, matched)
        np.testing.assert_array_equal(out_mat, mat)

    def test_respects_mask_solid(self):
        matched = np.full((3, 4, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((3, 4, 5), dtype=np.int32)
        # Only row 0 is solid.
        mask = np.zeros((3, 4), dtype=bool)
        mask[0, :] = True
        out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
            matched, mat, mask, {"#c86432": "#14c814"},
            _SMALL_PALETTE, 5, 0.08, "white",
        )
        assert applied == 1
        # Row 0 updated
        assert np.all(out_rgb[0] != matched[0])
        # Row 1+ untouched (outside mask_solid)
        np.testing.assert_array_equal(out_rgb[1:], matched[1:])
        np.testing.assert_array_equal(out_mat[1:], mat[1:])

    def test_uses_cache_when_available(self):
        """When a cache exists it should be used instead of MITM."""
        matched = np.full((2, 2, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)

        class _StubCache:
            def lookup(self, unique_srgb, user_materials):
                n = unique_srgb.shape[0]
                return (
                    # Return a deterministic achieved color.
                    np.full((n, 3), [10, 200, 20], dtype=np.uint8),
                    np.zeros((n, 5), dtype=np.int32),
                    np.full(n, 0.5, dtype=np.float32),
                )

        with patch(
            "core.material_cache.load_material_solver_cache",
            return_value=_StubCache(),
        ), patch(
            "core.material_lut_synthesis.solve_image_colors_optimal",
            side_effect=AssertionError(
                "MITM should not run when cache is available"
            ),
        ):
            out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
                matched, mat, mask, {"#c86432": "#14c814"},
                _SMALL_PALETTE, 5, 0.08, "white",
            )
        assert applied == 1
        # All originally matching pixels now carry the stubbed achieved color.
        np.testing.assert_array_equal(out_rgb[0, 0], [10, 200, 20])


class TestS03RunMaterialArchiveBranch:
    """Integration checks: the S03 run() step dispatches to the helper."""

    def test_recipe_override_virtual_material_extends_export_palette(self, tmp_path):
        """Material-archive generation must register virtual recipe channels.

        The apply endpoint can write a recipe such as ``[N, N, ...]`` where
        ``N`` is the first virtual material after the selected archive
        materials. During real generation, S03 receives that material matrix
        from disk and must also extend ``slot_names`` / ``preview_colors`` so
        S07 can emit a mesh for channel ``N`` instead of leaving the region as
        unmapped air.
        """
        ctx = _make_material_archive_ctx(None)
        native_count = len(_SMALL_PALETTE)
        mask = np.zeros(ctx["mask_solid"].shape, dtype=bool)
        mask[1:, 1:3] = True

        override_matrix = ctx["material_matrix"].copy()
        override_matrix[mask] = native_count
        matrix_path = tmp_path / "material_matrix.npy"
        np.save(matrix_path, override_matrix)

        masks_path = tmp_path / "recipe_masks.pkl"
        with open(masks_path, "wb") as f:
            pickle.dump({"region-1": mask}, f)

        ctx.update(
            {
                "slot_names": ["Red", "Blue", "White"],
                "preview_colors": {
                    0: [153, 13, 13, 255],
                    1: [13, 26, 153, 255],
                    2: [242, 242, 242, 255],
                },
                "color_conf": {
                    "slots": ["Red", "Blue", "White"],
                    "preview": {
                        0: [153, 13, 13, 255],
                        1: [13, 26, 153, 255],
                        2: [242, 242, 242, 255],
                    },
                },
                "material_matrix_path": os.fspath(matrix_path),
                "recipe_override_masks_path": os.fspath(masks_path),
                "recipe_overrides": [
                    {
                        "region_id": "region-1",
                        "recipe": [native_count] * ctx["material_matrix"].shape[2],
                        "layer_order": "Top2Bottom",
                        "virtual_materials": [
                            {"name": "Black", "hex": "#111111"}
                        ],
                    }
                ],
            }
        )

        result = run(ctx)

        assert result["slot_names"][native_count] == "Black"
        assert result["preview_colors"][native_count] == [17, 17, 17, 255]
        assert result["color_conf"]["slots"][native_count] == "Black"
        assert result["color_conf"]["preview"][native_count] == [17, 17, 17, 255]
        assert np.all(result["material_matrix"][mask] == native_count)

    def test_applies_replacement_without_processor(self):
        ctx = _make_material_archive_ctx({"#c86432": "#14c814"})
        original_col0 = ctx["matched_rgb"][:, 0].copy()
        result = run(ctx)
        # Rest of the image has been rewritten to the solver's achieved color.
        rewritten = result["matched_rgb"][:, 1:]
        assert not np.array_equal(rewritten[0, 0], [200, 100, 50])
        # Col 0 (blue-ish) was NOT targeted by the replacement, so it's intact.
        np.testing.assert_array_equal(result["matched_rgb"][:, 0], original_col0)
        # Material matrix on rewritten region is no longer all-zeros.
        assert np.any(result["material_matrix"][:, 1:] != 0)

    def test_no_warning_when_material_archive_handles_replacement(self, caplog):
        import logging
        ctx = _make_material_archive_ctx({"#c86432": "#14c814"})
        with caplog.at_level(logging.WARNING, logger="core.pipeline.s03_color_replacement"):
            run(ctx)
        skipped_warnings = [
            r for r in caplog.records
            if "skipped" in r.getMessage() and "material-archive" in r.getMessage()
        ]
        assert skipped_warnings == [], (
            "Material-archive color replacements should no longer be silently dropped"
        )

    def test_empty_replacements_in_material_archive_does_not_solve(self):
        """No replacement → no solver call, matched_rgb/material_matrix intact."""
        ctx = _make_material_archive_ctx(None)
        original_rgb = ctx["matched_rgb"].copy()
        original_mat = ctx["material_matrix"].copy()
        with patch(
            "core.pipeline.s03_color_replacement._apply_material_archive_color_replacements"
        ) as mock_apply:
            result = run(ctx)
        mock_apply.assert_not_called()
        np.testing.assert_array_equal(result["matched_rgb"], original_rgb)
        np.testing.assert_array_equal(result["material_matrix"], original_mat)

    def test_lut_mode_path_untouched(self, caplog):
        """When a processor exists, the material-archive branch is NOT used."""
        from unittest.mock import MagicMock

        ctx = _make_material_archive_ctx({"#c86432": "#14c814"})
        # Upgrade to LUT mode by attaching a processor and removing the flag.
        ctx["material_source"] = "lut"
        ctx.pop("_material_params")
        processor = MagicMock()
        processor._rgb_to_lab = MagicMock(
            return_value=np.array([[50.0, 0.0, 0.0]])
        )
        processor.kdtree = MagicMock()
        processor.kdtree.query = MagicMock(
            return_value=(np.array([0.0]), np.array([0]))
        )
        processor.ref_stacks = np.zeros((10, 5), dtype=int)
        processor.lut_rgb = np.zeros((10, 3), dtype=np.uint8)
        ctx["processor"] = processor

        with patch(
            "core.pipeline.s03_color_replacement._apply_material_archive_color_replacements"
        ) as mock_apply:
            run(ctx)
        mock_apply.assert_not_called()


class TestS03NotWorseFallbackWiring:
    """S03 must invoke the cross-N not-worse fallback on the baseline solve,
    and must degrade gracefully when the fallback itself raises.
    S03 必须在基线求解之后调用跨 N 不劣回退；回退自身抛错时必须安全降级。
    """

    def test_fallback_is_called_after_cache_lookup(self):
        matched = np.full((2, 2, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)

        class _StubCache:
            def lookup(self, unique_srgb, user_materials):
                n = unique_srgb.shape[0]
                return (
                    np.full((n, 3), [10, 200, 20], dtype=np.uint8),
                    np.zeros((n, 5), dtype=np.int32),
                    np.full(n, 2.0, dtype=np.float32),
                )

        fallback_calls: list[dict] = []

        def _mock_fallback(
            targets, materials, matched_rgb_unique, recipes_unique, delta_e,
            **kwargs,
        ):
            fallback_calls.append({
                "target_layer_count": kwargs["target_layer_count"],
                "substrate": kwargs["substrate"],
                "targets_shape": targets.shape,
            })
            return matched_rgb_unique, recipes_unique, delta_e, {
                "white_material_index": 2,
                "applied": True,
                "improved_pixels": 0,
                "per_k_improved": {},
                "mean_delta_e_before": 2.0,
                "max_delta_e_before": 2.0,
                "mean_delta_e_after": 2.0,
                "max_delta_e_after": 2.0,
            }

        with patch(
            "core.material_cache.load_material_solver_cache",
            return_value=_StubCache(),
        ), patch(
            "core.material_lut_synthesis.ensure_not_worse_than_smaller_N",
            side_effect=_mock_fallback,
        ):
            out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
                matched, mat, mask, {"#c86432": "#14c814"},
                _SMALL_PALETTE, 5, 0.08, "white",
            )

        assert applied == 1
        assert len(fallback_calls) == 1
        assert fallback_calls[0]["target_layer_count"] == 5
        assert fallback_calls[0]["substrate"] == "white"
        # Exactly one unique replacement target (#14c814) was solved.
        assert fallback_calls[0]["targets_shape"] == (1, 3)

    def test_fallback_exception_keeps_baseline(self, caplog):
        """If the fallback helper raises, S03 must log a warning and keep
        the baseline recipe/achieved color from the solver unchanged."""
        import logging

        matched = np.full((2, 2, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)

        class _StubCache:
            def lookup(self, unique_srgb, user_materials):
                n = unique_srgb.shape[0]
                return (
                    np.full((n, 3), [10, 200, 20], dtype=np.uint8),
                    # A recognisable non-zero recipe so we can verify it survives.
                    np.full((n, 5), 1, dtype=np.int32),
                    np.full(n, 1.2, dtype=np.float32),
                )

        with patch(
            "core.material_cache.load_material_solver_cache",
            return_value=_StubCache(),
        ), patch(
            "core.material_lut_synthesis.ensure_not_worse_than_smaller_N",
            side_effect=RuntimeError("synthetic fallback failure"),
        ), caplog.at_level(logging.WARNING, logger="core.pipeline.s03_color_replacement"):
            out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
                matched, mat, mask, {"#c86432": "#14c814"},
                _SMALL_PALETTE, 5, 0.08, "white",
            )

        assert applied == 1
        # Baseline achieved color still reached every matching pixel.
        assert np.all(out_rgb[:, 1:] == np.asarray([10, 200, 20], dtype=np.uint8))
        # Baseline recipe (all 1s) reached the matrix, reversed Top2Bottom
        # (reversing a constant vector is a no-op).
        assert np.all(out_mat[:, 1:] == 1)
        # A warning mentioning the fallback failure was recorded.
        failure_warnings = [
            r for r in caplog.records
            if "Not-worse fallback failed" in r.getMessage()
        ]
        assert failure_warnings, (
            "Expected a warning entry when the not-worse fallback raises"
        )
