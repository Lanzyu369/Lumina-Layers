"""Bounded-memory contracts for Vector mesh generation."""

from __future__ import annotations

import pickle

import numpy as np
import pytest
from PIL import Image

from core.errors import VectorMeshMemoryBudgetError
from core.vector_mesh_memory import (
    DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES,
    MATERIAL_WORKER_PROCESS_BASE_BYTES,
    enforce_vector_mesh_memory_budget,
    estimate_indexed_prism_memory,
    estimate_material_archive_runtime_bytes,
    estimate_vector_material_parallel_memory_target_bytes,
    estimate_vector_task_memory_reservation_bytes,
    estimate_vector_mesh_build_memory,
    resolve_vector_mesh_memory_budget_bytes,
)
from core.task_parallelism_runtime import task_host_memory_budget_scope


def test_memory_budget_error_is_structured_and_actionable() -> None:
    """Unsafe work fails before OOM with a stable recoverable error contract."""

    with pytest.raises(VectorMeshMemoryBudgetError) as raised:
        enforce_vector_mesh_memory_budget(
            stage="preflight",
            estimated_additional_bytes=900,
            memory_budget_bytes=1_000,
            current_rss_bytes=200,
            shape_count=42,
            coordinate_count=4_200,
        )

    error = raised.value
    assert error.code == "vector_mesh_memory_budget_exceeded"
    assert error.stage == "preflight"
    assert error.estimated_peak_bytes == 1_100
    assert error.memory_budget_bytes == 1_000
    assert error.recoverable is True
    assert "memory" in str(error).lower()
    assert "too complex" not in str(error).lower()


def test_memory_budget_accepts_work_that_fits() -> None:
    report = enforce_vector_mesh_memory_budget(
        stage="preflight",
        estimated_additional_bytes=700,
        memory_budget_bytes=1_000,
        current_rss_bytes=200,
        shape_count=4,
        coordinate_count=40,
    )

    assert report.estimated_peak_bytes == 900
    assert report.is_allowed is True


