from pathlib import Path
import zipfile

import numpy as np
import psutil
import pytest
import trimesh
from PIL import Image

import scripts.profile_converter_multicore as profile_module
from config import ModelingMode
from scripts.profile_converter_multicore import (
    MATERIAL_PALETTES,
    ProfileCase,
    _ResourceSampler,
    _build_vector_override_context,
    _canonical_triangle_sha256,
    _cleanup_result_files,
    _extract_vector_timings,
    _parse_args,
    build_report,
    build_pipeline_context,
    execute_case,
    semantic_snapshot,
    summarize_runs,
)


def test_profile_counts_reported_material_child_cpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "input.svg"
    source.write_text("<svg/>", encoding="utf-8")
    case = ProfileCase("cpu", "vector", source, 120.0, 8)
    monkeypatch.setattr(
        profile_module, "run_raster_pipeline",
        lambda ctx: {"vector_timing": {"materialize_child_cpu_s": 4.0}},
    )
    metrics = execute_case(case, "generate", enable_cprofile=False, capture_semantics=False)
    assert metrics["child_cpu_s"] == 4.0
    assert metrics["cpu_s"] == pytest.approx(metrics["parent_cpu_s"] + 4.0)
    assert metrics["average_cpu_percent"] == pytest.approx(
        metrics["cpu_s"] / metrics["total_s"] * 100.0,
    )


@pytest.mark.parametrize("size", [8, 12, 15])
def test_material_palette_has_requested_unique_archives(size: int) -> None:
    palette = MATERIAL_PALETTES[size]
    assert len(palette) == size
    assert len(set(palette)) == size
    for directory_name in palette:
        archive = Path("materials") / directory_name / "material.json"
        stage_a = Path("materials") / directory_name / "stage_A_parameters.json"
        assert archive.is_file()
        assert stage_a.is_file()


@pytest.mark.parametrize(
    ("kind", "mode"),
    [("raster", ModelingMode.HIGH_FIDELITY), ("vector", ModelingMode.VECTOR)],
)
def test_build_pipeline_context_uses_quality_locked_profile_settings(
    tmp_path: Path,
    kind: str,
    mode: ModelingMode,
) -> None:
    source = tmp_path / ("input.svg" if kind == "vector" else "input.png")
    source.write_bytes(b"<svg/>" if kind == "vector" else b"not-decoded-in-this-test")
    case = ProfileCase(
        name=f"{kind}-12",
        kind=kind,
        input_path=source,
        target_width_mm=299.0,
        material_count=12,
    )

    ctx = build_pipeline_context(case)

    assert ctx["modeling_mode"] is mode
    assert ctx["material_source"] == "material_archive"
    assert ctx["selected_materials"] == MATERIAL_PALETTES[12]
    assert ctx["material_layer_count"] == 10
    assert ctx["material_layer_height_mm"] == 0.08
    assert ctx["material_grid_resolution"] == 64
    assert ctx["quantize_colors"] == 64
    assert ctx["target_width_mm"] == 299.0
    assert ctx["structure_mode"] == "single-sided"
    assert ctx["retain_scene_for_profile"] is True


@pytest.mark.parametrize(
    "scenario",
    ["matched-rgb", "recipe", "combined"],
)
def test_build_vector_override_context_writes_deterministic_private_artifacts(
    tmp_path: Path,
    scenario: str,
) -> None:
    from core.preview_analysis_cache import REQUIRED_PREVIEW_ANALYSIS_REUSE

    matched_rgb = np.zeros((6, 8, 3), dtype=np.uint8)
    matched_rgb[:, :4] = [255, 0, 0]
    matched_rgb[:, 4:] = [0, 0, 255]
    material_matrix = np.ones((6, 8, 5), dtype=np.int16)
    material_matrix[:, 4:] = 3
    mask_solid = np.ones((6, 8), dtype=bool)
    mask_solid[0, 0] = False
    preview_result = {
        "cache": {
            "matched_rgb": matched_rgb,
            "height_identity_rgb": matched_rgb.copy(),
            "material_matrix": material_matrix,
            "mask_solid": mask_solid,
            "vector_parse_clip_cache_blob": b"parse-clip-reference",
        }
    }

    overrides = _build_vector_override_context(
        preview_result,
        output_dir=tmp_path,
        scenario=scenario,
    )

    saved_matched = np.load(overrides["matched_rgb_path"])
    saved_identity = np.load(overrides["height_identity_rgb_path"])
    saved_material = np.load(overrides["material_matrix_path"])
    saved_mask = np.load(overrides["mask_solid_path"])
    assert np.array_equal(saved_identity, matched_rgb)
    assert np.array_equal(saved_mask, mask_solid)
    assert overrides["reuse_preview_analysis"] == REQUIRED_PREVIEW_ANALYSIS_REUSE
    assert Path(overrides["vector_parse_clip_cache_path"]).read_bytes() == (
        b"parse-clip-reference"
    )
    fixture = overrides["profile_override_fixture"]
    assert fixture["scenario"] == scenario
    assert fixture["grid_shape"] == [6, 8]
    assert fixture["selected_pixel_count"] > 0
    assert "target_rgb" not in fixture

    if scenario in {"matched-rgb", "combined"}:
        assert not np.array_equal(saved_matched, matched_rgb)
        assert not np.array_equal(saved_material, material_matrix)
    else:
        assert np.array_equal(saved_matched, matched_rgb)
        assert np.array_equal(saved_material, material_matrix)

    if scenario in {"recipe", "combined"}:
        assert overrides["recipe_overrides"][0]["region_id"] == (
            "profile-override-region"
        )
        assert Path(overrides["recipe_override_masks_path"]).is_file()
    else:
        assert overrides["recipe_overrides"] is None
        assert overrides["recipe_override_masks_path"] is None


