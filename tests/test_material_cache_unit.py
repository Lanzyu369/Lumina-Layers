"""Unit tests for the disk-backed material-solver cache.

Covers:
- Palette fingerprinting (stability, order-independence, parameter-change invalidation)
- Build: shape/metadata contracts, cell coverage for small palettes
- Save / load roundtrip (with corrupted-file handling)
- Lookup: ΔE stays within a grid-cell diagonal of the strict optimal solver
- Listing / deletion of cached entries
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from core.material_cache import (
    DEFAULT_GRID_RESOLUTION,
    MaterialSolverCache,
    build_material_solver_cache,
    cache_file_path,
    canonical_palette_order,
    default_cache_directory,
    delete_cached_entry,
    find_any_cached_grid,
    fingerprint_palette,
    list_cached_entries,
    load_material_solver_cache,
    load_material_solver_cache_with_fallback,
    save_material_solver_cache,
)
from core.material_color_solver import (
    MaterialParams,
    rgb_to_lab,
    solve_image_colors_optimal,
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


RED = _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0))
BLUE = _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0))
WHITE = _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5))
GREEN = _mat("Green", E=(0.1, 0.6, 0.1), k=(4.0, 4.0, 4.0))
BLACK = _mat("Black", E=(0.05, 0.05, 0.05), k=(6.0, 6.0, 6.0))

SMALL_PALETTE = [RED, BLUE, WHITE]
MEDIUM_PALETTE = [RED, BLUE, WHITE, GREEN, BLACK]


# ---------------------------------------------------------------------------
# Palette fingerprinting
# ---------------------------------------------------------------------------


class TestFingerprintPalette:
    def test_stable_across_calls(self):
        assert fingerprint_palette(SMALL_PALETTE) == fingerprint_palette(SMALL_PALETTE)

    def test_order_independent(self):
        fp1 = fingerprint_palette([RED, BLUE, WHITE])
        fp2 = fingerprint_palette([WHITE, RED, BLUE])
        fp3 = fingerprint_palette([BLUE, WHITE, RED])
        assert fp1 == fp2 == fp3

    def test_changes_when_material_parameter_changes(self):
        RED_ALT = _mat("Red", E=(0.65, 0.05, 0.05), k=(4.0, 4.0, 4.0))
        assert fingerprint_palette([RED, BLUE]) != fingerprint_palette([RED_ALT, BLUE])

    def test_changes_when_palette_size_changes(self):
        assert fingerprint_palette([RED, BLUE]) != fingerprint_palette([RED, BLUE, WHITE])

    def test_empty_palette_raises(self):
        with pytest.raises(ValueError):
            fingerprint_palette([])

    def test_fingerprint_is_16_hex_chars(self):
        fp = fingerprint_palette(SMALL_PALETTE)
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)

    def test_canonical_order_is_stable(self):
        order1 = canonical_palette_order([RED, BLUE, WHITE])
        order2 = canonical_palette_order([RED, BLUE, WHITE])
        assert order1 == order2

    def test_canonical_order_is_reorder_independent(self):
        order_a = canonical_palette_order([RED, BLUE, WHITE])
        order_b = canonical_palette_order([WHITE, RED, BLUE])
        # Applying the orders should yield the same sorted materials.
        reordered_a = [[RED, BLUE, WHITE][i] for i in order_a]
        reordered_b = [[WHITE, RED, BLUE][i] for i in order_b]
        assert [m.name for m in reordered_a] == [m.name for m in reordered_b]


# ---------------------------------------------------------------------------
# Cache file path
# ---------------------------------------------------------------------------


class TestCacheFilePath:
    def test_path_includes_all_key_parameters(self, tmp_path: Path):
        p = cache_file_path(
            SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white", cache_root=tmp_path,
        )
        name = p.name
        assert name.startswith(fingerprint_palette(SMALL_PALETTE))
        assert "-N05-" in name
        assert "-t0_08-" in name
        # Default grid is 128, so the canonical stem ends with -white-g128.npz.
        assert name.endswith(f"-white-g{DEFAULT_GRID_RESOLUTION:03d}.npz")

    def test_path_differs_for_different_substrate(self, tmp_path: Path):
        p_white = cache_file_path(
            SMALL_PALETTE, 5, 0.08, "white", cache_root=tmp_path,
        )
        p_black = cache_file_path(
            SMALL_PALETTE, 5, 0.08, "black", cache_root=tmp_path,
        )
        assert p_white != p_black

    def test_path_differs_for_different_grid_resolution(self, tmp_path: Path):
        p_64 = cache_file_path(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=64, cache_root=tmp_path,
        )
        p_128 = cache_file_path(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=128, cache_root=tmp_path,
        )
        assert p_64 != p_128
        assert p_64.name.endswith("-white-g064.npz")
        assert p_128.name.endswith("-white-g128.npz")

    def test_default_cache_directory_includes_subdir(self, tmp_path: Path):
        d = default_cache_directory(tmp_path)
        assert d.name == "_solver_cache"
        assert d.parent == tmp_path


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


class TestBuild:
    def test_small_palette_produces_valid_cache(self):
        cache = build_material_solver_cache(
            SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white", grid_resolution=32,
        )
        assert cache.valid_cell_count > 0
        assert cache.recipes.shape == (cache.valid_cell_count, 5)
        assert cache.lab_centers.shape == (cache.valid_cell_count, 3)
        assert cache.achieved_srgb.shape == (cache.valid_cell_count, 3)
        assert cache.center_delta_e.shape == (cache.valid_cell_count,)
        # Metadata sanity.
        assert cache.metadata["layer_count"] == 5
        assert cache.metadata["layer_height_mm"] == 0.08
        assert cache.metadata["substrate"] == "white"
        assert cache.metadata["grid_resolution"] == 32
        assert cache.metadata["palette_hash"] == fingerprint_palette(SMALL_PALETTE)
        assert cache.metadata["valid_cell_count"] == cache.valid_cell_count
        assert cache.metadata["total_combinations"] == 3 ** 5

    def test_progress_callback_invoked(self):
        calls = []
        build_material_solver_cache(
            SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white", grid_resolution=32,
            progress_callback=lambda f, info: calls.append((f, info)),
        )
        assert len(calls) >= 1
        # Final progress should be ~1.0.
        final_fraction, final_info = calls[-1]
        assert final_fraction == pytest.approx(1.0, abs=1e-9)
        assert "valid_bucket_count" in final_info
        assert "elapsed_seconds" in final_info

    def test_rejects_invalid_layer_count(self):
        with pytest.raises(ValueError):
            build_material_solver_cache(
                SMALL_PALETTE, layer_count=1, layer_height_mm=0.08,
                substrate="white",
            )

    def test_rejects_invalid_substrate(self):
        with pytest.raises(ValueError):
            build_material_solver_cache(
                SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
                substrate="orange",  # type: ignore[arg-type]
            )

    def test_rejects_empty_materials(self):
        with pytest.raises(ValueError):
            build_material_solver_cache(
                [], layer_count=5, layer_height_mm=0.08, substrate="white",
            )

    def test_grid_resolution_bounds(self):
        with pytest.raises(ValueError):
            build_material_solver_cache(
                SMALL_PALETTE, 5, 0.08, "white", grid_resolution=4,
            )
        with pytest.raises(ValueError):
            build_material_solver_cache(
                SMALL_PALETTE, 5, 0.08, "white", grid_resolution=512,
            )


# ---------------------------------------------------------------------------
# Save / load roundtrip
# ---------------------------------------------------------------------------


class TestSaveLoadRoundtrip:
    def test_roundtrip_preserves_arrays_and_metadata(self, tmp_path: Path):
        cache = build_material_solver_cache(
            SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white", grid_resolution=32,
        )
        save_material_solver_cache(cache, cache_root=tmp_path)
        loaded = load_material_solver_cache(
            SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white", grid_resolution=32, cache_root=tmp_path,
        )
        assert loaded is not None
        np.testing.assert_allclose(loaded.lab_centers, cache.lab_centers, atol=1e-3)
        np.testing.assert_array_equal(loaded.recipes, cache.recipes)
        np.testing.assert_array_equal(loaded.achieved_srgb, cache.achieved_srgb)
        np.testing.assert_allclose(
            loaded.center_delta_e, cache.center_delta_e, atol=1e-3
        )
        assert loaded.metadata["palette_hash"] == cache.metadata["palette_hash"]
        assert loaded.metadata["layer_count"] == cache.metadata["layer_count"]

    def test_load_returns_none_when_absent(self, tmp_path: Path):
        result = load_material_solver_cache(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=32, cache_root=tmp_path,
        )
        assert result is None

    def test_load_returns_none_when_npz_corrupt(self, tmp_path: Path):
        cache = build_material_solver_cache(
            SMALL_PALETTE, 5, 0.08, "white", grid_resolution=32,
        )
        save_material_solver_cache(cache, cache_root=tmp_path)
        # Corrupt the npz file.
        npz_path = cache_file_path(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=32, cache_root=tmp_path,
        )
        npz_path.write_bytes(b"not a valid npz file")
        result = load_material_solver_cache(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=32, cache_root=tmp_path,
        )
        assert result is None

    def test_load_returns_none_when_palette_mismatched(self, tmp_path: Path):
        cache = build_material_solver_cache(
            SMALL_PALETTE, 5, 0.08, "white", grid_resolution=32,
        )
        save_material_solver_cache(cache, cache_root=tmp_path)
        # Try loading with a different palette sharing same N/t/substrate.
        # cache_file_path will resolve to a different file (palette_hash differs),
        # so the loader simply returns None.
        result = load_material_solver_cache(
            MEDIUM_PALETTE, 5, 0.08, "white",
            grid_resolution=32, cache_root=tmp_path,
        )
        assert result is None

    def test_load_returns_none_when_grid_resolution_mismatched(self, tmp_path: Path):
        cache = build_material_solver_cache(
            SMALL_PALETTE, 5, 0.08, "white", grid_resolution=32,
        )
        save_material_solver_cache(cache, cache_root=tmp_path)
        # Asking for a different grid resolution must neither read the suffixed
        # file (paths differ) nor silently upgrade/downgrade; result is None.
        result = load_material_solver_cache(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=64, cache_root=tmp_path,
        )
        assert result is None

    def test_legacy_path_accepted_when_grid_matches(self, tmp_path: Path):
        """A pre-`-g<grid>` cache is picked up when its metadata grid matches."""
        import json

        cache = build_material_solver_cache(
            SMALL_PALETTE, 5, 0.08, "white", grid_resolution=32,
        )
        save_material_solver_cache(cache, cache_root=tmp_path)
        # Rename the suffixed file pair to the legacy (pre-g<grid>) stem.
        suffixed_npz = cache_file_path(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=32, cache_root=tmp_path,
        )
        suffixed_meta = suffixed_npz.with_suffix(".meta.json")
        directory = suffixed_npz.parent
        palette_hash = fingerprint_palette(SMALL_PALETTE)
        legacy_stem = f"{palette_hash}-N05-t0_08-white"
        legacy_npz = directory / f"{legacy_stem}.npz"
        legacy_meta = directory / f"{legacy_stem}.meta.json"
        suffixed_npz.replace(legacy_npz)
        suffixed_meta.replace(legacy_meta)
        # Sanity: the suffixed path is gone, legacy path exists.
        assert not suffixed_npz.exists()
        assert legacy_npz.exists()

        # Legacy metadata already records grid_resolution=32, so the loader
        # should accept it when the caller explicitly asks for grid 32.
        loaded = load_material_solver_cache(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=32, cache_root=tmp_path,
        )
        assert loaded is not None
        assert loaded.grid_resolution == 32

        # But if the legacy file's metadata reports a different resolution
        # than the caller requests, we must refuse the fallback.
        metadata = json.loads(legacy_meta.read_text(encoding="utf-8"))
        metadata["grid_resolution"] = 64
        legacy_meta.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result = load_material_solver_cache(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=32, cache_root=tmp_path,
        )
        assert result is None


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


class TestLookup:
    @pytest.fixture
    def built_cache(self) -> MaterialSolverCache:
        return build_material_solver_cache(
            SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white", grid_resolution=32,
        )

    def test_lookup_returns_expected_shapes(self, built_cache: MaterialSolverCache):
        targets = np.asarray(
            [[200, 100, 50], [50, 50, 200], [128, 128, 128]], dtype=np.uint8
        )
        matched, recipes, delta_e = built_cache.lookup(targets, SMALL_PALETTE)
        assert matched.shape == (3, 3)
        assert matched.dtype == np.uint8
        assert recipes.shape == (3, 5)
        assert recipes.dtype == np.int32
        assert delta_e.shape == (3,)
        assert np.all(delta_e >= 0)

    def test_lookup_empty_targets(self, built_cache: MaterialSolverCache):
        targets = np.zeros((0, 3), dtype=np.uint8)
        matched, recipes, delta_e = built_cache.lookup(targets, SMALL_PALETTE)
        assert matched.shape == (0, 3)
        assert recipes.shape == (0, 5)
        assert delta_e.shape == (0,)

    def test_lookup_with_wrong_palette_raises(
        self, built_cache: MaterialSolverCache
    ):
        targets = np.asarray([[100, 100, 100]], dtype=np.uint8)
        with pytest.raises(ValueError, match="palette"):
            built_cache.lookup(targets, MEDIUM_PALETTE)

    def test_lookup_on_empty_cache_raises(self):
        """A cache with zero populated cells must refuse lookup explicitly."""
        empty_cache = MaterialSolverCache(
            lab_centers=np.zeros((0, 3), dtype=np.float32),
            recipes=np.zeros((0, 5), dtype=np.uint8),
            achieved_srgb=np.zeros((0, 3), dtype=np.uint8),
            center_delta_e=np.zeros((0,), dtype=np.float32),
            metadata={
                "palette_hash": fingerprint_palette(SMALL_PALETTE),
                "layer_count": 5,
                "layer_height_mm": 0.08,
                "substrate": "white",
                "grid_resolution": 32,
            },
        )
        targets = np.asarray([[100, 100, 100]], dtype=np.uint8)
        with pytest.raises(ValueError, match="no populated cells"):
            empty_cache.lookup(targets, SMALL_PALETTE)

    def test_lookup_within_cell_half_diagonal_of_optimal(
        self, built_cache: MaterialSolverCache
    ):
        """Cache lookup ΔE should be close to the strict-optimal solver's ΔE."""
        rng = np.random.default_rng(42)
        targets = rng.integers(0, 256, size=(16, 3), dtype=np.uint8)

        _, _, optimal_de = solve_image_colors_optimal(
            targets, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
        )
        _, _, cache_de = built_cache.lookup(targets, SMALL_PALETTE)

        # Cache ΔE can be up to ~one cell half-diagonal worse than optimal.
        # For grid_resolution=32: cell size = (100/32, 256/32, 256/32) =
        # (3.1, 8, 8); half-diagonal ≈ 5.9. Allow slack for quantization.
        max_extra = float((cache_de - optimal_de).max())
        assert max_extra <= 12.0, (
            f"Cache regressed {max_extra:.2f} ΔE vs. strict-optimal solver. "
            f"Cache DE mean={cache_de.mean():.2f}, optimal DE mean={optimal_de.mean():.2f}"
        )

    def test_lookup_reindexes_to_user_palette_order(
        self, built_cache: MaterialSolverCache
    ):
        """Reordering the caller's material list must re-bind recipe indices.

        The same target color should produce recipes that resolve to the same
        materials (not the same indices) regardless of caller order.
        """
        targets = np.asarray([[180, 80, 60]], dtype=np.uint8)
        # Original order.
        _, rec_original, _ = built_cache.lookup(targets, SMALL_PALETTE)
        original_mats = [SMALL_PALETTE[i] for i in rec_original[0]]
        # Shuffled user order.
        shuffled = [SMALL_PALETTE[2], SMALL_PALETTE[0], SMALL_PALETTE[1]]
        _, rec_shuffled, _ = built_cache.lookup(targets, shuffled)
        shuffled_mats = [shuffled[i] for i in rec_shuffled[0]]
        # Actual material per layer must match (same recipe, just different
        # integer encoding).
        assert [m.name for m in original_mats] == [m.name for m in shuffled_mats]

    def test_lookup_prefers_best_actual_color_across_nearby_cells(self):
        target = np.asarray([[168, 168, 168]], dtype=np.uint8)
        target_lab = rgb_to_lab(target).astype(np.float32)[0]
        cache = MaterialSolverCache(
            lab_centers=np.asarray(
                [
                    target_lab + np.asarray([0.1, 0.0, 0.0], dtype=np.float32),
                    target_lab + np.asarray([0.9, 0.0, 0.0], dtype=np.float32),
                ],
                dtype=np.float32,
            ),
            recipes=np.asarray(
                [
                    [0, 0, 0, 0, 0],
                    [2, 2, 2, 2, 2],
                ],
                dtype=np.uint8,
            ),
            achieved_srgb=np.asarray(
                [
                    [172, 169, 174],
                    [168, 168, 168],
                ],
                dtype=np.uint8,
            ),
            center_delta_e=np.asarray([0.1, 0.9], dtype=np.float32),
            metadata={
                "palette_hash": fingerprint_palette(SMALL_PALETTE),
                "layer_count": 5,
                "layer_height_mm": 0.08,
                "substrate": "white",
                "grid_resolution": 32,
            },
        )

        matched, recipes, delta_e = cache.lookup(target, SMALL_PALETTE)

        np.testing.assert_array_equal(
            matched,
            np.asarray([[168, 168, 168]], dtype=np.uint8),
        )
        expected_user_idx = canonical_palette_order(SMALL_PALETTE)[2]
        np.testing.assert_array_equal(
            recipes,
            np.full((1, 5), expected_user_idx, dtype=np.int32),
        )
        assert float(delta_e[0]) == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Listing / deletion
