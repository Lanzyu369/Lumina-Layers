"""Calibration method protocol + parameters (Phase 2 sketch).
校准方法协议与参数（Phase 2 草图）。

Establishes the ``CalibrationMethod`` abstraction described in
``progress/pipeline-refactor-design.md`` §6: each calibration generator
becomes a callable subclass of this protocol so new methods land without
touching old ones, and any (method, color-mode, renderer) combination is
reachable through composition rather than per-cell bespoke code.

Status:
    Phase 2 introduces the protocol + a ``CalibrationParams`` dataclass and
    wires ONE lighthouse adopter (``Smart1296CalibrationMethod``) to satisfy
    AGENTS.md L42 ("New utilities ... must land with at least one adoption
    site in the same PR"). Migration of every other ``generate_*_board``
    function in ``core/calibration.py`` is deferred to Phase 4 per design
    doc §4.

Out of scope here:
- ``BoardLayout`` IR (Phase 3 — see ``core/board_layout.py``).
- ``Renderer`` plugin Protocol (Phase 3).
- Bit-exact migration of every existing generator (Phase 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from core.color_modes import ColorMode


@dataclass(frozen=True)
class CalibrationParams:
    """Per-invocation calibration parameters (board geometry knobs).
    单次校准调用的参数（板几何旋钮）。

    Attributes:
        block_size_mm: 单格物理边长（毫米）。Per-cell physical edge length.
        gap_mm: 相邻格之间的物理间距（毫米）。Inter-cell physical gap.
        backing_thickness_mm: 底板厚度（毫米）；``None`` 时使用打印机默认值。
            Backing thickness; ``None`` falls back to ``PrinterConfig`` default.
        page_index: 多页模式（如 5-Color Extended）的页索引；零基。
            0-based page index for multi-page modes (e.g. 5-Color Extended).
        options: 不进入主签名的杂项选项（例如 ``corner_markers_enabled``）。
            Catch-all for sundry per-method options.
    """

    block_size_mm: float = 5.0
    gap_mm: float = 0.8
    backing_thickness_mm: float | None = None
    page_index: int = 0
    options: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CalibrationMethod(Protocol):
    """Protocol every calibration generator must satisfy (Phase 2 sketch).
    每个校准生成器必须满足的协议（Phase 2 草图）。

    Phase 2 establishes the *shape*; subclasses currently delegate back to
    the original ``generate_*_board()`` functions inside ``core.calibration``
    to keep behaviour bit-exact. Phase 4 will rewrite the bodies so each
    method returns a ``BoardLayout`` (IR) and rendering is pluggable.

    The runtime ``isinstance`` check is enabled via ``@runtime_checkable``
    so consumers can validate plug-ins without importing concrete types.
    """

    name: str
    """Stable identifier, e.g. ``"smart-1296"``."""

    description: str
    """Human-readable one-line description."""

    def generate(
        self,
        mode: ColorMode,
        params: CalibrationParams,
    ) -> Any:
        """Produce the calibration artefact for ``mode``.

        Phase 2 returns the legacy artefact shape (whatever the wrapped
        ``generate_*_board()`` returns). Phase 3 will tighten the return
        type to ``BoardLayout``.

        Args:
            mode: Canonical ColorMode descriptor (see ``core.color_modes``).
            params: Per-invocation parameters (geometry, page, ...).

        Returns:
            Method-specific artefact; see the lighthouse adopter for the
            current shape.
        """
        ...


# ---------------------------------------------------------------------------
# Lighthouse adopter — Smart1296 (6-Color CMYWGK 1296)
# ---------------------------------------------------------------------------


class Smart1296CalibrationMethod:
    """Lighthouse adopter for the 6-Color (CMYWGK 1296) board.
    6 色 CMYWGK 1296 校准板的灯塔适配。

    Wraps the existing ``core.calibration.generate_smart_board`` so the
    ``CalibrationMethod`` protocol has a working concrete implementation
    without touching the calibration generator code.

    Bit-exact contract: ``self.generate(mode, params)`` produces the same
    artefact as the legacy entry point with the same arguments.
    """

    name = "smart-1296"
    description = "6-Color (CMYWGK 1296) calibration board (Smart 1296 algorithm)"

    def generate(
        self,
        mode: ColorMode,
        params: CalibrationParams,
    ) -> Any:
        """Delegate to the legacy ``generate_smart_board`` entry point.
        委托给旧的 ``generate_smart_board`` 入口。

        Validates that ``mode`` is the 6-Color CMYWGK 1296 mode this method
        was designed for — calling Smart1296 with another mode would silently
        produce wrong data, so the failure is escalated to a ``ValueError``.

        Args:
            mode: Must be the 6-Color (CMYWGK 1296) mode.
            params: Per-invocation parameters; only ``block_size_mm``,
                ``gap_mm``, and ``backing_thickness_mm`` are forwarded.

        Returns:
            Whatever ``generate_smart_board`` returns (legacy 3MF path tuple).
        """
        if mode.canonical_display_name != "6-Color (CMYWGK 1296)":
            raise ValueError(
                f"Smart1296CalibrationMethod is designed for 6-Color (CMYWGK 1296); "
                f"got {mode.canonical_display_name!r}"
            )

        # Lazy import to avoid pulling the heavy calibration module on every
        # ``import core.calibration_methods``.
        from core.calibration import generate_smart_board

        return generate_smart_board(
            block_size_mm=params.block_size_mm,
            gap_mm=params.gap_mm,
            backing_thickness_mm=params.backing_thickness_mm,
        )


__all__ = [
    "CalibrationParams",
    "CalibrationMethod",
    "Smart1296CalibrationMethod",
]
