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
_VECTOR_MATERIAL_MAX_WORKERS = 2
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
        solver_cache,
        actual_grid_resolution: int,
        hue_weight: float = 0.0,
        neighbor_coherence: float = 0.5,
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
            try:
                r = int(rgb[0])
                g = int(rgb[1])
                b = int(rgb[2])
            except (TypeError, IndexError, ValueError):
                continue
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            key = (r, g, b)
            if key in self._cached:
                continue
            new_keys.append(key)

        if new_keys:
            new_arr = np.array(sorted(set(new_keys)), dtype=np.uint8)
            parallelism_plan = resolve_task_parallelism_plan(
                "vector",
                work_items=int(new_arr.shape[0]),
                min_parallel_items=2,
                hard_max_workers=_VECTOR_MATERIAL_MAX_WORKERS,
                work_units=int(new_arr.shape[0]),
                min_parallel_work_units=_MIN_PARALLEL_VECTOR_FILL_COUNT,
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

            # Aggregate INFO line so a single grep gives the user a
            # readable summary of every unique fill solved this run.
            # 汇总行用 INFO 级别写一次，便于一行 grep 看完整表。
            summary_pairs = []
            for i in range(new_arr.shape[0]):
                src = new_arr[i]
                matched = matched_rgb_unique[i]
                summary_pairs.append(
                    f"#{int(src[0]):02X}{int(src[1]):02X}{int(src[2]):02X}"
                    f"->#{int(matched[0]):02X}{int(matched[1]):02X}{int(matched[2]):02X}"
                )
            _log.info(
                "material vector solve summary: %d colors -> %s",
                new_arr.shape[0],
                ", ".join(summary_pairs),
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
            return

        keys = sorted(self._cached.keys())
        self._fill_rgbs = np.array(keys, dtype=np.uint8)
        # Lab of the source fills — KDTree queries from
        # ``_match_colors`` use Lab of the SVG fill colour.
        self._fill_lab = _rgb_to_lab_static(self._fill_rgbs.reshape(1, -1, 3)).reshape(-1, 3)
        self._matched_rgbs = np.stack([self._cached[k][0] for k in keys]).astype(np.uint8, copy=False)
        self._recipes = np.stack([self._cached[k][1] for k in keys]).astype(np.int32, copy=False)

        from scipy.spatial import KDTree

        self._kdtree = KDTree(self._fill_lab)