def test_semantic_snapshot_hashes_override_arrays_from_paths(
    tmp_path: Path,
) -> None:
    matched_rgb = np.arange(36, dtype=np.uint8).reshape(3, 4, 3)
    identity_rgb = np.flip(matched_rgb, axis=1).copy()
    material_matrix = np.arange(24, dtype=np.int16).reshape(3, 4, 2)
    mask_solid = np.ones((3, 4), dtype=bool)
    paths = {}
    for name, array in (
        ("matched_rgb", matched_rgb),
        ("height_identity_rgb", identity_rgb),
        ("material_matrix", material_matrix),
        ("mask_solid", mask_solid),
    ):
        path = tmp_path / f"{name}.npy"
        np.save(path, array)
        paths[f"{name}_path"] = str(path)

    snapshot = semantic_snapshot(paths)

    assert snapshot["matched_rgb"] == profile_module._array_summary(matched_rgb)
    assert snapshot["height_identity_rgb"] == profile_module._array_summary(
        identity_rgb
    )
    assert snapshot["material_matrix"] == profile_module._array_summary(
        material_matrix
    )
    assert snapshot["mask_solid"] == profile_module._array_summary(mask_solid)


def _scene_with_geometry_order(order: tuple[str, ...]) -> trimesh.Scene:
    scene = trimesh.Scene()
    meshes = {
        "red": trimesh.creation.box(extents=(2.0, 1.0, 0.4)),
        "blue": trimesh.creation.box(extents=(1.0, 3.0, 0.8)),
    }
    for name in order:
        scene.add_geometry(meshes[name].copy(), node_name=name, geom_name=name)
    return scene


def test_semantic_snapshot_is_stable_across_array_layout_and_scene_order() -> None:
    rgb = np.arange(36, dtype=np.uint8).reshape(3, 4, 3)
    matrix = np.arange(24, dtype=np.int32).reshape(3, 4, 2)
    first = semantic_snapshot(
        {
            "matched_rgb": rgb,
            "material_matrix": matrix,
            "mask_solid": np.ones((3, 4), dtype=bool),
            "scene": _scene_with_geometry_order(("red", "blue")),
            "slot_names": ["white", "black"],
        }
    )
    second = semantic_snapshot(
        {
            "matched_rgb": np.asfortranarray(rgb),
            "material_matrix": np.asfortranarray(matrix),
            "mask_solid": np.asfortranarray(np.ones((3, 4), dtype=bool)),
            "scene": _scene_with_geometry_order(("blue", "red")),
            "slot_names": ["white", "black"],
        }
    )
    assert first == second


def test_semantic_snapshot_changes_when_geometry_or_layers_change() -> None:
    ctx = {
        "matched_rgb": np.zeros((2, 2, 3), dtype=np.uint8),
        "material_matrix": np.zeros((2, 2, 2), dtype=np.int32),
        "mask_solid": np.ones((2, 2), dtype=bool),
        "scene": _scene_with_geometry_order(("red", "blue")),
        "slot_names": ["white", "black"],
    }
    baseline = semantic_snapshot(ctx)
    changed_layers = {**ctx, "material_matrix": np.ones((2, 2, 2), dtype=np.int32)}
    changed_scene = {
        **ctx,
        "scene": trimesh.Scene(trimesh.creation.box(extents=(9.0, 1.0, 0.4))),
    }
    assert semantic_snapshot(changed_layers) != baseline
    assert semantic_snapshot(changed_scene) != baseline


def test_semantic_snapshot_changes_when_face_colors_change() -> None:
    baseline_mesh = trimesh.creation.box(extents=(2.0, 1.0, 0.4))
    baseline_mesh.visual.face_colors = np.array([255, 0, 0, 255], dtype=np.uint8)
    changed_mesh = baseline_mesh.copy()
    changed_mesh.visual.face_colors = np.array([0, 0, 255, 255], dtype=np.uint8)

    baseline = semantic_snapshot({"scene": trimesh.Scene(baseline_mesh)})
    changed = semantic_snapshot({"scene": trimesh.Scene(changed_mesh)})

    assert baseline["geometry"] != changed["geometry"]
    baseline_visual = next(iter(baseline["geometry"].values()))["visual"]
    changed_visual = next(iter(changed["geometry"].values()))["visual"]
    assert baseline_visual["kind"] == "face"
    assert baseline_visual["face_colors"] != changed_visual["face_colors"]


