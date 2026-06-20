"""Material sync API tests."""

from __future__ import annotations

import json
import hashlib
import logging
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routers.material_sync import (
    MATERIAL_SYNC_CATALOG_UNAVAILABLE_DETAIL,
    MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
    MATERIAL_SYNC_REFRESH_UNAVAILABLE_DETAIL,
    MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL,
    MATERIAL_SYNC_STATUS_UNAVAILABLE_DETAIL,
)
from core.single_stage import (
    install_material_registry_package,
    list_material_registry_catalog,
    refresh_material_sync_from_registry,
    rollback_material_sync_revision,
)
import core.single_stage.materials as materials_module

_OFFICIAL_PASSWORD = "approve-secret"
_AUTH_HEADERS = {
    "X-Lumina-Material-Registry-Official-Password": _OFFICIAL_PASSWORD,
}
_MATERIAL_SYNC_LOGGER_NAMES = (
    "lumina.api.routers.material_sync",
    "lumina.api.app",
)


def _client() -> TestClient:
    return TestClient(create_app())


def _enable_material_registry_password(monkeypatch) -> None:
    monkeypatch.setenv(
        "LUMINA_MATERIAL_REGISTRY_OFFICIAL_PASSWORD",
        _OFFICIAL_PASSWORD,
    )


def _capture_material_sync_logs(
    caplog: pytest.LogCaptureFixture,
) -> list[logging.Logger]:
    loggers: list[logging.Logger] = []
    for logger_name in _MATERIAL_SYNC_LOGGER_NAMES:
        logger = logging.getLogger(logger_name)
        logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=logger.name)
        loggers.append(logger)
    return loggers


def _release_caplog_handler(
    loggers: list[logging.Logger],
    caplog: pytest.LogCaptureFixture,
) -> None:
    for logger in loggers:
        logger.removeHandler(caplog.handler)


def _records_for_event(
    caplog: pytest.LogCaptureFixture,
    event: str,
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == event
    ]


def _assert_http_error_log_safe(
    caplog: pytest.LogCaptureFixture,
    *,
    path: str,
    status_code: int,
    detail: str,
    forbidden_fragments: tuple[str, ...],
) -> None:
    records = [
        record
        for record in _records_for_event(caplog, "api_http_error")
        if getattr(record, "path", None) == path
        and getattr(record, "status_code", None) == status_code
    ]
    assert records
    error_message = str(getattr(records[-1], "error_message", ""))
    assert error_message == detail
    for fragment in forbidden_fragments:
        assert fragment not in error_message


def _assert_route_failure_log_preserves_diagnostics(
    caplog: pytest.LogCaptureFixture,
    *,
    event: str,
    error_type: str,
    raw_fragment: str,
    status_code: int,
) -> None:
    records = _records_for_event(caplog, event)
    assert records
    record = records[-1]
    assert getattr(record, "error_type", None) == error_type
    assert getattr(record, "status_code", None) == status_code
    assert raw_fragment in str(getattr(record, "error_message", ""))


