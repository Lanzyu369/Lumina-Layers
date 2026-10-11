from __future__ import annotations

from pathlib import Path
import io

import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_session_store, get_file_registry, get_worker_pool
from api.file_registry import FileRegistry
from api.session_store import SessionStore

from fastapi import HTTPException
import pytest

from api.export_device_validation import validate_export_device_selection


def test_export_device_validation_allows_legacy_requests_without_registry_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", "/missing/registry")

    validate_export_device_selection(
        printer_id="bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id=None,
        build_plate_id=None,
    )


def test_export_device_validation_accepts_supported_device_and_plate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUMINA_MACHINE_REGISTRY_DIR", raising=False)

    validate_export_device_selection(
        printer_id="bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
        build_plate_id="textured-pei-plate",
    )


@pytest.mark.parametrize(
    ("overrides", "detail_fragment"),
    [
        (
            {"device_profile_id": None, "build_plate_id": "textured-pei-plate"},
            "requires device_profile_id",
        ),
        (
            {"device_profile_id": "missing-device"},
            "Unknown machine registry device profile",
        ),
        (
            {"printer_id": "bambu-p1s"},
            "does not match requested printer",
        ),
        (
            {"slicer": "OrcaSlicer"},
            "does not match requested slicer/nozzle",
        ),
        (
            {"nozzle_size": "0.2"},
            "does not match requested slicer/nozzle",
        ),
        (
            {"build_plate_id": "cool-plate"},
            "Unsupported build plate",
        ),
    ],
)
def test_export_device_validation_rejects_invalid_combinations_with_422(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, str | None],
    detail_fragment: str,
) -> None:
    monkeypatch.delenv("LUMINA_MACHINE_REGISTRY_DIR", raising=False)
    selection: dict[str, str | None] = {
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.4",
        "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
        "build_plate_id": "textured-pei-plate",
    }
    selection.update(overrides)

    with pytest.raises(HTTPException) as exc_info:
        validate_export_device_selection(**selection)

    assert exc_info.value.status_code == 422
    assert detail_fragment in str(exc_info.value.detail)


def test_export_device_validation_reports_missing_explicit_registry_as_503(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "LUMINA_MACHINE_REGISTRY_DIR",
        str(tmp_path / "missing-registry"),
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_export_device_selection(
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            nozzle_size="0.4",
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
            build_plate_id="textured-pei-plate",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Machine registry is unavailable."


@pytest.mark.parametrize(
    "registry_json",
    [
        '{"schema_version": 1, "generated_at": "test", "slicers": [{}]}',
        '{"schema_version": 1, "generated_at": "test", "slicers": null}',
    ],
)
def test_export_device_validation_reports_malformed_registry_as_503(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    registry_json: str,
) -> None:
    registry_root = tmp_path / "machine-registry"
    registry_root.mkdir()
    (registry_root / "registry.json").write_text(registry_json, encoding="utf-8")
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    with pytest.raises(HTTPException) as exc_info:
        validate_export_device_selection(
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            nozzle_size="0.4",
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
            build_plate_id="textured-pei-plate",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Machine registry is unavailable."


@pytest.mark.parametrize(("path", "params"), [
    ("/api/convert/generate", {"params": {"lut_name": "unused.json"}}),
    ("/api/convert/generate-large-format", {"params": {"params": {"lut_name": "unused.json"}}}),
    ("/api/convert/generate-puzzle", {"params": {"target_height_mm": 30, "params": {"lut_name": "unused.json"}}}),
    ("/api/calibration/generate", {}),
    ("/api/calibration/generate-single-stage-kit", {"palette": [
        {"color": "White"}, {"color": "Red"}, {"color": "Yellow"}, {"color": "Blue"},
    ]}),
    ("/api/five-color/generate-swatch", {"lut_name": "unused.json", "recipes": [
        {"selected_indices": [0, 1, 2, 3, 0, 1], "result_hex": "#ff0000"},
    ]}),
    ("/api/extractor/generate-material-swatch", {"recipes": [
        {"directory_names": ["white"], "result_hex": "#ffffff"},
    ]}),
    ("/api/convert/batch", None),
])
def test_export_routes_reject_invalid_device_before_worker(path, params, monkeypatch):
    monkeypatch.delenv("LUMINA_MACHINE_REGISTRY_DIR", raising=False)
    store = SessionStore()
    session_id = store.create()
    store.put(session_id, "preview_cache", {"matched_rgb": np.zeros((2, 2, 3), dtype=np.uint8)})
    monkeypatch.setitem(app.dependency_overrides, get_session_store, lambda: store)
    monkeypatch.setitem(app.dependency_overrides, get_file_registry, lambda: FileRegistry())
    # An accidental worker call fails immediately instead of doing export work.
    monkeypatch.setitem(app.dependency_overrides, get_worker_pool, lambda: object())
    client = TestClient(app)

    if params is None:
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2)).save(buffer, format="PNG")
        response = client.post(path, data={"device_profile_id": "missing-device", "lut_name": "unused.json"},
                               files={"images": ("source.png", buffer.getvalue(), "image/png")})
    else:
        payload = dict(params)
        if path.startswith("/api/convert/"):
            payload["session_id"] = session_id
            options = dict(payload["params"])
            if "params" in options:
                options["params"] = {**options["params"], "device_profile_id": "missing-device"}
            else:
                options["device_profile_id"] = "missing-device"
            payload["params"] = options
        else:
            payload["device_profile_id"] = "missing-device"
        response = client.post(path, json=payload)

    assert response.status_code == 422
    assert "Unknown machine registry device profile" in str(response.json()["detail"])
