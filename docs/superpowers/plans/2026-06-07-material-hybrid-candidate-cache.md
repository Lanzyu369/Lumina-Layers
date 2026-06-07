# Material Hybrid Candidate Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Lumina 的大耗材数量场景新增有预算的 hybrid candidate runtime，使生产 fallback 不再通过低 grid 穷举扫描 `M ** N` 配方。

**Architecture:** 保留现有 `MaterialSolverCache` 和持久化文件兼容性；新增 `MaterialCandidateRuntime`，它暴露与 `MaterialSolverCache.lookup()` 同形的 duck-typed 接口。生产热路径先尝试加载旧持久缓存，缺失时构建 bounded candidate runtime；旧 bucketed builder 保留为小规模/显式 legacy 路径的安全阀。

**Tech Stack:** Python 3, NumPy, SciPy `scipy.stats.qmc.Sobol`, SciPy `cKDTree`, pytest。

---

## File Structure

- Create: `core/material_candidate_sampling.py`
  - 只负责生成有限候选配方。
  - 提供 Sobol 低差异采样、固定纯色配方、去重、预算裁剪。
  - 不导入 `core.material_cache.build_material_solver_cache`，不调用 `_enumerate_cumulative_affines`。

- Create: `core/material_candidate_cache.py`
  - 持有 `MaterialCandidateCacheConfig`、内存估算、`MaterialCandidateRuntime`。
  - 用 Beer-Lambert affine 正向预测候选配方颜色。
  - 构建 `cKDTree` 并实现 `lookup()`，返回 `(matched_rgb, recipes_user_order, delta_e)`。

- Modify: `core/material_lut_provider.py`
  - 新增 `load_solver_runtime(...)`。
  - 先加载旧 `MaterialSolverCache`；没有持久缓存时构建 `MaterialCandidateRuntime`。
  - 保持现有 `load_solver_cache(...)` 原语义不变，避免一次性扩散。

- Modify: `core/pipeline/p03_core_processing.py`
  - 把“无持久缓存时现场构建 64-grid 旧缓存”的 fallback 改为 `load_solver_runtime(...)`。
  - 保留错误返回格式，避免影响调用方。

- Modify: `core/vector_matchers.py`
  - 将 vector 分支的同类 fallback 改为 `load_solver_runtime(...)`。

- Create: `tests/test_material_candidate_cache_unit.py`
  - 覆盖预算、Sobol 采样、纯色 pinned、runtime lookup 契约、palette rebind。

- Modify: `tests/test_p03_material_archive_layer_order_unit.py`
  - 调整 monkeypatch 目标，确认 P03 fallback 不再调用 `build_material_solver_cache`。

- Modify: `tests/test_vector_material_matcher_unit.py`
  - 覆盖 vector fallback 使用 runtime resolver，不再现场构建旧 bucketed cache。

---

### Task 1: Core Candidate Sampling

**Files:**
- Create: `tests/test_material_candidate_cache_unit.py`
- Create: `core/material_candidate_sampling.py`

- [ ] **Step 1: Write the failing sampling tests**

Add this content to `tests/test_material_candidate_cache_unit.py`:

