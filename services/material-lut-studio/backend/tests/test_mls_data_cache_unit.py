"""MLS data material-cache concurrency tests.
MLS data 耗材缓存并发测试。
"""

from __future__ import annotations

import concurrent.futures
import threading

from backend.routers import data as data_router


def _reset_material_cache_state() -> None:
    """Reset process-level material cache state for isolated tests.
    重置进程级耗材缓存状态，保证用例隔离。
    """
    with data_router._material_cache_lock:
        data_router._material_cache.clear()
        data_router._material_epoch.clear()
    with data_router._inflight_lock:
        data_router._inflight.clear()


def test_post_write_reader_does_not_join_stale_inflight(monkeypatch) -> None:
    """A reader that starts after eviction must not wait on a pre-write load.
    写入失效后开始的读取不能复用写入前的 in-flight 加载。
    """
    _reset_material_cache_state()
    first_load_entered = threading.Event()
    release_first_load = threading.Event()
    second_load_entered = threading.Event()
    call_lock = threading.Lock()
    calls: list[list[str]] = []

    def fake_load_multiple_materials(
        directory_names: list[str], materials_dir: str
    ) -> list[str]:
        del materials_dir
        with call_lock:
            calls.append(list(directory_names))
            call_number = len(calls)
        if call_number == 1:
            first_load_entered.set()
            if not release_first_load.wait(timeout=2.0):
                raise AssertionError("timed out waiting to release first load")
            return ["old"]
        second_load_entered.set()
        return ["new"]

    monkeypatch.setattr(
        data_router, "load_multiple_materials", fake_load_multiple_materials
    )

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            old_future = pool.submit(data_router._load_materials_cached, ["mat"])
            assert first_load_entered.wait(timeout=2.0)

            data_router.evict_material_cache("mat")
            new_future = pool.submit(data_router._load_materials_cached, ["mat"])
            try:
                assert new_future.result(timeout=1.0) == ["new"]
            finally:
                release_first_load.set()
            assert old_future.result(timeout=1.0) == ["old"]

        assert second_load_entered.is_set()
        assert len(calls) == 2
        assert data_router._load_materials_cached(["mat"]) == ["new"]
    finally:
        release_first_load.set()
        _reset_material_cache_state()


def test_same_generation_waiters_share_inflight_load(monkeypatch) -> None:
    """Concurrent readers in one generation share the leader load.
    同一 generation 内的并发读取复用同一个 leader 加载。
    """
    _reset_material_cache_state()
    load_entered = threading.Event()
    release_load = threading.Event()
    call_lock = threading.Lock()
    calls: list[list[str]] = []

    def fake_load_multiple_materials(
        directory_names: list[str], materials_dir: str
    ) -> list[str]:
        del materials_dir
        with call_lock:
            calls.append(list(directory_names))
        load_entered.set()
        if not release_load.wait(timeout=2.0):
            raise AssertionError("timed out waiting to release load")
        return ["shared"]

    monkeypatch.setattr(
        data_router, "load_multiple_materials", fake_load_multiple_materials
    )

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            leader_future = pool.submit(data_router._load_materials_cached, ["mat"])
            assert load_entered.wait(timeout=2.0)
            waiter_future = pool.submit(data_router._load_materials_cached, ["mat"])

            release_load.set()
            assert leader_future.result(timeout=1.0) == ["shared"]
            assert waiter_future.result(timeout=1.0) == ["shared"]

        assert len(calls) == 1
    finally:
        release_load.set()
        _reset_material_cache_state()