def _registry_install_catalog() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "channels": ["official"],
        "count": 1,
        "materials": [
            {
                "material_id": "mat_cloud_test",
                "revision_id": "rev_cloud_test",
                "content_hash": "sha256:cloud",
                "channel": "official",
                "visibility": "official",
                "local_directory": "BrandA/pla-basic",
                "display": {"brand": "BrandA", "material_name": "PLA Basic"},
                "compatibility": {},
                "package_url": "/v1/packages/material_package.zip",
                "package_sha256": "a" * 64,
                "package_bytes": 1234,
            }
        ],
    }


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
                "substrates": [
                    {
                        "substrate_id": "white",
                        "C0": [1.0, 1.0, 1.0],
                    }
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


def _write_v2_multi_material_package(zip_path: Path) -> dict[str, str]:
    package_records: list[dict[str, object]] = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for suffix in ("selected", "other"):
            local_directory = f"BrandA/pla-{suffix}"
            material_payload = json.dumps(
                {
                    "brand": "BrandA",
                    "material_name": f"PLA {suffix.title()}",
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
                            {
                                "color_name": f"PLA {suffix.title()}",
                                "E": [0.1, 0.2, 0.3],
                                "k": [1.0, 1.1, 1.2],
                            }
                        ],
                        "substrates": [
                            {
                                "substrate_id": "white",
                                "C0": [1.0, 1.0, 1.0],
                            }
                        ],
                    },
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            material_hash = hashlib.sha256(material_payload).hexdigest()
            stage_a_hash = hashlib.sha256(stage_a_payload).hexdigest()
            content_hash = hashlib.sha256(
                (
                    f"material.json:{material_hash}\n"
                    f"stage_A_parameters.json:{stage_a_hash}"
                ).encode("utf-8")
            ).hexdigest()
            material_path = f"materials/{local_directory}/material.json"
            stage_a_path = f"materials/{local_directory}/stage_A_parameters.json"
            archive.writestr(material_path, material_payload)
            archive.writestr(stage_a_path, stage_a_payload)
            package_records.append(
                {
                    "material_id": f"mat_{suffix}",
                    "revision_id": f"rev_{suffix}",
                    "content_hash": f"sha256:{content_hash}",
                    "channel": "team",
                    "visibility": "team",
                    "local_directory": local_directory,
                    "display": {
                        "brand": "BrandA",
                        "material_name": f"PLA {suffix.title()}",
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
            )
        archive.writestr(
            "lumina_material_bundle.json",
            json.dumps(
                {
                    "kind": "lumina_material_bundle",
                    "schema_version": "2.0",
                    "exported_at": "2026-06-08T00:00:00+00:00",
                    "material_count": len(package_records),
                    "packages": package_records,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return {
        "selected_material_id": "mat_selected",
        "selected_revision_id": "rev_selected",
        "selected_content_hash": str(package_records[0]["content_hash"]),
        "package_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
    }


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


def test_material_sync_status_unavailable_returns_safe_detail(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_path = "/Users/min/private/materials/_sync/index.json"

    def _fake_get_material_sync_status() -> dict[str, object]:
        raise OSError(f"[Errno 13] Permission denied: '{private_path}'")

    monkeypatch.setattr(
        "api.routers.material_sync.get_material_sync_status",
        _fake_get_material_sync_status,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().get("/api/material-sync/status")
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 500
    assert response.json()["detail"] == MATERIAL_SYNC_STATUS_UNAVAILABLE_DETAIL
    assert private_path not in response.text
    assert "Permission denied" not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/status",
        status_code=500,
        detail=MATERIAL_SYNC_STATUS_UNAVAILABLE_DETAIL,
        forbidden_fragments=(private_path, "Permission denied"),
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_status_failed",
        error_type="OSError",
        raw_fragment=private_path,
        status_code=500,
    )


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
    assert "archive_path" not in install_body["installed_materials"][0]
    assert "stage_a_params_path" not in install_body["installed_materials"][0]
    assert "materials/BrandA/pla-basic/material.json" not in install_response.text
    assert (
        "materials/BrandA/pla-basic/stage_A_parameters.json"
        not in install_response.text
    )

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


def test_material_sync_install_rejects_oversized_upload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "material_package.zip"
    _write_v2_material_package(package_path)
    monkeypatch.setenv("LUMINA_MATERIAL_PACKAGE_MAX_ARCHIVE_BYTES", "32")

    response = _client().post(
        "/api/material-sync/install",
        files={
            "archive": (
                "material_package.zip",
                package_path.read_bytes(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 413
    assert "exceeds maximum size" in response.json()["detail"]


def test_material_sync_install_import_os_error_returns_safe_detail(
    monkeypatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    package_path = tmp_path / "material_package.zip"
    _write_v2_material_package(package_path)
    private_path = "/Users/min/private/materials/BrandA/pla-basic/material.json"

    def _fake_import_saved_stage_a_material_archives(
        *,
        archive_path: str,
    ) -> object:
        raise OSError(f"[Errno 13] Permission denied: '{private_path}'")

    monkeypatch.setattr(
        "api.routers.material_sync.import_saved_stage_a_material_archives",
        _fake_import_saved_stage_a_material_archives,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().post(
            "/api/material-sync/install",
            files={
                "archive": (
                    "material_package.zip",
                    package_path.read_bytes(),
                    "application/zip",
                )
            },
        )
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 422
    assert response.json()["detail"] == MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL
    assert private_path not in response.text
    assert "Permission denied" not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/install",
        status_code=422,
        detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
        forbidden_fragments=(private_path, "Permission denied"),
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_install_failed",
        error_type="OSError",
        raw_fragment=private_path,
        status_code=422,
    )


def test_material_sync_install_import_missing_file_returns_safe_404(
    monkeypatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    package_path = tmp_path / "material_package.zip"
    _write_v2_material_package(package_path)
    private_path = "/Users/min/private/materials/BrandA/pla-basic/material.json"

    def _fake_import_saved_stage_a_material_archives(
        *,
        archive_path: str,
    ) -> object:
        raise FileNotFoundError(f"Saved material archive not found: {private_path}")

    monkeypatch.setattr(
        "api.routers.material_sync.import_saved_stage_a_material_archives",
        _fake_import_saved_stage_a_material_archives,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().post(
            "/api/material-sync/install",
            files={
                "archive": (
                    "material_package.zip",
                    package_path.read_bytes(),
                    "application/zip",
                )
            },
        )
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 404
    assert response.json()["detail"] == MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL
    assert private_path not in response.text
    assert "Saved material archive" not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/install",
        status_code=404,
        detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
        forbidden_fragments=(private_path, "Saved material archive"),
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_install_failed",
        error_type="FileNotFoundError",
        raw_fragment=private_path,
        status_code=404,
    )


@pytest.mark.parametrize(
    ("exc", "error_type", "forbidden_fragments"),
    [
        (
            ValueError(
                "Material bundle file hash mismatch: "
                "/Users/min/private/materials/BrandA/pla-basic/material.json"
            ),
            "ValueError",
            (
                "/Users/min/private/materials/BrandA/pla-basic/material.json",
                "hash mismatch",
            ),
        ),
        (
            TypeError(
                "Material bundle manifest parser failed for "
                "/Users/min/private/materials/BrandA/pla-basic/material.json"
            ),
            "TypeError",
            (
                "/Users/min/private/materials/BrandA/pla-basic/material.json",
                "parser failed",
            ),
        ),
    ],
)
def test_material_sync_install_import_validation_errors_return_safe_detail(
    monkeypatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    exc: Exception,
    error_type: str,
    forbidden_fragments: tuple[str, ...],
) -> None:
    package_path = tmp_path / "material_package.zip"
    _write_v2_material_package(package_path)

    def _fake_import_saved_stage_a_material_archives(
        *,
        archive_path: str,
    ) -> object:
        raise exc

    monkeypatch.setattr(
        "api.routers.material_sync.import_saved_stage_a_material_archives",
        _fake_import_saved_stage_a_material_archives,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().post(
            "/api/material-sync/install",
            files={
                "archive": (
                    "material_package.zip",
                    package_path.read_bytes(),
                    "application/zip",
                )
            },
        )
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 422
    assert response.json()["detail"] == MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL
    for fragment in forbidden_fragments:
        assert fragment not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/install",
        status_code=422,
        detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
        forbidden_fragments=forbidden_fragments,
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_install_failed",
        error_type=error_type,
        raw_fragment=forbidden_fragments[0],
        status_code=422,
    )


def test_material_sync_install_is_local_import_without_official_password(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    monkeypatch.setattr("core.single_stage.materials.MATERIALS_DIR", str(materials_root))
    package_path = tmp_path / "material_package.zip"
    _write_v2_material_package(package_path)

    response = _client().post(
        "/api/material-sync/install",
        files={
            "archive": (
                "material_package.zip",
                package_path.read_bytes(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["installed_count"] == 1


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


def test_material_sync_refresh_registry_unavailable_returns_502(monkeypatch) -> None:
    private_url = "https://registry.internal/private/catalog.json"

    def _fake_refresh_material_sync_from_registry() -> dict[str, object]:
        raise RuntimeError(
            f"Material registry catalog request failed for {private_url}: status 500"
        )

    monkeypatch.setattr(
        "api.routers.material_sync.refresh_material_sync_from_registry",
        _fake_refresh_material_sync_from_registry,
    )

    response = _client().post("/api/material-sync/refresh")

    assert response.status_code == 502
    assert response.json()["detail"] == MATERIAL_SYNC_REFRESH_UNAVAILABLE_DETAIL
    assert private_url not in response.text
    assert "status 500" not in response.text


def test_material_sync_catalog_registry_unavailable_returns_safe_detail(
    monkeypatch,
) -> None:
    private_url = "https://registry.internal/private/catalog.json"

    def _fake_list_material_registry_catalog(**_: object) -> dict[str, object]:
        raise RuntimeError(
            f"Material registry catalog request failed for {private_url}: status 502"
        )

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )

    response = _client().get("/api/material-sync/catalog")

    assert response.status_code == 502
    assert response.json()["detail"] == MATERIAL_SYNC_CATALOG_UNAVAILABLE_DETAIL
    assert private_url not in response.text
    assert "status 502" not in response.text


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
    assert "archive_path" not in body["installed_materials"][0]
    assert "stage_a_params_path" not in body["installed_materials"][0]
    assert "materials/BrandA/pla-basic/material.json" not in response.text
    assert "materials/BrandA/pla-basic/stage_A_parameters.json" not in response.text


def test_material_sync_catalog_endpoint_returns_remote_catalog_without_installing(
    monkeypatch,
) -> None:
    def _fake_list_material_registry_catalog(**_: object) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "channels": ["official"],
            "count": 1,
            "materials": [
                {
                    "material_id": "mat_cloud_test",
                    "revision_id": "rev_cloud_test",
                    "content_hash": "sha256:cloud",
                    "channel": "official",
                    "visibility": "official",
                    "local_directory": "BrandA/pla-basic",
                    "display": {"brand": "BrandA", "material_name": "PLA Basic"},
                    "compatibility": {},
                    "package_url": "/v1/packages/material_package.zip",
                    "package_sha256": "a" * 64,
                    "package_bytes": 1234,
                }
            ],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )

    response = _client().get("/api/material-sync/catalog")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["materials"][0]["material_id"] == "mat_cloud_test"


def test_material_sync_catalog_allows_public_channels_without_password(
    monkeypatch,
) -> None:
    called = False
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_CHANNELS", "official,community")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_TOKEN", "team-token")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_OFFICIAL_PASSWORD", _OFFICIAL_PASSWORD)

    def _fake_list_material_registry_catalog(**_: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {
            "schema_version": "1.0",
            "channels": ["official", "community"],
            "count": 0,
            "materials": [],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )

    response = _client().get("/api/material-sync/catalog")

    assert response.status_code == 200
    assert called is True
    assert response.json()["channels"] == ["official", "community"]


def test_material_sync_catalog_allows_private_proxy_without_official_password(
    monkeypatch,
) -> None:
    called = False
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_CHANNELS", "official,team")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_TOKEN", "team-token")

    def _fake_list_material_registry_catalog(**_: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {
            "schema_version": "1.0",
            "channels": ["official", "team"],
            "count": 0,
            "materials": [],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )

    response = _client().get("/api/material-sync/catalog")

    assert response.status_code == 200
    assert called is True
    assert response.json()["channels"] == ["official", "team"]


def test_material_sync_catalog_ignores_legacy_official_password_header(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_CHANNELS", "official,team")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_OFFICIAL_PASSWORD", _OFFICIAL_PASSWORD)

    def _fake_list_material_registry_catalog(**_: object) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "channels": ["official", "team"],
            "count": 0,
            "materials": [],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )

    response = _client().get("/api/material-sync/catalog", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["channels"] == ["official", "team"]


def test_list_material_registry_catalog_reuses_remote_catalog_cache() -> None:
    request_counts = {"catalog": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            request_counts["catalog"] += 1
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_cloud",
                            "revision_id": "rev_cloud",
                            "content_hash": "sha256:cloud",
                            "channel": "official",
                            "visibility": "official",
                            "local_directory": "BrandA/pla-basic",
                            "package_url": "/v1/packages/material_package.zip",
                            "package_sha256": "a" * 64,
                            "package_bytes": 10,
                        }
                    ],
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)

    first = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        transport=transport,
    )
    second = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        transport=transport,
    )

    assert request_counts == {"catalog": 1}
    assert first == second
    assert second["count"] == 1


def test_list_material_registry_catalog_requests_remote_page() -> None:
    observed_queries: list[dict[str, str]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            observed_queries.append(dict(request.url.params.multi_items()))
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "count": 1,
                    "total_count": 3,
                    "offset": 1,
                    "limit": 1,
                    "materials": [
                        {
                            "material_id": "mat_cloud_1",
                            "revision_id": "rev_cloud_1",
                            "content_hash": "sha256:cloud1",
                            "channel": "official",
                            "visibility": "official",
                            "local_directory": "BrandA/pla-basic-1",
                            "package_url": "/v1/packages/material_package_1.zip",
                            "package_sha256": "b" * 64,
                            "package_bytes": 10,
                        }
                    ],
                },
            )
        return httpx.Response(404)

    catalog = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        limit=1,
        offset=1,
        transport=httpx.MockTransport(_handler),
    )

    assert observed_queries == [
        {"channel": "official", "offset": "1", "limit": "1"}
    ]
    assert catalog["count"] == 1
    assert catalog["total_count"] == 3
    assert catalog["offset"] == 1
    assert catalog["limit"] == 1
    assert catalog["materials"][0]["material_id"] == "mat_cloud_1"


def test_list_material_registry_catalog_requests_remote_search() -> None:
    observed_queries: list[dict[str, str]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            observed_queries.append(dict(request.url.params.multi_items()))
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "count": 1,
                    "total_count": 1,
                    "offset": 0,
                    "limit": 50,
                    "materials": [
                        {
                            "material_id": "mat_petg",
                            "revision_id": "rev_petg",
                            "content_hash": "sha256:petg",
                            "channel": "official",
                            "visibility": "official",
                            "local_directory": "BrandB/petg-silk",
                            "display": {"brand": "BrandB", "material_name": "Silk PETG"},
                            "package_url": "/v1/packages/petg.zip",
                            "package_sha256": "c" * 64,
                            "package_bytes": 10,
                        }
                    ],
                },
            )
        return httpx.Response(404)

    catalog = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        query="petg",
        limit=50,
        offset=0,
        transport=httpx.MockTransport(_handler),
    )

    assert observed_queries == [
        {"channel": "official", "q": "petg", "offset": "0", "limit": "50"}
    ]
    assert catalog["count"] == 1
    assert catalog["total_count"] == 1
    assert catalog["materials"][0]["material_id"] == "mat_petg"


def test_list_material_registry_catalog_rejects_cross_origin_redirect() -> None:
    requested_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            )
        return httpx.Response(200, json={"schema_version": "1.0", "materials": []})

    with pytest.raises(RuntimeError, match="catalog redirects are not allowed"):
        list_material_registry_catalog(
            registry_url="https://registry.test/v1",
            channels=["official"],
            transport=httpx.MockTransport(_handler),
            use_cache=False,
        )

    assert requested_urls == [
        "https://registry.test/v1/materials/catalog?channel=official"
    ]


def test_list_material_registry_catalog_reuses_full_cache_for_legacy_paging() -> None:
    request_counts = {"catalog": 0}

    def _catalog_entry(index: int) -> dict[str, object]:
        return {
            "material_id": f"mat_cloud_{index}",
            "revision_id": f"rev_cloud_{index}",
            "content_hash": f"sha256:cloud{index}",
            "channel": "official",
            "visibility": "official",
            "local_directory": f"BrandA/pla-basic-{index}",
            "package_url": f"/v1/packages/material_package_{index}.zip",
            "package_sha256": str(index) * 64,
            "package_bytes": 10,
        }

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            request_counts["catalog"] += 1
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [_catalog_entry(0), _catalog_entry(1)],
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)

    first_page = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        limit=1,
        offset=0,
        transport=transport,
    )
    second_page = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        limit=1,
        offset=1,
        transport=transport,
    )

    assert request_counts == {"catalog": 1}
    assert first_page["count"] == 1
    assert first_page["total_count"] == 2
    assert first_page["materials"][0]["material_id"] == "mat_cloud_0"
    assert second_page["count"] == 1
    assert second_page["total_count"] == 2
    assert second_page["materials"][0]["material_id"] == "mat_cloud_1"


def test_list_material_registry_catalog_filters_legacy_remote_search_locally() -> None:
    request_counts = {"catalog": 0}

    def _catalog_entry(index: int, name: str) -> dict[str, object]:
        return {
            "material_id": f"mat_cloud_{index}",
            "revision_id": f"rev_cloud_{index}",
            "content_hash": f"sha256:cloud{index}",
            "channel": "official",
            "visibility": "official",
            "local_directory": f"BrandA/{name.lower().replace(' ', '-')}",
            "display": {"brand": "BrandA", "material_name": name},
            "package_url": f"/v1/packages/material_package_{index}.zip",
            "package_sha256": str(index) * 64,
            "package_bytes": 10,
        }

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            request_counts["catalog"] += 1
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        _catalog_entry(0, "PLA Basic"),
                        _catalog_entry(1, "Silk PETG"),
                    ],
                },
            )
        return httpx.Response(404)

    catalog = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        query="petg",
        limit=50,
        offset=0,
        transport=httpx.MockTransport(_handler),
    )

    assert request_counts == {"catalog": 1}
    assert catalog["count"] == 1
    assert catalog["total_count"] == 1
    assert catalog["materials"][0]["material_id"] == "mat_cloud_1"


