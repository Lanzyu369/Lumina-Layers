"""ColorChecker resource lifecycle tests."""

from __future__ import annotations

import io
import os
from types import SimpleNamespace

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.colorchecker_artifacts import (
    COLORCHECKER_FULL_PENDING_PURPOSE,
    COLORCHECKER_FULL_PURPOSE,
)
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from config import COLORCHECKER_TEMP_TTL_SECONDS


def _png_bytes(width: int = 8, height: int = 6) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (128, 96, 64)).save(buffer, format="PNG")
    return buffer.getvalue()


def _client_with_state() -> tuple[TestClient, SessionStore, FileRegistry]:
    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app), store, registry


def test_colorchecker_calibrate_returns_private_full_id_and_releases(
    monkeypatch,
) -> None:
    """Calibration should expose only preview URLs and private full-image id."""
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state()
    calibrated = np.zeros((80, 120, 3), dtype=np.uint8)
    calibrated[:, :] = [10, 120, 240]
    overlay = np.zeros((40, 60, 3), dtype=np.uint8)

    def fake_apply(*_args, **_kwargs):
        return SimpleNamespace(
            calibrated_image=calibrated,
            overlay_image=overlay,
            patch_points=[{"x": 1.0, "y": 2.0}] * 24,
            display_summary={"deltaE00": {"mean": 1.0, "median": 1.0, "p95": 2.0, "max": 3.0}},
        )

    monkeypatch.setattr(adapter, "apply_colorchecker_calibration", fake_apply)

    response = client.post(
        "/api/extractor/colorchecker-calibrate",
        data={"corner_points": "[[0,0],[1,0],[1,1],[0,1]]"},
        files={"image": ("chart.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert "calibrated_url" not in body
    assert body["calibrated_preview_url"].startswith("/api/files/")
    assert body["overlay_url"].startswith("/api/files/")
    assert body["full_width"] == 120
    assert body["full_height"] == 80
    assert body["preview_width"] == 120
    assert body["preview_height"] == 80

    full_id = body["calibrated_full_file_id"]
    entry = registry.get_entry(full_id)
    assert entry is not None
    assert entry["is_public"] is False
    assert entry["purpose"] == COLORCHECKER_FULL_PENDING_PURPOSE
    assert os.path.exists(entry["path"])
    assert client.get(f"/api/files/{full_id}").status_code == 404

    touch_pending_response = client.post(
        "/api/extractor/colorchecker-touch",
        data={"file_id": full_id},
    )
    assert touch_pending_response.status_code == 200
    assert touch_pending_response.json()["renewed"] is True

    confirm_response = client.post(
        "/api/extractor/colorchecker-confirm",
        data={"file_id": full_id},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["confirmed"] is True
    confirmed_entry = registry.get_entry(full_id)
    assert confirmed_entry is not None
    assert confirmed_entry["purpose"] == COLORCHECKER_FULL_PURPOSE

    touch_confirmed_response = client.post(
        "/api/extractor/colorchecker-touch",
        data={"file_id": full_id},
    )
    assert touch_confirmed_response.status_code == 200
    assert touch_confirmed_response.json()["renewed"] is True

    release_response = client.post(
        "/api/extractor/colorchecker-release",
        data={"file_id": full_id},
    )
    assert release_response.status_code == 200
    assert release_response.json()["released"] is True
    assert registry.resolve(full_id) is None
    assert os.path.exists(entry["path"]) is False


def test_colorchecker_warp_preview_uses_colorchecker_ttl(monkeypatch) -> None:
    """Warp preview should use the ColorChecker artifact TTL constant."""
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state()

    def fake_decode(*_args, **_kwargs):
        return SimpleNamespace(image_bgr=np.zeros((8, 8, 3), dtype=np.uint8))

    def fake_warp(*_args, **_kwargs):
        return SimpleNamespace(
            preview_png=_png_bytes(),
            preview_width=8,
            preview_height=6,
            auto_patch_points=[],
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_upload", fake_decode)
    monkeypatch.setattr(adapter, "warp_colorchecker_preview", fake_warp)

    response = client.post(
        "/api/extractor/colorchecker-warp-preview",
        data={"corner_points": "[[0,0],[1,0],[1,1],[0,1]]"},
        files={"image": ("chart.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    preview_id = response.json()["preview_url"].rsplit("/", 1)[-1]
    entry = registry.get_entry(preview_id)
    assert entry is not None
    assert entry["ttl_seconds"] == COLORCHECKER_TEMP_TTL_SECONDS


def test_extractor_uses_private_colorchecker_image_and_scales_points(
    tmp_path,
    monkeypatch,
) -> None:
    """LUT extraction should read the private full image without uploading it."""
    import api.routers.extractor as extractor_router

    client, _store, registry = _client_with_state()
    full_image_path = tmp_path / "full.png"
    Image.new("RGB", (40, 20), (10, 20, 30)).save(full_image_path, format="PNG")
    full_id = registry.register_path(
        "colorchecker:test",
        str(full_image_path),
        "full.png",
        ttl_seconds=600,
        is_public=False,
        purpose=COLORCHECKER_FULL_PURPOSE,
    )
    pending_id = registry.register_path(
        "colorchecker:pending",
        str(full_image_path),
        "pending.png",
        ttl_seconds=600,
        is_public=False,
        purpose=COLORCHECKER_FULL_PENDING_PURPOSE,
    )
    lut_path = tmp_path / "lut.json"
    lut_path.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_extraction(**kwargs):
        captured.update(kwargs)
        return (
            np.zeros((4, 4, 3), dtype=np.uint8),
            np.zeros((4, 4, 3), dtype=np.uint8),
            str(lut_path),
            "ok",
        )

    monkeypatch.setattr(extractor_router, "run_extraction", fake_run_extraction)

    pending_response = client.post(
        "/api/extractor/extract",
        data={
            "corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "colorchecker_calibrated_file_id": pending_id,
            "corner_points_width": "10",
            "corner_points_height": "10",
        },
    )
    assert pending_response.status_code == 404
    assert captured == {}

    response = client.post(
        "/api/extractor/extract",
        data={
            "corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "colorchecker_calibrated_file_id": full_id,
            "corner_points_width": "10",
            "corner_points_height": "10",
        },
    )

    assert response.status_code == 200
    assert captured["img"].shape == (20, 40, 3)
    assert captured["points"] == [[0, 0], [40, 0], [40, 20], [0, 20]]


def test_stage_a_uses_private_colorchecker_images_only_when_restored(
    tmp_path,
    monkeypatch,
) -> None:
    """Stage A should require explicit restored source for ColorChecker images."""
    import api.routers.single_stage as single_stage_router

    client, _store, registry = _client_with_state()
    white_path = tmp_path / "white.png"
    black_path = tmp_path / "black.png"
    Image.new("RGB", (40, 20), (200, 200, 200)).save(white_path, format="PNG")
    Image.new("RGB", (80, 40), (20, 20, 20)).save(black_path, format="PNG")
    white_id = registry.register_path(
        "colorchecker:white",
        str(white_path),
        "white.png",
        ttl_seconds=600,
        is_public=False,
        purpose=COLORCHECKER_FULL_PURPOSE,
    )
    black_id = registry.register_path(
        "colorchecker:black",
        str(black_path),
        "black.png",
        ttl_seconds=600,
        is_public=False,
        purpose=COLORCHECKER_FULL_PURPOSE,
    )
    pending_white_id = registry.register_path(
        "colorchecker:white:pending",
        str(white_path),
        "white-pending.png",
        ttl_seconds=600,
        is_public=False,
        purpose=COLORCHECKER_FULL_PENDING_PURPOSE,
    )
    params_path = tmp_path / "params.json"
    params_path.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_extract(
        white_rgb,
        black_rgb,
        white_points,
        black_points,
        zip_path,
        **kwargs,
    ):
        captured.update(
            {
                "white_shape": white_rgb.shape,
                "black_shape": black_rgb.shape,
                "white_points": white_points,
                "black_points": black_points,
                "image_source": kwargs.get("image_source"),
                "zip_path": zip_path,
            }
        )
        return SimpleNamespace(
            params_path=str(params_path),
            params_payload={},
            fit_summary={
                "substrate_count": 2,
                "channel_count": 3,
                "orientation_ranking": None,
            },
            material_summary={
                "sample_count": 2,
                "per_substrate_sample_count": 1,
                "grid_rows": 1,
                "grid_cols": 1,
                "layer_height_mm": 0.2,
            },
            source_summary={},
            warnings=[],
            white_warp_rgb=np.zeros((4, 4, 3), dtype=np.uint8),
            black_warp_rgb=np.zeros((4, 4, 3), dtype=np.uint8),
        )

    monkeypatch.setattr(
        single_stage_router,
        "extract_stage_a_material_from_gradient_cards",
        fake_extract,
    )

    raw_response = client.post(
        "/api/extractor/extract-gradient-card-stage-a",
        data={
            "white_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "black_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "white_colorchecker_file_id": white_id,
            "black_colorchecker_file_id": black_id,
            "image_source": "raw",
        },
        files={
            "white_image": ("white.png", _png_bytes(), "image/png"),
            "black_image": ("black.png", _png_bytes(), "image/png"),
            "dataset_zip": ("kit.zip", b"zip", "application/zip"),
        },
    )
    assert raw_response.status_code == 422
    assert captured == {}

    mixed_response = client.post(
        "/api/extractor/extract-gradient-card-stage-a",
        data={
            "white_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "black_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "white_colorchecker_file_id": white_id,
            "white_corner_points_width": "10",
            "white_corner_points_height": "10",
            "image_source": "restored",
        },
        files={
            "black_image": ("black.png", _png_bytes(), "image/png"),
            "dataset_zip": ("kit.zip", b"zip", "application/zip"),
        },
    )
    assert mixed_response.status_code == 422
    assert captured == {}

    restored_upload_response = client.post(
        "/api/extractor/extract-gradient-card-stage-a",
        data={
            "white_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "black_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "image_source": "restored",
        },
        files={
            "white_image": ("white.png", _png_bytes(), "image/png"),
            "black_image": ("black.png", _png_bytes(), "image/png"),
            "dataset_zip": ("kit.zip", b"zip", "application/zip"),
        },
    )
    assert restored_upload_response.status_code == 422
    assert captured == {}

    pending_response = client.post(
        "/api/extractor/extract-gradient-card-stage-a",
        data={
            "white_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "black_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "white_colorchecker_file_id": pending_white_id,
            "black_colorchecker_file_id": black_id,
            "white_corner_points_width": "10",
            "white_corner_points_height": "10",
            "black_corner_points_width": "10",
            "black_corner_points_height": "10",
            "image_source": "restored",
        },
        files={
            "dataset_zip": ("kit.zip", b"zip", "application/zip"),
        },
    )
    assert pending_response.status_code == 404
    assert captured == {}

    response = client.post(
        "/api/extractor/extract-gradient-card-stage-a",
        data={
            "white_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "black_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "white_colorchecker_file_id": white_id,
            "black_colorchecker_file_id": black_id,
            "white_corner_points_width": "10",
            "white_corner_points_height": "10",
            "black_corner_points_width": "10",
            "black_corner_points_height": "10",
            "image_source": "restored",
        },
        files={
            "dataset_zip": ("kit.zip", b"zip", "application/zip"),
        },
    )

    assert response.status_code == 200
    assert captured["white_shape"] == (20, 40, 3)
    assert captured["black_shape"] == (40, 80, 3)
    assert captured["white_points"] == [[0, 0], [40, 0], [40, 20], [0, 20]]
    assert captured["black_points"] == [[0, 0], [80, 0], [80, 40], [0, 40]]
    assert captured["image_source"] == "restored"
