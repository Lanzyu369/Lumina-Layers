"""Unit coverage for effective CPU-capacity discovery."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _use_temporary_drive_for_posix_mount_fixtures(monkeypatch, tmp_path: Path):
    # A rooted POSIX fixture path resolves on the current drive on Windows.
    monkeypatch.chdir(tmp_path)


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
    assert result.cpu_topology == "heterogeneous"
    assert result.scheduling_policy == "apple_performance_budget"


def test_uniform_or_unknown_thirty_two_cpu_host_keeps_full_capacity() -> None:
    system_capacity = _capacity_module()

    result = system_capacity.discover_effective_cpu_capacity(
        host_cpu_count=32,
        affinity_cpu_ids=set(range(32)),
        cgroup_cpu_max=None,
        apple_performance_cpu_count=None,
        windows_efficiency_classes=None,
        platform_name="linux",
    )

    assert result.effective_cpu_count == 32
    assert result.windows_performance_cpu_count is None
    assert result.cpu_topology == "unknown"
    assert result.scheduling_policy == "os_capacity_scheduler"


def test_windows_hybrid_cpu_uses_all_visible_cpus_under_os_scheduler() -> None:
    system_capacity = _capacity_module()

    result = system_capacity.discover_effective_cpu_capacity(
        host_cpu_count=32,
        affinity_cpu_ids=set(range(32)),
        cgroup_cpu_max=None,
        apple_performance_cpu_count=None,
        windows_efficiency_classes=([1] * 16) + ([0] * 16),
        platform_name="win32",
    )

    assert result.windows_performance_cpu_count == 16
    assert result.cpu_topology == "heterogeneous"
    assert result.scheduling_policy == "os_core_type_scheduler"
    assert result.effective_cpu_count == 32


def test_windows_uniform_cpu_is_not_misclassified_as_hybrid() -> None:
    system_capacity = _capacity_module()

    result = system_capacity.discover_effective_cpu_capacity(
        host_cpu_count=32,
        affinity_cpu_ids=set(range(32)),
        cgroup_cpu_max=None,
        apple_performance_cpu_count=None,
        windows_efficiency_classes=[0] * 32,
        platform_name="win32",
    )

    assert result.windows_performance_cpu_count == 32
    assert result.cpu_topology == "homogeneous"
    assert result.scheduling_policy == "all_visible_cpus"
    assert result.effective_cpu_count == 32


def test_windows_cpu_set_parser_reads_efficiency_classes() -> None:
    system_capacity = _capacity_module()

    def cpu_set_record(efficiency_class: int) -> bytes:
        record = bytearray(32)
        record[0:4] = (32).to_bytes(4, "little")
        record[4:8] = (0).to_bytes(4, "little")
        record[18] = efficiency_class
        return bytes(record)

    raw_records = cpu_set_record(1) + cpu_set_record(0)

    assert system_capacity._parse_windows_efficiency_classes(raw_records) == (
        1,
        0,
    )


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


def _write_cgroup_v2_probe(
    tmp_path: Path,
    *,
    process_cgroup: str,
    mount_root: str = "/",
) -> tuple[Path, Path, Path]:
    proc_self_path = tmp_path / "proc" / "self"
    proc_self_path.mkdir(parents=True)
    cgroup_path = proc_self_path / "cgroup"
    cgroup_path.write_text(process_cgroup, encoding="utf-8")

    mount_point = tmp_path / "sys" / "fs" / "cgroup"
    mount_point.mkdir(parents=True)
    mount_path = "/" + mount_point.relative_to(mount_point.anchor).as_posix()
    mountinfo_path = proc_self_path / "mountinfo"
    mountinfo_path.write_text(
        (
            f"36 29 0:32 {mount_root} {mount_path} "
            "rw,nosuid,nodev,noexec,relatime - cgroup2 cgroup rw\n"
        ),
        encoding="utf-8",
    )
    return cgroup_path, mountinfo_path, mount_point


def test_cgroup_reader_resolves_root_cgroup_cpu_max(tmp_path: Path) -> None:
    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup="0::/\n",
    )
    (mount_point / "cpu.max").write_text(
        "150000 100000\n",
        encoding="utf-8",
    )

    assert system_capacity._read_cgroup_v2_cpu_max(
        proc_self_cgroup_path=cgroup_path,
        proc_self_mountinfo_path=mountinfo_path,
    ) == "150000 100000"


def test_cgroup_reader_resolves_nested_systemd_cgroup(tmp_path: Path) -> None:
    system_capacity = _capacity_module()
    relative_path = Path("user.slice/user-1000.slice/session-2.scope")
    cgroup_path, mountinfo_path, mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup=f"0::/{relative_path.as_posix()}\n",
    )
    cpu_max_path = mount_point / relative_path / "cpu.max"
    cpu_max_path.parent.mkdir(parents=True)
    cpu_max_path.write_text("250000 100000\n", encoding="utf-8")

    assert system_capacity._read_cgroup_v2_cpu_max(
        proc_self_cgroup_path=cgroup_path,
        proc_self_mountinfo_path=mountinfo_path,
    ) == "250000 100000"


def test_cgroup_reader_maps_namespace_path_from_mount_root(
    tmp_path: Path,
) -> None:
    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup="0::/workload.scope\n",
        mount_root="/docker/container-id",
    )
    cpu_max_path = mount_point / "workload.scope" / "cpu.max"
    cpu_max_path.parent.mkdir(parents=True)
    cpu_max_path.write_text("300000 100000\n", encoding="utf-8")

    assert system_capacity._read_cgroup_v2_cpu_max(
        proc_self_cgroup_path=cgroup_path,
        proc_self_mountinfo_path=mountinfo_path,
    ) == "300000 100000"


def test_cgroup_reader_strips_host_visible_mount_root(tmp_path: Path) -> None:
    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup="0::/containers/container-id/workload.scope\n",
        mount_root="/containers/container-id",
    )
    cpu_max_path = mount_point / "workload.scope" / "cpu.max"
    cpu_max_path.parent.mkdir(parents=True)
    cpu_max_path.write_text("400000 100000\n", encoding="utf-8")

    assert system_capacity._read_cgroup_v2_cpu_max(
        proc_self_cgroup_path=cgroup_path,
        proc_self_mountinfo_path=mountinfo_path,
    ) == "400000 100000"


@pytest.mark.parametrize(
    "process_cgroup",
    [
        "malformed\n",
        "0:cpu:/legacy-only\n",
        "0::/first\n0::/second\n",
        "0::/removed.scope (deleted)\n",
    ],
)
def test_cgroup_reader_rejects_malformed_process_cgroup(
    tmp_path: Path,
    process_cgroup: str,
) -> None:
    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, _mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup=process_cgroup,
    )

    assert system_capacity._read_cgroup_v2_cpu_max(
        proc_self_cgroup_path=cgroup_path,
        proc_self_mountinfo_path=mountinfo_path,
    ) is None


def test_cgroup_reader_rejects_path_traversal(tmp_path: Path) -> None:
    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup="0::/../../escape\n",
    )
    escaped_cpu_max = mount_point.parent.parent / "escape" / "cpu.max"
    escaped_cpu_max.parent.mkdir(parents=True)
    escaped_cpu_max.write_text("900000 100000\n", encoding="utf-8")

    assert system_capacity._read_cgroup_v2_cpu_max(
        proc_self_cgroup_path=cgroup_path,
        proc_self_mountinfo_path=mountinfo_path,
    ) is None


def test_cgroup_reader_returns_none_when_current_cpu_max_is_missing(
    tmp_path: Path,
) -> None:
    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, _mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup="0::/missing.scope\n",
    )

    assert system_capacity._read_cgroup_v2_cpu_max(
        proc_self_cgroup_path=cgroup_path,
        proc_self_mountinfo_path=mountinfo_path,
    ) is None


def test_process_affinity_falls_back_to_psutil_on_non_posix_platforms() -> None:
    system_capacity = _capacity_module()

    def unavailable_affinity_reader(_pid: int):
        raise OSError("sched_getaffinity unavailable")

    class FakeProcess:
        def cpu_affinity(self) -> list[int]:
            return [7, 3, 7]

    result = system_capacity._read_process_affinity(
        affinity_reader=unavailable_affinity_reader,
        process_factory=FakeProcess,
    )

    assert result == frozenset({3, 7})


# ---------------------------------------------------------------------------
# Container memory limit (F3)
# ---------------------------------------------------------------------------


def test_cgroup_reader_resolves_memory_limit_and_usage(tmp_path: Path) -> None:
    """The memory reader reuses the CPU path discovery, not a second parser."""

    system_capacity = _capacity_module()
    relative_path = Path("docker/abc123")
    cgroup_path, mountinfo_path, mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup=f"0::/{relative_path.as_posix()}\n",
    )
    cgroup_dir = mount_point / relative_path
    cgroup_dir.mkdir(parents=True)
    (cgroup_dir / "memory.max").write_text("2147483648\n", encoding="utf-8")
    (cgroup_dir / "memory.current").write_text("1073741824\n", encoding="utf-8")

    values = system_capacity._read_cgroup_v2_files(
        ("memory.max", "memory.current"),
        proc_self_cgroup_path=cgroup_path,
        proc_self_mountinfo_path=mountinfo_path,
    )
    assert values == {
        "memory.max": "2147483648",
        "memory.current": "1073741824",
    }


def test_memory_limit_parsing_treats_max_as_unlimited() -> None:
    system_capacity = _capacity_module()
    assert system_capacity._parse_cgroup_v2_memory_value("max") is None
    assert system_capacity._parse_cgroup_v2_memory_value("") is None
    assert system_capacity._parse_cgroup_v2_memory_value("nonsense") is None
    assert system_capacity._parse_cgroup_v2_memory_value("0") == 0
    assert system_capacity._parse_cgroup_v2_memory_value("1024\n") == 1024


def test_effective_memory_is_capped_by_the_container_not_host_ram() -> None:
    """A 2 GiB container must not be told it has the host's 24 GiB."""

    system_capacity = _capacity_module()
    host_available = 24 * 1024**3
    capacity = system_capacity.discover_effective_memory_capacity(
        host_available_bytes=host_available,
        cgroup_values={
            "memory.max": str(2 * 1024**3),
            "memory.current": str(512 * 1024**2),
        },
    )
    assert capacity.source == "cgroup_v2"
    assert capacity.limit_bytes == 2 * 1024**3
    assert capacity.container_used_bytes == 512 * 1024**2
    assert capacity.available_bytes == 1536 * 1024**2
    assert capacity.host_available_bytes == host_available


