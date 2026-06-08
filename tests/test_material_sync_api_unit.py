"""Material sync API tests."""

from __future__ import annotations

import json
import hashlib
import zipfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from api.app import create_app
from core.single_stage import refresh_material_sync_from_registry


def _client() -> TestClient:
    return TestClient(create_app())


def _write_v2_material_package(
    zip_path: Path,
    *,
    material_id: str = "mat_sync_test",
    revision_id: str = "rev_sync_test",
    local_directory: str = "BrandA/pla-basic",
) -> str:
    material_payload = json.dumps(
        {
            "brand": "BrandA",
            "material_name": "PLA Basic Imported",
            "stage_a_params_file": "stage_A_parameters.json",
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    stage_a_payload = json.dumps(
        {
            "meta": {},
            "parameters": {
                "channels": [
                    {"color_name": "PLA Basic Imported", "E": [0.1, 0.2, 0.3], "k": [1.0, 1.1, 1.2]}
                ],
            },
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    material_hash = hashlib.sha256(material_payload).hexdigest()
    stage_a_hash = hashlib.sha256(stage_a_payload).hexdigest()
    content_hash = hashlib.sha256(
        f"material.json:{material_hash}\nstage_A_parameters.json:{stage_a_hash}".encode(
            "utf-8"
        )
    ).hexdigest()
    material_path = f"materials/{local_directory}/material.json"
    stage_a_path = f"materials/{local_directory}/stage_A_parameters.json"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(material_path, material_payload)
        archive.writestr(stage_a_path, stage_a_payload)
        archive.writestr(
            "lumina_material_bundle.json",
            json.dumps(
                {
                    "kind": "lumina_material_bundle",
                    "schema_version": "2.0",
                    "exported_at": "2026-06-08T00:00:00+00:00",
                    "material_count": 1,
                    "packages": [
                        {
                            "material_id": material_id,
                            "revision_id": revision_id,
                            "content_hash": f"sha256:{content_hash}",
                            "channel": "team",
                            "visibility": "team",
                            "local_directory": local_directory,
                            "display": {
                                "brand": "BrandA",
                                "material_name": "PLA Basic Imported",
                            },
                            "files": [
                                {
                                    "path": material_path,
                                    "role": "material_archive",
                                    "sha256": material_hash,
                                    "bytes": len(material_payload),
                                    "required": True,
                                },
                                {
                                    "path": stage_a_path,
                                    "role": "stage_a_parameters",
                                    "sha256": stage_a_hash,
                                    "bytes": len(stage_a_payload),
                                    "required": True,
                                },
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return f"sha256:{content_hash}"


def test_material_sync_status_returns_empty_state_when_index_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    monkeypatch.setattr("core.single_stage.materials.MATERIALS_DIR", str(materials_root))

    response = _client().get("/api/material-sync/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["index_state"] == "missing"
    assert body["installed_count"] == 0
    assert body["installed"] == []


def test_material_sync_install_imports_v2_package_and_updates_status(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    monkeypatch.setattr("core.single_stage.materials.MATERIALS_DIR", str(materials_root))
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(package_path)

    install_response = _client().post(
        "/api/material-sync/install",
        files={
            "archive": (
                "material_package.zip",
                package_path.read_bytes(),
                "application/zip",
            )
        },
    )

    assert install_response.status_code == 200
    install_body = install_response.json()
    assert install_body["status"] == "ok"
    assert install_body["installed_count"] == 1
    assert install_body["installed_materials"][0]["directory_name"] == "BrandA/pla-basic"

    status_response = _client().get("/api/material-sync/status")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["index_state"] == "ready"
    assert status_body["installed_count"] == 1
    assert status_body["installed"][0]["material_id"] == "mat_sync_test"
    assert status_body["installed"][0]["revision_id"] == "rev_sync_test"
    assert status_body["installed"][0]["content_hash"] == content_hash
    assert status_body["installed"][0]["local_exists"] is True
    assert status_body["installed"][0]["material_file_exists"] is True


def test_material_sync_install_rejects_non_zip_upload(tmp_path: Path) -> None:
    response = _client().post(
        "/api/material-sync/install",
        files={"archive": ("not-a-package.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 422


def test_material_sync_refresh_requires_registry_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    monkeypatch.setattr("core.single_stage.materials.MATERIALS_DIR", str(materials_root))
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_URL", raising=False)

    response = _client().post("/api/material-sync/refresh")

    assert response.status_code == 422
    assert "Material registry URL is not configured" in response.json()["detail"]


def test_material_sync_refresh_endpoint_returns_core_summary(monkeypatch) -> None:
    def _fake_refresh_material_sync_from_registry() -> dict[str, object]:
        return {
            "registry_url": "https://registry.test/v1",
            "channels": ["official"],
            "checked_count": 1,
            "installed_count": 1,
            "skipped_count": 0,
            "failed_count": 0,
            "installed_materials": [
                {
                    "material_name": "PLA Basic Imported",
                    "directory_name": "BrandA/pla-basic",
                    "brand": "BrandA",
                    "archive_path": "materials/BrandA/pla-basic/material.json",
                    "stage_a_params_path": (
                        "materials/BrandA/pla-basic/stage_A_parameters.json"
                    ),
                }
            ],
            "failures": [],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.refresh_material_sync_from_registry",
        _fake_refresh_material_sync_from_registry,
    )

    response = _client().post("/api/material-sync/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["registry_url"] == "https://registry.test/v1"
    assert body["channels"] == ["official"]
    assert body["installed_count"] == 1
    assert body["installed_materials"][0]["directory_name"] == "BrandA/pla-basic"


def test_refresh_material_sync_from_registry_installs_new_revision_and_skips_same_revision(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(
        package_path,
        material_id="mat_registry_test",
        revision_id="rev_registry_test",
    )
    package_bytes = package_path.read_bytes()
    package_sha256 = hashlib.sha256(package_bytes).hexdigest()
    request_counts = {"catalog": 0, "package": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            request_counts["catalog"] += 1
            assert request.headers["authorization"] == "Bearer team-token"
            assert request.url.params.get_list("channel") == ["official", "team"]
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "cursor": "cursor-1",
                    "materials": [
                        {
                            "material_id": "mat_registry_test",
                            "revision_id": "rev_registry_test",
                            "content_hash": content_hash,
                            "channel": "team",
                            "package_url": "/v1/packages/material_package.zip",
                            "package_sha256": package_sha256,
                        }
                    ],
                },
            )
        if request.url.path == "/v1/packages/material_package.zip":
            request_counts["package"] += 1
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)

    first = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        channels=["official", "team"],
        token="team-token",
        materials_dir=str(materials_root),
        transport=transport,
    )
    second = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        channels=["official", "team"],
        token="team-token",
        materials_dir=str(materials_root),
        transport=transport,
    )

    assert first["checked_count"] == 1
    assert first["installed_count"] == 1
    assert first["skipped_count"] == 0
    assert first["failed_count"] == 0
    assert first["installed_materials"][0]["directory_name"] == "BrandA/pla-basic"
    assert second["installed_count"] == 0
    assert second["skipped_count"] == 1
    assert request_counts == {"catalog": 2, "package": 1}

    index = json.loads((materials_root / "_sync" / "index.json").read_text("utf-8"))
    assert "https://registry.test/v1" in index["registries"]
    assert index["registries"]["https://registry.test/v1"]["channels"] == [
        "official",
        "team",
    ]


def test_refresh_material_sync_from_registry_reports_corrupt_package_without_install(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(package_path)
    package_bytes = package_path.read_bytes()

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_sync_test",
                            "revision_id": "rev_sync_test",
                            "content_hash": content_hash,
                            "channel": "official",
                            "package_url": "/v1/packages/material_package.zip",
                            "package_sha256": "sha256:deadbeef",
                        }
                    ],
                },
            )
        if request.url.path == "/v1/packages/material_package.zip":
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["checked_count"] == 1
    assert result["installed_count"] == 0
    assert result["failed_count"] == 1
    assert result["failures"][0]["material_id"] == "mat_sync_test"
    assert "package_sha256" in result["failures"][0]["error"]
    assert (materials_root / "BrandA" / "pla-basic" / "material.json").exists() is False


def test_material_sync_status_lists_installed_package_and_local_presence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "Generic" / "PLA Basic"
    material_dir.mkdir(parents=True)
    (material_dir / "material.json").write_text(
        json.dumps({"material_name": "PLA Basic", "brand": "Generic"}),
        encoding="utf-8",
    )
    (materials_root / "_sync").mkdir()
    (materials_root / "_sync" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "last_sync_at": "2026-06-08T01:02:03+00:00",
                "registries": {},
                "installed": {
                    "mat_test": {
                        "revision_id": "rev_test",
                        "content_hash": "sha256:abc",
                        "channel": "stable",
                        "source": "package",
                        "local_directory": "Generic/PLA Basic",
                        "display_brand": "Generic",
                        "display_name": "PLA Basic",
                        "installed_at": "2026-06-08T01:02:03+00:00",
                        "updated_at": "2026-06-08T01:02:03+00:00",
                    }
                },
                "local_overrides": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.single_stage.materials.MATERIALS_DIR", str(materials_root))

    response = _client().get("/api/material-sync/status")

    assert response.status_code == 200
    body = response.json()
    assert body["index_state"] == "ready"
    assert body["last_sync_at"] == "2026-06-08T01:02:03+00:00"
    assert body["installed_count"] == 1
    assert body["installed"][0] == {
        "material_id": "mat_test",
        "revision_id": "rev_test",
        "content_hash": "sha256:abc",
        "channel": "stable",
        "source": "package",
        "local_directory": "Generic/PLA Basic",
        "display_brand": "Generic",
        "display_name": "PLA Basic",
        "installed_at": "2026-06-08T01:02:03+00:00",
        "updated_at": "2026-06-08T01:02:03+00:00",
        "local_exists": True,
        "material_file_exists": True,
    }


def test_material_sync_status_handles_corrupt_index_without_traceback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    (materials_root / "_sync").mkdir(parents=True)
    (materials_root / "_sync" / "index.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("core.single_stage.materials.MATERIALS_DIR", str(materials_root))

    response = _client().get("/api/material-sync/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["index_state"] == "invalid"
    assert body["installed_count"] == 0
    assert body["installed"] == []