# ---------------------------------------------------------------------------


class TestListingAndDeletion:
    def test_list_empty_directory_returns_empty(self, tmp_path: Path):
        assert list_cached_entries(cache_root=tmp_path) == []

    def test_list_after_save(self, tmp_path: Path):
        cache = build_material_solver_cache(
            SMALL_PALETTE, 5, 0.08, "white", grid_resolution=32,
        )
        save_material_solver_cache(cache, cache_root=tmp_path)
        entries = list_cached_entries(cache_root=tmp_path)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["palette_hash"] == cache.palette_hash
        assert entry["layer_count"] == 5
        assert entry["substrate"] == "white"
        assert entry["cache_file_size_bytes"] > 0
        assert "cache_file_path" in entry
        assert "cache_meta_path" in entry

    def test_delete_removes_npz_and_meta(self, tmp_path: Path):
        cache = build_material_solver_cache(
            SMALL_PALETTE, 5, 0.08, "white", grid_resolution=32,
        )
        save_material_solver_cache(cache, cache_root=tmp_path)
        npz_path = cache_file_path(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=32, cache_root=tmp_path,
        )
        meta_path = npz_path.with_suffix(".meta.json")
        assert npz_path.exists() and meta_path.exists()

        removed = delete_cached_entry(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=32, cache_root=tmp_path,
        )
        assert removed is True
        assert not npz_path.exists()
        assert not meta_path.exists()

    def test_delete_returns_false_when_absent(self, tmp_path: Path):
        result = delete_cached_entry(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=32, cache_root=tmp_path,
        )
        assert result is False


