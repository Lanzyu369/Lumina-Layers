from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routers import workshop as workshop_router
from core.workshop import WorkshopInstaller, inspect_workshop_package
from core.workshop.models import RegistryRefreshResult
from core.workshop.registry_client import parse_registry_index


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
REPOSITORY = (
    "https://github.com/lumina-layer-studio/Fixture-Workshop"
)


def write_package(
    tmp_path: Path,
    version: str,
    *,
    module_id: str = "fixture.hello",
) -> Path:
    archive = tmp_path / f"{module_id}-{version}.lumina-workshop"
    manifest = {
        "manifestVersion": 1,
        "id": module_id,
        "version": version,
        "name": {
            "zh-CN": "测试模块",
            "en-US": "Fixture module",
        },
        "description": {
            "zh-CN": "Workshop API 测试",
            "en-US": "Workshop API tests",
        },
        "publisher": "Fixture Publisher",
        "workshopApi": {
            "min": "1.0.0",
            "maxExclusive": "2.0.0",
        },
        "luminaVersion": {
            "min": "1.0.0",
        },
        "entrypoints": {
            "ui": "ui/index.html",
        },
        "permissions": [
            {
                "name": "project.storage",
                "reason": "Save fixture projects.",
            }
        ],
    }
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
        output.writestr(
            "manifest.json",
            json.dumps(
                manifest,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        output.writestr(
            "ui/index.html",
            (
                b"<!doctype html><html><head></head><body>"
                b"<script>globalThis.fixture=true</script></body></html>"
            ),
        )
        output.writestr("assets/icon.png", PNG_1X1)
        output.writestr("README.md", b"# Fixture\n")
        output.writestr("LICENSE", b"MIT\n")
    return archive


def write_seed_directory(
    tmp_path: Path,
    version: str = "1.0.0",
    *,
    module_id: str = "fixture.official",
) -> tuple[Path, Path]:
    seed_dir = tmp_path / f"seed-{module_id}-{version}"
    seed_dir.mkdir()
    archive = write_package(
        seed_dir,
        version,
        module_id=module_id,
    )
    inspected = inspect_workshop_package(archive)
    repository = (
        "https://github.com/lumina-layer-studio/Fixture-Workshop"
    )
    lock = {
        "schemaVersion": 1,
        "moduleId": module_id,
        "version": version,
        "repository": repository,
        "releaseTag": f"v{version}",
        "releaseAsset": archive.name,
        "downloadUrl": (
            f"{repository}/releases/download/v{version}/{archive.name}"
        ),
        "assetBytes": archive.stat().st_size,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "manifestSha256": inspected.manifest_sha256,
    }
    (seed_dir / "seed-lock.json").write_text(
        json.dumps(lock, ensure_ascii=False),
        encoding="utf-8",
    )
    return seed_dir, archive


def registry_index_for(
    archive: Path,
    *,
    module_id: str = "fixture.hello",
    version: str = "1.0.0",
    state: str = "active",
):
    asset_name = f"{module_id}-{version}.lumina-workshop"
    revocation = None
    if state == "blocked":
        revocation = {
            "reasonCode": "malware",
            "severity": "critical",
            "message": {
                "zh-CN": "此版本已被阻止。",
                "en-US": "This version has been blocked.",
            },
        }
    payload = {
        "schemaVersion": 1,
        "generatedAt": "2026-07-30T00:00:00Z",
        "modules": [
            {
                "moduleId": module_id,
                "repository": REPOSITORY,
                "official": False,
                "publisher": "Fixture Publisher",
                "name": {
                    "zh-CN": "测试模块",
                    "en-US": "Fixture module",
                },
                "description": {
                    "zh-CN": "Workshop API 测试",
                    "en-US": "Workshop API tests",
                },
                "versions": [
                    {
                        "version": version,
                        "releaseTag": f"v{version}",
                        "assetName": asset_name,
                        "downloadUrl": (
                            f"{REPOSITORY}/releases/download/"
                            f"v{version}/{asset_name}"
                        ),
                        "assetBytes": archive.stat().st_size,
                        "sha256": hashlib.sha256(
                            archive.read_bytes()
                        ).hexdigest(),
                        "manifestSha256": "b" * 64,
                        "workshopApi": {
                            "min": "1.0.0",
                            "maxExclusive": "2.0.0",
                        },
                        "luminaVersion": {
                            "min": "1.0.0",
                        },
                        "permissions": [
                            {
                                "name": "project.storage",
                                "reason": "Save fixture projects.",
                            }
                        ],
                        "state": state,
                        "revocation": revocation,
                    }
                ],
            }
        ],
    }
    return parse_registry_index(
        (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )


class FakeRegistryClient:
    def __init__(self, index) -> None:
        self.index = index

    def refresh(self) -> RegistryRefreshResult:
        return RegistryRefreshResult(
            source="remote",
            verified=True,
            index=self.index,
        )


@pytest.fixture()
def api_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    installer = WorkshopInstaller(data_dir=tmp_path / "workshop-data")
    archive = write_package(tmp_path, "1.0.0")
    registry = FakeRegistryClient(registry_index_for(archive))
    monkeypatch.setattr(
        workshop_router,
        "get_workshop_installer",
        lambda: installer,
    )
    monkeypatch.setattr(
        workshop_router,
        "get_workshop_registry_client",
        lambda: registry,
    )
    monkeypatch.setenv(
        "LUMINA_WORKSHOP_DESKTOP_TOKEN",
        "desktop-token",
    )
    return TestClient(create_app()), installer, archive, registry


def install_direct(
    installer: WorkshopInstaller,
    archive: Path,
    *,
    source: str = "registry",
    official: bool = False,
) -> None:
    installer.install_candidate(
        archive,
        source=source,
        source_repository=REPOSITORY,
        official=official,
    )
    module_id, version = archive.name.removesuffix(
        ".lumina-workshop"
    ).rsplit("-", 1)
    installer.activate(module_id, version)


def test_workshop_v1_routes_are_registered(api_bundle) -> None:
    client, _installer, _archive, _registry = api_bundle
    route_paths = {
        route.path for route in client.app.routes
    }

    assert {
        "/api/workshop/v1/catalog",
        "/api/workshop/v1/modules",
        "/api/workshop/v1/install/registry",
        "/api/workshop/v1/install/github",
        "/api/workshop/v1/install/local",
        "/api/workshop/v1/modules/{module_id}/activate",
        "/api/workshop/v1/modules/{module_id}/rollback",
        "/api/workshop/v1/modules/{module_id}/enabled",
        "/api/workshop/v1/modules/{module_id}/restore-seed",
        "/api/workshop/v1/modules/{module_id}/runtime-success",
        "/api/workshop/v1/modules/{module_id}/runtime-failure",
        "/api/workshop/v1/modules/{module_id}",
        (
            "/api/workshop/v1/modules/{module_id}/{version}/details"
        ),
        (
            "/api/workshop/v1/modules/{module_id}/{version}/runtime"
        ),
        (
            "/api/workshop/v1/modules/{module_id}/{version}/"
            "assets/{asset_path:path}"
        ),
    }.issubset(route_paths)


def test_installed_modules_include_public_version_manifests(
    api_bundle,
) -> None:
    client, installer, archive, _registry = api_bundle
    install_direct(installer, archive)

    response = client.get("/api/workshop/v1/modules")

    assert response.status_code == 200
    module = response.json()["modules"][0]
    assert module["version_details"] == [
        {
            "version": "1.0.0",
            "name": {
                "zh_cn": "测试模块",
                "en_us": "Fixture module",
            },
            "description": {
                "zh_cn": "Workshop API 测试",
                "en_us": "Workshop API tests",
            },
            "publisher": "Fixture Publisher",
            "workshop_api_min": "1.0.0",
            "workshop_api_max_exclusive": "2.0.0",
            "lumina_version_min": "1.0.0",
            "permissions": [
                {
                    "name": "project.storage",
                    "reason": "Save fixture projects.",
                }
            ],
            "runtime_url": (
                "/api/workshop/v1/modules/"
                "fixture.hello/1.0.0/runtime"
            ),
            "details_url": (
                "/api/workshop/v1/modules/"
                "fixture.hello/1.0.0/details"
            ),
            "icon_url": (
                "/api/workshop/v1/modules/"
                "fixture.hello/1.0.0/assets/icon.png"
            ),
            "asset_base_url": (
                "/api/workshop/v1/modules/"
                "fixture.hello/1.0.0/assets"
            ),
        }
    ]
    assert str(installer.data_dir) not in response.text


def test_module_details_expose_only_bounded_public_documents(
    api_bundle,
) -> None:
    client, installer, archive, _registry = api_bundle
    install_direct(installer, archive)

    response = client.get(
        "/api/workshop/v1/modules/fixture.hello/1.0.0/details"
    )

    assert response.status_code == 200
    assert response.json() == {
        "module_id": "fixture.hello",
        "version": "1.0.0",
        "readme_markdown": "# Fixture\n",
        "license_text": "MIT\n",
        "gallery_urls": [],
    }
    assert str(installer.data_dir) not in response.text


def test_runtime_health_is_persisted_without_exposing_paths(
    api_bundle,
) -> None:
    client, installer, archive, _registry = api_bundle
    install_direct(installer, archive)

    failed = client.post(
        "/api/workshop/v1/modules/fixture.hello/runtime-failure"
    )
    succeeded = client.post(
        "/api/workshop/v1/modules/fixture.hello/runtime-success"
    )

    assert failed.status_code == 200
    assert failed.json()["module"]["consecutive_start_failures"] == 1
    assert succeeded.status_code == 200
    assert (
        succeeded.json()["module"]["consecutive_start_failures"]
        == 0
    )
    assert str(installer.data_dir) not in failed.text


def test_catalog_returns_verified_public_metadata(api_bundle) -> None:
    client, _installer, _archive, _registry = api_bundle

    response = client.get("/api/workshop/v1/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "remote"
    assert payload["verified"] is True
    assert payload["modules"][0]["module_id"] == "fixture.hello"
    assert payload["modules"][0]["versions"][0]["state"] == "active"
    assert "/Users/" not in response.text


def test_local_install_rejects_oversize_upload(
    api_bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _installer, _archive, _registry = api_bundle
    monkeypatch.setattr(workshop_router, "MAX_PACKAGE_BYTES", 1024)

    response = client.post(
        "/api/workshop/v1/install/local",
        files={
            "archive": (
                "bad.lumina-workshop",
                b"x" * 1025,
                "application/zip",
            )
        },
    )

    assert response.status_code == 413


def test_local_install_creates_a_candidate_without_exposing_paths(
    api_bundle,
) -> None:
    client, installer, archive, _registry = api_bundle

    response = client.post(
        "/api/workshop/v1/install/local",
        files={
            "archive": (
                archive.name,
                archive.read_bytes(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()["module"]
    assert payload["module_id"] == "fixture.hello"
    assert payload["candidate_version"] == "1.0.0"
    assert payload["runtime_url"] is None
    assert payload["icon_url"].startswith("/api/workshop/v1/")
    assert str(installer.data_dir) not in response.text


def test_registry_install_uses_exact_verified_candidate(
    api_bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _installer, archive, _registry = api_bundle
    monkeypatch.setattr(
        workshop_router,
        "download_registry_package",
        lambda _candidate: archive,
    )

    response = client.post(
        "/api/workshop/v1/install/registry",
        json={
            "module_id": "fixture.hello",
            "version": "1.0.0",
        },
    )

    assert response.status_code == 200
    assert response.json()["module"]["source"] == "registry"
    assert response.json()["module"]["candidate_version"] == "1.0.0"


def test_github_install_accepts_only_exact_repository_release(
    api_bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _installer, archive, _registry = api_bundle
    monkeypatch.setattr(
        workshop_router,
        "resolve_github_release_package",
        lambda _repository, _version: archive,
    )

    invalid = client.post(
        "/api/workshop/v1/install/github",
        json={
            "repository_url": "https://example.com/owner/repo",
            "version": "1.0.0",
        },
    )
    valid = client.post(
        "/api/workshop/v1/install/github",
        json={
            "repository_url": REPOSITORY,
            "version": "1.0.0",
        },
    )

    assert invalid.status_code == 422
    assert valid.status_code == 200
    assert valid.json()["module"]["source"] == "github"


def test_github_install_rejects_encoded_repository_segments(
    api_bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _installer, archive, _registry = api_bundle
    monkeypatch.setattr(
        workshop_router,
        "resolve_github_release_package",
        lambda _repository, _version: archive,
    )

    response = client.post(
        "/api/workshop/v1/install/github",
        json={
            "repository_url": "https://github.com/owner/%2Frepository",
            "version": "1.0.0",
        },
    )

    assert response.status_code == 422


def test_community_runtime_requires_desktop_token(
    api_bundle,
) -> None:
    client, installer, archive, _registry = api_bundle
    install_direct(installer, archive)
    url = (
        "/api/workshop/v1/modules/"
        "fixture.hello/1.0.0/runtime"
    )

    missing = client.get(url)
    wrong = client.get(
        url,
        headers={
            "X-Lumina-Workshop-Desktop-Token": "wrong",
        },
    )
    allowed = client.get(
        url,
        headers={
            "X-Lumina-Workshop-Desktop-Token": "desktop-token",
        },
    )

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert allowed.status_code == 200


def test_disabled_module_runtime_cannot_be_loaded(api_bundle) -> None:
    client, installer, archive, _registry = api_bundle
    install_direct(installer, archive)
    installer.set_enabled("fixture.hello", False)

    response = client.get(
        "/api/workshop/v1/modules/"
        "fixture.hello/1.0.0/runtime",
        headers={
            "X-Lumina-Workshop-Desktop-Token": "desktop-token",
        },
    )

    assert response.status_code == 409


def test_official_seed_runtime_has_fixed_security_headers(
    tmp_path: Path,
    api_bundle,
) -> None:
    client, installer, _archive, _registry = api_bundle
    official = write_package(
        tmp_path,
        "1.0.0",
        module_id="fixture.official",
    )
    install_direct(
        installer,
        official,
        source="seed",
        official=True,
    )

    response = client.get(
        "/api/workshop/v1/modules/"
        "fixture.official/1.0.0/runtime"
    )

    assert response.status_code == 200
    assert response.headers["content-security-policy"].startswith(
        "default-src 'none';"
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert (
        response.text.index("Content-Security-Policy")
        < response.text.index("<script>")
    )
    assert "desktop-token" not in response.text


def test_only_public_module_assets_can_be_served(api_bundle) -> None:
    client, installer, archive, _registry = api_bundle
    install_direct(installer, archive)
    prefix = (
        "/api/workshop/v1/modules/"
        "fixture.hello/1.0.0/assets"
    )

    icon = client.get(f"{prefix}/icon.png")
    manifest = client.get(f"{prefix}/../manifest.json")

    assert icon.status_code == 200
    assert icon.headers["content-type"] == "image/png"
    assert icon.headers["x-content-type-options"] == "nosniff"
    assert manifest.status_code == 404


def test_activate_rollback_disable_and_uninstall_lifecycle(
    tmp_path: Path,
    api_bundle,
) -> None:
    client, installer, archive, _registry = api_bundle
    install_direct(installer, archive)
    second = write_package(tmp_path, "1.1.0")
    installer.install_candidate(
        second,
        source="registry",
        source_repository=REPOSITORY,
        official=False,
    )

    activated = client.post(
        "/api/workshop/v1/modules/fixture.hello/activate",
        json={"version": "1.1.0"},
    )
    rolled_back = client.post(
        "/api/workshop/v1/modules/fixture.hello/rollback",
    )
    disabled = client.patch(
        "/api/workshop/v1/modules/fixture.hello/enabled",
        json={"enabled": False},
    )
    project = (
        installer.project_data_path("fixture.hello")
        / "keep.json"
    )
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")
    removed = client.request(
        "DELETE",
        "/api/workshop/v1/modules/fixture.hello",
        json={"delete_projects": False},
    )

    assert activated.status_code == 200
    assert activated.json()["module"]["active_version"] == "1.1.0"
    assert rolled_back.status_code == 200
    assert rolled_back.json()["module"]["active_version"] == "1.0.0"
    assert disabled.status_code == 200
    assert disabled.json()["module"]["enabled"] is False
    assert removed.status_code == 200
    assert removed.json()["module"] is None
    assert project.is_file()


def test_official_tombstone_can_restore_only_from_verified_bundled_seed(
    tmp_path: Path,
    api_bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, installer, _archive, _registry = api_bundle
    seed_dir, official = write_seed_directory(tmp_path)
    monkeypatch.setenv("LUMINA_WORKSHOP_SEED_DIR", str(seed_dir))
    install_direct(
        installer,
        official,
        source="seed",
        official=True,
    )
    project = (
        installer.project_data_path("fixture.official")
        / "keep.json"
    )
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")
    installer.uninstall("fixture.official")

    response = client.post(
        "/api/workshop/v1/modules/fixture.official/restore-seed",
    )

    assert response.status_code == 200
    module = response.json()["module"]
    assert module["official_uninstalled"] is False
    assert module["candidate_version"] == "1.0.0"
    assert module["active_version"] is None
    assert project.is_file()
    assert str(seed_dir) not in response.text


def test_official_seed_restore_is_unavailable_without_bundled_resource(
    api_bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, installer, archive, _registry = api_bundle
    monkeypatch.delenv("LUMINA_WORKSHOP_SEED_DIR", raising=False)
    install_direct(
        installer,
        archive,
        source="seed",
        official=True,
    )
    installer.uninstall("fixture.hello")

    response = client.post(
        "/api/workshop/v1/modules/fixture.hello/restore-seed",
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "The bundled official Workshop module is unavailable."
    }


def test_runtime_and_lifecycle_errors_are_deterministic(
    api_bundle,
) -> None:
    client, _installer, _archive, _registry = api_bundle

    runtime = client.get(
        "/api/workshop/v1/modules/missing.module/1.0.0/runtime",
        headers={
            "X-Lumina-Workshop-Desktop-Token": "desktop-token",
        },
    )
    rollback = client.post(
        "/api/workshop/v1/modules/missing.module/rollback",
    )

    assert runtime.status_code == 404
    assert rollback.status_code == 404
    assert "Traceback" not in runtime.text