def test_over_limit_container_reports_zero_available() -> None:
    system_capacity = _capacity_module()
    capacity = system_capacity.discover_effective_memory_capacity(
        host_available_bytes=24 * 1024**3,
        cgroup_values={
            "memory.max": str(1024**3),
            "memory.current": str(2 * 1024**3),
        },
    )
    assert capacity.available_bytes == 0
    assert capacity.limit_bytes == 1024**3


def test_unlimited_container_keeps_the_host_figure() -> None:
    system_capacity = _capacity_module()
    capacity = system_capacity.discover_effective_memory_capacity(
        host_available_bytes=6 * 1024**3,
        cgroup_values={"memory.max": "max", "memory.current": "0"},
    )
    assert capacity.source == "unrestricted"
    assert capacity.limit_bytes is None
    assert capacity.available_bytes == 6 * 1024**3


def test_memory_probe_without_any_source_is_explicitly_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_capacity = _capacity_module()
    monkeypatch.setattr(
        system_capacity, "_host_available_memory_bytes", lambda: None
    )
    capacity = system_capacity.discover_effective_memory_capacity(
        cgroup_values={}
    )
    assert capacity.available_bytes is None
    assert capacity.source == "unavailable"


def test_task_memory_probe_uses_the_container_remaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The inner-worker memory ceiling must follow the container, not host RAM."""

    from core import task_parallelism

    host_only = 24 * 1024**3
    container_remaining = 1536 * 1024**2
    observed: dict = {}

    class _Capacity:
        available_bytes = container_remaining

    monkeypatch.setattr(
        task_parallelism, "get_effective_memory_capacity", lambda: _Capacity()
    )
    observed["probe"] = task_parallelism._available_memory_bytes()
    assert observed["probe"] == container_remaining
    assert host_only != observed["probe"]

    plan = task_parallelism.resolve_task_parallelism_plan(
        "vector",
        work_items=8,
        hard_max_workers=None,
        estimated_worker_bytes=512 * 1024**2,
        available_memory_bytes=task_parallelism._available_memory_bytes(),
        effective_cpu_capacity=16,
        outer_demand=1,
    )
    # 1.5 GiB minus the one-GiB headroom leaves room for exactly one 512 MiB
    # worker - not the sixteen the host figure would have allowed.
    assert plan.available_memory_bytes == container_remaining
    assert plan.memory_ceiling == 1
    assert plan.workers == 1
    assert plan.limiting_reason == "memory"


def test_mesh_budget_is_capped_by_the_container_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import vector_mesh_memory

    monkeypatch.delenv("LUMINA_VECTOR_MESH_MEMORY_BUDGET_MB", raising=False)
    monkeypatch.setattr(
        vector_mesh_memory, "get_effective_memory_limit_bytes", lambda: None
    )
    monkeypatch.setattr(
        vector_mesh_memory, "current_task_host_memory_budget_bytes", lambda: None
    )
    assert (
        vector_mesh_memory.resolve_vector_mesh_memory_budget_bytes()
        == vector_mesh_memory.DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES
    )

    monkeypatch.setattr(
        vector_mesh_memory, "get_effective_memory_limit_bytes", lambda: 2 * 1024**3
    )
    assert (
        vector_mesh_memory.resolve_vector_mesh_memory_budget_bytes()
        == 2 * 1024**3
    )

    # An explicit environment override stays an upper bound, never a raise.
    monkeypatch.setenv("LUMINA_VECTOR_MESH_MEMORY_BUDGET_MB", "512")
    assert (
        vector_mesh_memory.resolve_vector_mesh_memory_budget_bytes()
        == 512 * 1024**2
    )


def test_parent_reservation_still_bounds_the_mesh_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The existing parent-task reservation must not be widened or ignored."""

    from core import vector_mesh_memory

    monkeypatch.delenv("LUMINA_VECTOR_MESH_MEMORY_BUDGET_MB", raising=False)
    monkeypatch.setattr(
        vector_mesh_memory, "get_effective_memory_limit_bytes", lambda: 2 * 1024**3
    )
    monkeypatch.setattr(
        vector_mesh_memory, "current_task_host_memory_budget_bytes", lambda: 256 * 1024**2
    )
    assert (
        vector_mesh_memory.resolve_vector_mesh_memory_budget_bytes()
        == 256 * 1024**2
    )