# ---------------------------------------------------------------------------
# Sanity: achieved color is deterministic and matches metadata statistics
# ---------------------------------------------------------------------------


class TestInternalConsistency:
    def test_metadata_statistics_match_arrays(self):
        cache = build_material_solver_cache(
            SMALL_PALETTE, 5, 0.08, "white", grid_resolution=32,
        )
        assert cache.metadata["valid_cell_count"] == cache.valid_cell_count
        if cache.valid_cell_count > 0:
            assert cache.metadata["mean_delta_e"] == pytest.approx(
                float(cache.center_delta_e.mean()), rel=1e-4
            )
            assert cache.metadata["max_delta_e"] == pytest.approx(
                float(cache.center_delta_e.max()), rel=1e-4
            )

    def test_default_grid_resolution_constant(self):
        # Low-density is the shipped default so the build cost stays within the
        # budget every user pays without opting in. Upgrading the default is a
        # UX choice that should flip this assertion together with the UI.
        assert DEFAULT_GRID_RESOLUTION == 64

    def test_allowed_grid_resolutions_whitelist(self):
        from core.material_cache import ALLOWED_GRID_RESOLUTIONS

        # Whitelist exposes exactly three tiers ("low/medium/high" in the UI);
        # adding a tier requires matching translation/UI/settings changes.
        assert ALLOWED_GRID_RESOLUTIONS == (64, 128, 256)
        assert DEFAULT_GRID_RESOLUTION in ALLOWED_GRID_RESOLUTIONS


