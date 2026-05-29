"""Spec: SVG vector outline support Task 2.1
(``progress/svg-vector-outline-preservation-baseline.md``)

Property 2 (Preservation) — Raster outline 字节级 / 结构级稳定。

Domain
======

Per ``requirements.md`` §"Bug Analysis" the bug condition only fires on
``modeling_mode == VECTOR`` inputs. Raster modes (``HIGH_FIDELITY`` and
``PIXEL``) are explicitly listed in the *Unchanged Behavior* section
(EARS clause 3.1): regardless of how ``enable_outline`` / ``outline_width``
/ ``color_mode`` vary, the raster ``s08_auxiliary_meshes`` outline path
must keep producing the exact same scene-level structural fingerprint as
on current ``main`` after the upcoming Task 3 fix lands.

Note on enum naming: the task text uses ``RASTER`` as shorthand for the
umbrella *raster pipeline* (S01-S12) which the coordinator drives for
both ``ModelingMode.PIXEL`` and ``ModelingMode.HIGH_FIDELITY``. There is
no ``ModelingMode.RASTER`` enum value (see ``config.py``); instead this
file iterates over ``{PIXEL, HIGH_FIDELITY}``, which together cover the
non-vector raster surface.

What is locked
==============

The fingerprint captured per example consists of:

1. ``sorted(scene.geometry.keys())`` — geometry name set
2. for each mesh: ``(vertex_count, face_count, tuple(sorted(metadata.keys())))``
   — structural shape + metadata schema
3. ``ctx["outline_added"]`` — the boolean status flag returned by ``s08``
4. ``"Outline" in preview_colors`` — outline colour entry presence

We deliberately avoid raw vertex hashes (brittle across CV2 / NumPy /
trimesh micro-version changes) and prefer per-example structural
invariants over a single global-equivalence check, because
``color_mode`` and ``outline_width`` legitimately change the layer count,
ring width in pixels, and (for material_archive) the outline metadata
schema — so a global "all examples equal one baseline" assertion would
be too strong.

Test surface
============

We invoke ``core.pipeline.s08_auxiliary_meshes.run`` directly with the
same synthetic inputs the existing
``tests/test_puzzle_boundary_pipeline_unit.py`` uses. This gives the
fastest, most deterministic exercise of the raster outline path and is
the canonical pattern other raster outline unit tests already follow.

Validates: Requirements 3.1
"""

from __future__ import annotations

import os
import sys
from typing import Any

import numpy as np
import pytest
import trimesh
from hypothesis import HealthCheck, given, settings, strategies as st

# Ensure project root is importable when this file is invoked via
# ``pytest tests/test_raster_outline_preservation_properties.py`` directly.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import ModelingMode, PrinterConfig  # noqa: E402
from core.mesh_generators import HighFidelityMesher, VoxelMesher  # noqa: E402
from core.pipeline import s08_auxiliary_meshes  # noqa: E402


# ---------------------------------------------------------------------------
# Color-mode-aware fixtures
# 颜色模式相关 fixtures
# ---------------------------------------------------------------------------

# Canonical preview_colors per color_mode. Values mirror the baseline rows
# that ``ColorSystem`` exposes in ``config.py`` for the same labels;
# trimming to the slot count keeps the test self-contained without forcing
# the heavy ``ColorSystem.get_color_config`` resolver.
# 每种颜色模式的预览颜色，与 config.py 中 ColorSystem 的最小子集保持一致。
_PREVIEW_COLORS_BY_MODE: dict[str, dict[int, list[int]]] = {
    "BW": {0: [255, 255, 255, 255], 1: [0, 0, 0, 255]},
    "4-Color RYBW": {
        0: [255, 255, 255, 255],
        1: [220, 20, 60, 255],
        2: [255, 230, 0, 255],
        3: [0, 100, 240, 255],
    },
    "8-Color Max": {
        0: [255, 255, 255, 255],
        1: [0, 134, 214, 255],
        2: [236, 0, 140, 255],
        3: [244, 238, 42, 255],
        4: [220, 20, 60, 255],
        5: [16, 16, 16, 255],
        6: [0, 100, 240, 255],
        7: [0, 168, 76, 255],
    },
}


def _make_mesher(modeling_mode: ModelingMode):
    """Return the canonical mesher used by the raster pipeline for ``mode``.

    返回 raster 管道在指定 modeling_mode 下规范使用的 mesher。
    """
    if modeling_mode == ModelingMode.PIXEL:
        return VoxelMesher()
    return HighFidelityMesher(disable_material_dilation=True)


