"""Vector pipeline color matchers.
矢量管线颜色匹配器适配器。

This module provides duck-typed adapters consumed by
:class:`core.vector_engine.VectorProcessor` so the same SVG-native
parse / clip / extrude / preview pipeline can be driven by either a
LUT (the historical default, handled by
:class:`core.image_processing.LuminaImageProcessor`) or by the
material-archive Beer-Lambert solver.

The adapter exposes the small slice of ``LuminaImageProcessor``'s
public surface that ``VectorProcessor`` actually reads:

- ``lut_path`` — opaque sentinel string, only used by ``analyze_svg``
  to decide whether to load palette metadata from a JSON/msgpack file.
- ``color_mode`` — display string echoed by logs and preview titles.
- ``lut_rgb`` — ``(N, 3) uint8`` table of solver-matched colours, one
  row per pre-solved fill.
- ``ref_stacks`` — ``(N, layer_count) int32`` Top2Bottom recipes, one
  row per pre-solved fill (``recipe[0]`` is the visible face,
  ``recipe[-1]`` sits next to the substrate — same convention as
  ``image_processing.LuminaImageProcessor``).
- ``kdtree`` — :class:`scipy.spatial.KDTree` over Lab of the
  pre-solved fills. ``VectorProcessor._match_colors`` queries this
  per shape's fill RGB.
- ``_rgb_to_lab(rgb_array)`` — same colour-space helper as
  ``LuminaImageProcessor._rgb_to_lab``.
- ``color_conf`` — pre-built ``{slots, preview, name, map}`` dict
  derived from the materials list. ``VectorProcessor.analyze_svg``
  reads this in material mode instead of calling
  :func:`config.ColorSystem.get`.

Lazily-extensible design: ``solve_for_fills(rgbs)`` adds new colours
to the internal table and rebuilds the KDTree. ``VectorProcessor``
calls it once after occlusion clipping with the unique SVG fill
colours. Helpers that introduce new colours (e.g. region-replace
overrides) can call it again before issuing further KDTree queries.

VectorProcessor 使用的 ImageProcessor 鸭型表面在此被 Material
Beer-Lambert 求解器实现。色板/预览色/插槽名直接从耗材清单构造，
KDTree 建立在已求解填充色的 Lab 上；后续若再有新颜色（例如区域改
色端点引入的目标色），调用 ``solve_for_fills`` 即可懒求解并刷新表。
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Iterable

import numpy as np

from api.structured_logging import get_logger
from core.task_parallelism import (
    AdaptiveParallelismPlan,
    resolve_task_parallelism_plan,
)

if TYPE_CHECKING:
    from core.material_color_solver import MaterialParams

_log = get_logger(__name__)

MATERIAL_ARCHIVE_LUT_SENTINEL = "__material_archive__"
_MIN_PARALLEL_VECTOR_FILL_COUNT = 32
_VECTOR_MATERIAL_WORK_UNITS_PER_WORKER = 16
_ESTIMATED_VECTOR_WORKER_BYTES = 256 * 1024**2


def _rgb_to_lab_static(rgb_array: np.ndarray) -> np.ndarray:
    """Mirror of :meth:`LuminaImageProcessor._rgb_to_lab` for the matcher.

    Kept as a free function so the adapter does not need to import
    :mod:`core.image_processing` (importing that module pulls in the
    full LUT loading stack which is irrelevant in material mode).

    与 ``LuminaImageProcessor._rgb_to_lab`` 行为一致，但避免引入
    LUT 加载依赖；material 模式下不需要 LUT 解析栈。

    Args:
        rgb_array: ``(N, 3)`` or ``(H, W, 3)`` uint8 RGB array.

    Returns:
        ``float64`` Lab array with the same shape as input.
    """
    import cv2

    original_shape = rgb_array.shape
    if rgb_array.ndim == 2:
        rgb_3d = rgb_array.reshape(1, -1, 3).astype(np.uint8)
    else:
        rgb_3d = rgb_array.astype(np.uint8)
    bgr = cv2.cvtColor(rgb_3d, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64)
    if len(original_shape) == 2:
        return lab.reshape(original_shape)
    return lab


class MaterialVectorMatcher:
    """Material-archive backed matcher for the vector pipeline.

    See module docstring for the full interface contract. Construct via
    :meth:`from_materials` so the underlying
    :class:`core.material_cache.MaterialSolverCache` is resolved (or
    built on the fly) consistently with
    :func:`core.pipeline.p03_core_processing._run_material_archive_branch`.

    耗材档案版本的矢量颜色匹配器：在矢量管线里替代 LUT KDTree。预先
    求解 SVG 填充色板，再以鸭型方式暴露 ``LuminaImageProcessor``
    所需字段，使 ``VectorProcessor`` 主体逻辑零改动地复用整套
    解析/裁剪/挤出/预览流程。
    """

    def __init__(
        self,
        *,
        materials: list["MaterialParams"],
        layer_count: int,
        layer_height_mm: float,
        substrate: str,
        slot_names: list[str],
        preview_colors: dict,
        color_conf: dict,
        solver_cache=None,
        actual_grid_resolution: int = 0,
        hue_weight: float = 0.0,
        neighbor_coherence: float = 0.5,
        dynamic_layer_count_enabled: bool = False,
        dynamic_min_layer_count: int = 5,
        dynamic_max_layer_count: int | None = None,
        dynamic_delta_e00_tolerance: float = 0.5,
        backing_material_index: int = 0,
    ):
        """Use :meth:`from_materials` for normal construction.

        Args:
            materials: Selected ``MaterialParams`` list (ordered).
            layer_count: Effective recipe length (same as the raster
                ``material_archive`` path).
            layer_height_mm: Layer thickness in mm.
            substrate: ``"white"`` / ``"black"`` etc.
            slot_names: Pre-built material slot name list — must match
                ``materials`` ordering so ``ref_stacks`` indices stay
                consistent with downstream voxel/extrude code.
            preview_colors: ``{idx: (r, g, b, a)}`` mapping for the
                preview canvas.
            color_conf: ``{slots, preview, name, map}`` dict mirroring
                :func:`config.ColorSystem.get` output shape.
            solver_cache: Pre-resolved
                :class:`core.material_cache.MaterialSolverCache`
                (loaded or built on the fly).
            actual_grid_resolution: Grid resolution actually used by
                ``solver_cache`` (may differ from request when fallback
                kicked in). Recorded for diagnostics.
            dynamic_layer_count_enabled: Use the exact dynamic solver instead
                of the fixed-depth material cache.
            dynamic_min_layer_count: Lower bound for the effective recipe
                depth when dynamic solving is enabled.
            dynamic_max_layer_count: Physical printed depth for dynamic
                recipes. Defaults to ``layer_count``.
            dynamic_delta_e00_tolerance: Allowed exact-solver sacrifice when
                reducing a colour's effective layer count.
            backing_material_index: Material used to pad dynamic recipes to
                the physical maximum depth.
        """
        self.materials = list(materials)
        self.layer_count = int(layer_count)
        self.layer_height_mm = float(layer_height_mm)
        self.substrate = str(substrate)
        self._slot_names = list(slot_names)
        self._preview_colors = dict(preview_colors)
        self._color_conf = dict(color_conf)
        self._solver_cache = solver_cache
        self.actual_grid_resolution = int(actual_grid_resolution)
        self.hue_weight = float(hue_weight)
        self.neighbor_coherence = float(neighbor_coherence)
        self.dynamic_layer_count_enabled = bool(dynamic_layer_count_enabled)
        self.dynamic_min_layer_count = int(dynamic_min_layer_count)
        self.dynamic_max_layer_count = int(
            dynamic_max_layer_count
            if dynamic_max_layer_count is not None
            else layer_count
        )
        self.dynamic_delta_e00_tolerance = float(dynamic_delta_e00_tolerance)
        self.backing_material_index = int(backing_material_index)
        if self.dynamic_layer_count_enabled:
            # The vector extrusion depth must be the common physical maximum;
            # individual colours retain their shorter effective recipes in
            # ``dynamic_layer_info`` and are padded by the exact solver.
            self.layer_count = self.dynamic_max_layer_count

        # Duck-typed surface consumed by VectorProcessor
        self.lut_path = MATERIAL_ARCHIVE_LUT_SENTINEL
        self.color_mode = "Material Archive"

        # Internal table — keyed by source RGB tuple so repeated solves
        # are idempotent.
        self._cached: dict[tuple[int, int, int], tuple[np.ndarray, np.ndarray]] = {}
        self._fill_rgbs = np.zeros((0, 3), dtype=np.uint8)
        self._fill_lab = np.zeros((0, 3), dtype=np.float64)
        self._matched_rgbs = np.zeros((0, 3), dtype=np.uint8)
        self._recipes = np.zeros((0, self.layer_count), dtype=np.int32)
        self._kdtree = None
        self._exact_fill_indices: dict[tuple[int, int, int], int] = {}
        self._coverage_by_fill: dict[tuple[int, int, int], int] = {}
        self._dynamic_layer_info: dict | None = None
        self._material_solver_info: dict | None = None
        self._dynamic_metadata_by_fill: dict[tuple[int, int, int], dict] = {}
        self.effective_parallelism_workers = 1
        self.effective_parallelism_plan: AdaptiveParallelismPlan | None = None

    # ------------------------------------------------------------------
    # Construction helper
    # ------------------------------------------------------------------

    @classmethod
    def from_materials(
        cls,
        *,
        materials: list["MaterialParams"],
        layer_count: int,
        layer_height_mm: float,
        substrate: str,
        slot_names: list[str],
        preview_colors: dict,
        color_conf: dict,
        grid_resolution: int,
        hue_weight: float = 0.0,
        neighbor_coherence: float = 0.5,
        dynamic_layer_count_enabled: bool = False,
        dynamic_min_layer_count: int = 5,
        dynamic_max_layer_count: int | None = None,
        dynamic_delta_e00_tolerance: float = 0.5,
        backing_material_index: int = 0,
    ) -> "MaterialVectorMatcher":
        """Resolve / build the solver cache, then return a ready matcher.

        Mirrors :func:`core.pipeline.p03_core_processing._run_material_archive_branch`
        cache-lookup semantics so the matcher's recipes are
        bit-identical to those the raster path would produce for the
        same palette + parameters.

        与 P03 ``_run_material_archive_branch`` 保持一致的缓存解析
        语义：先查持久化缓存，找不到则按最小回退分辨率（64³）现场
        构建一份内存缓存。这样矢量与栅格两条路径在同样输入下产出
        逐位相同的配方。

        Args:
            materials: Material params, same order as ``slot_names``.
            layer_count: Recipe length.
            layer_height_mm: Layer thickness in mm.
            substrate: ``"white"`` / ``"black"``.
            slot_names: Material slot labels for downstream UI.
            preview_colors: Material RGBA preview colours.
            color_conf: Pre-built color_conf dict.
            grid_resolution: Requested cache grid resolution.

        Returns:
            Configured ``MaterialVectorMatcher`` with the solver cache
            already resolved. ``solve_for_fills`` must be called once
            before any ``kdtree.query`` is issued.
        """
        cache = None
        actual_grid = 0
        if not dynamic_layer_count_enabled:
            from core.material_cache import DEFAULT_GRID_RESOLUTION
            from core.material_lut_provider import load_solver_runtime

            cache, actual_grid = load_solver_runtime(
                materials=materials,
                layer_count=int(layer_count),
                layer_height_mm=float(layer_height_mm),
                substrate=str(substrate),
                grid_resolution=int(grid_resolution or DEFAULT_GRID_RESOLUTION),
            )
            if cache is None:
                raise RuntimeError("No material solver runtime could be built")

        return cls(
            materials=materials,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
            slot_names=slot_names,
            preview_colors=preview_colors,
            color_conf=color_conf,
            solver_cache=cache,
            actual_grid_resolution=int(actual_grid),
            hue_weight=hue_weight,
            neighbor_coherence=neighbor_coherence,
            dynamic_layer_count_enabled=dynamic_layer_count_enabled,
            dynamic_min_layer_count=dynamic_min_layer_count,
            dynamic_max_layer_count=dynamic_max_layer_count,
            dynamic_delta_e00_tolerance=dynamic_delta_e00_tolerance,
            backing_material_index=backing_material_index,
        )

    # ------------------------------------------------------------------
    # VectorProcessor / analyze_svg duck-typed surface
    # ------------------------------------------------------------------

    @staticmethod
    def _rgb_to_lab(rgb_array: np.ndarray) -> np.ndarray:
        """Static for VectorProcessor compatibility (mirror of LuminaImageProcessor)."""
        return _rgb_to_lab_static(rgb_array)

    @property
    def color_conf(self) -> dict:
        """Pre-built color_conf dict (slots/preview/name/map).

        Returned as a defensive copy so callers can freely mutate it
        without leaking edits back into the matcher (mirrors
        ``slot_names`` / ``preview_colors`` semantics).
        """
        return dict(self._color_conf)

    @property
    def slot_names(self) -> list[str]:
        return list(self._slot_names)

    @property
    def preview_colors(self) -> dict:
        return dict(self._preview_colors)

    @property
    def lut_rgb(self) -> np.ndarray:
        """Solver-matched RGB table (one row per pre-solved fill)."""
        return self._matched_rgbs

    @property
    def ref_stacks(self) -> np.ndarray:
        """Top2Bottom recipes (one row per pre-solved fill)."""
        return self._recipes

    @property
    def kdtree(self):
        """KDTree over Lab of pre-solved fills.

        Returns ``None`` until :meth:`solve_for_fills` has been called
        with a non-empty colour set. ``VectorProcessor._match_colors``
        guards against empty ``clipped_shapes`` upstream so this is
        only reached after the solver has populated the table.
        """
        return self._kdtree

    @property
    def dynamic_layer_info(self) -> dict | None:
        """Return a serializable copy of the current exact dynamic result."""

        return deepcopy(self._dynamic_layer_info)

    @property
    def material_solver_info(self) -> dict | None:
        """Return dynamic solver diagnostics without exposing mutable state."""

        return deepcopy(self._material_solver_info)

    def dynamic_metadata_for_fill(self, rgb) -> dict | None:
        """Return exact recipe metadata for one SVG fill, when available."""

        key = self._normalize_rgb_key(rgb)
        if key is None:
            return None
        metadata = self._dynamic_metadata_by_fill.get(key)
        return deepcopy(metadata) if metadata is not None else None

    def exact_lut_index_for_rgb(self, rgb) -> int | None:
        """Return the stable table row for an exact source fill.

        返回 SVG 原始填充色对应的稳定表行。该精确索引避免两个不同
        RGB 在 8 位 Lab 量化后重合时互相借用配方；未知颜色仍由调用方
        使用普通近邻匹配。

        Args:
            rgb: Source RGB triple. SVG 原始 RGB 三元组。

        Returns:
            Exact row index, or ``None`` when this fill was not pre-solved.
            精确表行；未预求解该颜色时返回 ``None``。
        """

        key = self._normalize_rgb_key(rgb)
        if key is None:
            return None
        return self._exact_fill_indices.get(key)

    # ------------------------------------------------------------------
    # Solve API
    # ------------------------------------------------------------------

    def solve_for_fills(self, rgbs: Iterable) -> None:
        """Pre-solve the given RGB triples and refresh internal tables.

        Idempotent: colours already in the cache are skipped. Triggers
        one batched ``solver_cache.lookup`` per call for the new
        colours, then rebuilds the KDTree over the union of all
        previously-solved fills.

        预求解给定填充色，幂等；只对新出现的颜色调用一次
        ``solver_cache.lookup``，再按全集重建 KDTree。

        Args:
            rgbs: Iterable of ``(r, g, b)`` uint8 triples or a
                ``(N, 3)`` array. Out-of-range values are clipped.
        """
        new_keys: list[tuple[int, int, int]] = []
        for rgb in rgbs:
            key = self._normalize_rgb_key(rgb)
            if key is None:
                continue
            if key in self._cached:
                continue
            new_keys.append(key)

        if self.dynamic_layer_count_enabled:
            for key in new_keys:
                self._coverage_by_fill.setdefault(key, 1)
            if self._coverage_by_fill:
                self._solve_dynamic_for_coverage()
            return

        if new_keys:
            new_arr = np.array(sorted(set(new_keys)), dtype=np.uint8)
            parallelism_plan = resolve_task_parallelism_plan(
                "vector",
                work_items=int(new_arr.shape[0]),
                min_parallel_items=2,
                hard_max_workers=None,
                work_units=int(new_arr.shape[0]),
                min_parallel_work_units=_MIN_PARALLEL_VECTOR_FILL_COUNT,
                work_units_per_worker=(
                    _VECTOR_MATERIAL_WORK_UNITS_PER_WORKER
                ),
                estimated_worker_bytes=_ESTIMATED_VECTOR_WORKER_BYTES,
            )
            effective_parallelism = parallelism_plan.workers
            self.effective_parallelism_workers = max(
                int(self.effective_parallelism_workers),
                int(effective_parallelism),
            )
            if (
                self.effective_parallelism_plan is None
                or parallelism_plan.workers
                >= self.effective_parallelism_plan.workers
            ):
                self.effective_parallelism_plan = parallelism_plan
            _log.debug(
                "solve_for_fills input: %d new colors (total cached before=%d)",
                new_arr.shape[0],
                len(self._cached),
                extra={
                    "event": "material_vector_solve_input",
                    "new_color_count": int(new_arr.shape[0]),
                    "cached_before": len(self._cached),
                    "new_colors_hex": [
                        f"#{int(c[0]):02X}{int(c[1]):02X}{int(c[2]):02X}"
                        for c in new_arr[:50]  # cap at 50 to avoid log explosion
                    ],
                    "truncated": new_arr.shape[0] > 50,
                    "parallelism": int(effective_parallelism),
                    "parallelism_limit": parallelism_plan.limiting_reason,
                    "effective_cpu_capacity": int(
                        parallelism_plan.effective_cpu_capacity,
                    ),
                    "outer_demand": int(parallelism_plan.outer_demand),
                    "cpu_fair_share_ceiling": int(
                        parallelism_plan.cpu_fair_share_ceiling,
                    ),
                    "memory_ceiling": int(parallelism_plan.memory_ceiling),
                    "demand_snapshot_fallback": bool(
                        parallelism_plan.demand_snapshot_fallback,
                    ),
                },
            )
            lookup_kwargs = {
                "hue_weight": self.hue_weight,
                "neighbor_coherence": self.neighbor_coherence,
                "parallelism": effective_parallelism,
            }
            try:
                import inspect

                lookup_signature = inspect.signature(self._solver_cache.lookup)
                accepts_kwargs = any(
                    param.kind == inspect.Parameter.VAR_KEYWORD
                    for param in lookup_signature.parameters.values()
                )
                if not accepts_kwargs:
                    lookup_kwargs = {
                        key: value
                        for key, value in lookup_kwargs.items()
                        if key in lookup_signature.parameters
                    }
            except (TypeError, ValueError):
                pass
            matched_rgb_unique, recipes_b2t, delta_e = self._solver_cache.lookup(
                new_arr,
                self.materials,
                **lookup_kwargs,
            )
            fallback_stats = None
            try:
                from core.material_layer_fallback_policy import (
                    should_run_cross_n_fallback,
                )
                from core.material_lut_synthesis import (
                    ensure_not_worse_than_smaller_N,
                )

                if should_run_cross_n_fallback(
                    solver_path="cache",
                    runtime=self._solver_cache,
                    unique_color_count=int(new_arr.shape[0]),
                    material_count=len(self.materials),
                    layer_count=self.layer_count,
                ):
                    matched_rgb_unique, recipes_b2t, delta_e, fallback_stats = (
                        ensure_not_worse_than_smaller_N(
                            new_arr,
                            self.materials,
                            matched_rgb_unique,
                            recipes_b2t,
                            delta_e,
                            target_layer_count=self.layer_count,
                            layer_height_mm=self.layer_height_mm,
                            substrate=self.substrate,
                        )
                    )
            except (ValueError, TypeError, RuntimeError) as exc:
                _log.warning(
                    "Not-worse fallback failed for vector material solve (%s); "
                    "keeping baseline recipes",
                    exc,
                    extra={
                        "event": "material_vector_not_worse_fallback_failed",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "color_count": int(new_arr.shape[0]),
                        "layer_count": int(self.layer_count),
                    },
                )
            recipes_t2b = self._normalise_recipes(recipes_b2t)
            for i in range(new_arr.shape[0]):
                key = tuple(int(c) for c in new_arr[i])
                self._cached[key] = (
                    matched_rgb_unique[i].astype(np.uint8, copy=True),
                    recipes_t2b[i].astype(np.int32, copy=True),
                )

            # Diagnostic per-fill DEBUG so the vector pipeline's
            # material-mode colour drift (e.g. when a fill's solved
            # recipe disagrees visibly with the source RGB) can be
            # bisected by re-running the export with DEBUG enabled.
            # 每个唯一填充色的求解结果按 DEBUG 级别打日志，便于排查
            # 矢量 + 耗材模式下的偏色问题。
            for i in range(new_arr.shape[0]):
                src = new_arr[i]
                matched = matched_rgb_unique[i]
                _log.debug(
                    "material vector solve: src=#%02X%02X%02X -> matched=#%02X%02X%02X recipe_top2btm=%s delta_e=%.3f",
                    int(src[0]), int(src[1]), int(src[2]),
                    int(matched[0]), int(matched[1]), int(matched[2]),
                    list(int(x) for x in recipes_t2b[i]),
                    float(delta_e[i]) if delta_e is not None and len(delta_e) > i else float("nan"),
                    extra={
                        "event": "material_vector_solve_per_color",
                        "src_rgb": [int(src[0]), int(src[1]), int(src[2])],
                        "matched_rgb": [int(matched[0]), int(matched[1]), int(matched[2])],
                        "recipe_top2btm": [int(x) for x in recipes_t2b[i]],
                        "delta_e": (
                            float(delta_e[i])
                            if delta_e is not None and len(delta_e) > i
                            else None
                        ),
                    },
                )

            # Keep the INFO event bounded for artwork with thousands of
            # unique fills. Per-colour details remain available at DEBUG.
            _log.info(
                "material vector solve summary: %d colors",
                new_arr.shape[0],
                extra={
                    "event": "material_vector_solve_summary",
                    "color_count": int(new_arr.shape[0]),
                    "layer_count": int(self.layer_count),
                    "substrate": str(self.substrate),
                    "grid_resolution": int(self.actual_grid_resolution),
                    "not_worse_fallback_checked": fallback_stats is not None,
                    "not_worse_fallback_applied": bool(
                        fallback_stats and fallback_stats.get("applied")
                    ),
                    "not_worse_fallback_improved_pixels": int(
                        fallback_stats.get("improved_pixels", 0)
                        if fallback_stats
                        else 0
                    ),
                },
            )

        self._rebuild_tables()

    def solve_for_clipped_shapes(self, clipped_shapes, *, scale_factor: float) -> None:
        """Solve SVG fills with exact geometry-coverage weights.

        This is intentionally geometry-only: it aggregates the retained
        Shapely areas after SVG parsing and occlusion clipping, then hands
        those relative coverages to the existing exact dynamic solver. It
        never rasterizes or substitutes a bitmap representation of the SVG.

        根据 SVG 解析和遮挡裁剪后的 Shapely 几何面积聚合各颜色覆盖量，再交给
        既有精确动态求解器；全过程不栅格化 SVG，也不改变原始路径/几何。
        """

        if not self.dynamic_layer_count_enabled:
            self.solve_for_fills(
                (
                    item.get("match_color")
                    if item.get("match_color") is not None
                    else item.get("color")
                )
                for item in (clipped_shapes or [])
                if isinstance(item, dict)
            )
            return

        try:
            scale_squared = max(0.0, float(scale_factor) ** 2)
        except (TypeError, ValueError):
            scale_squared = 1.0
        coverage_by_fill: dict[tuple[int, int, int], float] = {}
        for item in clipped_shapes or []:
            if not isinstance(item, dict):
                continue
            match_color = item.get("match_color")
            key = self._normalize_rgb_key(
                match_color if match_color is not None else item.get("color")
            )
            if key is None:
                continue
            geometry = item.get("geometry")
            try:
                area_mm2 = max(0.0, float(geometry.area) * scale_squared)
            except (AttributeError, TypeError, ValueError):
                area_mm2 = 0.0
            if area_mm2 <= 0.0:
                continue
            coverage_by_fill[key] = coverage_by_fill.get(key, 0.0) + area_mm2

        # The exact solver only needs relative ownership counts for its
        # weighted benefit curve. Use a stable high-resolution integer scale
        # so sub-mm vector regions are retained without materializing pixels.
        coverage_scale = 1_000_000
        self._coverage_by_fill = {
            key: max(1, int(round(area_mm2 * coverage_scale)))
            for key, area_mm2 in sorted(coverage_by_fill.items())
        }
        if not self._coverage_by_fill:
            # Keep the duck-typed matcher usable for retained degenerate
            # vector records (for example a zero-area parser artefact). The
            # normal path above always uses true geometry coverage.
            for item in clipped_shapes or []:
                if not isinstance(item, dict):
                    continue
                match_color = item.get("match_color")
                key = self._normalize_rgb_key(
                    match_color if match_color is not None else item.get("color")
                )
                if key is not None:
                    self._coverage_by_fill.setdefault(key, 1)
        if self._coverage_by_fill:
            self._solve_dynamic_for_coverage()

    @staticmethod
    def _normalize_rgb_key(rgb) -> tuple[int, int, int] | None:
        try:
            r = int(rgb[0])
            g = int(rgb[1])
            b = int(rgb[2])
        except (TypeError, IndexError, ValueError):
            return None
        return (
            max(0, min(255, r)),
            max(0, min(255, g)),
            max(0, min(255, b)),
        )

    def _solve_dynamic_for_coverage(self) -> None:
        """Refresh exact dynamic rows from the current vector coverage map."""

        from core.pipeline.material_dynamic_layers import solve_dynamic_material_targets

        ordered_keys = sorted(self._coverage_by_fill)
        unique_colors = np.asarray(ordered_keys, dtype=np.uint8)
        pixel_counts = np.asarray(
            [self._coverage_by_fill[key] for key in ordered_keys],
            dtype=np.int64,
        )
        (
            matched_rgb,
            recipes_top_to_bottom,
            delta_e,
            dynamic_info,
            solver_meta,
        ) = solve_dynamic_material_targets(
            unique_colors=unique_colors,
            pixel_counts=pixel_counts,
            materials=self.materials,
            backing_material_index=self.backing_material_index,
            layer_height_mm=self.layer_height_mm,
            substrate=self.substrate,
            min_layer_count=self.dynamic_min_layer_count,
            max_layer_count=self.dynamic_max_layer_count,
            delta_e00_tolerance=self.dynamic_delta_e00_tolerance,
        )
        self._cached = {
            key: (
                matched_rgb[index].astype(np.uint8, copy=True),
                recipes_top_to_bottom[index].astype(np.int32, copy=True),
            )
            for index, key in enumerate(ordered_keys)
        }
        dynamic_info = deepcopy(dynamic_info)
        dynamic_info["coverage_source"] = "native_svg_geometry"
        dynamic_info["coverage_unit"] = "square_millimeter_x_1000000"
        dynamic_info["benefit_curve_scope"] = "visible_svg_geometry"
        self._dynamic_layer_info = dynamic_info
        self._material_solver_info = {
            "path": "dynamic_exact_vector_geometry",
            "layer_count": int(self.layer_count),
            "layer_height_mm": float(self.layer_height_mm),
            "substrate": str(self.substrate),
            "unique_color_count": int(unique_colors.shape[0]),
            "mean_delta_e": float(np.mean(delta_e)) if delta_e.size else 0.0,
            "max_delta_e": float(np.max(delta_e)) if delta_e.size else 0.0,
            **solver_meta,
        }
        self._dynamic_metadata_by_fill = {
            tuple(int(value) for value in entry.get("target_srgb", ())): deepcopy(entry)
            for entry in dynamic_info.get("colors", [])
            if isinstance(entry, dict)
            and len(entry.get("target_srgb", ())) == 3
        }
        self._rebuild_tables()

    def _normalise_recipes(self, recipes_b2t: np.ndarray) -> np.ndarray:
        """Convert Bottom2Top → Top2Bottom and pad/truncate to layer_count.

        The solver returns ``recipes[:, 0]`` as the substrate-adjacent
        layer (Bottom2Top). The vector pipeline expects
        ``recipe[0]`` = visible face (Top2Bottom). Pad with the
        substrate-adjacent material id (``-1`` is reserved for
        transparent pixels in the raster path; the vector path never
        emits transparent recipes since shapes are always solid).

        与 P03 完全一致的反转 + 截断/填充逻辑，确保配方语义对齐。
        """
        if recipes_b2t.size == 0:
            return np.zeros((0, self.layer_count), dtype=np.int32)
        if recipes_b2t.shape[1] > 1:
            recipes_t2b = np.ascontiguousarray(recipes_b2t[:, ::-1])
        else:
            recipes_t2b = np.array(recipes_b2t, dtype=np.int32, copy=True)

        if recipes_t2b.shape[1] < self.layer_count:
            # Pad the substrate-adjacent end with the bottom-most
            # channel so extrusion stays continuous with the backing.
            # 在贴基底端按底层颜色填充，避免拉伸阶段出现 -1 / 越界。
            pad_count = self.layer_count - recipes_t2b.shape[1]
            pad_value = recipes_t2b[:, -1:].astype(np.int32, copy=False)
            pad_block = np.repeat(pad_value, pad_count, axis=1)
            recipes_t2b = np.concatenate([recipes_t2b, pad_block], axis=1)
        elif recipes_t2b.shape[1] > self.layer_count:
            recipes_t2b = recipes_t2b[:, : self.layer_count]
        return recipes_t2b.astype(np.int32, copy=False)

    def _rebuild_tables(self) -> None:
        """Refresh the public arrays + KDTree from the cached dict."""
        if not self._cached:
            self._fill_rgbs = np.zeros((0, 3), dtype=np.uint8)
            self._fill_lab = np.zeros((0, 3), dtype=np.float64)
            self._matched_rgbs = np.zeros((0, 3), dtype=np.uint8)
            self._recipes = np.zeros((0, self.layer_count), dtype=np.int32)
            self._kdtree = None
            self._exact_fill_indices = {}
            return

        keys = sorted(self._cached.keys())
        self._exact_fill_indices = {key: index for index, key in enumerate(keys)}
        self._fill_rgbs = np.array(keys, dtype=np.uint8)
        # Lab of the source fills — KDTree queries from
        # ``_match_colors`` use Lab of the SVG fill colour.
        self._fill_lab = _rgb_to_lab_static(self._fill_rgbs.reshape(1, -1, 3)).reshape(-1, 3)
        self._matched_rgbs = np.stack([self._cached[k][0] for k in keys]).astype(np.uint8, copy=False)
        self._recipes = np.stack([self._cached[k][1] for k in keys]).astype(np.int32, copy=False)

        from scipy.spatial import KDTree

        self._kdtree = KDTree(self._fill_lab)
