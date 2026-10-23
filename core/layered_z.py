"""Explicit physical layer boundaries for compact raster label planes."""

from __future__ import annotations

import numpy as np


def validate_layer_z_edges(z_edges: object, plane_count: int) -> np.ndarray:
    """Validate integer layer coordinates without silently rounding a schedule."""
    values = np.asarray(z_edges)
    maximum = np.iinfo(np.int64).max // 2
    if (
        values.shape != (plane_count + 1,)
        or values.dtype.kind not in "iuf"
        or not np.all(np.isfinite(values))
        or np.any(values < 0)
        or np.any(values > maximum)
        or np.any(values != np.floor(values))
    ):
        raise ValueError("Z edges must contain one finite integer boundary per label plane plus one.")
    edges = values.astype(np.int64)
    if edges[0] != 0 or np.any(edges[1:] <= edges[:-1]) or np.any(edges > maximum):
        raise ValueError("Z edges must start at zero and strictly increase.")
    return edges


def map_doubled_layer_z(doubled_positions: np.ndarray, z_edges: np.ndarray) -> np.ndarray:
    """Map exact integer/half-integer indices before float32 materialization."""
    positions = np.asarray(doubled_positions, dtype=np.int64)
    if np.any(positions < 0) or np.any(positions > 2 * (len(z_edges) - 1)):
        raise ValueError("Mesh vertices left the compact Z layer lattice.")
    lower = positions // 2
    mapped = 2 * z_edges[lower]
    half = positions % 2 == 1
    mapped[half] = z_edges[lower[half]] + z_edges[lower[half] + 1]
    return mapped
