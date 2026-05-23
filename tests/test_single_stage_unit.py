"""Single-stage workflow router tests."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
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
    MaterialArchiveExportResult,
    MaterialArchiveImportResult,
    MaterialArchiveSaveResult,
    MaterialArchiveUpdateResult,
    SingleStageExtractResult,
    SingleStageKitResult,
    StageAFitResult,
    delete_saved_stage_a_material_archive,
    export_saved_stage_a_material_archives,
    extract_single_stage_dataset,
    extract_stage_a_material_from_gradient_cards,
    fit_stage_a_from_stage_json,
    generate_single_stage_kit,
    import_saved_stage_a_material_archives,
    list_saved_stage_a_material_archives,
    save_stage_a_material_archive,
    update_saved_stage_a_material_archive_metadata,
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
            "printer_id": "bambu-p1s",
            "slicer": "OrcaSlicer",
            "nozzle_size": "0.2",
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
    assert captured["printer_id"] == "bambu-p1s"
    assert captured["slicer"] == "OrcaSlicer"
    assert captured["nozzle_size"] == "0.2"


def test_calibration_generate_registers_stateless_outputs_with_ttl(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, _, registry = _client_with_state()
    clock = {"now": 10_000.0}
    board_path = tmp_path / "board.3mf"
    board_path.write_bytes(b"3mf")

    monkeypatch.setattr("api.file_registry.time.time", lambda: clock["now"])
    monkeypatch.setattr(
        "api.routers.calibration.generate_calibration_board",
        lambda **kwargs: (
            str(board_path),
            Image.new("RGB", (8, 8), (255, 255, 255)),
            "ok",
        ),
    )

    response = client.post(
        "/api/calibration/generate",
        json={
            "color_mode": "4-Color (RYBW)",
            "block_size": 5,
            "gap": 0.84,
            "backing": "White",
        },
    )

    assert response.status_code == 200
    body = response.json()
    download_id = body["download_url"].rsplit("/", 1)[-1]
    preview_id = body["preview_url"].rsplit("/", 1)[-1]

    download_entry = registry.get_entry(download_id)
    preview_entry = registry.get_entry(preview_id)
    assert download_entry is not None
    assert preview_entry is not None
    assert download_entry["ttl_seconds"] == 8 * 60 * 60
    assert preview_entry["ttl_seconds"] == 8 * 60 * 60

    clock["now"] += (8 * 60 * 60) + 1
    removed = registry.cleanup_expired()

    assert removed == 2
    assert registry.resolve(download_id) is None
    assert registry.resolve(preview_id) is None
    assert not board_path.exists()


def test_calibration_generate_uses_unique_registry_session_ids_per_request(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, _, registry = _client_with_state()
    first_board_path = tmp_path / "board-1.3mf"
    second_board_path = tmp_path / "board-2.3mf"
    first_board_path.write_bytes(b"3mf-1")
    second_board_path.write_bytes(b"3mf-2")
    call_count = {"count": 0}

    def _fake_generate_calibration_board(**kwargs):
        call_count["count"] += 1
        path = first_board_path if call_count["count"] == 1 else second_board_path
        return str(path), Image.new("RGB", (8, 8), (255, 255, 255)), "ok"

    monkeypatch.setattr(
        "api.routers.calibration.generate_calibration_board",
        _fake_generate_calibration_board,
    )

    payload = {
        "color_mode": "4-Color (RYBW)",
        "block_size": 5,
        "gap": 0.84,
        "backing": "White",
    }
    response_one = client.post("/api/calibration/generate", json=payload)
    response_two = client.post("/api/calibration/generate", json=payload)

    assert response_one.status_code == 200
    assert response_two.status_code == 200

    download_id_one = response_one.json()["download_url"].rsplit("/", 1)[-1]
    download_id_two = response_two.json()["download_url"].rsplit("/", 1)[-1]
    entry_one = registry.get_entry(download_id_one)
    entry_two = registry.get_entry(download_id_two)
    assert entry_one is not None
    assert entry_two is not None
    assert entry_one["session_id"] != entry_two["session_id"]


def test_generate_single_stage_kit_route_registers_ttl_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, _, registry = _client_with_state()
    clock = {"now": 20_000.0}
    kit_path = tmp_path / "kit.zip"
    manifest_path = tmp_path / "manifest.json"
    kit_path.write_bytes(b"zip")
    manifest_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("api.file_registry.time.time", lambda: clock["now"])

    def _fake_generate_single_stage_kit(*args, **kwargs):
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

    file_ids = [
        body["kit_download_url"].rsplit("/", 1)[-1],
        body["manifest_url"].rsplit("/", 1)[-1],
        body["preview_url"].rsplit("/", 1)[-1],
    ]
    entries = [registry.get_entry(file_id) for file_id in file_ids]
    assert all(entry is not None for entry in entries)
    assert all(entry["ttl_seconds"] == 8 * 60 * 60 for entry in entries)

    clock["now"] += (8 * 60 * 60) + 1
    removed = registry.cleanup_expired()

    assert removed == 3
    assert all(registry.resolve(file_id) is None for file_id in file_ids)
    assert not kit_path.exists()
    assert not manifest_path.exists()


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


def test_build_stage_scene_preserves_step_material_name_for_slicer_metadata() -> None:
    spec = SingleStageSpec(
        grid_cols=1,
        grid_rows=1,
        block_mm=2.0,
        gap_mm=0.0,
        margin_mm=0.0,
        pixel_mm=1.0,
        layer_height_mm=0.5,
        base_mm=1.0,
        max_step_layers=1,
        step_layers=(1,),
        shrink_xy_mm=0.0,
    )
    entry = PaletteEntry(
        color="Sample",
        material="PETG Basic",
        hex_color="#808080",
        color_name="Sample",
    )

    scene, _ = _build_stage_scene(
        entry,
        "white",
        "White",
        (255, 255, 255),
        spec,
    )

    assert scene.geometry["Step - Sample"].metadata["bambu_material_name"] == "PETG Basic"
    assert "bambu_material_name" not in scene.geometry["Base - White"].metadata


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
    # Tight tolerances after precision overhaul (linear-space median sampling,
    # locked C0, fixed k-init bug): on noise-free synthetic captures the fit
    # recovers E to <5e-3 and k to <5e-2. Tolerances kept above measured
    # values to allow for numerical drift across platforms/BLAS backends.
    # 经过精度改进后，无噪声合成数据下 E 误差 <5e-3，k 误差 <5e-2。
    assert np.allclose(estimated_e, expected_e, atol=5e-3)
    assert np.allclose(estimated_k, expected_k, atol=5e-2)
    assert result.fit_summary["overall_validation"]["mean_delta_e"] < 0.2
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


def _write_updatable_material_archive(
    materials_root: Path,
    directory_name: str,
    *,
    material_name: str = "PLA Basic",
    brand: str | None = None,
) -> tuple[Path, Path]:
    """Fixture helper: write a minimal ``material.json`` + ``stage_A_parameters.json``
    pair so update/delete flows have something to act on.
    写入最小的 ``material.json`` + ``stage_A_parameters.json`` 供更新/删除流程测试使用。
    """
    material_dir = materials_root / directory_name
    material_dir.mkdir(parents=True, exist_ok=True)
    archive_payload: dict[str, object] = {
        "material_name": material_name,
        "brand": brand,
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
        "stage_a_params_file": "stage_A_parameters.json",
        "fit_summary": {
            "colors": [material_name],
            "overall_validation": {"mean_delta_e": 0.5},
        },
        "material_summary": {"estimated_rgb": [120, 130, 140]},
    }
    (material_dir / "material.json").write_text(
        json.dumps(archive_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    stage_a_payload = {
        "meta": {"material_name": material_name, "warnings": []},
        "parameters": {
            "channels": [
                {"color_name": material_name, "E": [0.1, 0.2, 0.3], "k": [1.0, 1.1, 1.2]}
            ],
        },
    }
    stage_a_path = material_dir / "stage_A_parameters.json"
    stage_a_path.write_text(
        json.dumps(stage_a_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return material_dir / "material.json", stage_a_path


def test_update_saved_stage_a_material_archive_metadata_updates_both_files(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    archive_path, stage_a_path = _write_updatable_material_archive(
        materials_root,
        "pla-basic",
        material_name="PLA Basic",
        brand="Generic",
    )

    result = update_saved_stage_a_material_archive_metadata(
        directory_name="pla-basic",
        material_name="  PLA Matte  ",
        brand="  Bambu Lab  ",
        materials_dir=str(materials_root),
    )

    assert isinstance(result, MaterialArchiveUpdateResult)
    assert result.archive_path == str(archive_path)
    assert result.stage_a_params_path == str(stage_a_path)
    archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive_payload["material_name"] == "PLA Matte"
    assert archive_payload["brand"] == "Bambu Lab"
    assert archive_payload["updated_at"] != archive_payload["created_at"]
    assert archive_payload["fit_summary"]["colors"] == ["PLA Matte"]
    stage_a_payload = json.loads(stage_a_path.read_text(encoding="utf-8"))
    assert stage_a_payload["parameters"]["channels"][0]["color_name"] == "PLA Matte"
    assert stage_a_payload["meta"]["material_name"] == "PLA Matte"
    assert result.material_summary["material_name"] == "PLA Matte"
    assert result.material_summary["brand"] == "Bambu Lab"
    assert result.material_summary["directory_name"] == "pla-basic"


def test_update_saved_stage_a_material_archive_metadata_clears_brand_on_blank(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    archive_path, _ = _write_updatable_material_archive(
        materials_root,
        "pla-basic",
        brand="Generic",
    )

    update_saved_stage_a_material_archive_metadata(
        directory_name="pla-basic",
        material_name="PLA Basic",
        brand="   ",
        materials_dir=str(materials_root),
    )

    archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive_payload["brand"] is None


def test_update_saved_stage_a_material_archive_metadata_rejects_blank_name(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    _write_updatable_material_archive(materials_root, "pla-basic")

    with pytest.raises(ValueError, match="material_name is required"):
        update_saved_stage_a_material_archive_metadata(
            directory_name="pla-basic",
            material_name="   ",
            materials_dir=str(materials_root),
        )


def test_update_saved_stage_a_material_archive_metadata_missing_archive(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    materials_root.mkdir()

    with pytest.raises(FileNotFoundError):
        update_saved_stage_a_material_archive_metadata(
            directory_name="does-not-exist",
            material_name="Ghost",
            materials_dir=str(materials_root),
        )


def test_update_saved_stage_a_material_archive_metadata_missing_stage_a_file(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    _, stage_a_path = _write_updatable_material_archive(materials_root, "pla-basic")
    stage_a_path.unlink()

    with pytest.raises(FileNotFoundError, match="Saved Stage A parameters"):
        update_saved_stage_a_material_archive_metadata(
            directory_name="pla-basic",
            material_name="PLA Basic",
            materials_dir=str(materials_root),
        )


def test_update_saved_stage_a_material_archive_metadata_overrides_estimated_rgb(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    archive_path, _ = _write_updatable_material_archive(
        materials_root,
        "pla-basic",
    )

    result = update_saved_stage_a_material_archive_metadata(
        directory_name="pla-basic",
        material_name="PLA Basic",
        estimated_rgb=[255, 128, 0],
        materials_dir=str(materials_root),
    )

    archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive_payload["material_summary"]["estimated_rgb"] == [255, 128, 0]
    assert result.material_summary["estimated_rgb"] == [255, 128, 0]


def test_update_saved_stage_a_material_archive_metadata_preserves_estimated_rgb_when_unset(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    archive_path, _ = _write_updatable_material_archive(
        materials_root,
        "pla-basic",
    )

    update_saved_stage_a_material_archive_metadata(
        directory_name="pla-basic",
        material_name="PLA Basic",
        brand="Generic",
        materials_dir=str(materials_root),
    )

    archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive_payload["material_summary"]["estimated_rgb"] == [120, 130, 140]


@pytest.mark.parametrize(
    "invalid_value",
    [
        [255, 128],
        [255, 128, 0, 10],
        [256, 0, 0],
        [-1, 0, 0],
        ["ff", "80", "00"],
        "not-a-list",
    ],
)
def test_update_saved_stage_a_material_archive_metadata_rejects_invalid_estimated_rgb(
    tmp_path: Path,
    invalid_value,
) -> None:
    materials_root = tmp_path / "materials"
    _write_updatable_material_archive(materials_root, "pla-basic")

    with pytest.raises(ValueError):
        update_saved_stage_a_material_archive_metadata(
            directory_name="pla-basic",
            material_name="PLA Basic",
            estimated_rgb=invalid_value,
            materials_dir=str(materials_root),
        )


def test_extractor_update_gradient_card_material_route_persists_edits(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, _, _ = _client_with_state()
    materials_root = tmp_path / "materials"
    archive_path, stage_a_path = _write_updatable_material_archive(
        materials_root,
        "pla-basic",
        material_name="PLA Basic",
        brand="Generic",
    )
    monkeypatch.setattr(
        "core.single_stage.materials.MATERIALS_DIR",
        str(materials_root),
    )

    response = client.patch(
        "/api/extractor/gradient-card-materials/pla-basic",
        json={"material_name": "PLA Matte", "brand": "Bambu Lab"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["material"]["material_name"] == "PLA Matte"
    assert body["material"]["brand"] == "Bambu Lab"
    assert body["material"]["directory_name"] == "pla-basic"
    assert body["material"]["material_file_url"].startswith("/api/files/")
    assert body["material"]["stage_a_params_url"].startswith("/api/files/")
    archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive_payload["material_name"] == "PLA Matte"
    assert archive_payload["brand"] == "Bambu Lab"
    stage_a_payload = json.loads(stage_a_path.read_text(encoding="utf-8"))
    assert stage_a_payload["parameters"]["channels"][0]["color_name"] == "PLA Matte"


def test_extractor_update_gradient_card_material_route_rejects_blank_name(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, _, _ = _client_with_state()
    materials_root = tmp_path / "materials"
    _write_updatable_material_archive(materials_root, "pla-basic")
    monkeypatch.setattr(
        "core.single_stage.materials.MATERIALS_DIR",
        str(materials_root),
    )

    response = client.patch(
        "/api/extractor/gradient-card-materials/pla-basic",
        json={"material_name": "   ", "brand": "Bambu Lab"},
    )

    assert response.status_code == 422


def test_extractor_update_gradient_card_material_route_overrides_estimated_rgb(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, _, _ = _client_with_state()
    materials_root = tmp_path / "materials"
    archive_path, _ = _write_updatable_material_archive(
        materials_root,
        "pla-basic",
        material_name="PLA Basic",
    )
    monkeypatch.setattr(
        "core.single_stage.materials.MATERIALS_DIR",
        str(materials_root),
    )

    response = client.patch(
        "/api/extractor/gradient-card-materials/pla-basic",
        json={
            "material_name": "PLA Basic",
            "brand": None,
            "estimated_rgb": [255, 128, 0],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["material"]["estimated_rgb"] == [255, 128, 0]
    archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive_payload["material_summary"]["estimated_rgb"] == [255, 128, 0]


def test_extractor_update_gradient_card_material_route_rejects_invalid_estimated_rgb(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, _, _ = _client_with_state()
    materials_root = tmp_path / "materials"
    _write_updatable_material_archive(materials_root, "pla-basic")
    monkeypatch.setattr(
        "core.single_stage.materials.MATERIALS_DIR",
        str(materials_root),
    )

    response = client.patch(
        "/api/extractor/gradient-card-materials/pla-basic",
        json={
            "material_name": "PLA Basic",
            "estimated_rgb": [300, 0, 0],
        },
    )

    assert response.status_code == 422


def test_extractor_update_gradient_card_material_route_missing_archive(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, _, _ = _client_with_state()
    materials_root = tmp_path / "materials"
    materials_root.mkdir()
    monkeypatch.setattr(
        "core.single_stage.materials.MATERIALS_DIR",
        str(materials_root),
    )

    response = client.patch(
        "/api/extractor/gradient-card-materials/does-not-exist",
        json={"material_name": "Ghost"},
    )

    assert response.status_code == 404


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
    # Same tight tolerances as the identity-orientation test — perspective
    # warp of a rotated+mirrored capture should not degrade fit accuracy
    # beyond the noise-free synthetic baseline.
    # 旋转翻转后仍应达到与 identity 方向一致的精度。
    assert np.allclose(estimated_e, expected_e, atol=5e-3)
    assert np.allclose(estimated_k, expected_k, atol=5e-2)
    assert result.fit_summary["overall_validation"]["mean_delta_e"] < 0.2
    assert result.source_summary["white_detected_orientation"] != "identity"
    assert result.source_summary["black_detected_orientation"] != "identity"


def test_gradient_card_stage_a_core_is_robust_to_image_noise(tmp_path: Path) -> None:
    """Regression test for noise robustness after precision overhaul.
    精度改进后对图像噪声鲁棒性的回归测试。

    Adds independent Gaussian noise to each pixel of both substrate captures
    and asserts that the fit still recovers E/k well within a conservative
    budget. This exercises the linear-space-median sampling path (which
    should reject the noise tails) and locked-C0 path (which should stay
    anchored to the measured zero-thickness observation).

    向像素加入独立高斯噪声后，仍应满足保守的 E/k 误差预算。
    """
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
    zip_path = tmp_path / "kit_noisy.zip"
    _write_gradient_card_manifest(zip_path, spec)

    white_substrate = np.array([0.86, 0.88, 0.9], dtype=np.float64)
    black_substrate = np.array([0.08, 0.09, 0.1], dtype=np.float64)
    expected_e = np.array([0.22, 0.18, 0.15], dtype=np.float64)
    expected_k = np.array([1.7, 1.4, 1.2], dtype=np.float64)
    clean_white = _build_gradient_card_capture(spec, white_substrate, expected_e, expected_k)
    clean_black = _build_gradient_card_capture(spec, black_substrate, expected_e, expected_k)

    # Gaussian noise with sigma=6 in sRGB uint8 space — roughly comparable to
    # a modern phone's ISO 400 sensor noise after JPEG. (与手机 ISO 400 拍摄噪声相当)
    rng = np.random.default_rng(42)
    white_noisy = np.clip(
        clean_white.astype(np.int16) + rng.normal(0.0, 6.0, clean_white.shape).astype(np.int16),
        0,
        255,
    ).astype(np.uint8)
    black_noisy = np.clip(
        clean_black.astype(np.int16) + rng.normal(0.0, 6.0, clean_black.shape).astype(np.int16),
        0,
        255,
    ).astype(np.uint8)

    corners = [
        [0, 0],
        [white_noisy.shape[1] - 1, 0],
        [white_noisy.shape[1] - 1, white_noisy.shape[0] - 1],
        [0, white_noisy.shape[0] - 1],
    ]

    result = extract_stage_a_material_from_gradient_cards(
        white_noisy,
        black_noisy,
        corners,
        corners,
        str(zip_path),
        output_path=str(tmp_path / "stage_a_noisy.json"),
    )
    payload = json.loads(Path(result.params_path).read_text(encoding="utf-8"))
    estimated_e = np.asarray(payload["parameters"]["channels"][0]["E"], dtype=np.float64)
    estimated_k = np.asarray(payload["parameters"]["channels"][0]["k"], dtype=np.float64)

    # Conservative noise-budget tolerances. Observed values on a reference run
    # are ~2e-3 for E and ~2e-2 for k; margin accounts for BLAS/platform drift.
    # (观测值约 E<2e-3，k<2e-2；留够不同平台的数值波动余量)
    assert np.allclose(estimated_e, expected_e, atol=1e-2)
    assert np.allclose(estimated_k, expected_k, atol=1e-1)
    assert result.fit_summary["overall_validation"]["mean_delta_e"] < 1.0


def test_gradient_card_stage_a_core_locks_c0_to_measured_zero_thickness_samples(
    tmp_path: Path,
) -> None:
    """Regression guard: fitted C0 must equal the measured zero-thickness sample.
    回归校验：拟合出的 C0 必须等于零厚度格的实测值（不再作为自由参数）。
    """
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
    zip_path = tmp_path / "kit_c0.zip"
    _write_gradient_card_manifest(zip_path, spec)

    white_substrate = np.array([0.84, 0.85, 0.88], dtype=np.float64)
    black_substrate = np.array([0.05, 0.06, 0.07], dtype=np.float64)
    expected_e = np.array([0.30, 0.25, 0.20], dtype=np.float64)
    expected_k = np.array([1.5, 1.3, 1.1], dtype=np.float64)
    white_capture = _build_gradient_card_capture(spec, white_substrate, expected_e, expected_k)
    black_capture = _build_gradient_card_capture(spec, black_substrate, expected_e, expected_k)
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
        output_path=str(tmp_path / "stage_a_c0.json"),
    )
    payload = json.loads(Path(result.params_path).read_text(encoding="utf-8"))
    white_c0 = np.asarray(
        next(
            substrate["C0"]
            for substrate in payload["parameters"]["substrates"]
            if substrate["substrate_id"] == "white"
        ),
        dtype=np.float64,
    )
    black_c0 = np.asarray(
        next(
            substrate["C0"]
            for substrate in payload["parameters"]["substrates"]
            if substrate["substrate_id"] == "black"
        ),
        dtype=np.float64,
    )
    # C0 is locked to the median of the zero-thickness cell in linear RGB space.
    # JPEG/rendering losses keep the gap within a few thousandths.
    # (C0 锁定为零厚度格中位数，渲染误差应在千分之几)
    assert np.allclose(white_c0, white_substrate, atol=5e-3)
    assert np.allclose(black_c0, black_substrate, atol=5e-3)


def test_gradient_card_stage_a_core_flags_flat_substrate_and_recommends_manual_override(
    tmp_path: Path,
) -> None:
    """White-on-white captures must surface a 'flat substrate' diagnostic
    and a Chinese warning steering the user toward the manual override.
    白底白色耗材：必须给出"基底信号过弱"诊断与手动覆盖提示。

    Real-world failure mode reported by user: a pure white material on a
    white substrate has near-zero gradient signal, so the joint-fit
    orientation search may pick an arbitrary rotation. We do NOT auto-lock
    (would degrade legitimate low-absorption materials); instead we expose
    ``signal_strength`` + a clear warning so the user knows to override.
    """
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
    zip_path = tmp_path / "kit_white_on_white.zip"
    _write_gradient_card_manifest(zip_path, spec)

    # Material E ≈ substrate → all white cells look identical regardless of
    # thickness — no usable orientation gradient on the white capture.
    white_substrate = np.array([0.95, 0.96, 0.97], dtype=np.float64)
    black_substrate = np.array([0.04, 0.05, 0.06], dtype=np.float64)
    expected_e = np.array([0.93, 0.94, 0.95], dtype=np.float64)
    expected_k = np.array([2.5, 2.7, 3.0], dtype=np.float64)
    white_capture = _build_gradient_card_capture(spec, white_substrate, expected_e, expected_k)
    black_capture = _build_gradient_card_capture(spec, black_substrate, expected_e, expected_k)
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
        output_path=str(tmp_path / "stage_a_white_on_white.json"),
    )

    white_info = result.source_summary["white_orientation_info"]
    black_info = result.source_summary["black_orientation_info"]
    # White is flagged flat — but NOT auto-locked. The user is steered toward
    # manual override via a clear warning. (不自动收缩候选，仅警示)
    assert white_info["flat"] is True
    assert white_info["manual_override"] is None
    assert white_info["locked_to"] is None
    # Diagnostic signal strengths are present and ordered as expected.
    assert white_info["signal_strength"] < 0.015
    assert black_info["signal_strength"] > white_info["signal_strength"]
    # Clear Chinese warning steering user to the manual orientation UI.
    assert any(
        "白底" in w and "纯色块位置" in w for w in result.warnings
    )


def test_gradient_card_stage_a_core_does_not_auto_lock_orientation_for_low_absorption_materials(
    tmp_path: Path,
) -> None:
    """Low-absorption colored materials (low k) produce small per-cell
    variance but the orientation IS still recoverable from the data — the
    auto-detector must NOT collapse to identity in these cases.
    弱吸收彩色耗材方差天然较小，但方向仍可由数据决定，自动检测不得强制锁 identity。
    """
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
    zip_path = tmp_path / "kit_low_absorption.zip"
    _write_gradient_card_manifest(zip_path, spec)

    # Same data as the rotated-orientation regression test: low k (1.2-1.7)
    # plus narrow C0/E gap on the black substrate produce small std, but the
    # joint fit can still determine the correct orientation.
    white_substrate = np.array([0.86, 0.88, 0.9], dtype=np.float64)
    black_substrate = np.array([0.08, 0.09, 0.1], dtype=np.float64)
    expected_e = np.array([0.22, 0.18, 0.15], dtype=np.float64)
    expected_k = np.array([1.7, 1.4, 1.2], dtype=np.float64)
    rotated_white = np.rot90(
        np.fliplr(_build_gradient_card_capture(spec, white_substrate, expected_e, expected_k)),
        k=1,
    )
    rotated_black = np.rot90(
        np.fliplr(_build_gradient_card_capture(spec, black_substrate, expected_e, expected_k)),
        k=1,
    )
    corners = [
        [0, 0],
        [rotated_white.shape[1] - 1, 0],
        [rotated_white.shape[1] - 1, rotated_white.shape[0] - 1],
        [0, rotated_white.shape[0] - 1],
    ]

    result = extract_stage_a_material_from_gradient_cards(
        rotated_white,
        rotated_black,
        corners,
        corners,
        str(zip_path),
        output_path=str(tmp_path / "stage_a_low_abs.json"),
    )
    # The detected orientation must NOT be identity (the rotated capture
    # genuinely needs a non-identity warp to recover the canonical layout).
    # 旋转捕获必须自动选择非 identity 方向。
    assert result.source_summary["white_detected_orientation"] != "identity"
    # Manual override fields stay clean (no auto-locking).
    white_info = result.source_summary["white_orientation_info"]
    assert white_info["manual_override"] is None
    assert white_info["locked_to"] is None


def test_gradient_card_stage_a_core_respects_manual_white_orientation_override(
    tmp_path: Path,
) -> None:
    """Manual orientation override must bypass auto-detection entirely.
    手动方向覆盖必须完全绕过自动检测。
    """
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
    zip_path = tmp_path / "kit_manual.zip"
    _write_gradient_card_manifest(zip_path, spec)

    white_substrate = np.array([0.86, 0.88, 0.9], dtype=np.float64)
    black_substrate = np.array([0.08, 0.09, 0.1], dtype=np.float64)
    expected_e = np.array([0.22, 0.18, 0.15], dtype=np.float64)
    expected_k = np.array([1.7, 1.4, 1.2], dtype=np.float64)
    white_capture = _build_gradient_card_capture(spec, white_substrate, expected_e, expected_k)
    black_capture = _build_gradient_card_capture(spec, black_substrate, expected_e, expected_k)
    corners = [
        [0, 0],
        [white_capture.shape[1] - 1, 0],
        [white_capture.shape[1] - 1, white_capture.shape[0] - 1],
        [0, white_capture.shape[0] - 1],
    ]

    # Force a deliberately wrong orientation; the result must reflect the user's
    # explicit choice (manual_override + locked_to set), even if it's wrong.
    result = extract_stage_a_material_from_gradient_cards(
        white_capture,
        black_capture,
        corners,
        corners,
        str(zip_path),
        output_path=str(tmp_path / "stage_a_manual.json"),
        manual_white_orientation="rotate_180",
        manual_black_orientation="identity",
    )
    white_info = result.source_summary["white_orientation_info"]
    black_info = result.source_summary["black_orientation_info"]
    assert white_info["manual_override"] == "rotate_180"
    assert white_info["locked_to"] == "rotate_180"
    assert black_info["manual_override"] == "identity"
    assert result.source_summary["white_detected_orientation"] == "rotate_180"
    assert result.source_summary["black_detected_orientation"] == "identity"


def test_gradient_card_stage_a_core_rejects_invalid_manual_orientation_label(
    tmp_path: Path,
) -> None:
    """Invalid orientation labels must raise ``ValueError`` early.
    非法方向标签应在调用早期抛出 ValueError。
    """
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
    zip_path = tmp_path / "kit_invalid.zip"
    _write_gradient_card_manifest(zip_path, spec)
    white_substrate = np.array([0.86, 0.88, 0.9], dtype=np.float64)
    black_substrate = np.array([0.08, 0.09, 0.1], dtype=np.float64)
    e_arr = np.array([0.22, 0.18, 0.15], dtype=np.float64)
    k_arr = np.array([1.7, 1.4, 1.2], dtype=np.float64)
    white_capture = _build_gradient_card_capture(spec, white_substrate, e_arr, k_arr)
    black_capture = _build_gradient_card_capture(spec, black_substrate, e_arr, k_arr)
    corners = [
        [0, 0],
        [white_capture.shape[1] - 1, 0],
        [white_capture.shape[1] - 1, white_capture.shape[0] - 1],
        [0, white_capture.shape[0] - 1],
    ]

    with pytest.raises(ValueError, match="Invalid orientation label"):
        extract_stage_a_material_from_gradient_cards(
            white_capture,
            black_capture,
            corners,
            corners,
            str(zip_path),
            manual_white_orientation="not_a_real_orientation",
        )


def test_gradient_card_stage_a_routes_compute_and_save_material(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, store, registry = _client_with_state()
    clock = {"now": 1_000.0}
    monkeypatch.setattr("api.file_registry.time.time", lambda: clock["now"])
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

    clock["now"] += 86_400
    removed = registry.cleanup_expired()
    assert removed == 4
    assert registry.resolve(save_body["material_file_url"].split("/")[-1]) is None
    assert registry.resolve(save_body["stage_a_params_url"].split("/")[-1]) is None


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
    clock = {"now": 2_000.0}
    monkeypatch.setattr("api.file_registry.time.time", lambda: clock["now"])
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

    clock["now"] += 86_400
    removed = registry.cleanup_expired()
    assert removed == 2
    assert registry.resolve(item["material_file_url"].split("/")[-1]) is None
    assert registry.resolve(item["stage_a_params_url"].split("/")[-1]) is None


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


def test_export_saved_stage_a_material_archives_writes_manifest_and_files(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "BrandA" / "pla-basic"
    material_dir.mkdir(parents=True)
    archive_path = material_dir / "material.json"
    stage_a_path = material_dir / "stage_A_parameters.json"
    archive_path.write_text(
        json.dumps(
            {
                "material_name": "PLA Basic",
                "created_at": "2026-04-16T10:00:00Z",
                "updated_at": "2026-04-16T11:00:00Z",
                "stage_a_params_file": "stage_A_parameters.json",
                "verification_count": 2,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    stage_a_path.write_text(
        json.dumps({"parameters": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    zip_output = tmp_path / "materials_export.zip"

    result = export_saved_stage_a_material_archives(
        directory_names=["BrandA/pla-basic"],
        materials_dir=str(materials_root),
        output_path=str(zip_output),
    )

    assert result.archive_path == str(zip_output)
    assert result.exported_directory_names == ["BrandA/pla-basic"]
    with zipfile.ZipFile(zip_output, "r") as archive:
        members = set(archive.namelist())
        assert "lumina_material_export.json" in members
        assert "materials/BrandA/pla-basic/material.json" in members
        assert "materials/BrandA/pla-basic/stage_A_parameters.json" in members
        manifest = json.loads(
            archive.read("lumina_material_export.json").decode("utf-8")
        )
    assert manifest["kind"] == "lumina_material_export"
    assert manifest["directory_names"] == ["BrandA/pla-basic"]


def test_import_saved_stage_a_material_archives_copies_materials_and_renames_collisions(
    tmp_path: Path,
) -> None:
    exported_zip = tmp_path / "materials_import.zip"
    with zipfile.ZipFile(exported_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "lumina_material_export.json",
            json.dumps(
                {
                    "schema_version": "1.0",
                    "kind": "lumina_material_export",
                    "directory_names": ["BrandA/pla-basic"],
                    "material_count": 1,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        archive.writestr(
            "materials/BrandA/pla-basic/material.json",
            json.dumps(
                {
                    "material_name": "PLA Basic Imported",
                    "created_at": "2026-04-16T10:00:00Z",
                    "updated_at": "2026-04-16T11:00:00Z",
                    "stage_a_params_file": "stage_A_parameters.json",
                    "verification_count": 4,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        archive.writestr(
            "materials/BrandA/pla-basic/stage_A_parameters.json",
            json.dumps({"parameters": {}}, ensure_ascii=False, indent=2),
        )

    materials_root = tmp_path / "materials"
    existing_dir = materials_root / "BrandA" / "pla-basic"
    existing_dir.mkdir(parents=True)
    (existing_dir / "material.json").write_text("{}", encoding="utf-8")
    (existing_dir / "stage_A_parameters.json").write_text("{}", encoding="utf-8")

    result = import_saved_stage_a_material_archives(
        archive_path=str(exported_zip),
        materials_dir=str(materials_root),
    )

    assert len(result.imported_materials) == 1
    imported_item = result.imported_materials[0]
    assert imported_item["material_name"] == "PLA Basic Imported"
    assert imported_item["directory_name"].startswith("BrandA/pla-basic_")
    imported_dir = materials_root / Path(imported_item["directory_name"])
    assert imported_dir.exists() is True
    assert (imported_dir / "material.json").exists() is True
    assert (imported_dir / "stage_A_parameters.json").exists() is True


def test_gradient_card_material_export_route_returns_download_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, _, registry = _client_with_state()
    exported_zip = tmp_path / "exported-materials.zip"
    exported_zip.write_bytes(b"zip")

    monkeypatch.setattr(
        "api.routers.single_stage.export_saved_stage_a_material_archives",
        lambda directory_names: MaterialArchiveExportResult(
            archive_path=str(exported_zip),
            download_filename="materials.zip",
            exported_directory_names=list(directory_names),
        ),
    )

    response = client.post(
        "/api/extractor/gradient-card-materials/export",
        json={"directory_names": ["pla-basic", "brand-a/pla-plus"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["filename"] == "materials.zip"
    assert body["download_url"].startswith("/api/files/")
    assert body["exported_directory_names"] == ["pla-basic", "brand-a/pla-plus"]
    resolved = registry.resolve(body["download_url"].split("/")[-1])
    assert resolved is not None
    assert resolved[0] == str(exported_zip)


def test_gradient_card_material_import_route_imports_multiple_archives(
    monkeypatch,
) -> None:
    client, _, _ = _client_with_state()
    uploaded_paths = ["C:/tmp/material-a.zip", "C:/tmp/material-b.zip"]
    upload_index = {"value": 0}
    seen_import_paths: list[str] = []
    removed_paths: list[str] = []

    async def _fake_upload_to_tempfile(*args, **kwargs):
        index = upload_index["value"]
        upload_index["value"] += 1
        return uploaded_paths[index]

    def _fake_import_saved_stage_a_material_archives(*, archive_path: str):
        seen_import_paths.append(archive_path)
        suffix = "a" if archive_path.endswith("material-a.zip") else "b"
        return MaterialArchiveImportResult(
            imported_materials=[
                {
                    "material_name": f"PLA {suffix.upper()}",
                    "directory_name": f"pla-{suffix}",
                    "brand": None,
                    "archive_path": f"materials/pla-{suffix}/material.json",
                    "stage_a_params_path": f"materials/pla-{suffix}/stage_A_parameters.json",
                    "verification_count": 1,
                    "created_at": "2026-04-16T10:00:00Z",
                    "updated_at": "2026-04-16T10:00:00Z",
                }
            ]
        )

    monkeypatch.setattr(
        "api.routers.single_stage.upload_to_tempfile",
        _fake_upload_to_tempfile,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.import_saved_stage_a_material_archives",
        _fake_import_saved_stage_a_material_archives,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.os.remove",
        lambda path: removed_paths.append(path),
    )

    response = client.post(
        "/api/extractor/gradient-card-materials/import",
        files=[
            ("archives", ("materials-a.zip", b"zip-a", "application/zip")),
            ("archives", ("materials-b.zip", b"zip-b", "application/zip")),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["imported_count"] == 2
    assert [item["directory_name"] for item in body["imported_materials"]] == [
        "pla-a",
        "pla-b",
    ]
    assert seen_import_paths == uploaded_paths
    assert removed_paths == uploaded_paths


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


# ---------------------------------------------------------------------------
# image_source whitelist (API <-> UI lock-step)
# image_source 白名单（API 与 UI 双锁）
# ---------------------------------------------------------------------------


class TestNormalizeImageSource:
    """Unit tests for ``_normalize_image_source``.

    The helper keeps the API explicit: default/blank values let the core use
    raw, while restored is accepted only when the caller labels it directly.
    """

    def test_none_passes_through(self) -> None:
        from api.routers.single_stage import _normalize_image_source

        assert _normalize_image_source(None) is None

    def test_blank_treated_as_none(self) -> None:
        from api.routers.single_stage import _normalize_image_source

        assert _normalize_image_source("") is None
        assert _normalize_image_source("   ") is None

    def test_raw_is_normalized_lowercase(self) -> None:
        from api.routers.single_stage import _normalize_image_source

        assert _normalize_image_source("raw") == "raw"
        assert _normalize_image_source("RAW") == "raw"
        assert _normalize_image_source("  Raw  ") == "raw"

    def test_restored_is_normalized_lowercase(self) -> None:
        from api.routers.single_stage import _normalize_image_source

        assert _normalize_image_source("restored") == "restored"
        assert _normalize_image_source("RESTORED") == "restored"
        assert _normalize_image_source("  Restored  ") == "restored"

    def test_unknown_value_is_rejected_with_422(self) -> None:
        from fastapi import HTTPException

        from api.routers.single_stage import _normalize_image_source

        with pytest.raises(HTTPException) as exc_info:
            _normalize_image_source("totally-bogus")
        assert exc_info.value.status_code == 422


def test_extract_gradient_card_endpoint_accepts_explicit_restored_image_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The HTTP endpoint must forward explicit ``restored`` to the core."""
    from api.colorchecker_artifacts import COLORCHECKER_FULL_PURPOSE

    client, _, registry = _client_with_state()
    white_path = tmp_path / "white-full.png"
    black_path = tmp_path / "black-full.png"
    Image.new("RGB", (8, 8), (255, 255, 255)).save(white_path)
    Image.new("RGB", (8, 8), (0, 0, 0)).save(black_path)
    white_id = registry.register_path(
        "colorchecker:white",
        str(white_path),
        "white-full.png",
        ttl_seconds=600,
        is_public=False,
        purpose=COLORCHECKER_FULL_PURPOSE,
    )
    black_id = registry.register_path(
        "colorchecker:black",
        str(black_path),
        "black-full.png",
        ttl_seconds=600,
        is_public=False,
        purpose=COLORCHECKER_FULL_PURPOSE,
    )

    seen: dict[str, str | None] = {"image_source": None}

    async def _upload_to_ndarray(*_args, **_kwargs):  # noqa: ANN001
        raise AssertionError("restored ColorChecker extraction must use full artifact ids")

    async def _upload_to_tempfile(*_args, **_kwargs):  # noqa: ANN001
        return str(tmp_path / "kit.zip")

    def _extract(*_args, image_source=None, **_kwargs):  # noqa: ANN001
        from types import SimpleNamespace

        seen["image_source"] = image_source
        params_path = tmp_path / "stage_a.json"
        params_path.write_text("{}", encoding="utf-8")
        return SimpleNamespace(
            params_path=str(params_path),
            params_payload={"meta": {"image_source": image_source}},
            fit_summary={
                "substrate_count": 2,
                "channel_count": 4,
                "substrates": ["white", "black"],
                "colors": ["C0", "C1", "C2", "C3"],
                "overall_validation": {},
                "warnings": [],
            },
            material_summary={
                "sample_count": 2,
                "per_substrate_sample_count": 1,
                "grid_rows": 1,
                "grid_cols": 1,
                "layer_height_mm": 0.2,
            },
            source_summary={"image_source": image_source},
            white_warp_rgb=np.zeros((8, 8, 3), dtype=np.uint8),
            black_warp_rgb=np.zeros((8, 8, 3), dtype=np.uint8),
            warnings=[],
        )

    monkeypatch.setattr(
        "api.routers.single_stage.upload_to_ndarray", _upload_to_ndarray
    )
    monkeypatch.setattr(
        "api.routers.single_stage.upload_to_tempfile", _upload_to_tempfile
    )
    monkeypatch.setattr(
        "api.routers.single_stage.extract_stage_a_material_from_gradient_cards",
        _extract,
    )

    response = client.post(
        "/api/extractor/extract-gradient-card-stage-a",
        data={
            "white_corner_points": json.dumps([[0, 0], [1, 0], [1, 1], [0, 1]]),
            "black_corner_points": json.dumps([[0, 0], [1, 0], [1, 1], [0, 1]]),
            "white_colorchecker_file_id": white_id,
            "black_colorchecker_file_id": black_id,
            "white_corner_points_width": "1",
            "white_corner_points_height": "1",
            "black_corner_points_width": "1",
            "black_corner_points_height": "1",
            "image_source": "restored",
        },
        files={
            "dataset_zip": ("kit.zip", b"zip", "application/zip"),
        },
    )

    assert response.status_code == 200
    assert seen["image_source"] == "restored"
