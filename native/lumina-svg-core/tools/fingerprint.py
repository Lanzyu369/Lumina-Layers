"""Deterministic fingerprint and summary for native SVG analysis results."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

import numpy as np

import lumina_svg_core


ARRAY_FIELDS = (
    "coordinates",
    "ring_offsets",
    "polygon_offsets",
    "geometry_offsets",
    "hole_parent",
    "rgba",
    "rgba_f64",
    "draw_indices",
    "source_indices",
    "source_kinds",
    "contributor_offsets",
    "contributor_draw_indices",
    "contributor_source_indices",
    "contributor_source_kinds",
    "contributor_weights",
)


def _stable_array_bytes(array: np.ndarray) -> bytes:
    dtype = array.dtype.newbyteorder("<")
    return np.ascontiguousarray(array.astype(dtype, copy=False)).tobytes()


def result_fingerprint(result: Any) -> str:
    digest = hashlib.sha256()
    digest.update(struct.pack("<I", result.schema_version))
    digest.update(result.status.encode("utf-8") + b"\0")
    digest.update(result.reason_code.encode("utf-8") + b"\0")
    digest.update(struct.pack("<4d", *(round(value, 9) for value in result.bbox)))
    digest.update(
        struct.pack(
            "<4d",
            round(result.scale_factor, 12),
            round(result.grid_to_source_unit, 12),
            round(result.max_flattening_error_mm, 12),
            round(result.max_quantization_error_mm, 12),
        )
    )
    for collection_name in ("raw", "visible", "silhouette"):
        digest.update(collection_name.encode("ascii") + b"\0")
        collection = getattr(result, collection_name)
        for field in ARRAY_FIELDS:
            array = getattr(collection, field)
            digest.update(field.encode("ascii") + b"\0")
            digest.update(struct.pack("<I", array.ndim))
            digest.update(struct.pack(f"<{array.ndim}Q", *array.shape))
            digest.update(array.dtype.newbyteorder("<").str.encode("ascii") + b"\0")
            digest.update(_stable_array_bytes(array))
    return digest.hexdigest()


def _geometry_area(result: Any, collection: Any, geometry_index: int) -> float:
    area = 0.0
    polygon_start = collection.geometry_offsets[geometry_index]
    polygon_end = collection.geometry_offsets[geometry_index + 1]
    for polygon_index in range(polygon_start, polygon_end):
        ring_start = collection.polygon_offsets[polygon_index]
        ring_end = collection.polygon_offsets[polygon_index + 1]
        for ring_index in range(ring_start, ring_end):
            point_start = collection.ring_offsets[ring_index]
            point_end = collection.ring_offsets[ring_index + 1]
            ring = collection.coordinates[point_start:point_end].astype(
                np.float64
            )
            area += 0.5 * float(
                np.sum(
                    ring[:-1, 0] * ring[1:, 1]
                    - ring[1:, 0] * ring[:-1, 1]
                )
            )
    return abs(area) * result.grid_to_source_unit**2


def result_summary(result: Any) -> dict[str, Any]:
    visible = result.visible
    area_by_rgba: dict[str, float] = {}
    ordered_rgba: list[list[int]] = []
    for geometry_index, color in enumerate(visible.rgba.tolist()):
        ordered_rgba.append(color)
        key = "-".join(str(channel) for channel in color)
        area_by_rgba[key] = area_by_rgba.get(key, 0.0) + _geometry_area(
            result, visible, geometry_index
        )
    return {
        "status": result.status,
        "reason_code": result.reason_code,
        "bbox": [round(value, 9) for value in result.bbox],
        "ordered_rgba": ordered_rgba,
        "raw_components": result.raw.component_count,
        "visible_components": visible.component_count,
        "visible_holes": visible.hole_count,
        "area_by_rgba": {
            key: round(value, 6) for key, value in sorted(area_by_rgba.items())
        },
        "fingerprint": result_fingerprint(result),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("svg", type=Path)
    parser.add_argument("--target-width-mm", type=float, default=100.0)
    parser.add_argument("--tolerance-mm", type=float, default=0.02)
    args = parser.parse_args()
    result = lumina_svg_core.analyze_svg(
        args.svg, args.target_width_mm, args.tolerance_mm
    )
    summary = result_summary(result)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