def test_spill_limit_follows_the_container_remaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import vector_mesh_spill

    container_remaining = 900 * 1024**2
    monkeypatch.setattr(
        vector_mesh_spill, "get_process_rss_bytes", lambda: 0
    )
    monkeypatch.setattr(
        vector_mesh_spill,
        "resolve_vector_mesh_memory_budget_bytes",
        lambda: 8 * 1024**3,
    )
    monkeypatch.setattr(
        vector_mesh_spill,
        "get_effective_memory_capacity",
        lambda: system_capacity_capacity(container_remaining),
    )
    # 900 MiB / 3 is far below the 8 GiB budget the host would have allowed.
    assert vector_mesh_spill._retained_memory_limit() == container_remaining // 3


def system_capacity_capacity(available_bytes: int | None):
    from core.system_capacity import EffectiveMemoryCapacity

    return EffectiveMemoryCapacity(
        available_bytes=available_bytes,
        limit_bytes=None,
        container_used_bytes=None,
        host_available_bytes=available_bytes,
        source="unrestricted" if available_bytes is not None else "unavailable",
    )


def test_owned_memory_report_names_the_container_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import vector_mesh_memory

    monkeypatch.setattr(
        vector_mesh_memory,
        "get_process_rss_bytes",
        lambda: 100 * 1024**2,
    )
    monkeypatch.setattr(
        vector_mesh_memory, "get_owned_process_group_rss_bytes", lambda: 700 * 1024**2
    )
    report = vector_mesh_memory.get_owned_memory_report()
    assert report["self_rss_bytes"] == 100 * 1024**2
    assert report["owned_group_rss_bytes"] == 700 * 1024**2
    assert report["container_source"] in {"cgroup_v2", "unrestricted"}
    assert "container_limit_bytes" in report