# ---------------------------------------------------------------------------
# find_any_cached_grid + load_material_solver_cache_with_fallback
# ---------------------------------------------------------------------------


class TestFindAnyCachedGrid:
    """Verify directory-scanning grid discovery."""

    def test_empty_directory_returns_empty(self, tmp_path: Path):
        result = find_any_cached_grid(
            SMALL_PALETTE, 5, 0.08, "white", cache_root=tmp_path,
        )
        assert result == []

    def test_finds_single_suffixed_cache(self, tmp_path: Path):
        cache = build_material_solver_cache(
            SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white", grid_resolution=32,
        )
        save_material_solver_cache(cache, cache_root=tmp_path)
        result = find_any_cached_grid(
            SMALL_PALETTE, 5, 0.08, "white", cache_root=tmp_path,
        )
        assert len(result) == 1
        assert result[0][0] == 32

    def test_finds_multiple_grids_sorted_descending(self, tmp_path: Path):
        for grid in (16, 32):
            cache = build_material_solver_cache(
                SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
                substrate="white", grid_resolution=grid,
            )
            save_material_solver_cache(cache, cache_root=tmp_path)
        result = find_any_cached_grid(
            SMALL_PALETTE, 5, 0.08, "white", cache_root=tmp_path,
        )
        grids = [g for g, _ in result]
        assert grids == [32, 16], "should be sorted descending"

    def test_different_palette_not_found(self, tmp_path: Path):
        cache = build_material_solver_cache(
            SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white", grid_resolution=32,
        )
        save_material_solver_cache(cache, cache_root=tmp_path)
        result = find_any_cached_grid(
            MEDIUM_PALETTE, 5, 0.08, "white", cache_root=tmp_path,
        )
        assert result == []


