"""Bounded-memory policy for native Vector mesh generation.

原生矢量网格生成的有界内存策略。
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from core.errors import VectorMeshMemoryBudgetError
from core.system_capacity import get_effective_memory_limit_bytes
from core.task_parallelism_runtime import current_task_host_memory_budget_bytes


DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES = 8 * 1024 * 1024 * 1024
_VECTOR_MESH_MEMORY_BUDGET_ENV = "LUMINA_VECTOR_MESH_MEMORY_BUDGET_MB"
_VECTOR_MESH_FIXED_WORKING_BYTES = 128 * 1024 * 1024
_VECTOR_MESH_BYTES_PER_RUN_COORDINATE = 144
_VECTOR_MESH_BYTES_PER_SOURCE_COORDINATE = 64
_VECTOR_TASK_RESERVATION_BASE_BYTES = 768 * 1024**2
_VECTOR_TASK_RESERVATION_BYTES_PER_ARTIFACT_BYTE = 64
_VECTOR_TASK_RESERVATION_BYTES_PER_RASTER_BYTE = 16
_VECTOR_TASK_INCLUDED_RESIDENT_BYTES = 16 * 1024**2
_VECTOR_TASK_BYTES_PER_EXCESS_RESIDENT_BYTE = 32
_VECTOR_TASK_MATERIAL_ARCHIVE_BASE_BYTES = 256 * 1024**2
_VECTOR_TASK_MATERIAL_ARCHIVE_BYTES_PER_MATERIAL = 32 * 1024**2

# Material-stage cost model. These are the numbers the stage's own budget
# arithmetic uses, kept in the module that owns memory policy so a task
# reservation and the stage it funds cannot drift apart.
# 材质阶段成本模型：与材质阶段自身的预算算法共用同一组常数，放在拥有内存策略的
# 模块里，使任务预留与它所资助的阶段不会各自漂移。
MATERIAL_WORKER_PROCESS_BASE_BYTES = 256 * 1024**2
MATERIAL_MONITOR_BASE_BYTES = 128 * 1024**2
MATERIAL_WORKER_WORKING_BYTES_PER_COORDINATE = 1024
MATERIAL_OUTPUT_RETAINED_BYTES_PER_COORDINATE = 384
MIN_PARALLEL_MATERIAL_COORDINATES = 131_072
MATERIAL_COORDINATES_PER_WORKER = 65_536


@dataclass(frozen=True)
class VectorMeshMemoryBudgetReport:
    """Scalar result of one Vector mesh memory admission check.

    单次矢量网格内存准入检查的标量结果。
    """

    stage: str
    estimated_additional_bytes: int
    estimated_peak_bytes: int
    memory_budget_bytes: int
    current_rss_bytes: int
    shape_count: int
    coordinate_count: int
    is_allowed: bool


@dataclass(frozen=True)
class VectorMeshBuildMemoryEstimate:
    """Conservative scalar complexity estimate before 3D allocation.

    三维分配前的保守标量复杂度估算。
    """

    shape_count: int
    coordinate_count: int
    auxiliary_coordinate_count: int
    run_count: int
    run_coordinate_references: int
    auxiliary_coordinate_references: int
    largest_prepared_group_coordinate_count: int
    estimated_final_mesh_bytes: int
    estimated_preparation_bytes: int


@dataclass(frozen=True)
class IndexedPrismMemoryEstimate:
    """Exact array counts and conservative workspace for one canonical prism.

    单个规范棱柱的精确数组计数与保守工作区估算。
    """

    coordinate_count: int
    hole_count: int
    component_count: int
    vertex_count: int
    face_count: int
    mesh_array_bytes: int
    writer_array_bytes: int
    topology_working_bytes: int
    estimated_additional_bytes: int


def estimate_indexed_prism_memory(
    *,
    coordinate_count: int,
    hole_count: int,
    component_count: int,
) -> IndexedPrismMemoryEstimate:
    """Estimate one direct extrusion from its canonical ring counts.

    根据规范环的实际计数估算一次直接挤出的内存。顶点数和三角面数与
    预分配公式与分层索引棱柱构建器完全相同。
    """

    coordinates = max(0, int(coordinate_count))
    holes = max(0, int(hole_count))
    components = max(0, int(component_count))
    if coordinates == 0 or components == 0:
        return IndexedPrismMemoryEstimate(
            coordinate_count=coordinates,
            hole_count=holes,
            component_count=components,
            vertex_count=0,
            face_count=0,
            mesh_array_bytes=0,
            writer_array_bytes=0,
            topology_working_bytes=0,
            estimated_additional_bytes=_VECTOR_MESH_FIXED_WORKING_BYTES,
        )

    vertex_count = 2 * coordinates
    face_count = max(0, 4 * coordinates + 4 * holes - 4 * components)
    mesh_array_bytes = vertex_count * 3 * 8 + face_count * 3 * 8
    writer_array_bytes = vertex_count * 3 * 4 + face_count * 3 * 4
    # Cap validation is performed one polygon at a time. This allowance covers
    # triangle coordinate gathers, edge sorting/counts, and GEOS/Earcut output
    # without pretending those buffers are retained after the group finishes.
    cap_face_count = max(0, coordinates + 2 * holes - 2 * components)
    topology_working_bytes = max(
        16 * 1024**2,
        coordinates * 64 + cap_face_count * 256,
    )
    estimated_additional_bytes = (
        mesh_array_bytes + writer_array_bytes + topology_working_bytes
    )
    return IndexedPrismMemoryEstimate(
        coordinate_count=coordinates,
        hole_count=holes,
        component_count=components,
        vertex_count=vertex_count,
        face_count=face_count,
        mesh_array_bytes=mesh_array_bytes,
        writer_array_bytes=writer_array_bytes,
        topology_working_bytes=topology_working_bytes,
        estimated_additional_bytes=estimated_additional_bytes,
    )


def estimate_material_archive_runtime_bytes(material_count: int) -> int:
    """Return parent-visible resident cost for implicit material runtimes.

    返回父进程可预估的耗材档案隐式运行时常驻成本。
    """

    count = max(0, int(material_count))
    return (
        _VECTOR_TASK_MATERIAL_ARCHIVE_BASE_BYTES
        + count * _VECTOR_TASK_MATERIAL_ARCHIVE_BYTES_PER_MATERIAL
    )


def _geometry_coordinate_count(geometry) -> int:
    explicit_count = getattr(geometry, "coordinate_count", None)
    if explicit_count is not None:
        try:
            return max(0, int(explicit_count))
        except (TypeError, ValueError, OverflowError):
            return 0

    try:
        from shapely import get_num_coordinates  # type: ignore[attr-defined]

        return max(0, int(get_num_coordinates(geometry)))
    except (ImportError, AttributeError, TypeError, ValueError, OverflowError):
        pass

    try:
        parts = (
            tuple(geometry.geoms)
            if getattr(geometry, "geom_type", "") == "MultiPolygon"
            else (geometry,)
        )
        return sum(
            len(part.exterior.coords)
            + sum(len(ring.coords) for ring in part.interiors)
            for part in parts
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return 0


def _recipe_runs(recipe, num_layers: int) -> list[tuple[int, int, int]]:
    try:
        layers_to_use = min(max(0, int(num_layers)), len(recipe))
    except (TypeError, ValueError, OverflowError):
        return []
    if layers_to_use <= 0:
        return []
    try:
        previous = int(recipe[0])
    except (TypeError, ValueError, OverflowError):
        return []
    run_start = 0
    runs: list[tuple[int, int, int]] = []
    for index in range(1, layers_to_use):
        try:
            current = int(recipe[index])
        except (TypeError, ValueError, OverflowError):
            return []
        if current != previous:
            runs.append((previous, run_start, index - 1))
            run_start = index
            previous = current
    runs.append((previous, run_start, layers_to_use - 1))
    return runs


def estimate_vector_mesh_build_memory(
    matched_shapes,
    *,
    num_layers: int,
    double_sided: bool,
    spatial_group_chunk_bytes: int,
    auxiliary_geometries=(),
    auxiliary_run_count: int = 0,
) -> VectorMeshBuildMemoryEstimate:
    """Estimate retained output plus bounded peak working allocations.

    估算最终输出与有界工作区叠加后的峰值分配。

    The estimate intentionally assumes the largest material may contain the
    whole final mesh during assembly. It is conservative without traversing or
    serializing coordinates into another full buffer.

    ``spatial_group_chunk_bytes`` bounds material aggregation while preserving
    independent canonical shell groups.
    ``spatial_group_chunk_bytes`` 限制材质聚合峰值，同时保留独立规范壳体组。
    """

    shape_count = 0
    coordinate_count = 0
    run_count = 0
    run_coordinate_references = 0
    run_group_coordinate_counts: dict[tuple[int, int, int], int] = {}
    side_multiplier = 2 if bool(double_sided) else 1
    for item in matched_shapes or ():
        geometry = item.get("geometry") if isinstance(item, dict) else None
        if geometry is None or getattr(geometry, "is_empty", False):
            continue
        coordinates = _geometry_coordinate_count(geometry)
        runs = _recipe_runs(
            item.get("recipe") if isinstance(item, dict) else None,
            num_layers,
        )
        shape_count += 1
        coordinate_count += coordinates
        run_count += len(runs)
        run_coordinate_references += coordinates * len(runs)
        for run_key in runs:
            run_group_coordinate_counts[run_key] = (
                run_group_coordinate_counts.get(run_key, 0) + coordinates
            )

    run_count *= side_multiplier
    run_coordinate_references *= side_multiplier
    auxiliary_coordinate_count = sum(
        _geometry_coordinate_count(geometry)
        for geometry in (auxiliary_geometries or ())
        if geometry is not None and not getattr(geometry, "is_empty", False)
    )
    auxiliary_runs = max(0, int(auxiliary_run_count))
    auxiliary_coordinate_references = (
        auxiliary_coordinate_count * auxiliary_runs
    )
    largest_prepared_group_coordinate_count = max(
        max(run_group_coordinate_counts.values(), default=0),
        auxiliary_coordinate_count if auxiliary_runs else 0,
    )
    estimated_final_mesh_bytes = (
        (run_coordinate_references + auxiliary_coordinate_references)
        * _VECTOR_MESH_BYTES_PER_RUN_COORDINATE
    )
    retained_source_geometry_bytes = (
        coordinate_count * _VECTOR_MESH_BYTES_PER_SOURCE_COORDINATE
    )
    estimated_preparation_bytes = sum(
        (
            _VECTOR_MESH_FIXED_WORKING_BYTES,
            retained_source_geometry_bytes,
            largest_prepared_group_coordinate_count * 256,
        )
    )
    return VectorMeshBuildMemoryEstimate(
        shape_count=shape_count,
        coordinate_count=coordinate_count,
        auxiliary_coordinate_count=auxiliary_coordinate_count,
        run_count=run_count,
        run_coordinate_references=run_coordinate_references,
        auxiliary_coordinate_references=auxiliary_coordinate_references,
        largest_prepared_group_coordinate_count=(
            largest_prepared_group_coordinate_count
        ),
        estimated_final_mesh_bytes=estimated_final_mesh_bytes,
        estimated_preparation_bytes=estimated_preparation_bytes,
    )


def resolve_vector_mesh_memory_budget_bytes() -> int:
    """Resolve the worker RSS cap, including any parent host reservation."""

    raw_value = os.environ.get(_VECTOR_MESH_MEMORY_BUDGET_ENV)
    if raw_value is None or not raw_value.strip():
        configured_budget = DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES
    else:
        try:
            value_mb = int(raw_value)
        except ValueError:
            value_mb = 0
        configured_budget = (
            value_mb * 1024 * 1024
            if value_mb > 0
            else DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES
        )
    # A budget above the container limit is not a budget: the allocator stops
    # at the cgroup limit, so the guards must use the smaller figure. An
    # explicit environment override remains an upper bound, never a raise.
    # 高于容器上限的预算不是预算：分配器在 cgroup 上限处就会停止，因此保护
    # 逻辑必须使用较小值。显式环境变量仍然只是上限，不会抬高容器上限。
    container_limit = get_effective_memory_limit_bytes()
    if container_limit is not None:
        configured_budget = min(configured_budget, max(1, int(container_limit)))
    host_reservation = current_task_host_memory_budget_bytes()
    if host_reservation is None:
        return configured_budget
    return min(configured_budget, max(1, int(host_reservation)))


def estimate_vector_task_memory_reservation_bytes(
    source_path: str | os.PathLike[str],
    *,
    supporting_paths: tuple[str | os.PathLike[str], ...] = (),
    resident_paths: tuple[str | os.PathLike[str], ...] = (),
    implicit_resident_bytes: int = 0,
    memory_budget_bytes: int | None = None,
) -> int:
    """Estimate a complete parent/worker cap from native SVG artifacts.

    根据原生 SVG 及其缓存文件大小，估算父进程占位与 worker 上限。

    The estimate is intentionally conservative: one GiB covers fixed Python,
    geometry, and export working state, while each source/cache byte receives
    a 64-byte expansion allowance. The worker's geometry-aware preflight
    remains authoritative. Unknown, unreadable, or non-SVG sources retain the
    configured worst-case cap instead of receiving an optimistic estimate.

    Args:
        source_path: Native SVG artifact submitted to the worker. 提交给
            worker 的原生 SVG 文件。
        supporting_paths: Parse/cache artifacts whose serialized complexity
            can expand into geometry. 会展开为几何的解析或缓存文件。
        resident_paths: Other worker inputs such as STL, heightmap, LUT, and
            material arrays. STL、高度图、LUT、材料数组等其他常驻输入。
        implicit_resident_bytes: Already-expanded runtime state not represented
            by a file path. 不对应文件路径、已按内存计量的运行时状态。
        memory_budget_bytes: Optional configured upper bound. 可选的配置上限。

    Returns:
        int: Complete task reservation in bytes. 完整任务内存占位字节数。
    """

    configured_budget = max(
        1,
        int(
            resolve_vector_mesh_memory_budget_bytes()
            if memory_budget_bytes is None
            else memory_budget_bytes
        ),
    )
    source = Path(source_path)
    source_suffix = source.suffix.lower()
    supported_raster_suffixes = {
        ".bmp",
        ".gif",
        ".jpeg",
        ".jpg",
        ".png",
        ".tif",
        ".tiff",
        ".webp",
    }
    if source_suffix != ".svg" and source_suffix not in supported_raster_suffixes:
        return configured_budget

    try:
        if not source.is_file():
            return configured_budget
        if source_suffix == ".svg":
            source_expanded_bytes = (
                max(0, int(source.stat().st_size))
                * _VECTOR_TASK_RESERVATION_BYTES_PER_ARTIFACT_BYTE
            )
        else:
            source_expanded_bytes = (
                _resident_artifact_size_hint(source)
                * _VECTOR_TASK_RESERVATION_BYTES_PER_RASTER_BYTE
            )
        supporting_bytes = 0
        for supporting_path in supporting_paths:
            artifact = Path(supporting_path)
            if not artifact.is_file():
                return configured_budget
            supporting_bytes += max(0, int(artifact.stat().st_size))
        resident_bytes = 0
        resident_seen: set[str] = set()
        for resident_path in resident_paths:
            artifact = Path(resident_path)
            identity = os.path.abspath(os.fspath(artifact))
            if identity in resident_seen:
                continue
            resident_seen.add(identity)
            if not artifact.is_file():
                return configured_budget
            resident_bytes += _resident_artifact_size_hint(artifact)
    except (OSError, TypeError, ValueError, OverflowError):
        return configured_budget

    estimated_bytes = (
        _VECTOR_TASK_RESERVATION_BASE_BYTES
        + source_expanded_bytes
        + supporting_bytes * _VECTOR_TASK_RESERVATION_BYTES_PER_ARTIFACT_BYTE
        + max(
            0,
            resident_bytes - _VECTOR_TASK_INCLUDED_RESIDENT_BYTES,
        )
        * _VECTOR_TASK_BYTES_PER_EXCESS_RESIDENT_BYTE
        + max(0, int(implicit_resident_bytes))
    )
    return min(configured_budget, max(1, int(estimated_bytes)))


def estimate_vector_material_parallel_memory_target_bytes(
    source_path: str | os.PathLike[str],
    *,
    material_count: int,
    supporting_paths: tuple[str | os.PathLike[str], ...] = (),
    memory_budget_bytes: int | None = None,
) -> int | None:
    """Estimate the budget the material stage needs to build in parallel.

    估算材质阶段并行构建所需的预算。

    The stage decides for itself how many builders it may start, from its live
    budget and the real coordinate counts. A reservation sized only for the
    serial pipeline therefore leaves a resource-rich device building every
    material in the parent process. This returns the budget at which that same
    arithmetic affords the builders that work can actually keep busy: the
    serial reservation, plus each builder's process base, plus the coordinate
    working set the reservation's own source expansion already implies (one
    source byte expands to
    ``_VECTOR_TASK_RESERVATION_BYTES_PER_ARTIFACT_BYTE`` runtime bytes and one
    coordinate is charged ``MATERIAL_OUTPUT_RETAINED_BYTES_PER_COORDINATE`` of
    retained output). That model's 0.167 coordinates per source byte sits above
    the 0.156 the product's own dense document measured, so it asks for a
    little more than that document needed.

    阶段自己决定能起几个构建进程（用实时预算与真实坐标数）。只为串行管线计的预留
    会让内存充足的设备把每个材质都在父进程内构建。本函数返回同一套算法能给出
    “这份工作真正能喂饱的构建进程数”所需预算：串行预留、每个构建进程的进程基数，
    以及源扩展本身已隐含的坐标工作集。该模型每源字节 0.167 个坐标，高于产品自有
    密集文档实测的 0.156，即请求略多于该文档实际所需。

    The result is a request, not a raise: it is capped by the configured or
    container budget, and the parent admission gate grants only the part that is
    free, leaving the required reservation untouched when nothing is spare.
    结果是请求而非抬高：受配置/容器预算封顶；父进程准入只授予空闲部分，无空闲时
    不影响必需预留。

    Returns:
        The target bytes, or ``None`` when no grounded figure exists: fewer than
        two materials to build, a source this estimate cannot price, or work
        below the coordinates at which the stage starts workers at all.
        目标字节数；无法给出有根据数值时返回 ``None``（少于两个材质、无法定价的源，
        或工作量低于阶段开始使用 worker 的坐标下限）。
    """

    if int(material_count) < 2:
        return None
    configured = max(
        1,
        int(
            resolve_vector_mesh_memory_budget_bytes()
            if memory_budget_bytes is None
            else memory_budget_bytes
        ),
    )
    source = Path(source_path)
    if source.suffix.lower() != ".svg":
        return None
    try:
        if not source.is_file():
            return None
        source_bytes = max(0, int(source.stat().st_size))
        required = estimate_vector_task_memory_reservation_bytes(
            source_path,
            supporting_paths=supporting_paths,
            memory_budget_bytes=configured,
        )
    except (OSError, TypeError, ValueError, OverflowError):
        return None
    coordinate_estimate = (
        source_bytes
        * _VECTOR_TASK_RESERVATION_BYTES_PER_ARTIFACT_BYTE
        // MATERIAL_OUTPUT_RETAINED_BYTES_PER_COORDINATE
    )
    if coordinate_estimate < MIN_PARALLEL_MATERIAL_COORDINATES:
        # Work this small is built in the process that already exists, whatever
        # budget it holds, so asking for builders would take capacity from tasks
        # that can use it. 这个量级的工作无论预算多少都在已有进程内完成，为它索
        # 取构建进程会占掉真正能用上的任务的容量。
        return None
    usable_workers = min(
        int(material_count),
        max(
            1,
            (coordinate_estimate + MATERIAL_COORDINATES_PER_WORKER - 1)
            // MATERIAL_COORDINATES_PER_WORKER,
        ),
    )
    target = (
        required
        + usable_workers * MATERIAL_WORKER_PROCESS_BASE_BYTES
        + coordinate_estimate * MATERIAL_WORKER_WORKING_BYTES_PER_COORDINATE
    )
    return min(configured, max(required, int(target)))


def _resident_artifact_size_hint(path: Path) -> int:
    """Return retained bytes for a worker input without materializing it."""

    file_bytes = max(0, int(path.stat().st_size))
    suffix = path.suffix.lower()
    if suffix == ".npy":
        try:
            import numpy as np

            array = np.load(path, mmap_mode="r", allow_pickle=False)
            try:
                return max(file_bytes, int(array.nbytes))
            finally:
                mmap = getattr(array, "_mmap", None)
                if mmap is not None:
                    mmap.close()
        except (ImportError, OSError, TypeError, ValueError, OverflowError):
            return file_bytes
    if suffix in {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}:
        try:
            from PIL import Image

            with Image.open(path) as image:
                sample_bytes = 4 if image.mode in {"F", "I"} else (
                    2 if "16" in image.mode else 1
                )
                decoded_bytes = (
                    max(1, int(image.width))
                    * max(1, int(image.height))
                    * max(1, len(image.getbands()))
                    * sample_bytes
                )
            return max(file_bytes, decoded_bytes)
        except (ImportError, OSError, TypeError, ValueError, OverflowError):
            return file_bytes
    return file_bytes


def get_process_rss_bytes() -> int | None:
    """Return current process RSS without introducing an API-layer import."""

    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (OSError, RuntimeError):
        return None


def get_owned_process_group_rss_bytes() -> int | None:
    """Return RSS of this process plus every process it currently owns.

    返回本进程及其当前拥有的全部子进程的 RSS 之和。

    Material workers are children of the task process, so the parent's own RSS
    alone understates what the task uses while results are recovered.
    材质 worker 是任务进程的子进程；只统计父进程 RSS 会低估任务在回收结果期间
    的真实占用。
    """

    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        process = psutil.Process(os.getpid())
        total = int(process.memory_info().rss)
        for child in process.children(recursive=True):
            try:
                total += int(child.memory_info().rss)
            except (OSError, RuntimeError, psutil.Error):
                continue
        return total
    except (OSError, RuntimeError, psutil.Error):
        return None


def get_owned_memory_report() -> dict[str, int | str | None]:
    """Describe the whole owned process group and the container charge.

    描述整个自有进程组以及容器计费口径。

    Returns:
        Scalar diagnostics: this process RSS, its children's RSS sum, and the
        cgroup v2 limit/current of this process's own cgroup. The container
        figures use the same path discovery as the CPU quota.
        标量诊断：本进程 RSS、子进程 RSS 之和，以及本进程所属 cgroup 的 v2
        上限与当前用量。容器数值与 CPU 配额使用同一套路径发现逻辑。
    """

    from core.system_capacity import get_effective_memory_capacity

    report: dict[str, int | str | None] = {
        "self_rss_bytes": get_process_rss_bytes(),
        "owned_group_rss_bytes": get_owned_process_group_rss_bytes(),
    }
    try:
        capacity = get_effective_memory_capacity()
    except (ImportError, AttributeError, OSError, RuntimeError, ValueError):
        report.update({
            "container_limit_bytes": None,
            "container_current_bytes": None,
            "container_source": "unavailable",
            "effective_available_bytes": None,
        })
        return report
    report.update({
        "container_limit_bytes": capacity.limit_bytes,
        "container_current_bytes": capacity.container_used_bytes,
        "container_source": capacity.source,
        "effective_available_bytes": capacity.available_bytes,
    })
    return report


def enforce_vector_mesh_memory_budget(
    *,
    stage: str,
    estimated_additional_bytes: int,
    memory_budget_bytes: int,
    current_rss_bytes: int,
    shape_count: int,
    coordinate_count: int,
) -> VectorMeshMemoryBudgetReport:
    """Accept safe estimated work or raise an actionable validation error.

    接受预算内任务；超预算时抛出可操作的校验错误。
    """

    additional = max(0, int(estimated_additional_bytes))
    budget = max(1, int(memory_budget_bytes))
    rss = max(0, int(current_rss_bytes))
    peak = rss + additional
    report = VectorMeshMemoryBudgetReport(
        stage=str(stage),
        estimated_additional_bytes=additional,
        estimated_peak_bytes=peak,
        memory_budget_bytes=budget,
        current_rss_bytes=rss,
        shape_count=max(0, int(shape_count)),
        coordinate_count=max(0, int(coordinate_count)),
        is_allowed=peak <= budget,
    )
    if not report.is_allowed:
        raise VectorMeshMemoryBudgetError(
            report.stage,
            report.estimated_peak_bytes,
            report.memory_budget_bytes,
            report.current_rss_bytes,
            report.shape_count,
            report.coordinate_count,
        )
    return report
