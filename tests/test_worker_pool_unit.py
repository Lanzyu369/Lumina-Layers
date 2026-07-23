"""Unit tests for WorkerPoolManager lifecycle and behavior.

Covers: start/shutdown lifecycle, submit success/error, is_alive property,
max_workers defaults, and RuntimeError when pool not started.

**Validates: Requirements 1.1, 1.4, 1.5, 2.3**
"""

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import api.worker_pool as worker_pool
from api.worker_pool import WorkerPoolManager
from config import WorkerPoolConfig


@pytest.fixture(autouse=True)
def _clear_logging_context_between_tests():
    from api.structured_logging import bind_session_id, set_request_id

    set_request_id(None)
    bind_session_id(None)
    yield
    set_request_id(None)
    bind_session_id(None)


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

    def test_default_task_timeout_from_constructor(self) -> None:
        pool = WorkerPoolManager(max_workers=2, default_task_timeout=12.5)
        assert pool.default_task_timeout == 12.5

    def test_zero_default_task_timeout_disables_timeout(self) -> None:
        pool = WorkerPoolManager(max_workers=2, default_task_timeout=0)
        assert pool.default_task_timeout is None

    def test_dependency_factory_wires_configured_task_timeout(self) -> None:
        from api.dependencies import _build_worker_pool

        cfg = WorkerPoolConfig()
        cfg.MAX_WORKERS = 3
        cfg.TASK_TIMEOUT = 14.0

        pool = _build_worker_pool(cfg)

        assert pool.max_workers == 3
        assert pool.default_task_timeout == 14.0


