"""API server bind configuration tests.

API 服务监听配置测试。
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_backend_prepares_multiprocessing_before_heavy_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api_server

    calls: list[str] = []
    monkeypatch.setattr(
        api_server.multiprocessing,
        "freeze_support",
        lambda: calls.append("freeze_support"),
    )

    api_server._prepare_frozen_multiprocessing()

    assert calls == ["freeze_support"]
    source = (ROOT / "api_server.py").read_text(encoding="utf-8")
    run_index = source.index("def _run_server")
    prepare_index = source.index("_prepare_frozen_multiprocessing()", run_index)
    stdio_index = source.index("_prepare_windowed_stdio()", prepare_index)
    uvicorn_index = source.index("import uvicorn", prepare_index)
    app_index = source.index("from api.app import app", prepare_index)
    assert prepare_index < stdio_index < uvicorn_index
    assert prepare_index < stdio_index < app_index


def test_windowed_backend_replaces_only_missing_standard_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api_server

    preserved_stdout = io.StringIO()
    replacement_stderr = io.StringIO()
    monkeypatch.setattr(api_server.sys, "stdout", preserved_stdout)
    monkeypatch.setattr(api_server.sys, "stderr", None)
    monkeypatch.setattr(
        api_server,
        "_open_null_stream",
        lambda: replacement_stderr,
    )

    api_server._prepare_windowed_stdio()

    assert api_server.sys.stdout is preserved_stdout
    assert api_server.sys.stderr is replacement_stderr


def test_startup_diagnostics_capture_watchdog_and_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api_server

    events: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        api_server.faulthandler,
        "dump_traceback_later",
        lambda timeout, *, repeat, file: events.append(
            ("start", timeout, repeat, file.closed)
        ),
    )
    monkeypatch.setattr(
        api_server.faulthandler,
        "cancel_dump_traceback_later",
        lambda: events.append(("cancel",)),
    )
    diagnostic_path = tmp_path / "startup-traceback.txt"

    with pytest.raises(RuntimeError, match="startup boom"):
        with api_server._startup_diagnostics(
            {"LUMINA_STARTUP_DIAGNOSTIC_PATH": str(diagnostic_path)}
        ):
            raise RuntimeError("startup boom")

    assert events == [("start", 30, True, False), ("cancel",)]
    diagnostic = diagnostic_path.read_text(encoding="utf-8")
    assert "RuntimeError: startup boom" in diagnostic


def test_api_server_defaults_preserve_existing_development_bind() -> None:
    from api_server import _resolve_server_bind

    assert _resolve_server_bind({}) == ("0.0.0.0", 8000)


def test_launcher_can_bind_backend_to_an_isolated_loopback_port() -> None:
    from api_server import _resolve_server_bind

    assert _resolve_server_bind(
        {
            "LUMINA_API_HOST": "127.0.0.1",
            "LUMINA_API_PORT": "18000",
        }
    ) == ("127.0.0.1", 18000)


@pytest.mark.parametrize(
    "port",
    ["", "0", "80", "65536", "8000x", "8.0", " 8000 "],
)
def test_api_server_rejects_invalid_or_privileged_port(port: str) -> None:
    from api_server import _resolve_server_bind

    with pytest.raises(ValueError, match="LUMINA_API_PORT"):
        _resolve_server_bind({"LUMINA_API_PORT": port})


def test_api_server_rejects_non_loopback_launcher_override() -> None:
    from api_server import _resolve_server_bind

    with pytest.raises(ValueError, match="LUMINA_API_HOST"):
        _resolve_server_bind(
            {
                "LUMINA_API_HOST": "192.168.1.5",
                "LUMINA_API_PORT": "18000",
            }
        )
