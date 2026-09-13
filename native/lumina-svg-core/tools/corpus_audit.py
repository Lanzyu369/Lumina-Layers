#!/usr/bin/env python3
"""Measure native SVG parser completeness on an anonymous local corpus."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Callable

import numpy as np

import lumina_svg_core

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on Windows
    resource = None


def _collection_area_source_units_squared(
    collection: Any,
    grid_to_source_unit: float,
) -> float:
    coordinates = np.asarray(collection.coordinates, dtype=np.int64)
    ring_offsets = np.asarray(collection.ring_offsets, dtype=np.uint64)
    hole_parent = np.asarray(collection.hole_parent, dtype=np.int64)
    total_grid_area = np.longdouble(0)
    for ring_index, (start, end) in enumerate(
        zip(ring_offsets[:-1], ring_offsets[1:], strict=True)
    ):
        ring = coordinates[int(start) : int(end)]
        if len(ring) < 4:
            continue
        x0 = ring[:-1, 0].astype(np.longdouble, copy=False)
        y0 = ring[:-1, 1].astype(np.longdouble, copy=False)
        x1 = ring[1:, 0].astype(np.longdouble, copy=False)
        y1 = ring[1:, 1].astype(np.longdouble, copy=False)
        area = np.abs(np.sum(x0 * y1 - y0 * x1)) / np.longdouble(2)
        total_grid_area += area if hole_parent[ring_index] < 0 else -area
    return float(
        total_grid_area
        * np.longdouble(grid_to_source_unit)
        * np.longdouble(grid_to_source_unit)
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _process_peak_rss_bytes() -> int:
    if resource is None:
        return 0
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def audit_corpus(
    corpus_dir: Path,
    *,
    target_width_mm: float,
    tolerance_mm: float,
    allow_strokes: bool = True,
    progress_callback: Callable[[str, str, float], None] | None = None,
) -> dict[str, Any]:
    """Analyze every SVG and return anonymous completeness/performance data.

    分析目录内全部 SVG，并返回不含源路径和哈希的完整性与性能数据。

    Args:
        corpus_dir: Directory searched recursively for ``*.svg`` files.
            递归查找 ``*.svg`` 的目录。
        target_width_mm: Common geometry scaling width. 统一几何缩放宽度。
        tolerance_mm: Common curve approximation error budget. 统一曲线近似预算。
        allow_strokes: Whether stroke paint is expanded to area. 是否将描边展开为面积。
        progress_callback: Optional anonymous per-document progress hook.
            可选的匿名逐文档进度回调。

    Returns:
        JSON-serializable anonymous report. 可序列化为 JSON 的匿名报告。
    """

    root = Path(corpus_dir)
    svg_paths = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() == ".svg"
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    documents: list[dict[str, Any]] = []
    elapsed_values: list[float] = []
    status_counts: Counter[str] = Counter()
    unsupported_reasons: Counter[str] = Counter()
    unprintable_reasons: Counter[str] = Counter()
    aggregate = Counter()

    audit_started = perf_counter()
    for index, path in enumerate(svg_paths, start=1):
        started = perf_counter()
        result = lumina_svg_core.analyze_svg(
            path,
            target_width_mm,
            tolerance_mm,
            allow_strokes,
        )
        elapsed = perf_counter() - started
        elapsed_values.append(elapsed)
        status = str(result.status)
        reason_code = str(result.reason_code)
        status_counts[status] += 1
        if status != "supported" and reason_code:
            unsupported_reasons[reason_code] += 1

        input_paint_count = int(result.input_paint_count)
        raw_output_paint_count = int(result.raw.geometry_count)
        visible_output_paint_count = int(result.visible.geometry_count)
        raw_alpha = np.asarray(result.raw.rgba_f64, dtype=np.float64)[:, 3]
        visible_alpha = np.asarray(
            result.visible.rgba_f64, dtype=np.float64
        )[:, 3]
        partial_alpha_raw_paint_count = int(
            np.count_nonzero((raw_alpha > 0.0) & (raw_alpha < 1.0))
        )
        partial_alpha_visible_paint_count = int(
            np.count_nonzero(
                (visible_alpha > 0.0) & (visible_alpha < 1.0)
            )
        )
        composite_visible_paint_count = int(
            np.count_nonzero(
                np.asarray(result.visible.source_kinds, dtype=np.int32) == 3
            )
        )
        visible_contributor_count = int(
            np.asarray(
                result.visible.contributor_weights, dtype=np.float64
            ).size
        )
        fragment_reason_counts = Counter(
            str(value)
            for value in result.unprintable_fragments.reason_codes
        )
        fragment_count = int(result.unprintable_fragments.count)
        unprintable_reasons.update(fragment_reason_counts)
        aggregate.update(
            {
                "input_paint_count": input_paint_count,
                "raw_output_paint_count": raw_output_paint_count,
                "visible_output_paint_count": visible_output_paint_count,
                "partial_alpha_raw_paint_count": (
                    partial_alpha_raw_paint_count
                ),
                "partial_alpha_visible_paint_count": (
                    partial_alpha_visible_paint_count
                ),
                "composite_visible_paint_count": (
                    composite_visible_paint_count
                ),
                "visible_contributor_count": visible_contributor_count,
                "raw_component_count": int(result.raw.component_count),
                "visible_component_count": int(
                    result.visible.component_count
                ),
                "raw_hole_count": int(result.raw.hole_count),
                "visible_hole_count": int(result.visible.hole_count),
                "unprintable_fragment_count": fragment_count,
            }
        )

        raw_area = _collection_area_source_units_squared(
            result.raw, float(result.grid_to_source_unit)
        ) if status == "supported" else 0.0
        visible_area = _collection_area_source_units_squared(
            result.visible, float(result.grid_to_source_unit)
        ) if status == "supported" else 0.0
        silhouette_area = _collection_area_source_units_squared(
            result.silhouette, float(result.grid_to_source_unit)
        ) if status == "supported" else 0.0
        visible_partition_delta = abs(visible_area - silhouette_area)
        visible_partition_scale = max(
            abs(visible_area), abs(silhouette_area)
        )
        visible_partition_relative_delta = (
            visible_partition_delta / visible_partition_scale
            if visible_partition_scale > 0.0
            else 0.0
        )
        anonymous_id = f"svg-{index:06d}"
        documents.append(
            {
                "anonymous_id": anonymous_id,
                "status": status,
                "reason_code": reason_code,
                "input_paint_count": input_paint_count,
                "raw_output_paint_count": raw_output_paint_count,
                "visible_output_paint_count": visible_output_paint_count,
                "partial_alpha_raw_paint_count": (
                    partial_alpha_raw_paint_count
                ),
                "partial_alpha_visible_paint_count": (
                    partial_alpha_visible_paint_count
                ),
                "composite_visible_paint_count": (
                    composite_visible_paint_count
                ),
                "visible_contributor_count": visible_contributor_count,
                "raw_component_count": int(result.raw.component_count),
                "visible_component_count": int(
                    result.visible.component_count
                ),
                "raw_hole_count": int(result.raw.hole_count),
                "visible_hole_count": int(result.visible.hole_count),
                "raw_area_source_units_squared": raw_area,
                "visible_area_source_units_squared": visible_area,
                "silhouette_area_source_units_squared": silhouette_area,
                "raw_to_visible_area_delta": raw_area - visible_area,
                "visible_partition_area_delta": visible_partition_delta,
                "visible_partition_area_relative_delta": (
                    visible_partition_relative_delta
                ),
                "unprintable_fragment_count": fragment_count,
                "unprintable_reasons": dict(
                    sorted(fragment_reason_counts.items())
                ),
                "elapsed_seconds": elapsed,
                "recorder_seconds": float(result.recorder_seconds),
                "kernel_seconds": float(result.kernel_seconds),
                "bounds_seconds": float(result.bounds_seconds),
                "replay_seconds": float(result.replay_seconds),
                "topology_seconds": float(result.topology_seconds),
                "composite_seconds": float(result.composite_seconds),
                "export_seconds": float(result.export_seconds),
            }
        )
        if progress_callback is not None:
            progress_callback(anonymous_id, status, elapsed)

    total_seconds = perf_counter() - audit_started
    summary = {
        "file_count": len(documents),
        "supported_count": status_counts.get("supported", 0),
        "unsupported_count": status_counts.get("unsupported", 0),
        "invalid_count": status_counts.get("invalid", 0),
        **{
            key: int(aggregate.get(key, 0))
            for key in (
                "input_paint_count",
                "raw_output_paint_count",
                "visible_output_paint_count",
                "partial_alpha_raw_paint_count",
                "partial_alpha_visible_paint_count",
                "composite_visible_paint_count",
                "visible_contributor_count",
                "raw_component_count",
                "visible_component_count",
                "raw_hole_count",
                "visible_hole_count",
                "unprintable_fragment_count",
            )
        },
        "unprintable_reasons": dict(sorted(unprintable_reasons.items())),
        "unsupported_reasons": dict(sorted(unsupported_reasons.items())),
        "visible_partition_area_delta_max": max(
            (
                float(item["visible_partition_area_delta"])
                for item in documents
            ),
            default=0.0,
        ),
        "visible_partition_area_relative_delta_max": max(
            (
                float(item["visible_partition_area_relative_delta"])
                for item in documents
            ),
            default=0.0,
        ),
    }
    return {
        "schema_version": 3,
        "settings": {
            "target_width_mm": target_width_mm,
            "tolerance_mm": tolerance_mm,
            "allow_strokes": allow_strokes,
        },
        "summary": summary,
        "performance": {
            "total_seconds": total_seconds,
            "median_seconds": _percentile(elapsed_values, 0.5),
            "p95_seconds": _percentile(elapsed_values, 0.95),
            "max_seconds": max(elapsed_values, default=0.0),
            # This is the peak of the fresh audit process, including the
            # parser runtime and all documents processed so far. It is not a
            # per-document RSS sample.
            "corpus_process_peak_rss_bytes": _process_peak_rss_bytes(),
        },
        "documents": documents,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-width-mm", type=float, default=100.0)
    parser.add_argument("--tolerance-mm", type=float, default=0.02)
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Write anonymous per-document progress to stderr.",
    )
    parser.add_argument(
        "--no-strokes",
        action="store_false",
        dest="allow_strokes",
        help="Exclude stroke paint from the audit (strokes are included by default).",
    )
    parser.set_defaults(allow_strokes=True)
    args = parser.parse_args()
    def report_progress(
        anonymous_id: str, status: str, elapsed: float
    ) -> None:
        print(
            f"{anonymous_id} {status} {elapsed:.3f}s",
            file=sys.stderr,
            flush=True,
        )

    report = audit_corpus(
        args.corpus,
        target_width_mm=args.target_width_mm,
        tolerance_mm=args.tolerance_mm,
        allow_strokes=args.allow_strokes,
        progress_callback=report_progress if args.progress else None,
    )
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
