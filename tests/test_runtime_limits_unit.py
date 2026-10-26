from __future__ import annotations

import os

from api import runtime_limits


def test_configure_blas_thread_limits_sets_missing_defaults(monkeypatch) -> None:
    for env_name in runtime_limits.BLAS_THREAD_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)

    runtime_limits.configure_blas_thread_limits()

    for env_name in runtime_limits.BLAS_THREAD_ENV_VARS:
        assert os.environ[env_name] == "1"


def test_configure_blas_thread_limits_preserves_operator_overrides(monkeypatch) -> None:
    for env_name in runtime_limits.BLAS_THREAD_ENV_VARS:
        monkeypatch.setenv(env_name, "4")

    runtime_limits.configure_blas_thread_limits()

    for env_name in runtime_limits.BLAS_THREAD_ENV_VARS:
        assert os.environ[env_name] == "4"