def test_material_sync_install_from_registry_endpoint_installs_selected_package(
    monkeypatch,
) -> None:
    def _fake_list_material_registry_catalog() -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "channels": ["official"],
            "count": 1,
            "materials": [
                {
                    "material_id": "mat_cloud_test",
                    "revision_id": "rev_cloud_test",
                    "content_hash": "sha256:cloud",
                    "channel": "official",
                    "visibility": "official",
                    "local_directory": "BrandA/pla-basic",
                    "display": {"brand": "BrandA", "material_name": "PLA Basic"},
                    "compatibility": {},
                    "package_url": "/v1/packages/material_package.zip",
                    "package_sha256": "a" * 64,
                    "package_bytes": 1234,
                }
            ],
        }

    def _fake_install_material_registry_package(
        *,
        package_url: str,
        package_sha256: str,
        material_id: str,
        revision_id: str,
    ) -> dict[str, object]:
        assert package_url == "/v1/packages/material_package.zip"
        assert package_sha256 == "a" * 64
        assert material_id == "mat_cloud_test"
        assert revision_id == "rev_cloud_test"
        return {
            "registry_url": "https://registry.test/v1",
            "material_id": material_id,
            "revision_id": revision_id,
            "installed_count": 1,
            "installed_materials": [
                {
                    "material_name": "PLA Basic",
                    "directory_name": "BrandA/pla-basic",
                    "brand": "BrandA",
                    "archive_path": "materials/BrandA/pla-basic/material.json",
                    "stage_a_params_path": (
                        "materials/BrandA/pla-basic/stage_A_parameters.json"
                    ),
                }
            ],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )
    monkeypatch.setattr(
        "api.routers.material_sync.install_material_registry_package",
        _fake_install_material_registry_package,
    )

    response = _client().post(
        "/api/material-sync/install-from-registry",
        json={
            "package_url": "/v1/packages/material_package.zip",
            "package_sha256": "a" * 64,
            "material_id": "mat_cloud_test",
            "revision_id": "rev_cloud_test",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["installed_count"] == 1
    assert body["installed_materials"][0]["directory_name"] == "BrandA/pla-basic"
    assert "archive_path" not in body["installed_materials"][0]
    assert "stage_a_params_path" not in body["installed_materials"][0]
    assert "materials/BrandA/pla-basic/material.json" not in response.text
    assert "materials/BrandA/pla-basic/stage_A_parameters.json" not in response.text


def test_material_sync_install_from_registry_rejects_package_not_in_catalog(
    monkeypatch,
) -> None:
    _enable_material_registry_password(monkeypatch)
    install_called = False

    def _fake_list_material_registry_catalog() -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "channels": ["official"],
            "count": 1,
            "materials": [
                {
                    "material_id": "mat_cloud_test",
                    "revision_id": "rev_cloud_test",
                    "content_hash": "sha256:cloud",
                    "channel": "official",
                    "visibility": "official",
                    "local_directory": "BrandA/pla-basic",
                    "display": {"brand": "BrandA", "material_name": "PLA Basic"},
                    "compatibility": {},
                    "package_url": "/v1/packages/material_package.zip",
                    "package_sha256": "a" * 64,
                    "package_bytes": 1234,
                }
            ],
        }

    def _fake_install_material_registry_package(**_: object) -> dict[str, object]:
        nonlocal install_called
        install_called = True
        return {
            "registry_url": "https://registry.test/v1",
            "material_id": "mat_cloud_test",
            "revision_id": "rev_cloud_test",
            "installed_count": 0,
            "installed_materials": [],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )
    monkeypatch.setattr(
        "api.routers.material_sync.install_material_registry_package",
        _fake_install_material_registry_package,
    )

    response = _client().post(
        "/api/material-sync/install-from-registry",
        json={
            "package_url": "https://evil.test/material_package.zip",
            "package_sha256": "a" * 64,
            "material_id": "mat_cloud_test",
            "revision_id": "rev_cloud_test",
        },
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 422
    assert "current material registry catalog" in response.json()["detail"]
    assert install_called is False


def test_material_sync_install_from_registry_maps_invalid_package_to_502(
    monkeypatch,
) -> None:
    _enable_material_registry_password(monkeypatch)

    def _fake_list_material_registry_catalog() -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "channels": ["official"],
            "count": 1,
            "materials": [
                {
                    "material_id": "mat_cloud_test",
                    "revision_id": "rev_cloud_test",
                    "content_hash": "sha256:cloud",
                    "channel": "official",
                    "visibility": "official",
                    "local_directory": "BrandA/pla-basic",
                    "display": {"brand": "BrandA", "material_name": "PLA Basic"},
                    "compatibility": {},
                    "package_url": "/v1/packages/material_package.zip",
                    "package_sha256": "a" * 64,
                    "package_bytes": 1234,
                }
            ],
        }

    def _fake_install_material_registry_package(**_: object) -> dict[str, object]:
        raise FileNotFoundError("Saved material archive not found in ZIP")

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )
    monkeypatch.setattr(
        "api.routers.material_sync.install_material_registry_package",
        _fake_install_material_registry_package,
    )

    response = _client().post(
        "/api/material-sync/install-from-registry",
        json={
            "package_url": "/v1/packages/material_package.zip",
            "package_sha256": "a" * 64,
            "material_id": "mat_cloud_test",
            "revision_id": "rev_cloud_test",
        },
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL
    assert "Saved material archive" not in response.text


@pytest.mark.parametrize(
    ("exc", "status_code", "forbidden_fragments"),
    [
        (
            RuntimeError(
                "Material registry package request failed for "
                "https://registry.internal/private/material_package.zip: status 500"
            ),
            502,
            ("https://registry.internal/private/material_package.zip", "status 500"),
        ),
        (
            FileNotFoundError(
                "Saved material archive not found in "
                "/Users/min/private/materials/BrandA/pla-basic/material.json"
            ),
            502,
            (
                "/Users/min/private/materials/BrandA/pla-basic/material.json",
                "Saved material archive",
            ),
        ),
        (
            OSError(
                "[Errno 13] Permission denied: "
                "'/Users/min/private/materials/BrandA/pla-basic/material.json'"
            ),
            500,
            (
                "/Users/min/private/materials/BrandA/pla-basic/material.json",
                "Permission denied",
            ),
        ),
        (
            ValueError(
                "Material bundle file hash mismatch: "
                "/Users/min/private/materials/BrandA/pla-basic/material.json"
            ),
            502,
            (
                "/Users/min/private/materials/BrandA/pla-basic/material.json",
                "hash mismatch",
            ),
        ),
        (
            TypeError(
                "Material bundle manifest parser failed for "
                "/Users/min/private/materials/BrandA/pla-basic/material.json"
            ),
            502,
            (
                "/Users/min/private/materials/BrandA/pla-basic/material.json",
                "parser failed",
            ),
        ),
    ],
)
def test_material_sync_install_from_registry_failures_return_safe_detail(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
    exc: Exception,
    status_code: int,
    forbidden_fragments: tuple[str, ...],
) -> None:
    _enable_material_registry_password(monkeypatch)

    def _fake_install_material_registry_package(**_: object) -> dict[str, object]:
        raise exc

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _registry_install_catalog,
    )
    monkeypatch.setattr(
        "api.routers.material_sync.install_material_registry_package",
        _fake_install_material_registry_package,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().post(
            "/api/material-sync/install-from-registry",
            json={
                "package_url": "/v1/packages/material_package.zip",
                "package_sha256": "a" * 64,
                "material_id": "mat_cloud_test",
                "revision_id": "rev_cloud_test",
            },
            headers=_AUTH_HEADERS,
        )
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == status_code
    assert response.json()["detail"] == MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL
    for fragment in forbidden_fragments:
        assert fragment not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/install-from-registry",
        status_code=status_code,
        detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
        forbidden_fragments=forbidden_fragments,
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_install_from_registry_failed",
        error_type=type(exc).__name__,
        raw_fragment=forbidden_fragments[0],
        status_code=status_code,
    )
    route_record = _records_for_event(
        caplog,
        "material_sync_install_from_registry_failed",
    )[-1]
    assert getattr(route_record, "material_id", None) == "mat_cloud_test"
    assert getattr(route_record, "revision_id", None) == "rev_cloud_test"


