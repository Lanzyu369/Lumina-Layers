#!/usr/bin/env python3
"""Profile the lossless GEOS dense-buffer proof kernel."""

from __future__ import annotations

import hashlib

from shapely import normalize
from shapely.geometry.base import BaseGeometry


def _polygon_parts(geometry: BaseGeometry) -> list[BaseGeometry]:
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    return []


def geometry_fingerprint(geometry: BaseGeometry) -> dict[str, object]:
    """Return product-semantic geometry evidence.

    返回用于产品语义比对的几何证据。

    Args:
        geometry: Polygonal Shapely geometry to summarize.

    Returns:
        Stable structural fields plus a diagnostic normalized-WKB digest.
    """

    parts = _polygon_parts(geometry)
    normalized_wkb = normalize(geometry).wkb
    return {
        "valid": bool(geometry.is_valid),
        "geom_type": geometry.geom_type,
        "components": len(parts),
        "holes": sum(len(part.interiors) for part in parts),
        "area": float(geometry.area),
        "bounds": [float(value) for value in geometry.bounds],
        "normalized_wkb_sha256": hashlib.sha256(normalized_wkb).hexdigest(),
    }


def compare_geometry(
    stock: BaseGeometry,
    candidate: BaseGeometry,
) -> dict[str, object]:
    """Compare geometries using the material-region contract.

    按耗材区域不变的产品约束比较几何结果。

    Args:
        stock: Current production GEOS result.
        candidate: Candidate optimized GEOS result.

    Returns:
        Structural fingerprints and exact topological-difference evidence.
    """

    difference = stock.symmetric_difference(candidate)
    stock_fingerprint = geometry_fingerprint(stock)
    candidate_fingerprint = geometry_fingerprint(candidate)
    same_structure = all(
        stock_fingerprint[key] == candidate_fingerprint[key]
        for key in (
            "valid",
            "geom_type",
            "components",
            "holes",
            "area",
            "bounds",
        )
    )
    return {
        "pass": bool(difference.is_empty and same_structure),
        "symmetric_difference_empty": bool(difference.is_empty),
        "symmetric_difference_area": float(difference.area),
        "stock": stock_fingerprint,
        "candidate": candidate_fingerprint,
    }