```python
"""Unit tests for bounded material candidate runtime."""

from __future__ import annotations

import numpy as np

from core.material_candidate_cache import (
    DEFAULT_CANDIDATE_BUILD_MEMORY_BUDGET_BYTES,
    MaterialCandidateCacheConfig,
    estimate_candidate_cache_memory,
)
from core.material_candidate_sampling import generate_candidate_recipes
from core.material_color_solver import MaterialParams


def _mat(name: str, E: tuple[float, float, float], k: tuple[float, float, float]) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(E, dtype=np.float64),
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.asarray((1.0, 1.0, 1.0), dtype=np.float64),
        estimated_rgb=np.asarray([int(round(255 * c)) for c in E], dtype=np.uint8),
    )


RED = _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0))
BLUE = _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0))
WHITE = _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5))
GREEN = _mat("Green", E=(0.1, 0.6, 0.1), k=(4.0, 4.0, 4.0))
BLACK = _mat("Black", E=(0.05, 0.05, 0.05), k=(6.0, 6.0, 6.0))
SMALL_PALETTE = [RED, BLUE, WHITE]
MEDIUM_PALETTE = [RED, BLUE, WHITE, GREEN, BLACK]


def test_default_candidate_config_uses_8g_build_budget() -> None:
    config = MaterialCandidateCacheConfig.default_persisted()

    assert config.candidate_budget == 4_194_304
    assert config.candidate_pool_multiplier == 8
    assert config.batch_recipe_count == 524_288
    assert config.build_memory_budget_bytes == 8 * 1024 * 1024 * 1024
    assert DEFAULT_CANDIDATE_BUILD_MEMORY_BUDGET_BYTES == 8 * 1024 * 1024 * 1024


def test_default_candidate_memory_estimate_fits_8g_budget() -> None:
    config = MaterialCandidateCacheConfig.default_persisted()

    report = estimate_candidate_cache_memory(
        candidate_budget=config.candidate_budget,
        layer_count=10,
        material_count=22,
    )

    assert report.candidate_budget == 4_194_304
    assert report.estimated_peak_bytes < config.build_memory_budget_bytes


def test_sobol_candidate_generation_is_deterministic_and_bounded() -> None:
    first = generate_candidate_recipes(
        material_count=5,
        layer_count=8,
        candidate_budget=128,
        seed=1234,
    )
    second = generate_candidate_recipes(
        material_count=5,
        layer_count=8,
        candidate_budget=128,
        seed=1234,
    )

    np.testing.assert_array_equal(first.recipes, second.recipes)
    assert first.recipes.shape == (128, 8)
    assert first.recipes.dtype == np.uint16
    assert int(first.recipes.min()) >= 0
    assert int(first.recipes.max()) < 5
    assert first.pinned_mask.shape == (128,)


def test_uniform_recipes_are_pinned_before_sobol_candidates() -> None:
    generated = generate_candidate_recipes(
        material_count=5,
        layer_count=6,
        candidate_budget=32,
        seed=9,
    )

    expected_uniforms = np.asarray([[i] * 6 for i in range(5)], dtype=np.uint16)
    np.testing.assert_array_equal(generated.recipes[:5], expected_uniforms)
    np.testing.assert_array_equal(generated.pinned_mask[:5], np.ones(5, dtype=bool))
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
python -m pytest tests/test_material_candidate_cache_unit.py -v
```

Expected: FAIL during import with `ModuleNotFoundError: No module named 'core.material_candidate_cache'` or `No module named 'core.material_candidate_sampling'`.

- [ ] **Step 3: Implement minimal sampling module**

Create `core/material_candidate_sampling.py`:

