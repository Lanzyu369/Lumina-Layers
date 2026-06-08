"""Read-only material Registry API tests."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app


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
