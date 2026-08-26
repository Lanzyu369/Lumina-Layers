"""Regression tests for non-manifold SVG Outline extrusion."""

from __future__ import annotations

from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Polygon, box

import core.pipeline.vector_branch as vector_branch
from core.errors import VectorTopologyError
from utils.bambu_3mf_writer import BambuStudio3MFWriter


def _edge_incidence_counts(mesh) -> np.ndarray:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    edges = np.concatenate(
        [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]],
        axis=0,
    )
    edges.sort(axis=1)
    _unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    return counts


def _point_touching_hole_polygon() -> Polygon:
    """Return a valid polygon whose two holes share one vertex."""

    angles = np.linspace(0.0, 2.0 * np.pi, 20, endpoint=False)
    large_hole = [(10.0 + 8.0 * np.cos(theta), 10.0 + 8.0 * np.sin(theta)) for theta in angles]
    contact = large_hole[0]
    small_hole = [contact, (25.0, 8.0), (25.0, 12.0), contact]
    polygon = Polygon(
        [(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)],
        [large_hole, small_hole],
    )
    assert polygon.is_valid
    return polygon


def _near_duplicate_boundary_polygon() -> Polygon:
    """Return a valid SVG-like ring with a sub-resolution repeated vertex."""

    return Polygon(
        [
            (2509.917435338203, 4623.051929933649),
            (2510.172565883122, 4623.021385042616),
            (2510.883578978562, 4623.157336359613),
            (2556.1858527699997, 4617.512555038293),
            (2509.9174353413346, 4623.05192992644),
            (2509.7519150970775, 4622.940953283469),
        ]
    )


def _outline_analysis() -> SimpleNamespace:
    return SimpleNamespace(
        matched_shapes=[{"geometry": box(-20.0, -20.0, -10.0, -10.0)}],
        scale_factor=1.0,
        bbox=(0.0, 0.0, 30.0, 30.0),
        num_layers=1,
    )


def _patch_ring(monkeypatch: pytest.MonkeyPatch, ring) -> None:
    """Make the public Outline helper consume a deterministic ring fixture."""

    disjoint_union = box(-20.0, -20.0, -10.0, -10.0)
    monkeypatch.setattr(
        vector_branch,
        "_vector_outline_union_geometry",
        lambda _matched_shapes: disjoint_union,
    )
    monkeypatch.setattr(
        vector_branch,
        "_clip_vector_outline_buffer_to_expected_bounds",
        lambda _expanded, _union, _width_units: ring,
    )


def _outline_context() -> dict:
    return {
        "spacer_thick": 1.0,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color RYBW",
        "enable_coating": False,
    }


def test_vector_outline_repairs_point_touching_holes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outline extrusion must not expose a 4/8-face edge at hole contact."""

    _patch_ring(monkeypatch, _point_touching_hole_polygon())

    outline = vector_branch._generate_vector_outline_mesh(
        analysis=_outline_analysis(),
        outline_width_mm=1.0,
        base_aux_color=[255, 255, 255, 255],
        base_aux_material_name="White",
        ctx=_outline_context(),
    )

    assert outline is not None
    counts = _edge_incidence_counts(outline)
    assert outline.is_watertight
    assert np.all(counts == 2)


def test_vector_outline_repairs_nonwatertight_simple_ring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid ring with near-duplicate boundary vertices must be closed."""

    _patch_ring(monkeypatch, _near_duplicate_boundary_polygon())

    outline = vector_branch._generate_vector_outline_mesh(
        analysis=_outline_analysis(),
        outline_width_mm=1.0,
        base_aux_color=[255, 255, 255, 255],
        base_aux_material_name="White",
        ctx=_outline_context(),
    )

    assert outline is not None
    assert outline.is_watertight
    counts = _edge_incidence_counts(outline)
    assert np.all(counts == 2)


