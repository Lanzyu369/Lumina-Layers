"""
Property-Based Tests for Keychain Loop Enhancement.
钥匙扣挂孔增强功能的 Property-Based 测试。

Uses Hypothesis to verify universal correctness properties
across randomly generated valid parameter spaces.
"""

import numpy as np
import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from core.geometry_utils import create_keychain_loop


# ---------------------------------------------------------------------------
# Smart Hypothesis strategies — constrain to valid input space
# ---------------------------------------------------------------------------

# Width: reasonable range for a keychain loop (2–10 mm)
width_st = st.floats(min_value=2.0, max_value=10.0, allow_nan=False, allow_infinity=False)

# Length must be > circle_radius (half_w) so rect_height > 0.2
# We generate length in [4, 15] which is always > max(half_w)=5
length_st = st.floats(min_value=4.0, max_value=15.0, allow_nan=False, allow_infinity=False)

# Thickness: typical 3D-print layer range
thickness_st = st.floats(min_value=0.4, max_value=3.0, allow_nan=False, allow_infinity=False)

# Attach position: reasonable model coordinate range
attach_st = st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False)

# Rotation angle: full range
angle_st = st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False)


@st.composite
def valid_loop_params(draw):
    """Generate a valid set of keychain loop parameters.
    生成一组有效的钥匙扣挂孔参数。

    Ensures hole_dia < width so the hole fits inside the shape.
    确保 hole_dia < width，使圆孔能放入形状内。
    """
    width = draw(width_st)
    length = draw(length_st)
    # hole_dia must be < width (the implementation clamps to 0.8 * circle_radius)
    hole_dia = draw(st.floats(min_value=0.5, max_value=width * 0.8 - 0.01,
                              allow_nan=False, allow_infinity=False))
    assume(hole_dia > 0)
    thickness = draw(thickness_st)
    attach_x = draw(attach_st)
    attach_y = draw(attach_st)
    angle = draw(angle_st)
    return {
        "width_mm": width,
        "length_mm": length,
        "hole_dia_mm": hole_dia,
        "thickness_mm": thickness,
        "attach_x_mm": attach_x,
        "attach_y_mm": attach_y,
        "angle_deg": angle,
    }


# ===========================================================================
# Property 2: 后端网格旋转正确性
# Feature: keychain-loop-enhancement, Property 2: 后端网格旋转正确性
# Validates: Requirements 1.3, 5.1
# ===========================================================================