def test_semantic_snapshot_binds_face_colors_across_face_reordering() -> None:
    box = trimesh.creation.box(extents=(2.0, 1.0, 0.4))
    vertices = np.asarray(box.vertices, dtype=np.float64)
    faces = np.asarray(box.faces, dtype=np.int64)
    colors = np.tile(
        np.asarray(
            [[255, 0, 0, 255], [0, 0, 255, 255]],
            dtype=np.uint8,
        ),
        (faces.shape[0] // 2, 1),
    )
    first_mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    first_mesh.visual.face_colors = colors
    reordered_mesh = trimesh.Trimesh(
        vertices=vertices,
        faces=faces[::-1],
        process=False,
    )
    reordered_mesh.visual.face_colors = colors[::-1]
    first_scene = trimesh.Scene()
    first_scene.add_geometry(first_mesh, node_name="part", geom_name="part")
    reordered_scene = trimesh.Scene()
    reordered_scene.add_geometry(
        reordered_mesh,
        node_name="part",
        geom_name="part",
    )

    assert semantic_snapshot({"scene": first_scene}) == semantic_snapshot(
        {"scene": reordered_scene}
    )


def test_semantic_snapshot_changes_when_texture_pixels_change() -> None:
    box = trimesh.creation.box(extents=(2.0, 1.0, 0.4))
    vertices = np.asarray(box.vertices, dtype=np.float64)
    faces = np.asarray(box.faces, dtype=np.int64)
    xy = vertices[:, :2]
    uv = (xy - xy.min(axis=0)) / np.maximum(
        xy.max(axis=0) - xy.min(axis=0),
        1e-12,
    )

    def _textured_scene(rgb: tuple[int, int, int]) -> trimesh.Scene:
        pixels = np.full((2, 2, 3), rgb, dtype=np.uint8)
        visual = trimesh.visual.texture.TextureVisuals(
            uv=uv,
            image=Image.fromarray(pixels),
        )
        mesh = trimesh.Trimesh(
            vertices=vertices,
            faces=faces,
            visual=visual,
            process=False,
        )
        scene = trimesh.Scene()
        scene.add_geometry(mesh, node_name="part", geom_name="part")
        return scene

    red = semantic_snapshot({"scene": _textured_scene((255, 0, 0))})
    blue = semantic_snapshot({"scene": _textured_scene((0, 0, 255))})

    assert red["geometry"] != blue["geometry"]


def test_semantic_snapshot_supports_solid_pbr_material_without_uv() -> None:
    def _solid_material_scene(
        color: tuple[int, int, int, int],
    ) -> trimesh.Scene:
        source = trimesh.creation.box(extents=(2.0, 1.0, 0.4))
        material = trimesh.visual.material.PBRMaterial(
            baseColorFactor=np.asarray(color, dtype=np.uint8),
        )
        visual = trimesh.visual.texture.TextureVisuals(material=material)
        mesh = trimesh.Trimesh(
            vertices=np.asarray(source.vertices),
            faces=np.asarray(source.faces),
            visual=visual,
            process=False,
        )
        return trimesh.Scene(mesh)

    red = semantic_snapshot(
        {"scene": _solid_material_scene((255, 0, 0, 255))}
    )
    blue = semantic_snapshot(
        {"scene": _solid_material_scene((0, 0, 255, 255))}
    )

    red_visual = next(iter(red["geometry"].values()))["visual"]
    blue_visual = next(iter(blue["geometry"].values()))["visual"]
    assert red_visual["kind"] == "texture"
    assert red_visual["uv"] is None
    assert red_visual["material_baseColorFactor"] != (
        blue_visual["material_baseColorFactor"]
    )


def test_canonical_triangle_hash_preserves_face_winding() -> None:
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float64,
    )
    forward = trimesh.Trimesh(
        vertices=vertices,
        faces=np.array([[0, 1, 2]], dtype=np.int64),
        process=False,
    )
    cyclic = trimesh.Trimesh(
        vertices=vertices,
        faces=np.array([[1, 2, 0]], dtype=np.int64),
        process=False,
    )
    reversed_winding = trimesh.Trimesh(
        vertices=vertices,
        faces=np.array([[0, 2, 1]], dtype=np.int64),
        process=False,
    )

    assert _canonical_triangle_sha256(forward) == _canonical_triangle_sha256(cyclic)
    assert (
        _canonical_triangle_sha256(forward)
        != _canonical_triangle_sha256(reversed_winding)
    )


