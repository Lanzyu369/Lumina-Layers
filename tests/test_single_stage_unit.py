"""Single-stage workflow router tests."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from core.single_stage import (
    SingleStageExtractResult,
    SingleStageKitResult,
    StageAFitResult,
    extract_single_stage_dataset,
    fit_stage_a_from_stage_json,
)
from core.single_stage.processing import _safe_extract_zip


def _client_with_state() -> tuple[TestClient, SessionStore, FileRegistry]:
    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app), store, registry


def test_generate_single_stage_kit_route(monkeypatch, tmp_path: Path) -> None:
    client, _, _ = _client_with_state()
    kit_path = tmp_path / "kit.zip"
    manifest_path = tmp_path / "manifest.json"
    kit_path.write_bytes(b"zip")
    manifest_path.write_text("{}", encoding="utf-8")

    def _fake_generate_single_stage_kit(*args, **kwargs):
        return SingleStageKitResult(
            zip_path=str(kit_path),
            manifest_path=str(manifest_path),
            preview_image=Image.new("RGB", (32, 32), (255, 255, 255)),
            jobs=[
                {
                    "color": "White",
                    "color_name": "White",
                    "material": "PLA Basic",
                    "substrate_id": "white",
                    "substrate_display_name": "White",
                    "filename": "single_stage_white_white.3mf",
                }
            ],
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
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["kit_download_url"].startswith("/api/files/")
    assert body["manifest_url"].startswith("/api/files/")
    assert body["preview_url"].startswith("/api/files/")
    assert len(body["jobs"]) == 1


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