class TestProperty2MeshRotationCorrectness:
    """Property 2: Backend mesh rotation correctness.
    属性 2：后端网格旋转正确性。

    For any valid keychain loop parameters and any rotation angle,
    create_keychain_loop should produce a mesh that:
    - At 0° rotation, vertices match the unrotated version
    - At any angle, bounding box center is near (attach_x, attach_y)
    - Mesh is always valid (vertices > 0, faces > 0, watertight)
    """

    @settings(max_examples=100)
    @given(params=valid_loop_params())
    def test_zero_rotation_matches_unrotated(self, params):
        """**Validates: Requirements 1.3, 5.1**

        Rotation of 0° should produce vertices identical to the default
        (no rotation) version.
        旋转 0° 时，网格顶点应与未旋转版本一致。
        """
        # Build mesh with explicit angle_deg=0
        mesh_zero = create_keychain_loop(
            width_mm=params["width_mm"],
            length_mm=params["length_mm"],
            hole_dia_mm=params["hole_dia_mm"],
            thickness_mm=params["thickness_mm"],
            attach_x_mm=params["attach_x_mm"],
            attach_y_mm=params["attach_y_mm"],
            angle_deg=0.0,
        )

        # Build mesh without specifying angle (default=0)
        mesh_default = create_keychain_loop(
            width_mm=params["width_mm"],
            length_mm=params["length_mm"],
            hole_dia_mm=params["hole_dia_mm"],
            thickness_mm=params["thickness_mm"],
            attach_x_mm=params["attach_x_mm"],
            attach_y_mm=params["attach_y_mm"],
        )

        np.testing.assert_allclose(
            mesh_zero.vertices, mesh_default.vertices, atol=1e-10,
            err_msg="0° rotation should produce identical vertices to default",
        )

    @settings(max_examples=100)
    @given(params=valid_loop_params())
    def test_bounding_box_center_near_attach_point(self, params):
        """**Validates: Requirements 1.3, 5.1**

        For any rotation angle, the bounding box center (XY) of the mesh
        should be near the attachment point (attach_x, attach_y).
        旋转任意角度时，网格 bounding box 中心应位于 (attach_x, attach_y) 附近。
        """
        mesh = create_keychain_loop(**params)

        bb_min = mesh.vertices.min(axis=0)
        bb_max = mesh.vertices.max(axis=0)
        bb_center_x = (bb_min[0] + bb_max[0]) / 2.0
        bb_center_y = (bb_min[1] + bb_max[1]) / 2.0

        # The shape is not symmetric around the attach point — the attach
        # point is at the base (y=0 before translation). After rotation the
        # geometric center shifts. We allow a generous tolerance equal to
        # the maximum possible extent of the shape (length + width).
        max_extent = params["length_mm"] + params["width_mm"]

        assert abs(bb_center_x - params["attach_x_mm"]) < max_extent, (
            f"BB center X {bb_center_x} too far from attach_x {params['attach_x_mm']}"
        )
        assert abs(bb_center_y - params["attach_y_mm"]) < max_extent, (
            f"BB center Y {bb_center_y} too far from attach_y {params['attach_y_mm']}"
        )

    @settings(max_examples=100)
    @given(params=valid_loop_params())
    def test_mesh_always_valid(self, params):
        """**Validates: Requirements 1.3, 5.1**

        The generated mesh must always be valid: positive vertex count,
        positive face count, and watertight.
        网格始终有效：顶点数 > 0，面数 > 0，watertight。
        """
        mesh = create_keychain_loop(**params)

        assert len(mesh.vertices) > 0, "Mesh must have vertices"
        assert len(mesh.faces) > 0, "Mesh must have faces"
        assert mesh.is_watertight, (
            f"Mesh must be watertight (vertices={len(mesh.vertices)}, "
            f"faces={len(mesh.faces)}, angle={params['angle_deg']})"
        )

    @pytest.mark.parametrize(
        ("width", "length", "hole_dia", "thickness"),
        [(4.0, 8.0, 2.5, 1.6), (5.0, 4.0, 3.0, 1.0)],
    )
    def test_cap_faces_match_loop_cross_section_area(self, width, length, hole_dia, thickness):
        mesh = create_keychain_loop(
            width_mm=width,
            length_mm=length,
            hole_dia_mm=hole_dia,
            thickness_mm=thickness,
            attach_x_mm=0.0,
            attach_y_mm=0.0,
            angle_deg=0.0,
        )

        radius = width / 2.0
        rect_height = max(0.2, length - radius)
        hole_radius = min(hole_dia / 2.0, radius * 0.8, rect_height * 0.8)
        expected_area = (
            width * rect_height
            + 0.5 * np.pi * radius * radius
            - np.pi * hole_radius * hole_radius
        )

        for z_value in (0.0, thickness):
            cap_area = 0.0
            for face in mesh.faces:
                triangle = mesh.vertices[face]
                if not np.allclose(triangle[:, 2], z_value):
                    continue
                xy = triangle[:, :2]
                cap_area += 0.5 * abs(
                    (xy[1, 0] - xy[0, 0]) * (xy[2, 1] - xy[0, 1])
                    - (xy[2, 0] - xy[0, 0]) * (xy[1, 1] - xy[0, 1])
                )

            assert cap_area == pytest.approx(expected_area, abs=0.1)

    @settings(max_examples=100)
    @given(params=valid_loop_params())
    def test_rotation_preserves_vertex_count(self, params):
        """**Validates: Requirements 1.3, 5.1**

        Rotation should not change the number of vertices or faces —
        it is a rigid transformation.
        旋转不应改变顶点数或面数——它是刚体变换。
        """
        mesh_no_rot = create_keychain_loop(
            width_mm=params["width_mm"],
            length_mm=params["length_mm"],
            hole_dia_mm=params["hole_dia_mm"],
            thickness_mm=params["thickness_mm"],
            attach_x_mm=params["attach_x_mm"],
            attach_y_mm=params["attach_y_mm"],
            angle_deg=0.0,
        )

        mesh_rotated = create_keychain_loop(**params)

        assert len(mesh_rotated.vertices) == len(mesh_no_rot.vertices), (
            "Rotation must preserve vertex count"
        )
        assert len(mesh_rotated.faces) == len(mesh_no_rot.faces), (
            "Rotation must preserve face count"
        )


# ---------------------------------------------------------------------------
# Strategies for Property 4 — _calculate_loop_position offset superposition
# ---------------------------------------------------------------------------

from core.converter import _calculate_loop_position

# Valid position presets
VALID_PRESETS = [
    "top-center", "top-left", "top-right",
    "left-center", "right-center", "bottom-center",
]

preset_st = st.sampled_from(VALID_PRESETS)

