"""Read-only material Registry API tests."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
import core.material_registry as material_registry_module


def _client() -> TestClient:
    return TestClient(create_app())


def _write_v2_registry_package(
    zip_path: Path,
    *,
    material_id: str = "mat_registry_test",
    revision_id: str = "rev_registry_test",
    channel: str = "official",
    local_directory: str = "BrandA/pla-basic",
) -> str:
    material_payload = json.dumps(
        {
            "brand": "BrandA",
            "material_name": "PLA Basic",
            "stage_a_params_file": "stage_A_parameters.json",
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    stage_a_payload = json.dumps(
        {"parameters": {"channels": [{"color_name": "PLA Basic"}]}},
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
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(material_path, material_payload)
        archive.writestr(stage_a_path, stage_a_payload)
        archive.writestr(
            "lumina_material_bundle.json",
            json.dumps(
                {
                    "kind": "lumina_material_bundle",
                    "schema_version": "2.0",
                    "packages": [
                        {
                            "material_id": material_id,
                            "revision_id": revision_id,
                            "content_hash": f"sha256:{content_hash}",
                            "channel": channel,
                            "visibility": channel,
                            "local_directory": local_directory,
                            "display": {
                                "brand": "BrandA",
                                "material_name": "PLA Basic",
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
    return hashlib.sha256(zip_path.read_bytes()).hexdigest()


def test_material_registry_catalog_requires_package_directory(monkeypatch) -> None:
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_PACKAGES_DIR", raising=False)

    response = _client().get("/api/material-registry/v1/materials/catalog")

    assert response.status_code == 422
    assert "Material registry packages directory is not configured" in response.json()["detail"]


def test_material_registry_catalog_lists_official_package_and_serves_zip(
    monkeypatch,
    tmp_path: Path,
) -> None:
    packages_dir = tmp_path / "registry-packages"
    package_path = packages_dir / "official-pla.zip"
    package_sha256 = _write_v2_registry_package(package_path, channel="official")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_PACKAGES_DIR", str(packages_dir))
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_TEAM_TOKEN", raising=False)

    response = _client().get(
        "/api/material-registry/v1/materials/catalog",
        params={"channel": "official"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["count"] == 1
    entry = body["materials"][0]
    assert entry["material_id"] == "mat_registry_test"
    assert entry["revision_id"] == "rev_registry_test"
    assert entry["channel"] == "official"
    assert entry["package_sha256"] == package_sha256
    assert entry["package_bytes"] == package_path.stat().st_size
    assert entry["package_url"] == "/api/material-registry/v1/packages/official-pla.zip"

    download = _client().get(entry["package_url"])

    assert download.status_code == 200
    assert download.content == package_path.read_bytes()


def test_material_registry_catalog_paginates_after_channel_filter(
    monkeypatch,
    tmp_path: Path,
) -> None:
    packages_dir = tmp_path / "registry-packages"
    for index in range(3):
        _write_v2_registry_package(
            packages_dir / f"official-{index}.zip",
            material_id=f"mat_registry_{index}",
            revision_id=f"rev_registry_{index}",
            channel="official",
            local_directory=f"BrandA/pla-basic-{index}",
        )
    _write_v2_registry_package(
        packages_dir / "team-only.zip",
        material_id="mat_team_only",
        revision_id="rev_team_only",
        channel="team",
        local_directory="BrandA/team-only",
    )
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_PACKAGES_DIR", str(packages_dir))

    response = _client().get(
        "/api/material-registry/v1/materials/catalog",
        params={"channel": "official", "limit": "1", "offset": "1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["total_count"] == 3
    assert body["offset"] == 1
    assert body["limit"] == 1
    assert [entry["material_id"] for entry in body["materials"]] == [
        "mat_registry_1"
    ]


def test_material_registry_catalog_reuses_cached_package_scan(
    monkeypatch,
    tmp_path: Path,
) -> None:
    packages_dir = tmp_path / "registry-packages"
    package_path = packages_dir / "official-pla.zip"
    _write_v2_registry_package(package_path, channel="official")
    calls = 0
    original_load_bundle_manifest = material_registry_module._load_bundle_manifest

    def counting_load_bundle_manifest(zip_path: Path) -> dict[str, object] | None:
        nonlocal calls
        calls += 1
        return original_load_bundle_manifest(zip_path)

    monkeypatch.setattr(
        material_registry_module,
        "_load_bundle_manifest",
        counting_load_bundle_manifest,
    )

    first = material_registry_module.build_material_registry_catalog(
        channels=["official"],
        packages_dir=str(packages_dir),
    )
    second = material_registry_module.build_material_registry_catalog(
        channels=["official"],
        packages_dir=str(packages_dir),
    )

    assert calls == 1
    assert first == second
    assert second["count"] == 1


def test_material_registry_catalog_cache_invalidates_after_upload(
    tmp_path: Path,
) -> None:
    packages_dir = tmp_path / "registry-packages"
    existing_package = packages_dir / "official" / "existing.zip"
    upload_package = tmp_path / "upload.zip"
    _write_v2_registry_package(
        existing_package,
        material_id="mat_existing",
        revision_id="rev_existing",
        channel="official",
    )
    _write_v2_registry_package(
        upload_package,
        material_id="mat_uploaded",
        revision_id="rev_uploaded",
        channel="manual",
    )

    first = material_registry_module.build_material_registry_catalog(
        channels=["official"],
        packages_dir=str(packages_dir),
    )
    material_registry_module.upload_material_registry_package(
        archive_path=str(upload_package),
        channel="official",
        packages_dir=str(packages_dir),
    )
    second = material_registry_module.build_material_registry_catalog(
        channels=["official"],
        packages_dir=str(packages_dir),
    )

    assert first["count"] == 1
    assert second["count"] == 2
    assert {entry["material_id"] for entry in second["materials"]} == {
        "mat_existing",
        "mat_uploaded",
    }


def test_material_registry_team_channel_requires_bearer_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    packages_dir = tmp_path / "registry-packages"
    _write_v2_registry_package(
        packages_dir / "team-pla.zip",
        material_id="mat_team_test",
        revision_id="rev_team_test",
        channel="team",
    )
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_PACKAGES_DIR", str(packages_dir))
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_TEAM_TOKEN", "team-token")

    anonymous = _client().get(
        "/api/material-registry/v1/materials/catalog",
        params={"channel": "team"},
    )
    authorized = _client().get(
        "/api/material-registry/v1/materials/catalog",
        params={"channel": "team"},
        headers={"Authorization": "Bearer team-token"},
    )

    assert anonymous.status_code == 403
    assert authorized.status_code == 200
    body = authorized.json()
    assert body["count"] == 1
    assert body["materials"][0]["material_id"] == "mat_team_test"
    assert body["materials"][0]["channel"] == "team"


def test_material_registry_team_package_download_requires_bearer_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    packages_dir = tmp_path / "registry-packages"
    package_path = packages_dir / "team-pla.zip"
    _write_v2_registry_package(
        package_path,
        material_id="mat_team_test",
        revision_id="rev_team_test",
        channel="team",
    )
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_PACKAGES_DIR", str(packages_dir))
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_TEAM_TOKEN", "team-token")

    anonymous = _client().get("/api/material-registry/v1/packages/team-pla.zip")
    authorized = _client().get(
        "/api/material-registry/v1/packages/team-pla.zip",
        headers={"Authorization": "Bearer team-token"},
    )

    assert anonymous.status_code == 403
    assert authorized.status_code == 200
    assert authorized.content == package_path.read_bytes()


def test_material_registry_package_download_rejects_traversal(
    monkeypatch,
    tmp_path: Path,
) -> None:
    packages_dir = tmp_path / "registry-packages"
    packages_dir.mkdir()
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_PACKAGES_DIR", str(packages_dir))

    response = _client().get(
        "/api/material-registry/v1/packages/%2e%2e/secret.zip"
    )

    assert response.status_code == 422


def test_material_registry_upload_stores_package_as_pending(
    monkeypatch,
    tmp_path: Path,
) -> None:
    packages_dir = tmp_path / "registry-packages"
    source_package = tmp_path / "upload.zip"
    _write_v2_registry_package(
        source_package,
        material_id="mat_upload_test",
        revision_id="rev_upload_test",
        channel="manual",
    )
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_PACKAGES_DIR", str(packages_dir))

    response = _client().post(
        "/api/material-registry/v1/packages/upload",
        files={
            "archive": (
                "upload.zip",
                source_package.read_bytes(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["channel"] == "pending"
    assert body["materials"][0]["material_id"] == "mat_upload_test"
    assert body["materials"][0]["channel"] == "pending"
    assert body["package_path"].startswith("pending/")

    catalog = _client().get(
        "/api/material-registry/v1/materials/catalog",
        params={"channel": "pending"},
        headers={"Authorization": "Bearer team-token"},
    )
    assert catalog.status_code == 403


def test_material_registry_approve_requires_official_password(
    monkeypatch,
    tmp_path: Path,
) -> None:
    packages_dir = tmp_path / "registry-packages"
    pending_path = packages_dir / "pending" / "upload.zip"
    _write_v2_registry_package(
        pending_path,
        material_id="mat_approve_test",
        revision_id="rev_approve_test",
        channel="pending",
    )
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_PACKAGES_DIR", str(packages_dir))
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_OFFICIAL_PASSWORD", "approve-secret")

    wrong = _client().post(
        "/api/material-registry/v1/packages/pending/upload.zip/approve",
        json={"official_password": "wrong"},
    )
    approved = _client().post(
        "/api/material-registry/v1/packages/pending/upload.zip/approve",
        json={"official_password": "approve-secret"},
    )

    assert wrong.status_code == 403
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "ok"
    assert body["channel"] == "official"
    assert body["materials"][0]["channel"] == "official"
    assert body["package_path"].startswith("official/")

    catalog = _client().get(
        "/api/material-registry/v1/materials/catalog",
        params={"channel": "official"},
    )
    assert catalog.status_code == 200
    entries = catalog.json()["materials"]
    assert entries[0]["material_id"] == "mat_approve_test"
    assert entries[0]["channel"] == "official"