```python
"""Bounded recipe sampling for material candidate runtimes."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CandidateRecipeBatch:
    recipes: np.ndarray
    pinned_mask: np.ndarray


def _uniform_recipes(material_count: int, layer_count: int) -> np.ndarray:
    indices = np.arange(material_count, dtype=np.uint16)
    return np.repeat(indices[:, None], layer_count, axis=1)


def _sobol_points(count: int, layer_count: int, seed: int) -> np.ndarray:
    from scipy.stats import qmc

    power = int(np.ceil(np.log2(max(1, count))))
    sampler = qmc.Sobol(d=int(layer_count), scramble=True, seed=int(seed))
    return sampler.random_base2(power)[:count]


def _rng_points(count: int, layer_count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(int(seed))
    return rng.random((int(count), int(layer_count)), dtype=np.float64)


def _low_discrepancy_recipes(
    *,
    material_count: int,
    layer_count: int,
    count: int,
    seed: int,
) -> np.ndarray:
    try:
        points = _sobol_points(count, layer_count, seed)
    except Exception:
        points = _rng_points(count, layer_count, seed)
    recipes = np.floor(points * int(material_count)).astype(np.uint16)
    return np.clip(recipes, 0, int(material_count) - 1)


def _unique_rows_preserve_order(rows: np.ndarray) -> np.ndarray:
    if rows.size == 0:
        return rows.reshape(0, rows.shape[-1])
    _, unique_indices = np.unique(rows, axis=0, return_index=True)
    return rows[np.sort(unique_indices)]


def generate_candidate_recipes(
    *,
    material_count: int,
    layer_count: int,
    candidate_budget: int,
    seed: int = 0,
) -> CandidateRecipeBatch:
    if material_count <= 0:
        raise ValueError("material_count must be positive")
    if layer_count <= 0:
        raise ValueError("layer_count must be positive")
    if candidate_budget <= 0:
        raise ValueError("candidate_budget must be positive")

    budget = int(candidate_budget)
    pinned = _uniform_recipes(int(material_count), int(layer_count))[:budget]
    remaining = max(0, budget - pinned.shape[0])
    sample_count = max(remaining * 2, remaining)
    sampled = _low_discrepancy_recipes(
        material_count=int(material_count),
        layer_count=int(layer_count),
        count=sample_count,
        seed=int(seed),
    )
    combined = _unique_rows_preserve_order(np.vstack([pinned, sampled]))[:budget]
    while combined.shape[0] < budget:
        extra = _low_discrepancy_recipes(
            material_count=int(material_count),
            layer_count=int(layer_count),
            count=(budget - combined.shape[0]) * 4,
            seed=int(seed) + combined.shape[0] + 1,
        )
        combined = _unique_rows_preserve_order(np.vstack([combined, extra]))[:budget]

    pinned_mask = np.zeros(combined.shape[0], dtype=bool)
    pinned_mask[: min(int(material_count), combined.shape[0])] = True
    return CandidateRecipeBatch(recipes=combined.astype(np.uint16, copy=False), pinned_mask=pinned_mask)
```

- [ ] **Step 4: Add minimal config/memory code for imports**

Create `core/material_candidate_cache.py` with only config and memory estimator needed by the tests:

```python
"""Bounded material candidate runtime.

候选缓存运行时：用有限候选覆盖大耗材空间，避免生产路径穷举 ``M ** N``。
"""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_CANDIDATE_BUILD_MEMORY_BUDGET_BYTES = 8 * 1024 * 1024 * 1024
PREVIEW_SAFE_CANDIDATE_BUDGET = 1_048_576
DEFAULT_PERSISTED_CANDIDATE_BUDGET = 4_194_304
QUALITY_8G_CANDIDATE_BUDGET = 8_388_608


@dataclass(frozen=True)
class MaterialCandidateCacheConfig:
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

    @classmethod
    def preview_safe(cls) -> "MaterialCandidateCacheConfig":
        return cls(candidate_budget=PREVIEW_SAFE_CANDIDATE_BUDGET)

    @classmethod
    def default_persisted(cls) -> "MaterialCandidateCacheConfig":
        return cls(candidate_budget=DEFAULT_PERSISTED_CANDIDATE_BUDGET)

    @classmethod
    def quality_8g(cls) -> "MaterialCandidateCacheConfig":
        return cls(candidate_budget=QUALITY_8G_CANDIDATE_BUDGET)


@dataclass(frozen=True)
class CandidateCacheMemoryEstimate:
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
```

- [ ] **Step 5: Run Task 1 tests and verify GREEN**

Run:

```bash
python -m pytest tests/test_material_candidate_cache_unit.py::test_default_candidate_config_uses_8g_build_budget tests/test_material_candidate_cache_unit.py::test_default_candidate_memory_estimate_fits_8g_budget tests/test_material_candidate_cache_unit.py::test_sobol_candidate_generation_is_deterministic_and_bounded tests/test_material_candidate_cache_unit.py::test_uniform_recipes_are_pinned_before_sobol_candidates -v
```

Expected: PASS.

### Task 2: Candidate Runtime Lookup Contract

**Files:**
- Modify: `tests/test_material_candidate_cache_unit.py`
- Modify: `core/material_candidate_cache.py`

