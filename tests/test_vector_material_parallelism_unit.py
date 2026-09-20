"""Materialization ordering, ownership and concurrency contracts."""

from __future__ import annotations

import numpy as np
import pytest
import os
from pathlib import Path
from types import SimpleNamespace
from shapely import get_precision, set_precision
from shapely.geometry import box

from core import vector_engine
from core.vector_engine import VectorProcessor
from core.vector_layer_geometry import VectorLayerGeometryPolicy


def _slots() -> dict:
    return {
        name: {"mat_id": index, "slabs": [
            {"geometry": box(index * 3, 0, index * 3 + 2, 2),
             "height": 0.16, "z_offset": 0.0}
        ]}
        for index, name in enumerate(("Blue", "White", "Red"))
    }


def test_serial_materialization_preserves_slots_and_releases_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "1")
    slots = _slots()
    slots["unused"] = {"mat_id": 9, "slabs": []}
    result = VectorProcessor._materialize_vector_slabs(slots, scale_factor=1.0)
    assert list(result) == ["Blue", "White", "Red"]
    assert [v["mat_id"] for v in result.values()] == [0, 1, 2]
    assert all(not data["slabs"] for data in slots.values())
    for data in result.values():
        mesh = data["meshes"][0]
        assert mesh.is_watertight
        assert mesh.volume == pytest.approx(0.64)


def test_none_mesh_is_omitted_and_policy_is_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "1")
    slots = _slots()
    policy = VectorLayerGeometryPolicy(grid_mm=0.001)
    seen = []

    def build(slabs, **kwargs):
        seen.append(kwargs)
        return None

    monkeypatch.setattr(vector_engine, "build_vector_layered_volume", build)
    assert VectorProcessor._materialize_vector_slabs(
        slots, scale_factor=0.5, geometry_policy=policy,
    ) == {}
    assert len(seen) == 3
    assert all(item == {"scale_mm_per_svg_unit": 0.5, "policy": policy} for item in seen)
    assert all(not data["slabs"] for data in slots.values())


def test_memory_error_is_not_retried_or_returned_as_partial_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "1")
    calls = []

    def fail(slabs, **kwargs):
        calls.append(slabs)
        raise MemoryError("allocation budget")

    slots = _slots()
    monkeypatch.setattr(vector_engine, "build_vector_layered_volume", fail)
    with pytest.raises(MemoryError, match="allocation budget"):
        VectorProcessor._materialize_vector_slabs(slots, scale_factor=1.0)
    assert len(calls) == 1
    assert all(data["slabs"] for data in slots.values())


def _force_process_plan(monkeypatch: pytest.MonkeyPatch, workers: int = 2):
    from core import vector_material_meshing as materializer

    monkeypatch.setattr(
        materializer, "resolve_task_parallelism_plan",
        lambda *args, **kwargs: SimpleNamespace(
            workers=workers, limiting_reason="test", outer_demand=1,
        ),
    )
    monkeypatch.setattr(materializer, "get_process_rss_bytes", lambda: 100 * 1024**2)
    monkeypatch.setattr(materializer, "resolve_vector_mesh_memory_budget_bytes", lambda: 8 * 1024**3)
    return materializer


def test_process_materialization_is_exact_ordered_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import tempfile

    materializer = _force_process_plan(monkeypatch)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    source = _slots()
    expected = {
        name: vector_engine.build_vector_layered_volume(
            data["slabs"], scale_mm_per_svg_unit=1.0,
        ) for name, data in source.items()
    }
    timings = {}
    actual = materializer.materialize_material_meshes(
        source, scale_factor=1.0, geometry_policy=None,
        serial_builder=vector_engine.build_vector_layered_volume, timings=timings,
    )
    assert list(actual) == list(expected)
    for name, mesh in expected.items():
        result = actual[name]["meshes"][0]
        np.testing.assert_array_equal(result.vertices, mesh.vertices)
        np.testing.assert_array_equal(result.faces, mesh.faces)
        assert result.metadata == mesh.metadata
    assert timings["materialize_parallelism_workers"] == 2
    assert timings["materialize_process_count"] >= 1
    assert all(not v["slabs"] for v in source.values())
    assert not list(tmp_path.glob("lumina-vector-material-*"))