def test_canonical_triangle_hash_is_stable_across_face_order_and_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [2.0, 1.0, 0.0],
        ],
        dtype=np.float64,
    )
    first = trimesh.Trimesh(
        vertices=vertices,
        faces=np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int64),
        process=False,
    )
    reordered_cyclic = trimesh.Trimesh(
        vertices=vertices,
        faces=np.array([[3, 2, 1], [1, 2, 0]], dtype=np.int64),
        process=False,
    )
    monkeypatch.setattr(
        profile_module,
        "_CANONICAL_TRIANGLE_CHUNK_FACES",
        1,
    )

    assert _canonical_triangle_sha256(first) == _canonical_triangle_sha256(
        reordered_cyclic,
    )


def test_semantic_snapshot_applies_scene_node_transforms() -> None:
    mesh = trimesh.creation.box(extents=(2.0, 1.0, 0.4))
    baseline_scene = trimesh.Scene()
    baseline_scene.add_geometry(
        mesh.copy(),
        node_name="part",
        geom_name="part",
    )
    translated_scene = trimesh.Scene()
    translated_scene.add_geometry(
        mesh.copy(),
        node_name="part",
        geom_name="part",
        transform=trimesh.transformations.translation_matrix(
            [100.0, 0.0, 0.0],
        ),
    )

    baseline = semantic_snapshot({"scene": baseline_scene})
    translated = semantic_snapshot({"scene": translated_scene})

    assert baseline != translated
    assert baseline["geometry"] == translated["geometry"]
    assert baseline["scene_instances"] != translated["scene_instances"]
    assert (
        baseline["scene_instances"][0]["world"]["visual"]
        == translated["scene_instances"][0]["world"]["visual"]
    )


def test_semantic_snapshot_preserves_multiple_scene_instances() -> None:
    mesh = trimesh.creation.box(extents=(2.0, 1.0, 0.4))
    single = trimesh.Scene()
    single.add_geometry(mesh.copy(), node_name="first", geom_name="shared")
    repeated = single.copy()
    repeated.graph.update(
        frame_from=repeated.graph.base_frame,
        frame_to="second",
        matrix=trimesh.transformations.translation_matrix([5.0, 0.0, 0.0]),
        geometry="shared",
    )

    single_snapshot = semantic_snapshot({"scene": single})
    repeated_snapshot = semantic_snapshot({"scene": repeated})

    assert len(single_snapshot["scene_instances"]) == 1
    assert len(repeated_snapshot["scene_instances"]) == 2
    assert single_snapshot != repeated_snapshot


def test_semantic_snapshot_preserves_geometry_identity_per_instance() -> None:
    """Equal meshes swapping transforms must retain material assignment."""

    shared_shape = trimesh.creation.box(extents=(2.0, 1.0, 0.4))
    first = trimesh.Scene()
    first.add_geometry(
        shared_shape.copy(),
        node_name="red-node",
        geom_name="red-material",
    )
    first.add_geometry(
        shared_shape.copy(),
        node_name="blue-node",
        geom_name="blue-material",
        transform=trimesh.transformations.translation_matrix([5.0, 0.0, 0.0]),
    )
    swapped = trimesh.Scene()
    swapped.add_geometry(
        shared_shape.copy(),
        node_name="red-node",
        geom_name="red-material",
        transform=trimesh.transformations.translation_matrix([5.0, 0.0, 0.0]),
    )
    swapped.add_geometry(
        shared_shape.copy(),
        node_name="blue-node",
        geom_name="blue-material",
    )

    first_snapshot = semantic_snapshot({"scene": first})
    swapped_snapshot = semantic_snapshot({"scene": swapped})

    assert first_snapshot["geometry"] == swapped_snapshot["geometry"]
    assert first_snapshot["scene_instances"] != swapped_snapshot["scene_instances"]


