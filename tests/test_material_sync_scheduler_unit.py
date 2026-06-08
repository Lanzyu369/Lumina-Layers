"""Unit tests for material sync background refresh scheduling."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from api.material_sync_scheduler import (
    cancel_material_sync_auto_refresh_tasks,
    run_material_sync_refresh_once,
    start_material_sync_auto_refresh_tasks,
)


def test_material_sync_auto_refresh_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("LUMINA_MATERIAL_SYNC_STARTUP_REFRESH", raising=False)
    monkeypatch.delenv("LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S", raising=False)

    async def _run() -> None:
        tasks = start_material_sync_auto_refresh_tasks()

        assert tasks == []

    asyncio.run(_run())


def test_material_sync_startup_refresh_schedules_one_refresh(monkeypatch) -> None:
    calls: list[str] = []

    async def _fake_refresh_once(*, reason: str) -> dict[str, Any]:
        calls.append(reason)
        return {"installed_count": 0, "skipped_count": 0, "failed_count": 0}

    monkeypatch.setenv("LUMINA_MATERIAL_SYNC_STARTUP_REFRESH", "true")
    monkeypatch.delenv("LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S", raising=False)
    monkeypatch.setattr(
        "api.material_sync_scheduler.run_material_sync_refresh_once",
        _fake_refresh_once,
    )

    async def _run() -> None:
        tasks = start_material_sync_auto_refresh_tasks()
        try:
            await asyncio.sleep(0)
            assert calls == ["startup"]
        finally:
            await cancel_material_sync_auto_refresh_tasks(tasks)

    asyncio.run(_run())


def test_material_sync_refresh_lock_skips_overlapping_refresh(monkeypatch) -> None:
    calls = 0

    def _blocking_refresh() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        return {"installed_count": 1, "skipped_count": 0, "failed_count": 0}

    monkeypatch.setattr(
        "api.material_sync_scheduler.refresh_material_sync_from_registry",
        _blocking_refresh,
    )

    async def _run() -> None:
        first, second = await asyncio.gather(
            run_material_sync_refresh_once(reason="startup"),
            run_material_sync_refresh_once(reason="scheduled"),
        )

        results = [first, second]
        assert calls == 1
        assert any(result is None for result in results)
        assert any(
            isinstance(result, dict) and result["installed_count"] == 1
            for result in results
        )

    asyncio.run(_run())


def test_material_sync_interval_refresh_schedules_repeated_refresh(monkeypatch) -> None:
    calls: list[str] = []

    async def _fake_refresh_once(*, reason: str) -> dict[str, Any]:
        calls.append(reason)
        return {"installed_count": 0, "skipped_count": 0, "failed_count": 0}

    monkeypatch.delenv("LUMINA_MATERIAL_SYNC_STARTUP_REFRESH", raising=False)
    monkeypatch.setenv("LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S", "0.01")
    monkeypatch.setattr(
        "api.material_sync_scheduler.run_material_sync_refresh_once",
        _fake_refresh_once,
    )

    async def _run() -> None:
        tasks = start_material_sync_auto_refresh_tasks()
        try:
            await asyncio.sleep(0.04)
        finally:
            await cancel_material_sync_auto_refresh_tasks(tasks)

        assert calls
        assert set(calls) == {"scheduled"}

    asyncio.run(_run())


def test_material_sync_refresh_returns_none_when_core_refresh_fails(monkeypatch) -> None:
    def _failing_refresh() -> dict[str, Any]:
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(
        "api.material_sync_scheduler.refresh_material_sync_from_registry",
        _failing_refresh,
    )

    async def _run() -> None:
        result = await run_material_sync_refresh_once(reason="startup")

        assert result is None

    asyncio.run(_run())