def test_parent_host_reservation_tightens_worker_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pool-assigned cap bounds every later build/export memory guard."""

    monkeypatch.delenv("LUMINA_VECTOR_MESH_MEMORY_BUDGET_MB", raising=False)
    assert (
        resolve_vector_mesh_memory_budget_bytes()
        == DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES
    )
    with task_host_memory_budget_scope(512):
        assert resolve_vector_mesh_memory_budget_bytes() == 512
    assert (
        resolve_vector_mesh_memory_budget_bytes()
        == DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES
    )


def test_small_svg_task_reservation_uses_artifact_complexity(
    tmp_path,
) -> None:
    """A real-size small SVG must not reserve the full 8 GiB ceiling."""

    mib = 1024**2
    gib = 1024**3
    source_path = tmp_path / "source.svg"
    source_path.write_bytes(b"x" * (2 * mib))
    parse_cache_path = tmp_path / "parse-cache.pkl"
    parse_cache_path.write_bytes(b"x" * (3 * mib // 2))

    preview_bytes = estimate_vector_task_memory_reservation_bytes(
        source_path,
    )
    generate_bytes = estimate_vector_task_memory_reservation_bytes(
        source_path,
        supporting_paths=(parse_cache_path,),
    )

    assert 768 * mib < preview_bytes < generate_bytes
    assert generate_bytes < 5 * gib // 4
    assert generate_bytes < DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES


def test_material_archive_reservation_is_estimated_not_full_cap(tmp_path) -> None:
    """Implicit material state adds a bounded cost instead of forcing 8 GiB."""

    source_path = tmp_path / "source.svg"
    source_path.write_bytes(b"x" * (2 * 1024**2))
    implicit_bytes = estimate_material_archive_runtime_bytes(8)

    reservation = estimate_vector_task_memory_reservation_bytes(
        source_path,
        implicit_resident_bytes=implicit_bytes,
    )

    assert implicit_bytes > 0
    assert reservation < 2 * 1024**3
    assert reservation < DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES


def test_large_svg_task_reservation_scales_without_exceeding_cap(
    tmp_path,
) -> None:
    """Historical 55 MiB-class SVGs retain a multi-GiB safety promise."""

    source_path = tmp_path / "large.svg"
    with source_path.open("wb") as handle:
        handle.truncate(55 * 1024**2)

    reservation = estimate_vector_task_memory_reservation_bytes(source_path)

    assert reservation >= 4 * 1024**3
    assert reservation <= DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES


def test_large_resident_auxiliary_artifact_expands_task_reservation(
    tmp_path,
) -> None:
    """Large model/cache inputs must be represented in the worker hard cap."""

    source_path = tmp_path / "source.svg"
    source_path.write_text("<svg/>", encoding="utf-8")
    typical_model_path = tmp_path / "typical.stl"
    large_model_path = tmp_path / "large.stl"
    with typical_model_path.open("wb") as handle:
        handle.truncate(13 * 1024**2)
    with large_model_path.open("wb") as handle:
        handle.truncate(64 * 1024**2)

    source_only = estimate_vector_task_memory_reservation_bytes(source_path)
    typical_model = estimate_vector_task_memory_reservation_bytes(
        source_path,
        resident_paths=(typical_model_path,),
    )
    large_model = estimate_vector_task_memory_reservation_bytes(
        source_path,
        resident_paths=(large_model_path,),
    )

    assert typical_model == source_only
    assert large_model > 2 * 1024**3
    assert large_model < DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES


def test_unknown_vector_source_reservation_fails_closed(tmp_path) -> None:
    """Missing and unsupported sources retain the configured worst-case cap."""

    assert (
        estimate_vector_task_memory_reservation_bytes(
            tmp_path / "missing.svg",
        )
        == DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES
    )
    unsupported_path = tmp_path / "source.bin"
    unsupported_path.write_bytes(b"data")
    assert (
        estimate_vector_task_memory_reservation_bytes(unsupported_path)
        == DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES
    )
    source_path = tmp_path / "source.svg"
    source_path.write_text("<svg/>", encoding="utf-8")
    assert (
        estimate_vector_task_memory_reservation_bytes(
            source_path,
            resident_paths=(tmp_path / "missing-model.stl",),
        )
        == DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES
    )


def test_rasterized_svg_fallback_uses_decoded_pixel_cost(tmp_path) -> None:
    raster_path = tmp_path / "fallback.png"
    Image.new("RGBA", (800, 400), (0, 0, 0, 0)).save(raster_path)

    reservation = estimate_vector_task_memory_reservation_bytes(raster_path)

    assert 768 * 1024**2 < reservation < 2 * 1024**3
    assert reservation < DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES


def test_memory_budget_error_survives_process_pool_serialization() -> None:
    """Worker admission diagnostics must reach the API process intact."""

    error = VectorMeshMemoryBudgetError(
        "assemble",
        9 * 1024**3,
        8 * 1024**3,
        7 * 1024**3,
        42,
        4_200,
    )

    restored = pickle.loads(pickle.dumps(error))

    assert isinstance(restored, VectorMeshMemoryBudgetError)
    assert restored.stage == "assemble"
    assert restored.estimated_peak_bytes == 9 * 1024**3
    assert restored.memory_budget_bytes == 8 * 1024**3
    assert restored.shape_count == 42
    assert restored.coordinate_count == 4_200
    assert str(restored) == str(error)


def test_build_estimate_accounts_for_run_multiplicity_and_double_sided_output() -> None:
    shapes = [
        {
            "geometry": _CoordinateCountGeometry(100),
            "recipe": [0, 1, 0, 1],
        },
        {
            "geometry": _CoordinateCountGeometry(50),
            "recipe": [0, 0, 1, 1],
        },
    ]

    single = estimate_vector_mesh_build_memory(
        shapes,
        num_layers=4,
        double_sided=False,
        spatial_group_chunk_bytes=0,
    )
    double = estimate_vector_mesh_build_memory(
        shapes,
        num_layers=4,
        double_sided=True,
        spatial_group_chunk_bytes=0,
    )

    assert single.shape_count == 2
    assert single.coordinate_count == 150
    assert single.run_count == 6
    assert single.run_coordinate_references == 500
    assert double.run_coordinate_references == 1_000
    assert (
        double.estimated_final_mesh_bytes
        > single.estimated_final_mesh_bytes
    )


def test_build_estimate_accounts_for_backing_coating_and_preparation() -> None:
    estimate = estimate_vector_mesh_build_memory(
        [],
        num_layers=4,
        double_sided=False,
        spatial_group_chunk_bytes=0,
        auxiliary_geometries=[_CoordinateCountGeometry(10_000)],
        auxiliary_run_count=3,
    )

    assert estimate.coordinate_count == 0
    assert estimate.auxiliary_coordinate_count == 10_000
    assert estimate.auxiliary_coordinate_references == 30_000
    assert estimate.largest_prepared_group_coordinate_count == 10_000
    assert estimate.estimated_preparation_bytes > 0
    assert estimate.estimated_final_mesh_bytes > 0


def test_indexed_prism_estimate_uses_exact_canonical_counts() -> None:
    estimate = estimate_indexed_prism_memory(
        coordinate_count=1_000,
        hole_count=3,
        component_count=4,
    )

    assert estimate.vertex_count == 2_000
    assert estimate.face_count == 4_000 + 4 * 3 - 4 * 4
    assert estimate.mesh_array_bytes == (
        estimate.vertex_count * 3 * 8 + estimate.face_count * 3 * 8
    )
    assert estimate.writer_array_bytes == (
        estimate.vertex_count * 3 * 4 + estimate.face_count * 3 * 4
    )
    assert estimate.estimated_additional_bytes > estimate.mesh_array_bytes


def test_build_estimate_scales_preparation_with_largest_group() -> None:
    estimate = estimate_vector_mesh_build_memory(
        [
            {
                "geometry": _CoordinateCountGeometry(12_000_000),
                "recipe": [0],
            }
        ],
        num_layers=1,
        double_sided=False,
        spatial_group_chunk_bytes=0,
    )

    assert estimate.largest_prepared_group_coordinate_count == 12_000_000
    assert estimate.estimated_preparation_bytes > 3 * 1024**3


class _CoordinateCountGeometry:
    """Tiny fixture that exposes complexity without allocating coordinates."""

    def __init__(self, coordinate_count: int) -> None:
        self.coordinate_count = int(coordinate_count)


# ---------------------------------------------------------------------------
# R3: the material stage's parallel working set as a task reservation
#
# The stage decides how many builders it may start from its own live budget, so
# a reservation sized only for the serial pipeline leaves every resource-rich
# device serial. These tests pin the estimator that turns the source's known
# scale and the selected material count into the budget the stage needs.
# ---------------------------------------------------------------------------


def _write_dense_svg(path, target_bytes: int):
    """Write a well-formed SVG whose path data is close to ``target_bytes``."""

    prefix = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
        '<path d="M 0 0'
    )
    suffix = ' Z"/></svg>'
    points = max(1, (target_bytes - len(prefix) - len(suffix)) // 8)
    body = "".join(f" L {index % 997} {index % 991}" for index in range(points))
    path.write_text(prefix + body + suffix, encoding="utf-8")
    return path


def test_material_parallel_target_covers_the_builders_a_source_can_use(
    tmp_path,
) -> None:
    """A dense multi-material source asks for its builders' working set."""

    source = _write_dense_svg(tmp_path / "dense.svg", 3_803_242)
    required = estimate_vector_task_memory_reservation_bytes(source)
    target = estimate_vector_material_parallel_memory_target_bytes(
        source, material_count=12
    )

    assert target is not None
    assert target > required
    # Builders the work can keep busy at the stage's own work density, each at
    # the process base the stage charges, plus the coordinate working set the
    # reservation's expansion implies. Fewer than one per material is enough
    # for this source, and the request never exceeds the configured ceiling.
    assert target - required >= 9 * MATERIAL_WORKER_PROCESS_BASE_BYTES
    assert target - required < 12 * MATERIAL_WORKER_PROCESS_BASE_BYTES + 1024**3


