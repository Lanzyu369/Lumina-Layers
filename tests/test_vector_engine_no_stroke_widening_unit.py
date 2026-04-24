"""Regression guard: ensure ``core/vector_engine.py`` never re-introduces
the 'widen thin stroke to nozzle width' buffer step.

That step (originally added in commit 34a22dc, PR #24 overhaul) was a
silent geometry mutation that outward-buffered every sub-nozzle stroke
shape by ``0.5 * (nozzle - stroke)`` using ``join_style='mitre',
mitre_limit=2.0``. It produced two visible regressions simultaneously:

  1. Every fine contour in illustrated SVGs grew chunky and fuzzy.
  2. Mitre joins at sharp corners generated outward spikes.

The regression was diagnosed via a pixel-level A/B that showed disabling
the widening branch immediately restored clean vector strokes matching
the reference ChromaPrint3D output.

These checks are intentionally lightweight (static source scans) so they
survive refactors that rename internal helpers, while still guarding
against the specific mutation signature that caused the regression.

回归守护：core/vector_engine.py 不应再引入 "按 nozzle 宽度外扩细描边" 的
buffer 步骤。该步骤（PR #24 overhaul 悄悄塞入）让细笔触整体变粗、mitre
尖角产生毛刺，与参考项目输出严重不符。本测试通过静态扫描源码来保证
该 regression 不会被重新引入。
"""

from __future__ import annotations

import os
import re

import pytest


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VECTOR_ENGINE_PATH = os.path.join(_REPO_ROOT, "core", "vector_engine.py")


@pytest.fixture(scope="module")
def vector_engine_source() -> str:
    """Read core/vector_engine.py as a single UTF-8 string."""
    with open(_VECTOR_ENGINE_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


def test_min_printable_stroke_svg_variable_not_reintroduced(vector_engine_source):
    """The ``min_printable_stroke_svg`` threshold (ratio of nozzle width
    to scale factor) must not reappear. Its only historical use was the
    widening branch we removed.

    min_printable_stroke_svg 变量不得重现：历史唯一用法就是描边膨胀分支。
    """
    # Allow the name to appear inside a NOTE/comment block documenting the
    # regression, but not as a live variable binding. We detect a live
    # binding by requiring `= ` (assignment) somewhere on the same line.
    offending = []
    for lineno, line in enumerate(vector_engine_source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if re.search(r"\bmin_printable_stroke_svg\b\s*=", line):
            offending.append((lineno, line.rstrip()))

    assert not offending, (
        "min_printable_stroke_svg assignment was re-introduced — this is the "
        "stroke-widening regression (see commit 34a22dc / PR #24). Offending "
        "lines:\n" + "\n".join(f"  line {ln}: {src}" for ln, src in offending)
    )


def test_stroke_width_widening_gate_not_reintroduced(vector_engine_source):
    """The widening branch was gated by a ``stroke_width_svg < <threshold>``
    comparison that triggered an outward buffer. No such comparison should
    exist in active code.

    ``_normalize_contours`` and ``_filter_slits`` also call mitre buffer
    but as balanced close/open pairs (buffer(+d) followed by buffer(-d)),
    which do not inflate contours. Those are legal; the widening branch
    was a single unpaired outward buffer keyed by stroke width.

    守护：不得再出现按 stroke 宽度作为阈值触发外扩 buffer 的分支；
    _normalize_contours 等模块里的平衡 close/open 操作是合法的。
    """
    offending = []
    for lineno, line in enumerate(vector_engine_source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # Widening gate was literally
        #     stroke_width_svg < min_printable_stroke_svg
        # We guard against any "< ...stroke..." comparison that uses stroke
        # width as a gate for a buffer call. Keeping the pattern narrow to
        # the actual regression so unrelated refactors are not blocked.
        if re.search(r"\bstroke_width_svg\s*<\s*", line):
            offending.append((lineno, line.rstrip()))

    assert not offending, (
        "A ``stroke_width_svg < <threshold>`` comparison was re-introduced "
        "— historically this was the entry into the stroke-widening buffer. "
        "Offending lines:\n"
        + "\n".join(f"  line {ln}: {src}" for ln, src in offending)
    )


def test_nozzle_width_not_used_as_geometric_threshold(vector_engine_source):
    """The nozzle width should not be mixed into SVG coordinate space via
    division by ``scale_factor`` inside the shape finalisation code.
    That division produced ``min_printable_stroke_svg`` and was the gate
    for the widening branch.

    nozzle 宽度除以 scale_factor 得到 SVG 空间阈值——这是膨胀分支的入口，
    不得重现。
    """
    pattern = re.compile(
        r"PrinterConfig\.NOZZLE_WIDTH\s*/\s*max\s*\(\s*scale_factor",
    )
    offending = []
    for lineno, line in enumerate(vector_engine_source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if pattern.search(line):
            offending.append((lineno, line.rstrip()))

    assert not offending, (
        "PrinterConfig.NOZZLE_WIDTH / scale_factor expression re-introduced "
        "— this used to be min_printable_stroke_svg, the stroke-widening "
        "regression gate. Offending lines:\n"
        + "\n".join(f"  line {ln}: {src}" for ln, src in offending)
    )
