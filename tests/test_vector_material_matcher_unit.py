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

import logging

import numpy as np
import pytest
from shapely.geometry import box

from core.task_parallelism import AdaptiveParallelismPlan
from core.vector_engine import VectorProcessor
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
        self.mode = "stub"
        self.valid_cell_count = 0
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


class _ParallelSolverCache(_StubSolverCache):
    """Solver stub that records the effective inner parallelism keyword."""

    def __init__(self, layer_count: int):
        super().__init__(layer_count)
        self.observed_parallelism: list[int] = []
        self.returned_results: list[
            tuple[np.ndarray, np.ndarray, np.ndarray]
        ] = []

    def lookup(
        self,
        unique_colors: np.ndarray,
        materials,
        *,
        hue_weight: float = 0.0,
        neighbor_coherence: float = 0.5,
        parallelism: int = 1,
    ):
        del neighbor_coherence
        self.observed_parallelism.append(int(parallelism))
        result = super().lookup(
            unique_colors,
            materials,
            hue_weight=hue_weight,
        )
        self.returned_results.append(tuple(value.copy() for value in result))
        return result


def _parallelism_plan(
    workers: int,
    *,
    limiting_reason: str = "requested",
    outer_demand: int = 1,
) -> AdaptiveParallelismPlan:
    """Build a deterministic plan for matcher adoption tests."""

    effective_cpu = max(1, workers * outer_demand)
    return AdaptiveParallelismPlan(
        workers=workers,
        requested_ceiling=max(1, workers),
        effective_cpu_capacity=effective_cpu,
        outer_demand=outer_demand,
        cpu_fair_share_ceiling=max(1, effective_cpu // outer_demand),
        work_item_ceiling=40,
        work_unit_ceiling=4,
        stage_ceiling=4,
        memory_ceiling=max(1, workers),
        available_memory_bytes=8 * 1024**3,
        estimated_worker_bytes=256 * 1024**2,
        limiting_reason=limiting_reason,
        demand_snapshot_fallback=False,
    )


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

    def test_info_summary_is_bounded_and_excludes_source_colors(self, caplog):
        m = _build_matcher(layer_count=4, materials_count=3)
        target_logger = logging.getLogger("lumina.core.vector_matchers")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.INFO, logger=target_logger.name)
        try:
            m.solve_for_fills([(1, 2, 3), (4, 5, 6)])
        finally:
            target_logger.removeHandler(caplog.handler)

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "material_vector_solve_summary"
        ]
        assert len(records) == 1
        assert records[0].color_count == 2
        assert records[0].getMessage() == "material vector solve summary: 2 colors"
        assert "#010203" not in records[0].getMessage()

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

    def test_exact_source_colors_keep_their_own_recipes_when_lab_rows_collide(self):
        """Exact material fills must not inherit a colliding colour's recipe."""

        first_rgb = (73, 92, 134)
        second_rgb = (73, 92, 135)
        matcher = _build_matcher(layer_count=5, materials_count=4)
        matcher.solve_for_fills([first_rgb, second_rgb])

        first_lab = matcher._rgb_to_lab(np.array([first_rgb], dtype=np.uint8))
        second_lab = matcher._rgb_to_lab(np.array([second_rgb], dtype=np.uint8))
        np.testing.assert_array_equal(first_lab, second_lab)

        processor = VectorProcessor.from_img_processor(
            matcher,
            color_mode="Material Archive",
        )
        matched = processor._match_colors(
            [
                {"geometry": box(0, 0, 1, 1), "color": first_rgb},
                {"geometry": box(2, 0, 3, 1), "color": second_rgb},
            ],
            replacement_manager=None,
            num_channels=4,
            num_layers=5,
        )

        row_by_rgb = {
            tuple(int(value) for value in rgb): index
            for index, rgb in enumerate(matcher.lut_rgb)
        }
        for item in matched:
            expected_index = row_by_rgb[item["color"]]
            assert item["lut_idx"] == expected_index
            np.testing.assert_array_equal(
                item["recipe"],
                matcher.ref_stacks[expected_index],
            )

    def test_resolves_and_forwards_vector_parallelism(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.vector_matchers as vector_matchers

        matcher = _build_matcher(layer_count=4, materials_count=3)
        runtime = _ParallelSolverCache(layer_count=4)
        matcher._solver_cache = runtime  # noqa: SLF001
        policy_calls: list[dict[str, int | str | None]] = []

        def _resolve(
            workload: str,
            *,
            work_items: int,
            min_parallel_items: int,
            hard_max_workers: int | None,
            work_units: int,
            min_parallel_work_units: int,
            work_units_per_worker: int,
            estimated_worker_bytes: int,
        ) -> AdaptiveParallelismPlan:
            policy_calls.append(
                {
                    "workload": workload,
                    "work_items": work_items,
                    "min_parallel_items": min_parallel_items,
                    "hard_max_workers": hard_max_workers,
                    "work_units": work_units,
                    "min_parallel_work_units": min_parallel_work_units,
                    "work_units_per_worker": work_units_per_worker,
                    "estimated_worker_bytes": estimated_worker_bytes,
                },
            )
            return _parallelism_plan(
                3,
                limiting_reason="cpu_fair_share",
            )

        monkeypatch.setattr(
            vector_matchers,
            "resolve_task_parallelism_plan",
            _resolve,
        )

        matcher.solve_for_fills(
            [(10, 20, 30), (20, 30, 40), (30, 40, 50), (40, 50, 60)],
        )

        assert policy_calls == [
            {
                "workload": "vector",
                "work_items": 4,
                "min_parallel_items": 2,
                "hard_max_workers": None,
                "work_units": 4,
                "min_parallel_work_units": 32,
                "work_units_per_worker": 16,
                "estimated_worker_bytes": 256 * 1024**2,
            }
        ]
        assert runtime.observed_parallelism == [3]
        assert matcher.effective_parallelism_workers == 3
        assert matcher.effective_parallelism_plan == _parallelism_plan(
            3,
            limiting_reason="cpu_fair_share",
        )

    def test_parallelism_keyword_is_filtered_for_legacy_runtime(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.vector_matchers as vector_matchers

        matcher = _build_matcher()
        monkeypatch.setattr(
            vector_matchers,
            "resolve_task_parallelism_plan",
            lambda *args, **kwargs: _parallelism_plan(4),
        )

        matcher.solve_for_fills([(10, 20, 30), (20, 30, 40)])

        assert matcher.lut_rgb.shape == (2, 3)

    def test_serial_and_parallel_solver_outputs_are_byte_identical(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Worker allocation must not alter colors, recipes, or deltas."""

        import core.vector_matchers as vector_matchers

        fills = [
            (10, 20, 30),
            (20, 30, 40),
            (30, 40, 50),
            (40, 50, 60),
        ]
        serial = _build_matcher(layer_count=4, materials_count=3)
        serial_runtime = _ParallelSolverCache(layer_count=4)
        serial._solver_cache = serial_runtime  # noqa: SLF001
        monkeypatch.setattr(
            vector_matchers,
            "resolve_task_parallelism_plan",
            lambda *args, **kwargs: _parallelism_plan(1),
        )
        serial.solve_for_fills(fills)

        parallel = _build_matcher(layer_count=4, materials_count=3)
        parallel_runtime = _ParallelSolverCache(layer_count=4)
        parallel._solver_cache = parallel_runtime  # noqa: SLF001
        monkeypatch.setattr(
            vector_matchers,
            "resolve_task_parallelism_plan",
            lambda *args, **kwargs: _parallelism_plan(3),
        )
        parallel.solve_for_fills(fills)

        assert serial_runtime.observed_parallelism == [1]
        assert parallel_runtime.observed_parallelism == [3]
        for serial_value, parallel_value in zip(
            serial_runtime.returned_results[0],
            parallel_runtime.returned_results[0],
            strict=True,
        ):
            assert serial_value.tobytes() == parallel_value.tobytes()
        assert serial.lut_rgb.tobytes() == parallel.lut_rgb.tobytes()
        assert serial.ref_stacks.tobytes() == parallel.ref_stacks.tobytes()
        assert serial._fill_lab.tobytes() == parallel._fill_lab.tobytes()  # noqa: SLF001

    def test_invalid_vector_parallelism_uses_automatic_policy(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.task_parallelism as task_parallelism
        from core.system_capacity import EffectiveCpuCapacity

        matcher = _build_matcher(layer_count=4, materials_count=3)
        runtime = _ParallelSolverCache(layer_count=4)
        matcher._solver_cache = runtime  # noqa: SLF001
        monkeypatch.setattr(task_parallelism.os, "cpu_count", lambda: 8)
        monkeypatch.setattr(
            task_parallelism,
            "get_effective_cpu_capacity",
            lambda: EffectiveCpuCapacity(
                host_cpu_count=8,
                affinity_cpu_count=None,
                cgroup_quota_cpu_count=None,
                apple_performance_cpu_count=None,
                effective_cpu_count=8,
                limiting_source="host_fallback",
            ),
        )
        monkeypatch.setattr(
            task_parallelism,
            "_available_memory_bytes",
            lambda: 16 * 1024**3,
        )
        monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "invalid")
        monkeypatch.setenv("LUMINA_MAX_WORKERS", "2")
        task_parallelism._WARNED_INVALID_VALUES.clear()

        matcher.solve_for_fills(
            [(index, index + 1, index + 2) for index in range(40)],
        )

        assert runtime.observed_parallelism == [3]

    def test_full_coverage_runtime_applies_not_worse_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        m = _build_matcher(layer_count=6, materials_count=3)
        m._solver_cache.mode = "candidate_hybrid"  # noqa: SLF001
        m._solver_cache.valid_cell_count = 3**6  # noqa: SLF001

        improved_b2t = np.asarray([[2, 2, 1, 1, 0, 0]], dtype=np.int32)
        calls = {"n": 0}

        def fake_fallback(
            unique_colors,
            materials,
            baseline_matched_rgb,
            baseline_recipes,
            baseline_delta_e,
            **kwargs,
        ):
            calls["n"] += 1
            assert kwargs["target_layer_count"] == 6
            assert unique_colors.tolist() == [[10, 20, 30]]
            assert baseline_recipes.shape == (1, 6)
            return (
                np.asarray([[11, 21, 31]], dtype=np.uint8),
                improved_b2t,
                np.asarray([0.5], dtype=np.float64),
                {
                    "applied": True,
                    "improved_pixels": 1,
                    "mean_delta_e_before": 4.0,
                    "max_delta_e_before": 4.0,
                    "mean_delta_e_after": 0.5,
                    "max_delta_e_after": 0.5,
                },
            )

        monkeypatch.setattr(
            "core.material_lut_synthesis.ensure_not_worse_than_smaller_N",
            fake_fallback,
        )

        m.solve_for_fills([(10, 20, 30)])

        assert calls["n"] == 1
        np.testing.assert_array_equal(
            m.lut_rgb[0],
            np.asarray([11, 21, 31], dtype=np.uint8),
        )
        np.testing.assert_array_equal(
            m.ref_stacks[0],
            np.asarray([0, 0, 1, 1, 2, 2], dtype=np.int32),
        )


class TestMaterialVectorMatcherDynamicGeometry:
    """Native SVG dynamic layers use clipped geometry, not raster fallback."""

    def test_dynamic_solver_receives_relative_clipped_geometry_coverage(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: dict[str, object] = {}

        def fake_solve_dynamic_material_targets(**kwargs):
            calls.update(kwargs)
            unique_colors = kwargs["unique_colors"]
            assert unique_colors.tolist() == [[10, 20, 30], [200, 210, 220]]
            return (
                np.asarray([[11, 21, 31], [201, 211, 221]], dtype=np.uint8),
                np.asarray(
                    [
                        [1, 1, 1, 1, 0, 0, 0],
                        [2, 2, 2, 2, 2, 2, 2],
                    ],
                    dtype=np.int32,
                ),
                np.asarray([0.1, 0.2], dtype=np.float64),
                {
                    "enabled": True,
                    "min_layer_count": 5,
                    "max_layer_count": 7,
                    "colors": [
                        {
                            "target_srgb": [10, 20, 30],
                            "matched_srgb": [11, 21, 31],
                            "actual_layer_count": 4,
                            "padding_layer_count": 3,
                            "actual_recipe_top_to_bottom": [1, 1, 1, 1],
                            "print_recipe_top_to_bottom": [1, 1, 1, 1, 0, 0, 0],
                        },
                        {
                            "target_srgb": [200, 210, 220],
                            "matched_srgb": [201, 211, 221],
                            "actual_layer_count": 7,
                            "padding_layer_count": 0,
                            "actual_recipe_top_to_bottom": [2] * 7,
                            "print_recipe_top_to_bottom": [2] * 7,
                        },
                    ],
                    "benefit_curve": [],
                },
                {"dynamic_engine": "exact"},
            )

        monkeypatch.setattr(
            "core.pipeline.material_dynamic_layers.solve_dynamic_material_targets",
            fake_solve_dynamic_material_targets,
        )
        matcher = MaterialVectorMatcher(
            materials=[object(), object(), object()],
            layer_count=7,
            layer_height_mm=0.08,
            substrate="white",
            slot_names=["Base", "Red", "Blue"],
            preview_colors={},
            color_conf={},
            dynamic_layer_count_enabled=True,
            dynamic_min_layer_count=5,
            dynamic_max_layer_count=7,
            dynamic_delta_e00_tolerance=0.5,
            backing_material_index=0,
        )

        matcher.solve_for_clipped_shapes(
            [
                {"color": (10, 20, 30), "geometry": box(0, 0, 4, 2)},
                {"color": (200, 210, 220), "geometry": box(0, 0, 1, 1)},
            ],
            scale_factor=1.0,
        )

        counts = np.asarray(calls["pixel_counts"], dtype=np.int64)
        assert counts.tolist() == [8_000_000, 1_000_000]
        assert matcher.layer_count == 7
        assert matcher.ref_stacks.dtype == np.int32
        np.testing.assert_array_equal(
            matcher.ref_stacks[0],
            np.asarray([1, 1, 1, 1, 0, 0, 0], dtype=np.int32),
        )
        dynamic_info = matcher.dynamic_layer_info
        assert dynamic_info is not None
        assert dynamic_info["coverage_source"] == "native_svg_geometry"
        assert matcher.dynamic_metadata_for_fill((10, 20, 30))["actual_layer_count"] == 4


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