def test_material_sync_install_from_registry_rejects_missing_catalog_entry_without_password(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_OFFICIAL_PASSWORD", _OFFICIAL_PASSWORD)
    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        lambda: {
            "schema_version": "1.0",
            "channels": ["official"],
            "count": 0,
            "materials": [],
        },
    )

    response = _client().post(
        "/api/material-sync/install-from-registry",
        json={
            "package_url": "/v1/packages/material_package.zip",
            "package_sha256": "a" * 64,
            "material_id": "mat_cloud_test",
            "revision_id": "rev_cloud_test",
        },
    )

    assert response.status_code == 422


def test_install_material_registry_package_imports_only_selected_material(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "multi_material_package.zip"
    package_info = _write_v2_multi_material_package(package_path)
    package_bytes = package_path.read_bytes()

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/packages/multi_material_package.zip":
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    result = install_material_registry_package(
        registry_url="https://registry.test/v1",
        package_url="/v1/packages/multi_material_package.zip",
        package_sha256=package_info["package_sha256"],
        material_id=package_info["selected_material_id"],
        revision_id=package_info["selected_revision_id"],
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["installed_count"] == 1
    assert result["installed_materials"][0]["directory_name"] == "BrandA/pla-selected"
    assert (materials_root / "BrandA" / "pla-selected" / "material.json").is_file()
    assert (materials_root / "BrandA" / "pla-other" / "material.json").exists() is False


def test_refresh_material_sync_from_registry_imports_only_catalog_revision(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "multi_material_package.zip"
    package_info = _write_v2_multi_material_package(package_path)
    package_bytes = package_path.read_bytes()

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": package_info["selected_material_id"],
                            "revision_id": package_info["selected_revision_id"],
                            "content_hash": package_info["selected_content_hash"],
                            "channel": "official",
                            "visibility": "official",
                            "package_url": "/v1/packages/multi_material_package.zip",
                            "package_sha256": package_info["package_sha256"],
                        }
                    ],
                },
            )
        if request.url.path == "/v1/packages/multi_material_package.zip":
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["installed_count"] == 1
    assert result["failed_count"] == 0
    assert result["installed_materials"][0]["directory_name"] == "BrandA/pla-selected"
    assert (materials_root / "BrandA" / "pla-selected" / "material.json").is_file()
    assert (materials_root / "BrandA" / "pla-other" / "material.json").exists() is False


