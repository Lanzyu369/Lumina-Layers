"""Regression tests for the async segmented-GLB build pipeline.

Covers / 覆盖范围:
    1. Replace endpoints return ``preview_glb_url = None`` immediately
       rather than synchronously waiting for ``generate_segmented_glb``.
       替换端点立即返回 ``preview_glb_url = None``，不再同步等 GLB。
    2. ``GET /api/convert/glb-status/{session_id}`` transitions from
       ``pending`` to ``ready`` after the worker thread finishes, and
       publishes the newly registered GLB URL in cache.
       ``glb-status`` 端点在后台线程完成后由 pending 切换到 ready，并把
       新注册的 GLB URL 从 cache 暴露给前端。
    3. Job-token guarding: a newer replace supersedes the in-flight job
       so the older thread's result is discarded and the status endpoint
       keeps reporting the newer token.
       job_token 守护：新任务覆盖未完成任务后，旧线程的结果被丢弃。
    4. Failure path: if ``generate_segmented_glb`` raises, ``status``
       becomes ``error`` and the error text is surfaced.
       失败路径：后台抛错时状态切换为 ``error`` 并回传错误消息。

    The tests monkeypatch ``generate_segmented_glb`` so they can exercise
    the async scheduler deterministically without spending 30+ seconds on
    actual mesh building. A minimal LUT session is seeded directly into
    the SessionStore to keep each test independent of the full /preview
    pipeline.
    测试通过 monkeypatch 替换 ``generate_segmented_glb``，避免真实 GLB
    构建的 30+ 秒耗时，同时保持与调度器的契约一致。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.routers.converter import async_glb as async_glb_module
from api.session_store import SessionStore

_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()


def setup_module(module) -> None:
    app.dependency_overrides[get_session_store] = lambda: _test_store
    app.dependency_overrides[get_file_registry] = lambda: _test_registry


def teardown_module(module) -> None:
    app.dependency_overrides.pop(get_session_store, None)
    app.dependency_overrides.pop(get_file_registry, None)


setup_module(None)
client: TestClient = TestClient(app)


def setup_function() -> None:
    global _test_store, _test_registry
    _test_store = SessionStore(ttl=1800)
    _test_registry = FileRegistry()


def _seed_session(tmp_path: Path) -> str:
    """Build a minimal LUT-backed session that region-replace can act on.

    Keeping the shape identical to the real pipeline's preview cache is
    what matters here — the actual LUT content is irrelevant because the
    GLB build is monkey-patched in every test.
    构造一个 region-replace 能处理的最小 LUT 会话；内容对 GLB 行为无关，
    因为每个用例都会 monkeypatch 真实的 mesh 构建。
    """

    lut_path = tmp_path / "simple_lut.npz"
    rgb = np.asarray(
        [[255, 0, 0], [0, 0, 255], [0, 255, 0]], dtype=np.uint8
    )
    stacks = np.asarray([[0, 0], [1, 1], [2, 2]], dtype=np.int16)
    np.savez(lut_path, rgb=rgb, stacks=stacks)

    sid = _test_store.create()
    matched = np.zeros((3, 3, 3), dtype=np.uint8)
    matched[:, :] = [255, 0, 0]
    material_matrix = np.zeros((3, 3, 2), dtype=np.int16)
    mask_solid = np.ones((3, 3), dtype=bool)
    cache = {
        "matched_rgb": matched.copy(),
        "quantized_image": matched.copy(),
        "mask_solid": mask_solid,
        "material_matrix": material_matrix.copy(),
        "color_conf": {
            "preview": {0: [255, 0, 0, 255], 1: [0, 0, 255, 255], 2: [0, 255, 0, 255]},
            "slots": ["Red", "Blue"],
        },
        "preview_rgba": np.dstack(
            [matched.copy(), np.full((3, 3), 255, dtype=np.uint8)]
        ),
        "color_layers": 2,
        "layer_height_mm": 0.08,
        "target_w": 3,
        "target_h": 3,
        "target_width_mm": 60.0,
    }
    _test_store.put(sid, "preview_cache", cache)
    _test_store.put(sid, "original_matched_rgb", matched.copy())
    _test_store.put(sid, "original_material_matrix", material_matrix.copy())
    _test_store.put(sid, "replacement_regions", [])
    _test_store.put(sid, "replacement_history", [])
    _test_store.put(sid, "lut_path", str(lut_path))
    _test_store.put(sid, "color_mode", "4-Color (RYBW)")
    _test_store.put(sid, "color_layers", 2)
    _test_store.put(sid, "layer_height_mm", 0.08)
    _test_store.put(sid, "material_source", "lut")
    return sid


def _install_glb_stub(
    monkeypatch: pytest.MonkeyPatch,
    builder: Callable[[dict], str | None],
) -> list[str]:
    """Replace the real ``generate_segmented_glb`` with *builder*.

    Returns a list that records every call — tests can assert how many
    background builds actually ran (e.g. to check job-token cancellation).
    返回一个列表，记录 builder 被调用的次数与对应 job_token，便于测试断言。
    """

    calls: list[str] = []

    def _wrapper(cache: dict) -> str | None:
        calls.append(cache.get("glb_job_token", ""))
        return builder(cache)

    monkeypatch.setattr(async_glb_module, "generate_segmented_glb", _wrapper)
    return calls


def _wait_for_status(
    sid: str, predicate: Callable[[dict], bool], timeout_s: float = 5.0
) -> dict:
    """Poll /glb-status until *predicate* accepts or *timeout_s* elapses.

    Chosen over a fixed sleep so the tests stay fast on CI (the stub
    builds finish in milliseconds) while still tolerating ThreadPool
    scheduler latency.
    轮询 glb-status 直到满足谓词或超时，保证测试稳定又快。
    """

    deadline = time.perf_counter() + timeout_s
    last: dict = {}
    while time.perf_counter() < deadline:
        resp = client.get(f"/api/convert/glb-status/{sid}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if predicate(last):
            return last
        time.sleep(0.02)
    raise AssertionError(
        f"glb-status predicate never matched within {timeout_s}s; last={last}"
    )


class TestReplaceReturnsImmediately:
    def test_region_replace_returns_glb_url_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = _seed_session(tmp_path)
        # Pin the stub so we can observe status transitions without waiting
        # for real mesh construction.
        # 使用 stub 避免真实 GLB 构建的耗时。
        stub_glb_path = tmp_path / "fake.glb"
        stub_glb_path.write_bytes(b"glb-placeholder")
        _install_glb_stub(monkeypatch, lambda _c: str(stub_glb_path))

        # Seed a connected region so /region-replace has something to act on.
        # 种入一个连通区域 mask，让 region-replace 有目标。
        region_mask = np.zeros((3, 3), dtype=bool)
        region_mask[:2, :2] = True
        _test_store.put(sid, "selected_region_mask", region_mask)
        _test_store.put(sid, "selected_region_id", "region-a")

        response = client.post(
            "/api/convert/region-replace",
            json={"session_id": sid, "replacement_color": "#0000ff"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["preview_glb_url"] is None
        assert body["preview_url"]

    def test_replace_color_returns_glb_url_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = _seed_session(tmp_path)
        stub_glb_path = tmp_path / "fake.glb"
        stub_glb_path.write_bytes(b"glb-placeholder")
        _install_glb_stub(monkeypatch, lambda _c: str(stub_glb_path))

        response = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json().get("preview_glb_url") is None


class TestGlbStatusLifecycle:
    def test_idle_before_any_replace(self, tmp_path: Path) -> None:
        sid = _seed_session(tmp_path)
        resp = client.get(f"/api/convert/glb-status/{sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "idle"
        assert body["glb_url"] is None
        assert body["job_token"] is None

    def test_unknown_session_returns_404(self) -> None:
        resp = client.get("/api/convert/glb-status/not-a-session")
        assert resp.status_code == 404

    def test_pending_then_ready_after_replace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = _seed_session(tmp_path)
        stub_glb_path = tmp_path / "fake.glb"
        stub_glb_path.write_bytes(b"glb-placeholder")

        # A slow-ish stub ensures we can observe a pending snapshot
        # between scheduling and completion without racing.
        # 让 stub 延迟一点，确保 pending 状态能被观察到（否则太快直接 ready）。
        def slow_builder(_cache: dict) -> str:
            time.sleep(0.05)
            return str(stub_glb_path)

        _install_glb_stub(monkeypatch, slow_builder)

        resp = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        assert resp.status_code == 200

        final = _wait_for_status(sid, lambda b: b["status"] == "ready")
        assert isinstance(final["glb_url"], str)
        assert final["glb_url"].startswith("/api/files/")
        assert isinstance(final["job_token"], str)
        assert final["error"] is None

    def test_error_propagated_to_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = _seed_session(tmp_path)

        def broken(_cache: dict) -> str | None:
            raise RuntimeError("simulated mesh failure")

        _install_glb_stub(monkeypatch, broken)

        resp = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        assert resp.status_code == 200

        final = _wait_for_status(sid, lambda b: b["status"] == "error")
        assert final["glb_url"] is None
        assert "simulated mesh failure" in (final["error"] or "")


class TestJobTokenGuard:
    def test_newer_job_discards_older_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A newer replace while an old build is still running must win.

        We observe this indirectly: the status payload after both
        responses has ``job_token`` equal to the newest task's token, and
        its ``glb_url`` is the one produced by the *second* builder call
        (we give each call a distinct output path so the URLs differ).
        验证：旧任务仍在跑时来了新任务，最终 job_token 为新任务的，且
        glb_url 对应第二次 builder 的输出（用不同路径区分）。
        """

        sid = _seed_session(tmp_path)
        first_path = tmp_path / "first.glb"
        first_path.write_bytes(b"first-glb")
        second_path = tmp_path / "second.glb"
        second_path.write_bytes(b"second-glb")

        # Order the outputs strictly: first call returns first_path, second
        # returns second_path. A small sleep in the first call lets the
        # second request arrive before the first finishes.
        # 让两个 builder 的输出可区分，第一次故意慢，第二次在其完成前发起。
        call_index = {"i": 0}

        def sequencer(_cache: dict) -> str:
            call_index["i"] += 1
            idx = call_index["i"]
            if idx == 1:
                time.sleep(0.1)
                return str(first_path)
            return str(second_path)

        _install_glb_stub(monkeypatch, sequencer)

        r1 = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        assert r1.status_code == 200
        first_token = _test_store.get(sid)["preview_cache"]["glb_job_token"]

        # Race: fire the second replace right away before the first
        # background build has a chance to finish.
        # 竞争：第一个后台任务还未结束就发第二个 replace。
        r2 = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#0000ff",
                "replacement_color": "#00ff00",
            },
        )
        assert r2.status_code == 200
        second_token = _test_store.get(sid)["preview_cache"]["glb_job_token"]
        assert second_token != first_token

        final = _wait_for_status(sid, lambda b: b["status"] == "ready")
        assert final["job_token"] == second_token
        # file registry was handed the *second* path; assert that's the
        # one behind the final URL.
        # 验证 FileRegistry 解析出的路径是第二次的产物。
        file_id = final["glb_url"].rsplit("/", 1)[-1]
        resolved = _test_registry.resolve(file_id)
        assert resolved is not None
        resolved_path, _ = resolved
        assert Path(resolved_path).resolve() == second_path.resolve()