def test_worker_error_propagates_without_partial_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import tempfile

    materializer = _force_process_plan(monkeypatch)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    slots = _slots()
    slots["Blue"]["slabs"][0]["height"] = "invalid"
    with pytest.raises(ValueError, match="invalid height"):
        materializer.materialize_material_meshes(
            slots, scale_factor=1.0, geometry_policy=None,
            serial_builder=vector_engine.build_vector_layered_volume,
        )
    assert all(v["slabs"] for v in slots.values())
    assert not list(tmp_path.glob("lumina-vector-material-*"))


def test_task_memory_cap_prevents_process_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    materializer = _force_process_plan(monkeypatch, workers=8)
    monkeypatch.setattr(materializer, "resolve_vector_mesh_memory_budget_bytes", lambda: 110 * 1024**2)
    monkeypatch.setattr(materializer, "ProcessPoolExecutor", lambda **kwargs: pytest.fail("budget exceeded"))
    timings = {}
    result = materializer.materialize_material_meshes(
        _slots(), scale_factor=1.0, geometry_policy=None,
        serial_builder=vector_engine.build_vector_layered_volume, timings=timings,
    )
    assert len(result) == 3
    assert timings["materialize_parallelism_workers"] == 1
    assert timings["materialize_parallelism_limit"] == "vector_memory_budget"


def test_geometry_transport_preserves_precision_and_coordinates(tmp_path: Path) -> None:
    from core import vector_material_meshing as materializer

    shape = set_precision(box(0.125, 0.25, 3.125, 4.25), 0.125)
    path = tmp_path / "input.json"
    materializer._write_material_input(path, [
        {"geometry": shape, "height": 0.16, "z_offset": 0.08},
    ])
    loaded = materializer._read_material_input(path)[0]
    assert loaded["geometry"].wkb == shape.wkb
    assert get_precision(loaded["geometry"]) == get_precision(shape)
    assert loaded["height"] == 0.16
    assert loaded["z_offset"] == 0.08


def test_small_work_and_nested_worker_never_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    from core import vector_material_meshing as materializer
    from core.task_parallelism import task_parallelism_worker_scope

    monkeypatch.setattr(materializer, "ProcessPoolExecutor", lambda **kw: pytest.fail("unexpected pool"))
    for nested in (False, True):
        timings = {}
        from contextlib import nullcontext
        with task_parallelism_worker_scope() if nested else nullcontext():
            result = materializer.materialize_material_meshes(
                _slots(), scale_factor=1.0, geometry_policy=None,
                serial_builder=vector_engine.build_vector_layered_volume, timings=timings,
            )
        assert len(result) == 3
        assert timings["materialize_parallelism_workers"] == 1


def test_aliased_slab_lists_retain_serial_consumption(monkeypatch: pytest.MonkeyPatch) -> None:
    materializer = _force_process_plan(monkeypatch)
    slots = _slots()
    slots["White"]["slabs"] = slots["Blue"]["slabs"]
    result = materializer.materialize_material_meshes(
        slots, scale_factor=1.0, geometry_policy=None,
        serial_builder=vector_engine.build_vector_layered_volume,
    )
    assert list(result) == ["Blue", "Red"]


def test_generator_input_is_not_consumed_by_planning() -> None:
    slots = _slots()
    slabs = slots["Blue"]["slabs"]
    slots["Blue"]["slabs"] = (item for item in slabs)
    result = VectorProcessor._materialize_vector_slabs(slots, scale_factor=1.0)
    assert len(result) == 3


