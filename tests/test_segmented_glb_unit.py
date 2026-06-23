"""
Lumina Studio - 按颜色分组 GLB 预览模型单元测试 (Unit Tests)

验证 generate_segmented_glb() 的具体示例和边界条件。
Requirements: 1.1, 1.5
"""

import logging
import os
import re
import sys

import numpy as np
import pytest
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import PrinterConfig
from core.converter import generate_segmented_glb
from core.pipeline.s11_glb_preview import generate_realtime_glb

# Total Z layers hard-coded inside generate_segmented_glb().
# generate_segmented_glb 内部硬编码的总层数。
_TOTAL_LAYERS_IN_GLB = 25

COLOR_NODE_RE = re.compile(r"^color_([0-9a-f]{6})$")


def _make_cache(
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
    target_width_mm: float = 10.0,
) -> dict:
    """Build a minimal preview cache dict."""
    h, w = matched_rgb.shape[:2]
    return {
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "target_w": w,
        "target_h": h,
        "target_width_mm": target_width_mm,
    }


def _get_color_nodes(scene: trimesh.Scene) -> dict[str, trimesh.Trimesh]:
    """Extract color_<hex> named nodes from a loaded GLB scene."""
    nodes: dict[str, trimesh.Trimesh] = {}
    for node_name in scene.graph.nodes_geometry:
        m = COLOR_NODE_RE.match(node_name)
        if m:
            _, geom_name = scene.graph[node_name]
            nodes[node_name] = scene.geometry[geom_name]
    return nodes


def _get_node_mesh(scene: trimesh.Scene, node_name: str) -> trimesh.Trimesh:
    """Return the mesh attached to a named GLB node."""
    _, geom_name = scene.graph[node_name]
    return scene.geometry[geom_name]


@pytest.fixture
def out_path(tmp_path) -> str:
    """Per-test session-scoped GLB output path.
    逐个测试隔离的 GLB 输出路径.

    ``generate_segmented_glb`` now requires ``output_path`` to eliminate
    the cross-session collision documented in
    ``progress/glb-internals-audit-2026-04-30.md``. Each test gets its own
    pytest ``tmp_path`` so per-test outputs never overlap.
    """
    return str(tmp_path / "segmented_test.glb")


# ============================================================================
# Test 1: None cache returns None
# ============================================================================

