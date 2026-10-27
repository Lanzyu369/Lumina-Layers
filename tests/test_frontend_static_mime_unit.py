"""Built frontend MIME contracts under host overrides. / 系统类型覆盖下的前端资源契约。"""

import mimetypes
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.staticfiles import StaticFiles

from api.app import _configure_frontend_dist


@pytest.fixture
def static_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    for folder in (dist, dist / "assets"):
        for name, content in {
            "entry.js": "export const value = 1;",
            "worker.mjs": "export const value = 2;",
            "theme.css": "body { color: red; }",
            "image.png": "image-fixture",
        }.items():
            (folder / name).write_text(content, encoding="utf-8")
    (tmp_path / "outside.js").write_text("private", encoding="utf-8")
    mimetypes.init()
    for suffix in (".js", ".mjs", ".css", ".html"):
        monkeypatch.setitem(mimetypes.types_map, suffix, "text/plain")
    monkeypatch.setenv("LUMINA_SERVE_FRONTEND_DIST", "1")
    monkeypatch.setenv("LUMINA_FRONTEND_DIST_DIR", str(dist))
    app = FastAPI()
    _configure_frontend_dist(app)
    app.state.legacy_assets = StaticFiles(directory=str(dist / "assets"))
    return TestClient(app)


@pytest.mark.parametrize("prefix", ["/", "/assets/"])
@pytest.mark.parametrize("name,expected", [
    ("entry.js", "text/javascript"), ("worker.mjs", "text/javascript"),
    ("theme.css", "text/css"),
])
def test_frontend_types_ignore_host_mapping(
    static_client: TestClient, prefix: str, name: str, expected: str,
) -> None:
    response = static_client.get(prefix + name)
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == expected
    assert mimetypes.guess_type(name)[0] == "text/plain", "Do not change global MIME state"


@pytest.mark.parametrize("url", ["/", "/settings", "/index.html"])
def test_spa_html_type_is_explicit(static_client: TestClient, url: str) -> None:
    response = static_client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("url", ["/", "/settings", "/index.html"])
def test_spa_entry_does_not_persist_across_runtime_updates(
    static_client: TestClient, tmp_path: Path, url: str,
) -> None:
    previous = static_client.get(url)
    assert previous.headers.get("cache-control") == "no-store"

    current_html = '<script type="module" src="/assets/current.js"></script>'
    (tmp_path / "dist" / "index.html").write_text(current_html, encoding="utf-8")
    upgraded = static_client.get(url, headers={
        "If-None-Match": previous.headers["etag"],
        "If-Modified-Since": previous.headers["last-modified"],
    })
    assert upgraded.status_code == 200
    assert upgraded.text == current_html
    assert upgraded.headers.get("cache-control") == "no-store"


def test_assets_preserve_bytes_cache_head_and_non_script_types(
    static_client: TestClient,
) -> None:
    response = static_client.get("/assets/entry.js")
    assert response.content == b"export const value = 1;"
    cached = static_client.get("/assets/entry.js", headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304
    assert cached.content == b""
    head = static_client.head("/assets/entry.js")
    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-type"].startswith("text/javascript")
    image = static_client.get("/assets/image.png")
    assert image.headers["content-type"].startswith("image/png")
    assert static_client.get("/assets/missing.js").status_code == 404
    assert static_client.get("/assets/%2e%2e/%2e%2e/outside.js").status_code == 404
    assert static_client.get("/api/missing").status_code == 404


def test_old_wrong_type_cache_is_replaced_not_revalidated(
    static_client: TestClient,
) -> None:
    legacy = TestClient(static_client.app.state.legacy_assets)
    old = legacy.get("/entry.js")
    assert old.headers["content-type"].startswith("text/plain")
    upgraded = static_client.get("/assets/entry.js", headers={
        "If-None-Match": old.headers["etag"],
        "If-Modified-Since": old.headers["last-modified"],
    })
    assert upgraded.status_code == 200
    assert upgraded.headers["content-type"].startswith("text/javascript")
    assert upgraded.headers["etag"] != old.headers["etag"]
    assert upgraded.content == old.content
    assert static_client.get("/assets/entry.js", headers={
        "If-Modified-Since": old.headers["last-modified"],
    }).status_code == 200


def test_known_asset_range_preserves_correct_type(static_client: TestClient) -> None:
    response = static_client.get("/assets/entry.js", headers={"Range": "bytes=0-5"})
    assert response.status_code == 206
    assert response.content == b"export"
    assert response.headers["content-type"].startswith("text/javascript")