def test_install_material_registry_package_rejects_cross_origin_package_url(
    tmp_path: Path,
) -> None:
    requested_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, content=b"not used")

    try:
        install_material_registry_package(
            registry_url="https://registry.test/v1",
            package_url="https://attacker.test/pkg.zip",
            package_sha256="a" * 64,
            material_id="mat_cloud_test",
            revision_id="rev_cloud_test",
            materials_dir=str(tmp_path / "materials"),
            token="team-token",
            transport=httpx.MockTransport(_handler),
        )
    except ValueError as exc:
        assert "same origin" in str(exc)
    else:
        raise AssertionError("Expected cross-origin package_url to be rejected")

    assert requested_urls == []


def test_install_material_registry_package_rejects_cross_origin_redirect(
    tmp_path: Path,
) -> None:
    requested_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.host == "registry.test":
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            )
        return httpx.Response(200, content=b"unexpected redirected request")

    try:
        install_material_registry_package(
            registry_url="https://registry.test/v1",
            package_url="/v1/packages/redirect.zip",
            package_sha256="a" * 64,
            material_id="mat_cloud_test",
            revision_id="rev_cloud_test",
            materials_dir=str(tmp_path / "materials"),
            token="team-token",
            transport=httpx.MockTransport(_handler),
        )
    except ValueError as exc:
        assert "redirects" in str(exc)
    else:
        raise AssertionError("Expected redirected package download to be rejected")

    assert requested_urls == ["https://registry.test/v1/packages/redirect.zip"]