class TestWorkerPoolConfigEnvValidation:
    """Validate env override parsing for worker pool config."""

    def test_invalid_max_workers_falls_back_and_logs_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("LUMINA_MAX_WORKERS", "abc")
        target_logger = logging.getLogger("lumina.config")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)

        cfg = WorkerPoolConfig.from_env()

        assert cfg.MAX_WORKERS == WorkerPoolConfig.MAX_WORKERS
        warnings = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "worker_pool_max_workers_invalid"
        ]
        assert len(warnings) == 1
        assert getattr(warnings[0], "env_var", None) == "LUMINA_MAX_WORKERS"
        assert getattr(warnings[0], "raw_value", None) == "abc"
        assert getattr(warnings[0], "fallback", None) == WorkerPoolConfig.MAX_WORKERS
        assert getattr(warnings[0], "error_type", None) == "ValueError"
        assert getattr(warnings[0], "error_message", None)

    def test_blank_worker_config_env_is_ignored_without_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("LUMINA_MAX_WORKERS", "   ")
        monkeypatch.setenv("LUMINA_TASK_TIMEOUT", "   ")
        target_logger = logging.getLogger("lumina.config")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)

        cfg = WorkerPoolConfig.from_env()

        assert cfg.MAX_WORKERS == WorkerPoolConfig.MAX_WORKERS
        assert cfg.TASK_TIMEOUT == WorkerPoolConfig.TASK_TIMEOUT
        assert not [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            in {
                "worker_pool_max_workers_invalid",
                "worker_pool_task_timeout_invalid",
            }
        ]

    @pytest.mark.parametrize("raw_value", ["0", "-2"])
    def test_non_positive_max_workers_falls_back_and_logs_warning(
        self,
        raw_value: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("LUMINA_MAX_WORKERS", raw_value)
        target_logger = logging.getLogger("lumina.config")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)

        cfg = WorkerPoolConfig.from_env()

        assert cfg.MAX_WORKERS == WorkerPoolConfig.MAX_WORKERS
        warnings = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "worker_pool_max_workers_invalid"
        ]
        assert len(warnings) == 1
        assert getattr(warnings[0], "raw_value", None) == raw_value
        assert getattr(warnings[0], "fallback", None) == WorkerPoolConfig.MAX_WORKERS

    def test_invalid_task_timeout_falls_back_and_logs_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("LUMINA_TASK_TIMEOUT", "notfloat")
        target_logger = logging.getLogger("lumina.config")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)

        cfg = WorkerPoolConfig.from_env()

        assert cfg.TASK_TIMEOUT == WorkerPoolConfig.TASK_TIMEOUT
        warnings = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "worker_pool_task_timeout_invalid"
        ]
        assert len(warnings) == 1
        assert getattr(warnings[0], "env_var", None) == "LUMINA_TASK_TIMEOUT"
        assert getattr(warnings[0], "raw_value", None) == "notfloat"
        assert getattr(warnings[0], "fallback", None) == WorkerPoolConfig.TASK_TIMEOUT
        assert getattr(warnings[0], "error_type", None) == "ValueError"
        assert getattr(warnings[0], "error_message", None)

    @pytest.mark.parametrize("raw_value", ["nan", "inf", "-inf"])
    def test_non_finite_task_timeout_falls_back_and_logs_warning(
        self,
        raw_value: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("LUMINA_TASK_TIMEOUT", raw_value)
        target_logger = logging.getLogger("lumina.config")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)

        cfg = WorkerPoolConfig.from_env()

        assert cfg.TASK_TIMEOUT == WorkerPoolConfig.TASK_TIMEOUT
        warnings = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "worker_pool_task_timeout_invalid"
        ]
        assert len(warnings) == 1
        assert getattr(warnings[0], "raw_value", None) == raw_value
        assert getattr(warnings[0], "fallback", None) == WorkerPoolConfig.TASK_TIMEOUT

    def test_invalid_worker_env_does_not_crash_dependencies_cold_import(
        self,
        tmp_path: Path,
    ) -> None:
        env = os.environ.copy()
        env.update(
            {
                "LUMINA_ENV_LOCAL_PATH": str(tmp_path / "missing-env"),
                "LUMINA_LOG_DIR": str(tmp_path / "logs"),
                "LUMINA_MAX_WORKERS": "abc",
                "LUMINA_TASK_TIMEOUT": "notfloat",
                "PYTHONPATH": os.pathsep.join(
                    filter(None, [os.getcwd(), env.get("PYTHONPATH", "")])
                ),
            }
        )

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import api.dependencies as deps; "
                    "print("
                    "f'max={deps.worker_pool.max_workers};"
                    "timeout={deps.worker_pool.default_task_timeout!r}'"
                    ")"
                ),
            ],
            cwd=os.getcwd(),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        combined_output = f"{result.stdout}\n{result.stderr}"
        assert result.returncode == 0, combined_output
        assert f"max={WorkerPoolConfig.MAX_WORKERS};timeout=None" in result.stdout
        assert "worker_pool_max_workers_invalid" in combined_output
        assert "worker_pool_task_timeout_invalid" in combined_output


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

    @pytest.mark.asyncio
    async def test_timeout_restarts_pool_so_next_task_can_run(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A timed-out worker must not keep occupying the only pool slot."""
        target_logger = logging.getLogger("lumina.api.worker_pool")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)
        pool = WorkerPoolManager(max_workers=1, default_task_timeout=0.2)
        pool.start()
        try:
            with pytest.raises(asyncio.TimeoutError):
                await pool.submit(_slow_task, 2.0)

            result = await pool.submit(_add, 4, 5, timeout=2.0)
            assert result == 9

            restarts = [
                record
                for record in caplog.records
                if getattr(record, "event", None) == "worker_pool_restarted"
            ]
            assert len(restarts) == 1
            assert getattr(restarts[0], "reason", None) == "task_timeout"
            assert getattr(restarts[0], "error_type", None) == "task_timeout"
            assert getattr(restarts[0], "error_message", None)
            assert getattr(restarts[0], "terminated_workers", None) == 1
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


# ---------------------------------------------------------------------------
# max_tasks_per_child tests (worker recycling for long-running RSS bounds)
# ---------------------------------------------------------------------------

class TestMaxTasksPerChild:
    """Test LUMINA_WORKER_MAX_TASKS_PER_CHILD env var resolution and propagation.
    LUMINA_WORKER_MAX_TASKS_PER_CHILD 环境变量解析与传递测试.

    Validates env-driven worker recycling configuration that bounds
    long-running RSS growth in production.
    验证环境变量驱动的 worker 进程回收配置, 用于在生产长跑场景下
    限制 RSS 单调增长.
    """

    def test_default_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", raising=False)
        pool = WorkerPoolManager(max_workers=2)
        expected = 1 if worker_pool.sys.platform == "darwin" else 20
        assert pool.max_tasks_per_child == expected

    def test_default_is_1_on_darwin_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", raising=False)
        monkeypatch.setattr(worker_pool.sys, "platform", "darwin")
        pool = WorkerPoolManager(max_workers=2)
        assert pool.max_tasks_per_child == 1

    def test_default_is_20_off_darwin_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", raising=False)
        monkeypatch.setattr(worker_pool.sys, "platform", "linux")
        pool = WorkerPoolManager(max_workers=2)
        assert pool.max_tasks_per_child == 20

    def test_env_var_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", "5")
        pool = WorkerPoolManager(max_workers=2)
        assert pool.max_tasks_per_child == 5

    def test_env_zero_disables_recycling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", "0")
        pool = WorkerPoolManager(max_workers=2)
        assert pool.max_tasks_per_child is None

    def test_env_invalid_falls_back_to_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", "abc")
        target_logger = logging.getLogger("lumina.api.worker_pool")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)

        pool = WorkerPoolManager(max_workers=2)

        expected = 1 if worker_pool.sys.platform == "darwin" else 20
        assert pool.max_tasks_per_child == expected
        warnings = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "worker_pool_max_tasks_invalid"
        ]
        assert len(warnings) == 1
        assert getattr(warnings[0], "raw_value", None) == "abc"
        assert getattr(warnings[0], "fallback", None) == expected
        assert getattr(warnings[0], "error_type", None) == "ValueError"
        assert getattr(warnings[0], "error_message", None)

    def test_start_passes_param_to_executor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", raising=False)
        monkeypatch.setattr(worker_pool.sys, "platform", "linux")
        pool = WorkerPoolManager(max_workers=3)
        sentinel = object()
        with patch(
            "api.worker_pool.ProcessPoolExecutor", return_value=sentinel
        ) as executor_cls:
            pool.start()
        executor_cls.assert_called_once()
        kwargs = executor_cls.call_args.kwargs
        assert kwargs["max_workers"] == 3
        assert kwargs["max_tasks_per_child"] == 20
        assert "initializer" in kwargs