- [ ] **Step 1: Write failing runtime tests**

Append to `tests/test_material_candidate_cache_unit.py`:

```python
def test_candidate_runtime_lookup_returns_solver_cache_shaped_values() -> None:
    from core.material_candidate_cache import build_material_candidate_runtime

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=64, seed=77),
    )

    targets = np.asarray([[180, 80, 60], [40, 70, 180]], dtype=np.uint8)
    matched_rgb, recipes, delta_e = runtime.lookup(targets, SMALL_PALETTE)

    assert runtime.mode == "candidate_hybrid"
    assert runtime.layer_count == 5
    assert runtime.valid_cell_count == 64
    assert matched_rgb.shape == (2, 3)
    assert matched_rgb.dtype == np.uint8
    assert recipes.shape == (2, 5)
    assert recipes.dtype == np.int32
    assert delta_e.shape == (2,)
    assert delta_e.dtype == np.float64


def test_candidate_runtime_rebinds_recipes_to_user_material_order() -> None:
    from core.material_candidate_cache import build_material_candidate_runtime

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=64, seed=88),
    )

    target = np.asarray([[180, 80, 60]], dtype=np.uint8)
    _, original_recipes, _ = runtime.lookup(target, SMALL_PALETTE)
    original_names = [SMALL_PALETTE[index].name for index in original_recipes[0]]

    shuffled = [SMALL_PALETTE[2], SMALL_PALETTE[0], SMALL_PALETTE[1]]
    _, shuffled_recipes, _ = runtime.lookup(target, shuffled)
    shuffled_names = [shuffled[index].name for index in shuffled_recipes[0]]

    assert original_names == shuffled_names
```

- [ ] **Step 2: Run runtime tests and verify RED**

Run:

```bash
python -m pytest tests/test_material_candidate_cache_unit.py::test_candidate_runtime_lookup_returns_solver_cache_shaped_values tests/test_material_candidate_cache_unit.py::test_candidate_runtime_rebinds_recipes_to_user_material_order -v
```

Expected: FAIL with `ImportError: cannot import name 'build_material_candidate_runtime'`.

- [ ] **Step 3: Implement candidate runtime**

Extend `core/material_candidate_cache.py`:

```python
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
    start = 0
    substrate_rgb = _substrate_linear(substrate)
    while start < recipes.shape[0]:
        end = min(start + int(batch_recipe_count), recipes.shape[0])
        batch = recipes[start:end].astype(np.int64, copy=False)
        colors = np.repeat(substrate_rgb[None, :], batch.shape[0], axis=0)
        for layer_index in range(batch.shape[1]):
            material_indices = batch[:, layer_index]
            colors = affines.a[material_indices] * colors + affines.b[material_indices]
        output[start:end] = colors
        start = end
    return np.clip(output, 0.0, 1.0)


@dataclass
class MaterialCandidateRuntime:
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
        return int(self.metadata["lab_grid_resolution"])

    @property
    def valid_cell_count(self) -> int:
        return int(self.candidate_recipes.shape[0])

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

        target_lab = rgb_to_lab(targets).astype(np.float64, copy=False)
        neighbor_count = min(64, self.achieved_lab.shape[0])
        distances, indices = self._ensure_tree().query(target_lab, k=neighbor_count)
        if neighbor_count == 1:
            indices = indices[:, None]
        candidate_lab = self.achieved_lab[indices].astype(np.float64, copy=False)
        delta = np.linalg.norm(candidate_lab - target_lab[:, None, :], axis=2)
        best_offsets = np.argmin(delta, axis=1)
        best_indices = indices[np.arange(targets.shape[0]), best_offsets]

        matched_rgb = self.achieved_srgb[best_indices].astype(np.uint8, copy=True)
        canonical_to_user = np.asarray(canonical_palette_order(user_materials), dtype=np.int32)
        recipes_user = canonical_to_user[self.candidate_recipes[best_indices]].astype(np.int32, copy=False)
        best_delta = delta[np.arange(targets.shape[0]), best_offsets].astype(np.float64, copy=False)
        return matched_rgb, recipes_user, best_delta


def build_material_candidate_runtime(
    *,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    config: MaterialCandidateCacheConfig | None = None,
) -> MaterialCandidateRuntime:
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
        "lab_grid_resolution": int(cfg.lab_grid_resolution),
        "candidate_budget": int(cfg.candidate_budget),
        "seed": int(cfg.seed),
    }
    return MaterialCandidateRuntime(
        candidate_recipes=generated.recipes,
        achieved_srgb=achieved_srgb,
        achieved_lab=achieved_lab,
        pinned_mask=generated.pinned_mask,
        metadata=metadata,
    )
```

