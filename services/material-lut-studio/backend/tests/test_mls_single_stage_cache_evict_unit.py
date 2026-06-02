"""MLS single-stage material writes invalidate the data cache.
MLS single-stage 耗材写入会让 data cache 失效。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.dependencies import get_session_store
from backend.routers import data as data_module
from core.single_stage.materials import (
    MaterialArchiveDeleteResult,
    MaterialArchiveImportResult,
    MaterialArchiveSaveResult,
    MaterialArchiveUpdateResult,
)


def _write_material_files(tmp_path: Path) -> tuple[Path, Path]:
    """Create minimal material files that can be registered by FileRegistry."""
    archive_path = tmp_path / "brand" / "mat" / "material.json"
    params_path = tmp_path / "brand" / "mat" / "stage_a_params.json"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text("{}", encoding="utf-8")
    params_path.write_text("{}", encoding="utf-8")
    return archive_path, params_path


def _material_summary(archive_path: Path, params_path: Path) -> dict[str, object]:
    """Return the minimal saved-material summary required by response schemas."""
    return {
        "material_name": "Mat",
        "directory_name": "brand/mat",
        "brand": "brand",
        "archive_path": str(archive_path),
        "stage_a_params_path": str(params_path),
        "verification_count": 1,
    }


def test_save_gradient_card_material_evicts_mls_data_cache(monkeypatch, tmp_path) -> None:
    """MLS-hosted save endpoint evicts the saved material from data cache."""
    from api.routers import single_stage as single_stage_router

    archive_path, params_path = _write_material_files(tmp_path)
    evicted: list[str] = []

    def fake_save_stage_a_material_archive(**_kwargs) -> MaterialArchiveSaveResult:
        return MaterialArchiveSaveResult(
            archive_path=str(archive_path),
            stage_a_params_path=str(params_path),
            material_summary=_material_summary(archive_path, params_path),
        )

    monkeypatch.setattr(
        single_stage_router,
        "save_stage_a_material_archive",
        fake_save_stage_a_material_archive,
    )
    monkeypatch.setattr(
        data_module,
        "evict_material_cache",
        lambda directory_name: evicted.append(directory_name) or 0,
    )

    session_id = "mls-save-cache-evict"
    store = get_session_store()
    store.create(session_id)
    store.put(session_id, "gradient_card_stage_a_params", {"E": [1, 1, 1]})
    store.put(session_id, "gradient_card_fit_summary", {"ok": True})
    store.put(session_id, "gradient_card_material_summary", {"ok": True})
    store.put(session_id, "gradient_card_source_summary", {"ok": True})

    response = TestClient(create_app()).post(
        "/api/extractor/save-gradient-card-material",
        data={
            "session_id": session_id,
            "material_name": "Mat",
            "target_directory_name": "brand/mat",
            "save_mode": "merge",
        },
    )

    assert response.status_code == 200
    assert evicted == ["brand/mat"]


def test_update_gradient_card_material_evicts_mls_data_cache(monkeypatch, tmp_path) -> None:
    """MLS-hosted legacy update endpoint evicts the updated material."""
    from api.routers import single_stage as single_stage_router

    archive_path, params_path = _write_material_files(tmp_path)
    evicted: list[str] = []

    def fake_update_saved_stage_a_material_archive_metadata(
        **_kwargs,
    ) -> MaterialArchiveUpdateResult:
        return MaterialArchiveUpdateResult(
            archive_path=str(archive_path),
            stage_a_params_path=str(params_path),
            material_summary=_material_summary(archive_path, params_path),
        )

    monkeypatch.setattr(
        single_stage_router,
        "update_saved_stage_a_material_archive_metadata",
        fake_update_saved_stage_a_material_archive_metadata,
    )
    monkeypatch.setattr(
        data_module,
        "evict_material_cache",
        lambda directory_name: evicted.append(directory_name) or 0,
    )

    response = TestClient(create_app()).patch(
        "/api/extractor/gradient-card-materials/brand/mat",
        json={"material_name": "Mat"},
    )

    assert response.status_code == 200
    assert evicted == ["brand/mat"]


def test_legacy_update_evicts_normalized_directory_name(monkeypatch, tmp_path) -> None:
    """Legacy update evicts the normalized directory returned by core."""
    from api.routers import single_stage as single_stage_router

    archive_path, params_path = _write_material_files(tmp_path)
    evicted: list[str] = []

    def fake_update_saved_stage_a_material_archive_metadata(
        **_kwargs,
    ) -> MaterialArchiveUpdateResult:
        return MaterialArchiveUpdateResult(
            archive_path=str(archive_path),
            stage_a_params_path=str(params_path),
            material_summary=_material_summary(archive_path, params_path),
        )

    monkeypatch.setattr(
        single_stage_router,
        "update_saved_stage_a_material_archive_metadata",
        fake_update_saved_stage_a_material_archive_metadata,
    )
    monkeypatch.setattr(
        data_module,
        "evict_material_cache",
        lambda directory_name: evicted.append(directory_name) or 0,
    )

    response = TestClient(create_app()).patch(
        "/api/extractor/gradient-card-materials/brand%5Cmat",
        json={"material_name": "Mat"},
    )

    assert response.status_code == 200
    assert evicted == ["brand/mat"]


def test_native_update_evicts_normalized_directory_name(monkeypatch, tmp_path) -> None:
    """MLS-native update evicts the normalized directory returned by core."""
    from backend.routers import materials as materials_router

    archive_path, params_path = _write_material_files(tmp_path)
    evicted: list[str] = []

    def fake_update_saved_stage_a_material_archive_metadata(
        **_kwargs,
    ) -> MaterialArchiveUpdateResult:
        return MaterialArchiveUpdateResult(
            archive_path=str(archive_path),
            stage_a_params_path=str(params_path),
            material_summary=_material_summary(archive_path, params_path),
        )

    monkeypatch.setattr(
        materials_router,
        "update_saved_stage_a_material_archive_metadata",
        fake_update_saved_stage_a_material_archive_metadata,
    )
    monkeypatch.setattr(
        materials_router,
        "evict_material_cache",
        lambda directory_name: evicted.append(directory_name) or 0,
    )

    response = TestClient(create_app()).patch(
        "/api/mls/materials/brand%5Cmat",
        json={"material_name": "Mat"},
    )

    assert response.status_code == 200
    assert evicted == ["brand/mat"]


def test_delete_gradient_card_material_evicts_mls_data_cache(monkeypatch) -> None:
    """MLS-hosted legacy delete endpoint evicts the deleted material."""
    from api.routers import single_stage as single_stage_router

    evicted: list[str] = []

    def fake_delete_saved_stage_a_material_archive(
        **_kwargs,
    ) -> MaterialArchiveDeleteResult:
        return MaterialArchiveDeleteResult(
            directory_name="brand/mat",
            material_name="Mat",
            deleted_path="unused",
        )

    monkeypatch.setattr(
        single_stage_router,
        "delete_saved_stage_a_material_archive",
        fake_delete_saved_stage_a_material_archive,
    )
    monkeypatch.setattr(
        data_module,
        "evict_material_cache",
        lambda directory_name: evicted.append(directory_name) or 0,
    )

    response = TestClient(create_app()).delete(
        "/api/extractor/gradient-card-materials/brand/mat",
    )

    assert response.status_code == 200
    assert evicted == ["brand/mat"]


def test_import_gradient_card_materials_evicts_mls_data_cache(monkeypatch, tmp_path) -> None:
    """MLS-hosted legacy import endpoint evicts every imported material."""
    from api.routers import single_stage as single_stage_router

    archive_path, params_path = _write_material_files(tmp_path)
    evicted: list[str] = []

    def fake_import_saved_stage_a_material_archives(
        **_kwargs,
    ) -> MaterialArchiveImportResult:
        return MaterialArchiveImportResult(
            imported_materials=[_material_summary(archive_path, params_path)]
        )

    monkeypatch.setattr(
        single_stage_router,
        "import_saved_stage_a_material_archives",
        fake_import_saved_stage_a_material_archives,
    )
    monkeypatch.setattr(
        data_module,
        "evict_material_cache",
        lambda directory_name: evicted.append(directory_name) or 0,
    )

    response = TestClient(create_app()).post(
        "/api/extractor/gradient-card-materials/import",
        files={"archives": ("materials.zip", b"placeholder", "application/zip")},
    )

    assert response.status_code == 200
    assert evicted == ["brand/mat"]
