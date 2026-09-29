"""Integration test: full submit → ticket directory assembly.

端到端集成测试：POST /api/feedback/bug-report 后，工单目录包含
``ticket.json`` / ``original.*`` / ``final.*`` / ``index.md`` / ``summary.txt``。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "description": "Integration smoke",
        "user_email": "user@example.com",
        "context": {
            "url": "http://localhost:5174/",
            "user_agent": "pytest",
            "screen_width": 1280,
            "screen_height": 720,
            "device_pixel_ratio": 1.0,
            "app_version": "2.0.0",
            "language": "en",
            "theme": "light",
            "active_tab": "converter",
            "active_session_ids": {"converter": "sess-integration", "single_stage": None},
            "color_mode": "4-Color (RYBW)",
            "lut_name": None,
            "source_version": "legacy",
            "selected_native_brand_key": None,
            "selected_native_db_names": [],
            "selected_material_dir_names": [],
            "material_layer_count": None,
            "material_layer_height_mm": None,
            "material_backing_material_dir_name": None,
            "recent_client_logs": [],
            "action_history": [
                {
                    "timestamp": "2026-05-11T14:01:58",
                    "action_type": "upload_image",
                    "changed_fields": {},
                },
                {
                    "timestamp": "2026-05-11T14:02:58",
                    "action_type": "api_error",
                    "error": {
                        "status_code": 500,
                        "path": "/api/converter/generate",
                        "error_message": "boom",
                    },
                },
            ],
            "session_history": [
                {"workstream": "converter", "session_id": "sess-integration"},
            ],
            "active_original_image_ref": {"session_id": "sess-integration"},
            "active_final_artifact_ref": {
                "session_id": "sess-integration",
                "artifact_type": "3mf",
            },
        },
        "screenshot_data_url": None,
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def populated_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, Path]:
    """TestClient whose FileRegistry already knows about the user's files.

    FileRegistry 内预先注册了一张原图和一份 3MF 产物，供同步收集器拷贝。
    """
    from api.app import create_app
    from api.dependencies import get_file_registry
    import api.routers.feedback as feedback_router

    feedback_root = tmp_path / "feedback_root"
    feedback_root.mkdir()

    # Pre-populate source assets.
    source_dir = tmp_path / "source_assets"
    source_dir.mkdir()
    original_image = source_dir / "hello.png"
    original_image.write_bytes(b"PNGDATA_SENTINEL")
    final_artifact = source_dir / "model.3mf"
    final_artifact.write_bytes(b"3MFDATA_SENTINEL")

    monkeypatch.setenv("LUMINA_FEEDBACK_DUMP_DIR", str(feedback_root))
    monkeypatch.setenv("LUMINA_FEEDBACK_STARTUP_CLEANUP", "false")
    monkeypatch.setenv("LUMINA_FEEDBACK_SERVER_URL", "off")
    feedback_router._clear_feedback_rate_limit_state()

    app = create_app()
    registry = get_file_registry()
    registry.register_path(
        session_id="sess-integration",
        path=str(original_image),
        filename="hello.png",
    )
    registry.register_path(
        session_id="sess-integration",
        path=str(final_artifact),
        filename="model.3mf",
    )

    return TestClient(app), feedback_root


def test_full_submit_populates_ticket_directory(
    populated_client: tuple[TestClient, Path],
) -> None:
    client, feedback_root = populated_client
    response = client.post("/api/feedback/bug-report", json=_payload())

    assert response.status_code == 200
    data = response.json()
    ticket_id = data["ticket_id"]
    assert ticket_id.startswith("LUM-")
    assert data["assembly_status"] in ("in_progress", "done")

    month_dirs = [p for p in feedback_root.iterdir() if p.is_dir()]
    assert len(month_dirs) == 1
    ticket_dir = month_dirs[0] / ticket_id

    # Sync artifacts
    assert (ticket_dir / "ticket.json").exists()
    assert (ticket_dir / "original.png").exists()
    assert (ticket_dir / "original.png").read_bytes() == b"PNGDATA_SENTINEL"
    assert (ticket_dir / "final.3mf").exists()
    assert (ticket_dir / "final.3mf").read_bytes() == b"3MFDATA_SENTINEL"

    # Background task artifacts (TestClient runs them synchronously).
    assert (ticket_dir / "index.md").exists()
    assert (ticket_dir / "summary.txt").exists()

    payload = json.loads((ticket_dir / "ticket.json").read_text(encoding="utf-8"))
    assert payload["attachments"]["original_image"]["status"] == "attached"
    assert payload["attachments"]["final_artifact"]["status"] == "attached"
    assert payload["assembly_status"] in ("done", "partial_failed")

    index_md = (ticket_dir / "index.md").read_text(encoding="utf-8")
    assert ticket_id in index_md
    assert "original.png" in index_md
    assert "final.3mf" in index_md
    # Reproduction suggestion references the last API error.
    assert "/api/converter/generate" in index_md


def test_dynamic_material_state_is_preserved_in_all_ticket_views(
    populated_client: tuple[TestClient, Path],
) -> None:
    client, feedback_root = populated_client
    request_payload = _payload()
    request_payload["context"].update(
        {
            "source_version": "material",
            "selected_material_dir_names": ["BrandA", "BrandB"],
            "material_layer_count": 9,
            "material_dynamic_layer_count_enabled": True,
            "material_min_layer_count": 5,
            "material_max_layer_count": 9,
            "material_delta_e00_tolerance": 0.4,
            "material_layer_height_mm": 0.16,
            "material_backing_material_dir_name": "BrandA",
        }
    )

    response = client.post("/api/feedback/bug-report", json=request_payload)

    assert response.status_code == 200
    ticket_id = response.json()["ticket_id"]
    month_dirs = [path for path in feedback_root.iterdir() if path.is_dir()]
    assert len(month_dirs) == 1
    ticket_dir = month_dirs[0] / ticket_id

    ticket_payload = json.loads(
        (ticket_dir / "ticket.json").read_text(encoding="utf-8")
    )
    ticket_context = ticket_payload["context"]
    assert ticket_context["material_dynamic_layer_count_enabled"] is True
    assert ticket_context["material_min_layer_count"] == 5
    assert ticket_context["material_max_layer_count"] == 9
    assert ticket_context["material_delta_e00_tolerance"] == 0.4
    assert ticket_context["material_backing_material_dir_name"] == "BrandA"

    index_md = (ticket_dir / "index.md").read_text(encoding="utf-8")
    assert "material_dynamic_layer_count_enabled: True" in index_md
    assert "material_min_layer_count: 5" in index_md
    assert "material_max_layer_count: 9" in index_md
    assert "material_delta_e00_tolerance: 0.4" in index_md
    assert "material_backing_material_dir_name: BrandA" in index_md

    summary = (ticket_dir / "summary.txt").read_text(encoding="utf-8")
    assert "动态层数：开启" in summary
    assert "最小层数：5" in summary
    assert "最大层数：9" in summary
    assert "ΔE00 容差：0.4" in summary
    assert "底板：BrandA" in summary


def test_submit_returns_logical_dump_path_for_external_feedback_root(
    populated_client: tuple[TestClient, Path],
) -> None:
    """Response paths stay logical even when tickets are stored outside repo.

    即使反馈目录位于仓库外，响应路径也只返回逻辑定位，不暴露服务器绝对路径。
    """
    client, feedback_root = populated_client

    response = client.post("/api/feedback/bug-report", json=_payload())

    assert response.status_code == 200
    data = response.json()
    dump_path = data["dump_path"]
    assert dump_path.startswith("feedback/")
    assert data["ticket_id"] in dump_path
    assert not Path(dump_path).is_absolute()
    assert feedback_root.as_posix() not in dump_path


def test_submit_redacts_final_artifact_disk_path_from_persisted_payload(
    populated_client: tuple[TestClient, Path],
    tmp_path: Path,
) -> None:
    """Client-supplied disk paths are not persisted in feedback payloads.

    客户端上报的本地磁盘路径不应写入可转发的反馈 payload。
    """
    client, feedback_root = populated_client
    private_path = tmp_path / "private-output" / "model.3mf"
    private_path.parent.mkdir()
    private_path.write_bytes(b"LEGACY_DISK_PATH_SENTINEL")
    payload = _payload()
    payload["context"]["active_final_artifact_ref"]["disk_path"] = private_path.as_posix()

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    ticket_id = response.json()["ticket_id"]
    month_dirs = [p for p in feedback_root.iterdir() if p.is_dir()]
    assert len(month_dirs) == 1
    ticket_json = month_dirs[0] / ticket_id / "ticket.json"
    ticket_dir = ticket_json.parent
    persisted = json.loads(ticket_json.read_text(encoding="utf-8"))
    active_ref = persisted["context"]["active_final_artifact_ref"]
    assert "disk_path" not in active_ref
    assert private_path.as_posix() not in json.dumps(persisted, ensure_ascii=False)
    assert (ticket_dir / "final.3mf").read_bytes() == b"3MFDATA_SENTINEL"