- [ ] **Step 4: Run Task 2 tests and verify GREEN**

Run:

```bash
python -m pytest tests/test_material_candidate_cache_unit.py -v
```

Expected: PASS.

### Task 3: Hot Path Runtime Resolver

**Files:**
- Modify: `core/material_lut_provider.py`
- Create: `tests/test_material_lut_provider_candidate_runtime_unit.py`

- [ ] **Step 1: Write resolver tests**

Create `tests/test_material_lut_provider_candidate_runtime_unit.py`:

```python
from __future__ import annotations

import numpy as np

from core.material_candidate_cache import MaterialCandidateRuntime
from core.material_color_solver import MaterialParams


def _mat(name: str, E: tuple[float, float, float], k: tuple[float, float, float]) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(E, dtype=np.float64),
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.asarray((1.0, 1.0, 1.0), dtype=np.float64),
        estimated_rgb=np.asarray([int(round(255 * c)) for c in E], dtype=np.uint8),
    )


PALETTE = [
    _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0)),
    _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0)),
    _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5)),
]


def test_load_solver_runtime_returns_persisted_cache_when_available(monkeypatch) -> None:
    import core.material_lut_provider as provider

    sentinel = object()

    def fake_load_solver_cache(*args, **kwargs):
        return sentinel, 64

    def forbidden_candidate_build(*args, **kwargs):
        raise AssertionError("candidate runtime should not be built when persisted cache exists")

    monkeypatch.setattr(provider, "load_solver_cache", fake_load_solver_cache)
    monkeypatch.setattr(provider, "build_material_candidate_runtime", forbidden_candidate_build)

    runtime, actual_grid = provider.load_solver_runtime(
        PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
    )

    assert runtime is sentinel
    assert actual_grid == 64


def test_load_solver_runtime_builds_candidate_runtime_without_persisted_cache(monkeypatch) -> None:
    import core.material_lut_provider as provider

    monkeypatch.setattr(provider, "load_solver_cache", lambda *args, **kwargs: (None, None))

    runtime, actual_grid = provider.load_solver_runtime(
        PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        candidate_budget=32,
    )

    assert isinstance(runtime, MaterialCandidateRuntime)
    assert runtime.valid_cell_count == 32
    assert actual_grid == runtime.grid_resolution
```

- [ ] **Step 2: Run resolver tests and verify RED**

Run:

```bash
python -m pytest tests/test_material_lut_provider_candidate_runtime_unit.py -v
```

Expected: FAIL with `AttributeError: module 'core.material_lut_provider' has no attribute 'load_solver_runtime'`.

- [ ] **Step 3: Implement resolver**

Modify `core/material_lut_provider.py`:

```python
from core.material_candidate_cache import (
    MaterialCandidateCacheConfig,
    build_material_candidate_runtime,
)

if TYPE_CHECKING:
    from core.material_cache import MaterialSolverCache
    from core.material_candidate_cache import MaterialCandidateRuntime


def load_solver_runtime(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    grid_resolution: int = DEFAULT_GRID_RESOLUTION,
    cache_root: str | Path | None = None,
    candidate_budget: int | None = None,
) -> tuple["MaterialSolverCache | MaterialCandidateRuntime | None", int | None]:
    cache, actual_grid = load_solver_cache(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        grid_resolution=grid_resolution,
        cache_root=cache_root,
    )
    if cache is not None:
        return cache, actual_grid

    config = (
        MaterialCandidateCacheConfig(candidate_budget=int(candidate_budget))
        if candidate_budget is not None
        else MaterialCandidateCacheConfig.preview_safe()
    )
    runtime = build_material_candidate_runtime(
        materials=materials,
        layer_count=int(layer_count),
        layer_height_mm=float(layer_height_mm),
        substrate=str(substrate),
        config=config,
    )
    return runtime, runtime.grid_resolution
```