class TestEmptyAndNoneInputs:
    """Tests for empty/None inputs returning None."""

    def test_none_cache_returns_none(self, out_path: str) -> None:
        """None cache should return None immediately."""
        result = generate_segmented_glb(None, output_path=out_path)
        assert result is None

    def test_empty_image_all_transparent_returns_none(self, out_path: str) -> None:
        """All mask_solid=False (no solid pixels) should return None."""
        h, w = 8, 8
        matched_rgb = np.zeros((h, w, 3), dtype=np.uint8)
        mask_solid = np.zeros((h, w), dtype=bool)  # all transparent
        cache = _make_cache(matched_rgb, mask_solid)

        result = generate_segmented_glb(cache, output_path=out_path)
        assert result is None

    def test_missing_matched_rgb_returns_none(self, out_path: str) -> None:
        """Cache without matched_rgb key should return None."""
        cache = {
            "mask_solid": np.ones((4, 4), dtype=bool),
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 4.0,
        }
        result = generate_segmented_glb(cache, output_path=out_path)
        assert result is None

    def test_missing_mask_solid_returns_none(self, out_path: str) -> None:
        """Cache without mask_solid key should return None."""
        cache = {
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 4.0,
        }
        result = generate_segmented_glb(cache, output_path=out_path)
        assert result is None

    def test_export_failure_log_has_actionable_fields(
        self,
        out_path: str,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GLB export exceptions should leave a searchable structured log."""

        def _raise_export_error(self, *args, **kwargs) -> None:
            raise RuntimeError("glb writer unavailable")

        logger = logging.getLogger("lumina.core.pipeline.s11_glb_preview")
        logger.addHandler(caplog.handler)
        caplog.set_level(logging.ERROR, logger="lumina.core.pipeline.s11_glb_preview")
        monkeypatch.setattr(trimesh.Scene, "export", _raise_export_error)

        try:
            cache = _make_cache(
                matched_rgb=np.full((4, 4, 3), [255, 0, 0], dtype=np.uint8),
                mask_solid=np.ones((4, 4), dtype=bool),
                target_width_mm=10.0,
            )
            result = generate_segmented_glb(cache, output_path=out_path)
        finally:
            logger.removeHandler(caplog.handler)

        assert result is None

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "segmented_glb_export_failed"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.ERROR
        assert record.error_type == "RuntimeError"
        assert record.error_message == "glb writer unavailable"
        assert record.output_path == out_path
        assert record.width == 4
        assert record.height == 4
        assert record.geometry_count >= 1

    def test_export_failure_log_tolerates_invalid_max_meshes(
        self,
        out_path: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Logging should not mask the original GLB failure."""
        logger = logging.getLogger("lumina.core.pipeline.s11_glb_preview")
        logger.addHandler(caplog.handler)
        caplog.set_level(logging.ERROR, logger="lumina.core.pipeline.s11_glb_preview")

        try:
            cache = _make_cache(
                matched_rgb=np.full((4, 4, 3), [255, 0, 0], dtype=np.uint8),
                mask_solid=np.ones((4, 4), dtype=bool),
                target_width_mm=10.0,
            )
            result = generate_segmented_glb(cache, output_path=out_path, max_meshes=None)
        finally:
            logger.removeHandler(caplog.handler)

        assert result is None

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "segmented_glb_export_failed"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.error_type == "TypeError"
        assert record.max_meshes is None


# ============================================================================
# Test 2: Single color image generates exactly 1 Mesh
# ============================================================================

class TestSingleColorImage:
    """Tests for single-color images producing exactly 1 Mesh."""

    def test_single_color_generates_one_mesh(self, out_path: str) -> None:
        """A uniform red image should produce exactly 1 Mesh named color_ff0000."""
        h, w = 6, 6
        red = np.array([255, 0, 0], dtype=np.uint8)
        matched_rgb = np.full((h, w, 3), red, dtype=np.uint8)
        mask_solid = np.ones((h, w), dtype=bool)
        cache = _make_cache(matched_rgb, mask_solid)

        glb_path = generate_segmented_glb(cache, output_path=out_path)

        assert glb_path is not None
        assert os.path.isfile(glb_path)

        scene = trimesh.load(glb_path)
        color_nodes = _get_color_nodes(scene)

        assert len(color_nodes) == 1
        assert "color_ff0000" in color_nodes

        # Verify face color matches
        mesh = color_nodes["color_ff0000"]
        face_rgb = np.unique(mesh.visual.face_colors[:, :3], axis=0)
        assert len(face_rgb) == 1
        assert tuple(face_rgb[0]) == (255, 0, 0)

        # Verify Pivot Point constraint: min_z = 0
        assert np.isclose(mesh.vertices[:, 2].min(), 0.0, atol=1e-6)

    def test_single_color_with_partial_mask(self, out_path: str) -> None:
        """Single color with some transparent pixels still produces 1 Mesh."""
        h, w = 8, 8
        blue = np.array([0, 0, 255], dtype=np.uint8)
        matched_rgb = np.full((h, w, 3), blue, dtype=np.uint8)
        mask_solid = np.ones((h, w), dtype=bool)
        # Mark corners as transparent
        mask_solid[0, 0] = False
        mask_solid[0, -1] = False
        mask_solid[-1, 0] = False
        mask_solid[-1, -1] = False
        cache = _make_cache(matched_rgb, mask_solid)

        glb_path = generate_segmented_glb(cache, output_path=out_path)

        assert glb_path is not None
        scene = trimesh.load(glb_path)
        color_nodes = _get_color_nodes(scene)

        assert len(color_nodes) == 1
        assert "color_0000ff" in color_nodes

    def test_vector_backing_mask_drives_visible_backing_plate(self, out_path: str) -> None:
        """Vector preview GLB must use the cache backing footprint, not just shape pixels."""
        h, w = 24, 24
        red = np.array([255, 0, 0], dtype=np.uint8)
        matched_rgb = np.full((h, w, 3), red, dtype=np.uint8)
        mask_solid = np.zeros((h, w), dtype=bool)
        mask_solid[4:20, 4:20] = True
        backing_mask = np.zeros((h, w), dtype=bool)
        backing_mask[2:22, 2:22] = True

        cache = _make_cache(matched_rgb, mask_solid, target_width_mm=24.0)
        cache["backing_mask"] = backing_mask

        glb_path = generate_segmented_glb(cache, output_path=out_path)

        assert glb_path is not None
        scene = trimesh.load(glb_path)
        color_mesh = _get_color_nodes(scene)["color_ff0000"]
        backing_mesh = _get_node_mesh(scene, "backing_plate")

        assert backing_mesh.bounds[0][0] < color_mesh.bounds[0][0]
        assert backing_mesh.bounds[0][1] < color_mesh.bounds[0][1]
        assert backing_mesh.bounds[1][0] > color_mesh.bounds[1][0]
        assert backing_mesh.bounds[1][1] > color_mesh.bounds[1][1]

    def test_vector_outline_geometry_exports_native_outline_node(self, out_path: str) -> None:
        """Vector preview GLB must include cached outline geometry as an Outline node."""
        h, w = 24, 24
        red = np.array([255, 0, 0], dtype=np.uint8)
        matched_rgb = np.full((h, w, 3), red, dtype=np.uint8)
        mask_solid = np.zeros((h, w), dtype=bool)
        mask_solid[6:18, 6:18] = True

        cache = _make_cache(matched_rgb, mask_solid, target_width_mm=24.0)
        outline_mesh = trimesh.creation.box(
            extents=(24.0, 24.0, PrinterConfig.LAYER_HEIGHT * 2)
        )
        outline_mesh.apply_translation([12.0, 12.0, PrinterConfig.LAYER_HEIGHT])
        outline_mesh.visual.face_colors = np.tile(
            np.array([245, 245, 245, 255], dtype=np.uint8),
            (len(outline_mesh.faces), 1),
        )
        outline_mesh.metadata["name"] = "Outline"
        cache["outline_geometry"] = outline_mesh

        glb_path = generate_segmented_glb(cache, output_path=out_path)

        assert glb_path is not None
        scene = trimesh.load(glb_path)
        color_mesh = _get_color_nodes(scene)["color_ff0000"]
        outline_node = _get_node_mesh(scene, "Outline")

        assert outline_node.vertices.shape[0] > 0
        assert outline_node.faces.shape[0] > 0
        assert outline_node.bounds[0][0] < color_mesh.bounds[0][0]
        assert outline_node.bounds[0][1] < color_mesh.bounds[0][1]
        assert outline_node.bounds[1][0] > color_mesh.bounds[1][0]
        assert outline_node.bounds[1][1] > color_mesh.bounds[1][1]
        face_rgb = np.unique(outline_node.visual.face_colors[:, :3], axis=0)
        assert face_rgb.tolist() == [[245, 245, 245]]

    def test_vector_preview_glb_exports_canvas_bounds_anchor_for_puzzle_overlay(
        self,
        out_path: str,
    ) -> None:
        """Puzzle overlay alignment needs full preview-canvas bounds, not cropped art bounds."""
        h, w = 60, 60
        red = np.array([255, 0, 0], dtype=np.uint8)
        matched_rgb = np.full((h, w, 3), red, dtype=np.uint8)
        mask_solid = np.zeros((h, w), dtype=bool)
        mask_solid[5:55, 5:55] = True
        cache = _make_cache(matched_rgb, mask_solid, target_width_mm=60.0)
        cache["backing_mask"] = mask_solid.copy()

        glb_path = generate_segmented_glb(cache, output_path=out_path)

        assert glb_path is not None
        scene = trimesh.load(glb_path)
        canvas_mesh = _get_node_mesh(scene, "preview_canvas_bounds")
        assert canvas_mesh.bounds[0][0] == pytest.approx(0.0)
        assert canvas_mesh.bounds[0][1] == pytest.approx(0.0)
        assert canvas_mesh.bounds[1][0] == pytest.approx(60.0)
        assert canvas_mesh.bounds[1][1] == pytest.approx(60.0)

    def test_missing_target_width_uses_nozzle_width_fallback(
        self,
        out_path: str,
    ) -> None:
        """Async replace GLB should survive legacy caches without a target width."""
        h, w = 8, 8
        green = np.array([0, 255, 0], dtype=np.uint8)
        matched_rgb = np.full((h, w, 3), green, dtype=np.uint8)
        mask_solid = np.ones((h, w), dtype=bool)
        cache = _make_cache(matched_rgb, mask_solid)
        cache.pop("target_width_mm")

        glb_path = generate_segmented_glb(cache, output_path=out_path)

        assert glb_path is not None
        scene = trimesh.load(glb_path)
        canvas_mesh = _get_node_mesh(scene, "preview_canvas_bounds")
        assert canvas_mesh.bounds[1][0] == pytest.approx(
            w * PrinterConfig.NOZZLE_WIDTH
        )

    def test_none_target_width_uses_nozzle_width_fallback_for_realtime_glb(
        self,
        tmp_path,
    ) -> None:
        """Lightweight GLB should not fail when cache metadata has null width."""
        h, w = 8, 8
        blue = np.array([0, 0, 255], dtype=np.uint8)
        matched_rgb = np.full((h, w, 3), blue, dtype=np.uint8)
        mask_solid = np.ones((h, w), dtype=bool)
        cache = _make_cache(matched_rgb, mask_solid)
        cache["target_width_mm"] = None

        glb_path = generate_realtime_glb(
            cache,
            output_path=str(tmp_path / "realtime.glb"),
        )

        assert glb_path is not None


# ============================================================================
# Test 3: Exactly 64 unique colors does NOT trigger merging
# ============================================================================

class TestExactly64Colors:
    """Tests for exactly 64 colors not triggering merge logic."""

    def test_64_colors_no_merge(self, out_path: str) -> None:
        """Exactly 64 unique colors with default max_meshes=64 should produce 64 Meshes."""
        # Generate 64 distinct colors spread across the RGB cube
        colors = []
        for r_idx in range(4):
            for g_idx in range(4):
                for b_idx in range(4):
                    colors.append([r_idx * 85, g_idx * 85, b_idx * 85])
        assert len(colors) == 64

        # Build an image where each row of pixels uses one color
        # 64 colors, each gets at least 1 pixel in a 64x4 image
        h, w = 64, 4
        matched_rgb = np.zeros((h, w, 3), dtype=np.uint8)
        for i, c in enumerate(colors):
            matched_rgb[i, :, :] = c

        mask_solid = np.ones((h, w), dtype=bool)
        cache = _make_cache(matched_rgb, mask_solid)

        glb_path = generate_segmented_glb(cache, output_path=out_path, max_meshes=64)

        assert glb_path is not None
        assert os.path.isfile(glb_path)

        scene = trimesh.load(glb_path)
        color_nodes = _get_color_nodes(scene)

        # Exactly 64 meshes, no merging
        assert len(color_nodes) == 64

        # Every mesh name should be valid color_<hex>
        for name in color_nodes:
            assert COLOR_NODE_RE.match(name), f"Invalid mesh name: {name}"

        # Every mesh should satisfy Pivot Point constraint
        for name, mesh in color_nodes.items():
            min_z = mesh.vertices[:, 2].min()
            assert np.isclose(min_z, 0.0, atol=1e-6), (
                f"Mesh {name} min_z={min_z}, expected 0.0"
            )


# ============================================================================
# Test 3b: cache['glb_max_meshes'] override survives the merge step
# Region re-quantize introduces many low-frequency colours that would be
# wiped out by the default 64-mesh cap; the override must keep them.
# 二次量化会引入大量低频新色，默认 64 上限会把它们合并掉。这里验证 cache
# 中写入的覆盖值能在合并阶段生效，让全部新色保留为独立 mesh。
# ============================================================================


class TestCacheMaxMeshesOverride:
    """Tests for the per-cache ``glb_max_meshes`` override."""

    @staticmethod
    def _build_72_color_image() -> tuple[np.ndarray, np.ndarray]:
        """Synthesise a 72-unique-colour image (above the default 64 cap)."""
        # 72 distinct colours laid out as 1 pixel per row in a 72x2 image.
        # Two-pixel width keeps the contour-extrusion path happy without
        # inflating mesh size; one row per colour gives every colour an
        # equal pixel count so frequency-based merging is well-defined.
        # 72 行各一种颜色，宽度 2 像素以保证轮廓挤出路径成立。
        colors: list[list[int]] = []
        for idx in range(72):
            r = (idx * 11) & 0xFF
            g = (idx * 31) & 0xFF
            b = (idx * 71) & 0xFF
            # Avoid all-zero black which can collide with the background.
            colors.append([max(r, 1), max(g, 1), max(b, 1)])
        h, w = 72, 2
        matched_rgb = np.zeros((h, w, 3), dtype=np.uint8)
        for i, c in enumerate(colors):
            matched_rgb[i, :, :] = c
        mask_solid = np.ones((h, w), dtype=bool)
        return matched_rgb, mask_solid

    def test_override_above_default_keeps_all_unique_colors(self, out_path: str) -> None:
        """``glb_max_meshes`` larger than default must survive into the GLB.
        覆盖值高于默认时，所有唯一色都要保留为独立 mesh。
        """
        matched_rgb, mask_solid = self._build_72_color_image()
        cache = _make_cache(matched_rgb, mask_solid)
        # 72 unique colours, override the cap to 128 so none gets merged.
        cache["glb_max_meshes"] = 128

        glb_path = generate_segmented_glb(cache, output_path=out_path)

        assert glb_path is not None
        scene = trimesh.load(glb_path)
        color_nodes = _get_color_nodes(scene)

        # All 72 unique colours must survive — the override prevented merging.
        assert len(color_nodes) == 72

    def test_override_below_default_is_ignored(self, out_path: str) -> None:
        """Override < default must NOT lower the cap (safety floor).
        覆盖值小于默认时不能反向降低上限，避免误伤普通预览。
        """
        matched_rgb, mask_solid = self._build_72_color_image()
        cache = _make_cache(matched_rgb, mask_solid)
        # Pretend a stale request set the override to 16; the default
        # max_meshes=64 must still apply.
        cache["glb_max_meshes"] = 16

        glb_path = generate_segmented_glb(cache, output_path=out_path, max_meshes=64)

        assert glb_path is not None
        scene = trimesh.load(glb_path)
        color_nodes = _get_color_nodes(scene)

        # Should merge to 64, not down to 16, since override < default.
        assert len(color_nodes) == 64

    def test_no_override_keeps_explicit_max_meshes(self, out_path: str) -> None:
        """Without override an explicit max_meshes still rules.
        无覆盖时仍按显式传入的 max_meshes 合并。
        """
        matched_rgb, mask_solid = self._build_72_color_image()
        cache = _make_cache(matched_rgb, mask_solid)
        # No glb_max_meshes key in cache.

        glb_path = generate_segmented_glb(cache, output_path=out_path, max_meshes=64)

        assert glb_path is not None
        scene = trimesh.load(glb_path)
        color_nodes = _get_color_nodes(scene)

        # 72 colours -> merged down to 64.
        assert len(color_nodes) == 64

    def test_function_default_keeps_72_unique_colors_after_default_bump(self, out_path: str) -> None:
        """The production default should now keep more than 64 colours."""
        matched_rgb, mask_solid = self._build_72_color_image()
        cache = _make_cache(matched_rgb, mask_solid)

        glb_path = generate_segmented_glb(cache, output_path=out_path)

        assert glb_path is not None
        scene = trimesh.load(glb_path)
        color_nodes = _get_color_nodes(scene)

        assert len(color_nodes) == 72


# ============================================================================
# Test 4: Contour-extrusion size + coverage regression
# Guards the S11 refactor that replaced per-pixel voxel boxes with
# contour-extruded prisms. On a 256x256 / 6-colour representative image the
# pre-refactor baseline is ~15 MB / ~480k vertices; the new path targets
# single-digit MB and sub-100k vertices without any loss of XY footprint or
# Z volume coverage.
# 第 4 组：轮廓挤出的体积大小与覆盖率回归。针对把 S11 逐像素体素盒改成
# 轮廓挤出的重构，在 256x256 / 6 色代表性图像上，重构前基线约 15 MB /
# ~48 万顶点；新路径目标是个位数 MB 与 10 万顶点以下，同时在 XY 平面
# 与 Z 体积覆盖上完全保留原有精度。
# ============================================================================

class TestContourExtrusionSizeRegression:
    """Lock in the dramatic size / vertex reduction from contour extrusion."""

    @staticmethod
    def _representative_image(
        h: int = 256,
        w: int = 256,
        seed: int = 42,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Synthesize a 6-colour layered-print-style image deterministically.

        Light-grey background plus 5 Gaussian blobs of distinct hues, with a
        small transparent border — representative of typical user workloads.
        """
        rng = np.random.RandomState(seed)
        matched_rgb = np.full((h, w, 3), (245, 245, 245), dtype=np.uint8)
        mask_solid = np.ones((h, w), dtype=bool)

        yy, xx = np.mgrid[:h, :w]
        palette = [
            (0x0A, 0x29, 0x89),
            (0xC1, 0x2E, 0x1F),
            (0x00, 0xAE, 0x42),
            (0xF4, 0xEE, 0x2A),
            (0x00, 0x00, 0x00),
        ]
        for color in palette:
            cy = rng.randint(40, h - 40)
            cx = rng.randint(40, w - 40)
            sigma = rng.randint(30, 70)
            blob = (xx - cx) ** 2 + (yy - cy) ** 2 < sigma**2
            matched_rgb[blob] = color

        border = 6
        mask_solid[:border, :] = False
        mask_solid[-border:, :] = False
        mask_solid[:, :border] = False
        mask_solid[:, -border:] = False
        return matched_rgb, mask_solid

    def test_glb_size_under_2mb(self, out_path: str) -> None:
        """Representative 256x256 / 6-colour image must produce a GLB < 2 MB.

        Pre-refactor voxel baseline for this exact image is ~15 MB; the
        contour-extrusion path empirically lands around 0.1 MB, so 2 MB
        gives ample margin for future mesh-format changes while still
        flagging any accidental regression back to voxel-like sizes.
        """
        matched_rgb, mask_solid = self._representative_image()
        cache = _make_cache(matched_rgb, mask_solid, target_width_mm=100.0)

        glb_path = generate_segmented_glb(cache, output_path=out_path)

        assert glb_path is not None, "generate_segmented_glb returned None"
        assert os.path.isfile(glb_path), f"GLB file not found: {glb_path}"

        size_bytes = os.path.getsize(glb_path)
        size_mb = size_bytes / (1024 * 1024)
        assert size_mb < 2.0, (
            f"GLB size {size_mb:.3f} MB exceeds 2 MB threshold for the "
            f"representative 256x256 6-colour image (pre-refactor voxel "
            f"baseline was ~15 MB)."
        )

    def test_vertex_count_far_below_voxel_baseline(self, out_path: str) -> None:
        """Total vertex count must be well under the voxel-box equivalent.

        Voxel baseline = solid_pixel_count * 8 (each pixel = 8 vertices).
        Contour extrusion should use at most 5% of that, i.e. >= 20x
        fewer vertices on typical layered-print imagery.
        """
        matched_rgb, mask_solid = self._representative_image()
        cache = _make_cache(matched_rgb, mask_solid, target_width_mm=100.0)

        glb_path = generate_segmented_glb(cache, output_path=out_path)

        assert glb_path is not None
        scene = trimesh.load(glb_path)

        total_verts = sum(g.vertices.shape[0] for g in scene.geometry.values())
        solid_pixel_count = int(np.count_nonzero(mask_solid))
        voxel_baseline = solid_pixel_count * 8

        ratio = total_verts / max(voxel_baseline, 1)
        assert ratio < 0.05, (
            f"Vertex count {total_verts:,} is {ratio:.2%} of the voxel "
            f"baseline ({voxel_baseline:,}); expected < 5% (i.e. at least "
            f"20x reduction) from the contour-extrusion refactor."
        )

    def test_volume_coverage_preserved(self, out_path: str) -> None:
        """Sum of per-colour mesh volume equals the expected pixel volume.

        Representation-agnostic invariant proving the refactor did not lose
        any solid pixel: every solid pixel contributes 1x1xtotal_layers
        voxel units of volume (mapped to mm via pixel_scale^2 * LAYER_HEIGHT).
        """
        matched_rgb, mask_solid = self._representative_image()
        cache = _make_cache(matched_rgb, mask_solid, target_width_mm=100.0)

        glb_path = generate_segmented_glb(cache, output_path=out_path)

        assert glb_path is not None
        scene = trimesh.load(glb_path)
        color_nodes = _get_color_nodes(scene)

        solid_pixel_count = int(np.count_nonzero(mask_solid))
        pixel_scale = float(cache["target_width_mm"]) / matched_rgb.shape[1]
        expected_volume = (
            solid_pixel_count
            * (pixel_scale ** 2)
            * float(_TOTAL_LAYERS_IN_GLB)
            * float(PrinterConfig.LAYER_HEIGHT)
        )

        actual_volume = 0.0
        for mesh in color_nodes.values():
            try:
                v = float(mesh.volume)
            except (ValueError, TypeError, RuntimeError, AttributeError):
                v = 0.0
            if np.isfinite(v):
                actual_volume += abs(v)

        tolerance = max(1e-6, 1e-3 * expected_volume)
        assert abs(actual_volume - expected_volume) <= tolerance, (
            f"Volume coverage mismatch: expected {expected_volume:.6f} mm^3 "
            f"(pixels={solid_pixel_count}, pixel_scale={pixel_scale:.6f} mm), "
            f"got {actual_volume:.6f} mm^3"
        )