def test_vector_outline_routes_extrusion_through_shared_topology_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outline keeps its closed-mesh contract through the shared service."""

    ring = box(0.0, 0.0, 10.0, 10.0).difference(box(2.0, 2.0, 8.0, 8.0))
    _patch_ring(monkeypatch, ring)
    calls = []
    original_extrude_polygon = vector_branch.trimesh.creation.extrude_polygon

    def fake_extrude_polygon_for_export(poly, *, xy_scale, prefer_fast):
        calls.append((poly, xy_scale, prefer_fast))
        mesh = original_extrude_polygon(poly, height=1.0)
        mesh.metadata["topology_service_marker"] = "outline"
        return [mesh]

    monkeypatch.setattr(
        vector_branch,
        "extrude_polygon_for_export",
        fake_extrude_polygon_for_export,
    )

    outline = vector_branch._generate_vector_outline_mesh(
        analysis=_outline_analysis(),
        outline_width_mm=1.0,
        base_aux_color=[255, 255, 255, 255],
        base_aux_material_name="White",
        ctx=_outline_context(),
    )

    assert len(calls) == 1
    assert calls[0][0].equals(ring)
    assert calls[0][1] == pytest.approx(1.0)
    assert calls[0][2] is True
    assert outline is not None
    assert outline.is_watertight
    assert np.all(_edge_incidence_counts(outline) == 2)
    assert outline.metadata["topology_service_marker"] == "outline"


def test_vector_outline_rejects_shared_topology_service_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outline rejects a shared-service failure instead of retrying legacy extrusion."""

    ring = box(0.0, 0.0, 10.0, 10.0).difference(box(2.0, 2.0, 8.0, 8.0))
    _patch_ring(monkeypatch, ring)
    service_calls = []

    def fail_shared_topology_service(*_args, **_kwargs):
        service_calls.append(True)
        raise VectorTopologyError(
            "Vector polygon topology could not be repaired for export",
            ({"attempt": "repair_0.001_mm"},),
        )

    monkeypatch.setattr(
        vector_branch,
        "extrude_polygon_for_export",
        fail_shared_topology_service,
    )

    outline = vector_branch._generate_vector_outline_mesh(
        analysis=_outline_analysis(),
        outline_width_mm=1.0,
        base_aux_color=[255, 255, 255, 255],
        base_aux_material_name="White",
        ctx=_outline_context(),
    )

    assert service_calls == [True]
    assert outline is None


def test_vector_outline_survives_float32_writer_weld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outline topology must remain valid at the writer's float32 boundary."""

    _patch_ring(monkeypatch, _near_duplicate_boundary_polygon())

    outline = vector_branch._generate_vector_outline_mesh(
        analysis=_outline_analysis(),
        outline_width_mm=1.0,
        base_aux_color=[255, 255, 255, 255],
        base_aux_material_name="White",
        ctx=_outline_context(),
    )

    assert outline is not None
    vertices = np.asarray(outline.vertices, dtype=np.float64)
    faces = np.asarray(outline.faces, dtype=np.int64)
    writer_vertices = vertices.astype(np.float32)
    _unique_vertices, inverse = np.unique(
        writer_vertices,
        axis=0,
        return_inverse=True,
    )
    writer_faces = inverse[faces]
    assert not np.any(
        (writer_faces[:, 0] == writer_faces[:, 1])
        | (writer_faces[:, 1] == writer_faces[:, 2])
        | (writer_faces[:, 2] == writer_faces[:, 0])
    )
    counts = _edge_incidence_counts(
        vector_branch.trimesh.Trimesh(
            vertices=writer_vertices,
            faces=writer_faces,
            process=False,
        )
    )
    assert np.all(counts == 2)


