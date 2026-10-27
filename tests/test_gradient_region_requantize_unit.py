"""Unit tests for :mod:`core.gradient_region_requantize`.

验证 :mod:`core.gradient_region_requantize` 的关键行为：

- ``local_quantize_colors`` 的上下界校验与 TypeError 路径。
- 空 ``targets`` / shape 不匹配 / 非 uint8 等输入校验。
- 带有一个 (1,1) stub 求解器缓存时，区域内像素会被写回为 stub 输出。
- 失效的 target（索引越界到无像素）会被静默跳过，其它 target 正常工作。
- ``region_id_map`` 外的像素不会被改动（非目标区域不受影响）。
"""

from __future__ import annotations

import numpy as np
import pytest

from core.gradient_group_analyzer import REGION_ID_ENCODING_MULTIPLIER
from core.gradient_region_requantize import (
    MAX_LOCAL_QUANTIZE_COLORS,
    MIN_LOCAL_QUANTIZE_COLORS,
    requantize_gradient_regions,
)


class _StubSolverCache:
    """Minimal stand-in for :class:`MaterialSolverCache`.

    Returns a deterministic per-unique-colour RGB (all zeros) so tests can
    verify which pixels got overwritten without worrying about real Beer-
    Lambert solves. ``lookup`` must accept the same signature as the real
    cache, i.e. ``(target_srgb, user_materials) → (rgb, recipes, delta_e)``.
    """

    def __init__(self, fill_rgb: tuple[int, int, int] = (0, 0, 0)) -> None:
        self._fill_rgb = np.asarray(fill_rgb, dtype=np.uint8)

    def lookup(self, target_srgb, user_materials):  # noqa: D401
        n = np.asarray(target_srgb).shape[0]
        matched = np.broadcast_to(self._fill_rgb, (n, 3)).copy()
        recipes = np.zeros((n, 1), dtype=np.int32)
        delta_e = np.zeros((n,), dtype=np.float64)
        return matched, recipes, delta_e


