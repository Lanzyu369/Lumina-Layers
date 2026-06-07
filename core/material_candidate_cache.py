"""Bounded material candidate runtime.

候选缓存运行时：用有限候选覆盖大耗材空间，避免生产路径穷举 ``M ** N``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from core.material_cache import canonical_palette_order, fingerprint_palette
from core.material_candidate_sampling import generate_candidate_recipes
from core.material_color_solver import (
    MaterialParams,
    _compute_material_affines,
    linear_to_srgb_uint8,
    rgb_to_lab,
)
from core.material_inverse_refinement import (
    MaterialInverseRefinementConfig,
    refine_material_matches,
)


DEFAULT_CANDIDATE_BUILD_MEMORY_BUDGET_BYTES = 8 * 1024 * 1024 * 1024
PREVIEW_SAFE_CANDIDATE_BUDGET = 1_048_576
DEFAULT_PERSISTED_CANDIDATE_BUDGET = 4_194_304
QUALITY_8G_CANDIDATE_BUDGET = 8_388_608


@dataclass(frozen=True)
class MaterialCandidateCacheConfig:
    """Configuration for bounded material candidate runtime builds.
    有预算的耗材候选运行时构建配置。

    Attributes:
        candidate_budget: Final candidate row budget. (最终候选行数预算)
        candidate_pool_multiplier: Reserved multiplier for future streaming
            selection pools. (预留给后续流式选择池的候选倍数)
        build_memory_budget_bytes: Build-time memory budget. (构建期内存预算)
        batch_recipe_count: Forward-model batch size. (正向预测批大小)
        lab_grid_resolution: Diagnostic Lab resolution label. (诊断用 Lab 分辨率)
        seed: Deterministic sampling seed. (确定性采样种子)
        max_build_seconds: Optional build-time cap. (可选构建时间上限)
        enable_inverse_refinement: Reserved inverse-refinement flag.
            (预留的反向精修开关)
        max_refine_materials: Reserved material cap for inverse refinement.
            (反向精修耗材数量上限)
        max_refine_top_suffixes: Reserved top suffix cap. (顶部后缀数量上限)
        max_refine_bottom_prefixes: Reserved bottom prefix cap. (底部前缀数量上限)
        refine_bottom_neighbors: Bottom-prefix neighbors per inverse target.
            (每个反推目标使用的底部前缀邻居数)
    """

    candidate_budget: int
    candidate_pool_multiplier: int = 8
    build_memory_budget_bytes: int = DEFAULT_CANDIDATE_BUILD_MEMORY_BUDGET_BYTES
    batch_recipe_count: int = 524_288
    lab_grid_resolution: int = 64
    seed: int = 0
    max_build_seconds: float | None = None
    enable_inverse_refinement: bool = True
    max_refine_materials: int = 12
    max_refine_top_suffixes: int = 4096
    max_refine_bottom_prefixes: int = 64
    refine_bottom_neighbors: int = 2

    @classmethod
    def preview_safe(cls) -> "MaterialCandidateCacheConfig":
        return cls(
            candidate_budget=PREVIEW_SAFE_CANDIDATE_BUDGET,
            max_refine_materials=8,
            max_refine_top_suffixes=4096,
            max_refine_bottom_prefixes=4096,
            refine_bottom_neighbors=2,
        )

    @classmethod
    def default_persisted(cls) -> "MaterialCandidateCacheConfig":
        return cls(
            candidate_budget=DEFAULT_PERSISTED_CANDIDATE_BUDGET,
            max_refine_materials=8,
            max_refine_top_suffixes=32_768,
            max_refine_bottom_prefixes=65_536,
            refine_bottom_neighbors=2,
        )

    @classmethod
    def quality_8g(cls) -> "MaterialCandidateCacheConfig":
        return cls(
            candidate_budget=QUALITY_8G_CANDIDATE_BUDGET,
            max_refine_materials=8,
            max_refine_top_suffixes=32_768,
            max_refine_bottom_prefixes=65_536,
            refine_bottom_neighbors=2,
        )


@dataclass(frozen=True)
class CandidateCacheMemoryEstimate:
    """Approximate memory budget report for a candidate-runtime build.
    候选运行时构建的近似内存预算报告。

    Attributes:
        candidate_budget: Candidate row budget. (候选行数预算)
        layer_count: Recipe layer count. (配方层数)
        material_count: Material count. (耗材数量)
        final_runtime_bytes: Estimated resident runtime arrays. (常驻数组估算)
        estimated_peak_bytes: Estimated build-time peak. (构建峰值估算)
    """

    candidate_budget: int
    layer_count: int
    material_count: int
    final_runtime_bytes: int
    estimated_peak_bytes: int


def estimate_candidate_cache_memory(
    *,
    candidate_budget: int,
    layer_count: int,
    material_count: int,
) -> CandidateCacheMemoryEstimate:
    """Estimate peak memory for bounded candidate-runtime construction.
    估算有预算候选运行时的构建峰值内存。

    Args:
        candidate_budget: Candidate row budget. (候选行数预算)
        layer_count: Recipe layer count. (配方层数)
        material_count: Material count. (耗材数量)

    Returns:
        CandidateCacheMemoryEstimate: Final and peak memory estimate.
            (常驻与峰值内存估算)
    """
    recipe_item_bytes = 2 if material_count > 255 else 1
    recipe_bytes = int(candidate_budget) * int(layer_count) * recipe_item_bytes
    srgb_bytes = int(candidate_budget) * 3
    lab_bytes = int(candidate_budget) * 3 * 4
    pinned_bytes = int(candidate_budget)
    final_runtime_bytes = recipe_bytes + srgb_bytes + lab_bytes + pinned_bytes
    work_arrays_bytes = int(candidate_budget) * (3 * 8 + 3 * 8 + 32)
    safety_bytes = 256 * 1024 * 1024
    estimated_peak_bytes = final_runtime_bytes + work_arrays_bytes + safety_bytes
    return CandidateCacheMemoryEstimate(
        candidate_budget=int(candidate_budget),
        layer_count=int(layer_count),
        material_count=int(material_count),
        final_runtime_bytes=int(final_runtime_bytes),
        estimated_peak_bytes=int(estimated_peak_bytes),
    )


def _substrate_linear(substrate: str) -> np.ndarray:
    normalized = str(substrate).lower()
    if normalized == "white":
        return np.ones(3, dtype=np.float64)
    if normalized == "black":
        return np.zeros(3, dtype=np.float64)
    raise ValueError("substrate must be 'white' or 'black'")


def _predict_candidate_linear(
    *,
    recipes: np.ndarray,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate: str,
    batch_recipe_count: int,
) -> np.ndarray:
    affines = _compute_material_affines(materials, float(layer_height_mm))
    output = np.empty((recipes.shape[0], 3), dtype=np.float64)
    substrate_rgb = _substrate_linear(substrate)

    start = 0
    while start < recipes.shape[0]:
        end = min(start + int(batch_recipe_count), recipes.shape[0])
        batch = recipes[start:end].astype(np.int64, copy=False)
        colors = np.repeat(substrate_rgb[None, :], batch.shape[0], axis=0)
        for layer_index in range(batch.shape[1]):
            material_indices = batch[:, layer_index]
            colors = (
                affines.a[material_indices] * colors
                + affines.b[material_indices]
            )
        output[start:end] = colors
        start = end

    return np.clip(output, 0.0, 1.0)


@dataclass
class MaterialCandidateRuntime:
    """Lookup-compatible bounded material runtime.
    与旧求解缓存 ``lookup`` 兼容的有界耗材运行时。

    Attributes:
        candidate_recipes: ``(K, N)`` canonical bottom-to-top recipes.
            (规范耗材顺序下、自底向上的候选配方)
        achieved_srgb: ``(K, 3)`` predicted sRGB colors. (预测 sRGB 颜色)
        achieved_lab: ``(K, 3)`` predicted Lab colors. (预测 Lab 颜色)
        pinned_mask: Rows from deterministic anchors. (确定性锚点行)
        metadata: Runtime metadata and compatibility fields. (运行时元数据)
    """

    candidate_recipes: np.ndarray
    achieved_srgb: np.ndarray
    achieved_lab: np.ndarray
    pinned_mask: np.ndarray
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        self._tree: cKDTree | None = None

    @property
    def mode(self) -> str:
        return "candidate_hybrid"

    @property
    def layer_count(self) -> int:
        return int(self.metadata["layer_count"])

    @property
    def layer_height_mm(self) -> float:
        return float(self.metadata["layer_height_mm"])

    @property
    def substrate(self) -> str:
        return str(self.metadata["substrate"])

    @property
    def palette_hash(self) -> str:
        return str(self.metadata["palette_hash"])

    @property
    def grid_resolution(self) -> int:
        return int(self.metadata["grid_resolution"])

    @property
    def valid_cell_count(self) -> int:
        return int(self.candidate_recipes.shape[0])

    def _refinement_config(self) -> MaterialInverseRefinementConfig:
        inverse = self.metadata.get("inverse_refinement") or {}
        return MaterialInverseRefinementConfig(
            enabled=bool(inverse.get("enabled", False)),
            max_refine_materials=int(inverse.get("max_refine_materials", 8)),
            max_refine_top_suffixes=int(
                inverse.get("max_refine_top_suffixes", 32_768)
            ),
            max_refine_bottom_prefixes=int(
                inverse.get("max_refine_bottom_prefixes", 65_536)
            ),
            refine_bottom_neighbors=int(inverse.get("refine_bottom_neighbors", 2)),
            seed=int(self.metadata.get("seed", 0)),
        )

    def _ensure_tree(self) -> cKDTree:
        if self._tree is None:
            self._tree = cKDTree(self.achieved_lab.astype(np.float64, copy=False))
        return self._tree

    def lookup(
        self,
        target_srgb: np.ndarray,
        user_materials: list[MaterialParams],
        *,
        hue_weight: float = 0.0,
        neighbor_coherence: float = 0.5,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return nearest candidate recipes using the solver-cache tuple shape.
        按旧求解缓存的返回形状返回最近候选配方。

        Args:
            target_srgb: ``(C, 3)`` uint8 target colors. (目标色)
            user_materials: Materials in caller-visible order. (调用方耗材顺序)
            hue_weight: Accepted for API compatibility. (兼容旧接口)
            neighbor_coherence: Accepted for API compatibility. (兼容旧接口)

        Returns:
            tuple[np.ndarray, np.ndarray, np.ndarray]: matched RGB, recipes in
            user order, and CIE76 delta-E. (匹配色、用户顺序配方、Delta-E)
        """
        del hue_weight, neighbor_coherence
        targets = np.asarray(target_srgb, dtype=np.uint8)
        if targets.ndim != 2 or targets.shape[1] != 3:
            raise ValueError("target_srgb must have shape (C, 3)")
        if targets.shape[0] == 0:
            return (
                np.zeros((0, 3), dtype=np.uint8),
                np.zeros((0, self.layer_count), dtype=np.int32),
                np.zeros((0,), dtype=np.float64),
            )
        if fingerprint_palette(user_materials) != self.palette_hash:
            raise ValueError("MaterialCandidateRuntime palette_hash mismatch")
        if self.valid_cell_count <= 0:
            raise ValueError("MaterialCandidateRuntime has no candidates")

        target_lab = rgb_to_lab(targets).astype(np.float64, copy=False)
        neighbor_count = min(64, self.valid_cell_count)
        _distances, indices = self._ensure_tree().query(target_lab, k=neighbor_count)
        if neighbor_count == 1:
            indices = indices[:, None]

        candidate_lab = self.achieved_lab[indices].astype(np.float64, copy=False)
        delta = np.linalg.norm(candidate_lab - target_lab[:, None, :], axis=2)
        best_offsets = np.argmin(delta, axis=1)
        best_indices = indices[np.arange(targets.shape[0]), best_offsets]

        matched_rgb = self.achieved_srgb[best_indices].astype(np.uint8, copy=True)
        recipes_canonical = self.candidate_recipes[best_indices].astype(
            np.int32,
            copy=True,
        )
        best_delta = delta[np.arange(targets.shape[0]), best_offsets].astype(
            np.float64,
            copy=False,
        )

        refinement_config = self._refinement_config()
        if refinement_config.enabled:
            canonical_order = canonical_palette_order(user_materials)
            canonical_materials = [user_materials[index] for index in canonical_order]
            refined = refine_material_matches(
                target_srgb=targets,
                baseline_matched_srgb=matched_rgb,
                baseline_recipes=recipes_canonical,
                baseline_delta_e=best_delta,
                materials=canonical_materials,
                layer_count=self.layer_count,
                layer_height_mm=self.layer_height_mm,
                substrate=self.substrate,
                config=refinement_config,
            )
            matched_rgb = refined.matched_srgb
            recipes_canonical = refined.recipes
            best_delta = refined.delta_e

        canonical_to_user = np.asarray(
            canonical_palette_order(user_materials),
            dtype=np.int32,
        )
        recipes_user = canonical_to_user[recipes_canonical].astype(
            np.int32,
            copy=False,
        )
        return matched_rgb, recipes_user, best_delta