# ---------------------------------------------------------------------------
# R2: a finite limit on a visible parent cgroup bounds this process too
# ---------------------------------------------------------------------------


def _write_cgroup_memory_level(
    mount_point: Path, relative: str, *, limit: str | None, current: str | None
) -> None:
    """Write one level's memory control files inside the probe hierarchy."""

    directory = mount_point if relative in {"", "/"} else mount_point / relative
    directory.mkdir(parents=True, exist_ok=True)
    if limit is not None:
        (directory / "memory.max").write_text(f"{limit}\n", encoding="utf-8")
    if current is not None:
        (directory / "memory.current").write_text(f"{current}\n", encoding="utf-8")


def _discover_from_probe(
    system_capacity,
    *,
    cgroup_path: Path,
    mountinfo_path: Path,
    host_available: int,
):
    return system_capacity.discover_effective_memory_capacity(
        host_available_bytes=host_available,
        proc_self_cgroup_path=cgroup_path,
        proc_self_mountinfo_path=mountinfo_path,
    )


def test_parent_limit_bounds_a_child_whose_own_limit_is_max(
    tmp_path: Path,
) -> None:
    """A child writing ``max`` does not lift the parent's hard limit."""

    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup="0::/workload.scope\n",
    )
    # Parent (the mount root) is capped at 2 GiB and already holds 1.5 GiB.
    _write_cgroup_memory_level(
        mount_point, "", limit=str(2 * 1024**3), current=str(1536 * 1024**2)
    )
    # The scope this process lives in says "no limit of my own".
    _write_cgroup_memory_level(
        mount_point, "workload.scope", limit="max", current=str(128 * 1024**2)
    )

    capacity = _discover_from_probe(
        system_capacity,
        cgroup_path=cgroup_path,
        mountinfo_path=mountinfo_path,
        host_available=32 * 1024**3,
    )

    assert capacity.source == "cgroup_v2"
    assert capacity.limit_bytes == 2 * 1024**3
    # 2 GiB - 1.5 GiB is what the parent can still hand out; the child's 128 MiB
    # charge must not be subtracted from the parent's limit a second time.
    assert capacity.available_bytes == 512 * 1024**2
    assert capacity.available_bytes <= 512 * 1024**2