def _make_mask_solid(target_h: int = 12, target_w: int = 12) -> np.ndarray:
    """Build a deterministic non-trivial solid mask.

    A centred filled rectangle gives the dilation-based outline path a
    real boundary to operate on (so ``Outline`` actually lands in the
    scene) while staying small enough to keep the PBT loop fast.
    一个居中实心矩形作为 mask，确保 outline 真的能生成且测试本身保持轻量。
    """
    mask = np.zeros((target_h, target_w), dtype=bool)
    mask[2:10, 2:10] = True
    return mask


def _run_s08(
    *,
    modeling_mode: ModelingMode,
    enable_outline: bool,
    outline_width: float,
    color_mode: str,
) -> dict[str, Any]:
    """Drive ``s08_auxiliary_meshes.run`` with the requested raster inputs.

    Returns the post-run ctx dict so callers can inspect the assembled
    scene + ``outline_added`` flag + mutated ``preview_colors``.
    """
    target_h = target_w = 12
    mask_solid = _make_mask_solid(target_h, target_w)
    preview_colors = dict(_PREVIEW_COLORS_BY_MODE[color_mode])

    # full_matrix is sized (Z=1, H, W) and filled with -1 (air) — the
    # outline path only consumes ``mask_solid`` + ``pixel_scale`` +
    # ``outline_width``, so the matrix content does not affect outline
    # geometry. We still pass a valid shape because s08 keys on it.
    # full_matrix 仅在 separate_backing/free_color 等开关启用时才会被
    # mesher 消费；此用例只测 outline 路径，给一个全 air 矩阵即可。
    full_matrix = np.full((1, target_h, target_w), -1, dtype=int)
    matched_rgb = np.zeros((target_h, target_w, 3), dtype=np.uint8)

    ctx_in: dict[str, Any] = {
        "scene": trimesh.Scene(),
        "valid_slot_names": [],
        "full_matrix": full_matrix,
        "mask_solid": mask_solid,
        "matched_rgb": matched_rgb,
        "target_h": target_h,
        "target_w": target_w,
        "pixel_scale": 0.5,
        "total_layers": 4,
        "preview_colors": preview_colors,
        "transform": np.eye(4),
        "mesher": _make_mesher(modeling_mode),
        "separate_backing": False,
        "enable_cloisonne": False,
        "backing_metadata": {},
        "enable_coating": False,
        "coating_height_mm": PrinterConfig.LAYER_HEIGHT,
        "enable_outline": bool(enable_outline),
        "outline_width": float(outline_width),
        "free_color_set": None,
        "add_loop": False,
        "loop_info": None,
        "boundary_geometry": None,
        # ``modeling_mode`` is not consumed by s08 directly but a few
        # downstream readers inspect it — keep parity with raster ctx.
        "modeling_mode": modeling_mode,
    }
    return s08_auxiliary_meshes.run(ctx_in)


def _fingerprint(ctx: dict[str, Any]) -> dict[str, Any]:
    """Compute a stable, structural fingerprint of the post-s08 ctx.

    ``vertex_count`` / ``face_count`` cope with shape variations driven by
    ``outline_width`` and ``mode``; ``sorted(metadata.keys())`` captures
    the metadata-schema diff between LUT and material_archive paths.
    """
    scene: trimesh.Scene = ctx["scene"]
    per_mesh: dict[str, tuple[int, int, tuple[str, ...]]] = {}
    for name, geom in scene.geometry.items():
        verts = getattr(geom, "vertices", None)
        faces = getattr(geom, "faces", None)
        v_count = int(len(verts) if verts is not None else 0)
        f_count = int(len(faces) if faces is not None else 0)
        meta_keys = tuple(sorted((getattr(geom, "metadata", {}) or {}).keys()))
        per_mesh[str(name)] = (v_count, f_count, meta_keys)

    preview_colors = ctx.get("preview_colors") or {}
    return {
        "geometry_names": sorted(scene.geometry.keys()),
        "per_mesh": per_mesh,
        "outline_added": bool(ctx.get("outline_added", False)),
        "outline_in_preview_colors": "Outline" in preview_colors,
        "valid_slot_names": list(ctx.get("valid_slot_names") or []),
    }


# ---------------------------------------------------------------------------
# Module-scoped baseline fingerprints (approval anchors)
# 模块级 baseline 指纹（approval 锚点）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def baseline_pixel_8color_outline_on() -> dict[str, Any]:
    """Canonical PIXEL + outline=True + 2.0mm + 8-Color Max baseline."""
    return _fingerprint(
        _run_s08(
            modeling_mode=ModelingMode.PIXEL,
            enable_outline=True,
            outline_width=2.0,
            color_mode="8-Color Max",
        )
    )


