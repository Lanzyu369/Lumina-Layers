"""Regression tests for mesh vertex welding at shape borders.

Covers the fix where ``VectorProcessor.build_mesh`` pipes the concatenated
per-slot mesh through ``Trimesh.merge_vertices`` so that coincident border
vertices (produced by independent per-shape ``_extrude_geometry`` calls on
neighbouring Shapely polygons) are welded.

Without welding, Three.js and most triangle-based renderers compute per-face
normals on two touching but vertex-disjoint surfaces, producing the visible
"spikes / fragments" users reported on stroke-heavy or multi-path SVGs
(e.g. ``test_images/1 (1).svg``).
"""
from __future__ import annotations

import numpy as np
import pytest
import trimesh
from scipy.spatial import cKDTree
from shapely.geometry import box

from core.vector_engine import VectorProcessor


def _coincident_pair_count(mesh: trimesh.Trimesh, tol: float = 1e-6) -> int:
    """Count vertex pairs within *tol* mm — i.e. would be welded together."""
    if mesh.vertices.shape[0] < 2:
        return 0
    tree = cKDTree(mesh.vertices)
    pairs = tree.query_pairs(r=tol, output_type="ndarray")
    return int(pairs.shape[0])


class TestBuildMeshVertexWelding:
    """Validate the root cause and the fix at ``build_mesh``'s concat boundary."""

    @staticmethod
    def _two_adjacent_extrusions() -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
        """Build two boxes that share the edge x=5 (so six vertex pairs coincide
        along the border after extrusion)."""
        left = box(0.0, 0.0, 5.0, 5.0)
        right = box(5.0, 0.0, 10.0, 5.0)
        extrude = VectorProcessor._extrude_geometry
        left_meshes = extrude(left, height=1.0, z_offset=0.0, scale=1.0)
        right_meshes = extrude(right, height=1.0, z_offset=0.0, scale=1.0)
        assert left_meshes and right_meshes, "extrude_polygon returned empty mesh list"
        return left_meshes[0], right_meshes[0]

    def test_adjacent_shapes_produce_coincident_vertices(self):
        """Precondition: two adjacent extruded boxes share coincident border
        vertices that ``trimesh.util.concatenate`` does NOT weld."""
        left_mesh, right_mesh = self._two_adjacent_extrusions()
        combined = trimesh.util.concatenate([left_mesh, right_mesh])
        coincident = _coincident_pair_count(combined, tol=1e-9)
        assert coincident >= 4, (
            "Adjacent shapes should leave at least one coincident vertex pair "
            "per shared border corner; concatenate() must not weld them "
            "implicitly (if this fails, trimesh API semantics changed)."
        )

    def test_merge_vertices_welds_coincident_border(self):
        """``merge_vertices`` must eliminate the coincident pairs that caused
        Three.js to render visible seams at shape borders."""
        left_mesh, right_mesh = self._two_adjacent_extrusions()
        combined = trimesh.util.concatenate([left_mesh, right_mesh])
        v_before = int(combined.vertices.shape[0])
        combined.merge_vertices()
        v_after = int(combined.vertices.shape[0])
        assert v_after < v_before, (
            "merge_vertices must reduce the vertex count when adjacent shapes "
            "produced coincident border vertices"
        )
        remaining = _coincident_pair_count(combined, tol=1e-9)
        assert remaining == 0, (
            f"After merge_vertices the mesh must contain no coincident "
            f"vertex pairs, got {remaining}"
        )

    def test_build_mesh_call_site_includes_merge_vertices(self):
        """Governance: the fix in ``build_mesh`` must not regress by removing
        the ``merge_vertices`` call after ``trimesh.util.concatenate``."""
        import inspect

        source = inspect.getsource(VectorProcessor.build_mesh)
        concat_idx = source.find("trimesh.util.concatenate")
        assert concat_idx >= 0, "build_mesh no longer uses trimesh.util.concatenate"
        merge_idx = source.find("merge_vertices", concat_idx)
        assert merge_idx >= 0, (
            "build_mesh must call merge_vertices() after concatenate() so "
            "coincident border vertices are welded before the scene is "
            "handed to Three.js / exporters"
        )


def test_merge_vertices_preserves_volume_of_disjoint_parts():
    """Sanity guard: merging vertices must not collapse geometrically
    disjoint parts (boxes more than 1mm apart)."""
    far_left = box(0.0, 0.0, 1.0, 1.0)
    far_right = box(10.0, 0.0, 11.0, 1.0)
    extrude = VectorProcessor._extrude_geometry
    left = extrude(far_left, height=1.0, z_offset=0.0, scale=1.0)[0]
    right = extrude(far_right, height=1.0, z_offset=0.0, scale=1.0)[0]
    combined = trimesh.util.concatenate([left, right])
    vol_before = float(combined.volume)
    combined.merge_vertices()
    vol_after = float(combined.volume)
    assert vol_after == pytest.approx(vol_before, rel=1e-6, abs=1e-6)
