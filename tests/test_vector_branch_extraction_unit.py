"""vector_branch 抽取后的契约测试 (Phase 0 Sub-PR D).
Vector-branch extraction contract tests (Phase 0 Sub-PR D).

These tests pin the post-refactor invariants so the file move from
``core/pipeline/coordinator.py`` to ``core/pipeline/vector_branch.py`` cannot
silently break callers that import via the old ``coordinator.X`` attribute
path or ``mock.patch("core.pipeline.coordinator.X")``.

Coverage:
- The four extracted callables live in ``core.pipeline.vector_branch``.
- ``coordinator`` re-exports the *same* function objects (identity check) so
  tests / production code touching ``coordinator._run_vector_branch`` etc.
  continue to work without modification.
- Coordinator's call sites still resolve to the relocated callables (verified
  via ``inspect.getsourcefile``).

Per design doc \u00a714.3.D: pickle-based deep-equality on a synthetic SVG run
is intentionally avoided here because the extraction is a pure file move with
zero behavioral delta; the existing high-fidelity behavioral tests cover the
runtime contract:

- ``tests/test_vector_matched_rgb_overrides_unit.py`` — exercises
  ``_run_vector_branch`` end-to-end with a fake VectorProcessor.
- ``tests/test_pipeline_bambu_base_layer_ctx_unit.py`` — exercises
  ``_update_bambu_base_layer_ctx_for_vector`` plus a full
  ``_run_vector_branch`` invocation.
- ``tests/test_coordinator_properties.py`` — patches
  ``core.pipeline.coordinator._run_vector_preview_branch`` to assert
  routing.
"""

from __future__ import annotations

import inspect
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
def test_function_lives_in_vector_branch_module(name: str) -> None:
    """\u88ab\u62bd\u53d6\u7684\u51fd\u6570\u5fc5\u987b\u53ef\u4ece ``core.pipeline.vector_branch`` \u5bfc\u5165\u3002
    Each extracted callable must now reside in ``core.pipeline.vector_branch``.
    """
    from core.pipeline import vector_branch

    fn = getattr(vector_branch, name, None)
    assert callable(fn), (
        f"`{name}` must be defined in core.pipeline.vector_branch after Phase 0 Sub-PR D"
    )
    source_file = inspect.getsourcefile(fn) or ""
    assert source_file.endswith("vector_branch.py"), (
        f"`{name}` must physically live in vector_branch.py "
        f"(found in {source_file!r})"
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


def test_coordinator_call_sites_resolve_to_vector_branch() -> None:
    """coordinator \u7684 raster/preview \u5165\u53e3\u5728\u8c03\u7528\u70b9\u5fc5\u987b\u8d70\u8fdb vector_branch \u7684\u5b9e\u73b0\u3002
    The raster + preview entry points must dispatch to the relocated
    callables (not a stale local copy).
    """
    from core.pipeline import coordinator
    from core.pipeline import vector_branch

    raster_src = inspect.getsource(coordinator.run_raster_pipeline)
    preview_src = inspect.getsource(coordinator.run_preview_pipeline)
    assert "_run_vector_branch" in raster_src
    assert "_run_vector_preview_branch" in preview_src

    # The names that the call sites resolve to (via the module's globals)
    # must point at the vector_branch implementations.
    assert coordinator.__dict__["_run_vector_branch"] is vector_branch._run_vector_branch
    assert coordinator.__dict__["_run_vector_preview_branch"] is vector_branch._run_vector_preview_branch


def test_normalize_color_replacements_input_stays_in_s03() -> None:
    """``_normalize_color_replacements_input`` \u4ecd\u7136\u4f4d\u4e8e ``s03_color_replacement``\u3002
    Pin: this helper is shared with workers/converter and MUST NOT migrate.
    """
    from core.pipeline import s03_color_replacement

    assert hasattr(s03_color_replacement, "_normalize_color_replacements_input")
    fn = s03_color_replacement._normalize_color_replacements_input
    source_file = inspect.getsourcefile(fn) or ""
    assert source_file.endswith("s03_color_replacement.py")


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
        memory_ceiling=3,
        available_memory_bytes=8 * 1024**3,
        estimated_worker_bytes=256 * 1024**2,
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
        "material_parallelism_memory_ceiling": 3.0,
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