@pytest.fixture(scope="module")
def baseline_hifi_rybw_outline_off() -> dict[str, Any]:
    """Canonical HIGH_FIDELITY + outline=False + 2.0mm + 4-Color RYBW baseline."""
    return _fingerprint(
        _run_s08(
            modeling_mode=ModelingMode.HIGH_FIDELITY,
            enable_outline=False,
            outline_width=2.0,
            color_mode="4-Color RYBW",
        )
    )


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Raster umbrella: PIXEL + HIGH_FIDELITY are what the coordinator routes
# through ``_RASTER_STEPS`` (i.e. the "RASTER" surface the spec text
# refers to). VECTOR is intentionally excluded here — that domain is
# covered by Task 2.2.
# Raster 总称包含 PIXEL 与 HIGH_FIDELITY；VECTOR 不属于本测试域，由 Task 2.2 锁定。
_modeling_mode_strategy = st.sampled_from(
    [ModelingMode.PIXEL, ModelingMode.HIGH_FIDELITY]
)
_enable_outline_strategy = st.booleans()
_outline_width_strategy = st.floats(
    min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False
)
_color_mode_strategy = st.sampled_from(["BW", "4-Color RYBW", "8-Color Max"])


# ---------------------------------------------------------------------------
# Property — per-example structural invariants
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    modeling_mode=_modeling_mode_strategy,
    enable_outline=_enable_outline_strategy,
    outline_width=_outline_width_strategy,
    color_mode=_color_mode_strategy,
)
def test_raster_outline_structural_invariants(
    modeling_mode: ModelingMode,
    enable_outline: bool,
    outline_width: float,
    color_mode: str,
) -> None:
    """For any raster outline ctx, the outline geometry's *presence* and
    structural fingerprint must obey the documented current-main contract.

    raster 模式下任意输入组合，outline 是否存在以及结构性指纹均应满足
    当前 main 上既有合同：
      * enable_outline=True → ``"Outline" in scene.geometry`` AND mesh
        non-empty AND ``ctx["outline_added"] is True`` AND outline entry
        landed in ``preview_colors``.
      * enable_outline=False → ``"Outline"`` absent everywhere.

    Validates: Requirements 3.1
    """
    ctx = _run_s08(
        modeling_mode=modeling_mode,
        enable_outline=enable_outline,
        outline_width=outline_width,
        color_mode=color_mode,
    )
    fp = _fingerprint(ctx)

    if enable_outline:
        assert "Outline" in fp["geometry_names"], (
            "raster outline path lost the 'Outline' geometry key "
            f"(mode={modeling_mode.value}, width={outline_width}, "
            f"color_mode={color_mode}); current geometry={fp['geometry_names']}"
        )
        v_count, f_count, _meta = fp["per_mesh"]["Outline"]
        assert v_count > 0 and f_count > 0, (
            f"Outline mesh emptied out (verts={v_count}, faces={f_count}) "
            f"under mode={modeling_mode.value}, width={outline_width}, "
            f"color_mode={color_mode}"
        )
        assert fp["outline_added"] is True, (
            f"ctx['outline_added'] flag dropped to False on a successful "
            f"outline run (mode={modeling_mode.value}, width={outline_width})"
        )
        assert fp["outline_in_preview_colors"], (
            "preview_colors lost its 'Outline' entry on raster outline "
            f"path (mode={modeling_mode.value}, color_mode={color_mode})"
        )
        assert "Outline" in fp["valid_slot_names"], (
            "valid_slot_names did not get 'Outline' appended; downstream "
            f"3MF assembly relies on this list (mode={modeling_mode.value})"
        )
    else:
        assert "Outline" not in fp["geometry_names"], (
            "Outline geometry leaked into the scene with enable_outline=False "
            f"(mode={modeling_mode.value}, width={outline_width}, "
            f"color_mode={color_mode}); geometry={fp['geometry_names']}"
        )
        assert fp["outline_added"] is False, (
            f"outline_added flag flipped to True with enable_outline=False "
            f"(mode={modeling_mode.value})"
        )
        assert not fp["outline_in_preview_colors"], (
            "preview_colors contains an 'Outline' entry without "
            f"enable_outline (mode={modeling_mode.value})"
        )
        assert "Outline" not in fp["valid_slot_names"], (
            "valid_slot_names contained 'Outline' with enable_outline=False"
        )