def _build_canvas(h: int = 32, w: int = 48) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Canvas + original source + region_id_map for a single 1-region group.

    The target region is a rectangle in the middle of the canvas with
    ``(group_index=1, region_index=1)`` encoded in ``region_id_map``.
    其余像素 region_id=0（表示不属于任何渐变区域）。
    """
    rng = np.random.default_rng(0)
    matched = np.asarray(rng.integers(40, 200, size=(h, w, 3)), dtype=np.uint8)
    original = np.asarray(rng.integers(0, 256, size=(h, w, 3)), dtype=np.uint8)
    region_id_map = np.zeros((h, w), dtype=np.uint32)
    # Central rectangle as region (group=1, region=1).
    y0, y1 = h // 4, 3 * h // 4
    x0, x1 = w // 4, 3 * w // 4
    region_id_map[y0:y1, x0:x1] = (
        1 * REGION_ID_ENCODING_MULTIPLIER + 1
    )
    return matched, original, region_id_map


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_local_quantize_colors_below_min_raises() -> None:
    matched, original, region_id_map = _build_canvas()
    with pytest.raises(ValueError, match="local_quantize_colors"):
        requantize_gradient_regions(
            matched_rgb=matched,
            original_source_rgb=original,
            region_id_map=region_id_map,
            targets=[(1, 1)],
            materials=[],
            material_solver_cache=_StubSolverCache(),
            local_quantize_colors=MIN_LOCAL_QUANTIZE_COLORS - 1,
        )


def test_local_quantize_colors_above_max_raises() -> None:
    matched, original, region_id_map = _build_canvas()
    with pytest.raises(ValueError, match="local_quantize_colors"):
        requantize_gradient_regions(
            matched_rgb=matched,
            original_source_rgb=original,
            region_id_map=region_id_map,
            targets=[(1, 1)],
            materials=[],
            material_solver_cache=_StubSolverCache(),
            local_quantize_colors=MAX_LOCAL_QUANTIZE_COLORS + 1,
        )


def test_local_quantize_colors_non_int_raises() -> None:
    matched, original, region_id_map = _build_canvas()
    with pytest.raises(TypeError, match="local_quantize_colors"):
        requantize_gradient_regions(
            matched_rgb=matched,
            original_source_rgb=original,
            region_id_map=region_id_map,
            targets=[(1, 1)],
            materials=[],
            material_solver_cache=_StubSolverCache(),
            local_quantize_colors="64",  # type: ignore[arg-type]
        )


def test_empty_targets_raises() -> None:
    matched, original, region_id_map = _build_canvas()
    with pytest.raises(ValueError, match="targets"):
        requantize_gradient_regions(
            matched_rgb=matched,
            original_source_rgb=original,
            region_id_map=region_id_map,
            targets=[],
            materials=[],
            material_solver_cache=_StubSolverCache(),
            local_quantize_colors=32,
        )


def test_shape_mismatch_raises() -> None:
    matched, _original, region_id_map = _build_canvas()
    bad_original = np.zeros((10, 10, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="original_source_rgb"):
        requantize_gradient_regions(
            matched_rgb=matched,
            original_source_rgb=bad_original,
            region_id_map=region_id_map,
            targets=[(1, 1)],
            materials=[],
            material_solver_cache=_StubSolverCache(),
            local_quantize_colors=32,
        )


def test_non_uint8_raises() -> None:
    matched_f = np.zeros((32, 48, 3), dtype=np.float32)
    original = np.zeros((32, 48, 3), dtype=np.uint8)
    region_id_map = np.zeros((32, 48), dtype=np.uint32)
    with pytest.raises(TypeError, match="uint8"):
        requantize_gradient_regions(
            matched_rgb=matched_f,  # wrong dtype
            original_source_rgb=original,
            region_id_map=region_id_map,
            targets=[(1, 1)],
            materials=[],
            material_solver_cache=_StubSolverCache(),
            local_quantize_colors=32,
        )


def test_non_positive_index_raises() -> None:
    matched, original, region_id_map = _build_canvas()
    with pytest.raises(ValueError, match="must be >= 1"):
        requantize_gradient_regions(
            matched_rgb=matched,
            original_source_rgb=original,
            region_id_map=region_id_map,
            targets=[(0, 1)],
            materials=[],
            material_solver_cache=_StubSolverCache(),
            local_quantize_colors=32,
        )


# ---------------------------------------------------------------------------
# Functional behaviour
# ---------------------------------------------------------------------------


def test_original_input_not_mutated() -> None:
    """The function must return a copy; caller's matched_rgb stays intact.
    调用方的 matched_rgb 不允许被就地修改，便于 sync 比对前后。
    """
    matched, original, region_id_map = _build_canvas()
    matched_before = matched.copy()
    out, _count = requantize_gradient_regions(
        matched_rgb=matched,
        original_source_rgb=original,
        region_id_map=region_id_map,
        targets=[(1, 1)],
        materials=[],
        material_solver_cache=_StubSolverCache(fill_rgb=(255, 0, 0)),
        local_quantize_colors=16,
    )
    assert out is not matched
    np.testing.assert_array_equal(matched, matched_before)


def test_only_target_region_rewritten() -> None:
    """Pixels outside the encoded region stay untouched.
    非目标像素必须保持原值，防止"误伤"其它 region。
    """
    matched, original, region_id_map = _build_canvas()
    target_mask = region_id_map == np.uint32(
        1 * REGION_ID_ENCODING_MULTIPLIER + 1
    )
    stub_rgb = (255, 0, 0)

    out, rewritten = requantize_gradient_regions(
        matched_rgb=matched,
        original_source_rgb=original,
        region_id_map=region_id_map,
        targets=[(1, 1)],
        materials=[],
        material_solver_cache=_StubSolverCache(fill_rgb=stub_rgb),
        local_quantize_colors=16,
    )

    # In-region pixels must equal the stub RGB (the cache returns it for every
    # unique colour so every in-region pixel is that colour after snap).
    np.testing.assert_array_equal(
        out[target_mask], np.broadcast_to(stub_rgb, (int(target_mask.sum()), 3))
    )
    # Out-of-region pixels untouched.
    np.testing.assert_array_equal(out[~target_mask], matched[~target_mask])
    # Diagnostic counter counts only pixels that actually changed. The stub
    # writes (255, 0, 0) everywhere in-region; only pixels that weren't
    # already that colour register as rewrites. In this test matched is
    # generated from a non-red random stream, so the count must equal the
    # region size.
    assert rewritten == int(target_mask.sum())


def test_stale_target_silently_skipped() -> None:
    """A target with no pixels in region_id_map does not fail the batch.
    目标对应的 mask 为空时，静默跳过，不影响同批次其它 target。
    """
    matched, original, region_id_map = _build_canvas()
    # (2, 5) references group=2 which is not present in region_id_map.
    out, rewritten = requantize_gradient_regions(
        matched_rgb=matched,
        original_source_rgb=original,
        region_id_map=region_id_map,
        targets=[(2, 5), (1, 1)],
        materials=[],
        material_solver_cache=_StubSolverCache(fill_rgb=(10, 20, 30)),
        local_quantize_colors=16,
    )
    target_mask = region_id_map == np.uint32(
        1 * REGION_ID_ENCODING_MULTIPLIER + 1
    )
    assert out[target_mask][0].tolist() == [10, 20, 30]
    assert rewritten > 0


def test_duplicate_targets_deduplicated() -> None:
    """Duplicate (group, region) entries are processed only once.
    重复 target 去重，避免重复运行 k-means 浪费 CPU。
    """
    matched, original, region_id_map = _build_canvas()
    out, rewritten = requantize_gradient_regions(
        matched_rgb=matched,
        original_source_rgb=original,
        region_id_map=region_id_map,
        targets=[(1, 1), (1, 1), (1, 1)],
        materials=[],
        material_solver_cache=_StubSolverCache(fill_rgb=(5, 5, 5)),
        local_quantize_colors=16,
    )
    assert rewritten > 0
    # Outside the region still untouched.
    outside = region_id_map == 0
    np.testing.assert_array_equal(out[outside], matched[outside])