def test_material_package_import_rejects_zip_entry_count_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "material_package.zip"
    _write_v2_material_package(package_path)
    monkeypatch.setenv("LUMINA_MATERIAL_PACKAGE_MAX_ZIP_ENTRIES", "2")

    with pytest.raises(ValueError, match="too many entries"):
        materials_module.import_saved_stage_a_material_archives(
            archive_path=str(package_path),
            materials_dir=str(tmp_path / "materials"),
        )


def test_refresh_material_sync_from_registry_rejects_oversized_package(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(package_path)
    package_bytes = package_path.read_bytes()
    monkeypatch.setenv(
        "LUMINA_MATERIAL_PACKAGE_MAX_ARCHIVE_BYTES",
        str(len(package_bytes) - 1),
    )

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
                            "package_sha256": hashlib.sha256(package_bytes).hexdigest(),
                        }
                    ],
                },
            )
        if request.url.path == "/v1/packages/material_package.zip":
            return httpx.Response(
                200,
                content=package_bytes,
                headers={"content-length": str(len(package_bytes))},
            )
        return httpx.Response(404)

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["installed_count"] == 0
    assert result["failed_count"] == 1
    assert "exceeds maximum size" in result["failures"][0]["error"]
    assert (materials_root / "BrandA" / "pla-basic" / "material.json").exists() is False


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


def test_refresh_material_sync_from_registry_rejects_cross_origin_package_url(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    requested_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_registry_test",
                            "revision_id": "rev_registry_test",
                            "content_hash": "sha256:abc",
                            "channel": "official",
                            "package_url": "https://attacker.test/pkg.zip",
                            "package_sha256": "a" * 64,
                        }
                    ],
                },
            )
        return httpx.Response(500)

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        token="team-token",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert requested_urls == ["https://registry.test/v1/materials/catalog?channel=official"]
    assert result["checked_count"] == 1
    assert result["installed_count"] == 0
    assert result["failed_count"] == 1
    assert "same origin" in result["failures"][0]["error"]
    assert (materials_root / "BrandA" / "pla-basic" / "material.json").exists() is False


def test_refresh_material_sync_from_registry_rejects_cross_origin_redirect(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    requested_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_registry_test",
                            "revision_id": "rev_registry_test",
                            "content_hash": "sha256:abc",
                            "channel": "official",
                            "package_url": "/v1/packages/redirect.zip",
                            "package_sha256": "a" * 64,
                        }
                    ],
                },
            )
        if request.url.host == "registry.test":
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            )
        return httpx.Response(200, content=b"unexpected redirected request")

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        token="team-token",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert requested_urls == [
        "https://registry.test/v1/materials/catalog?channel=official",
        "https://registry.test/v1/packages/redirect.zip",
    ]
    assert result["checked_count"] == 1
    assert result["installed_count"] == 0
    assert result["failed_count"] == 1
    assert "redirects" in result["failures"][0]["error"]
    assert (materials_root / "BrandA" / "pla-basic" / "material.json").exists() is False


def test_refresh_material_sync_from_registry_rejects_catalog_cross_origin_redirect(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    requested_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            )
        return httpx.Response(200, json={"schema_version": "1.0", "materials": []})

    with pytest.raises(RuntimeError, match="catalog redirects are not allowed"):
        refresh_material_sync_from_registry(
            registry_url="https://registry.test/v1",
            token="team-token",
            materials_dir=str(materials_root),
            transport=httpx.MockTransport(_handler),
        )

    assert requested_urls == [
        "https://registry.test/v1/materials/catalog?channel=official"
    ]
    assert (materials_root / "BrandA" / "pla-basic" / "material.json").exists() is False


