#!/usr/bin/env python3
"""Compare native translucent regions with the pinned LunaSVG renderer."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter
from typing import Any

import numpy as np

import lumina_svg_core


def _anonymous_svg_paths(corpus_dir: Path) -> list[Path]:
    root = Path(corpus_dir)
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() == ".svg"
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _selected_ids(previous_report: Path) -> set[str]:
    report = json.loads(previous_report.read_text(encoding="utf-8"))
    return {
        str(document["anonymous_id"])
        for document in report["documents"]
        if document.get("reason_code") == "unsupported_partial_alpha"
    }


def _format_coordinate(value: float) -> str:
    return format(float(value), ".17g")


def _write_visible_svg(result: Any, destination: Path) -> None:
    bbox_width = float(result.bbox[2])
    bbox_height = float(result.bbox[3])
    coordinates = (
        np.asarray(result.visible.coordinates, dtype=np.float64)
        * float(result.grid_to_source_unit)
    )
    ring_offsets = np.asarray(result.visible.ring_offsets, dtype=np.uint64)
    polygon_offsets = np.asarray(
        result.visible.polygon_offsets, dtype=np.uint64
    )
    geometry_offsets = np.asarray(
        result.visible.geometry_offsets, dtype=np.uint64
    )
    rgba = np.asarray(result.visible.rgba, dtype=np.uint8)
    rgba_f64 = np.asarray(result.visible.rgba_f64, dtype=np.float64)

    with destination.open("w", encoding="utf-8", newline="\n") as output:
        output.write(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{_format_coordinate(bbox_width)}" '
            f'height="{_format_coordinate(bbox_height)}" '
            f'viewBox="0 0 {_format_coordinate(bbox_width)} '
            f'{_format_coordinate(bbox_height)}">\n'
        )
        for geometry_index in range(int(result.visible.geometry_count)):
            red, green, blue = (
                int(value) for value in rgba[geometry_index, :3]
            )
            alpha = float(rgba_f64[geometry_index, 3])
            output.write(
                f'<path fill="rgba({red},{green},{blue},'
                f'{_format_coordinate(alpha)})" '
                'fill-rule="evenodd" d="'
            )
            polygon_start = int(geometry_offsets[geometry_index])
            polygon_end = int(geometry_offsets[geometry_index + 1])
            for polygon_index in range(polygon_start, polygon_end):
                ring_start = int(polygon_offsets[polygon_index])
                ring_end = int(polygon_offsets[polygon_index + 1])
                for ring_index in range(ring_start, ring_end):
                    point_start = int(ring_offsets[ring_index])
                    point_end = int(ring_offsets[ring_index + 1])
                    ring = coordinates[point_start:point_end]
                    if len(ring) < 4:
                        continue
                    output.write(
                        f'M{_format_coordinate(ring[0, 0])} '
                        f'{_format_coordinate(ring[0, 1])}'
                    )
                    for point in ring[1:-1]:
                        output.write(
                            f'L{_format_coordinate(point[0])} '
                            f'{_format_coordinate(point[1])}'
                        )
                    output.write("Z")
            output.write('"/>\n')
        output.write("</svg>\n")


def _render_rgba(
    renderer: Path,
    svg_path: Path,
    output_path: Path,
    width: int,
    height: int,
    bbox: tuple[float, float, float, float],
) -> np.ndarray:
    completed = subprocess.run(
        [
            str(renderer),
            str(svg_path),
            str(output_path),
            str(width),
            str(height),
            *(_format_coordinate(value) for value in bbox),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if completed.returncode != 0:
        reason = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(reason or "raster_oracle_failed")
    pixels = np.fromfile(output_path, dtype=np.uint8)
    expected_size = width * height * 4
    if pixels.size != expected_size:
        raise RuntimeError("raster_oracle_size_mismatch")
    return pixels.reshape(height, width, 4)


def _transition_boundary(image: np.ndarray) -> np.ndarray:
    boundary = np.zeros(image.shape[:2], dtype=bool)
    horizontal = np.any(image[:, 1:] != image[:, :-1], axis=2)
    vertical = np.any(image[1:] != image[:-1], axis=2)
    boundary[:, 1:] |= horizontal
    boundary[:, :-1] |= horizontal
    boundary[1:] |= vertical
    boundary[:-1] |= vertical
    return boundary


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    result = mask.copy()
    for _ in range(radius):
        padded = np.pad(result, 1, mode="constant", constant_values=False)
        expanded = np.zeros_like(result)
        for y_offset in range(3):
            for x_offset in range(3):
                expanded |= padded[
                    y_offset : y_offset + result.shape[0],
                    x_offset : x_offset + result.shape[1],
                ]
        result = expanded
    return result


def _comparison(
    reference: np.ndarray,
    candidate: np.ndarray,
    boundary_exclusion_pixels: int,
) -> dict[str, Any]:
    boundary = _transition_boundary(reference) | _transition_boundary(
        candidate
    )
    excluded = _dilate(boundary, boundary_exclusion_pixels)
    interior = ~excluded
    absolute_error = np.abs(
        reference.astype(np.int16) - candidate.astype(np.int16)
    )
    reference_coverage = reference[:, :, 3] > 0
    candidate_coverage = candidate[:, :, 3] > 0
    interior_count = int(np.count_nonzero(interior))
    interior_coverage_disagreement = int(
        np.count_nonzero(
            (reference_coverage != candidate_coverage) & interior
        )
    )
    return {
        "compared_interior_pixel_count": interior_count,
        "excluded_boundary_pixel_count": int(np.count_nonzero(excluded)),
        "maximum_channel_error_u8": int(absolute_error.max(initial=0)),
        "maximum_interior_channel_error_u8": int(
            absolute_error[interior].max(initial=0)
        ),
        "interior_coverage_disagreement_pixel_count": (
            interior_coverage_disagreement
        ),
        "interior_coverage_disagreement_ratio": (
            interior_coverage_disagreement / interior_count
            if interior_count
            else 0.0
        ),
    }


def audit_alpha_rasters(
    corpus_dir: Path,
    previous_report: Path,
    renderer: Path,
    *,
    target_width_mm: float,
    tolerance_mm: float,
    maximum_dimension_pixels: int,
) -> dict[str, Any]:
    """Audit former alpha fallbacks against a transparent raster oracle.

    将曾因透明度回退的匿名 SVG 与透明画布光栅基准进行对照审计。

    Args:
        corpus_dir: Directory containing the private SVG corpus.
            私有 SVG 素材目录。
        previous_report: Anonymous report identifying former alpha fallbacks.
            用于定位旧透明度回退案例的匿名报告。
        renderer: Fixed-fork LunaSVG raster-oracle executable.
            固定 fork 的 LunaSVG 光栅基准程序。
        target_width_mm: Common physical width passed to the native parser.
            传给原生解析器的统一物理宽度。
        tolerance_mm: Shared physical boundary-error budget.
            统一物理边界误差预算。
        maximum_dimension_pixels: Long-edge raster resolution.
            光栅长边分辨率。

    Returns:
        Anonymous JSON-serializable differential evidence.
        不含源文件身份、可序列化为 JSON 的差分证据。
    """

    selected = _selected_ids(previous_report)
    documents: list[dict[str, Any]] = []
    started = perf_counter()
    with tempfile.TemporaryDirectory(
        prefix="lumina-native-svg-raster-audit-"
    ) as temporary_dir:
        temporary_root = Path(temporary_dir)
        for index, source_path in enumerate(
            _anonymous_svg_paths(corpus_dir), start=1
        ):
            anonymous_id = f"svg-{index:06d}"
            if anonymous_id not in selected:
                continue
            case_started = perf_counter()
            result = lumina_svg_core.analyze_svg(
                source_path,
                target_width_mm,
                tolerance_mm,
                True,
            )
            if result.status != "supported":
                documents.append(
                    {
                        "anonymous_id": anonymous_id,
                        "status": str(result.status),
                        "reason_code": str(result.reason_code),
                    }
                )
                continue

            bbox = tuple(float(value) for value in result.bbox)
            if bbox[2] >= bbox[3]:
                width = maximum_dimension_pixels
                height = max(1, int(round(width * bbox[3] / bbox[2])))
            else:
                height = maximum_dimension_pixels
                width = max(1, int(round(height * bbox[2] / bbox[3])))
            pixels_per_mm = width / target_width_mm
            boundary_exclusion_pixels = max(
                1, int(math.ceil(tolerance_mm * pixels_per_mm))
            )

            exported_svg = temporary_root / f"{anonymous_id}-visible.svg"
            reference_rgba = temporary_root / f"{anonymous_id}-source.rgba"
            candidate_rgba = temporary_root / f"{anonymous_id}-visible.rgba"
            _write_visible_svg(result, exported_svg)
            reference = _render_rgba(
                renderer,
                source_path,
                reference_rgba,
                width,
                height,
                bbox,
            )
            candidate = _render_rgba(
                renderer,
                exported_svg,
                candidate_rgba,
                width,
                height,
                (0.0, 0.0, bbox[2], bbox[3]),
            )
            comparison = _comparison(
                reference, candidate, boundary_exclusion_pixels
            )
            accepted = (
                comparison["maximum_interior_channel_error_u8"] <= 1
                and comparison[
                    "interior_coverage_disagreement_pixel_count"
                ]
                == 0
            )
            documents.append(
                {
                    "anonymous_id": anonymous_id,
                    "status": "matched" if accepted else "mismatch",
                    "reason_code": "" if accepted else "raster_mismatch",
                    "width_pixels": width,
                    "height_pixels": height,
                    "boundary_exclusion_pixels": (
                        boundary_exclusion_pixels
                    ),
                    **comparison,
                    "elapsed_seconds": perf_counter() - case_started,
                }
            )
            print(
                f"{anonymous_id} {documents[-1]['status']} "
                f"{documents[-1]['elapsed_seconds']:.3f}s",
                file=sys.stderr,
                flush=True,
            )

    matched_count = sum(
        document["status"] == "matched" for document in documents
    )
    missing_count = max(0, len(selected) - len(documents))
    return {
        "schema_version": 1,
        "settings": {
            "target_width_mm": target_width_mm,
            "tolerance_mm": tolerance_mm,
            "maximum_dimension_pixels": maximum_dimension_pixels,
            "canvas": "transparent_srgb",
            "maximum_interior_channel_error_u8": 1,
            "boundary_exclusion_rule": (
                "max(1, ceil(tolerance_mm * rendered_pixels_per_mm))"
            ),
        },
        "summary": {
            "selected_document_count": len(selected),
            "measured_document_count": len(documents),
            "matched_document_count": matched_count,
            "mismatch_document_count": sum(
                document["status"] == "mismatch"
                for document in documents
            ),
            "unsupported_document_count": sum(
                document["status"] not in {"matched", "mismatch"}
                for document in documents
            ),
            "missing_document_count": missing_count,
            "maximum_interior_channel_error_u8": max(
                (
                    int(
                        document.get(
                            "maximum_interior_channel_error_u8", 0
                        )
                    )
                    for document in documents
                ),
                default=0,
            ),
            "interior_coverage_disagreement_pixel_count": sum(
                int(
                    document.get(
                        "interior_coverage_disagreement_pixel_count", 0
                    )
                )
                for document in documents
            ),
        },
        "performance": {"total_seconds": perf_counter() - started},
        "documents": documents,
    }


def _report_passed(report: dict[str, Any]) -> bool:
    summary = report["summary"]
    selected = int(summary["selected_document_count"])
    measured = int(summary["measured_document_count"])
    matched = int(summary["matched_document_count"])
    return (
        selected == measured == matched
        and int(summary["mismatch_document_count"]) == 0
        and int(summary["unsupported_document_count"]) == 0
        and int(summary["missing_document_count"]) == 0
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--previous-report", type=Path, required=True)
    parser.add_argument("--renderer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-width-mm", type=float, default=100.0)
    parser.add_argument("--tolerance-mm", type=float, default=0.02)
    parser.add_argument(
        "--maximum-dimension-pixels", type=int, default=1024
    )
    args = parser.parse_args()
    report = audit_alpha_rasters(
        args.corpus,
        args.previous_report,
        args.renderer,
        target_width_mm=args.target_width_mm,
        tolerance_mm=args.tolerance_mm,
        maximum_dimension_pixels=args.maximum_dimension_pixels,
    )
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if _report_passed(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
