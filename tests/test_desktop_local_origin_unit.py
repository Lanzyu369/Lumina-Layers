"""Regression coverage for desktop fallback-port origin guards."""

import pytest
from starlette.requests import Request

from api.routers.single_stage import _is_trusted_material_library_request
from api.routers.system import _is_trusted_clear_cache_request


@pytest.mark.parametrize(
    ("guard", "env_name"),
    [
        (_is_trusted_material_library_request, "LUMINA_MATERIAL_LIBRARY_ALLOWED_LOCAL_PORTS"),
        (_is_trusted_clear_cache_request, "LUMINA_CLEAR_CACHE_ALLOWED_LOCAL_PORTS"),
    ],
)
def test_selected_desktop_port_is_trusted_without_allowing_other_ports(monkeypatch, guard, env_name):
    monkeypatch.setenv(env_name, "9100,9101,8001")
    for port, expected in [(8001, True), (9100, True), (9101, True), (8002, False)]:
        request = Request({
            "type": "http",
            "headers": [
                (b"host", b"127.0.0.1:8001"),
                (b"origin", f"http://127.0.0.1:{port}".encode("ascii")),
            ],
        })
        assert guard(request)[0] is expected