@pytest.mark.parametrize("cpus", [1, 2, 4, 10, 16, 20, 32])
@pytest.mark.parametrize("outer_demand", [1, 4])
def test_material_budget_adapts_to_device_and_concurrent_tasks(
    monkeypatch: pytest.MonkeyPatch, cpus: int, outer_demand: int,
) -> None:
    from functools import partial
    from core import vector_material_meshing as materializer

    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "auto")
    monkeypatch.setattr(materializer, "_coordinate_counts", lambda items: [100_000] * len(items))
    monkeypatch.setattr(materializer, "resolve_task_parallelism_plan", partial(
        materializer.resolve_task_parallelism_plan, effective_cpu_capacity=cpus,
        outer_demand=outer_demand, available_memory_bytes=64 * 1024**3,
    ))
    monkeypatch.setattr(materializer, "get_process_rss_bytes", lambda: 100 * 1024**2)
    monkeypatch.setattr(materializer, "resolve_vector_mesh_memory_budget_bytes", lambda: 16 * 1024**3)
    items = [(str(i), {"slabs": [i]}) for i in range(12)]
    workers, _reason, _bytes, plan = materializer._worker_budget(
        items, vector_engine.build_vector_layered_volume, None,
    )
    assert workers == min(12, max(1, cpus // outer_demand))
    # The plan travels back so the lease admission can use the same effective
    # CPU capacity the static plan did, instead of re-discovering it.
    assert plan.effective_cpu_capacity == cpus


def test_unavailable_process_monitor_falls_back_to_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    materializer = _force_process_plan(monkeypatch)

    def fail_open(self):
        raise OSError("process creation unavailable")

    monkeypatch.setattr(materializer.MaterialProcessLifetime, "open", fail_open)
    monkeypatch.setattr(materializer, "ProcessPoolExecutor", lambda **kw: pytest.fail("unexpected pool"))
    timings = {}
    assert len(materializer.materialize_material_meshes(
        _slots(), scale_factor=1.0, geometry_policy=None,
        serial_builder=vector_engine.build_vector_layered_volume, timings=timings,
    )) == 3
    assert timings["materialize_parallelism_workers"] == 1
    assert timings["materialize_parallelism_limit"] == "process_ownership_unavailable"


def test_parent_termination_kills_material_child(tmp_path: Path) -> None:
    import subprocess
    import sys
    import time
    import psutil
    from core.material_process_lifetime import _process_alive

    script = tmp_path / "parent.py"
    script.write_text('''
import os, sys, time, multiprocessing, ctypes, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from core.material_process_lifetime import MaterialProcessLifetime, attach_material_worker
def child(name, parent, ready):
    attach_material_worker(name, parent)
    Path(ready).write_text(str(os.getpid()), encoding="utf-8")
    if os.name == "nt":
        ctypes.PyDLL("kernel32").Sleep(60000)
    else:
        ctypes.PyDLL(None).sleep(60)
if __name__ == "__main__":
    owner = MaterialProcessLifetime()
    owner.open()
    data = tempfile.mkdtemp(prefix="lumina-vector-material-", dir=Path(owner.name).parent)
    owner.track_data_directory(data)
    Path(sys.argv[2] + ".owner").write_text(owner.name + "\\n" + data, encoding="utf-8")
    p = multiprocessing.get_context("spawn").Process(target=child, args=(owner.name, os.getpid(), sys.argv[2]))
    p.start()
    p.join()
''', encoding="utf-8")
    ready = tmp_path / "child.pid"
    parent = subprocess.Popen(
        [sys.executable, str(script), str(Path(__file__).resolve().parents[1]), str(ready)],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    child = None
    created = 0.0
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        child = psutil.Process(int(ready.read_text(encoding="utf-8")))
        created = child.create_time()
        parent.terminate()
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        while _process_alive(child.pid, created) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _process_alive(child.pid, created)
        directories = Path(str(ready) + ".owner").read_text(encoding="utf-8").splitlines()
        deadline = time.monotonic() + 10
        while any(Path(p).exists() for p in directories) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert all(not Path(p).exists() for p in directories)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        if child is not None and _process_alive(child.pid, created):
            child.kill()
            child.wait(timeout=5)
