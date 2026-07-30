"""Unit tests for the feedback router.

测试覆盖：
- 同步路径返回 ``assembly_status == 'in_progress'``、
  ``email_status`` 为 ``'pending'`` / ``'unconfigured'``
- 工单目录 ``feedback/<YYYY-MM>/<ticket_id>/ticket.json`` 正确落地
- 失败场景（screenshot 过大 / 校验失败 / 限流 / 目录写入失败）
- 现有 relay 行为保持不变
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

UNTRUSTED_ORIGIN_HEADERS = {"Origin": "https://attacker.example"}
LOCAL_FRONTEND_ORIGIN_HEADERS = {"Origin": "http://localhost:5174"}
DESCRIPTION_RAW_DIAGNOSTICS = (
    r"导出失败：AxiosError: Request failed with status code 500 "
    r"at /Users/min/private/model.3mf; retry /api/files/output-model; "
    r"file:///Users/min/private/source.png; C:\Users\min\secret\source.png"
)
GENERIC_HTTP_STATUS_DETAIL = (
    "The server reported an error while processing this request."
)


def _capture_feedback_logger(
    caplog: pytest.LogCaptureFixture,
    level: int,
) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.routers.feedback")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(level, logger=target_logger.name)
    return target_logger


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "description": "Preview failed after generate.",
        "user_email": None,
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
            "active_session_ids": {"converter": "session-abcdef", "single_stage": None},
            "color_mode": "4-Color (RYBW)",
            "lut_name": None,
            "source_version": "legacy",
            "selected_native_brand_key": None,
            "selected_native_db_names": [],
            "selected_material_dir_names": [],
            "material_layer_count": None,
            "material_layer_height_mm": None,
            "material_backing_material_dir_name": None,
            "recent_client_logs": [
                {
                    "timestamp": "2026-05-10T01:02:03.000Z",
                    "method": "error",
                    "label": "api: request failed",
                    "elapsed_ms": 12.346,
                    "scope": "api",
                    "phase": "request-failed",
                    "details": {"status_code": 500},
                }
            ],
            "action_history": [],
            "session_history": [],
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
            "advanced_params": None,
        },
        "screenshot_data_url": None,
    }
    payload.update(overrides)
    return payload


def _read_ticket_json(feedback_root: Path, ticket_id: str) -> dict[str, Any]:
    """Locate ``feedback/<YYYY-MM>/<ticket_id>/ticket.json`` and decode it."""
    for month_dir in feedback_root.iterdir():
        if not month_dir.is_dir():
            continue
        candidate = month_dir / ticket_id / "ticket.json"
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise AssertionError(f"ticket.json for {ticket_id} not found under {feedback_root}")


def _iter_json_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for key, item in value.items():
            strings.append(str(key))
            strings.extend(_iter_json_strings(item))
        return strings
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_iter_json_strings(item))
        return strings
    return []


def _assert_description_diagnostics_redacted(text: str) -> None:
    assert "Request failed with status code 500" not in text
    assert "AxiosError" not in text
    assert "/Users/min/private" not in text
    assert "file:///Users/min" not in text
    assert r"C:\Users\min" not in text
    assert "[redacted_local_path]" in text
    assert GENERIC_HTTP_STATUS_DETAIL in text
    assert "/api/files/output-model" in text


@pytest.fixture()
def feedback_root(tmp_path: Path) -> Path:
    root = tmp_path / "feedback_root"
    root.mkdir()
    return root


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch,
    feedback_root: Path,
) -> TestClient:
    from api.app import create_app
    import api.feedback_email as feedback_email
    import api.routers.feedback as feedback_router

    monkeypatch.setenv("LUMINA_FEEDBACK_DUMP_DIR", str(feedback_root))
    monkeypatch.setenv("LUMINA_FEEDBACK_STARTUP_CLEANUP", "false")
    monkeypatch.delenv("LUMINA_FEEDBACK_SMTP_HOST", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_TO", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_RATE_LIMIT_MAX", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_RATE_LIMIT_WINDOW_S", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_RELAY_URL", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_RELAY_TOKEN", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_RELAY_TIMEOUT_S", raising=False)
    feedback_email.is_email_configured.cache_clear()
    feedback_router._clear_feedback_rate_limit_state()
    app = create_app()
    return TestClient(app)


def test_submit_bug_report_accepts_full_payload_and_logs_canary(
    client: TestClient,
    feedback_root: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _capture_feedback_logger(caplog, logging.INFO)
    payload = _payload(
        user_email="user@example.com",
        screenshot_data_url="data:image/png;base64," + ("a" * 1024),
    )

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["ticket_id"].startswith("LUM-")
    assert data["emailed"] is False
    assert data["email_status"] == "unconfigured"
    assert data["assembly_status"] in ("in_progress", "done", "partial_failed")
    assert data["relay_available"] is False
    assert data["dump_path"].endswith(data["ticket_id"])

    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["schema_version"] == 3
    assert ticket_json["ticket_id"] == data["ticket_id"]
    assert ticket_json["description"] == payload["description"]
    assert ticket_json["attachments"]["screenshot"]["status"] == "attached"

    canaries = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_submitted"
    ]
    assert len(canaries) == 1
    assert canaries[0].ticket_id == data["ticket_id"]
    assert canaries[0].description_length == len(payload["description"])
    assert canaries[0].language == "en"
    assert canaries[0].has_screenshot is True
    assert canaries[0].email_status == "unconfigured"
    assert canaries[0].source_version == "legacy"
    assert canaries[0].recent_client_log_count == 1


def test_submit_bug_report_rejects_untrusted_origin_before_ticket_write(
    client: TestClient,
    feedback_root: Path,
) -> None:
    response = client.post(
        "/api/feedback/bug-report",
        json=_payload(description="cross-origin probe"),
        headers=UNTRUSTED_ORIGIN_HEADERS,
    )

    assert response.status_code == 403
    assert "local Lumina Studio app" in response.json()["detail"]
    assert list(feedback_root.rglob("ticket.json")) == []


def test_submit_bug_report_allows_untrusted_origin_for_public_gray_api(
    client: TestClient,
    feedback_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_ALLOW_PUBLIC_GRAY_API", "1")
    response = client.post(
        "/api/feedback/bug-report",
        json=_payload(description="cross-origin probe"),
        headers=UNTRUSTED_ORIGIN_HEADERS,
    )

    assert response.status_code == 200
    ticket_json = _read_ticket_json(feedback_root, response.json()["ticket_id"])
    assert ticket_json["description"] == "cross-origin probe"


def test_submit_bug_report_allows_local_frontend_origin(
    client: TestClient,
    feedback_root: Path,
) -> None:
    response = client.post(
        "/api/feedback/bug-report",
        json=_payload(description="local frontend report"),
        headers=LOCAL_FRONTEND_ORIGIN_HEADERS,
    )

    assert response.status_code == 200
    ticket_id = response.json()["ticket_id"]
    ticket_json = _read_ticket_json(feedback_root, ticket_id)
    assert ticket_json["description"] == "local frontend report"


def test_submit_bug_report_rejects_unregistered_final_artifact_disk_path(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """A crafted disk_path cannot attach an unregistered output artifact.

    构造请求中的 disk_path 不能把未注册 output 产物附进反馈工单。
    """
    from api.feedback_assembler import REPO_ROOT

    output_dir = REPO_ROOT / "output" / "feedback_security_probe"
    output_dir.mkdir(parents=True, exist_ok=True)
    sentinel = output_dir / "foreign_model.3mf"
    sentinel.write_bytes(b"PK\x03\x04FOREIGN_MODEL_SENTINEL")

    try:
        payload = _payload()
        payload["context"]["active_final_artifact_ref"] = {
            "session_id": "not-the-current-session",
            "download_url": None,
            "artifact_type": "3mf",
            "disk_path": str(sentinel),
            "source": "converter",
        }

        response = client.post("/api/feedback/bug-report", json=payload)

        assert response.status_code == 200
        data = response.json()
        ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
        final_artifact = ticket_json["attachments"]["final_artifact"]
        assert final_artifact["status"] == "expired_ttl"

        month_dir = next(
            p for p in feedback_root.iterdir() if p.is_dir() and p.name.startswith("20")
        )
        ticket_dir = month_dir / data["ticket_id"]
        assert not (ticket_dir / "final.3mf").exists()
        assert not (ticket_dir / "final.zip").exists()
    finally:
        sentinel.unlink(missing_ok=True)
        try:
            output_dir.rmdir()
        except OSError:
            pass


def test_submit_bug_report_accepts_description_only(client: TestClient) -> None:
    response = client.post("/api/feedback/bug-report", json=_payload(description="Only text"))

    assert response.status_code == 200
    data = response.json()
    assert data["emailed"] is False
    assert data["email_status"] == "unconfigured"
    assert data["assembly_status"] in ("in_progress", "done", "partial_failed")


def test_feedback_description_sanitizer_preserves_safe_text_and_api_context() -> None:
    from api.routers.feedback import _sanitize_bug_report_description

    ordinary = "中文描述：切换到 8 色时 3D 预览异常"
    assert _sanitize_bug_report_description(ordinary) == ordinary

    sanitized = _sanitize_bug_report_description(DESCRIPTION_RAW_DIAGNOSTICS)
    _assert_description_diagnostics_redacted(sanitized)

    api_query = (
        "AxiosError: Request failed with status code 500 "
        "at /api/files/output-model?token=secret#debug"
    )
    query_sanitized = _sanitize_bug_report_description(api_query)
    assert query_sanitized == (
        f"{GENERIC_HTTP_STATUS_DETAIL} Context: /api/files/output-model"
    )
    assert "token=secret" not in query_sanitized


def test_submit_bug_report_sanitizes_description_for_export(
    client: TestClient,
    feedback_root: Path,
) -> None:
    response = client.post(
        "/api/feedback/bug-report",
        json=_payload(description=DESCRIPTION_RAW_DIAGNOSTICS),
    )

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    ticket_dir = next(feedback_root.glob(f"*/{data['ticket_id']}"))
    exported_text = "\n".join(
        [
            json.dumps(ticket_json, ensure_ascii=False),
            (ticket_dir / "index.md").read_text(encoding="utf-8"),
            (ticket_dir / "summary.txt").read_text(encoding="utf-8"),
        ]
    )
    _assert_description_diagnostics_redacted(exported_text)


def test_submit_bug_report_returns_pending_email_status_when_configured(
    client: TestClient,
    feedback_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    email_calls: list[dict[str, Any]] = []

    async def _send(**kwargs: Any) -> bool:
        email_calls.append(kwargs)
        return True

    monkeypatch.setenv("LUMINA_FEEDBACK_SMTP_HOST", "localhost")
    monkeypatch.setenv("LUMINA_FEEDBACK_TO", "dev@example.com")
    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_URL", "https://relay.example.test/feedback")
    monkeypatch.setattr("api.feedback_email.send_bug_report_email_async", _send)
    import api.feedback_email as feedback_email

    feedback_email.is_email_configured.cache_clear()

    private_path = tmp_path / "private-output" / "model.3mf"
    payload = _payload(description=DESCRIPTION_RAW_DIAGNOSTICS)
    payload["context"]["recent_client_logs"] = [
        {
            "timestamp": "2026-05-10T01:02:03.000Z",
            "method": "error",
            "label": "api: request failed",
            "elapsed_ms": 12.346,
            "scope": "api",
            "phase": "request-failed",
            "details": {
                "status_code": 500,
                "api_path": "/api/files/output-model",
                "api_path_transport_error": (
                    "Request failed with status code 500 at /api/files/output-model"
                ),
            },
        }
    ]
    payload["context"]["active_final_artifact_ref"] = {
        "session_id": "session-abcdef",
        "download_url": None,
        "artifact_type": "3mf",
        "disk_path": private_path.as_posix(),
        "source": "converter",
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    # The new handler defers email to the background task; the sync response
    # should report 'pending' when SMTP is configured and relay availability.
    assert data["emailed"] is False
    assert data["email_status"] == "pending"
    assert data["relay_available"] is True
    email_payload = email_calls[0]["request_payload"]
    _assert_description_diagnostics_redacted(
        json.dumps(email_payload, ensure_ascii=False)
    )
    active_ref = email_payload["context"]["active_final_artifact_ref"]
    assert "disk_path" not in active_ref
    assert private_path.as_posix() not in json.dumps(email_payload, ensure_ascii=False)
    email_log_details = email_payload["context"]["recent_client_logs"][0]["details"]
    assert email_log_details["api_path_transport_error"] == (
        "The server reported an error while processing this request. "
        "Context: /api/files/output-model"
    )
    assert email_log_details["status_code"] == 500
    assert email_log_details["api_path"] == "/api/files/output-model"
    assert "Request failed with status code 500" not in json.dumps(
        email_payload,
        ensure_ascii=False,
    )
    from api.feedback_email import _build_email_message

    email_message = _build_email_message(
        ticket_id=data["ticket_id"],
        request_payload=email_payload,
        dump_path=email_calls[0]["dump_path"],
        smtp_from="from@example.com",
        smtp_to=["dev@example.com"],
    )
    json_attachments = [
        attachment
        for attachment in email_message.iter_attachments()
        if attachment.get_filename() == f"{data['ticket_id']}.json"
    ]
    assert len(json_attachments) == 1
    attached_payload = json.loads(
        json_attachments[0].get_payload(decode=True).decode("utf-8")
    )
    _assert_description_diagnostics_redacted(
        json.dumps(attached_payload, ensure_ascii=False)
    )
    attached_details = attached_payload["context"]["recent_client_logs"][0]["details"]
    assert attached_details["api_path_transport_error"] == (
        "The server reported an error while processing this request. "
        "Context: /api/files/output-model"
    )
    assert "Request failed with status code 500" not in json.dumps(
        attached_payload,
        ensure_ascii=False,
    )
    email_dump_path = email_calls[0]["dump_path"]
    assert email_dump_path.startswith("feedback/")
    assert data["ticket_id"] in email_dump_path
    assert not Path(email_dump_path).is_absolute()
    assert feedback_root.as_posix() not in email_dump_path


def test_submit_bug_report_assembly_marks_done_after_background_task(
    client: TestClient,
    feedback_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TestClient runs BackgroundTasks synchronously after the response body.

    Starlette TestClient 会在响应返回后同步执行 BackgroundTasks，
    因此 ``ticket.json`` 应已被装配器标记为 ``done`` 或 ``partial_failed``。
    """
    response = client.post("/api/feedback/bug-report", json=_payload(description="Assembly"))

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["assembly_status"] in ("done", "partial_failed")
    # Index + summary should have been rendered by finalize_ticket_async.
    month_dir = next(
        p for p in feedback_root.iterdir() if p.is_dir() and p.name.startswith("20")
    )
    ticket_dir = month_dir / data["ticket_id"]
    assert (ticket_dir / "index.md").exists()
    assert (ticket_dir / "summary.txt").exists()


