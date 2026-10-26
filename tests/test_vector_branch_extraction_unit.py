"""Vector compatibility exports, parallelism metadata and timing diagnostics."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.task_parallelism import AdaptiveParallelismPlan

EXTRACTED_FUNCTION_NAMES: tuple[str, ...] = (
    "_update_bambu_base_layer_ctx_for_vector",
    "_run_vector_branch",
    "_run_vector_preview_branch",
    "_log_vector_timings",
)


@pytest.mark.parametrize("name", EXTRACTED_FUNCTION_NAMES)
def test_coordinator_reexports_same_object(name: str) -> None:
    """``coordinator.X`` \u548c ``vector_branch.X`` \u5fc5\u987b\u662f\u540c\u4e00\u4e2a\u51fd\u6570\u5bf9\u8c61\u3002
    ``coordinator.X`` and ``vector_branch.X`` must be the *same* function
    object so ``mock.patch("core.pipeline.coordinator.X")`` and direct
    ``coordinator.X(ctx)`` calls continue to work post-refactor.
    """
    from core.pipeline import coordinator, vector_branch

    coord_fn = getattr(coordinator, name, None)
    branch_fn = getattr(vector_branch, name, None)
    assert coord_fn is not None, f"coordinator must re-export `{name}`"
    assert branch_fn is not None, f"vector_branch must define `{name}`"
    assert coord_fn is branch_fn, (
        f"coordinator.{name} must be the same object as vector_branch.{name} "
        f"(re-export, not a wrapper)"
    )


def test_material_parallelism_plan_is_recorded_as_bounded_scalars() -> None:
    from core.pipeline.vector_branch import _record_material_parallelism

    plan = AdaptiveParallelismPlan(
        workers=2,
        requested_ceiling=4,
        effective_cpu_capacity=4,
        outer_demand=2,
        cpu_fair_share_ceiling=2,
        work_item_ceiling=40,
        work_unit_ceiling=4,
        stage_ceiling=4,
        limiting_reason="cpu_fair_share",
        demand_snapshot_fallback=False,
        cpu_topology="heterogeneous",
        cpu_scheduling_policy="os_core_type_scheduler",
        performance_cpu_capacity=4,
    )
    processor = SimpleNamespace(
        img_processor=SimpleNamespace(
            effective_parallelism_workers=2,
            effective_parallelism_plan=plan,
        ),
    )
    timings: dict = {}

    _record_material_parallelism(timings, processor)

    assert timings == {
        "material_parallelism_workers": 2.0,
        "material_parallelism_limit": "cpu_fair_share",
        "material_parallelism_effective_cpu": 4.0,
        "material_parallelism_cpu_topology": "heterogeneous",
        "material_parallelism_cpu_scheduling_policy": (
            "os_core_type_scheduler"
        ),
        "material_parallelism_performance_cpu": 4.0,
        "material_parallelism_outer_demand": 2.0,
        "material_parallelism_cpu_fair_share": 2.0,
        "material_parallelism_demand_fallback": False,
    }


def test_material_parallelism_legacy_processor_still_records_workers() -> None:
    from core.pipeline.vector_branch import _record_material_parallelism

    processor = SimpleNamespace(
        img_processor=SimpleNamespace(effective_parallelism_workers=3),
    )
    timings: dict = {}

    _record_material_parallelism(timings, processor)

    assert timings == {"material_parallelism_workers": 3.0}


def test_vector_timing_logging_preserves_string_and_boolean_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.pipeline import vector_branch

    calls: list[tuple[str, dict]] = []

    class _RecordingLogger:
        def debug(self, _message: str, *args, extra: dict, **kwargs) -> None:
            del args, kwargs
            calls.append(("debug", extra))

        def info(self, _message: str, *args, extra: dict, **kwargs) -> None:
            del args, kwargs
            calls.append(("info", extra))

    monkeypatch.setattr(vector_branch, "log", _RecordingLogger())

    vector_branch._log_vector_timings(
        {
            "vector_branch_total_s": 1.25,
            "material_parallelism_limit": "cpu_fair_share",
            "material_parallelism_demand_fallback": False,
        }
    )

    assert len(calls) == 2
    for _level, extra in calls:
        assert extra["timings"]["material_parallelism_limit"] == "cpu_fair_share"
        assert extra["timings"]["material_parallelism_demand_fallback"] is False