# Offsets in [-200, 200] mm range (matching full bed travel)
offset_st = st.floats(min_value=-200.0, max_value=200.0, allow_nan=False, allow_infinity=False)

# Image dimensions: reasonable pixel sizes
dim_st = st.integers(min_value=10, max_value=500)

# Pixel scale: mm per pixel, typical range
pixel_scale_st = st.floats(min_value=0.01, max_value=2.0, allow_nan=False, allow_infinity=False)


@st.composite
def valid_mask_solid(draw, min_w: int = 10, max_w: int = 500,
                     min_h: int = 10, max_h: int = 500):
    """Generate a boolean 2D mask with at least some True values.
    生成至少包含部分 True 值的布尔二维掩码。

    The mask represents solid pixels in the model image.
    掩码表示模型图像中的实体像素。
    """
    h = draw(st.integers(min_value=min_h, max_value=max_h))
    w = draw(st.integers(min_value=min_w, max_value=max_w))
    # Generate a random mask, then ensure at least one True pixel
    mask = draw(st.lists(
        st.lists(st.booleans(), min_size=w, max_size=w),
        min_size=h, max_size=h,
    ).map(lambda rows: np.array(rows, dtype=bool)))
    # If all False, force a block of True pixels near the center
    if not np.any(mask):
        cy, cx = h // 2, w // 2
        mask[max(0, cy - 1):cy + 2, max(0, cx - 1):cx + 2] = True
    return mask


@st.composite
def loop_position_params(draw):
    """Generate a complete set of valid _calculate_loop_position parameters.
    生成一组完整的 _calculate_loop_position 有效参数。
    """
    mask = draw(valid_mask_solid())
    h, w = mask.shape
    preset = draw(preset_st)
    ox = draw(offset_st)
    oy = draw(offset_st)
    ps = draw(pixel_scale_st)
    return {
        "position_preset": preset,
        "offset_x": ox,
        "offset_y": oy,
        "mask_solid": mask,
        "target_w": w,
        "target_h": h,
        "pixel_scale": ps,
    }


# ===========================================================================
# Property 4: 后端位置偏移叠加正确性
# Feature: keychain-loop-enhancement, Property 4: 后端位置偏移叠加正确性
# Validates: Requirements 5.4
# ===========================================================================


class TestProperty4OffsetSuperposition:
    """Property 4: Backend position offset superposition correctness.
    属性 4：后端位置偏移叠加正确性。

    For any valid mask_solid, position_preset, and offsets (offset_x, offset_y),
    _calculate_loop_position with offsets should equal the base position
    (computed with zero offsets) plus (offset_x, offset_y).
    """

    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @given(params=loop_position_params())
    def test_offset_equals_base_plus_delta(self, params):
        """**Validates: Requirements 5.4**

        Position with offset must equal base position (offset=0) plus the offset values.
        带偏移的位置必须等于基准位置（偏移=0）加上偏移值。
        """
        # Compute position with the given offsets
        x_with, y_with = _calculate_loop_position(
            position_preset=params["position_preset"],
            offset_x=params["offset_x"],
            offset_y=params["offset_y"],
            mask_solid=params["mask_solid"],
            target_w=params["target_w"],
            target_h=params["target_h"],
            pixel_scale=params["pixel_scale"],
        )

        # Compute base position with zero offsets
        x_base, y_base = _calculate_loop_position(
            position_preset=params["position_preset"],
            offset_x=0.0,
            offset_y=0.0,
            mask_solid=params["mask_solid"],
            target_w=params["target_w"],
            target_h=params["target_h"],
            pixel_scale=params["pixel_scale"],
        )

        np.testing.assert_allclose(
            x_with, x_base + params["offset_x"], atol=1e-10,
            err_msg=f"X: expected base({x_base}) + offset({params['offset_x']}), got {x_with}",
        )
        np.testing.assert_allclose(
            y_with, y_base + params["offset_y"], atol=1e-10,
            err_msg=f"Y: expected base({y_base}) + offset({params['offset_y']}), got {y_with}",
        )

    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @given(params=loop_position_params())
    def test_zero_offset_matches_base(self, params):
        """**Validates: Requirements 5.4**

        Zero offsets should produce the same result regardless of how they are passed.
        零偏移应产生与基准位置完全相同的结果。
        """
        x1, y1 = _calculate_loop_position(
            position_preset=params["position_preset"],
            offset_x=0.0,
            offset_y=0.0,
            mask_solid=params["mask_solid"],
            target_w=params["target_w"],
            target_h=params["target_h"],
            pixel_scale=params["pixel_scale"],
        )

        # Call again — deterministic, same result expected
        x2, y2 = _calculate_loop_position(
            position_preset=params["position_preset"],
            offset_x=0.0,
            offset_y=0.0,
            mask_solid=params["mask_solid"],
            target_w=params["target_w"],
            target_h=params["target_h"],
            pixel_scale=params["pixel_scale"],
        )

        assert x1 == x2, "Zero-offset calls must be deterministic (X)"
        assert y1 == y2, "Zero-offset calls must be deterministic (Y)"