def test_parent_limit_wins_when_the_child_limit_is_larger(
    tmp_path: Path,
) -> None:
    """The smallest visible finite limit is the hard cap."""

    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup="0::/workload.scope\n",
    )
    _write_cgroup_memory_level(
        mount_point, "", limit=str(2 * 1024**3), current="0"
    )
    _write_cgroup_memory_level(
        mount_point, "workload.scope", limit=str(8 * 1024**3), current="0"
    )

    capacity = _discover_from_probe(
        system_capacity,
        cgroup_path=cgroup_path,
        mountinfo_path=mountinfo_path,
        host_available=32 * 1024**3,
    )

    assert capacity.source == "cgroup_v2"
    assert capacity.limit_bytes == 2 * 1024**3
    assert capacity.available_bytes == 2 * 1024**3


def test_child_limit_wins_when_it_is_the_stricter_one(
    tmp_path: Path,
) -> None:
    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup="0::/workload.scope\n",
    )
    _write_cgroup_memory_level(
        mount_point, "", limit=str(8 * 1024**3), current=str(1024**3)
    )
    _write_cgroup_memory_level(
        mount_point,
        "workload.scope",
        limit=str(1 * 1024**3),
        current=str(256 * 1024**2),
    )

    capacity = _discover_from_probe(
        system_capacity,
        cgroup_path=cgroup_path,
        mountinfo_path=mountinfo_path,
        host_available=32 * 1024**3,
    )

    assert capacity.limit_bytes == 1 * 1024**3
    assert capacity.available_bytes == 768 * 1024**2


