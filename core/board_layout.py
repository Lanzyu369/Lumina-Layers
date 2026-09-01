"""BoardLayout IR + Renderer protocol (Phase 3 sketch).
校准板中间表示与渲染器协议（Phase 3 草图）。

Establishes the ``BoardLayout`` IR and ``Renderer`` Protocol described in
``progress/pipeline-refactor-design.md`` §7. Pre-Phase-3, every
``generate_*_board()`` function inlined ``_generate_voxel_mesh`` at the
bottom; this coupled mesh generation to mode dispatch and prevented adding
SVG / multi-layer-count output formats without per-mode rewrites.

Status:
    Phase 3 introduces the dataclass + protocol and ships ONE lighthouse
    adopter (``VoxelMeshRenderer`` wrapping
    ``core.calibration._generate_voxel_mesh``) so AGENTS.md L42's
    "lighthouse adoption" rule is satisfied. Rewriting every existing
    calibration generator to *produce* a ``BoardLayout`` (instead of
    inlining the mesh path) is deferred to Phase 4 per design doc §4.

Out of scope here:
- Migrating ``generate_*_board()`` to return ``BoardLayout`` (Phase 4).
- ``SVGRenderer`` end-to-end (Phase 3 detailed spec, post-soak).
- ``PreviewPNGRenderer`` (Phase 3 detailed spec).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np

from core.color_modes import ColorMode


@dataclass(frozen=True)
class BoardLayoutMetadata:
    """Sidecar metadata that travels with a ``BoardLayout``.
    与 ``BoardLayout`` 一起流转的辅助元数据。

    Kept frozen so layouts can be safely cached / passed across worker
    boundaries without surprise mutation.
    """

    corner_positions: tuple[tuple[int, int], ...] = ()
    """TL/TR/BR/BL grid coordinates of the calibration corner markers."""

    slot_labels: tuple[str, ...] = ()
    """Human-readable per-slot labels (length == ``mode.n_materials``)."""

    page_index: int = 0
    """Zero-based page index for multi-page modes (5-Color Extended)."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Catch-all for method-specific metadata (e.g. recipe overrides)."""


@dataclass(frozen=True)
class BoardLayout:
    """Mode-independent intermediate representation of a calibration board.
    校准板的中间表示，与颜色模式无关。

    Pure data; no rendering logic. Multiple ``Renderer`` plug-ins can consume
    the same ``BoardLayout`` to produce 3MF / SVG / PNG / future formats
    without per-renderer per-mode bespoke code.

    Attributes:
        voxel_matrix: ``(Z, H, W)`` int array. Each cell stores the material
            ID for that voxel; backing layers carry ``mode.max_material_id``
            or a sentinel agreed with the renderer.
        color_mode: The canonical ``ColorMode`` this layout was produced for.
        metadata: Corner positions, slot labels, page index, etc.

    Phase 3 keeps this minimal; later phases may add ``physical_size_mm``,
    ``cell_centers``, etc. as renderers need them.
    """

    voxel_matrix: np.ndarray
    color_mode: ColorMode
    metadata: BoardLayoutMetadata = field(default_factory=BoardLayoutMetadata)

    def __post_init__(self) -> None:
        if self.voxel_matrix.ndim != 3:
            raise ValueError(
                f"BoardLayout.voxel_matrix must be 3D (Z, H, W); "
                f"got ndim={self.voxel_matrix.ndim}"
            )
        if not np.issubdtype(self.voxel_matrix.dtype, np.integer):
            raise ValueError(
                f"BoardLayout.voxel_matrix must be integer dtype; "
                f"got {self.voxel_matrix.dtype}"
            )


@runtime_checkable
class Renderer(Protocol):
    """Protocol every output renderer must satisfy (Phase 3 sketch).
    每个输出渲染器必须满足的协议（Phase 3 草图）。

    Phase 3 ships a thin ``VoxelMeshRenderer`` adopter; richer renderers
    (``SVGRenderer``, ``PreviewPNGRenderer``) are tracked for later phases.
    """

    output_format: str
    """Format tag, e.g. ``"3mf"``, ``"svg"``, ``"png"``."""

    def render(self, layout: BoardLayout) -> Any:
        """Render ``layout`` into this renderer's output format.

        Args:
            layout: The mode-independent ``BoardLayout`` to render.

        Returns:
            Format-specific artefact (e.g. ``trimesh.Scene`` for 3MF,
            ``str`` for SVG, ``PIL.Image.Image`` for PNG).
        """
        ...


# ---------------------------------------------------------------------------
# Lighthouse adopter — VoxelMeshRenderer
# ---------------------------------------------------------------------------


class VoxelMeshRenderer:
    """Lighthouse adopter wrapping ``core.calibration._generate_voxel_mesh``.
    包装 ``core.calibration._generate_voxel_mesh`` 的灯塔渲染器。

    Phase 3 routes ``BoardLayout``-driven voxel meshing through this class
    without touching the underlying meshing implementation. Each material in
    the layout produces one ``trimesh.Trimesh``; renderer concatenates them
    into a ``trimesh.Scene``.

    Compatibility contract: layouts preserve the established material IDs,
    physical dimensions, and TL/TR/BR/BL direction semantics while the
    shared mesher may use a different closed-surface triangulation.
    """

    output_format = "3mf"

    def render(self, layout: BoardLayout) -> Any:
        """Render the layout into a ``trimesh.Scene`` of per-material meshes.
        将布局渲染为每材料 trimesh 网格组成的场景。

        Args:
            layout: Source layout. ``layout.voxel_matrix`` is ``(Z, H, W)``.

        Returns:
            A ``trimesh.Scene`` whose ``geometry`` dict is keyed by material
            slot label and whose values are per-material meshes.
        """
        # Lazy imports to avoid pulling trimesh + heavy calibration module
        # on every ``import core.board_layout``.
        import trimesh

        from core.calibration import _generate_voxel_mesh

        voxel_matrix = layout.voxel_matrix
        _, grid_h, grid_w = voxel_matrix.shape
        n_materials = layout.color_mode.n_materials
        slot_labels = layout.metadata.slot_labels or tuple(
            f"slot_{i}" for i in range(n_materials)
        )

        scene = trimesh.Scene()
        for material_index in range(n_materials):
            mesh = _generate_voxel_mesh(
                voxel_matrix=voxel_matrix,
                material_index=material_index,
                grid_h=grid_h,
                grid_w=grid_w,
            )
            if mesh is None:
                continue
            label = slot_labels[material_index] if material_index < len(slot_labels) else f"slot_{material_index}"
            scene.add_geometry(mesh, geom_name=label)
        return scene


__all__ = [
    "BoardLayout",
    "BoardLayoutMetadata",
    "Renderer",
    "VoxelMeshRenderer",
]