def test_semantic_snapshot_does_not_copy_mesh_visuals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Broken preview-color caches must not block geometry verification."""

    scene = trimesh.Scene()
    scene.add_geometry(
        trimesh.creation.box(extents=(2.0, 1.0, 0.4)),
        node_name="part",
        geom_name="part",
    )
    monkeypatch.setattr(
        trimesh.Trimesh,
        "copy",
        lambda self: pytest.fail("semantic geometry must not copy visuals"),
    )

    snapshot = semantic_snapshot({"scene": scene})

    assert len(snapshot["scene_instances"]) == 1


def test_semantic_snapshot_reuses_identity_geometry_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = trimesh.Scene()
    scene.add_geometry(
        trimesh.creation.box(extents=(2.0, 1.0, 0.4)),
        node_name="part",
        geom_name="part",
    )
    original_summary = profile_module._mesh_summary
    summarized_mesh_ids: list[int] = []

    def _record_summary(
        mesh: trimesh.Trimesh,
        **kwargs: object,
    ) -> dict[str, object]:
        summarized_mesh_ids.append(id(mesh))
        return original_summary(mesh, **kwargs)

    monkeypatch.setattr(profile_module, "_mesh_summary", _record_summary)

    snapshot = semantic_snapshot({"scene": scene})

    assert len(summarized_mesh_ids) == 1
    assert snapshot["scene_instances"][0] == {
        "geometry": "part",
        "world": snapshot["geometry"]["part"],
    }


def test_semantic_snapshot_loads_exported_scene_from_result_tuple(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "model.glb"
    _scene_with_geometry_order(("red", "blue")).export(artifact)

    snapshot = semantic_snapshot(
        {
            "result_tuple": (str(artifact), None, None, "done", None),
            "slot_names": ["white", "black"],
        }
    )

    assert snapshot["geometry"]


def test_semantic_snapshot_detects_export_artifact_change(
    tmp_path: Path,
) -> None:
    scene = _scene_with_geometry_order(("red", "blue"))
    first_artifact = tmp_path / "first.glb"
    changed_artifact = tmp_path / "changed.glb"
    scene.export(first_artifact)
    changed_artifact.write_bytes(first_artifact.read_bytes() + b"changed")

    first = semantic_snapshot(
        {
            "scene": scene,
            "result_tuple": (None, str(first_artifact), None, "done", None),
        }
    )
    changed = semantic_snapshot(
        {
            "scene": scene,
            "result_tuple": (None, str(changed_artifact), None, "done", None),
        }
    )

    assert first["geometry"] == changed["geometry"]
    assert first["artifacts"] != changed["artifacts"]


def test_archive_summary_ignores_member_order_and_zip_timestamp(
    tmp_path: Path,
) -> None:
    first_archive = tmp_path / "first.3mf"
    reordered_archive = tmp_path / "reordered.3mf"
    changed_archive = tmp_path / "changed.3mf"

    def _write_archive(
        path: Path,
        entries: list[tuple[str, bytes]],
        date_time: tuple[int, int, int, int, int, int],
    ) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            for name, payload in entries:
                info = zipfile.ZipInfo(name, date_time=date_time)
                archive.writestr(info, payload)

    entries = [
        ("3D/3dmodel.model", b"<model material='red'/>"),
        ("[Content_Types].xml", b"<Types/>"),
    ]
    _write_archive(first_archive, entries, (2025, 1, 1, 0, 0, 0))
    _write_archive(
        reordered_archive,
        list(reversed(entries)),
        (2026, 7, 28, 12, 0, 0),
    )
    _write_archive(
        changed_archive,
        [
            ("3D/3dmodel.model", b"<model material='blue'/>"),
            entries[1],
        ],
        (2026, 7, 28, 12, 0, 0),
    )

    first = semantic_snapshot(
        {"result_tuple": (str(first_archive), None, None, "done", None)}
    )
    reordered = semantic_snapshot(
        {"result_tuple": (str(reordered_archive), None, None, "done", None)}
    )
    changed = semantic_snapshot(
        {"result_tuple": (str(changed_archive), None, None, "done", None)}
    )

    assert first["artifacts"] == reordered["artifacts"]
    assert first["artifacts"] != changed["artifacts"]


def test_archive_summary_streams_members_without_zipfile_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "model.3mf"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("3D/3dmodel.model", b"<model/>" * 1024)
    monkeypatch.setattr(
        zipfile.ZipFile,
        "read",
        lambda *_args, **_kwargs: pytest.fail(
            "artifact summaries must stream archive members"
        ),
    )

    summary = profile_module._export_artifact_summaries(
        {"result_tuple": (str(artifact), None, None, "done", None)}
    )

    assert summary["model"]["members"][0]["size_bytes"] == len(b"<model/>") * 1024


def test_archive_summary_normalizes_generated_source_filename(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.3mf"
    second = tmp_path / "second.3mf"
    changed = tmp_path / "changed.3mf"

    def _write(path: Path, source_file: str, extruder: str) -> None:
        xml = (
            "<config><object><part>"
            f'<metadata key="source_file" value="{source_file}"/>'
            f'<metadata key="extruder" value="{extruder}"/>'
            "</part></object></config>"
        ).encode("utf-8")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Metadata/model_settings.config", xml)

    _write(first, "first_generated_name.3mf", "1")
    _write(second, "second_generated_name.3mf", "1")
    _write(changed, "third_generated_name.3mf", "2")

    first_summary = profile_module._export_artifact_summaries(
        {"result_tuple": (str(first), None, None, "done", None)}
    )
    second_summary = profile_module._export_artifact_summaries(
        {"result_tuple": (str(second), None, None, "done", None)}
    )
    changed_summary = profile_module._export_artifact_summaries(
        {"result_tuple": (str(changed), None, None, "done", None)}
    )

    assert first_summary == second_summary
    assert first_summary != changed_summary


def test_summarize_runs_reports_cold_warm_median_and_p90() -> None:
    summary = summarize_runs(
        [
            {
                "total_s": 9.0,
                "rss_at_start_mb": 90.0,
                "peak_rss_mb": 100.0,
                "peak_rss_increase_mb": 10.0,
            },
            {
                "total_s": 5.0,
                "rss_at_start_mb": 95.0,
                "peak_rss_mb": 110.0,
                "peak_rss_increase_mb": 15.0,
            },
            {
                "total_s": 7.0,
                "rss_at_start_mb": 100.0,
                "peak_rss_mb": 120.0,
                "peak_rss_increase_mb": 20.0,
            },
        ]
    )
    assert summary["cold"]["total_s"] == 9.0
    assert summary["warm_median"]["total_s"] == 6.0
    assert summary["p90"]["total_s"] == pytest.approx(6.8)
    assert summary["peak"]["peak_rss_mb"] == 120.0
    assert summary["peak"]["peak_rss_increase_mb"] == 20.0


def test_build_report_omits_absolute_source_and_material_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("VECLIB_MAXIMUM_THREADS", "1")
    source = tmp_path / "private-user-image.jpg"
    source.write_bytes(b"image")
    case = ProfileCase(
        name="raster-12",
        kind="raster",
        input_path=source,
        target_width_mm=299.0,
        material_count=12,
    )
    report = build_report(
        case,
        runs=[{"total_s": 1.0, "peak_rss_mb": 2.0}],
    )
    serialized = repr(report)
    assert str(tmp_path) not in serialized
    assert report["input"]["name"] == source.name
    assert report["input"]["sha256"]
    assert report["materials"]["count"] == 12
    assert "directory_names" not in report["materials"]
    assert report["thread_environment"]["OMP_NUM_THREADS"] == "1"
    assert report["thread_environment"]["VECLIB_MAXIMUM_THREADS"] == "1"


def test_build_report_records_identical_semantic_snapshots(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fixture.svg"
    source.write_text("<svg/>", encoding="utf-8")
    case = ProfileCase(
        name="vector-8",
        kind="vector",
        input_path=source,
        target_width_mm=20.0,
        material_count=8,
    )
    snapshot = {"matched_rgb": {"sha256": "same"}}

    report = build_report(
        case,
        runs=[
            {
                "total_s": 1.0,
                "peak_rss_mb": 2.0,
                "semantic_snapshot": snapshot,
            },
            {
                "total_s": 1.1,
                "peak_rss_mb": 2.1,
                "semantic_snapshot": dict(snapshot),
            },
        ],
    )

    assert report["quality"]["semantic_snapshots_available"] is True
    assert report["quality"]["semantic_snapshots_equal"] is True
    assert report["quality"]["semantic_snapshot_count"] == 2
    assert report["quality"]["reference_sha256"]


def test_build_report_single_snapshot_is_captured_not_internally_compared(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.svg"
    source.write_text("<svg/>", encoding="utf-8")
    case = ProfileCase(
        name="vector-8",
        kind="vector",
        input_path=source,
        target_width_mm=20.0,
        material_count=8,
    )

    report = build_report(
        case,
        [
            {
                "total_s": 1.0,
                "peak_rss_mb": 2.0,
                "semantic_snapshot": {"quality": "captured"},
            },
        ],
    )

    assert report["quality"]["semantic_snapshot_count"] == 1
    assert report["quality"]["semantic_snapshots_available"] is True
    assert report["quality"]["semantic_snapshots_equal"] is False
    assert report["quality"]["reference_sha256"]


def test_external_semantic_reference_requires_equal_hash(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.svg"
    source.write_text("<svg/>", encoding="utf-8")
    case = ProfileCase(
        name="vector-8",
        kind="vector",
        input_path=source,
        target_width_mm=20.0,
        material_count=8,
    )
    reference = build_report(
        case,
        [
            {
                "total_s": 1.0,
                "peak_rss_mb": 2.0,
                "semantic_snapshot": {"quality": "reference"},
            },
        ],
    )
    matching = build_report(
        case,
        [
            {
                "total_s": 2.0,
                "peak_rss_mb": 3.0,
                "semantic_snapshot": {"quality": "reference"},
            },
        ],
    )
    changed = build_report(
        case,
        [
            {
                "total_s": 2.0,
                "peak_rss_mb": 3.0,
                "semantic_snapshot": {"quality": "changed"},
            },
        ],
    )

    assert profile_module._assert_semantic_reference(reference, matching)
    with pytest.raises(ValueError, match="differs from reference"):
        profile_module._assert_semantic_reference(reference, changed)

    wrong_schema = {**matching, "schema": "legacy"}
    with pytest.raises(ValueError, match="schema does not match"):
        profile_module._assert_semantic_reference(reference, wrong_schema)

    wrong_phase = {**matching, "phase": "generate"}
    reference["phase"] = "preview"
    with pytest.raises(ValueError, match="phase does not match"):
        profile_module._assert_semantic_reference(reference, wrong_phase)


def test_build_report_rejects_semantic_snapshot_mismatch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fixture.svg"
    source.write_text("<svg/>", encoding="utf-8")
    case = ProfileCase(
        name="vector-8",
        kind="vector",
        input_path=source,
        target_width_mm=20.0,
        material_count=8,
    )

    with pytest.raises(ValueError, match="semantic snapshots differ"):
        build_report(
            case,
            runs=[
                {
                    "total_s": 1.0,
                    "peak_rss_mb": 2.0,
                    "semantic_snapshot": {"sha256": "first"},
                },
                {
                    "total_s": 1.1,
                    "peak_rss_mb": 2.1,
                    "semantic_snapshot": {"sha256": "changed"},
                },
            ],
        )


def test_cleanup_result_files_removes_pipeline_result_tuple_artifacts(
    tmp_path: Path,
) -> None:
    model = tmp_path / "model.3mf"
    preview = tmp_path / "preview.glb"
    recipe = tmp_path / "recipe.json"
    for path in (model, preview, recipe):
        path.write_bytes(b"temporary")

    _cleanup_result_files(
        {
            "result_tuple": (
                str(model),
                str(preview),
                None,
                "done",
                str(recipe),
            )
        }
    )

    assert not model.exists()
    assert not preview.exists()
    assert not recipe.exists()


def test_extract_vector_timings_accepts_current_pipeline_key() -> None:
    assert _extract_vector_timings(
        {
            "vector_timing": {
                "parse_s": 1.25,
                "material_parallelism_workers": 3,
                "build_mesh_s": 1.0,
            }
        }
    ) == {
        "parse_s": 1.25,
        "material_parallelism_workers": 3,
        "build_mesh_s": 1.0,
    }


def test_resource_sampler_uses_low_overhead_default_interval() -> None:
    sampler = _ResourceSampler(psutil.Process())
    assert sampler._interval_s == pytest.approx(0.25)


def test_parse_args_supports_external_sampling_without_cprofile(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.svg"
    source.write_text("<svg/>", encoding="utf-8")

    args = _parse_args(
        [
            "--kind",
            "vector",
            "--input",
            str(source),
            "--phase",
            "preview",
            "--no-cprofile",
            "--timing-only",
        ]
    )

    assert args.no_cprofile is True
    assert args.timing_only is True


def test_parse_args_supports_vector_override_scenario(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.svg"
    source.write_text("<svg/>", encoding="utf-8")

    args = _parse_args(
        [
            "--kind",
            "vector",
            "--input",
            str(source),
            "--phase",
            "generate",
            "--override-scenario",
            "combined",
        ]
    )

    assert args.override_scenario == "combined"


def test_parse_args_rejects_removed_in_process_reference_strategy(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.svg"
    source.write_text("<svg/>", encoding="utf-8")

    with pytest.raises(SystemExit):
        _parse_args(
            [
                "--kind",
                "vector",
                "--input",
                str(source),
                "--phase",
                "generate",
                "--override-scenario",
                "combined",
                "--override-strategy",
                "full-canvas-reference",
            ]
        )


def test_execute_case_can_disable_cprofile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "input.jpg"
    source.write_bytes(b"profile-stub")
    case = ProfileCase(
        name="raster-8",
        kind="raster",
        input_path=source,
        target_width_mm=20.0,
        material_count=8,
    )
    monkeypatch.setattr(
        profile_module,
        "run_preview_pipeline",
        lambda ctx: {
            **ctx,
            "matched_rgb": np.zeros((1, 1, 3), dtype=np.uint8),
            "material_matrix": np.zeros((1, 1, 1), dtype=np.int8),
            "mask_solid": np.ones((1, 1), dtype=bool),
            "_hifi_timings": {
                "mesh_gen_s": 0.25,
                "mesh_parallelism_workers": 2,
                "mesh_parallelism_limit": "cpu_fair_share",
                "mesh_parallelism_effective_cpu": 4,
                "mesh_parallelism_outer_demand": 2,
                "mesh_parallelism_cpu_fair_share": 2,
                "mesh_parallelism_demand_fallback": False,
            },
        },
    )
    monkeypatch.delenv("LUMINA_RASTER_PARALLELISM", raising=False)

    metrics = execute_case(case, "preview", enable_cprofile=False)

    assert metrics["cprofile"] == ""
    assert metrics["queue_wait_s"] == 0.0
    assert metrics["worker_execution_s"] == pytest.approx(
        metrics["total_s"]
    )
    assert metrics["rss_at_start_mb"] > 0.0
    assert metrics["peak_rss_mb"] >= metrics["rss_at_start_mb"]
    assert metrics["peak_rss_increase_mb"] == pytest.approx(
        metrics["peak_rss_mb"] - metrics["rss_at_start_mb"]
    )
    assert metrics["hifi_timings"]["mesh_gen_s"] == 0.25
    assert metrics["parallelism"] == {
        "requested": "auto",
        "observed_workers": 2,
        "effective_cpu": 4,
        "cpu_topology": None,
        "cpu_scheduling_policy": None,
        "performance_cpu": None,
        "outer_demand": 2,
        "cpu_fair_share": 2,
        "limiting_reason": "cpu_fair_share",
        "demand_snapshot_fallback": False,
    }


def test_parallelism_metadata_uses_current_vector_material_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUMINA_VECTOR_PARALLELISM", raising=False)

    metadata = profile_module._parallelism_metadata(
        "vector",
        hifi_timings={},
        vector_timings={
            "material_parallelism_workers": 1,
            "material_parallelism_limit": "cpu_fair_share",
            "material_parallelism_effective_cpu": 4,
            "material_parallelism_cpu_topology": "heterogeneous",
            "material_parallelism_cpu_scheduling_policy": (
                "os_core_type_scheduler"
            ),
            "material_parallelism_performance_cpu": 2,
            "material_parallelism_outer_demand": 2,
            "material_parallelism_cpu_fair_share": 2,
            "material_parallelism_demand_fallback": False,
        },
    )

    assert metadata == {
        "requested": "auto",
        "observed_workers": 1,
        "effective_cpu": 4,
        "cpu_topology": "heterogeneous",
        "cpu_scheduling_policy": "os_core_type_scheduler",
        "performance_cpu": 2,
        "outer_demand": 2,
        "cpu_fair_share": 2,
        "limiting_reason": "cpu_fair_share",
        "demand_snapshot_fallback": False,
    }


def test_parallelism_metadata_keeps_legacy_reports_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUMINA_RASTER_PARALLELISM", raising=False)

    metadata = profile_module._parallelism_metadata(
        "raster",
        hifi_timings={"mesh_parallelism_workers": 2},
        vector_timings={},
    )

    assert metadata == {
        "requested": "auto",
        "observed_workers": 2,
        "effective_cpu": None,
        "cpu_topology": None,
        "cpu_scheduling_policy": None,
        "performance_cpu": None,
        "outer_demand": None,
        "cpu_fair_share": None,
        "limiting_reason": None,
        "demand_snapshot_fallback": None,
    }


def test_execute_case_timing_only_skips_semantic_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "input.jpg"
    source.write_bytes(b"profile-stub")
    case = ProfileCase(
        name="raster-8",
        kind="raster",
        input_path=source,
        target_width_mm=20.0,
        material_count=8,
    )
    monkeypatch.setattr(
        profile_module,
        "run_preview_pipeline",
        lambda ctx: {
            **ctx,
            "matched_rgb": np.zeros((1, 1, 3), dtype=np.uint8),
        },
    )
    monkeypatch.setattr(
        profile_module,
        "semantic_snapshot",
        lambda result: pytest.fail("timing-only must skip semantic hashing"),
    )

    metrics = execute_case(
        case,
        "preview",
        enable_cprofile=False,
        capture_semantics=False,
    )

    assert "semantic_snapshot" not in metrics


def test_render_markdown_labels_timing_only_quality(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.svg"
    source.write_text("<svg/>", encoding="utf-8")
    case = ProfileCase(
        name="vector-8",
        kind="vector",
        input_path=source,
        target_width_mm=20.0,
        material_count=8,
    )
    report = build_report(
        case,
        [{"total_s": 1.0, "peak_rss_mb": 2.0}],
    )
    report["phase"] = "preview"

    markdown = profile_module._render_markdown(report)

    assert "Quality evidence: `timing only (no semantic evidence)`" in markdown


def test_render_markdown_labels_exact_semantic_quality(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.svg"
    source.write_text("<svg/>", encoding="utf-8")
    case = ProfileCase(
        name="vector-8",
        kind="vector",
        input_path=source,
        target_width_mm=20.0,
        material_count=8,
    )
    report = build_report(
        case,
        [
            {
                "total_s": 1.0,
                "peak_rss_mb": 2.0,
                "semantic_snapshot": {"quality": "exact"},
            },
            {
                "total_s": 2.0,
                "peak_rss_mb": 3.0,
                "semantic_snapshot": {"quality": "exact"},
            },
        ],
    )
    report["phase"] = "preview"

    markdown = profile_module._render_markdown(report)

    assert "Quality evidence: `exact semantic snapshots`" in markdown


def test_render_markdown_labels_single_captured_snapshot(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.svg"
    source.write_text("<svg/>", encoding="utf-8")
    case = ProfileCase(
        name="vector-8",
        kind="vector",
        input_path=source,
        target_width_mm=20.0,
        material_count=8,
    )
    report = build_report(
        case,
        [
            {
                "total_s": 1.0,
                "peak_rss_mb": 2.0,
                "semantic_snapshot": {"quality": "captured"},
            },
        ],
    )
    report["phase"] = "preview"

    markdown = profile_module._render_markdown(report)

    assert (
        "Quality evidence: `semantic snapshot captured "
        "(not internally compared)`"
    ) in markdown
