"""LUT-source x renderer orthogonality contract tests.
LUT 来源 x 渲染器 正交性 契约测试.

Why this file exists:
    The user image rendering pipeline supports N LUT sources (photo-5-layer,
    gradient card, externally reverse-inferred) x M renderers (voxel via
    ``core.image_processing``, SVG via ``core.vector_engine``). Every cell
    must produce a valid output. Today all N x M cells work; this test pins
    that invariant so a future LUT source or renderer cannot silently
    regress one cell.

为什么有这个文件:
    用户图像渲染流水线支持 N 种 LUT 来源 x M 种渲染器, 每个组合必须能
    产出有效输出. 当前所有 N x M 组合都通过, 本测试将该不变量钉住, 防止
    未来新增的 LUT 来源或渲染器悄悄破坏某个组合.

When this test fails:
    1. A LUT source's output drifted from the canonical schema (see
       ``core/pipeline/processing_ops/lut_loader.py::_finalize_loaded_lut``).
    2. A renderer started rejecting a previously-working LUT shape.
    3. A new LUT source was added without extending ``LUT_SOURCES`` and
       proving orthogonality across all renderers.

Adding a new LUT source:
    1. Add the source name to ``LUT_SOURCES``.
    2. Implement ``_lut_for_<source_name>(tmp_path)`` producing a canonical
       LUT dict (same shape ``_finalize_loaded_lut`` returns) plus the two
       ``__test_*`` sentinel keys that drive the renderer wrappers.
    3. Run this file; all M renderer cells for the new source must pass.

Adding a new renderer:
    1. Add the renderer name to ``RENDERERS``.
    2. Implement ``_render_<renderer_name>(lut, sample, tmp_path)`` and a
       sample-input entry in ``_SAMPLE_INPUTS``.
    3. Run this file; the new renderer must pass for every LUT source.

Design notes (see ``docs/pipeline-refactor-followup.md`` SS6-7 for full
context):
- This is a SCHEMA-CONTRACT test, not an end-to-end mesh-build test.
  Each cell exercises the LUT-loader path + the renderer's kdtree-query
  hot loop on a tiny synthetic input. Mesh assembly and 3MF write are
  out of scope; they are tested elsewhere via dedicated suites.
- Synthetic LUTs are written to ``tmp_path`` via
  ``LUTManager.save_npz_with_metadata`` so the renderer loads via the
  real ``load_lut`` Branch 0 (``.npz`` pre-stacked path). This proves the
  schema flows end-to-end through the loader without depending on
  production photo fixtures.
- Heavy imports (cv2, scipy, trimesh-via-VectorProcessor) are deferred
  inside factories / wrappers to keep ``pytest --collect-only`` cheap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest


# Parametrize axes — keep these in lockstep with the orthogonality grid.
LUT_SOURCES = ("photo_5layer", "gradient_card", "external_reverse")
RENDERERS = ("voxel", "svg")


# Color mode each LUT source maps to. Drives the renderer ``__init__`` (via
# ``LuminaImageProcessor`` -> ``load_lut(color_mode=...)``).
_LUT_SOURCE_COLOR_MODES: dict[str, str] = {
    "photo_5layer": "4-Color (RYBW)",
    "gradient_card": "4-Color (RYBW)",
    "external_reverse": "Merged",
}


# Sentinel keys carried by each LUT factory's returned dict so the renderer
# wrappers can locate the on-disk ``.npz`` and the matching color mode. The
# leading double-underscore signals "test-internal — not part of the public
# canonical LUT schema".
_LUT_PATH_KEY = "__test_lut_path"
_LUT_COLOR_MODE_KEY = "__test_color_mode"


# Minimal SVG with one solid-fill rectangle. The SVG renderer's color-matching
# hot loop maps shape fills through the LUT's CIELAB kdtree, so a single fill
# is enough to exercise the contract.
SVG_FIXTURE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    '<rect x="0" y="0" width="10" height="10" fill="#ff0000"/>'
    "</svg>"
)


# ---------------------------------------------------------------------------
# Helpers shared across all LUT factories
# ---------------------------------------------------------------------------


def _build_synthetic_rgb(n: int, seed: int) -> np.ndarray:
    """Return a deterministic ``(n, 3)`` ``uint8`` RGB grid.
    返回 deterministic 的 (n, 3) uint8 RGB 网格.
    """
    rng = np.random.RandomState(seed)
    return rng.randint(0, 256, size=(n, 3), dtype=np.uint8)


def _save_lut_npz(
    tmp_path: Path,
    name: str,
    rgb: np.ndarray,
    stacks: np.ndarray,
    color_mode: str,
) -> Path:
    """Serialize ``(rgb, stacks)`` to ``<tmp>/<name>.npz`` via the canonical
    ``LUTManager.save_npz_with_metadata`` writer.
    通过 ``LUTManager.save_npz_with_metadata`` 把 (rgb, stacks) 写到
    ``<tmp>/<name>.npz``.
    """
    from utils.lut_manager import LUTManager

    npz_path = tmp_path / f"{name}.npz"
    metadata = LUTManager.infer_default_metadata(
        name,
        str(npz_path),
        len(rgb),
        color_mode=color_mode,
    )
    LUTManager.save_npz_with_metadata(str(npz_path), rgb, stacks, metadata)
    return npz_path


def _build_canonical_lut_dict(
    rgb: np.ndarray,
    stacks: np.ndarray,
    layer_count: int,
    color_mode: str,
) -> dict[str, Any]:
    """Build the canonical LUT dict via ``_finalize_loaded_lut``.
    通过 ``_finalize_loaded_lut`` 构建标准 LUT dict.

    Routing through the production helper guarantees the factory's dict
    matches what the renderer's loader produces, so any drift surfaces as
    a schema mismatch in the contract test.
    """
    from core.pipeline.processing_ops.lut_loader import _finalize_loaded_lut
    from utils.lut_manager import LUTManager

    metadata = LUTManager.infer_default_metadata(
        "test_synthetic",
        "test_synthetic.npz",
        len(rgb),
        color_mode=color_mode,
    )
    return _finalize_loaded_lut(
        rgb,
        stacks,
        layer_count,
        metadata,
        layer_height_mm=0.08,
    )


def _attach_test_sentinels(
    canonical: dict[str, Any],
    lut_path: Path,
    color_mode: str,
) -> dict[str, Any]:
    """Attach the on-disk path + color mode to the canonical dict so renderer
    wrappers can resolve them.
    把 on-disk 路径与 color mode 写入标准 dict, 供 wrapper 取用.
    """
    canonical[_LUT_PATH_KEY] = str(lut_path)
    canonical[_LUT_COLOR_MODE_KEY] = color_mode
    return canonical


# ---------------------------------------------------------------------------
# LUT factories — one per LUT source
# ---------------------------------------------------------------------------


def _lut_for_photo_5layer(tmp_path: Path) -> dict[str, Any]:
    """Produce a canonical photo-5-layer LUT (4-Color RYBW shape).
    生成标准的拍照 5 层 LUT (4-Color RYBW 形状).

    Mirrors the canonical 1024-row 4-Color RYBW LUT shape that
    ``core.extractor.run_extraction`` emits after the photo Stage A flow:
    1024 RGB rows + ``_generate_recipes("4-Color (RYBW)", 1024)`` stacks.
    Synthetic RGB values are used (no real calibration photo); the
    ``_generate_recipes`` call exercises the production stack generator
    so the stacks shape and dtype are bit-identical to a real run.
    """
    from core.extractor import _generate_recipes

    color_mode = _LUT_SOURCE_COLOR_MODES["photo_5layer"]
    n = 1024
    layer_count = 5

    rgb = _build_synthetic_rgb(n, seed=1)
    stacks = _generate_recipes(color_mode, n).astype(np.int32)
    assert stacks.shape == (n, layer_count), (
        f"_generate_recipes produced unexpected shape {stacks.shape}; "
        f"expected ({n}, {layer_count})"
    )

    npz_path = _save_lut_npz(tmp_path, "photo_5layer", rgb, stacks, color_mode)
    canonical = _build_canonical_lut_dict(rgb, stacks, layer_count, color_mode)
    return _attach_test_sentinels(canonical, npz_path, color_mode)


def _lut_for_gradient_card(tmp_path: Path) -> dict[str, Any]:
    """Produce a synthetic gradient-card-shaped LUT.
    生成渐变卡形状的合成 LUT.

    The real gradient-card path (Stage A gradient) takes a photographed
    gradient card and infers a smaller LUT than the 1024-row photo-5-layer
    canonical shape. Driving that path inside a unit test would require a
    real photographed gradient card fixture, which is out of scope for an
    orthogonality contract test (the contract is the LUT *schema*, not the
    production source). This factory simulates the result: a 256-row LUT
    in the same 4-Color RYBW recipe space, with monotonic stacks derived
    by 4-base digit decomposition (the same generator used by the
    production 1024-row path, just truncated).
    """
    color_mode = _LUT_SOURCE_COLOR_MODES["gradient_card"]
    n = 256
    layer_count = 5

    rgb = _build_synthetic_rgb(n, seed=2)
    stacks = np.zeros((n, layer_count), dtype=np.int32)
    for i in range(n):
        digits: list[int] = []
        temp = i
        for _ in range(layer_count):
            digits.append(temp % 4)
            temp //= 4
        stacks[i] = digits

    npz_path = _save_lut_npz(tmp_path, "gradient_card", rgb, stacks, color_mode)
    canonical = _build_canonical_lut_dict(rgb, stacks, layer_count, color_mode)
    return _attach_test_sentinels(canonical, npz_path, color_mode)


def _lut_for_external_reverse(tmp_path: Path) -> dict[str, Any]:
    """Produce a synthetic externally reverse-inferred LUT (Merged shape).
    生成外部逆推的合成 LUT (Merged 形状).

    Externally reverse-inferred LUTs (the ``.npz`` import / ``Merged`` mode
    path) carry arbitrary row counts and arbitrary material-id stacks
    within the 8-color material space. This factory emits 500 rows of
    deterministic random RGB + arbitrary stacks in ``[0, 8)`` to exercise
    the Merged dispatch in ``lut_loader.load_lut`` Branch 0.
    """
    color_mode = _LUT_SOURCE_COLOR_MODES["external_reverse"]
    n = 500
    layer_count = 5

    rgb = _build_synthetic_rgb(n, seed=3)
    rng = np.random.RandomState(4)
    stacks = rng.randint(0, 8, size=(n, layer_count), dtype=np.int32)

    npz_path = _save_lut_npz(tmp_path, "external_reverse", rgb, stacks, color_mode)
    canonical = _build_canonical_lut_dict(rgb, stacks, layer_count, color_mode)
    return _attach_test_sentinels(canonical, npz_path, color_mode)


_LUT_FACTORIES = {
    "photo_5layer": _lut_for_photo_5layer,
    "gradient_card": _lut_for_gradient_card,
    "external_reverse": _lut_for_external_reverse,
}


# ---------------------------------------------------------------------------
# Renderer wrappers — one per renderer
# ---------------------------------------------------------------------------


def _sample_voxel_input() -> np.ndarray:
    """Tiny 8x8 RGB image used to exercise the voxel renderer hot loop.
    用于体素渲染器热环的 8x8 RGB 小图.
    """
    rng = np.random.RandomState(42)
    return rng.randint(0, 256, size=(8, 8, 3), dtype=np.uint8)


def _rgb_to_lab(rgb_flat: np.ndarray) -> np.ndarray:
    """Convert an ``(N, 3)`` ``uint8`` RGB array to ``(N, 3)`` ``float64``
    CIELAB via OpenCV. Matches the production conversion in
    ``lut_loader._rgb_to_lab``.
    """
    import cv2

    rgb_3d = rgb_flat.reshape(1, -1, 3).astype(np.uint8)
    bgr = cv2.cvtColor(rgb_3d, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).reshape(-1, 3).astype(np.float64)
    return lab


def _render_voxel(
    lut: dict[str, Any],
    sample_input: np.ndarray,
    tmp_path: Path,
) -> np.ndarray:
    """Run the voxel renderer's LUT-consumer hot loop on the sample image.
    运行体素渲染器的 LUT 消费热环.

    Instantiates ``LuminaImageProcessor`` (the voxel renderer's LUT
    consumer entry point), which loads the on-disk ``.npz`` via
    ``load_lut`` and exposes ``ref_stacks`` / ``lut_lab`` / ``kdtree`` /
    ``layer_count`` as instance attributes. Then runs ``kdtree.query`` on
    the sample image's pixels in CIELAB, the canonical color-matching hot
    loop, and asserts the matched indices map to valid stack rows.
    """
    from core.image_processing import LuminaImageProcessor

    processor = LuminaImageProcessor(lut[_LUT_PATH_KEY], lut[_LUT_COLOR_MODE_KEY])

    # Renderer accepted the LUT — the canonical schema fields are populated
    # exactly as ``_finalize_loaded_lut`` produces them.
    assert processor.ref_stacks is not None
    assert processor.kdtree is not None
    assert processor.lut_lab is not None
    assert processor.layer_count == lut["layer_count"], (
        f"voxel renderer surfaced layer_count={processor.layer_count}; "
        f"factory produced {lut['layer_count']}"
    )

    flat_rgb = sample_input.reshape(-1, 3).astype(np.uint8)
    lab = _rgb_to_lab(flat_rgb)
    _, indices = processor.kdtree.query(lab)
    indices = np.asarray(indices)

    n_lut = processor.ref_stacks.shape[0]
    assert indices.shape == (flat_rgb.shape[0],)
    assert int(indices.max()) < n_lut
    assert int(indices.min()) >= 0
    return processor.ref_stacks[indices]


def _render_svg(
    lut: dict[str, Any],
    sample_input: str,
    tmp_path: Path,
) -> np.ndarray:
    """Run the SVG renderer's LUT-consumer hot loop on the sample SVG.
    运行 SVG 渲染器的 LUT 消费热环.

    Instantiates ``VectorProcessor`` (the SVG renderer's LUT consumer
    entry point), which internally creates a ``LuminaImageProcessor`` and
    so reuses the same ``load_lut`` path as the voxel renderer. Then
    extracts the SVG's fill color and runs ``kdtree.query`` over its Lab
    representation, mirroring the per-shape color matching that
    ``VectorProcessor`` performs at scale on real SVGs.
    """
    import re

    from core.vector_engine import VectorProcessor

    processor = VectorProcessor(lut[_LUT_PATH_KEY], lut[_LUT_COLOR_MODE_KEY])
    inner = processor.img_processor

    assert inner.ref_stacks is not None
    assert inner.kdtree is not None
    assert inner.lut_lab is not None
    assert inner.layer_count == lut["layer_count"], (
        f"svg renderer surfaced layer_count={inner.layer_count}; "
        f"factory produced {lut['layer_count']}"
    )

    fill_match = re.search(r'fill="(#[0-9a-fA-F]{6})"', sample_input)
    assert fill_match is not None, "SVG fixture must carry a #RRGGBB fill"
    hex_color = fill_match.group(1)
    rgb = np.array(
        [
            [
                int(hex_color[1:3], 16),
                int(hex_color[3:5], 16),
                int(hex_color[5:7], 16),
            ],
        ],
        dtype=np.uint8,
    )

    lab = _rgb_to_lab(rgb)
    _, indices = inner.kdtree.query(lab)
    indices = np.atleast_1d(np.asarray(indices))

    n_lut = inner.ref_stacks.shape[0]
    assert indices.shape == (1,)
    assert int(indices.max()) < n_lut
    assert int(indices.min()) >= 0
    return inner.ref_stacks[indices]


_RENDERERS = {
    "voxel": _render_voxel,
    "svg": _render_svg,
}


# Sample inputs are produced lazily for voxel (np.random) and reused eagerly
# for svg (immutable string).
_SAMPLE_INPUTS: dict[str, Any] = {
    "voxel": _sample_voxel_input,
    "svg": SVG_FIXTURE,
}


def _resolve_sample_input(renderer: str) -> Any:
    """Resolve the sample input for ``renderer`` (call factory if callable).
    解析 ``renderer`` 的样本输入 (callable 时调用).
    """
    sample = _SAMPLE_INPUTS[renderer]
    return sample() if callable(sample) else sample


def _assert_output_format_valid(renderer: str, output: Any) -> None:
    """Format-specific output validation.
    特定渲染器的输出校验.

    Both renderers in the current grid return matched ``ref_stacks`` rows
    (a ``(K, layer_count)`` integer array). Future renderers that produce
    different output shapes should add their own branch here.
    """
    assert isinstance(output, np.ndarray), (
        f"{renderer} returned non-ndarray output: {type(output).__name__}"
    )
    assert output.size > 0, f"{renderer} returned empty output"
    assert np.issubdtype(output.dtype, np.integer), (
        f"{renderer} returned non-integer output dtype {output.dtype}; "
        "matched stacks must be integer-typed"
    )


# ---------------------------------------------------------------------------
# The contract test — 3 LUT sources x 2 renderers = 6 cells
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("renderer", RENDERERS)
@pytest.mark.parametrize("lut_source", LUT_SOURCES)
def test_lut_source_x_renderer_orthogonality(
    lut_source: str,
    renderer: str,
    tmp_path: Path,
) -> None:
    """Every (LUT source, renderer) cell must produce a valid output.
    每个 (LUT 来源, 渲染器) 组合都必须能产生有效输出.

    Failure modes pinned by this test:
    - A LUT source emits an out-of-schema dict (missing keys, wrong dtypes).
    - A renderer rejects a canonical-schema LUT.
    - A future PR adds a LUT source / renderer without proving orthogonality
      across the entire grid.

    Args:
        lut_source: One of ``LUT_SOURCES``.
        renderer: One of ``RENDERERS``.
        tmp_path: pytest temp-directory fixture (per-test isolation).
    """
    lut = _LUT_FACTORIES[lut_source](tmp_path)

    # Schema contract — every LUT source must satisfy the canonical schema
    # produced by ``_finalize_loaded_lut``.
    assert isinstance(lut, dict), f"{lut_source} factory must return a dict"
    assert "lut_rgb" in lut and lut["lut_rgb"].dtype == np.uint8
    assert "ref_stacks" in lut and np.issubdtype(lut["ref_stacks"].dtype, np.integer)
    assert "lut_lab" in lut and lut["lut_lab"].dtype == np.float64
    assert "kdtree" in lut and lut["kdtree"] is not None
    assert "layer_count" in lut and isinstance(lut["layer_count"], int)
    assert lut["lut_rgb"].shape[0] == lut["ref_stacks"].shape[0]
    assert lut["lut_rgb"].shape[0] == lut["lut_lab"].shape[0]
    assert lut["ref_stacks"].shape[1] == lut["layer_count"]

    # Renderer contract — every renderer must consume the canonical LUT and
    # surface valid matched stacks via the kdtree-query hot loop.
    sample_input = _resolve_sample_input(renderer)
    output = _RENDERERS[renderer](lut, sample_input, tmp_path)

    # Output contract — non-None + format-specific shape check.
    assert output is not None, f"{renderer} produced None for {lut_source} LUT"
    _assert_output_format_valid(renderer, output)
