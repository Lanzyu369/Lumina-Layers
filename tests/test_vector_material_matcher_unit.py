"""Unit tests for :class:`core.vector_matchers.MaterialVectorMatcher`.

These tests pin the duck-typed surface that
:class:`core.vector_engine.VectorProcessor` consumes when running the
material-archive backed vector pipeline. The contract is intentionally
narrow: the matcher must look like ``LuminaImageProcessor`` to the
vector engine while routing colour matching through the material
solver cache.

锁定耗材档案版本矢量颜色匹配器的鸭型契约：必须满足
``VectorProcessor.analyze_svg`` / ``_match_colors`` 所读取字段的
形状与语义，配方按 Top2Bottom 排列并裁切到 ``layer_count``。
"""

from __future__ import annotations

import numpy as np
import pytest

from core.vector_matchers import (
    MATERIAL_ARCHIVE_LUT_SENTINEL,
    MaterialVectorMatcher,
)


class _StubSolverCache:
    """Minimal stand-in for :class:`core.material_cache.MaterialSolverCache`.

    Returns deterministic recipes (``[i, i, ...]`` per query colour) and
    matched RGBs equal to the queries themselves, so unit tests can
    verify reshape / reverse / pad logic without depending on the real
    Beer-Lambert solver.

    单测用最小 stub：matched_rgb 直接回传查询色，recipes 用查询行号
    填充，验证矩阵形状/反转/填充语义。
    """

    def __init__(self, layer_count: int):
        self.layer_count = int(layer_count)
        self.metadata = {"mean_delta_e": 0.0, "max_delta_e": 0.0}

    def lookup(self, unique_colors: np.ndarray, materials, *, hue_weight: float = 0.0):
        n = unique_colors.shape[0]
        matched_rgb = unique_colors.astype(np.uint8, copy=True)
        # Bottom2Top recipe: row i -> [i % len(materials)] * layer_count
        # Use distinct values per layer so reversal is observable.
        recipes_b2t = np.zeros((n, self.layer_count), dtype=np.int32)
        for i in range(n):
            for z in range(self.layer_count):
                recipes_b2t[i, z] = (i + z) % max(1, len(materials))
        delta_e = np.zeros((n,), dtype=np.float64)
        return matched_rgb, recipes_b2t, delta_e


def _build_matcher(*, layer_count: int = 5, materials_count: int = 4) -> MaterialVectorMatcher:
    materials = [object() for _ in range(materials_count)]
    slot_names = [f"M{i}" for i in range(materials_count)]
    preview_colors = {i: (i * 30, i * 30, i * 30, 255) for i in range(materials_count)}
    color_conf = {
        "name": "Material",
        "slots": slot_names,
        "preview": preview_colors,
        "map": {name: idx for idx, name in enumerate(slot_names)},
    }
    return MaterialVectorMatcher(
        materials=materials,
        layer_count=layer_count,
        layer_height_mm=0.08,
        substrate="white",
        slot_names=slot_names,
        preview_colors=preview_colors,
        color_conf=color_conf,
        solver_cache=_StubSolverCache(layer_count=layer_count),
        actual_grid_resolution=64,
    )


class TestMaterialVectorMatcherSurface:
    """The matcher must duck-type LuminaImageProcessor for VectorProcessor."""

    def test_lut_path_is_sentinel(self):
        m = _build_matcher()
        assert m.lut_path == MATERIAL_ARCHIVE_LUT_SENTINEL
        assert not m.lut_path.endswith((".json", ".msgpack"))

    def test_color_mode_is_material_archive(self):
        assert _build_matcher().color_mode == "Material Archive"

    def test_initial_tables_are_empty(self):
        m = _build_matcher()
        assert m.lut_rgb.shape == (0, 3)
        assert m.lut_rgb.dtype == np.uint8
        assert m.ref_stacks.shape == (0, 5)
        assert m.ref_stacks.dtype == np.int32
        assert m.kdtree is None

    def test_color_conf_is_independent_copy(self):
        m = _build_matcher()
        conf = m.color_conf
        conf["mutated"] = True
        assert "mutated" not in m.color_conf, "color_conf must be defensively copied"


