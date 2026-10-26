"""Preview publication must leave unrelated API requests responsive."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import io
from pathlib import Path
import pickle
import threading
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import numpy as np
from PIL import Image
import pytest

from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import externalize_preview_cache_to_artifacts
from api.routers import health
from api.routers.converter import async_glb, preview
from api.session_store import SessionStore


class _CompletedPreviewPool:
    """Return real persisted worker artifacts without running the CPU pipeline."""

    is_alive = True
    max_workers = 1

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    async def submit_timed(self, *args: object) -> tuple[dict[str, Any], dict]:
        return self.result, {}


def _write_worker_result(tmp_path: Path) -> dict[str, Any]:
    rgb = np.full((8, 12, 3), [255, 0, 0], dtype=np.uint8)
    rgba = np.concatenate(
        (rgb, np.full((8, 12, 1), 255, dtype=np.uint8)), axis=2,
    )
    cache = {
        "target_w": 12,
        "target_h": 8,
        "target_width_mm": 1.2,
        "matched_rgb": rgb,
        "mask_solid": np.ones((8, 12), dtype=bool),
        "quantized_image": rgb.copy(),
        "preview_rgba": rgba,
        "material_matrix": np.zeros((8, 12, 5), dtype=np.int8),
        "color_palette": [
            {"hex": "#ff0000", "color": [255, 0, 0], "count": 96, "percentage": 100.0},
        ],
    }
    ref, _ = externalize_preview_cache_to_artifacts(cache, root_dir=tmp_path)
    png_path = tmp_path / "worker-preview.png"
    raw_path = tmp_path / "worker-raw.png"
    cache_path = tmp_path / "worker-cache.pkl"
    Image.fromarray(rgb).save(png_path)
    Image.fromarray(rgba).save(raw_path)
    cache_path.write_bytes(pickle.dumps(ref["metadata"]))
    return {
        "status_msg": "Preview OK",
        "preview_png_path": str(png_path),
        "raw_preview_png_path": str(raw_path),
        "cache_data_path": str(cache_path),
        "cache_artifact_ref": ref,
        "vector_parse_clip_cache_path": None,
        "response_palette": None,
        "gradient_groups": None,
        "gradient_region_id_map_path": None,
    }


def _make_app(
    store: SessionStore,
    registry: FileRegistry,
    result: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    temp_dir = str(Path(result["preview_png_path"]).parent)
    monkeypatch.setattr("config.TEMP_DIR", temp_dir)
    monkeypatch.setattr("api.file_registry.TEMP_DIR", temp_dir)
    monkeypatch.setattr("api.preview_cache_artifacts.TEMP_DIR", temp_dir)
    monkeypatch.setattr(preview, "TEMP_DIR", temp_dir)
    pool = _CompletedPreviewPool(result)
    test_app = FastAPI()
    test_app.include_router(preview.router, prefix="/api/convert")
    test_app.include_router(health.router)
    test_app.dependency_overrides.update({
        get_session_store: lambda: store,
        get_file_registry: lambda: registry,
        get_worker_pool: lambda: pool,
    })
    monkeypatch.setattr(
        preview.LUTManager,
        "resolve_source_selection",
        lambda **kwargs: ("fixture.npy", "fixture"),
    )
    # Mesh generation is covered separately; keep the publication real.
    monkeypatch.setattr(preview, "generate_segmented_glb", lambda *a, **kw: None)
    return test_app


@pytest.mark.parametrize("blocked_stage", ["cache_read", "png_publish"])
def test_health_responds_before_preview_publication_is_released(
    blocked_stage: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file barrier proves health completes while publication is still busy."""
    result = _write_worker_result(tmp_path)
    store = SessionStore()
    registry = FileRegistry()
    test_app = _make_app(store, registry, result, monkeypatch)
    entered = threading.Event()
    release = threading.Event()

    def block_until_released() -> None:
        entered.set()
        if not release.wait(timeout=10):
            raise RuntimeError("Test did not release preview publication")

    if blocked_stage == "cache_read":
        hydrate = preview.hydrate_preview_cache

        def blocked_hydrate(*args: Any, **kwargs: Any) -> dict:
            block_until_released()
            return hydrate(*args, **kwargs)

        monkeypatch.setattr(preview, "hydrate_preview_cache", blocked_hydrate)
    else:
        register_bytes = registry.register_bytes

        def blocked_register(*args: Any, **kwargs: Any) -> str:
            block_until_released()
            return register_bytes(*args, **kwargs)

        monkeypatch.setattr(registry, "register_bytes", blocked_register)

    upload = io.BytesIO(Path(result["preview_png_path"]).read_bytes())
    with TestClient(test_app) as client, ThreadPoolExecutor(max_workers=2) as callers:
        pending_preview = callers.submit(
            client.post,
            "/api/convert/preview",
            files={"image": ("source.png", upload, "image/png")},
            data={"lut_name": "fixture", "target_width_mm": "1.2"},
        )
        health_before_release = None
        try:
            assert entered.wait(timeout=10), "Preview never reached the publication barrier"
            pending_health = callers.submit(client.get, "/api/health")
            try:
                health_before_release = pending_health.result(timeout=1)
            except FutureTimeoutError:
                pass
            assert not release.is_set()
            assert not pending_preview.done()
        finally:
            release.set()
        response = pending_preview.result(timeout=10)
        assert pending_health.result(timeout=10).status_code == 200
        assert response.status_code == 200, response.text
        session_id = response.json()["session_id"]
        assert store.get(session_id)["preview_cache"]["schema"]
        registry.cleanup_session(session_id)
        store.close(session_id)

    assert health_before_release is not None, (
        f"/api/health was blocked by preview {blocked_stage} until publication was released"
    )
    assert health_before_release.status_code == 200