def test_refresh_material_sync_from_registry_preserves_local_rollback(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    old_dir = materials_root / "BrandA" / "pla-basic"
    new_dir = materials_root / "BrandA" / "pla-basic-new"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    (old_dir / "material.json").write_text("{}", encoding="utf-8")
    (new_dir / "material.json").write_text("{}", encoding="utf-8")
    (materials_root / "_sync").mkdir()
    (materials_root / "_sync" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "installed": {
                    "mat_test": {
                        "revision_id": "rev_old",
                        "content_hash": "sha256:old",
                        "channel": "official",
                        "source": "package",
                        "local_directory": "BrandA/pla-basic",
                        "display_brand": "BrandA",
                        "display_name": "PLA Basic",
                    }
                },
                "revisions": {
                    "mat_test": {
                        "rev_new": {
                            "revision_id": "rev_new",
                            "content_hash": "sha256:new",
                            "channel": "official",
                            "source": "package",
                            "local_directory": "BrandA/pla-basic-new",
                            "display_brand": "BrandA",
                            "display_name": "PLA Basic",
                        },
                        "rev_old": {
                            "revision_id": "rev_old",
                            "content_hash": "sha256:old",
                            "channel": "official",
                            "source": "package",
                            "local_directory": "BrandA/pla-basic",
                            "display_brand": "BrandA",
                            "display_name": "PLA Basic",
                        },
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request_counts = {"catalog": 0, "package": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            request_counts["catalog"] += 1
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_test",
                            "revision_id": "rev_new",
                            "content_hash": "sha256:new",
                            "channel": "official",
                            "package_url": "/v1/packages/rev_new.zip",
                            "package_sha256": "a" * 64,
                        }
                    ],
                },
            )
        if request.url.path == "/v1/packages/rev_new.zip":
            request_counts["package"] += 1
            return httpx.Response(500)
        return httpx.Response(404)

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["checked_count"] == 1
    assert result["installed_count"] == 0
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 0
    assert request_counts == {"catalog": 1, "package": 0}
    index = json.loads((materials_root / "_sync" / "index.json").read_text("utf-8"))
    assert index["installed"]["mat_test"]["revision_id"] == "rev_old"


def test_refresh_material_sync_from_registry_preserves_index_when_catalog_unavailable(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "BrandA" / "pla-basic"
    material_dir.mkdir(parents=True)
    (material_dir / "material.json").write_text("{}", encoding="utf-8")
    sync_dir = materials_root / "_sync"
    sync_dir.mkdir()
    index_path = sync_dir / "index.json"
    index_payload = {
        "schema_version": "1.0",
        "installed": {
            "mat_test": {
                "revision_id": "rev_old",
                "content_hash": "sha256:old",
                "channel": "official",
                "source": "package",
                "local_directory": "BrandA/pla-basic",
                "display_brand": "BrandA",
                "display_name": "PLA Basic",
            }
        },
        "revisions": {
            "mat_test": {
                "rev_old": {
                    "revision_id": "rev_old",
                    "content_hash": "sha256:old",
                    "channel": "official",
                    "source": "package",
                    "local_directory": "BrandA/pla-basic",
                    "display_brand": "BrandA",
                    "display_name": "PLA Basic",
                }
            }
        },
    }
    index_path.write_text(json.dumps(index_payload, ensure_ascii=False), encoding="utf-8")
    before_index = index_path.read_text(encoding="utf-8")

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/materials/catalog"
        return httpx.Response(503, json={"detail": "temporarily unavailable"})

    with pytest.raises(RuntimeError, match="catalog request failed"):
        refresh_material_sync_from_registry(
            registry_url="https://registry.test/v1",
            materials_dir=str(materials_root),
            transport=httpx.MockTransport(_handler),
        )

    assert index_path.read_text(encoding="utf-8") == before_index
    assert (material_dir / "material.json").is_file()


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
        "available_revisions": [],
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


def test_material_library_api_marks_official_synced_material(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "BrandA" / "pla-basic"
    material_dir.mkdir(parents=True)
    (material_dir / "material.json").write_text(
        json.dumps(
            {
                "material_name": "PLA Basic",
                "brand": "BrandA",
                "stage_a_params_file": "stage_A_parameters.json",
                "material_summary": {"estimated_rgb": [120, 130, 140]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (material_dir / "stage_A_parameters.json").write_text("{}", encoding="utf-8")
    (materials_root / "_sync").mkdir()
    (materials_root / "_sync" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "installed": {
                    "mat_official": {
                        "revision_id": "rev_official",
                        "content_hash": "sha256:official",
                        "channel": "official",
                        "source": "package",
                        "local_directory": "BrandA/pla-basic",
                        "display_brand": "BrandA",
                        "display_name": "PLA Basic",
                    }
                },
                "revisions": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.single_stage.materials.MATERIALS_DIR", str(materials_root))

    response = _client().get("/api/extractor/gradient-card-materials")

    assert response.status_code == 200
    material = response.json()["materials"][0]
    assert material["sync_material_id"] == "mat_official"
    assert material["sync_revision_id"] == "rev_official"
    assert material["sync_channel"] == "official"
    assert material["sync_official"] is True


def test_material_library_api_marks_cloud_official_matching_local_material(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "BrandA" / "pla-basic"
    material_dir.mkdir(parents=True)
    material_payload = json.dumps(
        {
            "material_name": "PLA Basic",
            "brand": "BrandA",
            "stage_a_params_file": "stage_A_parameters.json",
            "material_summary": {"estimated_rgb": [120, 130, 140]},
        },
        ensure_ascii=False,
    )
    stage_a_payload = json.dumps({"parameters": {}}, ensure_ascii=False)
    (material_dir / "material.json").write_text(material_payload, encoding="utf-8")
    (material_dir / "stage_A_parameters.json").write_text(
        stage_a_payload,
        encoding="utf-8",
    )
    material_hash = hashlib.sha256(material_payload.encode("utf-8")).hexdigest()
    stage_a_hash = hashlib.sha256(stage_a_payload.encode("utf-8")).hexdigest()
    content_hash = "sha256:" + hashlib.sha256(
        f"material.json:{material_hash}\nstage_A_parameters.json:{stage_a_hash}".encode(
            "utf-8"
        )
    ).hexdigest()

    def _fake_list_material_registry_catalog(**_: object) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "channels": ["official"],
            "count": 1,
            "total_count": 1,
            "offset": 0,
            "limit": None,
            "materials": [
                {
                    "material_id": "mat_cloud_official",
                    "revision_id": "rev_cloud_official",
                    "content_hash": content_hash,
                    "channel": "official",
                    "visibility": "official",
                    "local_directory": "BrandA/pla-basic",
                    "display": {"brand": "BrandA", "material_name": "PLA Basic"},
                    "compatibility": {},
                    "package_url": "/v1/packages/official/pla-basic.zip",
                    "package_sha256": "a" * 64,
                    "package_bytes": 1024,
                }
            ],
        }

    monkeypatch.setattr(
        materials_module,
        "list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )
    monkeypatch.setattr("core.single_stage.materials.MATERIALS_DIR", str(materials_root))

    response = _client().get("/api/extractor/gradient-card-materials")

    assert response.status_code == 200
    material = response.json()["materials"][0]
    assert material["sync_material_id"] == "mat_cloud_official"
    assert material["sync_revision_id"] == "rev_cloud_official"
    assert material["sync_channel"] == "official"
    assert material["sync_official"] is True


def test_material_sync_rollback_switches_installed_revision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    old_dir = materials_root / "BrandA" / "pla-basic"
    new_dir = materials_root / "BrandA" / "pla-basic-new"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    (old_dir / "material.json").write_text("{}", encoding="utf-8")
    (new_dir / "material.json").write_text("{}", encoding="utf-8")
    (materials_root / "_sync").mkdir()
    (materials_root / "_sync" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "installed": {
                    "mat_test": {
                        "revision_id": "rev_new",
                        "content_hash": "sha256:new",
                        "channel": "official",
                        "source": "package",
                        "local_directory": "BrandA/pla-basic-new",
                        "display_brand": "BrandA",
                        "display_name": "PLA Basic",
                        "installed_at": "2026-06-08T02:00:00+00:00",
                        "updated_at": "2026-06-08T02:00:00+00:00",
                    }
                },
                "revisions": {
                    "mat_test": {
                        "rev_old": {
                            "revision_id": "rev_old",
                            "content_hash": "sha256:old",
                            "channel": "official",
                            "source": "package",
                            "local_directory": "BrandA/pla-basic",
                            "display_brand": "BrandA",
                            "display_name": "PLA Basic",
                            "installed_at": "2026-06-08T01:00:00+00:00",
                            "updated_at": "2026-06-08T01:00:00+00:00",
                        }
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.single_stage.materials.MATERIALS_DIR", str(materials_root))

    response = _client().post(
        "/api/material-sync/rollback",
        json={"material_id": "mat_test", "revision_id": "rev_old"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["material_id"] == "mat_test"
    assert body["revision_id"] == "rev_old"
    assert body["local_directory"] == "BrandA/pla-basic"

    index = json.loads((materials_root / "_sync" / "index.json").read_text("utf-8"))
    assert index["installed"]["mat_test"]["revision_id"] == "rev_old"
    assert "rev_new" in index["revisions"]["mat_test"]


def test_material_sync_rollback_is_local_without_official_password(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_OFFICIAL_PASSWORD", _OFFICIAL_PASSWORD)
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "BrandA" / "pla-basic"
    material_dir.mkdir(parents=True)
    (material_dir / "material.json").write_text("{}", encoding="utf-8")
    (materials_root / "_sync").mkdir()
    (materials_root / "_sync" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "installed": {},
                "revisions": {
                    "mat_test": {
                        "rev_old": {
                            "revision_id": "rev_old",
                            "content_hash": "sha256:old",
                            "channel": "official",
                            "source": "package",
                            "local_directory": "BrandA/pla-basic",
                        }
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.single_stage.materials.MATERIALS_DIR", str(materials_root))

    response = _client().post(
        "/api/material-sync/rollback",
        json={"material_id": "mat_test", "revision_id": "rev_old"},
    )

    assert response.status_code == 200
    assert response.json()["revision_id"] == "rev_old"


def test_material_sync_rollback_os_error_returns_safe_detail(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_path = "/Users/min/private/materials/_sync/index.json"

    def _fake_rollback_material_sync_revision(
        *,
        material_id: str,
        revision_id: str,
    ) -> dict[str, object]:
        raise OSError(f"[Errno 13] Permission denied: '{private_path}'")

    monkeypatch.setattr(
        "api.routers.material_sync.rollback_material_sync_revision",
        _fake_rollback_material_sync_revision,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().post(
            "/api/material-sync/rollback",
            json={"material_id": "mat_test", "revision_id": "rev_old"},
        )
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 500
    assert response.json()["detail"] == MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL
    assert private_path not in response.text
    assert "Permission denied" not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/rollback",
        status_code=500,
        detail=MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL,
        forbidden_fragments=(private_path, "Permission denied"),
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_rollback_failed",
        error_type="OSError",
        raw_fragment=private_path,
        status_code=500,
    )
    route_record = _records_for_event(caplog, "material_sync_rollback_failed")[-1]
    assert getattr(route_record, "material_id", None) == "mat_test"
    assert getattr(route_record, "revision_id", None) == "rev_old"


def test_rollback_material_sync_revision_rejects_missing_local_files(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    (materials_root / "_sync").mkdir(parents=True)
    (materials_root / "_sync" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "installed": {},
                "revisions": {
                    "mat_test": {
                        "rev_missing": {
                            "revision_id": "rev_missing",
                            "content_hash": "sha256:missing",
                            "channel": "official",
                            "source": "package",
                            "local_directory": "BrandA/missing",
                            "display_brand": "BrandA",
                            "display_name": "Missing",
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        rollback_material_sync_revision(
            material_id="mat_test",
            revision_id="rev_missing",
            materials_dir=str(materials_root),
        )
    except FileNotFoundError as exc:
        assert "material.json" in str(exc)
    else:
        raise AssertionError("rollback should reject missing material files")


def test_refresh_material_sync_from_registry_uses_cross_process_lock(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    sync_dir = materials_root / "_sync"
    sync_dir.mkdir(parents=True)
    (sync_dir / "refresh.lock").write_text("active", encoding="utf-8")
    request_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(500)

    try:
        refresh_material_sync_from_registry(
            registry_url="https://registry.test/v1",
            materials_dir=str(materials_root),
            transport=httpx.MockTransport(_handler),
        )
    except RuntimeError as exc:
        assert "already running" in str(exc)
    else:
        raise AssertionError("refresh should reject an active file lock")

    assert request_count == 0