def test_all_visible_levels_unlimited_keeps_the_host_figure(
    tmp_path: Path,
) -> None:
    """Confirmed unlimited: every visible level was read and says ``max``."""

    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup="0::/workload.scope\n",
    )
    _write_cgroup_memory_level(
        mount_point, "", limit="max", current=str(1024**3)
    )
    _write_cgroup_memory_level(
        mount_point, "workload.scope", limit="max", current=str(64 * 1024**2)
    )

    capacity = _discover_from_probe(
        system_capacity,
        cgroup_path=cgroup_path,
        mountinfo_path=mountinfo_path,
        host_available=32 * 1024**3,
    )

    assert capacity.source == "unrestricted"
    assert capacity.limit_bytes is None
    assert capacity.available_bytes == 32 * 1024**3


def test_unreadable_parent_limit_is_not_reported_as_confirmed_unlimited(
    tmp_path: Path,
) -> None:
    """A level we could not read is unknown, not proof of no limit."""

    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup="0::/workload.scope\n",
    )
    # The parent directory exists but its memory.max cannot be read; the child
    # explicitly says "no limit of my own".
    (mount_point / "workload.scope").mkdir(parents=True, exist_ok=True)
    (mount_point / "memory.current").write_text(str(1024**3), encoding="utf-8")
    _write_cgroup_memory_level(
        mount_point, "workload.scope", limit="max", current=str(64 * 1024**2)
    )

    capacity = _discover_from_probe(
        system_capacity,
        cgroup_path=cgroup_path,
        mountinfo_path=mountinfo_path,
        host_available=32 * 1024**3,
    )

    assert capacity.source == "unknown"
    # The host figure stays as the explicit fallback rather than a claim.
    assert capacity.available_bytes == 32 * 1024**3


def test_missing_memory_files_report_an_explicit_state(tmp_path: Path) -> None:
    """No readable memory level at all is reported, not assumed unlimited."""

    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, _mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup="0::/workload.scope\n",
    )

    capacity = _discover_from_probe(
        system_capacity,
        cgroup_path=cgroup_path,
        mountinfo_path=mountinfo_path,
        host_available=32 * 1024**3,
    )

    assert capacity.source == "unknown"
    assert capacity.limit_bytes is None
    assert capacity.available_bytes == 32 * 1024**3


def test_cached_limit_sees_the_parent_cap(tmp_path: Path) -> None:
    """``get_effective_memory_limit_bytes`` is the min of visible limits."""

    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup="0::/workload.scope\n",
    )
    _write_cgroup_memory_level(
        mount_point, "", limit=str(2 * 1024**3), current=str(1536 * 1024**2)
    )
    _write_cgroup_memory_level(
        mount_point, "workload.scope", limit="max", current=str(128 * 1024**2)
    )

    limit = system_capacity._read_cgroup_v2_memory_limit_bytes(
        proc_self_cgroup_path=cgroup_path,
        proc_self_mountinfo_path=mountinfo_path,
    )
    assert limit == 2 * 1024**3


def test_container_limit_does_not_escape_the_visible_mount(tmp_path: Path) -> None:
    """Ancestors above the mount root are not invented."""

    system_capacity = _capacity_module()
    cgroup_path, mountinfo_path, mount_point = _write_cgroup_v2_probe(
        tmp_path,
        process_cgroup="0::/docker/abc/workload.scope\n",
        mount_root="/docker/abc",
    )
    _write_cgroup_memory_level(
        mount_point, "", limit="max", current=str(1024**3)
    )
    _write_cgroup_memory_level(
        mount_point, "workload.scope", limit="max", current="0"
    )
    # A file outside the visible mount must not be consulted, even though it
    # sits above the namespaced path on disk.
    (mount_point.parent / "memory.max").write_text(str(512**3), encoding="utf-8")

    capacity = _discover_from_probe(
        system_capacity,
        cgroup_path=cgroup_path,
        mountinfo_path=mountinfo_path,
        host_available=32 * 1024**3,
    )

    assert capacity.source == "unrestricted"
    assert capacity.limit_bytes is None
    assert capacity.available_bytes == 32 * 1024**3
