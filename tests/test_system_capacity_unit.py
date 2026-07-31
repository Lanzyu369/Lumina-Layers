"""Unit coverage for effective CPU-capacity discovery."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _capacity_module():
    from core import system_capacity

    return system_capacity


def test_affinity_narrows_host_capacity() -> None:
    system_capacity = _capacity_module()

    result = system_capacity.discover_effective_cpu_capacity(
        host_cpu_count=12,
        affinity_cpu_ids={2, 3, 4, 5},
        cgroup_cpu_max=None,
        apple_performance_cpu_count=None,
    )

    assert result.host_cpu_count == 12
    assert result.affinity_cpu_count == 4
    assert result.effective_cpu_count == 4
    assert result.limiting_source == "affinity"


def test_cgroup_quota_narrows_affinity_and_rounds_fractional_cpu_up() -> None:
    system_capacity = _capacity_module()

    result = system_capacity.discover_effective_cpu_capacity(
        host_cpu_count=16,
        affinity_cpu_ids=set(range(8)),
        cgroup_cpu_max="250000 100000",
        apple_performance_cpu_count=None,
    )

    assert result.cgroup_quota_cpu_count == 3
    assert result.effective_cpu_count == 3
    assert result.limiting_source == "cgroup_v2"


def test_apple_performance_cores_are_preferred() -> None:
    system_capacity = _capacity_module()

    result = system_capacity.discover_effective_cpu_capacity(
        host_cpu_count=10,
        affinity_cpu_ids=None,
        cgroup_cpu_max=None,
        apple_performance_cpu_count=4,
    )

    assert result.apple_performance_cpu_count == 4
    assert result.effective_cpu_count == 4
    assert result.limiting_source == "apple_performance"


@pytest.mark.parametrize(
    "raw_cpu_max",
    [None, "", "max 100000", "broken", "1 0", "-1 100000"],
)
def test_unavailable_or_invalid_cgroup_quota_is_ignored(
    raw_cpu_max: str | None,
) -> None:
    system_capacity = _capacity_module()

    result = system_capacity.discover_effective_cpu_capacity(
        host_cpu_count=6,
        affinity_cpu_ids=None,
        cgroup_cpu_max=raw_cpu_max,
        apple_performance_cpu_count=None,
    )

    assert result.cgroup_quota_cpu_count is None
    assert result.effective_cpu_count == 6
    assert result.limiting_source == "host_fallback"


def test_invalid_probes_fall_back_to_at_least_one_cpu() -> None:
    system_capacity = _capacity_module()

    result = system_capacity.discover_effective_cpu_capacity(
        host_cpu_count=None,
        affinity_cpu_ids=set(),
        cgroup_cpu_max="broken",
        apple_performance_cpu_count=0,
    )

    assert result.effective_cpu_count == 1
    assert result.limiting_source == "host_fallback"


def test_live_capacity_discovery_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_capacity = _capacity_module()
    expected = system_capacity.EffectiveCpuCapacity(
        host_cpu_count=8,
        affinity_cpu_count=4,
        cgroup_quota_cpu_count=None,
        apple_performance_cpu_count=None,
        effective_cpu_count=4,
        limiting_source="affinity",
    )
    calls = 0

    def fake_discover_live_capacity():
        nonlocal calls
        calls += 1
        return expected

    system_capacity.get_effective_cpu_capacity.cache_clear()
    monkeypatch.setattr(
        system_capacity,
        "_discover_live_capacity",
        fake_discover_live_capacity,
    )
    try:
        assert system_capacity.get_effective_cpu_capacity() is expected
        assert system_capacity.get_effective_cpu_capacity() is expected
        assert calls == 1
    finally:
        system_capacity.get_effective_cpu_capacity.cache_clear()


def test_apple_probe_uses_argument_vector_timeout_without_shell() -> None:
    system_capacity = _capacity_module()
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="4\n", stderr="")

    result = system_capacity._read_apple_performance_cpu_count(
        platform_name="darwin",
        runner=fake_run,
    )

    assert result == 4
    assert observed["command"] == [
        "sysctl",
        "-n",
        "hw.perflevel0.logicalcpu",
    ]
    assert observed["kwargs"] == {
        "capture_output": True,
        "check": False,
        "shell": False,
        "text": True,
        "timeout": 0.5,
    }


def test_apple_probe_failure_is_normal_fallback() -> None:
    system_capacity = _capacity_module()

    def fail_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    assert (
        system_capacity._read_apple_performance_cpu_count(
            platform_name="darwin",
            runner=fail_run,
        )
        is None
    )
    assert (
        system_capacity._read_apple_performance_cpu_count(
            platform_name="linux",
            runner=fail_run,
        )
        is None
    )


def test_cgroup_reader_uses_explicit_utf8_path(tmp_path: Path) -> None:
    system_capacity = _capacity_module()
    cpu_max_path = tmp_path / "cpu.max"
    cpu_max_path.write_text("150000 100000\n", encoding="utf-8")

    assert (
        system_capacity._read_cgroup_v2_cpu_max(cpu_max_path=cpu_max_path)
        == "150000 100000"
    )