# ===========================================================================
# Property 7: Pydantic Schema 范围验证
# Feature: keychain-loop-enhancement, Property 7: Pydantic Schema 范围验证
# Validates: Requirements 9.2, 9.3
# ===========================================================================

from pydantic import ValidationError
from api.schemas.converter import ConvertGenerateRequest

# Strategies for out-of-range values
# loop_angle: valid [-180, 180], test outside that
angle_too_high_st = st.floats(min_value=180.01, max_value=1e6, allow_nan=False, allow_infinity=False)
angle_too_low_st = st.floats(min_value=-1e6, max_value=-180.01, allow_nan=False, allow_infinity=False)

# loop_offset_x / loop_offset_y: valid [-200, 200], test outside that
offset_too_high_st = st.floats(min_value=200.01, max_value=1e6, allow_nan=False, allow_infinity=False)
offset_too_low_st = st.floats(min_value=-1e6, max_value=-200.01, allow_nan=False, allow_infinity=False)

# Valid base kwargs for ConvertGenerateRequest (only lut_name is required)
_VALID_BASE = {"lut_name": "test_lut"}


class TestProperty7SchemaValidation:
    """Property 7: Pydantic Schema range validation.
    属性 7：Pydantic Schema 范围验证。

    For any loop_angle outside [-180, 180] or loop_offset_x / loop_offset_y
    outside [-200, 200], ConvertGenerateRequest validation should raise
    ValidationError.
    """

    # --- loop_angle out of range ---

    @settings(max_examples=100)
    @given(val=angle_too_high_st)
    def test_loop_angle_too_high_rejected(self, val: float):
        """**Validates: Requirements 9.2**

        loop_angle > 180 must be rejected.
        loop_angle > 180 应被拒绝。
        """
        with pytest.raises(ValidationError):
            ConvertGenerateRequest(**{**_VALID_BASE, "loop_angle": val})

    @settings(max_examples=100)
    @given(val=angle_too_low_st)
    def test_loop_angle_too_low_rejected(self, val: float):
        """**Validates: Requirements 9.2**

        loop_angle < -180 must be rejected.
        loop_angle < -180 应被拒绝。
        """
        with pytest.raises(ValidationError):
            ConvertGenerateRequest(**{**_VALID_BASE, "loop_angle": val})

    # --- loop_offset_x out of range ---

    @settings(max_examples=100)
    @given(val=offset_too_high_st)
    def test_loop_offset_x_too_high_rejected(self, val: float):
        """**Validates: Requirements 9.3**

        loop_offset_x > 200 must be rejected.
        loop_offset_x > 200 应被拒绝。
        """
        with pytest.raises(ValidationError):
            ConvertGenerateRequest(**{**_VALID_BASE, "loop_offset_x": val})

    @settings(max_examples=100)
    @given(val=offset_too_low_st)
    def test_loop_offset_x_too_low_rejected(self, val: float):
        """**Validates: Requirements 9.3**

        loop_offset_x < -200 must be rejected.
        loop_offset_x < -200 应被拒绝。
        """
        with pytest.raises(ValidationError):
            ConvertGenerateRequest(**{**_VALID_BASE, "loop_offset_x": val})

    # --- loop_offset_y out of range ---

    @settings(max_examples=100)
    @given(val=offset_too_high_st)
    def test_loop_offset_y_too_high_rejected(self, val: float):
        """**Validates: Requirements 9.3**

        loop_offset_y > 200 must be rejected.
        loop_offset_y > 200 应被拒绝。
        """
        with pytest.raises(ValidationError):
            ConvertGenerateRequest(**{**_VALID_BASE, "loop_offset_y": val})

    @settings(max_examples=100)
    @given(val=offset_too_low_st)
    def test_loop_offset_y_too_low_rejected(self, val: float):
        """**Validates: Requirements 9.3**

        loop_offset_y < -200 must be rejected.
        loop_offset_y < -200 应被拒绝。
        """
        with pytest.raises(ValidationError):
            ConvertGenerateRequest(**{**_VALID_BASE, "loop_offset_y": val})