class TestMaterialVectorMatcherSolveForFills:
    def test_basic_solve_populates_tables(self):
        m = _build_matcher(layer_count=4, materials_count=3)
        fills = [(255, 0, 0), (0, 255, 0)]

        m.solve_for_fills(fills)

        assert m.lut_rgb.shape == (2, 3)
        assert m.ref_stacks.shape == (2, 4)
        assert m.kdtree is not None

    def test_recipes_are_top2bottom_after_reversal(self):
        # Stub returns Bottom2Top recipes ``[i, i+1, i+2, ...]``;
        # matcher must flip to Top2Bottom so ``recipe[0]`` is the
        # visible face — the convention vector_engine extrudes from.
        m = _build_matcher(layer_count=5, materials_count=4)
        m.solve_for_fills([(10, 20, 30)])
        # Bottom2Top from stub (row 0): [0, 1, 2, 3, 0]
        # Top2Bottom expected:           [0, 3, 2, 1, 0]
        np.testing.assert_array_equal(
            m.ref_stacks[0],
            np.array([0, 3, 2, 1, 0], dtype=np.int32),
        )

    def test_repeated_solve_is_idempotent(self):
        m = _build_matcher()
        m.solve_for_fills([(255, 0, 0)])
        first_lut = m.lut_rgb.copy()
        first_recipes = m.ref_stacks.copy()

        m.solve_for_fills([(255, 0, 0)])  # same colour again
        np.testing.assert_array_equal(m.lut_rgb, first_lut)
        np.testing.assert_array_equal(m.ref_stacks, first_recipes)

    def test_solve_extends_table_with_new_colors(self):
        m = _build_matcher()
        m.solve_for_fills([(255, 0, 0)])
        m.solve_for_fills([(0, 0, 255)])
        assert m.lut_rgb.shape[0] == 2
        # The KDTree is rebuilt over the union; both colours must be
        # discoverable by exact-match Lab query.
        for rgb in [(255, 0, 0), (0, 0, 255)]:
            lab = MaterialVectorMatcher._rgb_to_lab(np.array([rgb], dtype=np.uint8))
            dist, _idx = m.kdtree.query(lab)
            assert dist[0] < 1e-3

    def test_solve_handles_short_recipes_by_padding(self):
        # When the solver returns a recipe shorter than ``layer_count``
        # (e.g. cache configured with smaller layer_count), the matcher
        # pads with the substrate-adjacent channel so the recipe never
        # has -1 sentinels reaching downstream extrusion.
        # 配方比 layer_count 短时按底层颜色填充而非 -1。
        m = _build_matcher(layer_count=6, materials_count=3)
        # Stub ignores layer_count of matcher and uses its own — make
        # them disagree to exercise the pad path.
        m._solver_cache = _StubSolverCache(layer_count=4)  # noqa: SLF001 — test-only

        m.solve_for_fills([(100, 100, 100)])
        # recipe length must equal layer_count, last column == padding
        assert m.ref_stacks.shape == (1, 6)
        # Bottom2Top from stub (row 0, layer_count=4): [0, 1, 2, 0]
        # Top2Bottom:                                   [0, 2, 1, 0]
        # Padded to 6 with bottom-most (=0) at the substrate end:
        # [0, 2, 1, 0, 0, 0]
        np.testing.assert_array_equal(
            m.ref_stacks[0],
            np.array([0, 2, 1, 0, 0, 0], dtype=np.int32),
        )

    def test_solve_truncates_long_recipes(self):
        m = _build_matcher(layer_count=3, materials_count=3)
        # Stub returns 5-layer recipe; matcher must truncate to 3.
        m._solver_cache = _StubSolverCache(layer_count=5)  # noqa: SLF001

        m.solve_for_fills([(50, 50, 50)])
        assert m.ref_stacks.shape == (1, 3)

    def test_kdtree_query_returns_nearest_index(self):
        # Direct query of the KDTree must round-trip exact RGBs to the
        # corresponding row in lut_rgb / ref_stacks.
        # KDTree 直接命中：查询色 → 对应表行索引。
        m = _build_matcher()
        m.solve_for_fills([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
        for expected_idx, rgb in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
            # solve_for_fills sorts colours, so re-derive expected idx
            sorted_keys = sorted([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
            expected_idx = sorted_keys.index(rgb)
            lab = MaterialVectorMatcher._rgb_to_lab(np.array([rgb], dtype=np.uint8))
            _dist, idx = m.kdtree.query(lab)
            assert int(idx[0]) == expected_idx


class TestMaterialVectorMatcherIgnoresInvalidInput:
    def test_solve_ignores_malformed_entries(self):
        m = _build_matcher()
        m.solve_for_fills([
            (255, 0, 0),
            None,            # malformed
            "abc",           # malformed
            (0, 255, 0),
        ])
        assert m.lut_rgb.shape[0] == 2

    def test_solve_clamps_out_of_range_channels(self):
        m = _build_matcher()
        m.solve_for_fills([(300, -10, 128)])  # clamped to (255, 0, 128)
        assert m.lut_rgb.shape[0] == 1
        # exact-match Lab query against the clamped colour
        lab = MaterialVectorMatcher._rgb_to_lab(np.array([(255, 0, 128)], dtype=np.uint8))
        dist, _idx = m.kdtree.query(lab)
        assert dist[0] < 1e-3

    def test_solve_with_empty_input_is_noop(self):
        m = _build_matcher()
        m.solve_for_fills([])
        assert m.lut_rgb.shape == (0, 3)
        assert m.kdtree is None


class TestMaterialVectorMatcherFactory:
    def test_from_materials_uses_candidate_runtime_resolver_without_bucketed_builder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import core.material_lut_provider as provider

        runtime_stub = _StubSolverCache(layer_count=5)
        calls = {"runtime": 0}

        def fake_load_solver_runtime(*args, **kwargs):
            calls["runtime"] += 1
            return runtime_stub, 64

        monkeypatch.setattr(provider, "load_solver_runtime", fake_load_solver_runtime)
        monkeypatch.setattr(
            "core.material_cache.load_material_solver_cache_with_fallback",
            lambda *args, **kwargs: (None, None),
        )
        monkeypatch.setattr(
            "core.material_cache.build_material_solver_cache",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("vector fallback must not call old bucketed builder")
            ),
        )

        materials = [object() for _ in range(3)]
        preview_colors = {
            0: (0, 0, 0, 255),
            1: (80, 80, 80, 255),
            2: (160, 160, 160, 255),
        }
        matcher = MaterialVectorMatcher.from_materials(
            materials=materials,
            layer_count=5,
            layer_height_mm=0.08,
            substrate="white",
            slot_names=["M0", "M1", "M2"],
            preview_colors=preview_colors,
            color_conf={
                "name": "Material",
                "slots": ["M0", "M1", "M2"],
                "preview": preview_colors,
                "map": {"M0": 0, "M1": 1, "M2": 2},
            },
            grid_resolution=64,
        )

        assert matcher._solver_cache is runtime_stub  # noqa: SLF001
        assert calls["runtime"] == 1
