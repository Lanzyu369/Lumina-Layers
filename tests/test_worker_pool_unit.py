"""Unit tests for WorkerPoolManager lifecycle and behavior.

Covers: start/shutdown lifecycle, submit success/error, is_alive property,
max_workers defaults, and RuntimeError when pool not started.

**Validates: Requirements 1.1, 1.4, 1.5, 2.3**
"""

import asyncio
import os
from unittest.mock import patch

import pytest

from api.worker_pool import WorkerPoolManager


# ---------------------------------------------------------------------------
# Helpers — top-level picklable functions for process pool
# ---------------------------------------------------------------------------

def _add(a: int, b: int) -> int:
    """Simple addition for testing submit."""
    return a + b


def _raise_value_error(msg: str) -> None:
    """Raise ValueError in worker process."""
    raise ValueError(msg)


def _slow_task(seconds: float) -> str:
    """Sleep for given seconds, simulating a long-running task."""
    import time
    time.sleep(seconds)
    return "done"


def _read_context_ids() -> tuple[str | None, str | None]:
    """Top-level helper for asserting contextvar propagation into a worker."""
    from api.structured_logging import get_request_id, get_session_id

    return (get_request_id(), get_session_id())


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------

class TestWorkerPoolLifecycle:
    """Test start/shutdown/is_alive behavior."""

    def test_not_alive_before_start(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        assert pool.is_alive is False

    def test_alive_after_start(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        pool.start()
        try:
            assert pool.is_alive is True
        finally:
            pool.shutdown(wait=True)

    def test_start_is_idempotent_when_pool_is_already_alive(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        sentinel_pool = object()

        with patch("api.worker_pool.ProcessPoolExecutor", return_value=sentinel_pool) as executor_cls:
            pool.start()
            first_pool = pool._pool
            pool.start()

        assert first_pool is sentinel_pool
        assert pool._pool is sentinel_pool
        executor_cls.assert_called_once()

    def test_not_alive_after_shutdown(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        pool.start()
        pool.shutdown(wait=True)
        assert pool.is_alive is False

    def test_shutdown_without_start_is_noop(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        pool.shutdown(wait=True)  # Should not raise
        assert pool.is_alive is False

    def test_double_shutdown_is_safe(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        pool.start()
        pool.shutdown(wait=True)
        pool.shutdown(wait=True)  # Should not raise
        assert pool.is_alive is False


# ---------------------------------------------------------------------------
# max_workers tests
# ---------------------------------------------------------------------------

class TestMaxWorkers:
    """Test max_workers default and explicit values."""

    def test_explicit_max_workers(self) -> None:
        pool = WorkerPoolManager(max_workers=3)
        assert pool.max_workers == 3

    def test_default_max_workers(self) -> None:
        pool = WorkerPoolManager()
        expected = min(os.cpu_count() or 2, 4)
        assert pool.max_workers == expected

    def test_none_max_workers_uses_default(self) -> None:
        pool = WorkerPoolManager(max_workers=None)
        expected = min(os.cpu_count() or 2, 4)
        assert pool.max_workers == expected


# ---------------------------------------------------------------------------
# submit tests
# ---------------------------------------------------------------------------

class TestSubmit:
    """Test async submit behavior."""

    @pytest.mark.asyncio
    async def test_submit_returns_result(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        pool.start()
        try:
            result = await pool.submit(_add, 3, 7)
            assert result == 10
        finally:
            pool.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_submit_raises_runtime_error_when_not_started(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        with pytest.raises(RuntimeError, match="WorkerPool not started"):
            await pool.submit(_add, 1, 2)

    @pytest.mark.asyncio
    async def test_submit_propagates_worker_exception(self) -> None:
        """Worker exceptions should propagate to the caller."""
        pool = WorkerPoolManager(max_workers=2)
        pool.start()
        try:
            with pytest.raises(ValueError, match="test error"):
                await pool.submit(_raise_value_error, "test error")
        finally:
            pool.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_submit_timeout_raises_timeout_error(self) -> None:
        """Tasks exceeding timeout should raise asyncio.TimeoutError."""
        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        try:
            with pytest.raises(asyncio.TimeoutError):
                await pool.submit(_slow_task, 10.0, timeout=0.3)
        finally:
            pool.shutdown(wait=False)


class TestContextvarPropagation:
    """Verify request_id / session_id flow into the worker process."""

    @pytest.mark.asyncio
    async def test_submit_propagates_request_id_and_session_id(self) -> None:
        from api.structured_logging import (
            reset_request_id,
            reset_session_id,
            set_request_id,
            set_session_id,
        )

        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        request_token = set_request_id("req-round2-abc")
        session_token = set_session_id("sess-round2-xyz")
        try:
            result = await pool.submit(_read_context_ids)
            assert result == ("req-round2-abc", "sess-round2-xyz")
        finally:
            reset_session_id(session_token)
            reset_request_id(request_token)
            pool.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_submit_passes_none_when_parent_has_no_ids(self) -> None:
        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        try:
            result = await pool.submit(_read_context_ids)
            assert result == (None, None)
        finally:
            pool.shutdown(wait=True)


class TestSubmitIsTransparentToParentContext:
    """submit() must not silently bind a new session_id on the parent context."""

    @pytest.mark.asyncio
    async def test_submit_leaves_parent_session_id_none_when_unset(self) -> None:
        from api.structured_logging import get_session_id

        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        try:
            assert get_session_id() is None
            await pool.submit(_add, 1, 2)
            assert get_session_id() is None
        finally:
            pool.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_submit_preserves_parent_session_id_when_set(self) -> None:
        from api.structured_logging import (
            get_session_id,
            reset_session_id,
            set_session_id,
        )

        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        token = set_session_id("parent-sess-explicit")
        try:
            await pool.submit(_add, 1, 2)
            assert get_session_id() == "parent-sess-explicit"
        finally:
            reset_session_id(token)
            pool.shutdown(wait=True)


class TestRunInWorkerWithContext:
    """Unit-test the wrapper without spawning subprocesses."""

    def test_wrapper_sets_request_id_before_invoking_fn(self) -> None:
        from api.worker_pool import _run_in_worker_with_context
        from api.structured_logging import get_request_id, get_session_id

        captured: dict[str, str | None] = {}

        def _capture(*_args: object) -> None:
            captured["request_id"] = get_request_id()
            captured["session_id"] = get_session_id()

        _run_in_worker_with_context(_capture, "req-direct", "sess-direct")
        assert captured == {"request_id": "req-direct", "session_id": "sess-direct"}

    def test_wrapper_skips_set_when_ids_are_none(self) -> None:
        from api.worker_pool import _run_in_worker_with_context
        from api.structured_logging import (
            get_request_id,
            get_session_id,
            reset_request_id,
            reset_session_id,
            set_request_id,
            set_session_id,
        )

        outer_request = set_request_id("outer-req")
        outer_session = set_session_id("outer-sess")
        try:
            captured: dict[str, str | None] = {}

            def _capture(*_args: object) -> None:
                captured["request_id"] = get_request_id()
                captured["session_id"] = get_session_id()

            _run_in_worker_with_context(_capture, None, None)
            assert captured == {"request_id": "outer-req", "session_id": "outer-sess"}
        finally:
            reset_session_id(outer_session)
            reset_request_id(outer_request)

    def test_wrapper_returns_fn_result(self) -> None:
        from api.worker_pool import _run_in_worker_with_context

        def _add_local(a: int, b: int) -> int:
            return a + b

        assert _run_in_worker_with_context(_add_local, "rid", "sid", 2, 3) == 5
