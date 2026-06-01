"""Regression: SVG-native vector preview must not leave 1px seams inside shapes.
回归测试：SVG 原生矢量预览不得在色块内部留下 1px 破洞（缝）。

Bug background (用户可见现象):
    用耗材档案 + 矢量模式转换 ``4.绫波丽...svg`` 后，头发右上出现一个肉眼可见
    的小破洞。在"颜色调整"里点击该破洞，后端 ``/api/convert/region-detect``
    返回 ``400 "Clicked on background area."``——说明该像素在预览缓存的
    ``mask_solid`` 里是 ``False``（被当成背景），而原图 resvg 在该处是实心头发。

Root cause (根因):
    ``VectorProcessor.build_preview_cache`` 的 ``_polygon_mask`` 用
    ``cv2.fillPoly`` 栅格化每个 shape 时，先把浮点顶点 ``astype(np.int32)``
    截断取整再填充。整数截断让多顶点折线边界（尤其带 interior 洞的复杂头发
    多边形）在某些**绝对像素**位置漏填，于是几何明明覆盖该像素中心、
    ``mask_solid`` 却是 ``False``，形成 1px 竖缝。

This test loads a real polygon (shape #165 from the reported SVG, captured at
its true absolute preview-grid position) and asserts the invariant the fix
must guarantee:

    对于 silhouette 内部、像素中心被几何严格覆盖的像素，``mask_solid``
    必须为 ``True``（不得漏填）。

It also locks the **boundary** safety property so a future fix cannot "patch"
the seam by over-filling: pixels whose centers fall **outside** the geometry
must stay ``mask_solid == False`` (the transparent SVG background must remain
air, per the Converter Regression Checklist's alpha-driven silhouette rule).
同时锁定边界安全：几何之外的像素必须保持 ``mask_solid == False``，避免
修复时把透明背景误填实。

Fixture: ``tests/fixtures/svg_alignment/hair_seam_polygon.json``
    - ``wkt``: the real shape polygon (absolute preview-vector coords).
    - ``scale_factor`` / ``pixels_per_mm`` / ``bbox``: reproduce the exact
      1130x2009 preview grid the backend used for the bug report.
    - ``seam_pixels``: the 208 geometry-covered pixels the *current* code
      drops (recorded for diagnostics; the test recomputes them live).
    - ``click_pixel``: ``[913, 376]`` — the exact pixel the user clicked.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types

import numpy as np
import pytest
from shapely import wkt as shapely_wkt
from shapely.geometry import Point
from shapely.prepared import prep

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Load core.vector_engine directly to skip the heavy core.__init__ chain
# (matches the bootstrap used by the other vector unit tests in this suite).
# 直接按文件加载 vector_engine，避免 core 包的重依赖 import 链。
_spec = importlib.util.spec_from_file_location(
    "core.vector_engine", os.path.join(_ROOT, "core", "vector_engine.py")
)
_ve = importlib.util.module_from_spec(_spec)
if "core" not in sys.modules:
    _pkg = types.ModuleType("core")
    _pkg.__path__ = [os.path.join(_ROOT, "core")]
    sys.modules["core"] = _pkg
sys.modules["core.vector_engine"] = _ve
_spec.loader.exec_module(_ve)

VectorProcessor = _ve.VectorProcessor
VectorAnalysis = _ve.VectorAnalysis

_FIXTURE_PATH = os.path.join(
    _ROOT, "tests", "fixtures", "svg_alignment", "hair_seam_polygon.json"
)


def _load_fixture() -> dict:
    with open(_FIXTURE_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _build_analysis(fixture: dict) -> tuple[VectorAnalysis, object, float]:
    """Build a single-shape VectorAnalysis mirroring the real preview grid.

    返回 ``(analysis, geom, coord_scale)``，其中 ``geom`` 是该色块的 shapely
    几何，``coord_scale = scale_factor * pixels_per_mm`` 用于 像素↔矢量坐标
    互转。
    """
    geom = shapely_wkt.loads(fixture["wkt"])
    sf = float(fixture["scale_factor"])
    ppm = float(fixture["pixels_per_mm"])
    bbox = tuple(fixture["bbox"])
    coord_scale = sf * ppm

    analysis = VectorAnalysis(
        shape_data=[],
        clipped_shapes=[{"geometry": geom}],
        matched_shapes=[
            {
                "geometry": geom,
                "recipe": [1, 1, 1],
                "color": (50, 80, 110),
                "matched_rgb": (50, 80, 110),
            }
        ],
        silhouette=geom,
        scale_factor=sf,
        bbox=bbox,
        color_conf={"slots": ["W", "C", "M", "Y"], "preview": {}},
        slot_names=["W", "C", "M", "Y"],
        num_channels=4,
        num_layers=3,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [0, 183, 235, 255],
            2: [230, 0, 126, 255],
            3: [255, 212, 0, 255],
        },
    )
    return analysis, geom, coord_scale


def _covered_missing_pixels(mask_solid, geom, coord_scale) -> list[tuple[int, int]]:
    """Return pixels whose centers are strictly inside ``geom`` but whose
    ``mask_solid`` is ``False`` (geometry-covered yet unfilled).

    返回"几何严格覆盖像素中心、但 ``mask_solid`` 漏填"的像素列表。这是
    破洞/缝的直接度量：未修复时该集合很大（成片缝），修复后应大幅下降到
    仅剩亚像素边界抖动。仅扫描几何 bbox 范围以保持快速。
    """
    h_px, w_px = mask_solid.shape
    prepared = prep(geom)
    minx, miny, maxx, maxy = geom.bounds
    x0 = max(0, int(minx * coord_scale))
    x1 = min(w_px, int(maxx * coord_scale) + 1)
    y0 = max(0, int(miny * coord_scale))
    y1 = min(h_px, int(maxy * coord_scale) + 1)

    missing: list[tuple[int, int]] = []
    for y in range(y0, y1):
        row = mask_solid[y]
        for x in range(x0, x1):
            if row[x]:
                continue
            center = Point((x + 0.5) / coord_scale, (y + 0.5) / coord_scale)
            if prepared.contains(center):
                missing.append((x, y))
    return missing


class TestVectorPreviewSeam:
    """Lock the seam-free + boundary-safe invariants of build_preview_cache."""

    def test_clicked_seam_pixel_is_solid(self):
        """The exact pixel the user clicked must be marked solid.

        用户点击的破洞像素 (913, 376) 在原图被该头发色块严格覆盖；
        ``mask_solid`` 必须为 True，否则 region-detect 会把它当背景拒绝。
        当前（未修复）代码该断言失败，修复后通过。
        """
        fixture = _load_fixture()
        analysis, geom, coord_scale = _build_analysis(fixture)
        cx, cy = fixture["click_pixel"]

        # Sanity: the geometry really does cover the clicked pixel center,
        # so a False mask there is unambiguously a rasterisation seam.
        # 前置校验：几何确实覆盖该像素中心，排除"本就是背景"的可能。
        center = Point((cx + 0.5) / coord_scale, (cy + 0.5) / coord_scale)
        assert geom.contains(center), (
            "Fixture invalid: geometry does not cover the clicked pixel center"
        )

        cache = VectorProcessor.build_preview_cache(
            analysis, pixels_per_mm=fixture["pixels_per_mm"], supersample_preview=2
        )
        mask_solid = cache["mask_solid"]

        assert bool(mask_solid[cy, cx]), (
            f"Clicked pixel ({cx}, {cy}) is geometry-covered but mask_solid is "
            "False — the 1px seam bug is present (region-detect would reject it "
            "as background)."
        )

    def test_no_interior_seam_pixels(self):
        """Geometry-covered-but-unfilled pixels must collapse to boundary jitter.

        几何覆盖却漏填的像素必须从"成片缝"塌缩到仅剩亚像素边界抖动。
        未修复基线 = 208（用户可见破洞）；修复后应远低于该值（仅边界抖动）。
        用一个保守阈值(<=80)守住回归：任何把缝重新放大的改动都会触发失败，
        同时容忍有限分辨率栅格化不可避免的边界抖动。
        """
        fixture = _load_fixture()
        analysis, geom, coord_scale = _build_analysis(fixture)

        cache = VectorProcessor.build_preview_cache(
            analysis, pixels_per_mm=fixture["pixels_per_mm"], supersample_preview=2
        )
        mask_solid = cache["mask_solid"]

        missing = _covered_missing_pixels(mask_solid, geom, coord_scale)
        # Broken baseline was 208; the sub-pixel fix drops this to boundary
        # jitter only. 80 leaves margin for platform fillPoly differences
        # while still failing hard if the seam returns.
        assert len(missing) <= 80, (
            f"{len(missing)} geometry-covered pixels left unfilled in mask_solid "
            f"(broken baseline was 208). The 1px seam appears to have returned. "
            f"First few: {missing[:10]}"
        )

    def test_preview_rgba_has_no_semitransparent_seam(self):
        """The displayed preview image must be opaque wherever it is solid.

        用户视觉看到的是 ``preview_rgba``（带 alpha 的显示图），不是
        ``mask_solid``。它由逐 shape 超采样填充 + INTER_AREA 降采样得到，
        相邻 shape 之间的细缝/遮挡洞边界会降采样成 alpha≈128 的半透明缝，
        合成到页面背景后透出底色——这正是用户报告的"透明破洞"。

        断言：凡 ``mask_solid`` 为实体的像素，``preview_rgba`` 的 alpha 必须
        ≈255（不得半透明）。未修复时头发区有上百个 alpha<240 的透底像素，
        修复后应为 0。外缘抗锯齿不受影响（那里 ``mask_solid`` 为 False）。
        """
        fixture = _load_fixture()
        analysis, _geom, _coord_scale = _build_analysis(fixture)

        cache = VectorProcessor.build_preview_cache(
            analysis, pixels_per_mm=fixture["pixels_per_mm"], supersample_preview=2
        )
        mask_solid = cache["mask_solid"]
        preview_rgba = cache["preview_rgba"]
        assert preview_rgba.shape[2] == 4, "preview_rgba must carry an alpha channel"

        alpha = preview_rgba[:, :, 3]
        # Solid pixels that the display image renders see-through (alpha<240)
        # would composite the page background through solid artwork.
        leak = mask_solid & (alpha < 240)
        leak_count = int(np.count_nonzero(leak))
        assert leak_count == 0, (
            f"{leak_count} solid pixels are semi-transparent in preview_rgba "
            "(visible as transparent holes when composited on the page). "
            "The displayed-image seam has returned."
        )

        # The exact pixel the user clicked must render fully opaque.
        cx, cy = fixture["click_pixel"]
        assert int(alpha[cy, cx]) == 255, (
            f"Clicked pixel ({cx}, {cy}) has alpha {int(alpha[cy, cx])} in "
            "preview_rgba — it would still show as a transparent hole."
        )

    def test_background_outside_geometry_stays_air(self):
        """Boundary safety: a fix must not over-fill the transparent exterior.

        边界安全：修复缝时不得把几何之外（透明背景）误填成实体。抽样检查
        几何 bbox 之外的像素，断言它们保持 ``mask_solid == False``。
        这条断言现在就应通过，用于防止未来的"过度填充"修复回归。
        """
        fixture = _load_fixture()
        analysis, geom, coord_scale = _build_analysis(fixture)

        cache = VectorProcessor.build_preview_cache(
            analysis, pixels_per_mm=fixture["pixels_per_mm"], supersample_preview=2
        )
        mask_solid = cache["mask_solid"]
        h_px, w_px = mask_solid.shape

        # The shape occupies only part of the 1130x2009 canvas. Pixels far
        # from its bounding box must remain air. Sample a margin band around
        # the geometry bbox plus the canvas corners.
        # 该色块只占画布一部分；远离其 bbox 的像素必须为空。检查 bbox 外扩
        # 一圈的边带 + 画布四角。
        minx, miny, maxx, maxy = geom.bounds
        bx0 = int(minx * coord_scale)
        bx1 = int(maxx * coord_scale)
        by0 = int(miny * coord_scale)
        by1 = int(maxy * coord_scale)

        prepared = prep(geom)
        margin = 12  # px clearly outside the shape silhouette

        sample_points: list[tuple[int, int]] = [
            (0, 0),
            (w_px - 1, 0),
            (0, h_px - 1),
            (w_px - 1, h_px - 1),
            (max(0, bx0 - margin), (by0 + by1) // 2),
            (min(w_px - 1, bx1 + margin), (by0 + by1) // 2),
            ((bx0 + bx1) // 2, max(0, by0 - margin)),
            ((bx0 + bx1) // 2, min(h_px - 1, by1 + margin)),
        ]

        offenders: list[tuple[int, int]] = []
        for x, y in sample_points:
            if not mask_solid[y, x]:
                continue
            center = Point((x + 0.5) / coord_scale, (y + 0.5) / coord_scale)
            # Only an offender if it is also genuinely outside the geometry.
            if not prepared.intersects(center.buffer(1.5 / coord_scale)):
                offenders.append((x, y))

        assert not offenders, (
            f"mask_solid marked exterior/background pixels as solid: {offenders}. "
            "A seam fix must not over-fill the transparent SVG background."
        )
