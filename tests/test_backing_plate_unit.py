"""
Lumina Studio - Backing Plate 单元测试 (Unit Tests)

验证 _build_color_extruded_mesh 在边界情况下的行为：
- 全 False mask 返回 None
- 单像素 mask 生成有效 mesh
- L 形 mask 生成有效 mesh（含顶点、面、颜色）
- Z 范围正确

Requirements: 1.5
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.pipeline.s11_glb_preview import _build_color_extruded_mesh
from core.pipeline.s11_glb_preview import _build_backing_plate_mesh
from config import PrinterConfig

BACKING_PLATE_RGBA = np.array([245, 245, 245, 255], dtype=np.uint8)


@pytest.mark.parametrize("kernel", ["v1", "v2"])
def test_production_backing_preserves_hole_scale_depth_and_color(
    kernel: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The actual GLB backing path preserves a transparent hole and millimeters.
    实际 GLB 底板路径保留透明孔洞及毫米尺寸。
    """
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union

    monkeypatch.setenv("LUMINA_GLB_KERNEL", kernel)
    mask = np.ones((7, 9), dtype=bool)
    mask[2:5, 3:6] = False
    pixel_scale = 0.4

    mesh = _build_backing_plate_mesh(
        mask, mask.shape[0], pixel_scale, BACKING_PLATE_RGBA,
    )

    assert mesh is not None
    np.testing.assert_allclose(mesh.bounds, [
        [0.0, 0.0, 0.0],
        [9 * pixel_scale, 7 * pixel_scale, PrinterConfig.LAYER_HEIGHT],
    ], atol=1e-9)
    expected_volume = np.count_nonzero(mask) * pixel_scale ** 2 * PrinterConfig.LAYER_HEIGHT
    assert abs(mesh.volume) == pytest.approx(expected_volume, abs=1e-9)
    assert np.all(mesh.visual.face_colors == BACKING_PLATE_RGBA)

    top_triangles = mesh.triangles[
        np.all(np.isclose(mesh.triangles[:, :, 2], PrinterConfig.LAYER_HEIGHT), axis=1)
    ]
    footprint = unary_union([Polygon(triangle[:, :2]) for triangle in top_triangles])
    assert footprint.area == pytest.approx(np.count_nonzero(mask) * pixel_scale ** 2)
    assert not footprint.covers(Point(4.5 * pixel_scale, 3.5 * pixel_scale))
    assert footprint.covers(Point(0.5 * pixel_scale, 0.5 * pixel_scale))


def test_production_backing_empty_mask_returns_none() -> None:
    mesh = _build_backing_plate_mesh(
        np.zeros((3, 3), dtype=bool), 3, 0.4, BACKING_PLATE_RGBA,
    )
    assert mesh is None


# ============================================================================
# Test: 全 False mask 返回 None
# ============================================================================

class TestAllFalseMask:
    """Verify _build_color_extruded_mesh returns None for all-False masks."""

    def test_all_false_3x3(self):
        """A 3x3 all-False mask should return None."""
        mask = np.zeros((3, 3), dtype=bool)
        result = _build_color_extruded_mesh(
            mask=mask, height=3, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert result is None

    def test_all_false_1x1(self):
        """A 1x1 all-False mask should return None."""
        mask = np.array([[False]])
        result = _build_color_extruded_mesh(
            mask=mask, height=1, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert result is None


# ============================================================================
# Test: 非空 mask 生成有效 mesh
# ============================================================================

class TestSinglePixelMask:
    """Verify single-pixel mask produces a valid mesh."""

    def test_single_pixel_returns_mesh(self):
        """A 1x1 True mask should produce a non-None mesh."""
        mask = np.array([[True]])
        mesh = _build_color_extruded_mesh(
            mask=mask, height=1, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None

    def test_single_pixel_has_geometry(self):
        """Mesh should have vertices and faces."""
        mask = np.array([[True]])
        mesh = _build_color_extruded_mesh(
            mask=mask, height=1, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert len(mesh.vertices) > 0
        assert len(mesh.faces) > 0

    def test_single_pixel_z_range(self):
        """Z range should be [0, total_layers]."""
        mask = np.array([[True]])
        mesh = _build_color_extruded_mesh(
            mask=mask, height=1, total_layers=5, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None
        assert mesh.vertices[:, 2].min() == pytest.approx(0.0, abs=1e-9)
        assert mesh.vertices[:, 2].max() == pytest.approx(5.0, abs=1e-9)

    def test_single_pixel_face_color(self):
        """All face colors should match the given RGBA."""
        mask = np.array([[True]])
        mesh = _build_color_extruded_mesh(
            mask=mask, height=1, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None
        colors = mesh.visual.face_colors
        assert np.all(colors == BACKING_PLATE_RGBA)


# ============================================================================
# Test: 多像素 mask
# ============================================================================

class TestMultiPixelMask:
    """Verify multi-pixel masks produce valid meshes."""

    @staticmethod
    def _make_l_mask():
        """L-shaped mask: col=0 rows 0-2, col=1 row=2."""
        mask = np.zeros((3, 2), dtype=bool)
        mask[0, 0] = True
        mask[1, 0] = True
        mask[2, 0] = True
        mask[2, 1] = True
        return mask

    def test_l_shape_returns_mesh(self):
        """L-shaped mask should produce a non-None mesh."""
        mask = self._make_l_mask()
        mesh = _build_color_extruded_mesh(
            mask=mask, height=3, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None

    def test_l_shape_has_geometry(self):
        """Mesh should have vertices and faces."""
        mask = self._make_l_mask()
        mesh = _build_color_extruded_mesh(
            mask=mask, height=3, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert len(mesh.vertices) > 0
        assert len(mesh.faces) > 0

    def test_l_shape_z_range(self):
        """Z range should be [0, total_layers]."""
        mask = self._make_l_mask()
        mesh = _build_color_extruded_mesh(
            mask=mask, height=3, total_layers=3, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None
        assert mesh.vertices[:, 2].min() == pytest.approx(0.0, abs=1e-9)
        assert mesh.vertices[:, 2].max() == pytest.approx(3.0, abs=1e-9)

    def test_l_shape_face_color(self):
        """All face colors should match the given RGBA."""
        mask = self._make_l_mask()
        mesh = _build_color_extruded_mesh(
            mask=mask, height=3, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None
        colors = mesh.visual.face_colors
        assert np.all(colors == BACKING_PLATE_RGBA)

    def test_full_mask_returns_mesh(self):
        """A full 5x5 mask should produce a valid mesh."""
        mask = np.ones((5, 5), dtype=bool)
        mesh = _build_color_extruded_mesh(
            mask=mask, height=5, total_layers=10, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None
        assert len(mesh.faces) > 0
