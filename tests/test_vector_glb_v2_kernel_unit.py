"""Unit tests for SVG/vector GLB preview V2 descriptor dispatch."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest
import numpy as np
import trimesh
from shapely.geometry import box
from shapely.ops import unary_union

from core.pipeline import vector_glb_preview


@pytest.fixture
def vector_glb_caplog(caplog):
    target = logging.getLogger("lumina.core.pipeline.vector_glb_preview")
    target.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        target.removeHandler(caplog.handler)


def _record_events(caplog) -> list[str | None]:
    return [getattr(record, "event", None) for record in caplog.records]


def _box_mesh(z_min: float = 0.0, z_max: float = 0.4) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=(2.0, 2.0, z_max - z_min))
    mesh.apply_translation((0.0, 0.0, (z_min + z_max) / 2.0))
    return mesh


def _load_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    magic, _version, _length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67
    chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
    assert chunk_type == 0x4E4F534A
    chunk = data[20 : 20 + chunk_length]
    return json.loads(chunk.decode("utf-8").rstrip("\x00 "))


def _load_glb_json_and_bin(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    magic, _version, _length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67
    json_length, json_type = struct.unpack_from("<II", data, 12)
    assert json_type == 0x4E4F534A
    json_chunk = data[20 : 20 + json_length]
    tree = json.loads(json_chunk.decode("utf-8").rstrip("\x00 "))
    bin_header = 20 + json_length
    bin_length, bin_type = struct.unpack_from("<II", data, bin_header)
    assert bin_type == 0x004E4942
    bin_start = bin_header + 8
    return tree, data[bin_start : bin_start + bin_length]


def _analysis_for_v2_test() -> SimpleNamespace:
    return SimpleNamespace(
        matched_shapes=[
            {"geometry": box(0, 0, 8, 8), "recipe": [0, 0, 1, 1]},
            {"geometry": box(8, 0, 16, 8), "recipe": [1, 1, 1, 1]},
        ],
        silhouette=box(0, 0, 16, 8),
        scale_factor=1.0,
        bbox=(0, 0, 16, 8),
        slot_names=["White", "Red"],
        num_channels=2,
        num_layers=4,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
            "White": [255, 255, 255, 255],
            "Red": [255, 0, 0, 255],
            "Board": [240, 240, 240, 255],
            "Outline": [20, 20, 20, 255],
        },
    )


def test_vector_glb_kernel_defaults_to_v1(monkeypatch) -> None:
    monkeypatch.delenv("LUMINA_VECTOR_GLB_KERNEL", raising=False)

    assert vector_glb_preview.resolve_vector_glb_kernel_choice() == "trimesh_v1"


def test_vector_glb_kernel_accepts_v2_aliases(monkeypatch) -> None:
    for value in ("v2", "V2", "rasterio_manifold3d", "rasterio+manifold3d"):
        monkeypatch.setenv("LUMINA_VECTOR_GLB_KERNEL", value)

        assert (
            vector_glb_preview.resolve_vector_glb_kernel_choice()
            == "rasterio_manifold3d"
        )


def test_vector_glb_kernel_unknown_value_warns_and_falls_back(
    monkeypatch,
    vector_glb_caplog,
) -> None:
    vector_glb_caplog.set_level(
        logging.WARNING,
        logger="lumina.core.pipeline.vector_glb_preview",
    )
    monkeypatch.setenv("LUMINA_VECTOR_GLB_KERNEL", "bad-value")

    assert vector_glb_preview.resolve_vector_glb_kernel_choice() == "trimesh_v1"

    assert "vector_glb_kernel_unknown_value" in _record_events(vector_glb_caplog)


def test_make_export_name_keeps_color_prefix_and_suffixes_duplicates() -> None:
    seen: set[str] = set()

    first = vector_glb_preview.make_vector_glb_export_name(
        source_name="Red",
        role="color",
        rgba=(255, 0, 0, 255),
        seen_names=seen,
    )
    second = vector_glb_preview.make_vector_glb_export_name(
        source_name="AlsoRed",
        role="color",
        rgba=(255, 0, 0, 255),
        seen_names=seen,
    )

    assert first == "color_ff0000"
    assert second == "color_ff0000_1"


def test_make_export_name_keeps_non_color_roles_out_of_color_prefix() -> None:
    seen: set[str] = set()

    assert (
        vector_glb_preview.make_vector_glb_export_name(
            source_name="Board",
            role="backing",
            rgba=(255, 255, 255, 255),
            seen_names=seen,
        )
        == "backing_plate"
    )

    assert (
        vector_glb_preview.make_vector_glb_export_name(
            source_name="Outline",
            role="outline",
            rgba=(255, 255, 255, 255),
            seen_names=seen,
        )
        == "Outline"
    )


def test_v1_exporter_writes_color_and_backing_names(tmp_path: Path) -> None:
    parts = [
        vector_glb_preview.VectorPreviewPart(
            source_name="Red",
            export_name="color_ff0000",
            role="color",
            rgba=(255, 0, 0, 255),
            is_recolorable=True,
            fallback_mesh=_box_mesh(),
        ),
        vector_glb_preview.VectorPreviewPart(
            source_name="Board",
            export_name="backing_plate",
            role="backing",
            rgba=(255, 255, 255, 255),
            is_recolorable=False,
            fallback_mesh=_box_mesh(-0.2, 0.0),
        ),
    ]

    out_path = tmp_path / "preview.glb"
    result = vector_glb_preview.export_vector_glb_preview_v1(
        parts,
        output_path=str(out_path),
    )

    assert result == str(out_path)
    loaded = trimesh.load(out_path, force="scene")
    names = set(loaded.geometry.keys())
    assert "color_ff0000" in names
    assert "backing_plate" in names


def test_build_parts_from_display_scene_classifies_roles_and_colors() -> None:
    scene = trimesh.Scene()
    scene.add_geometry(_box_mesh(), geom_name="Red")
    scene.add_geometry(_box_mesh(), geom_name="Board")
    scene.add_geometry(_box_mesh(), geom_name="Outline")

    parts = vector_glb_preview.build_vector_preview_parts_from_scene(
        scene=scene,
        preview_colors={
            "Red": [255, 0, 0, 255],
            "Board": [255, 255, 255, 255],
            "Outline": [10, 10, 10, 255],
        },
        slot_list=["Red", "Board"],
    )

    by_source = {part.source_name: part for part in parts}
    assert by_source["Red"].role == "color"
    assert by_source["Red"].export_name == "color_ff0000"
    assert by_source["Red"].is_recolorable is True
    assert by_source["Board"].role == "backing"
    assert by_source["Board"].export_name == "backing_plate"
    assert by_source["Outline"].role == "outline"
    assert by_source["Outline"].export_name == "Outline"


def test_build_parts_from_display_scene_preserves_auxiliary_business_geometry() -> None:
    scene = trimesh.Scene()
    keychain_mesh = _box_mesh()
    magnet_mesh = _box_mesh()
    coating_mesh = _box_mesh()
    scene.add_geometry(keychain_mesh, geom_name="KeychainLoop")
    scene.add_geometry(magnet_mesh, geom_name="FridgeCavityBoard")
    scene.add_geometry(coating_mesh, geom_name="CoatingShell")

    parts = vector_glb_preview.build_vector_preview_parts_from_scene(
        scene=scene,
        preview_colors={
            "KeychainLoop": [40, 40, 40, 255],
            "FridgeCavityBoard": [240, 240, 240, 255],
            "CoatingShell": [220, 220, 255, 128],
        },
        slot_list=["White", "Red", "Blue"],
        copy_fallback_mesh=False,
    )

    by_source = {part.source_name: part for part in parts}
    for source_name in ("KeychainLoop", "FridgeCavityBoard", "CoatingShell"):
        part = by_source[source_name]
        assert part.role == "auxiliary"
        assert part.export_name == source_name
        assert not part.export_name.startswith("color_")
        assert part.fallback_mesh is scene.geometry[source_name]


def test_build_parts_from_analysis_creates_color_backing_and_outline_parts() -> None:
    analysis = _analysis_for_v2_test()

    parts = vector_glb_preview.build_vector_preview_parts_from_analysis(
        analysis=analysis,
        preview_colors=dict(analysis.preview_colors),
        slot_list=list(analysis.slot_names),
        structure_mode="Single-sided",
        color_mode="4-Color (RYBW)",
        thickness_mm=1.6,
        separate_backing=True,
        include_backing=True,
        include_outline=True,
        outline_width_mm=2.0,
    )

    names = {part.export_name for part in parts}
    assert "color_ffffff" in names
    assert "color_ff0000" in names
    assert "backing_plate" in names
    assert "Outline" in names
    assert all(not part.export_name.startswith("color_") for part in parts if part.role != "color")
    assert all(
        extrusion.z_max > extrusion.z_min
        for part in parts
        for extrusion in part.extrusions
    )


def test_export_dispatch_defaults_to_v1(monkeypatch, tmp_path: Path) -> None:
    scene = trimesh.Scene()
    scene.add_geometry(_box_mesh(), geom_name="Red")
    calls: list[str] = []

    def fake_v1(parts, *, output_path):
        assert parts[0].export_name == "color_ff0000"
        calls.append("v1")
        Path(output_path).write_bytes(b"glb")
        return output_path

    def fail_v2(*_args, **_kwargs):
        raise AssertionError("v2 should not run by default")

    monkeypatch.delenv("LUMINA_VECTOR_GLB_KERNEL", raising=False)
    monkeypatch.setattr(vector_glb_preview, "export_vector_glb_preview_v1", fake_v1)
    monkeypatch.setattr(vector_glb_preview, "export_vector_glb_preview_v2", fail_v2)

    result = vector_glb_preview.export_vector_glb_preview(
        scene=scene,
        output_path=str(tmp_path / "preview.glb"),
        structure_mode="Double-sided",
        color_mode="4-Color (RYBW)",
        preview_colors={"Red": [255, 0, 0, 255]},
        slot_list=["Red"],
        analysis=_analysis_for_v2_test(),
        ctx={"spacer_thick": 1.6},
    )

    assert result.endswith("preview.glb")
    assert calls == ["v1"]


def test_export_dispatch_v2_uses_scene_reuse_exporter(monkeypatch, tmp_path: Path) -> None:
    scene = trimesh.Scene()
    scene.add_geometry(_box_mesh(), geom_name="Red")
    calls: list[str] = []

    def fake_scene_reuse(parts, *, output_path):
        assert parts[0].export_name == "color_ff0000"
        calls.append("scene_reuse")
        Path(output_path).write_bytes(b"glb")
        return output_path

    def fail_v2(*_args, **_kwargs):
        raise AssertionError("descriptor v2 should not run before scene-reuse export")

    def fail_v1(*_args, **_kwargs):
        raise AssertionError("v1 should not run when v2 succeeds")

    monkeypatch.setenv("LUMINA_VECTOR_GLB_KERNEL", "v2")
    monkeypatch.setattr(
        vector_glb_preview,
        "export_vector_glb_preview_v2_scene_reuse",
        fake_scene_reuse,
    )
    monkeypatch.setattr(vector_glb_preview, "export_vector_glb_preview_v2", fail_v2)
    monkeypatch.setattr(vector_glb_preview, "export_vector_glb_preview_v1", fail_v1)

    result = vector_glb_preview.export_vector_glb_preview(
        scene=scene,
        output_path=str(tmp_path / "preview.glb"),
        structure_mode="Double-sided",
        color_mode="4-Color (RYBW)",
        preview_colors=dict(_analysis_for_v2_test().preview_colors),
        slot_list=["White", "Red"],
        analysis=_analysis_for_v2_test(),
        ctx={"spacer_thick": 1.6},
    )

    assert result.endswith("preview.glb")
    assert calls == ["scene_reuse"]


def test_export_dispatch_v2_prepares_scene_reuse_without_intermediate_mesh_copy(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_mesh = _box_mesh()
    scene = trimesh.Scene()
    scene.add_geometry(source_mesh, geom_name="Red")
    captured_meshes: list[trimesh.Trimesh] = []

    def fail_copy(_mesh):
        raise AssertionError("v2 dispatch should not copy scene meshes before scene-reuse export")

    def fake_scene_reuse(parts, *, output_path):
        captured_meshes.append(parts[0].fallback_mesh)
        Path(output_path).write_bytes(b"glb")
        return output_path

    monkeypatch.setenv("LUMINA_VECTOR_GLB_KERNEL", "v2")
    monkeypatch.setattr(vector_glb_preview, "_mesh_geometry_only_copy", fail_copy)
    monkeypatch.setattr(
        vector_glb_preview,
        "export_vector_glb_preview_v2_scene_reuse",
        fake_scene_reuse,
    )

    result = vector_glb_preview.export_vector_glb_preview(
        scene=scene,
        output_path=str(tmp_path / "preview.glb"),
        structure_mode="Double-sided",
        color_mode="4-Color (RYBW)",
        preview_colors=dict(_analysis_for_v2_test().preview_colors),
        slot_list=["White", "Red"],
        analysis=_analysis_for_v2_test(),
        ctx={"spacer_thick": 1.6},
    )

    assert result.endswith("preview.glb")
    assert captured_meshes == [source_mesh]


def test_export_dispatch_v2_failure_falls_back_to_v1(
    monkeypatch,
    tmp_path: Path,
    vector_glb_caplog,
) -> None:
    scene = trimesh.Scene()
    scene.add_geometry(_box_mesh(), geom_name="Red")
    calls: list[str] = []
    vector_glb_caplog.set_level(
        logging.WARNING,
        logger="lumina.core.pipeline.vector_glb_preview",
    )

    def raise_scene_reuse(*_args, **_kwargs):
        calls.append("scene_reuse")
        raise RuntimeError("forced v2 failure")

    def fake_v1(parts, *, output_path):
        assert parts[0].export_name == "color_ff0000"
        calls.append("v1")
        Path(output_path).write_bytes(b"glb")
        return output_path

    monkeypatch.setenv("LUMINA_VECTOR_GLB_KERNEL", "v2")
    monkeypatch.setattr(
        vector_glb_preview,
        "export_vector_glb_preview_v2_scene_reuse",
        raise_scene_reuse,
    )
    monkeypatch.setattr(vector_glb_preview, "export_vector_glb_preview_v1", fake_v1)

    result = vector_glb_preview.export_vector_glb_preview(
        scene=scene,
        output_path=str(tmp_path / "preview.glb"),
        structure_mode="Double-sided",
        color_mode="4-Color (RYBW)",
        preview_colors={"Red": [255, 0, 0, 255]},
        slot_list=["Red"],
        analysis=_analysis_for_v2_test(),
        ctx={"spacer_thick": 1.6},
    )

    assert result.endswith("preview.glb")
    assert calls == ["scene_reuse", "v1"]
    assert "vector_glb_v2_runtime_fallback" in _record_events(vector_glb_caplog)


def test_v2_scene_reuse_export_uses_material_color_and_quantization(
    tmp_path: Path,
) -> None:
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        fallback_mesh=_box_mesh(),
    )
    out_path = tmp_path / "scene-reuse-v2.glb"

    result = vector_glb_preview.export_vector_glb_preview_v2_scene_reuse(
        [part],
        output_path=str(out_path),
    )

    assert result == str(out_path)
    gltf = _load_glb_json(out_path)
    assert "KHR_mesh_quantization" in set(gltf.get("extensionsUsed", []))
    primitive = gltf["meshes"][0]["primitives"][0]
    assert "COLOR_0" not in primitive["attributes"]
    position_accessor = gltf["accessors"][primitive["attributes"]["POSITION"]]
    assert position_accessor["componentType"] == vector_glb_preview._GLTF_UINT16_COMPONENT_TYPE
    material = gltf["materials"][primitive["material"]]
    assert material["pbrMetallicRoughness"]["baseColorFactor"] == [
        1.0,
        0.0,
        0.0,
        1.0,
    ]


def test_v2_scene_reuse_export_sorts_quantized_position_buffer(
    tmp_path: Path,
) -> None:
    vertices = np.asarray(
        [
            [10.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [5.0, 0.0, 0.0],
        ],
        dtype=np.float64,
    )
    faces = np.asarray([[0, 1, 2]], dtype=np.int64)
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        fallback_mesh=trimesh.Trimesh(vertices=vertices, faces=faces, process=False),
    )

    out_path = tmp_path / "scene-reuse-v2.glb"
    vector_glb_preview.export_vector_glb_preview_v2_scene_reuse(
        [part],
        output_path=str(out_path),
    )

    gltf, bin_chunk = _load_glb_json_and_bin(out_path)
    primitive = gltf["meshes"][0]["primitives"][0]
    position_accessor = gltf["accessors"][primitive["attributes"]["POSITION"]]
    position_view = gltf["bufferViews"][position_accessor["bufferView"]]
    start = position_view.get("byteOffset", 0) + position_accessor.get("byteOffset", 0)
    raw = np.frombuffer(
        bin_chunk[start : start + position_accessor["count"] * 3 * 2],
        dtype="<u2",
    ).reshape((position_accessor["count"], 3))

    np.testing.assert_array_equal(raw[:, 0], np.sort(raw[:, 0]))


def test_v2_scene_reuse_export_splits_large_meshes_for_uint16_indices(
    tmp_path: Path,
) -> None:
    vertex_count = 70_000
    vertices = np.column_stack(
        (
            np.arange(vertex_count, dtype=np.float64),
            np.mod(np.arange(vertex_count, dtype=np.float64), 7.0),
            np.zeros(vertex_count, dtype=np.float64),
        )
    )
    fan_indices = np.arange(1, vertex_count - 1, dtype=np.int64)
    faces = np.column_stack(
        (
            np.zeros(len(fan_indices), dtype=np.int64),
            fan_indices,
            fan_indices + 1,
        )
    )
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        fallback_mesh=trimesh.Trimesh(vertices=vertices, faces=faces, process=False),
    )

    out_path = tmp_path / "scene-reuse-large.glb"
    vector_glb_preview.export_vector_glb_preview_v2_scene_reuse(
        [part],
        output_path=str(out_path),
    )

    gltf = _load_glb_json(out_path)
    color_meshes = [
        mesh
        for mesh in gltf["meshes"]
        if str(mesh.get("name", "")).startswith("color_ff0000")
    ]
    assert len(color_meshes) >= 2
    for mesh in color_meshes:
        primitive = mesh["primitives"][0]
        index_accessor = gltf["accessors"][primitive["indices"]]
        assert index_accessor["componentType"] == vector_glb_preview._GLTF_UINT16_COMPONENT_TYPE


@pytest.mark.parametrize("ctx_flag", ["enable_fridge_magnet", "enable_coating"])
def test_dispatch_v2_scene_reuse_supports_existing_auxiliary_scene_geometry(
    monkeypatch,
    tmp_path: Path,
    ctx_flag: str,
) -> None:
    scene = trimesh.Scene()
    scene.add_geometry(_box_mesh(), geom_name="Board")
    calls: list[str] = []

    def fake_scene_reuse(parts, *, output_path):
        assert parts[0].export_name == "backing_plate"
        calls.append("scene_reuse")
        Path(output_path).write_bytes(b"glb")
        return output_path

    def fake_v1(parts, *, output_path):
        del parts, output_path
        calls.append("v1")
        raise AssertionError("scene-reuse v2 can preserve already-built auxiliary geometry")

    monkeypatch.setenv("LUMINA_VECTOR_GLB_KERNEL", "v2")
    monkeypatch.setattr(
        vector_glb_preview,
        "export_vector_glb_preview_v2_scene_reuse",
        fake_scene_reuse,
    )
    monkeypatch.setattr(vector_glb_preview, "export_vector_glb_preview_v1", fake_v1)

    result = vector_glb_preview.export_vector_glb_preview(
        scene=scene,
        output_path=str(tmp_path / "preview.glb"),
        structure_mode="Single-sided",
        color_mode="4-Color (RYBW)",
        preview_colors={"Board": [255, 255, 255, 255]},
        slot_list=["Board"],
        analysis=_analysis_for_v2_test(),
        ctx={ctx_flag: True, "spacer_thick": 1.6},
    )

    assert result.endswith("preview.glb")
    assert calls == ["scene_reuse"]


def test_v2_exporter_rejects_part_without_footprint(tmp_path: Path) -> None:
    part = vector_glb_preview.VectorPreviewPart(
        source_name="FridgeCavityBoard",
        export_name="backing_plate",
        role="backing",
        rgba=(255, 255, 255, 255),
        is_recolorable=False,
        extrusions=(),
        fallback_mesh=trimesh.creation.box(extents=(1, 1, 1)),
    )

    with pytest.raises(RuntimeError, match="requires footprints"):
        vector_glb_preview.export_vector_glb_preview_v2(
            [part],
            output_path=str(tmp_path / "bad.glb"),
        )


def test_v2_success_logs_kernel_and_part_count(
    tmp_path: Path,
    vector_glb_caplog,
) -> None:
    vector_glb_caplog.set_level(
        logging.INFO,
        logger="lumina.core.pipeline.vector_glb_preview",
    )
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        extrusions=(
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(0, 0, 5, 5),
                z_min=0.0,
                z_max=0.16,
            ),
        ),
    )

    vector_glb_preview.export_vector_glb_preview_v2(
        [part],
        output_path=str(tmp_path / "preview.glb"),
        pixels_per_mm=4.0,
    )

    assert "vector_glb_v2_exported" in _record_events(vector_glb_caplog)


def test_v2_exporter_uses_material_color_without_vertex_color_attribute(
    tmp_path: Path,
) -> None:
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        extrusions=(
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(0, 0, 5, 5),
                z_min=0.0,
                z_max=0.16,
            ),
        ),
    )

    out_path = tmp_path / "preview.glb"
    vector_glb_preview.export_vector_glb_preview_v2(
        [part],
        output_path=str(out_path),
        pixels_per_mm=4.0,
    )

    gltf = _load_glb_json(out_path)
    mesh = next(item for item in gltf["meshes"] if item["name"] == "color_ff0000")
    primitive = mesh["primitives"][0]
    assert "COLOR_0" not in primitive["attributes"]

    material = gltf["materials"][primitive["material"]]
    assert material["pbrMetallicRoughness"]["baseColorFactor"] == [1.0, 0.0, 0.0, 1.0]

    loaded = trimesh.load(out_path, force="scene")
    color_mesh = loaded.geometry["color_ff0000"]
    assert getattr(color_mesh.visual, "vertex_colors", None) is None
    assert getattr(color_mesh.visual, "face_colors", None) is None


def test_v2_exporter_splits_large_color_meshes_for_uint16_indices(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vertex_count = 70_000
    vertices = np.column_stack(
        [
            np.arange(vertex_count, dtype=np.float64),
            np.zeros(vertex_count, dtype=np.float64),
            np.zeros(vertex_count, dtype=np.float64),
        ]
    )
    faces = np.arange(69_999, dtype=np.int64).reshape(-1, 3)
    source_mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)

    def fake_mesh_from_extrusion(_extrusion, *, rgba, pixels_per_mm):
        del rgba, pixels_per_mm
        return source_mesh

    monkeypatch.setattr(
        vector_glb_preview,
        "_mesh_from_extrusion_v2",
        fake_mesh_from_extrusion,
    )
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        extrusions=(
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(0, 0, 1, 1),
                z_min=0.0,
                z_max=0.16,
            ),
        ),
    )

    out_path = tmp_path / "chunked.glb"
    vector_glb_preview.export_vector_glb_preview_v2(
        [part],
        output_path=str(out_path),
        pixels_per_mm=4.0,
    )

    gltf = _load_glb_json(out_path)
    color_meshes = [
        mesh
        for mesh in gltf["meshes"]
        if str(mesh["name"]).startswith("color_ff0000")
    ]
    assert len(color_meshes) > 1
    assert {mesh["name"][:12] for mesh in color_meshes} == {"color_ff0000"}
    for mesh in color_meshes:
        primitive = mesh["primitives"][0]
        index_accessor = gltf["accessors"][primitive["indices"]]
        assert index_accessor["componentType"] == 5123
        assert "COLOR_0" not in primitive["attributes"]


def test_v2_exporter_quantizes_position_buffers_and_preserves_bounds(
    tmp_path: Path,
) -> None:
    extrusion = vector_glb_preview.VectorPreviewExtrusion(
        footprint=box(0, 0, 5, 3),
        z_min=0.0,
        z_max=0.16,
    )
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        extrusions=(extrusion,),
    )
    expected_mesh = vector_glb_preview._mesh_from_extrusion_v2(
        extrusion,
        rgba=part.rgba,
        pixels_per_mm=8.0,
    )

    out_path = tmp_path / "quantized.glb"
    vector_glb_preview.export_vector_glb_preview_v2(
        [part],
        output_path=str(out_path),
        pixels_per_mm=8.0,
    )

    gltf, bin_chunk = _load_glb_json_and_bin(out_path)
    assert "KHR_mesh_quantization" in set(gltf.get("extensionsUsed", []))
    mesh_index, mesh = next(
        (index, item)
        for index, item in enumerate(gltf["meshes"])
        if item["name"] == "color_ff0000"
    )
    primitive = mesh["primitives"][0]
    position_accessor = gltf["accessors"][primitive["attributes"]["POSITION"]]
    assert position_accessor["componentType"] == 5123
    assert position_accessor["normalized"] is True
    assert position_accessor["type"] == "VEC3"

    position_view = gltf["bufferViews"][position_accessor["bufferView"]]
    assert position_view["byteLength"] <= position_accessor["count"] * 6 + 3
    node = next(item for item in gltf["nodes"] if item.get("mesh") == mesh_index)
    assert node["translation"] == pytest.approx(expected_mesh.bounds[0].tolist())
    expected_scale = (expected_mesh.bounds[1] - expected_mesh.bounds[0]).tolist()
    assert node["scale"] == pytest.approx(expected_scale)

    start = position_view.get("byteOffset", 0) + position_accessor.get("byteOffset", 0)
    raw = np.frombuffer(
        bin_chunk[start : start + position_accessor["count"] * 3 * 2],
        dtype="<u2",
    ).reshape((position_accessor["count"], 3))
    reconstructed = (
        raw.astype(np.float64)
        / vector_glb_preview._GLTF_UINT16_MAX_INDEX
        * np.asarray(node["scale"], dtype=np.float64)
        + np.asarray(node["translation"], dtype=np.float64)
    )
    np.testing.assert_allclose(
        reconstructed.min(axis=0),
        expected_mesh.bounds[0],
        atol=0.001,
    )
    np.testing.assert_allclose(
        reconstructed.max(axis=0),
        expected_mesh.bounds[1],
        atol=0.001,
    )


def test_v2_postprocessor_sorts_triangle_indices_for_gzip() -> None:
    original = np.asarray(
        [
            [5, 4, 3],
            [0, 2, 1],
            [2, 3, 0],
        ],
        dtype="<u2",
    )
    buffer_items = {0: original.reshape(-1).tobytes()}
    tree = {
        "accessors": {
            0: {
                "componentType": vector_glb_preview._GLTF_UINT16_COMPONENT_TYPE,
                "count": int(original.size),
                "bufferView": 0,
                "type": "SCALAR",
            }
        },
        "meshes": [
            {
                "primitives": [
                    {
                        "indices": 0,
                        "mode": 4,
                    }
                ]
            }
        ],
    }

    vector_glb_preview._sort_v2_triangle_index_buffers_for_gzip(buffer_items, tree)

    sorted_indices = np.frombuffer(buffer_items[0], dtype="<u2").reshape((-1, 3))
    expected = np.asarray(
        [
            [0, 2, 1],
            [2, 3, 0],
            [5, 4, 3],
        ],
        dtype=np.uint16,
    )
    np.testing.assert_array_equal(sorted_indices, expected)
    assert {tuple(row) for row in sorted_indices.tolist()} == {
        tuple(row) for row in original.tolist()
    }


def test_v2_postprocessor_sorts_quantized_positions_and_remaps_indices() -> None:
    positions = np.asarray(
        [
            [10, 0, 0],
            [0, 0, 0],
            [5, 0, 0],
        ],
        dtype="<u2",
    )
    indices = np.asarray([0, 1, 2], dtype="<u2")
    buffer_items = {
        0: indices.tobytes(),
        1: positions.reshape(-1).tobytes(),
    }
    tree = {
        "accessors": {
            0: {
                "componentType": vector_glb_preview._GLTF_UINT16_COMPONENT_TYPE,
                "count": int(indices.size),
                "bufferView": 0,
                "type": "SCALAR",
                "min": [0],
                "max": [2],
            },
            1: {
                "componentType": vector_glb_preview._GLTF_UINT16_COMPONENT_TYPE,
                "normalized": True,
                "count": int(len(positions)),
                "bufferView": 1,
                "type": "VEC3",
                "min": [0, 0, 0],
                "max": [10, 0, 0],
            },
        },
        "meshes": [
            {
                "primitives": [
                    {
                        "indices": 0,
                        "attributes": {"POSITION": 1},
                        "mode": 4,
                    }
                ]
            }
        ],
    }

    vector_glb_preview._sort_quantized_position_buffers_for_gzip(buffer_items, tree)

    sorted_positions = np.frombuffer(buffer_items[1], dtype="<u2").reshape((-1, 3))
    remapped_indices = np.frombuffer(buffer_items[0], dtype="<u2")
    np.testing.assert_array_equal(
        sorted_positions,
        np.asarray(
            [
                [0, 0, 0],
                [5, 0, 0],
                [10, 0, 0],
            ],
            dtype=np.uint16,
        ),
    )
    np.testing.assert_array_equal(remapped_indices, np.asarray([2, 0, 1], dtype=np.uint16))
    assert tree["accessors"][0]["min"] == [0]
    assert tree["accessors"][0]["max"] == [2]


def test_v2_postprocessor_sorts_vertex_attributes_with_quantized_positions() -> None:
    positions = np.asarray(
        [
            [10, 0, 0],
            [0, 0, 0],
            [5, 0, 0],
        ],
        dtype="<u2",
    )
    normals = np.asarray(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype="<f4",
    )
    indices = np.asarray([0, 1, 2], dtype="<u2")
    buffer_items = {
        0: indices.tobytes(),
        1: positions.reshape(-1).tobytes(),
        2: normals.reshape(-1).tobytes(),
    }
    tree = {
        "accessors": {
            0: {
                "componentType": vector_glb_preview._GLTF_UINT16_COMPONENT_TYPE,
                "count": int(indices.size),
                "bufferView": 0,
                "type": "SCALAR",
                "min": [0],
                "max": [2],
            },
            1: {
                "componentType": vector_glb_preview._GLTF_UINT16_COMPONENT_TYPE,
                "normalized": True,
                "count": int(len(positions)),
                "bufferView": 1,
                "type": "VEC3",
                "min": [0, 0, 0],
                "max": [10, 0, 0],
            },
            2: {
                "componentType": vector_glb_preview._GLTF_FLOAT_COMPONENT_TYPE,
                "count": int(len(normals)),
                "bufferView": 2,
                "type": "VEC3",
            },
        },
        "meshes": [
            {
                "primitives": [
                    {
                        "indices": 0,
                        "attributes": {"POSITION": 1, "NORMAL": 2},
                        "mode": 4,
                    }
                ]
            }
        ],
    }

    vector_glb_preview._sort_quantized_position_buffers_for_gzip(buffer_items, tree)

    sorted_normals = np.frombuffer(buffer_items[2], dtype="<f4").reshape((-1, 3))
    np.testing.assert_array_equal(
        sorted_normals,
        np.asarray(
            [
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
                [1.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        ),
    )


def test_v2_uint16_mesh_split_keeps_shared_vertex_chunks_compact() -> None:
    vertex_count = 70_000
    vertices = np.column_stack(
        [
            np.arange(vertex_count, dtype=np.float64),
            np.zeros(vertex_count, dtype=np.float64),
            np.zeros(vertex_count, dtype=np.float64),
        ]
    )
    fan_indices = np.arange(1, vertex_count - 1, dtype=np.int64)
    faces = np.column_stack(
        [
            np.zeros(len(fan_indices), dtype=np.int64),
            fan_indices,
            fan_indices + 1,
        ]
    )
    source_mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)

    chunks = vector_glb_preview._split_mesh_for_uint16_indices(source_mesh)

    assert len(chunks) == 2
    assert sum(len(chunk.faces) for chunk in chunks) == len(faces)
    assert all(len(chunk.vertices) <= 65_536 for chunk in chunks)


def test_v2_uint16_pack_avoids_split_copy_for_small_meshes(monkeypatch) -> None:
    monkeypatch.setattr(
        vector_glb_preview,
        "_split_mesh_for_uint16_indices",
        lambda _mesh, *, max_vertices=65_536: pytest.fail(
            "small meshes should pack without split-copy"
        ),
    )

    first = _box_mesh(0.0, 0.08)
    second = _box_mesh(0.08, 0.16)

    chunks = vector_glb_preview._pack_meshes_for_uint16_indices([first, second])

    assert len(chunks) == 1
    assert len(chunks[0].vertices) == len(first.vertices) + len(second.vertices)
    assert len(chunks[0].faces) == len(first.faces) + len(second.faces)
    np.testing.assert_allclose(
        chunks[0].bounds,
        np.vstack(
            [
                np.minimum(first.bounds[0], second.bounds[0]),
                np.maximum(first.bounds[1], second.bounds[1]),
            ]
        ),
    )


def test_v2_material_assignment_reuses_mesh_without_geometry_copy() -> None:
    source_mesh = _box_mesh()

    result = vector_glb_preview._mesh_with_material_rgba(
        source_mesh,
        (255, 0, 0, 255),
        material_name="red_material",
    )

    assert result is source_mesh
    assert result.visual.material.name == "red_material"
    assert result.visual.material.baseColorFactor.tolist() == [255, 0, 0, 255]


def test_v2_vector_mesh_generation_skips_temporary_face_colors(monkeypatch) -> None:
    captured_assign_face_colors: list[bool] = []
    captured_chunk_sizes: list[int | None] = []

    def fake_build_color_extruded_mesh_v2(
        *,
        mask,
        height,
        total_layers,
        rgba,
        assign_face_colors=True,
        component_compose_chunk_size=None,
    ):
        del mask, height, total_layers, rgba
        captured_assign_face_colors.append(assign_face_colors)
        captured_chunk_sizes.append(component_compose_chunk_size)
        return _box_mesh()

    monkeypatch.setattr(
        vector_glb_preview,
        "_build_color_extruded_mesh_v2",
        fake_build_color_extruded_mesh_v2,
    )

    mesh = vector_glb_preview._mesh_from_extrusion_v2(
        vector_glb_preview.VectorPreviewExtrusion(
            footprint=box(0, 0, 1, 1),
            z_min=0.0,
            z_max=0.16,
        ),
        rgba=(255, 0, 0, 255),
        pixels_per_mm=4.0,
    )

    assert mesh is not None
    assert captured_assign_face_colors == [False]
    assert captured_chunk_sizes == [vector_glb_preview._V2_VECTOR_COMPONENT_COMPOSE_CHUNK_SIZE]


def test_v2_exporter_preserves_subpixel_thin_footprint(tmp_path: Path) -> None:
    part = vector_glb_preview.VectorPreviewPart(
        source_name="White",
        export_name="color_ffffff",
        role="color",
        rgba=(255, 255, 255, 255),
        is_recolorable=True,
        extrusions=(
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(0.0, 0.0, 0.4090640439188539, 0.03940056407232227),
                z_min=0.16,
                z_max=0.24,
            ),
        ),
    )

    out_path = tmp_path / "thin.glb"
    result = vector_glb_preview.export_vector_glb_preview_v2(
        [part],
        output_path=str(out_path),
        pixels_per_mm=10.0,
    )

    assert result == str(out_path)
    assert out_path.exists()


def test_v2_exporter_batches_same_z_extrusions_before_meshing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[tuple[float, float, float, float], float, float, int]] = []

    def fake_mesh_from_extrusion(extrusion, *, rgba, pixels_per_mm):
        del rgba, pixels_per_mm
        captured.append(
            (
                vector_glb_preview._bounds_for_footprints(extrusion.footprints),
                float(extrusion.z_min),
                float(extrusion.z_max),
                len(extrusion.footprints),
            )
        )
        return _box_mesh(extrusion.z_min, extrusion.z_max)

    monkeypatch.setattr(
        vector_glb_preview,
        "_mesh_from_extrusion_v2",
        fake_mesh_from_extrusion,
    )
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        extrusions=(
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(0, 0, 1, 1),
                z_min=0.0,
                z_max=0.08,
            ),
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(2, 0, 3, 1),
                z_min=0.0,
                z_max=0.08,
            ),
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(4, 0, 5, 1),
                z_min=0.08,
                z_max=0.16,
            ),
        ),
    )

    vector_glb_preview.export_vector_glb_preview_v2(
        [part],
        output_path=str(tmp_path / "batched.glb"),
    )

    assert len(captured) == 2
    assert captured[0] == ((0.0, 0.0, 3.0, 1.0), 0.0, 0.08, 2)
    assert captured[1] == ((4.0, 0.0, 5.0, 1.0), 0.08, 0.16, 1)


def test_v2_exporter_packs_batched_color_meshes_without_trimesh_concatenate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_mesh_from_extrusion(extrusion, *, rgba, pixels_per_mm):
        del rgba, pixels_per_mm
        return _box_mesh(extrusion.z_min, extrusion.z_max)

    monkeypatch.setattr(
        vector_glb_preview,
        "_mesh_from_extrusion_v2",
        fake_mesh_from_extrusion,
    )
    monkeypatch.setattr(
        vector_glb_preview.trimesh.util,
        "concatenate",
        lambda _meshes: pytest.fail("V2 color export should not concatenate batched meshes"),
    )
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        extrusions=(
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(0, 0, 1, 1),
                z_min=0.0,
                z_max=0.08,
            ),
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(0, 0, 1, 1),
                z_min=0.08,
                z_max=0.16,
            ),
        ),
    )

    out_path = tmp_path / "separate.glb"
    vector_glb_preview.export_vector_glb_preview_v2(
        [part],
        output_path=str(out_path),
    )

    gltf = _load_glb_json(out_path)
    color_mesh_names = [
        str(mesh["name"])
        for mesh in gltf["meshes"]
        if str(mesh["name"]).startswith("color_ff0000")
    ]
    assert color_mesh_names == ["color_ff0000"]
    color_material_indices: set[int] = set()
    for mesh in gltf["meshes"]:
        if not str(mesh["name"]).startswith("color_ff0000"):
            continue
        primitive = mesh["primitives"][0]
        assert "COLOR_0" not in primitive["attributes"]
        color_material_indices.add(primitive["material"])
        material = gltf["materials"][primitive["material"]]
        assert material["pbrMetallicRoughness"]["baseColorFactor"] == [
            1.0,
            0.0,
            0.0,
            1.0,
        ]
    assert len(color_material_indices) == 1
    mesh_index = next(
        index
        for index, mesh in enumerate(gltf["meshes"])
        if mesh["name"] == "color_ff0000"
    )
    node = next(item for item in gltf["nodes"] if item.get("mesh") == mesh_index)
    assert node["translation"] == pytest.approx([-1.0, -1.0, 0.0])
    assert node["scale"] == pytest.approx([2.0, 2.0, 0.16])


def test_v2_batch_keeps_same_z_footprints_without_union(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        vector_glb_preview,
        "disjoint_subset_union_all",
        lambda _footprints: pytest.fail("same-Z V2 batching should not call fast union"),
        raising=False,
    )
    monkeypatch.setattr(
        vector_glb_preview,
        "unary_union",
        lambda _footprints: pytest.fail("same-Z V2 batching should not call unary_union"),
    )
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        extrusions=(
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(0, 0, 1, 1),
                z_min=0.0,
                z_max=0.08,
            ),
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(2, 0, 3, 1),
                z_min=0.0,
                z_max=0.08,
            ),
        ),
    )

    batched = vector_glb_preview._batch_part_extrusions_for_v2(part)

    assert len(batched) == 1
    assert len(batched[0].footprints) == 2
    assert vector_glb_preview._bounds_for_footprints(batched[0].footprints) == (
        0.0,
        0.0,
        3.0,
        1.0,
    )


def test_v2_batched_extrusions_skip_revalidating_footprints(monkeypatch) -> None:
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        extrusions=(
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(0, 0, 1, 1),
                z_min=0.0,
                z_max=0.08,
            ),
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(2, 0, 3, 1),
                z_min=0.0,
                z_max=0.08,
            ),
        ),
    )

    batched = vector_glb_preview._batch_part_extrusions_for_v2(part)

    assert len(batched) == 1
    assert getattr(batched[0], "footprints_validated", False) is True

    monkeypatch.setattr(
        vector_glb_preview,
        "_valid_geometry",
        lambda _geometry: pytest.fail("batched footprints should not be revalidated"),
    )

    mesh = vector_glb_preview._mesh_from_extrusion_v2(
        batched[0],
        rgba=(255, 0, 0, 255),
        pixels_per_mm=4.0,
    )

    assert len(mesh.vertices) > 0
    assert len(mesh.faces) > 0


def test_v2_vector_rasterizer_imports_are_cached(monkeypatch) -> None:
    import builtins as _builtins

    vector_glb_preview._get_vector_v2_rasterizer_modules.cache_clear()
    original_import = _builtins.__import__
    import_counts = {"rasterio.features": 0, "rasterio.transform": 0}

    def counted_import(name, *args, **kwargs):
        if name in import_counts:
            import_counts[name] += 1
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(_builtins, "__import__", counted_import)

    extrusion = vector_glb_preview.VectorPreviewExtrusion(
        footprint=box(0, 0, 1, 1),
        z_min=0.0,
        z_max=0.16,
    )
    first = vector_glb_preview._mesh_from_extrusion_v2(
        extrusion,
        rgba=(255, 0, 0, 255),
        pixels_per_mm=4.0,
    )
    counts_after_first = dict(import_counts)
    second = vector_glb_preview._mesh_from_extrusion_v2(
        extrusion,
        rgba=(255, 0, 0, 255),
        pixels_per_mm=4.0,
    )

    assert first is not None
    assert second is not None
    assert import_counts == counts_after_first


def test_v2_batch_preserves_overlapping_footprints_without_union(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        vector_glb_preview,
        "disjoint_subset_union_all",
        lambda _footprints: pytest.fail("same-Z V2 batching should not call fast union"),
        raising=False,
    )
    monkeypatch.setattr(
        vector_glb_preview,
        "unary_union",
        lambda _footprints: pytest.fail("same-Z V2 batching should not call unary_union"),
    )
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        extrusions=(
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(0, 0, 2, 1),
                z_min=0.0,
                z_max=0.08,
            ),
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(1, 0, 3, 1),
                z_min=0.0,
                z_max=0.08,
            ),
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=box(5, 0, 6, 1),
                z_min=0.0,
                z_max=0.08,
            ),
        ),
    )

    batched = vector_glb_preview._batch_part_extrusions_for_v2(part)

    assert len(batched) == 1
    assert len(batched[0].footprints) == 3


def test_v2_multi_footprint_mesh_matches_union_reference(
) -> None:
    footprints = (box(0, 0, 2, 1), box(1, 0, 3, 1), box(5, 0, 6, 1))
    part = vector_glb_preview.VectorPreviewPart(
        source_name="Red",
        export_name="color_ff0000",
        role="color",
        rgba=(255, 0, 0, 255),
        is_recolorable=True,
        extrusions=(
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=footprints[0],
                z_min=0.0,
                z_max=0.08,
            ),
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=footprints[1],
                z_min=0.0,
                z_max=0.08,
            ),
            vector_glb_preview.VectorPreviewExtrusion(
                footprint=footprints[2],
                z_min=0.0,
                z_max=0.08,
            ),
        ),
    )

    batched = vector_glb_preview._batch_part_extrusions_for_v2(part)

    assert len(batched) == 1
    multi_mesh = vector_glb_preview._mesh_from_extrusion_v2(
        batched[0],
        rgba=(255, 0, 0, 255),
        pixels_per_mm=8.0,
    )
    union_mesh = vector_glb_preview._mesh_from_extrusion_v2(
        vector_glb_preview.VectorPreviewExtrusion(
            footprint=unary_union(footprints),
            z_min=0.0,
            z_max=0.08,
        ),
        rgba=(255, 0, 0, 255),
        pixels_per_mm=8.0,
    )

    np.testing.assert_allclose(multi_mesh.bounds, union_mesh.bounds)
    assert len(multi_mesh.faces) == len(union_mesh.faces)
    assert len(multi_mesh.vertices) == len(union_mesh.vertices)
    assert multi_mesh.volume == pytest.approx(union_mesh.volume)