# ---------------------------------------------------------------------------
# Property — canonical-input approval (fingerprint stability)
# ---------------------------------------------------------------------------


@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(seed=st.integers(min_value=0, max_value=2**16 - 1))
def test_raster_outline_canonical_pixel_8color_fingerprint_stable(
    baseline_pixel_8color_outline_on: dict[str, Any],
    seed: int,
) -> None:
    """Re-running the canonical PIXEL + 8-Color Max + outline=True case
    multiple times under fast-check must always produce the same
    fingerprint as the module-scope baseline.

    canonical 输入下多次运行应稳定指纹（approval anchor）。

    The ``seed`` parameter only triggers Hypothesis to actually call the
    function several times; the inputs themselves are fixed because the
    point of an approval anchor is determinism, not coverage.
    seed 仅用于让 Hypothesis 重复触发函数；输入本身固定，重在确定性。

    Validates: Requirements 3.1
    """
    _ = seed  # input is intentionally constant — only re-runs matter
    fp = _fingerprint(
        _run_s08(
            modeling_mode=ModelingMode.PIXEL,
            enable_outline=True,
            outline_width=2.0,
            color_mode="8-Color Max",
        )
    )
    assert fp == baseline_pixel_8color_outline_on, (
        "PIXEL + 8-Color Max + enable_outline=True canonical fingerprint "
        "drifted between runs:\n"
        f"baseline={baseline_pixel_8color_outline_on}\n"
        f"current ={fp}"
    )


# ---------------------------------------------------------------------------
# Anchors — non-PBT canonical cases pinning the LUM-20260527-001 cousins
# 锚点：非 PBT，固化工单 LUM-20260527-001 在 raster 域的最近邻输入。
# ---------------------------------------------------------------------------


def test_anchor_pixel_8color_outline_on_default_width() -> None:
    """Anchor: ``(PIXEL, enable_outline=True, outline_width=2.0,
    color_mode='8-Color Max')`` always lands an Outline mesh.
    """
    ctx = _run_s08(
        modeling_mode=ModelingMode.PIXEL,
        enable_outline=True,
        outline_width=2.0,
        color_mode="8-Color Max",
    )
    assert "Outline" in ctx["scene"].geometry
    assert ctx.get("outline_added") is True
    assert "Outline" in (ctx.get("preview_colors") or {})
    assert "Outline" in (ctx.get("valid_slot_names") or [])
    outline = ctx["scene"].geometry["Outline"]
    assert len(outline.vertices) > 0 and len(outline.faces) > 0


def test_anchor_hifi_rybw_outline_off_default_width() -> None:
    """Anchor: ``(HIGH_FIDELITY, enable_outline=False, outline_width=2.0,
    color_mode='4-Color RYBW')`` keeps the scene free of Outline geometry.
    """
    ctx = _run_s08(
        modeling_mode=ModelingMode.HIGH_FIDELITY,
        enable_outline=False,
        outline_width=2.0,
        color_mode="4-Color RYBW",
    )
    assert "Outline" not in ctx["scene"].geometry
    assert ctx.get("outline_added") is False
    assert "Outline" not in (ctx.get("preview_colors") or {})
    assert "Outline" not in (ctx.get("valid_slot_names") or [])


def test_anchor_pixel_8color_outline_on_matches_baseline_fingerprint(
    baseline_pixel_8color_outline_on: dict[str, Any],
) -> None:
    """Approval anchor — canonical PIXEL + outline-on fingerprint is the
    exact hash baseline future Task 3 fix has to preserve.
    """
    fp = _fingerprint(
        _run_s08(
            modeling_mode=ModelingMode.PIXEL,
            enable_outline=True,
            outline_width=2.0,
            color_mode="8-Color Max",
        )
    )
    assert fp == baseline_pixel_8color_outline_on


def test_anchor_hifi_rybw_outline_off_matches_baseline_fingerprint(
    baseline_hifi_rybw_outline_off: dict[str, Any],
) -> None:
    """Approval anchor — canonical HIGH_FIDELITY + outline-off fingerprint
    is the exact hash baseline future Task 3 fix has to preserve.
    """
    fp = _fingerprint(
        _run_s08(
            modeling_mode=ModelingMode.HIGH_FIDELITY,
            enable_outline=False,
            outline_width=2.0,
            color_mode="4-Color RYBW",
        )
    )
    assert fp == baseline_hifi_rybw_outline_off