def build_material_candidate_runtime(
    *,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    config: MaterialCandidateCacheConfig | None = None,
) -> MaterialCandidateRuntime:
    """Build an in-memory bounded candidate runtime for material matching.
    构建内存中的有界耗材候选匹配运行时。

    Args:
        materials: Material parameters in user order. (用户选择顺序的耗材参数)
        layer_count: Recipe layer count. (配方层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"`` substrate. (基底颜色)
        config: Optional build configuration. (可选构建配置)

    Returns:
        MaterialCandidateRuntime: Lookup-compatible candidate runtime.
            (与 ``lookup`` 契约兼容的候选运行时)
    """
    if not materials:
        raise ValueError("materials must not be empty")
    cfg = config or MaterialCandidateCacheConfig.preview_safe()
    order = canonical_palette_order(materials)
    canonical_materials = [materials[index] for index in order]
    generated = generate_candidate_recipes(
        material_count=len(canonical_materials),
        layer_count=int(layer_count),
        candidate_budget=int(cfg.candidate_budget),
        seed=int(cfg.seed),
    )
    linear = _predict_candidate_linear(
        recipes=generated.recipes,
        materials=canonical_materials,
        layer_height_mm=float(layer_height_mm),
        substrate=str(substrate),
        batch_recipe_count=int(cfg.batch_recipe_count),
    )
    achieved_srgb = linear_to_srgb_uint8(linear)
    achieved_lab = rgb_to_lab(achieved_srgb).astype(np.float32, copy=False)
    metadata = {
        "mode": "candidate_hybrid",
        "palette_hash": fingerprint_palette(canonical_materials),
        "layer_count": int(layer_count),
        "layer_height_mm": float(layer_height_mm),
        "substrate": str(substrate),
        "grid_resolution": int(cfg.lab_grid_resolution),
        "lab_grid_resolution": int(cfg.lab_grid_resolution),
        "candidate_budget": int(cfg.candidate_budget),
        "seed": int(cfg.seed),
        "inverse_refinement": {
            "enabled": bool(cfg.enable_inverse_refinement),
            "max_refine_materials": int(cfg.max_refine_materials),
            "max_refine_top_suffixes": int(cfg.max_refine_top_suffixes),
            "max_refine_bottom_prefixes": int(cfg.max_refine_bottom_prefixes),
            "refine_bottom_neighbors": int(cfg.refine_bottom_neighbors),
        },
    }
    return MaterialCandidateRuntime(
        candidate_recipes=generated.recipes,
        achieved_srgb=achieved_srgb,
        achieved_lab=achieved_lab,
        pinned_mask=generated.pinned_mask,
        metadata=metadata,
    )
