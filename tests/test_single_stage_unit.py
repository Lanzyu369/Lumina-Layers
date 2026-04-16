"""Single-stage workflow router tests."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from config import PaletteEntry
from core.single_stage import (
    GradientCardStageAResult,
    MaterialArchiveDeleteResult,
    MaterialArchiveSaveResult,
    SingleStageExtractResult,
    SingleStageKitResult,
    StageAFitResult,
    delete_saved_stage_a_material_archive,
    extract_single_stage_dataset,
    extract_stage_a_material_from_gradient_cards,
    fit_stage_a_from_stage_json,
    generate_single_stage_kit,
    list_saved_stage_a_material_archives,
    save_stage_a_material_archive,
)
from core.single_stage.kit import SingleStageSpec, _build_stage_matrix, _build_stage_scene
from core.single_stage.processing import _safe_extract_zip


def _client_with_state() -> tuple[TestClient, SessionStore, FileRegistry]:
    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app), store, registry


def _linear_to_srgb_uint8(arr: np.ndarray) -> np.ndarray:
    clipped = np.clip(arr.astype(np.float64), 0.0, 1.0)
    srgb = np.where(
        clipped <= 0.0031308,
        12.92 * clipped,
        1.055 * np.power(clipped, 1.0 / 2.4) - 0.055,
    )
    return np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)


def _write_gradient_card_manifest(zip_path: Path, spec: SingleStageSpec) -> None:
    manifest = {
        "schema_version": "1.0",
        "workflow": "single-stage-kit",
        "material_default": "PLA Basic",
        "substrate_id": "white",
        "substrate_display_name": "White",
        "spec": {
            "grid_cols": spec.grid_cols,
            "grid_rows": spec.grid_rows,
            "block_mm": spec.block_mm,
            "gap_mm": spec.gap_mm,
            "margin_mm": spec.margin_mm,
            "pixel_mm": spec.pixel_mm,
            "layer_height_mm": spec.layer_height_mm,
            "base_mm": spec.base_mm,
            "max_step_layers": spec.max_step_layers,
            "step_layers": list(spec.step_layers),
            "shrink_xy_mm": spec.shrink_xy_mm,
        },
    }
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )


def _build_gradient_card_capture(
    spec: SingleStageSpec,
    substrate_linear: np.ndarray,
    e_linear: np.ndarray,
    k_linear: np.ndarray,
) -> np.ndarray:
    pixels_per_mm = 20
    width = int(round(spec.board_width_mm * pixels_per_mm))
    height = int(round(spec.board_height_mm * pixels_per_mm))
    image = np.tile(
        _linear_to_srgb_uint8(substrate_linear.reshape(1, 3)),
        (height, width, 1),
    )
    step_matrix = np.asarray(spec.step_layers, dtype=np.float64).reshape(
        spec.grid_rows,
        spec.grid_cols,
    )
    for row in range(spec.grid_rows):
        for col in range(spec.grid_cols):
            step_layers = step_matrix[row, col]
            thickness_mm = step_layers * spec.layer_height_mm
            linear_rgb = e_linear + (substrate_linear - e_linear) * np.exp(
                -k_linear * thickness_mm,
            )
            srgb = _linear_to_srgb_uint8(linear_rgb.reshape(1, 3))[0]
            x0 = int(round((spec.margin_mm + col * (spec.block_mm + spec.gap_mm)) * pixels_per_mm))
            y0 = int(round((spec.margin_mm + row * (spec.block_mm + spec.gap_mm)) * pixels_per_mm))
            x1 = int(round((spec.margin_mm + col * (spec.block_mm + spec.gap_mm) + spec.block_mm) * pixels_per_mm))
            y1 = int(round((spec.margin_mm + row * (spec.block_mm + spec.gap_mm) + spec.block_mm) * pixels_per_mm))
            image[y0:y1, x0:x1] = srgb
    return image


def test_generate_single_stage_kit_route(monkeypatch, tmp_path: Path) -> None:
    client, _, _ = _client_with_state()
    kit_path = tmp_path / "kit.zip"
    manifest_path = tmp_path / "manifest.json"
    kit_path.write_bytes(b"zip")
    manifest_path.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_generate_single_stage_kit(*args, **kwargs):
        captured.update(kwargs)
        return SingleStageKitResult(
            zip_path=str(kit_path),
            manifest_path=str(manifest_path),
            preview_image=Image.new("RGB", (32, 32), (255, 255, 255)),
            jobs=[],
            message="ok",
        )

    monkeypatch.setattr(
        "api.routers.calibration.generate_single_stage_kit",
        _fake_generate_single_stage_kit,
    )

    response = client.post(
        "/api/calibration/generate-single-stage-kit",
        json={
            "palette": [
                {
                    "color": "White",
                    "material": "PLA Basic",
                    "hex_color": "#FFFFFF",
                    "color_name": "White",
                }
            ],
            "substrate_id": "white",
            "substrate_display_name": "White",
            "material_default": "PLA Basic",
            "layer_height_mm": 0.1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["kit_download_url"].startswith("/api/files/")
    assert body["manifest_url"].startswith("/api/files/")
    assert body["preview_url"].startswith("/api/files/")
    assert body["jobs"] == []
    assert captured["layer_height_mm"] == 0.1


def test_build_stage_matrix_creates_flat_face_down_board() -> None:
    spec = SingleStageSpec(
        grid_cols=2,
        grid_rows=1,
        block_mm=2.0,
        gap_mm=0.0,
        margin_mm=0.0,
        pixel_mm=1.0,
        layer_height_mm=0.5,
        base_mm=1.0,
        max_step_layers=2,
        step_layers=(0, 2),
        shrink_xy_mm=0.0,
    )

    voxel = _build_stage_matrix(spec)

    assert voxel.shape == (4, 2, 4)
    assert np.all(np.isin(voxel, [0, 1]))
    assert np.all(voxel[-1] == 0)
    assert int(np.count_nonzero(voxel[:, 0, 0] == 1)) == 0
    assert int(np.count_nonzero(voxel[:, 0, 3] == 1)) == 2


def test_build_stage_scene_applies_face_down_mirror_compensation() -> None:
    spec = SingleStageSpec(
        grid_cols=2,
        grid_rows=1,
        block_mm=2.0,
        gap_mm=0.0,
        margin_mm=0.0,
        pixel_mm=1.0,
        layer_height_mm=0.5,
        base_mm=1.0,
        max_step_layers=1,
        step_layers=(1, 0),
        shrink_xy_mm=0.0,
    )
    entry = PaletteEntry(
        color="Red",
        material="PLA Basic",
        hex_color="#FF0000",
        color_name="Red",
    )

    scene, preview = _build_stage_scene(
        entry,
        "white",
        "White",
        (255, 255, 255),
        spec,
    )

    step_bounds = scene.geometry["Step - Red"].bounds
    assert step_bounds[0][0] == 2.0
    assert step_bounds[1][0] == 4.0
    assert preview.getpixel((0, 0)) == (255, 0, 0)
    assert preview.getpixel((3, 0)) == (255, 255, 255)


def test_generate_single_stage_kit_overrides_layer_height_in_manifest_spec(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("core.single_stage.kit.MODELS_DIR", str(tmp_path))
    monkeypatch.setattr("core.single_stage.kit.TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(
        "core.single_stage.kit.export_scene_with_bambu_metadata",
        lambda scene, output_path, **kwargs: Path(output_path).write_bytes(b"3mf"),
    )
    monkeypatch.setattr(
        "core.single_stage.kit._resolve_colorchecker_bundle",
        lambda: (None, None),
    )

    result = generate_single_stage_kit(
        palette=[
            PaletteEntry(
                color="Red",
                material="PLA Basic",
                hex_color="#FF0000",
                color_name="Red",
            )
        ],
        layer_height_mm=0.1,
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["spec"]["layer_height_mm"] == 0.1


def test_generate_single_stage_kit_packages_one_shared_3mf(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("core.single_stage.kit.MODELS_DIR", str(tmp_path))
    monkeypatch.setattr("core.single_stage.kit.TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(
        "core.single_stage.kit.export_scene_with_bambu_metadata",
        lambda scene, output_path, **kwargs: Path(output_path).write_bytes(b"3mf"),
    )
    monkeypatch.setattr(
        "core.single_stage.kit._resolve_colorchecker_bundle",
        lambda: (None, None),
    )

    result = generate_single_stage_kit(
        palette=[
            PaletteEntry(
                color="White",
                material="PLA Basic",
                hex_color="#FFFFFF",
                color_name="White",
            ),
            PaletteEntry(
                color="Red",
                material="PLA Basic",
                hex_color="#FF0000",
                color_name="Red",
            ),
            PaletteEntry(
                color="Blue",
                material="PLA Basic",
                hex_color="#0000FF",
                color_name="Blue",
            ),
        ],
        substrate_id="white",
        substrate_display_name="White",
    )

    with zipfile.ZipFile(result.zip_path, "r") as archive:
        names = archive.namelist()

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    model_entries = [name for name in names if name.endswith(".3mf")]
    template_entries = [
        name
        for name in names
        if name.startswith("dataset_template/")
        and name.endswith("PUT_PHOTOS_AND_LABELME_JSON_HERE.txt")
    ]

    assert len(model_entries) == 1
    assert template_entries == [
        "dataset_template/white/Sample/PUT_PHOTOS_AND_LABELME_JSON_HERE.txt"
    ]
    assert manifest["shared_model_filename"] == model_entries[0]
    assert manifest["jobs"] == []


def test_extract_single_stage_route_creates_session(monkeypatch, tmp_path: Path) -> None:
    client, store, _ = _client_with_state()
    zip_path = tmp_path / "dataset.zip"
    stage_json_path = tmp_path / "1_single_stage.json"
    extract_root = tmp_path / "dataset"
    zip_path.write_bytes(b"zip")
    stage_json_path.write_text("{}", encoding="utf-8")
    extract_root.mkdir()

    async def _fake_upload_to_tempfile(*args, **kwargs):
        return str(zip_path)

    def _fake_extract_single_stage_dataset(*args, **kwargs):
        return SingleStageExtractResult(
            stage_json_path=str(stage_json_path),
            dataset_summary={
                "substrate_count": 1,
                "color_count": 1,
                "dataset_count": 1,
                "image_count": 2,
                "substrates": ["white"],
                "coverage": [{"substrate_id": "white", "colors": ["White"]}],
                "datasets": [],
            },
            warnings=["warn"],
            extracted_root=str(extract_root),
        )

    monkeypatch.setattr(
        "api.routers.single_stage.upload_to_tempfile",
        _fake_upload_to_tempfile,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.extract_single_stage_dataset",
        _fake_extract_single_stage_dataset,
    )

    response = client.post(
        "/api/extractor/extract-single-stage",
        files={"dataset_zip": ("dataset.zip", b"zip", "application/zip")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["stage_json_url"].startswith("/api/files/")
    assert body["warnings"] == ["warn"]

    session = store.get(body["session_id"])
    assert session is not None
    assert session["single_stage_stage_json_path"] == str(stage_json_path)


def test_fit_stage_a_route_uses_session(monkeypatch, tmp_path: Path) -> None:
    client, store, _ = _client_with_state()
    stage_json_path = tmp_path / "1_single_stage.json"
    params_path = tmp_path / "stage_A_parameters.json"
    stage_json_path.write_text("{}", encoding="utf-8")
    params_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    session_id = store.create()
    store.put(session_id, "single_stage_stage_json_path", str(stage_json_path))

    def _fake_fit_stage_a_from_stage_json(path: str, output_path: str | None = None):
        assert path == str(stage_json_path)
        return StageAFitResult(
            params_path=str(params_path),
            fit_summary={
                "substrate_count": 1,
                "channel_count": 6,
                "substrates": ["white"],
                "colors": ["White"],
                "overall_validation": {"mean_delta_e": 1.2},
                "warnings": [],
            },
        )

    monkeypatch.setattr(
        "api.routers.single_stage.fit_stage_a_from_stage_json",
        _fake_fit_stage_a_from_stage_json,
    )

    response = client.post(
        "/api/extractor/fit-stage-a",
        data={"session_id": session_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["stage_a_params_url"].startswith("/api/files/")
    assert body["fit_summary"]["channel_count"] == 6


def test_fit_stage_a_route_requires_input() -> None:
    client, _, _ = _client_with_state()
    response = client.post("/api/extractor/fit-stage-a", data={})
    assert response.status_code == 422


def test_fit_stage_a_route_accepts_uploaded_stage_json(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, store, registry = _client_with_state()
    uploaded_stage_json = tmp_path / "uploaded_stage.json"
    params_path = tmp_path / "stage_A_parameters.json"
    uploaded_stage_json.write_text("{}", encoding="utf-8")
    params_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    async def _fake_upload_to_tempfile(*args, **kwargs):
        return str(uploaded_stage_json)

    def _fake_fit_stage_a_from_stage_json(path: str, output_path: str | None = None):
        assert path == str(uploaded_stage_json)
        return StageAFitResult(
            params_path=str(params_path),
            fit_summary={
                "substrate_count": 1,
                "channel_count": 1,
                "substrates": ["white"],
                "colors": ["White"],
                "overall_validation": {},
                "warnings": [],
            },
        )

    monkeypatch.setattr(
        "api.routers.single_stage.upload_to_tempfile",
        _fake_upload_to_tempfile,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.fit_stage_a_from_stage_json",
        _fake_fit_stage_a_from_stage_json,
    )

    response = client.post(
        "/api/extractor/fit-stage-a",
        files={"stage_json": ("1_single_stage.json", b"{}", "application/json")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stage_a_params_url"].startswith("/api/files/")

    resolved = registry.resolve(body["stage_a_params_url"].split("/")[-1])
    assert resolved is not None
    assert resolved[0] == str(params_path)

    stored_sessions = [
        store.get(session_id)
        for session_id in list(store._store.keys())
    ]
    assert any(
        session is not None
        and session.get("single_stage_stage_json_path") == str(uploaded_stage_json)
        for session in stored_sessions
    )


def test_gradient_card_stage_a_core_extracts_and_saves_material_archive(
    tmp_path: Path,
) -> None:
    spec = SingleStageSpec(
        grid_cols=3,
        grid_rows=2,
        block_mm=10.0,
        gap_mm=0.0,
        margin_mm=0.0,
        pixel_mm=1.0,
        layer_height_mm=0.1,
        base_mm=1.0,
        max_step_layers=6,
        step_layers=(0, 1, 2, 3, 4, 6),
        shrink_xy_mm=0.0,
    )
    zip_path = tmp_path / "kit.zip"
    _write_gradient_card_manifest(zip_path, spec)

    white_substrate = np.array([0.86, 0.88, 0.9], dtype=np.float64)
    black_substrate = np.array([0.08, 0.09, 0.1], dtype=np.float64)
    expected_e = np.array([0.22, 0.18, 0.15], dtype=np.float64)
    expected_k = np.array([1.7, 1.4, 1.2], dtype=np.float64)
    white_capture = _build_gradient_card_capture(
        spec,
        white_substrate,
        expected_e,
        expected_k,
    )
    black_capture = _build_gradient_card_capture(
        spec,
        black_substrate,
        expected_e,
        expected_k,
    )
    corners = [
        [0, 0],
        [white_capture.shape[1] - 1, 0],
        [white_capture.shape[1] - 1, white_capture.shape[0] - 1],
        [0, white_capture.shape[0] - 1],
    ]

    result = extract_stage_a_material_from_gradient_cards(
        white_capture,
        black_capture,
        corners,
        corners,
        str(zip_path),
        output_path=str(tmp_path / "stage_a.json"),
    )

    assert Path(result.params_path).exists()
    payload = json.loads(Path(result.params_path).read_text(encoding="utf-8"))
    estimated_e = np.asarray(payload["parameters"]["channels"][0]["E"], dtype=np.float64)
    estimated_k = np.asarray(payload["parameters"]["channels"][0]["k"], dtype=np.float64)
    assert np.allclose(estimated_e, expected_e, atol=0.08)
    assert np.allclose(estimated_k, expected_k, atol=0.35)
    assert result.material_summary["sample_count"] == 12
    assert result.material_summary["warp_width_px"] == 600
    assert result.material_summary["warp_height_px"] == 400
    assert len(result.material_summary["sample_boxes"]) == 6
    assert result.material_summary["sample_boxes"][0]["row"] == 0
    assert result.material_summary["sample_boxes"][0]["col"] == 0
    assert result.material_summary["sample_boxes"][0]["thickness_layers"] == 0

    save_result = save_stage_a_material_archive(
        material_name="Test Material",
        params_payload=result.params_payload,
        fit_summary=result.fit_summary,
        source_summary=result.source_summary,
        material_summary=result.material_summary,
        materials_dir=str(tmp_path / "materials"),
    )

    assert Path(save_result.archive_path).exists()
    assert Path(save_result.stage_a_params_path).exists()
    saved_payload = json.loads(Path(save_result.stage_a_params_path).read_text(encoding="utf-8"))
    archive_payload = json.loads(Path(save_result.archive_path).read_text(encoding="utf-8"))
    assert saved_payload["parameters"]["channels"][0]["color_name"] == "Test Material"
    assert archive_payload["material_name"] == "Test Material"


def test_save_stage_a_material_archive_aggregates_reverification_runs(tmp_path: Path) -> None:
    materials_root = tmp_path / "materials"
    first_params = {
        "meta": {},
        "parameters": {
            "channels": [{"color_name": "PLA Basic", "E": [0.2, 0.3, 0.4], "k": [1.0, 1.1, 1.2]}],
            "substrates": [
                {"substrate_id": "white", "C0": [0.9, 0.9, 0.9]},
                {"substrate_id": "black", "C0": [0.1, 0.1, 0.1]},
            ],
        },
        "fitted_substrates": {},
        "validation": {"overall": {"mean_delta_e": 2.0}},
    }
    second_params = {
        "meta": {},
        "parameters": {
            "channels": [{"color_name": "PLA Basic", "E": [0.4, 0.5, 0.6], "k": [1.4, 1.5, 1.6]}],
            "substrates": [
                {"substrate_id": "white", "C0": [0.8, 0.8, 0.8]},
                {"substrate_id": "black", "C0": [0.2, 0.2, 0.2]},
            ],
        },
        "fitted_substrates": {},
        "validation": {"overall": {"mean_delta_e": 1.0}},
    }
    first_fit_summary = {
        "overall_validation": {"mean_delta_e": 2.0, "rmse_linear": 0.2, "channel_rmse": [0.2, 0.2, 0.2]},
        "warnings": [],
    }
    second_fit_summary = {
        "overall_validation": {"mean_delta_e": 1.0, "rmse_linear": 0.1, "channel_rmse": [0.1, 0.1, 0.1]},
        "warnings": [],
    }
    first_material_summary = {
        "estimated_rgb": [120, 130, 140],
        "estimated_k": [1.0, 1.1, 1.2],
        "white_zero_rgb": [240, 240, 240],
        "black_zero_rgb": [30, 30, 30],
        "layer_height_mm": 0.04,
        "sample_boxes": [],
    }
    second_material_summary = {
        "estimated_rgb": [150, 160, 170],
        "estimated_k": [1.4, 1.5, 1.6],
        "white_zero_rgb": [220, 220, 220],
        "black_zero_rgb": [40, 40, 40],
        "layer_height_mm": 0.04,
        "sample_boxes": [],
    }

    first_result = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=first_params,
        fit_summary=first_fit_summary,
        source_summary={"capture": 1},
        material_summary=first_material_summary,
        materials_dir=str(materials_root),
    )
    second_result = save_stage_a_material_archive(
        material_name="Should Be Ignored",
        params_payload=second_params,
        fit_summary=second_fit_summary,
        source_summary={"capture": 2},
        material_summary=second_material_summary,
        materials_dir=str(materials_root),
        existing_directory_name=first_result.material_summary["directory_name"],
    )

    assert second_result.material_summary["directory_name"] == first_result.material_summary["directory_name"]
    assert second_result.material_summary["material_name"] == "PLA Basic"
    assert second_result.material_summary["verification_count"] == 2

    saved_payload = json.loads(Path(second_result.stage_a_params_path).read_text(encoding="utf-8"))
    archive_payload = json.loads(Path(second_result.archive_path).read_text(encoding="utf-8"))
    assert archive_payload["verification_count"] == 2
    assert len(archive_payload["verification_runs"]) == 2
    assert archive_payload["material_name"] == "PLA Basic"
    assert saved_payload["meta"]["verification_count"] == 2
    assert saved_payload["parameters"]["channels"][0]["color_name"] == "PLA Basic"
    assert np.allclose(
        np.asarray(saved_payload["parameters"]["channels"][0]["E"], dtype=np.float64),
        np.asarray([0.3, 0.4, 0.5], dtype=np.float64),
    )
    assert np.allclose(
        np.asarray(saved_payload["parameters"]["channels"][0]["k"], dtype=np.float64),
        np.asarray([1.2, 1.3, 1.4], dtype=np.float64),
    )


def test_delete_saved_stage_a_material_archive_removes_directory(tmp_path: Path) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "pla-basic"
    material_dir.mkdir(parents=True)
    (material_dir / "material.json").write_text(
        json.dumps({"material_name": "PLA Basic"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (material_dir / "stage_A_parameters.json").write_text("{}", encoding="utf-8")

    result = delete_saved_stage_a_material_archive(
        directory_name="pla-basic",
        materials_dir=str(materials_root),
    )

    assert result.directory_name == "pla-basic"
    assert result.material_name == "PLA Basic"
    assert not material_dir.exists()


def test_gradient_card_stage_a_core_auto_detects_rotated_and_mirrored_capture_orientation(
    tmp_path: Path,
) -> None:
    spec = SingleStageSpec(
        grid_cols=3,
        grid_rows=2,
        block_mm=10.0,
        gap_mm=0.0,
        margin_mm=0.0,
        pixel_mm=1.0,
        layer_height_mm=0.1,
        base_mm=1.0,
        max_step_layers=6,
        step_layers=(0, 1, 2, 3, 4, 6),
        shrink_xy_mm=0.0,
    )
    zip_path = tmp_path / "kit_rotated.zip"
    _write_gradient_card_manifest(zip_path, spec)

    white_substrate = np.array([0.86, 0.88, 0.9], dtype=np.float64)
    black_substrate = np.array([0.08, 0.09, 0.1], dtype=np.float64)
    expected_e = np.array([0.22, 0.18, 0.15], dtype=np.float64)
    expected_k = np.array([1.7, 1.4, 1.2], dtype=np.float64)
    white_capture = np.rot90(
        np.fliplr(
            _build_gradient_card_capture(
                spec,
                white_substrate,
                expected_e,
                expected_k,
            )
        ),
        k=1,
    )
    black_capture = np.rot90(
        np.fliplr(
            _build_gradient_card_capture(
                spec,
                black_substrate,
                expected_e,
                expected_k,
            )
        ),
        k=1,
    )
    corners = [
        [0, 0],
        [white_capture.shape[1] - 1, 0],
        [white_capture.shape[1] - 1, white_capture.shape[0] - 1],
        [0, white_capture.shape[0] - 1],
    ]

    result = extract_stage_a_material_from_gradient_cards(
        white_capture,
        black_capture,
        corners,
        corners,
        str(zip_path),
        output_path=str(tmp_path / "stage_a_rotated.json"),
    )

    payload = json.loads(Path(result.params_path).read_text(encoding="utf-8"))
    estimated_e = np.asarray(payload["parameters"]["channels"][0]["E"], dtype=np.float64)
    estimated_k = np.asarray(payload["parameters"]["channels"][0]["k"], dtype=np.float64)
    assert np.allclose(estimated_e, expected_e, atol=0.08)
    assert np.allclose(estimated_k, expected_k, atol=0.35)
    assert result.fit_summary["overall_validation"]["mean_delta_e"] < 1.0
    assert result.source_summary["white_detected_orientation"] != "identity"
    assert result.source_summary["black_detected_orientation"] != "identity"


def test_gradient_card_stage_a_routes_compute_and_save_material(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, store, registry = _client_with_state()
    zip_path = tmp_path / "kit.zip"
    zip_path.write_bytes(b"zip")
    params_path = tmp_path / "stage_A_parameters.json"
    params_payload = {
        "parameters": {"channels": [{"color_name": "PLA Basic", "E": [0.1, 0.2, 0.3], "k": [1.0, 1.1, 1.2]}]},
        "meta": {"warnings": []},
    }
    params_path.write_text(json.dumps(params_payload), encoding="utf-8")
    fit_summary = {
        "substrate_count": 2,
        "channel_count": 1,
        "substrates": ["black", "white"],
        "colors": ["PLA Basic"],
        "overall_validation": {"mean_delta_e": 1.2},
        "warnings": [],
    }
    material_summary = {
        "sample_count": 36,
        "per_substrate_sample_count": 18,
        "grid_rows": 3,
        "grid_cols": 6,
        "layer_height_mm": 0.04,
        "thickness_layers": [25, 16, 15],
        "white_zero_rgb": [255, 255, 255],
        "black_zero_rgb": [12, 12, 12],
        "estimated_rgb": [120, 130, 140],
        "estimated_k": [1.0, 1.1, 1.2],
    }
    source_summary = {
        "kit_manifest": {"material_default": "PLA Basic"},
        "white_corner_points": [[0, 0], [100, 0], [100, 50], [0, 50]],
        "black_corner_points": [[0, 0], [100, 0], [100, 50], [0, 50]],
        "spec": {"grid_cols": 6, "grid_rows": 3},
    }
    extract_result = GradientCardStageAResult(
        params_path=str(params_path),
        params_payload=params_payload,
        fit_summary=fit_summary,
        material_summary=material_summary,
        source_summary=source_summary,
        warnings=["warn"],
        white_warp_rgb=np.zeros((32, 32, 3), dtype=np.uint8),
        black_warp_rgb=np.zeros((32, 32, 3), dtype=np.uint8),
    )

    async def _fake_upload_to_ndarray(file):
        return np.zeros((32, 32, 3), dtype=np.uint8)

    async def _fake_upload_to_tempfile(*args, **kwargs):
        return str(zip_path)

    def _fake_extract_stage_a_material_from_gradient_cards(*args, **kwargs):
        return extract_result

    archive_path = tmp_path / "materials" / "test-material" / "material.json"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(json.dumps({"material_name": "Test Material"}), encoding="utf-8")
    saved_stage_a_path = archive_path.parent / "stage_A_parameters.json"
    saved_stage_a_path.write_text(json.dumps(params_payload), encoding="utf-8")

    def _fake_save_stage_a_material_archive(**kwargs):
        assert kwargs["material_name"] == "Test Material"
        assert kwargs["existing_directory_name"] == "test-material"
        return MaterialArchiveSaveResult(
            archive_path=str(archive_path),
            stage_a_params_path=str(saved_stage_a_path),
            material_summary={
                "material_name": "Test Material",
                "directory_name": "test-material",
                "archive_path": str(archive_path),
                "stage_a_params_path": str(saved_stage_a_path),
                "verification_count": 2,
            },
        )

    monkeypatch.setattr("api.routers.single_stage.upload_to_ndarray", _fake_upload_to_ndarray)
    monkeypatch.setattr("api.routers.single_stage.upload_to_tempfile", _fake_upload_to_tempfile)
    monkeypatch.setattr(
        "api.routers.single_stage.extract_stage_a_material_from_gradient_cards",
        _fake_extract_stage_a_material_from_gradient_cards,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.save_stage_a_material_archive",
        _fake_save_stage_a_material_archive,
    )

    response = client.post(
        "/api/extractor/extract-gradient-card-stage-a",
        data={
            "white_corner_points": json.dumps([[0, 0], [100, 0], [100, 50], [0, 50]]),
            "black_corner_points": json.dumps([[0, 0], [100, 0], [100, 50], [0, 50]]),
        },
        files={
            "white_image": ("white.png", b"white", "image/png"),
            "black_image": ("black.png", b"black", "image/png"),
            "dataset_zip": ("kit.zip", b"zip", "application/zip"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stage_a_params_url"].startswith("/api/files/")
    assert body["white_warp_preview_url"].startswith("/api/files/")
    assert body["black_warp_preview_url"].startswith("/api/files/")
    assert body["warnings"] == ["warn"]

    session = store.get(body["session_id"])
    assert session is not None
    assert session["gradient_card_stage_a_params"] == params_payload
    assert session["gradient_card_material_summary"]["sample_count"] == 36

    save_response = client.post(
        "/api/extractor/save-gradient-card-material",
        data={
            "session_id": body["session_id"],
            "material_name": "Test Material",
            "target_directory_name": "test-material",
        },
    )

    assert save_response.status_code == 200
    save_body = save_response.json()
    assert save_body["material_file_url"].startswith("/api/files/")
    assert save_body["stage_a_params_url"].startswith("/api/files/")
    assert "2 runs aggregated" in save_body["message"]

    material_resolved = registry.resolve(save_body["material_file_url"].split("/")[-1])
    stage_a_resolved = registry.resolve(save_body["stage_a_params_url"].split("/")[-1])
    assert material_resolved is not None
    assert stage_a_resolved is not None
    assert material_resolved[0] == str(archive_path)
    assert stage_a_resolved[0] == str(saved_stage_a_path)


def test_list_saved_stage_a_material_archives_reads_saved_material_directory(tmp_path: Path) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "pla-basic"
    material_dir.mkdir(parents=True)
    stage_a_path = material_dir / "stage_A_parameters.json"
    archive_path = material_dir / "material.json"
    stage_a_path.write_text(json.dumps({"parameters": {}}), encoding="utf-8")
    archive_path.write_text(
        json.dumps(
            {
                "material_name": "PLA Basic",
                "created_at": "2026-04-16T10:00:00Z",
                "updated_at": "2026-04-16T11:00:00Z",
                "stage_a_params_file": "stage_A_parameters.json",
                "verification_count": 3,
                "verification_runs": [
                    {
                        "captured_at": "2026-04-16T10:00:00Z",
                        "params": {
                            "E": [0.2, 0.3, 0.4],
                            "k": [1.1, 1.2, 1.3],
                            "white_C0": [0.9, 0.91, 0.92],
                            "black_C0": [0.1, 0.11, 0.12],
                        },
                        "fit_summary": {
                            "overall_validation": {
                                "mean_delta_e": 1.23,
                                "rmse_linear": 0.015,
                            },
                        },
                        "material_summary": {
                            "estimated_rgb": [100, 120, 140],
                            "estimated_k": [1.1, 1.2, 1.3],
                        },
                        "source": {
                            "white_detected_orientation": "identity",
                            "black_detected_orientation": "rotate_90_cw",
                        },
                    },
                ],
                "fit_summary": {"overall_validation": {"mean_delta_e": 1.23}},
                "material_summary": {
                    "estimated_rgb": [100, 120, 140],
                    "layer_height_mm": 0.04,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    results = list_saved_stage_a_material_archives(materials_dir=str(materials_root))

    assert len(results) == 1
    assert results[0]["material_name"] == "PLA Basic"
    assert results[0]["directory_name"] == "pla-basic"
    assert results[0]["archive_path"] == str(archive_path)
    assert results[0]["stage_a_params_path"] == str(stage_a_path)
    assert results[0]["estimated_rgb"] == [100, 120, 140]
    assert results[0]["layer_height_mm"] == 0.04
    assert results[0]["mean_delta_e"] == 1.23
    assert results[0]["updated_at"] == "2026-04-16T11:00:00Z"
    assert results[0]["verification_count"] == 3
    assert len(results[0]["verification_history"]) == 1
    assert results[0]["verification_history"][0]["verification_index"] == 1
    assert results[0]["verification_history"][0]["rmse_linear"] == 0.015
    assert results[0]["verification_history"][0]["white_detected_orientation"] == "identity"


def test_gradient_card_material_library_route_lists_saved_materials(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, _, registry = _client_with_state()
    archive_path = tmp_path / "material.json"
    stage_a_path = tmp_path / "stage_A_parameters.json"
    archive_path.write_text("{}", encoding="utf-8")
    stage_a_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "api.routers.single_stage.list_saved_stage_a_material_archives",
        lambda: [
            {
                "material_name": "PLA Basic",
                "directory_name": "pla-basic",
                "created_at": "2026-04-16T10:00:00Z",
                "updated_at": "2026-04-16T11:00:00Z",
                "archive_path": str(archive_path),
                "stage_a_params_path": str(stage_a_path),
                "estimated_rgb": [100, 120, 140],
                "layer_height_mm": 0.04,
                "mean_delta_e": 1.23,
                "verification_count": 3,
                "verification_history": [
                    {
                        "verification_index": 1,
                        "captured_at": "2026-04-16T10:00:00Z",
                        "mean_delta_e": 1.23,
                        "rmse_linear": 0.015,
                        "estimated_rgb": [100, 120, 140],
                        "estimated_k": [1.1, 1.2, 1.3],
                        "e_values": [0.2, 0.3, 0.4],
                        "k_values": [1.1, 1.2, 1.3],
                        "white_c0_values": [0.9, 0.91, 0.92],
                        "black_c0_values": [0.1, 0.11, 0.12],
                        "white_detected_orientation": "identity",
                        "black_detected_orientation": "rotate_90_cw",
                    }
                ],
            }
        ],
    )

    response = client.get("/api/extractor/gradient-card-materials")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert len(body["materials"]) == 1
    item = body["materials"][0]
    assert item["material_name"] == "PLA Basic"
    assert item["updated_at"] == "2026-04-16T11:00:00Z"
    assert item["verification_count"] == 3
    assert len(item["verification_history"]) == 1
    assert item["verification_history"][0]["rmse_linear"] == 0.015
    assert item["material_file_url"].startswith("/api/files/")
    assert item["stage_a_params_url"].startswith("/api/files/")
    material_resolved = registry.resolve(item["material_file_url"].split("/")[-1])
    stage_a_resolved = registry.resolve(item["stage_a_params_url"].split("/")[-1])
    assert material_resolved is not None
    assert stage_a_resolved is not None
    assert material_resolved[0] == str(archive_path)
    assert stage_a_resolved[0] == str(stage_a_path)


def test_gradient_card_material_delete_route_removes_saved_material(
    monkeypatch,
) -> None:
    client, _, _ = _client_with_state()

    monkeypatch.setattr(
        "api.routers.single_stage.delete_saved_stage_a_material_archive",
        lambda directory_name: MaterialArchiveDeleteResult(
            directory_name=directory_name,
            material_name="PLA Basic",
            deleted_path=f"materials/{directory_name}",
        ),
    )

    response = client.delete("/api/extractor/gradient-card-materials/pla-basic")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["directory_name"] == "pla-basic"
    assert body["material_name"] == "PLA Basic"


def test_extract_single_stage_dataset_rejects_invalid_layout(tmp_path: Path) -> None:
    zip_path = tmp_path / "invalid_dataset.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("just_a_file.txt", "x")

    try:
        extract_single_stage_dataset(str(zip_path))
    except ValueError as exc:
        assert "{substrate_id}/{color_name}/" in str(exc)
    else:
        raise AssertionError("Expected invalid dataset layout to raise ValueError")


def test_safe_extract_zip_rejects_sibling_prefix_escape(tmp_path: Path) -> None:
    zip_path = tmp_path / "escape.zip"
    extract_dir = tmp_path / "single_stage_dataset"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("../single_stage_dataset-evil/payload.txt", "x")

    try:
        _safe_extract_zip(str(zip_path), extract_dir)
    except ValueError as exc:
        assert "Unsafe zip entry" in str(exc)
    else:
        raise AssertionError("Expected sibling-prefix escape to be rejected")


def test_extract_single_stage_route_rejects_bad_zip_and_cleans_temp_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, store, _ = _client_with_state()
    uploaded_zip = tmp_path / "dataset.zip"
    uploaded_zip.write_bytes(b"not-a-zip")

    async def _fake_upload_to_tempfile(*args, **kwargs):
        return str(uploaded_zip)

    def _fake_extract_single_stage_dataset(*args, **kwargs):
        raise zipfile.BadZipFile("File is not a zip file")

    monkeypatch.setattr(
        "api.routers.single_stage.upload_to_tempfile",
        _fake_upload_to_tempfile,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.extract_single_stage_dataset",
        _fake_extract_single_stage_dataset,
    )

    response = client.post(
        "/api/extractor/extract-single-stage",
        files={"dataset_zip": ("dataset.zip", b"not-a-zip", "application/zip")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Malformed ZIP archive"
    assert not uploaded_zip.exists()
    assert store._store == {}


def test_processing_helpers_build_summaries(monkeypatch, tmp_path: Path) -> None:
    dataset_zip = tmp_path / "dataset.zip"
    with zipfile.ZipFile(dataset_zip, "w") as archive:
        archive.writestr("dataset/white/White/img01.png", b"fake")
        archive.writestr("dataset/white/White/img01.json", "{}")

    ref_json = tmp_path / "ColorCheckerjson.json"
    ref_json.write_text("{}", encoding="utf-8")

    stage_output = tmp_path / "1_single_stage.json"
    params_output = tmp_path / "stage_A_parameters.json"

    def _fake_resolve_assets():
        return str(ref_json), None

    def _fake_run_reference_module(module_name: str, args: list[str]) -> None:
        if module_name.endswith("step1_extract_stages"):
            output_path = Path(args[args.index("--output") + 1])
            output_path.write_text(
                json.dumps(
                    {
                        "datasets": [
                            {
                                "substrate_id": "white",
                                "color_name": "White",
                                "image_count": 1,
                                "calibration": {"mode": "ok"},
                            }
                        ],
                        "meta": {"warnings": ["sample warning"]},
                    }
                ),
                encoding="utf-8",
            )
            return

        if module_name.endswith("step2_fit_stage_a"):
            output_path = Path(args[args.index("--output") + 1])
            output_path.write_text(
                json.dumps(
                    {
                        "fitted_substrates": {"white": {"C0": [1, 1, 1]}},
                        "parameters": {"channels": [{"color_name": "White"}]},
                        "validation": {"overall": {"mean_delta_e": 1.23}},
                        "meta": {"warnings": ["fit warning"]},
                    }
                ),
                encoding="utf-8",
            )
            return

        raise AssertionError(f"Unexpected module call: {module_name}")

    monkeypatch.setattr(
        "core.single_stage.processing.resolve_single_stage_colorchecker_assets",
        _fake_resolve_assets,
    )
    monkeypatch.setattr(
        "core.single_stage.processing._run_reference_module",
        _fake_run_reference_module,
    )

    extract_result = extract_single_stage_dataset(
        str(dataset_zip),
        output_path=str(stage_output),
    )
    assert extract_result.stage_json_path == str(stage_output)
    assert extract_result.dataset_summary["substrate_count"] == 1
    assert extract_result.warnings == ["sample warning"]

    fit_result = fit_stage_a_from_stage_json(
        extract_result.stage_json_path,
        output_path=str(params_output),
    )
    assert fit_result.params_path == str(params_output)
    assert fit_result.fit_summary["substrate_count"] == 1
    assert fit_result.fit_summary["channel_count"] == 1
    assert fit_result.fit_summary["warnings"] == ["fit warning"]