def test_material_parallel_target_is_absent_when_nothing_can_be_gained(
    tmp_path,
) -> None:
    """One material, an unknown source, or a missing file asks for nothing."""

    source = _write_dense_svg(tmp_path / "dense.svg", 4096)

    assert (
        estimate_vector_material_parallel_memory_target_bytes(
            source, material_count=1
        )
        is None
    )
    assert (
        estimate_vector_material_parallel_memory_target_bytes(
            source, material_count=0
        )
        is None
    )
    assert (
        estimate_vector_material_parallel_memory_target_bytes(
            tmp_path / "missing.svg", material_count=12
        )
        is None
    )
    raster = tmp_path / "cut.png"
    Image.new("L", (8, 8)).save(raster)
    assert (
        estimate_vector_material_parallel_memory_target_bytes(
            raster, material_count=12
        )
        is None
    )
    # Below the coordinates at which the stage starts workers at all, the same
    # source asks for nothing: the reservation stays with tasks that can use it.
    assert (
        estimate_vector_material_parallel_memory_target_bytes(
            source, material_count=12
        )
        is None
    )


def test_material_parallel_target_respects_the_configured_ceiling(tmp_path) -> None:
    """The request never exceeds the configured or container cap."""

    ceiling = 3 * 1024**3
    source = _write_dense_svg(tmp_path / "dense.svg", 3_803_242)

    target = estimate_vector_material_parallel_memory_target_bytes(
        source, material_count=12, memory_budget_bytes=ceiling
    )

    assert target == ceiling