class TestLoadWithFallback:
    """Verify the requested-grid-first, any-grid-fallback loader."""

    def test_exact_hit_returns_requested_grid(self, tmp_path: Path):
        cache = build_material_solver_cache(
            SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white", grid_resolution=32,
        )
        save_material_solver_cache(cache, cache_root=tmp_path)
        loaded, actual_grid = load_material_solver_cache_with_fallback(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=32, cache_root=tmp_path,
        )
        assert loaded is not None
        assert actual_grid == 32

    def test_fallback_to_different_grid(self, tmp_path: Path):
        # Build only grid=32; request grid=64 — should fall back to 32.
        cache = build_material_solver_cache(
            SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white", grid_resolution=32,
        )
        save_material_solver_cache(cache, cache_root=tmp_path)
        loaded, actual_grid = load_material_solver_cache_with_fallback(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=64, cache_root=tmp_path,
        )
        assert loaded is not None
        assert actual_grid == 32, "should fall back to the only available grid"

    def test_fallback_prefers_finer_grid(self, tmp_path: Path):
        # Build both 16 and 32; request 64 — should fall back to 32 (finer).
        for grid in (16, 32):
            c = build_material_solver_cache(
                SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
                substrate="white", grid_resolution=grid,
            )
            save_material_solver_cache(c, cache_root=tmp_path)
        loaded, actual_grid = load_material_solver_cache_with_fallback(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=64, cache_root=tmp_path,
        )
        assert loaded is not None
        assert actual_grid == 32, "finer grid should be preferred"

    def test_returns_none_when_no_cache_exists(self, tmp_path: Path):
        loaded, actual_grid = load_material_solver_cache_with_fallback(
            SMALL_PALETTE, 5, 0.08, "white",
            grid_resolution=64, cache_root=tmp_path,
        )
        assert loaded is None
        assert actual_grid is None