def test_submit_bug_report_marks_partial_when_declared_attachments_missing(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload(description="Missing repro attachments")
    payload["context"]["active_session_ids"] = {
        "converter": "missing-repro-session",
        "single_stage": None,
    }
    payload["context"]["active_original_image_ref"] = {
        "session_id": "missing-repro-session",
        "filename": "source.png",
        "source": "converter",
    }
    payload["context"]["active_final_artifact_ref"] = {
        "session_id": "missing-repro-session",
        "download_url": "/api/files/missing-final-id",
        "artifact_type": "3mf",
        "disk_path": None,
        "source": "converter",
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["attachments"]["original_image"]["status"] == (
        "unavailable_after_cleanup"
    )
    assert ticket_json["attachments"]["final_artifact"]["status"] == "expired_ttl"
    assert ticket_json["assembly_status"] == "partial_failed"


def test_submit_bug_report_marks_failed_when_attachment_copy_fails(
    client: TestClient,
    feedback_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    from api.dependencies import get_file_registry

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_image = source_dir / "source.png"
    source_image.write_bytes(b"PNGDATA")
    source_model = source_dir / "model.3mf"
    source_model.write_bytes(b"3MFDATA")
    session_id = "copy-fails-session"
    registry = get_file_registry()
    registry.register_path(
        session_id=session_id,
        path=str(source_image),
        filename="source.png",
    )
    registry.register_path(
        session_id=session_id,
        path=str(source_model),
        filename="model.3mf",
    )

    original_copy2 = shutil.copy2

    def _fail_ticket_copy(src: object, dst: object, *args: object, **kwargs: object) -> object:
        if Path(dst).name in {"original.png", "final.3mf"}:
            raise OSError("disk full")
        return original_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr("api.feedback_assembler.shutil.copy2", _fail_ticket_copy)

    payload = _payload(description="Copy fails during attachment collection")
    payload["context"]["active_session_ids"] = {
        "converter": session_id,
        "single_stage": None,
    }
    payload["context"]["active_original_image_ref"] = {
        "session_id": session_id,
        "filename": "source.png",
        "source": "converter",
    }
    payload["context"]["active_final_artifact_ref"] = {
        "session_id": session_id,
        "download_url": None,
        "artifact_type": "3mf",
        "disk_path": None,
        "source": "converter",
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    original = ticket_json["attachments"]["original_image"]
    final = ticket_json["attachments"]["final_artifact"]
    assert original["status"] == "failed"
    assert original["error_type"] == "OSError"
    assert original["error_message"] == "Original image could not be saved."
    assert final["status"] == "failed"
    assert final["error_type"] == "OSError"
    assert final["error_message"] == "Final artifact could not be saved."
    assert ticket_json["assembly_status"] == "partial_failed"


def test_submit_bug_report_preserves_material_source_context(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload()
    payload["context"] = {
        **payload["context"],
        "color_mode": None,
        "lut_name": None,
        "source_version": "material",
        "selected_material_dir_names": ["Aliz/red", "Wujing/white"],
        "material_layer_count": 10,
        "material_layer_height_mm": 0.06,
        "material_backing_material_dir_name": "Wujing/white",
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["context"]["source_version"] == "material"
    assert ticket_json["context"]["lut_name"] is None
    assert ticket_json["context"]["selected_material_dir_names"] == ["Aliz/red", "Wujing/white"]
    assert ticket_json["context"]["material_layer_count"] == 10
    assert ticket_json["context"]["material_layer_height_mm"] == 0.06
    assert ticket_json["context"]["material_backing_material_dir_name"] == "Wujing/white"
    assert ticket_json["server"]["schema_version"] == 3


def test_submit_bug_report_persists_only_safe_workshop_runtime_metadata(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload()
    payload["context"]["active_tab"] = "workshop"
    payload["context"]["workshop"] = {
        "module_id": "lumina.bead-pattern",
        "module_version": "1.0.0",
        "install_source": "seed",
        "audit_status": "official",
        "runtime_mode": "desktop-secure",
        "error_code": None,
        "project_schema_version": "bead-project/v1",
        "input_mode": "numbered-grid",
        "rows": 52,
        "columns": 52,
        "compression": 50,
        "palette": [{"name": "private-red", "hex": "#ff0000"}],
        "cellsRle": [[2704, 1]],
        "sourcePath": "/Users/min/private-pattern.png",
        "imageBytes": "private-image-bytes",
        "packagePath": "/Users/min/private-module.lumina-workshop",
        "githubToken": "ghp_private-token",
        "registrySignature": "private-registry-signature",
        "desktopToken": "private-desktop-token",
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    ticket_json = _read_ticket_json(
        feedback_root,
        response.json()["ticket_id"],
    )
    assert ticket_json["context"]["workshop"] == {
        "module_id": "lumina.bead-pattern",
        "module_version": "1.0.0",
        "install_source": "seed",
        "audit_status": "official",
        "runtime_mode": "desktop-secure",
        "error_code": None,
    }


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("module_id", "m" * 129),
        ("module_version", "v" * 129),
        ("install_source", "remote"),
        ("audit_status", "trusted"),
        ("runtime_mode", "browser"),
        ("error_code", "e" * 129),
    ],
)
def test_submit_bug_report_rejects_out_of_bounds_workshop_diagnostics(
    client: TestClient,
    feedback_root: Path,
    field_name: str,
    bad_value: object,
) -> None:
    payload = _payload()
    payload["context"]["workshop"] = {
        "module_id": "lumina.bead-pattern",
        "module_version": "1.0.0",
        "install_source": "seed",
        "audit_status": "official",
        "runtime_mode": "desktop-secure",
        "error_code": None,
        field_name: bad_value,
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 422
    assert list(feedback_root.rglob("ticket.json")) == []


def test_submit_bug_report_accepts_older_client_without_workshop_context(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload()
    payload["context"].pop("workshop", None)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    ticket_json = _read_ticket_json(
        feedback_root,
        response.json()["ticket_id"],
    )
    assert ticket_json["context"]["workshop"] is None


def test_submit_bug_report_sanitizes_recent_client_logs(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload()
    payload["context"]["recent_client_logs"] = [
        {
            "label": f"event-{index}",
            "elapsed_ms": index + 0.12345,
            "details": {
                "long": "x" * 1300,
                **{f"k{item}": item for item in range(30)},
            },
        }
        for index in range(55)
    ]

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    logs = ticket_json["context"]["recent_client_logs"]
    assert len(logs) == 50
    assert logs[0]["label"] == "event-5"
    assert logs[-1]["label"] == "event-54"
    assert logs[0]["elapsed_ms"] == 5.123
    assert logs[0]["details"]["long"].endswith("...<truncated>")
    assert logs[0]["details"]["__truncated_keys"] == 7


def test_submit_bug_report_redacts_context_diagnostic_strings(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload()
    payload["context"]["recent_client_logs"] = [
        {
            "timestamp": "file:///Users/min/private/log.txt",
            "method": "error",
            "label": "Request failed with status code 500",
            "elapsed_ms": 12.3456,
            "scope": r"\\LUMINA-NAS\private\trace.log",
            "phase": "HTTP 500",
            "details": {
                "posix_path": "failed at /Users/min/private/model.3mf",
                "private_tmp": "open /private/tmp/lumina/model.png",
                "windows_path": r"C:\Users\min\secret\model.3mf",
                "windows_forward_path": "C:/Users/min/secret/model.3mf",
                "unc_path": r"\\LUMINA-NAS\share\secret.3mf",
                "file_url": "file:///Users/min/private/model.3mf",
                "windows_file_url": "file:///C:/Users/min/private/model.3mf",
                "generic_http_error": "Request failed with status code 500",
                "api_path_transport_error": (
                    "Request failed with status code 500 at /api/files/output-model"
                ),
                "business_detail": "Color palette has no hex entries.",
                "api_path": "/api/files/output-model",
            },
        }
    ]
    payload["context"]["action_history"] = [
        {
            "timestamp": 1760000000000,
            "action_type": "api_error",
            "snapshot": {
                "active_tab": "converter",
                "advanced_params": {
                    "relief": {
                        "source": "file:///Users/min/private/source.png",
                        "color_height_map": {"#ffffff": 0.24},
                    },
                },
            },
            "error": {
                "status_code": 500,
                "path": "/api/files/output-model",
                "error_message": "HTTP 404: /api/files/output-model",
                "local_path_error_message": (
                    r"Request failed with status code 500 at C:\Users\min\secret.3mf"
                ),
                "stack": "Traceback at /home/min/lumina/app.py",
            },
        }
    ]
    payload["context"]["advanced_params"] = {
        "relief": {
            "source": "file:///Users/min/private/source.png",
            "color_height_map": {"#ffffff": 0.24},
        }
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    context_text = json.dumps(ticket_json["context"], ensure_ascii=False)
    context_strings = "\n".join(_iter_json_strings(ticket_json["context"]))
    log_details = ticket_json["context"]["recent_client_logs"][0]["details"]
    action_error = ticket_json["context"]["action_history"][0]["error"]
    assert "/Users/min/private" not in context_strings
    assert "/private/tmp/lumina" not in context_strings
    assert "/home/min/lumina" not in context_strings
    assert r"C:\Users\min" not in context_strings
    assert "C:/Users/min" not in context_strings
    assert r"\\LUMINA-NAS" not in context_strings
    assert "file:///Users/min" not in context_strings
    assert "file:///C:/Users/min" not in context_strings
    assert "Request failed with status code 500" not in context_strings
    assert "HTTP 404" not in context_strings
    assert "HTTP 500" not in context_strings
    assert "[redacted_local_path]" in context_text
    assert "The server reported an error while processing this request." in context_text
    assert ticket_json["context"]["action_history"][0]["error"]["status_code"] == 500
    assert "/api/files/output-model" in context_text
    assert log_details["api_path_transport_error"] == (
        "The server reported an error while processing this request. "
        "Context: /api/files/output-model"
    )
    assert action_error["error_message"] == (
        "The server reported an error while processing this request. "
        "Context: /api/files/output-model"
    )
    assert action_error["local_path_error_message"] == (
        "The server reported an error while processing this request."
    )
    assert "Color palette has no hex entries." in context_text
    assert ticket_json["context"]["recent_client_logs"][0]["elapsed_ms"] == 12.346


@pytest.mark.parametrize(
    "patch",
    [
        {"description": ""},
        {"description": "x" * 10001},
        {"user_email": "not-an-email"},
    ],
)
def test_submit_bug_report_rejects_invalid_payloads(
    client: TestClient,
    patch: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = client.post("/api/feedback/bug-report", json=_payload(**patch))

    assert response.status_code == 422
    assert [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_submitted"
    ] == []


def test_submit_bug_report_rejects_oversized_screenshot(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _capture_feedback_logger(caplog, logging.WARNING)
    payload = _payload(screenshot_data_url="data:image/png;base64," + ("a" * 7_000_001))

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 413
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_too_large"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "PayloadTooLarge"


def test_submit_bug_report_rate_limits_repeated_submissions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("LUMINA_FEEDBACK_RATE_LIMIT_MAX", "1")
    monkeypatch.setenv("LUMINA_FEEDBACK_RATE_LIMIT_WINDOW_S", "60")
    _capture_feedback_logger(caplog, logging.WARNING)

    first = client.post("/api/feedback/bug-report", json=_payload(description="first"))
    second = client.post("/api/feedback/bug-report", json=_payload(description="second"))

    assert first.status_code == 200
    assert second.status_code == 429
    assert 1 <= int(second.headers["Retry-After"]) <= 60
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_rate_limited"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "RateLimitExceeded"
    assert warnings[0].max_requests == 1


def test_submit_bug_report_returns_500_when_ticket_dir_creation_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the ticket id generator cannot create its reserved dir the handler 500s.

    工单目录保留失败时，handler 应返回 500 而不是抛原始异常。
    """

    def _raise(*_args: Any, **_kwargs: Any) -> str:
        raise OSError("disk full")

    monkeypatch.setattr("api.routers.feedback.generate_ticket_id", _raise)
    _capture_feedback_logger(caplog, logging.ERROR)

    response = client.post("/api/feedback/bug-report", json=_payload())

    assert response.status_code == 500
    failures = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_dump_failed"
    ]
    assert len(failures) == 1
    assert failures[0].error_type == "OSError"


def test_relay_bug_report_returns_503_when_unconfigured(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post(
        "/api/feedback/bug-report/relay",
        json={"ticket_id": "abc12345", "request_payload": _payload()},
    )

    assert response.status_code == 503
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_relay_unconfigured"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "RelayUnconfigured"


def test_relay_bug_report_rejects_untrusted_origin_before_relay_http(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            raise AssertionError("relay client should not be opened")

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_URL", "https://relay.example.test/feedback")
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    response = client.post(
        "/api/feedback/bug-report/relay",
        json={"ticket_id": "abc12345", "request_payload": _payload()},
        headers=UNTRUSTED_ORIGIN_HEADERS,
    )

    assert response.status_code == 403
    assert "local Lumina Studio app" in response.json()["detail"]


def test_relay_bug_report_allows_untrusted_origin_for_public_gray_api(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    monkeypatch.setenv("LUMINA_ALLOW_PUBLIC_GRAY_API", "1")
    calls: list[dict[str, Any]] = []

    class _Response:
        status_code = 202

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> _Response:
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_URL", "https://relay.example.test/feedback")
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    response = client.post(
        "/api/feedback/bug-report/relay",
        json={"ticket_id": "abc12345", "request_payload": _payload()},
        headers=UNTRUSTED_ORIGIN_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {"forwarded": True}
    assert calls[0]["url"] == "https://relay.example.test/feedback"


def test_relay_bug_report_forwards_to_configured_relay(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import httpx

    calls: list[dict[str, Any]] = []

    class _Response:
        status_code = 202

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> _Response:
            calls.append({
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": self.timeout,
            })
            return _Response()

    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_URL", "https://relay.example.test/feedback")
    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_TOKEN", "secret-token")
    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_TIMEOUT_S", "3")
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    _capture_feedback_logger(caplog, logging.INFO)

    response = client.post(
        "/api/feedback/bug-report/relay",
        json={"ticket_id": "abc12345", "request_payload": _payload(description="Relay me")},
    )

    assert response.status_code == 200
    assert response.json() == {"forwarded": True}
    assert calls == [
        {
            "url": "https://relay.example.test/feedback",
            "json": {
                "ticket_id": "abc12345",
                "request_payload": _payload(description="Relay me"),
            },
            "headers": {
                "Content-Type": "application/json",
                "X-Lumina-Feedback-Ticket": "abc12345",
                "Authorization": "Bearer secret-token",
            },
            "timeout": 3.0,
        }
    ]
    infos = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_relay_done"
    ]
    assert len(infos) == 1
    assert infos[0].relay_status_code == 202


def test_relay_bug_report_sanitizes_description_before_forwarding(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    calls: list[dict[str, Any]] = []

    class _Response:
        status_code = 202

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> _Response:
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_URL", "https://relay.example.test/feedback")
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    response = client.post(
        "/api/feedback/bug-report/relay",
        json={
            "ticket_id": "abc12345",
            "request_payload": _payload(description=DESCRIPTION_RAW_DIAGNOSTICS),
        },
    )

    assert response.status_code == 200
    forwarded_payload = calls[0]["json"]["request_payload"]
    _assert_description_diagnostics_redacted(
        json.dumps(forwarded_payload, ensure_ascii=False)
    )


def test_relay_bug_report_redacts_final_artifact_disk_path(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Relay payloads must not forward local or server disk paths.

    官方转发 payload 不应包含本机或服务器磁盘路径。
    """
    import httpx

    calls: list[dict[str, Any]] = []

    class _Response:
        status_code = 202

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> _Response:
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    private_path = tmp_path / "private-output" / "model.3mf"
    payload = _payload()
    payload["context"]["active_final_artifact_ref"] = {
        "session_id": "session-abcdef",
        "download_url": None,
        "artifact_type": "3mf",
        "disk_path": private_path.as_posix(),
        "source": "converter",
    }

    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_URL", "https://relay.example.test/feedback")
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    response = client.post(
        "/api/feedback/bug-report/relay",
        json={"ticket_id": "abc12345", "request_payload": payload},
    )

    assert response.status_code == 200
    relayed_payload = calls[0]["json"]["request_payload"]
    active_ref = relayed_payload["context"]["active_final_artifact_ref"]
    assert "disk_path" not in active_ref
    assert private_path.as_posix() not in json.dumps(relayed_payload, ensure_ascii=False)


def test_relay_bug_report_returns_502_when_relay_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import httpx

    class _Client:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            _url: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> httpx.Response:
            raise httpx.ConnectError("offline")

    monkeypatch.setenv("LUMINA_FEEDBACK_RELAY_URL", "https://relay.example.test/feedback")
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    _capture_feedback_logger(caplog, logging.ERROR)

    response = client.post(
        "/api/feedback/bug-report/relay",
        json={"ticket_id": "abc12345", "request_payload": _payload()},
    )

    assert response.status_code == 502
    failures = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_relay_failed"
    ]
    assert len(failures) == 1
    assert failures[0].dependency == "httpx"

# ---------------------------------------------------------------------------
# Screenshot data URL strict validation tests
# ---------------------------------------------------------------------------


def test_submit_bug_report_accepts_valid_png_screenshot(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """A valid PNG data URL is accepted and saved as screenshot.png."""
    import base64

    valid_png_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode()
    payload = _payload(screenshot_data_url=f"data:image/png;base64,{valid_png_b64}")

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["attachments"]["screenshot"]["status"] == "attached"
    assert ticket_json["attachments"]["screenshot"]["filename"] == "screenshot.png"


def test_submit_bug_report_marks_screenshot_failed_when_write_fails(
    client: TestClient,
    feedback_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed screenshot write is explicit in ``ticket.json``.

    截图写入失败时，``ticket.json`` 必须显式标记失败，不能伪装成不适用。
    """
    import base64

    original_write_bytes = Path.write_bytes

    def _fail_screenshot_write(self: Path, data: bytes) -> int:
        if self.name.startswith("screenshot"):
            raise OSError("disk full while writing screenshot")
        return original_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", _fail_screenshot_write)
    _capture_feedback_logger(caplog, logging.WARNING)

    valid_png_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode()
    payload = _payload(screenshot_data_url=f"data:image/png;base64,{valid_png_b64}")

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    screenshot = ticket_json["attachments"]["screenshot"]
    assert screenshot == {
        "status": "failed",
        "filename": "screenshot.png",
        "size_bytes": None,
        "error_type": "OSError",
        "error_message": "Screenshot could not be saved.",
    }
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_attachment_lookup_failed"
    ]
    assert warnings
    assert warnings[0].attachment_kind == "screenshot"
    assert warnings[0].error_type == "OSError"


def test_submit_bug_report_rejects_non_image_mime_screenshot(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """data:text/plain;base64,... returns 400."""
    import base64

    b64 = base64.b64encode(b"hello world").decode()
    payload = _payload(screenshot_data_url=f"data:text/plain;base64,{b64}")
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 400
    assert "Invalid screenshot data URL" in response.json()["detail"]
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_invalid"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "UnsupportedMimeType"


def test_submit_bug_report_rejects_missing_base64_marker(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """data:image/png,not-base64 (no ;base64) returns 400."""
    payload = _payload(screenshot_data_url="data:image/png,not-base64-content")
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 400
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_invalid"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "InvalidDataUrlFormat"


def test_submit_bug_report_rejects_invalid_base64_payload(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """data:image/png;base64,%%% returns 400."""
    payload = _payload(screenshot_data_url="data:image/png;base64,%%%")
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 400
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_invalid"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "InvalidBase64"


def test_submit_bug_report_rejects_svg_screenshot(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """data:image/svg+xml;base64,... returns 400 (SVG not in allowed list)."""
    import base64

    b64 = base64.b64encode(b"<svg></svg>").decode()
    payload = _payload(screenshot_data_url=f"data:image/svg+xml;base64,{b64}")
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 400
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_invalid"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "UnsupportedMimeType"
    assert warnings[0].mime_type == "image/svg+xml"


# ---------------------------------------------------------------------------
# Task 6.7: advanced_params schema / sanitizer integration tests
# ---------------------------------------------------------------------------


def _full_advanced_params() -> dict[str, Any]:
    """Return a fully-populated grouped ``advanced_params`` payload.

    构造覆盖全部 11 个分组的 ``advanced_params`` 测试载荷。
    """
    return {
        "dimensions": {
            "target_width_mm": 120,
            "target_height_mm": 80,
            "spacer_thick": 0.06,
            "base_spacer_thick": 0.12,
        },
        "generation": {
            "structure_mode": "standard",
            "modeling_mode": "flat",
            "color_layers": 4,
            "layer_height_mm": 0.08,
            "model_enable": False,
            "model_only": False,
            "model_threshold": None,
            "model_margin": None,
            "quantize_colors": 8,
            "quantize_colors_unlocked": False,
            "enable_cleanup": True,
            "hue_enable": True,
            "chroma_gate": 0.5,
            "use_lut_constrained": False,
            "auto_dynamic_range": True,
            "separate_backing": False,
        },
        "relief": {
            "enable_relief": True,
            "color_height_map": {"#ff0000": 0.1, "#00ff00": 0.2},
            "heightmap_max_height": 0.6,
            "autoHeightMode": "linear",
            "heightmapFile": None,
            "hasHeightmapThumbnail": False,
        },
        "outline": {"enable_outline": True, "outline_width": 0.2},
        "cloisonne": {
            "enable_cloisonne": False,
            "wire_width_mm": None,
            "wire_height_mm": None,
        },
        "coating": {"enable_coating": False, "coating_height_mm": None},
        "loop": {
            "add_loop": False,
            "loop_width": None,
            "loop_length": None,
            "loop_hole": None,
            "loop_angle": None,
            "loop_offset_x": None,
            "loop_offset_y": None,
            "loop_position_preset": None,
        },
        "fridge_magnet": {
            "enable_fridge_magnet": False,
            "selectedFridgeMagnetId": None,
            "fridge_magnets": None,
        },
        "puzzle": {
            "puzzleEnabled": False,
            "puzzleStyle": None,
            "puzzleSizingMode": None,
            "pieceWidthMm": None,
            "pieceHeightMm": None,
            "puzzleRows": None,
            "puzzleCols": None,
            "targetPieceCount": None,
            "connectorStyle": None,
            "labelsEnabled": None,
            "engraveBackLabels": None,
            "irregularityStrength": None,
            "minNeckWidthMm": None,
        },
        "large_format": {
            "largeFormatEnabled": False,
            "tileWidthMm": None,
            "tileHeightMm": None,
        },
        "color_replacement": {"replacement_regions": None},
    }


def test_submit_bug_report_accepts_grouped_advanced_params(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """Pydantic accepts ``advanced_params`` as a grouped 11-key dict and the
    router persists it into ``ticket.json``.

    Pydantic 接收包含全部 11 个分组的 ``advanced_params``，路由把它写入
    ``ticket.json``。
    """
    payload = _payload()
    payload["context"]["advanced_params"] = _full_advanced_params()

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    advanced = ticket_json["context"]["advanced_params"]
    assert isinstance(advanced, dict)
    # All 11 group keys are preserved end-to-end (size is far below 16 KB).
    expected_groups = {
        "dimensions",
        "generation",
        "relief",
        "outline",
        "cloisonne",
        "coating",
        "loop",
        "fridge_magnet",
        "puzzle",
        "large_format",
        "color_replacement",
    }
    assert expected_groups.issubset(advanced.keys())
    assert advanced["dimensions"]["target_width_mm"] == 120
    assert advanced["relief"]["color_height_map"] == {
        "#ff0000": 0.1,
        "#00ff00": 0.2,
    }


def test_submit_bug_report_accepts_null_advanced_params(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """``advanced_params: None`` round-trips untouched.

    显式传 ``None`` 时原样写回 ``ticket.json``。
    """
    payload = _payload()
    payload["context"]["advanced_params"] = None

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["context"]["advanced_params"] is None


def test_submit_bug_report_accepts_missing_advanced_params(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """Old clients that omit the field still succeed; default is ``None``.

    老客户端不传 ``advanced_params`` 时仍然成功，默认值为 ``None``。
    """
    payload = _payload()
    payload["context"].pop("advanced_params", None)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["context"]["advanced_params"] is None


@pytest.mark.parametrize(
    "bad_value",
    [
        [],
        ["not", "a", "dict"],
        "string-advanced-params",
        123,
    ],
    ids=["empty-list", "list", "string", "number"],
)
def test_submit_bug_report_rejects_non_dict_advanced_params(
    client: TestClient,
    bad_value: Any,
) -> None:
    """Non-dict ``advanced_params`` values are rejected at validation time.

    ``advanced_params`` 不是 dict/None 时，Pydantic 返回 422。
    """
    payload = _payload()
    payload["context"]["advanced_params"] = bad_value

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 422


def test_submit_bug_report_falls_back_when_sanitizer_raises(
    client: TestClient,
    feedback_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A crashing sanitizer is caught; request succeeds, advanced_params is ``None``.

    sanitizer 抛异常时请求仍然成功，``ticket.json`` 里的
    ``context.advanced_params`` 被降级为 ``None``。
    """

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("sanitizer exploded")

    monkeypatch.setattr(
        "api.routers.feedback._sanitize_advanced_params", _raise
    )
    _capture_feedback_logger(caplog, logging.WARNING)

    payload = _payload()
    payload["context"]["advanced_params"] = _full_advanced_params()

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["context"]["advanced_params"] is None

    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_advanced_params_failed"
    ]
    assert warnings, "Expected a feedback_advanced_params_failed WARNING"
    assert warnings[0].error_type == "RuntimeError"


def test_submit_bug_report_size_overflow_emits_trimmed_shape(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """When the sanitized ``advanced_params`` exceeds 16 KB, ticket.json stores
    exactly ``{"_size_trimmed": True, "_original_byte_length": N}`` — never a
    third shape.

    sanitized ``advanced_params`` 超过 16 KB 上限时，``ticket.json`` 里
    的 advanced_params 固定为 ``{"_size_trimmed": True,
    "_original_byte_length": N}``，不会出现第三种形态。
    """
    # 15 × 1200-char strings sit under the 1200-char per-string cap but
    # together serialize to ~18 KB, guaranteed to cross the 16 KB total cap.
    # 每个字符串恰好不触发 _truncate_feedback_text，但总体积会超过 16 KB。
    payload_advanced: dict[str, Any] = _full_advanced_params()
    payload_advanced["generation"] = {
        f"field_{i:02d}": "x" * 1200 for i in range(15)
    }

    payload = _payload()
    payload["context"]["advanced_params"] = payload_advanced

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    advanced = ticket_json["context"]["advanced_params"]

    assert isinstance(advanced, dict)
    # The shape is exactly two keys — no third variant.
    assert set(advanced.keys()) == {"_size_trimmed", "_original_byte_length"}
    assert advanced["_size_trimmed"] is True
    assert isinstance(advanced["_original_byte_length"], int)
    assert advanced["_original_byte_length"] > 16_384


def test_submit_bug_report_preserves_action_history_advanced_params(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """``action_history`` snapshots keep their full ``advanced_params`` (e.g.
    a 64-key ``relief.color_height_map``) through the generic + dedicated
    sanitization pipeline.

    ``action_history`` 中的 snapshot 经过通用 + 专用 sanitizer 后，嵌套的
    ``advanced_params``（例如 64 键的 ``relief.color_height_map``）被完整
    保留。
    """
    snapshot_advanced = _full_advanced_params()
    snapshot_advanced["relief"] = {
        "enable_relief": True,
        "color_height_map": {f"#{i:06x}": float(i) * 0.01 for i in range(64)},
        "heightmap_max_height": 0.5,
        "autoHeightMode": "linear",
        "heightmapFile": None,
        "hasHeightmapThumbnail": False,
    }

    payload = _payload()
    payload["context"]["action_history"] = [
        {
            "timestamp": 1747000000000,
            "action_type": "advanced_param_change",
            "changed_fields": {
                "enable_relief": {"from": False, "to": True}
            },
            "snapshot": {
                "active_tab": "converter",
                "source_version": "legacy",
                "advanced_params": snapshot_advanced,
            },
        }
    ]

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    history = ticket_json["context"]["action_history"]
    assert len(history) == 1

    entry_snapshot = history[0]["snapshot"]
    assert isinstance(entry_snapshot, dict)
    assert "advanced_params" in entry_snapshot
    advanced = entry_snapshot["advanced_params"]
    assert isinstance(advanced, dict)
    color_map = advanced["relief"]["color_height_map"]
    assert isinstance(color_map, dict)
    # All 64 entries survive — the generic sanitizer would have cut to 24.
    assert len(color_map) == 64
    assert "__truncated_keys" not in color_map


def test_assembler_entry_points_remain_untouched() -> None:
    """Non-regression: ``collect_sync_attachments`` and ``finalize_ticket_async``
    are imported into the router with their original signatures — nothing
    wraps them at import time.

    非回归校验：``collect_sync_attachments`` 和 ``finalize_ticket_async``
    被路由原样引用，没有被装饰 / 重命名 / 改签名。
    """
    import inspect

    import api.feedback_assembler as feedback_assembler
    import api.routers.feedback as feedback_router

    # Same function object imported in the router as exported by the module.
    assert (
        feedback_router.collect_sync_attachments
        is feedback_assembler.collect_sync_attachments
    )
    assert (
        feedback_router.finalize_ticket_async
        is feedback_assembler.finalize_ticket_async
    )

    sync_params = list(
        inspect.signature(feedback_assembler.collect_sync_attachments).parameters
    )
    assert sync_params == [
        "ticket_dir",
        "payload",
        "file_registry",
        "now",
        "session_store",
    ]

    async_params = list(
        inspect.signature(feedback_assembler.finalize_ticket_async).parameters
    )
    assert async_params == ["ticket_dir", "file_registry", "session_store"]
    assert inspect.iscoroutinefunction(feedback_assembler.finalize_ticket_async)
