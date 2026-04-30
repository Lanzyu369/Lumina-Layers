"""Canonical ColorMode value object + registry (Phase 1).
统一颜色模式值对象与注册表（Phase 1）。

Replaces six string-matching dispatch sites previously scattered across
``config.ColorSystem.get``, ``core.lut_merger`` (``_SIZE_TO_MODE`` /
``_MODE_PRIORITY`` / ``_MODE_MAX_MATERIAL``), ``core.extractor._generate_recipes``,
``core.pipeline.processing_ops.lut_loader``, and
``core.pipeline.pipeline_utils.detect_lut_color_mode``. See
``progress/pipeline-refactor-design.md`` §2.1 + §5 for the diagnosis and
target architecture.

Phase 1 scope (this commit):
- Single ``ColorMode`` value object capturing per-mode invariants.
- Module-level alias-aware registry: ``ColorMode.from_name(str)``,
  ``ColorMode.from_lut_size(int)``,
  ``ColorMode.from_lut_size_and_layers(int, int|None, int|None)``.
- Backward-compatible bridge: every ``ColorMode`` exposes a ``legacy_dict``
  property returning the equivalent ``config.ColorSystem.<MODE>`` dict so
  callers that read the historical shape keep working unchanged.

Out of scope for Phase 1 (deferred to Phase 4 per design doc §4):
- ``CalibrationMethod`` Protocol/ABC.
- ``BoardLayout`` IR + ``Renderer`` plugins.
- Hard-coded layer counts inside ``core/calibration.py`` —
  Phase 1 only routes the *taxonomy* through ``ColorMode``; per-mode
  generator function bodies stay untouched.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional


# ---------------------------------------------------------------------------
# Value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColorMode:
    """Canonical color mode descriptor.
    颜色模式规范描述符。

    Attributes:
        name: 内部稳定 ID，例如 ``"6-color-rybw-1296"``。Stable internal id.
        display_names: 历史上出现的全部展示名（含别名），按优先级排序；
            ``display_names[0]`` 即向外/向前端公开的标准字符串。
            All historical display strings (incl. aliases); ``[0]`` is the
            canonical public string.
        n_materials: 材料 slot 数量。Number of material slots.
        n_layers: 颜色层数（5 / 6 / 未来值）。Color layer count.
        priority: 合并冲突时的优先级，数值越大优先级越高（替换
            ``core.lut_merger._MODE_PRIORITY``）。Higher wins during merge dedup.
        expected_lut_size: 该模式 LUT 的标准条目数；``None`` 表示 ``Merged``
            等无固定尺寸的模式。Canonical LUT row count; ``None`` for sizeless modes.
        legacy_color_system_attr: ``config.ColorSystem.<NAME>`` 中对应的属性名，
            用于 ``legacy_dict`` 旁路。Backing attribute name on ``ColorSystem``.
        size_range: 用于 ``detect_lut_color_mode`` 阈值的 (min, max_exclusive)
            元组；当 LUT 列数落在此区间且其余守卫通过时即可判定为该模式。
            ``None`` 表示该模式不参与基于尺寸的反向探测。
        requires_layer_count: 仅当所提供的层数等于该值时才接受按尺寸命中；
            ``None`` 时忽略。Used by 5-Color Extended (size + layers=6 both required).
        requires_max_material_at_most: 仅当 ``max_material`` ≤ 此值时才接受；
            ``None`` 时忽略。Used by 5-Color Extended (max_material<=4).
    """

    name: str
    display_names: tuple[str, ...]
    n_materials: int
    n_layers: int
    priority: int
    expected_lut_size: Optional[int]
    legacy_color_system_attr: Optional[str]
    size_range: Optional[tuple[int, int]] = None
    requires_layer_count: Optional[int] = None
    requires_max_material_at_most: Optional[int] = None

    # Internal: ordered detection priority (higher = checked earlier in the
    # cascade so 5-Color Extended is matched before the broader 8-color
    # window when both could otherwise fit).
    _detection_priority: int = 0

    def __post_init__(self) -> None:
        # Frozen dataclass: validate invariants at construction.
        if not self.display_names:
            raise ValueError(f"ColorMode {self.name!r}: display_names must be non-empty")
        if self.n_materials <= 0:
            raise ValueError(f"ColorMode {self.name!r}: n_materials must be positive")
        if self.n_layers <= 0:
            raise ValueError(f"ColorMode {self.name!r}: n_layers must be positive")

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def canonical_display_name(self) -> str:
        """对外标准展示名（前端/API 使用此值）。"""
        return self.display_names[0]

    @property
    def max_material_id(self) -> int:
        """最大材料 ID（替换 ``_MODE_MAX_MATERIAL``）。"""
        return self.n_materials - 1

    @property
    def legacy_dict(self) -> dict[str, Any] | None:
        """返回 ``config.ColorSystem.<MODE>`` 中等价的旧 dict（向后兼容旁路）。
        Bridge to the legacy ``ColorSystem`` dict shape (None for ``Merged``).
        """
        if self.legacy_color_system_attr is None:
            return None
        # Lazy import to avoid cycles at module load.
        from config import ColorSystem

        return getattr(ColorSystem, self.legacy_color_system_attr)

    # ------------------------------------------------------------------
    # Lookup API (replaces the six dispatch sites)
    # ------------------------------------------------------------------

    @classmethod
    def from_name(cls, name: str | None) -> Optional["ColorMode"]:
        """按字符串名（含别名）查找 ColorMode；找不到时返回 ``None``。
        Look up by display name / alias. Returns ``None`` for unknown input.

        Replaces ``ColorSystem.get`` string-matching cascade (config.py L274-326).
        """
        if name is None:
            return None
        # Exact-match fast path.
        mode = _NAME_INDEX.get(name)
        if mode is not None:
            return mode
        # Substring fallback to mirror the legacy "X-Color in mode" behaviour.
        for mode in iter_modes():
            for alias in mode.display_names:
                if alias and alias in name:
                    return mode
        return None

    @classmethod
    def from_lut_size(cls, size: int) -> Optional["ColorMode"]:
        """按 LUT 行数精确查找（替换 ``core.lut_merger._SIZE_TO_MODE``）。
        Exact-size lookup; returns ``None`` if the size is not canonical.
        """
        return _SIZE_INDEX.get(int(size))

    @classmethod
    def from_lut_size_and_layers(
        cls,
        size: int,
        layers: int | None = None,
        max_material: int | None = None,
    ) -> Optional["ColorMode"]:
        """按 (size, layers, max_material) 三元组探测（替换
        ``core.pipeline.pipeline_utils.detect_lut_color_mode`` 的阈值阶梯）。

        Returns the first ``ColorMode`` whose ``size_range`` contains ``size``
        and whose layer + max_material guards are satisfied. Modes are checked
        in descending ``_detection_priority`` so the most specific (5-Color
        Extended, with its layer + max_material guards) wins over the broader
        8-color window when both could match.
        """
        for mode in _MODES_BY_DETECTION_PRIORITY:
            rng = mode.size_range
            if rng is None:
                continue
            lo, hi = rng
            if not (lo <= size < hi):
                continue
            if (
                mode.requires_layer_count is not None
                and layers is not None
                and layers != mode.requires_layer_count
            ):
                # Layer guard is only enforced when the caller actually knows
                # the layer count; ``.npy`` LUTs carry no stacks metadata so
                # they pass on size alone (matches legacy behaviour).
                continue
            if mode.requires_max_material_at_most is not None:
                if max_material is not None and max_material > mode.requires_max_material_at_most:
                    continue
            return mode
        return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


# Canonical taxonomy. Values mirror the behaviours captured in:
#   config.py::ColorSystem.get          (display-name aliases)
#   core/lut_merger.py::_SIZE_TO_MODE   (size -> mode)
#   core/lut_merger.py::_MODE_PRIORITY  (priority)
#   core/lut_merger.py::_MODE_MAX_MATERIAL (n_materials - 1)
#   core/pipeline/pipeline_utils.py::detect_lut_color_mode (size ranges)
# See ``progress/pipeline-refactor-design.md`` §2.1 for cross-file diagnosis.
_REGISTRY: tuple[ColorMode, ...] = (
    ColorMode(
        name="bw",
        display_names=("BW (Black & White)", "BW"),
        n_materials=2,
        n_layers=5,
        priority=0,
        expected_lut_size=32,
        legacy_color_system_attr="BW",
        size_range=(30, 36),
        _detection_priority=10,
    ),
    ColorMode(
        name="4-color-rybw",
        # ``"4-Color"`` is the legacy primary string; CMYW is a separate mode below.
        display_names=("4-Color", "4-Color (RYBW)", "RYBW"),
        n_materials=4,
        n_layers=5,
        priority=1,
        expected_lut_size=1024,
        legacy_color_system_attr="RYBW",
        size_range=(900, 1200),
        _detection_priority=20,
    ),
    ColorMode(
        name="4-color-cmyw",
        display_names=("4-Color (CMYW)", "CMYW"),
        n_materials=4,
        n_layers=5,
        priority=1,
        # CMYW shares the same exact size as RYBW; from_lut_size returns
        # the first registered match (RYBW), so CMYW is reachable via
        # from_name only — same as the legacy ColorSystem.get behaviour.
        expected_lut_size=None,
        legacy_color_system_attr="CMYW",
        # Detection priority deliberately lower than RYBW so size-based
        # detection still routes to "4-Color" (the legacy display string).
        _detection_priority=15,
    ),
    ColorMode(
        name="6-color-cmyw-1296",
        display_names=("6-Color (CMYWGK 1296)", "6-Color"),
        n_materials=6,
        n_layers=5,
        priority=2,
        expected_lut_size=1296,
        legacy_color_system_attr="SIX_COLOR",
        size_range=(1200, 1400),
        _detection_priority=30,
    ),
    ColorMode(
        name="6-color-rybw-1296",
        display_names=("6-Color (RYBWGK 1296)", "6-Color (RYBW)"),
        n_materials=6,
        n_layers=5,
        priority=2,
        # 6-Color (RYBW) shares the 1296 size with the CMYW variant; reachable
        # only via from_name. from_lut_size routes to the CMYW entry above.
        expected_lut_size=None,
        legacy_color_system_attr="SIX_COLOR_RYBW",
        _detection_priority=25,
    ),
    ColorMode(
        name="5-color-extended",
        display_names=("5-Color Extended", "5-Color (Extended)"),
        n_materials=5,
        n_layers=6,
        priority=1,
        expected_lut_size=2468,
        legacy_color_system_attr="FIVE_COLOR_EXTENDED",
        size_range=(2400, 2600),
        # 5-Color Extended must be matched BEFORE the 8-color window because
        # the legacy detector required layers==6 AND max_material<=4 to
        # disambiguate. Registry ordering + _detection_priority both ensure
        # this; the size-window itself does not overlap 8-color (2600+) so
        # the layer/max_material guards are belt-and-suspenders.
        requires_layer_count=6,
        requires_max_material_at_most=4,
        _detection_priority=50,
    ),
    ColorMode(
        name="8-color-max",
        display_names=("8-Color Max", "8-Color"),
        n_materials=8,
        n_layers=5,
        priority=3,
        expected_lut_size=2738,
        legacy_color_system_attr="EIGHT_COLOR",
        size_range=(2600, 2801),
        _detection_priority=40,
    ),
    ColorMode(
        name="merged",
        display_names=("Merged",),
        # 8-color superset semantics for merged LUTs (per ColorSystem.get
        # which routes "Merged" to ColorSystem.EIGHT_COLOR).
        n_materials=8,
        n_layers=5,
        priority=-1,
        expected_lut_size=None,
        legacy_color_system_attr="EIGHT_COLOR",
        _detection_priority=0,
    ),
)


def _build_name_index() -> dict[str, ColorMode]:
    index: dict[str, ColorMode] = {}
    for mode in _REGISTRY:
        for alias in mode.display_names:
            # First registration wins so the canonical display_name[0] mapping
            # is stable; aliases that collide across modes (e.g. "4-Color" /
            # "6-Color" substring tokens) still resolve via the substring
            # fallback in ``ColorMode.from_name``.
            index.setdefault(alias, mode)
    return index


def _build_size_index() -> dict[int, ColorMode]:
    index: dict[int, ColorMode] = {}
    for mode in _REGISTRY:
        if mode.expected_lut_size is not None:
            index.setdefault(mode.expected_lut_size, mode)
    return index


_NAME_INDEX: dict[str, ColorMode] = _build_name_index()
_SIZE_INDEX: dict[int, ColorMode] = _build_size_index()
_MODES_BY_DETECTION_PRIORITY: tuple[ColorMode, ...] = tuple(
    sorted(_REGISTRY, key=lambda m: -m._detection_priority)
)


# ---------------------------------------------------------------------------
# Public iterator
# ---------------------------------------------------------------------------


def iter_modes() -> Iterator[ColorMode]:
    """枚举所有已注册 ColorMode（registry 顺序保证可重复）。
    Iterate every registered ColorMode in deterministic registry order.
    """
    return iter(_REGISTRY)


# ---------------------------------------------------------------------------
# Env-override helper
# ---------------------------------------------------------------------------


def lut_2468_should_be_merged() -> bool:
    """``LUMINA_LUT_2468_MODE=merged`` 环境覆盖（保留 ``core.lut_merger``
    既有特例）。Returns ``True`` when the legacy env override redirects
    2468-size LUTs to the ``Merged`` mode.
    """
    return os.getenv("LUMINA_LUT_2468_MODE", "").strip().lower() == "merged"