def test_vector_outline_rejects_failed_piece_instead_of_partial_ring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrepaired piece must reject the complete Outline, not disappear."""

    bad_piece = _point_touching_hole_polygon()
    ring = MultiPolygon(
        [
            box(40.0, 0.0, 45.0, 5.0),
            bad_piece,
        ]
    )
    _patch_ring(monkeypatch, ring)

    original_extrude = vector_branch.extrude_polygon_for_export

    def fail_suspicious_polygon(poly, *, xy_scale, prefer_fast):
        if getattr(poly, "interiors", ()):
            raise ValueError("synthetic topology service failure")
        return original_extrude(
            poly,
            xy_scale=xy_scale,
            prefer_fast=prefer_fast,
        )

    monkeypatch.setattr(
        vector_branch,
        "extrude_polygon_for_export",
        fail_suspicious_polygon,
    )

    outline = vector_branch._generate_vector_outline_mesh(
        analysis=_outline_analysis(),
        outline_width_mm=1.0,
        base_aux_color=[255, 255, 255, 255],
        base_aux_material_name="White",
        ctx=_outline_context(),
    )

    assert outline is None


def test_outline_component_separation_survives_writer_coordinate_mapping() -> None:
    """Independent Outline shells must stay distinct after 3MF rounding."""

    left = box(0.0, 0.0, 1.0, 1.0)
    right = box(1.0, 0.0, 2.0, 1.0)
    meshes = [
        vector_branch.trimesh.creation.extrude_polygon(left, height=1.0),
        vector_branch.trimesh.creation.extrude_polygon(right, height=1.0),
    ]

    assert vector_branch.separate_component_coordinates(meshes)

    vertices = np.vstack([np.asarray(mesh.vertices) for mesh in meshes])
    faces = []
    offset = 0
    for mesh in meshes:
        faces.append(np.asarray(mesh.faces, dtype=np.int64) + offset)
        offset += len(mesh.vertices)
    faces = np.vstack(faces)

    # ``neroued_3mf`` narrows vertices to float32, then the package writer
    # serializes the result with its compact six-decimal XML precision.
    writer_vertices = np.round(
        vertices.astype(np.float32).astype(np.float64),
        decimals=6,
    )
    _unique_vertices, inverse = np.unique(
        writer_vertices,
        axis=0,
        return_inverse=True,
    )
    remapped_faces = inverse[faces]
    assert not np.any(
        (remapped_faces[:, 0] == remapped_faces[:, 1])
        | (remapped_faces[:, 1] == remapped_faces[:, 2])
        | (remapped_faces[:, 2] == remapped_faces[:, 0])
    )
    counts = _edge_incidence_counts(
        vector_branch.trimesh.Trimesh(
            vertices=writer_vertices,
            faces=remapped_faces,
            process=False,
        )
    )
    assert np.all(counts == 2)


def test_outline_component_separation_survives_bed_scale_3mf_export(
    tmp_path,
) -> None:
    """The writer must preserve separate shells at bed-scale coordinates."""

    meshes = [
        vector_branch.trimesh.creation.extrude_polygon(
            box(180.0, 245.0, 181.0, 246.0),
            height=1.0,
        ),
        vector_branch.trimesh.creation.extrude_polygon(
            box(181.0, 245.0, 182.0, 246.0),
            height=1.0,
        ),
    ]
    assert vector_branch.separate_component_coordinates(meshes)
    outline = vector_branch.trimesh.util.concatenate(meshes)

    output_path = tmp_path / "outline.3mf"
    writer = BambuStudio3MFWriter(
        str(output_path),
        settings={},
        color_mode="4-Color RYBW",
    )
    writer.add_mesh(outline, "Outline", (255, 255, 255))
    writer.export()

    with ZipFile(output_path) as archive:
        root = ET.fromstring(archive.read("3D/Objects/object_1.model"))
    namespace = {"m": root.tag[root.tag.find("{") + 1 : root.tag.find("}")]}
    outline_object = next(
        item
        for item in root.findall(".//m:resources/m:object", namespace)
        if item.attrib.get("name") == "Outline"
    )
    vertices = np.asarray(
        [
            (
                float(node.attrib["x"]),
                float(node.attrib["y"]),
                float(node.attrib["z"]),
            )
            for node in outline_object.findall("./m:mesh/m:vertices/m:vertex", namespace)
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [
            (
                int(node.attrib["v1"]),
                int(node.attrib["v2"]),
                int(node.attrib["v3"]),
            )
            for node in outline_object.findall("./m:mesh/m:triangles/m:triangle", namespace)
        ],
        dtype=np.int64,
    )
    _unique_vertices, inverse = np.unique(vertices, axis=0, return_inverse=True)
    remapped_faces = inverse[faces]

    assert not np.any(
        (remapped_faces[:, 0] == remapped_faces[:, 1])
        | (remapped_faces[:, 1] == remapped_faces[:, 2])
        | (remapped_faces[:, 2] == remapped_faces[:, 0])
    )
    exported = vector_branch.trimesh.Trimesh(
        vertices=vertices,
        faces=remapped_faces,
        process=False,
    )
    assert np.all(_edge_incidence_counts(exported) == 2)