- [ ] **Step 4: Run resolver tests and verify GREEN**

Run:

```bash
python -m pytest tests/test_material_lut_provider_candidate_runtime_unit.py -v
```

Expected: PASS.

### Task 4: Replace P03 and Vector Fallbacks

**Files:**
- Modify: `core/pipeline/p03_core_processing.py`
- Modify: `core/vector_matchers.py`
- Modify: `tests/test_p03_material_archive_layer_order_unit.py`
- Modify: `tests/test_vector_material_matcher_unit.py`

- [ ] **Step 1: Add P03 regression test**

In `tests/test_p03_material_archive_layer_order_unit.py`, change the three existing tests that currently monkeypatch `core.material_cache.build_material_solver_cache`. Each test must patch the provider resolver instead, while also patching the old builder to raise:

```python
def _patch_solver_runtime(
    monkeypatch: pytest.MonkeyPatch,
    fake_cache: _FakeCache,
    calls: dict[str, int],
) -> None:
    import core.material_lut_provider as provider

    def fake_load_solver_runtime(*args, **kwargs):
        calls["runtime"] += 1
        return fake_cache, 64

    monkeypatch.setattr(provider, "load_solver_runtime", fake_load_solver_runtime)
    monkeypatch.setattr(
        "core.material_cache.build_material_solver_cache",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("P03 fallback must not call old bucketed builder")
        ),
    )
```

Then replace each old pair of monkeypatch calls:

```python
monkeypatch.setattr(
    "core.material_cache.load_material_solver_cache",
    lambda *args, **kwargs: None,
)
monkeypatch.setattr(
    "core.material_cache.build_material_solver_cache",
    lambda **kwargs: fake_cache,
)
```

with:

```python
calls = {"runtime": 0}
_patch_solver_runtime(monkeypatch, fake_cache, calls)
```

After each `_run_material_archive_branch(ctx)` assertion block, add:

```python
assert calls["runtime"] == 1
```

- [ ] **Step 2: Add vector fallback regression test**

Append this test to `tests/test_vector_material_matcher_unit.py`:

```python
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
            "core.material_cache.build_material_solver_cache",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("vector fallback must not call old bucketed builder")
            ),
        )

        materials = [object() for _ in range(3)]
        matcher = MaterialVectorMatcher.from_materials(
            materials=materials,
            layer_count=5,
            layer_height_mm=0.08,
            substrate="white",
            slot_names=["M0", "M1", "M2"],
            preview_colors={0: (0, 0, 0, 255), 1: (80, 80, 80, 255), 2: (160, 160, 160, 255)},
            color_conf={
                "name": "Material",
                "slots": ["M0", "M1", "M2"],
                "preview": {0: (0, 0, 0, 255), 1: (80, 80, 80, 255), 2: (160, 160, 160, 255)},
                "map": {"M0": 0, "M1": 1, "M2": 2},
            },
            grid_resolution=64,
        )

        assert matcher._solver_cache is runtime_stub  # noqa: SLF001
        assert calls["runtime"] == 1
```

- [ ] **Step 3: Run fallback tests and verify RED**

Run:

```bash
python -m pytest tests/test_p03_material_archive_layer_order_unit.py tests/test_vector_material_matcher_unit.py -v
```

Expected: at least one FAIL showing the production code still calls/imports `build_material_solver_cache` for fallback.

- [ ] **Step 4: Change P03 fallback**

In `core/pipeline/p03_core_processing.py`:

```python
from core.material_lut_provider import load_solver_runtime

cache, actual_grid = load_solver_runtime(
    materials=materials,
    layer_count=layer_count,
    layer_height_mm=layer_height_mm,
    substrate=substrate,
    grid_resolution=requested_grid,
)
```

Remove the local `build_material_solver_cache(... grid_resolution=64)` fallback block. Keep the same final `cache.lookup(unique_colors, materials)` call and preserve the existing `ctx["error"]` shape on failure.

- [ ] **Step 5: Change vector fallback**

In `core/vector_matchers.py`, inside `from_material_archive(...)`, import from provider:

```python
from core.material_lut_provider import load_solver_runtime
```

Replace the old `load_material_solver_cache_with_fallback(...)` plus 64-grid builder fallback with:

```python
cache, actual_grid = load_solver_runtime(
    materials=materials,
    layer_count=int(layer_count),
    layer_height_mm=float(layer_height_mm),
    substrate=str(substrate),
    grid_resolution=int(grid_resolution or DEFAULT_GRID_RESOLUTION),
)
if cache is None:
    raise RuntimeError("No material solver runtime could be built for this palette")
```

- [ ] **Step 6: Run fallback tests and verify GREEN**

Run:

```bash
python -m pytest tests/test_p03_material_archive_layer_order_unit.py tests/test_vector_material_matcher_unit.py -v
```

Expected: PASS.

### Task 5: Focused Verification

**Files:**
- No new files.

- [ ] **Step 1: Run core candidate and provider tests**

Run:

```bash
python -m pytest tests/test_material_candidate_cache_unit.py tests/test_material_lut_provider_candidate_runtime_unit.py -v
```

Expected: PASS.

- [ ] **Step 2: Run existing cache regression tests**

Run:

```bash
python -m pytest tests/test_material_cache_unit.py -v
```

Expected: PASS. These tests prove the old exact/bucketed cache compatibility remains intact.

- [ ] **Step 3: Run targeted P03/vector regressions**

Run:

```bash
python -m pytest tests/test_p03_material_archive_layer_order_unit.py tests/test_vector_material_matcher_unit.py -v
```

Expected: PASS.

- [ ] **Step 4: Inspect changed files**

Run:

```bash
git diff -- core/material_candidate_sampling.py core/material_candidate_cache.py core/material_lut_provider.py core/pipeline/p03_core_processing.py core/vector_matchers.py tests/test_material_candidate_cache_unit.py tests/test_material_lut_provider_candidate_runtime_unit.py tests/test_p03_material_archive_layer_order_unit.py tests/test_vector_material_matcher_unit.py
```

Expected: no edits to unrelated files, no changes to protected branches, no removal of old cache loaders/savers.

---

## Self-Review

- Spec coverage:
  - 8GiB 默认预算：Task 1 tests and config.
  - 不新增依赖的 Sobol：Task 1 sampling uses existing SciPy qmc.
  - 避免夸张缓存数量：Task 1 candidate_budget and generation bound.
  - 保证 lookup 契约：Task 2 runtime contract tests.
  - 旧穷举同步优化：Task 4 removes production fallback to low-grid builder while preserving old builder for explicit callers.
  - 不影响其它功能：Task 5 runs old material cache, P03, vector focused regressions.

- Known first-iteration limits:
  - 本计划第一轮先落地 bounded coverage runtime；target-aware inverse refinement 和持久化 candidate `.npz` 可以在该 runtime 稳定后独立 PR。这样 P03/vector 不再触发旧穷举，同时保留旧缓存兼容性。
  - API `/material-solver-cache/build` 仍是 legacy exact/bucketed 构建端点，本轮不改变响应 schema，避免影响前端和现有自动化。

- Placeholder scan:
  - No `TBD` or open-ended implementation step remains.

- Type consistency:
  - `MaterialCandidateCacheConfig`, `MaterialCandidateRuntime`, `build_material_candidate_runtime`, `load_solver_runtime` names are consistent across tests and implementation steps.
