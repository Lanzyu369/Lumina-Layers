"""Tests for Phase 3 BoardLayout IR + Renderer Protocol."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest


def test_board_layout_requires_3d_int_matrix() -> None:
    """``BoardLayout`` 拒绝非 3D 或非整型 voxel_matrix。"""
    from core.board_layout import BoardLayout
    from core.color_modes import ColorMode

    mode = ColorMode.from_name("4-Color")
    assert mode is not None

    # Wrong ndim
    with pytest.raises(ValueError, match="3D"):
        BoardLayout(voxel_matrix=np.zeros((4, 4), dtype=np.int8), color_mode=mode)

    # Wrong dtype
    with pytest.raises(ValueError, match="integer"):
        BoardLayout(voxel_matrix=np.zeros((2, 4, 4), dtype=np.float32), color_mode=mode)


def test_board_layout_defaults_metadata() -> None:
    """无元数据时使用空默认。"""
    from core.board_layout import BoardLayout, BoardLayoutMetadata
    from core.color_modes import ColorMode

    mode = ColorMode.from_name("4-Color")
    assert mode is not None

    layout = BoardLayout(
        voxel_matrix=np.zeros((2, 4, 4), dtype=np.int32),
        color_mode=mode,
    )
    assert isinstance(layout.metadata, BoardLayoutMetadata)
    assert layout.metadata.page_index == 0
    assert layout.metadata.corner_positions == ()


def test_voxel_mesh_renderer_satisfies_protocol() -> None:
    """``VoxelMeshRenderer`` 必须满足 ``Renderer`` 协议。"""
    from core.board_layout import Renderer, VoxelMeshRenderer

    renderer = VoxelMeshRenderer()
    assert isinstance(renderer, Renderer)
    assert renderer.output_format == "3mf"


def test_voxel_mesh_renderer_invokes_generate_voxel_mesh_per_material() -> None:
    """每个材料 ID 都应触发一次 ``_generate_voxel_mesh`` 调用。
    Verify the renderer iterates over every material slot in the layout's
    color mode and dispatches a separate meshing call for each.
    """
    from core.board_layout import BoardLayout, BoardLayoutMetadata, VoxelMeshRenderer
    from core.color_modes import ColorMode

    mode = ColorMode.from_name("4-Color")
    assert mode is not None
    voxel_matrix = np.zeros((2, 4, 4), dtype=np.int32)
    layout = BoardLayout(
        voxel_matrix=voxel_matrix,
        color_mode=mode,
        metadata=BoardLayoutMetadata(slot_labels=("White", "Red", "Yellow", "Blue")),
    )

    # Stub the heavy meshing call. Returning ``None`` for some materials
    # exercises the renderer's "skip empty mesh" branch.
    def _fake_generate(voxel_matrix, material_index, grid_h, grid_w):
        # Return a minimal mesh stand-in for material 0/1, None for 2/3.
        if material_index >= 2:
            return None
        import trimesh

        return trimesh.Trimesh(
            vertices=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float),
            faces=np.array([[0, 1, 2]], dtype=np.int64),
        )

    renderer = VoxelMeshRenderer()
    with patch("core.calibration._generate_voxel_mesh", side_effect=_fake_generate) as fake:
        scene = renderer.render(layout)

    # Called once per material slot (n_materials == 4).
    assert fake.call_count == 4
    # Only the two non-None meshes ended up in the scene.
    assert len(scene.geometry) == 2
    # Slot labels propagated.
    assert "White" in scene.geometry
    assert "Red" in scene.geometry