@pytest.mark.parametrize("failed_stage", ["session_write", "palette"])
def test_publication_failure_removes_unreturned_session_and_worker_files(
    failed_stage: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _write_worker_result(tmp_path)
    store, registry = SessionStore(), FileRegistry()
    test_app = _make_app(store, registry, result, monkeypatch)
    created: list[str] = []
    create = store.create

    def record_session(*args: Any, **kwargs: Any) -> str:
        session_id = create(*args, **kwargs)
        created.append(session_id)
        return session_id

    monkeypatch.setattr(store, "create", record_session)
    if failed_stage == "session_write":
        put = store.put

        def fail_put(session_id: str, key: str, value: Any) -> None:
            if key == "image_path":
                raise OSError("Publication session write failed")
            put(session_id, key, value)

        monkeypatch.setattr(store, "put", fail_put)
    else:
        def fail_palette(*args: Any, **kwargs: Any) -> list:
            raise ValueError("Publication palette assembly failed")

        monkeypatch.setattr(preview, "build_preview_response_palette", fail_palette)

    upload_bytes = Path(result["preview_png_path"]).read_bytes()
    try:
        with TestClient(test_app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/convert/preview",
                files={"image": ("source.png", upload_bytes, "image/png")},
                data={"lut_name": "fixture", "target_width_mm": "1.2"},
            )
        assert response.status_code == 500
        assert created
        assert all(store.get(session_id) is None for session_id in created)
        assert all(registry.get_session_entries(session_id) == {} for session_id in created)
        assert list(tmp_path.iterdir()) == []
    finally:
        for session_id in created:
            registry.cleanup_session(session_id)
            store.close(session_id)


@pytest.mark.parametrize(
    ("blocked_stage", "publication_fails", "cancel_during_rollback"),
    [
        ("cache_read", False, False),
        ("png_publish", False, False),
        ("png_publish", True, False),
        ("png_publish", False, True),
    ],
)
def test_cancellation_drains_publication_before_rolling_back(
    blocked_stage: str,
    publication_fails: bool,
    cancel_during_rollback: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling a request must not remove inputs still used by its thread."""
    result = _write_worker_result(tmp_path)
    store, registry = SessionStore(), FileRegistry()
    test_app = _make_app(store, registry, result, monkeypatch)
    entered, release, cancellation_delivered = (
        threading.Event(), threading.Event(), threading.Event(),
    )
    rollback_entered, release_rollback = threading.Event(), threading.Event()
    created: list[str] = []
    request_state: dict[str, Any] = {}
    create = store.create
    register_bytes = registry.register_bytes

    def record_session(*args: Any, **kwargs: Any) -> str:
        session_id = create(*args, **kwargs)
        created.append(session_id)
        return session_id

    monkeypatch.setattr(store, "create", record_session)
    if cancel_during_rollback:
        close = store.close

        def blocked_close(session_id: str) -> int:
            rollback_entered.set()
            if not release_rollback.wait(timeout=10):
                raise RuntimeError("Test did not release rollback")
            return close(session_id)

        monkeypatch.setattr(store, "close", blocked_close)

    def block_until_released() -> None:
        entered.set()
        if not release.wait(timeout=10):
            raise RuntimeError("Test did not release publication")
        assert Path(result["preview_png_path"]).is_file()
        assert all(store.get(session_id) is not None for session_id in created)

    if blocked_stage == "cache_read":
        hydrate = preview.hydrate_preview_cache

        def blocked_hydrate(*args: Any, **kwargs: Any) -> dict:
            block_until_released()
            return hydrate(*args, **kwargs)

        monkeypatch.setattr(preview, "hydrate_preview_cache", blocked_hydrate)
    else:
        def blocked_register(session_id: str, *args: Any, **kwargs: Any) -> str:
            block_until_released()
            if publication_fails:
                raise OSError("PNG publication failed after cancellation")
            return register_bytes(session_id, *args, **kwargs)

        monkeypatch.setattr(registry, "register_bytes", blocked_register)
    upload_bytes = Path(result["preview_png_path"]).read_bytes()

    async def request_preview() -> bool:
        request_state["loop"] = asyncio.get_running_loop()
        request_state["task"] = asyncio.current_task()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(test_app), base_url="http://test",
        ) as client:
            try:
                await client.post(
                    "/api/convert/preview",
                    files={"image": ("source.png", upload_bytes, "image/png")},
                    data={"lut_name": "fixture", "target_width_mm": "1.2"},
                )
            except asyncio.CancelledError:
                return True
            return False

    try:
        with TestClient(test_app) as client:
            pending = client.portal.start_task_soon(request_preview)
            try:
                assert entered.wait(timeout=10)

                def cancel_request() -> None:
                    request_state["task"].cancel()
                    # Deliver a second cancellation on a later loop turn while
                    # the publication thread remains at the barrier.
                    def cancel_again() -> None:
                        request_state["task"].cancel()
                        request_state["loop"].call_soon(cancellation_delivered.set)

                    request_state["loop"].call_soon(cancel_again)

                request_state["loop"].call_soon_threadsafe(cancel_request)
                assert cancellation_delivered.wait(timeout=1)
                assert Path(result["preview_png_path"]).is_file()
                assert all(store.get(session_id) is not None for session_id in created)
            finally:
                release.set()
            if cancel_during_rollback:
                assert rollback_entered.wait(timeout=10)
                cancellation_delivered.clear()

                def cancel_rollback() -> None:
                    request_state["task"].cancel()
                    request_state["loop"].call_soon(cancellation_delivered.set)

                request_state["loop"].call_soon_threadsafe(cancel_rollback)
                assert cancellation_delivered.wait(timeout=1)
                assert not pending.done(), "Cancellation abandoned an active rollback"
                release_rollback.set()
            assert pending.result(timeout=10), "Preview ignored cancellation during publication"
        assert all(store.get(session_id) is None for session_id in created)
        assert all(registry.get_session_entries(session_id) == {} for session_id in created)
        assert list(tmp_path.iterdir()) == []
    finally:
        release.set()
        release_rollback.set()
        for session_id in created:
            registry.cleanup_session(session_id)
            store.close(session_id)


def test_rollback_invalidates_session_before_cleaning_glb_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An in-flight GLB cannot publish into the rollback cleanup gap."""
    result = _write_worker_result(tmp_path)
    store, registry = SessionStore(), FileRegistry()
    test_app = _make_app(store, registry, result, monkeypatch)
    monkeypatch.setattr(preview, "generate_segmented_glb", preview._DEFAULT_GENERATE_SEGMENTED_GLB)
    monkeypatch.setattr(async_glb, "OUTPUT_DIR", str(tmp_path))
    build_started, release_build, build_finished = (
        threading.Event(), threading.Event(), threading.Event(),
    )
    created: list[str] = []
    built_paths: list[Path] = []
    run_job = async_glb._run_glb_build_job

    def measured_job(*args: Any, **kwargs: Any) -> None:
        try:
            run_job(*args, **kwargs)
        finally:
            build_finished.set()

    def paused_mesh_build(*, output_path: str, **kwargs: Any) -> tuple[str, str]:
        import trimesh

        build_started.set()
        if not release_build.wait(timeout=10):
            raise RuntimeError("Test did not release GLB build")
        trimesh.creation.box().export(output_path)
        built_paths.append(Path(output_path))
        return output_path, "segmented"

    monkeypatch.setattr(async_glb, "_run_glb_build_job", measured_job)
    monkeypatch.setattr(async_glb, "_build_preview_glb", paused_mesh_build)
    cleanup_registry = registry.cleanup_session

    def release_glb_after_registry_cleanup(session_id: str) -> int:
        created.append(session_id)
        removed = cleanup_registry(session_id)
        release_build.set()
        assert build_finished.wait(timeout=10), "GLB job did not complete"
        return removed

    monkeypatch.setattr(registry, "cleanup_session", release_glb_after_registry_cleanup)

    def fail_response(*args: Any, **kwargs: Any) -> None:
        assert build_started.wait(timeout=10), "GLB build never started"
        raise ValueError("Response validation failed after GLB scheduling")

    monkeypatch.setattr(preview, "PreviewResponse", fail_response)
    upload_bytes = Path(result["preview_png_path"]).read_bytes()
    try:
        with TestClient(test_app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/convert/preview",
                files={"image": ("source.png", upload_bytes, "image/png")},
                data={"lut_name": "fixture", "target_width_mm": "1.2"},
            )
        assert response.status_code == 500
        assert created
        assert all(store.get(session_id) is None for session_id in created)
        assert all(registry.get_session_entries(session_id) == {} for session_id in created)
        assert all(not path.exists() for path in built_paths)
    finally:
        release_build.set()
        for session_id in created:
            store.close(session_id)
            cleanup_registry(session_id)
