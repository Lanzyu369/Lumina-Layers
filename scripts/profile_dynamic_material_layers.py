"""Reproducible benchmark for exact dynamic-material layer solving.

动态耗材层数精确求解的可复现性能基准入口。

The benchmark keeps targets, materials, candidate budget, and seeds fixed while
measuring cache-cold and cache-warm solves.  It writes only the requested JSON
report; all candidate/catalog caches live in an automatically removed temporary
directory.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import material_dynamic_catalog_cache as catalog_cache
from core import material_dynamic_solver as dynamic_solver
from core.material_candidate_cache import (
    MaterialCandidateCacheConfig,
    PREVIEW_SAFE_CANDIDATE_BUDGET,
)
from core.material_lut_provider import load_materials


DEFAULT_TARGET_COUNTS = (48, 256, 8192)
DEFAULT_TARGET_SEED = 20_260_718
DEFAULT_RSS_SAMPLE_INTERVAL_SECONDS = 0.005
DEFAULT_CANCELLATION_TIMEOUT_SECONDS = 0.25
DEFAULT_CANCELLATION_WORKER_DELAY_SECONDS = 2.0
_RSS_READER: Callable[[], int | None] | None = None
_RSS_METHOD: str | None = None


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must not be negative")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not np.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive finite number")
    return parsed


def _parse_target_counts(value: str) -> tuple[int, ...]:
    try:
        counts = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "target counts must be comma-separated integers"
        ) from exc
    if not counts or any(count <= 0 for count in counts):
        raise argparse.ArgumentTypeError("target counts must all be positive")
    if len(set(counts)) != len(counts):
        raise argparse.ArgumentTypeError("target counts must not contain duplicates")
    return counts


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark exact dynamic-material solving with fixed inputs and "
            "separate cache-cold/cache-warm measurements."
        )
    )
    parser.add_argument(
        "--materials-root",
        type=Path,
        required=True,
        help="Root containing the selected material archive directories.",
    )
    parser.add_argument(
        "--material-dir",
        action="append",
        required=True,
        help=(
            "Material directory relative to --materials-root, in palette order. "
            "Repeat once per material."
        ),
    )
    parser.add_argument(
        "--backing-material-index",
        type=_nonnegative_int,
        default=0,
        help="Zero-based palette index used for backing padding (default: 0).",
    )
    parser.add_argument(
        "--target-counts",
        type=_parse_target_counts,
        default=DEFAULT_TARGET_COUNTS,
        help="Comma-separated target counts (default: 48,256,8192).",
    )
    parser.add_argument(
        "--candidate-budget",
        type=_positive_int,
        default=PREVIEW_SAFE_CANDIDATE_BUDGET,
        help=(
            "Pinned candidate budget for every layer "
            f"(default: {PREVIEW_SAFE_CANDIDATE_BUDGET})."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_TARGET_SEED,
        help=f"Fixed target-color RNG seed (default: {DEFAULT_TARGET_SEED}).",
    )
    parser.add_argument("--cold-runs", type=_positive_int, default=1)
    parser.add_argument("--warm-runs", type=_positive_int, default=3)
    parser.add_argument("--min-layers", type=int, default=5)
    parser.add_argument("--max-layers", type=int, default=10)
    parser.add_argument("--delta-e00-tolerance", type=float, default=0.5)
    parser.add_argument("--layer-height-mm", type=float, default=0.08)
    parser.add_argument(
        "--substrate",
        choices=("white", "black"),
        default="white",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the JSON report to this path instead of stdout.",
    )
    parser.add_argument(
        "--cancellation-timeout-seconds",
        type=_positive_float,
        default=DEFAULT_CANCELLATION_TIMEOUT_SECONDS,
        help=(
            "Timeout used by the isolated WorkerPool restart probe "
            f"(default: {DEFAULT_CANCELLATION_TIMEOUT_SECONDS})."
        ),
    )
    parser.add_argument(
        "--cancellation-worker-delay-seconds",
        type=_positive_float,
        default=DEFAULT_CANCELLATION_WORKER_DELAY_SECONDS,
        help=(
            "Intentional worker delay for the cancellation probe "
            f"(default: {DEFAULT_CANCELLATION_WORKER_DELAY_SECONDS})."
        ),
    )
    parser.add_argument(
        "--skip-cancellation-probe",
        action="store_true",
        help="Skip the isolated WorkerPool timeout/restart measurement.",
    )
    args = parser.parse_args(argv)
    if args.cancellation_worker_delay_seconds <= args.cancellation_timeout_seconds:
        parser.error(
            "--cancellation-worker-delay-seconds must exceed "
            "--cancellation-timeout-seconds"
        )
    return args


def _cancellation_probe_worker(marker_path: str, delay_seconds: float) -> int:
    """Write a completion marker only after a deliberate slow worker delay.

    The function is top-level and accepts only scalar/path arguments so it is
    submitted through the same ProcessPool contract as converter workers.
    It is intentionally a controlled timeout probe, not a claim that the
    exact solver supports cooperative cancellation.
    """

    time.sleep(delay_seconds)
    Path(marker_path).write_text("completed\n", encoding="utf-8")
    return os.getpid()


def _cancellation_probe_worker_pid() -> int:
    """Return the current probe worker identity after a successful restart."""

    return os.getpid()


async def _measure_worker_pool_cancellation(
    *,
    temp_root: Path,
    timeout_seconds: float,
    worker_delay_seconds: float,
) -> dict[str, Any]:
    """Measure the existing timeout/restart path without a CI wall-clock gate.

    The probe creates a marker only on normal worker completion. A timeout must
    return through :class:`api.worker_pool.WorkerPoolManager`, replace the
    original process, and leave that marker absent. This yields narrow evidence
    that the pool terminates a timed-out worker before it can publish a final
    cache/download-style artifact; it does not infer a cancellation API inside
    the exact solver itself.
    """

    from api.worker_pool import WorkerPoolManager

    marker_path = temp_root / "cancellation_probe_completed.marker"
    pool = WorkerPoolManager(max_workers=1)
    before_pid: int | None = None
    after_pid: int | None = None
    started = time.perf_counter()
    timeout_observed = False
    error: Exception | None = None
    try:
        pool.start()
        before_pid = await pool.submit(_cancellation_probe_worker_pid, timeout=10.0)
        started = time.perf_counter()
        try:
            await pool.submit(
                _cancellation_probe_worker,
                str(marker_path),
                worker_delay_seconds,
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            timeout_observed = True
        after_pid = await pool.submit(_cancellation_probe_worker_pid, timeout=10.0)
    except Exception as exc:  # pragma: no cover - environment-owned probe failure
        error = exc
    finally:
        pool.shutdown(wait=True)

    elapsed = time.perf_counter() - started
    completion_artifact_exists = marker_path.exists()
    worker_identity_changed = (
        before_pid is not None
        and after_pid is not None
        and before_pid != after_pid
    )
    if error is not None:
        return {
            "status": "probe_failed",
            "measurement_kind": "measured_probe_failure",
            "latency_seconds": elapsed,
            "timeout_seconds": timeout_seconds,
            "worker_delay_seconds": worker_delay_seconds,
            "timeout_observed": timeout_observed,
            "worker_identity_changed": worker_identity_changed,
            "completion_artifact_exists": completion_artifact_exists,
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
    status = (
        "timed_out_and_restarted"
        if timeout_observed
        and worker_identity_changed
        and not completion_artifact_exists
        else "inconclusive"
    )
    return {
        "status": status,
        "measurement_kind": "measured_controlled_worker_pool_probe",
        "latency_seconds": elapsed,
        "timeout_seconds": timeout_seconds,
        "worker_delay_seconds": worker_delay_seconds,
        "timeout_observed": timeout_observed,
        "worker_identity_changed": worker_identity_changed,
        "completion_artifact_exists": completion_artifact_exists,
        "artifact_scope": "controlled final-marker only; no converter cache or download was requested",
        "solver_cancellation_support": "not inferred",
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_material_directory(root: Path, directory_name: str) -> Path:
    candidate = (root / directory_name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"material directory escapes --materials-root: {directory_name}"
        ) from exc
    if not candidate.is_dir():
        raise FileNotFoundError(f"material directory not found: {directory_name}")
    return candidate


def _material_file_summaries(
    materials_root: Path,
    directory_names: Sequence[str],
) -> tuple[list[dict[str, Any]], str]:
    root = materials_root.resolve(strict=True)
    combined = hashlib.sha256()
    summaries: list[dict[str, Any]] = []
    for directory_name in directory_names:
        material_dir = _resolve_material_directory(root, directory_name)
        files: list[dict[str, Any]] = []
        for path in sorted(
            (item for item in material_dir.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(material_dir).as_posix(),
        ):
            relative = path.relative_to(material_dir).as_posix()
            size = path.stat().st_size
            file_digest = _sha256_file(path)
            files.append(
                {
                    "path": relative,
                    "bytes": size,
                    "sha256": file_digest,
                }
            )
            combined.update(directory_name.encode("utf-8"))
            combined.update(b"\0")
            combined.update(relative.encode("utf-8"))
            combined.update(b"\0")
            combined.update(str(size).encode("ascii"))
            combined.update(b"\0")
            combined.update(bytes.fromhex(file_digest))
        summaries.append(
            {
                "directory": directory_name,
                "file_count": len(files),
                "total_bytes": sum(int(item["bytes"]) for item in files),
                "files": files,
            }
        )
    return summaries, combined.hexdigest()


def _current_rss_bytes() -> tuple[int | None, str]:
    """Return current process RSS without adding a required dependency."""

    global _RSS_METHOD, _RSS_READER
    if _RSS_READER is not None and _RSS_METHOD is not None:
        return _RSS_READER(), _RSS_METHOD

    try:
        import psutil  # type: ignore[import-not-found]

        process = psutil.Process(os.getpid())

        def read_psutil_rss() -> int:
            return int(process.memory_info().rss)

        _RSS_READER = read_psutil_rss
        _RSS_METHOD = "psutil_rss"
        return _RSS_READER(), _RSS_METHOD
    except (ImportError, OSError):
        pass

    if sys.platform == "win32":
        try:
            size_t = ctypes.c_size_t

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", size_t),
                    ("WorkingSetSize", size_t),
                    ("QuotaPeakPagedPoolUsage", size_t),
                    ("QuotaPagedPoolUsage", size_t),
                    ("QuotaPeakNonPagedPoolUsage", size_t),
                    ("QuotaNonPagedPoolUsage", size_t),
                    ("PagefileUsage", size_t),
                    ("PeakPagefileUsage", size_t),
                ]

            get_current_process = ctypes.windll.kernel32.GetCurrentProcess
            get_current_process.restype = ctypes.c_void_p
            process = get_current_process()
            get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
            get_process_memory_info.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ProcessMemoryCounters),
                ctypes.c_ulong,
            ]
            get_process_memory_info.restype = ctypes.c_int

            def read_win32_working_set() -> int | None:
                counters = ProcessMemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                succeeded = get_process_memory_info(
                    process,
                    ctypes.byref(counters),
                    counters.cb,
                )
                return int(counters.WorkingSetSize) if succeeded else None

            if read_win32_working_set() is not None:
                _RSS_READER = read_win32_working_set
                _RSS_METHOD = "win32_working_set_sampled"
                return _RSS_READER(), _RSS_METHOD
        except (AttributeError, OSError, ValueError):
            pass

    def unsupported_rss() -> None:
        return None

    _RSS_READER = unsupported_rss
    _RSS_METHOD = "unsupported"
    return None, _RSS_METHOD


@dataclass
class _RssSampler:
    interval_seconds: float = DEFAULT_RSS_SAMPLE_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.start_bytes: int | None = None
        self.peak_bytes: int | None = None
        self.method = "unsupported"

    def __enter__(self) -> "_RssSampler":
        current, method = _current_rss_bytes()
        self.start_bytes = current
        self.peak_bytes = current
        self.method = method
        if current is not None:
            self._thread = threading.Thread(target=self._sample, daemon=True)
            self._thread.start()
        return self

    def _sample(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            current, _method = _current_rss_bytes()
            if current is not None:
                self.peak_bytes = max(self.peak_bytes or current, current)

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 4.0))
        current, _method = _current_rss_bytes()
        if current is not None:
            self.peak_bytes = max(self.peak_bytes or current, current)

    def as_json(self) -> dict[str, Any]:
        if self.start_bytes is None or self.peak_bytes is None:
            return {
                "status": "unsupported",
                "method": self.method,
                "sample_interval_seconds": self.interval_seconds,
                "start_mb": None,
                "observed_peak_mb": None,
                "observed_peak_delta_mb": None,
            }
        scale = 1024 * 1024
        return {
            "status": "measured",
            "method": self.method,
            "sample_interval_seconds": self.interval_seconds,
            "start_mb": self.start_bytes / scale,
            "observed_peak_mb": self.peak_bytes / scale,
            "observed_peak_delta_mb": max(
                0, self.peak_bytes - self.start_bytes
            )
            / scale,
        }


def _json_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _result_summary(
    result: dynamic_solver.DynamicMaterialSolveResult,
) -> dict[str, Any]:
    stable_matches = [
        {
            "target_srgb": list(match.target_srgb),
            "selected": {
                "actual_layer_count": match.selected.actual_layer_count,
                "matched_srgb": list(match.selected.matched_srgb),
                "actual_recipe_bottom_to_top": list(
                    match.selected.actual_recipe_bottom_to_top
                ),
                "print_recipe_bottom_to_top": list(
                    match.selected.print_recipe_bottom_to_top
                ),
                "delta_e00": match.selected.delta_e00,
            },
            "best_range_delta_e00": match.best_range.delta_e00,
            "fixed_max_delta_e00": match.fixed_max_delta_e00,
            "delta_e00_sacrifice": match.delta_e00_sacrifice,
        }
        for match in result.matches
    ]
    counts: dict[str, int] = {}
    for match in result.matches:
        key = str(match.selected.actual_layer_count)
        counts[key] = counts.get(key, 0) + 1
    mean_delta = (
        statistics.fmean(match.selected.delta_e00 for match in result.matches)
        if result.matches
        else 0.0
    )
    return {
        "sha256": _json_digest(stable_matches),
        "engine": result.engine,
        "match_count": len(result.matches),
        "candidate_count_before_dedup": result.candidate_count_before_dedup,
        "candidate_count_after_dedup": result.candidate_count_after_dedup,
        "layer_counts": list(result.layer_counts),
        "selected_actual_layer_histogram": counts,
        "selected_mean_delta_e00": mean_delta,
    }


def _array_digest(value: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(str(contiguous.dtype).encode("ascii"))
    digest.update(str(tuple(contiguous.shape)).encode("ascii"))
    digest.update(contiguous.tobytes())
    return digest.hexdigest()


def _compare_search_backends(
    targets: np.ndarray,
    catalog: dynamic_solver.DynamicCandidateCatalog,
    min_layers: int,
    max_layers: int,
) -> dict[str, Any]:
    numpy_result = dynamic_solver.search_dynamic_catalog_exact(
        targets,
        catalog,
        min_layers,
        max_layers,
        prefer_numba=False,
    )
    numpy_payload = {
        "engine": numpy_result.engine,
        "indices_sha256": _array_digest(
            numpy_result.cumulative_best_candidate_indices
        ),
        "delta_e00_sha256": _array_digest(
            numpy_result.cumulative_best_delta_e00
        ),
        "fixed_max_delta_e00_sha256": _array_digest(
            numpy_result.fixed_max_delta_e00
        ),
    }
    if not dynamic_solver._NUMBA_AVAILABLE:
        return {
            "status": "numba_unavailable",
            "numpy": numpy_payload,
            "numba": None,
            "exact_identity": None,
            "numeric_identity_at_1e-12": None,
        }

    preferred_result = dynamic_solver.search_dynamic_catalog_exact(
        targets,
        catalog,
        min_layers,
        max_layers,
        prefer_numba=True,
    )
    if preferred_result.engine != "numba":
        return {
            "status": "numba_execution_fell_back_to_numpy",
            "numpy": numpy_payload,
            "numba": None,
            "exact_identity": None,
            "numeric_identity_at_1e-12": None,
        }
    numba_payload = {
        "engine": preferred_result.engine,
        "indices_sha256": _array_digest(
            preferred_result.cumulative_best_candidate_indices
        ),
        "delta_e00_sha256": _array_digest(
            preferred_result.cumulative_best_delta_e00
        ),
        "fixed_max_delta_e00_sha256": _array_digest(
            preferred_result.fixed_max_delta_e00
        ),
    }
    indices_equal = np.array_equal(
        numpy_result.cumulative_best_candidate_indices,
        preferred_result.cumulative_best_candidate_indices,
    )
    delta_exact = np.array_equal(
        numpy_result.cumulative_best_delta_e00,
        preferred_result.cumulative_best_delta_e00,
    )
    fixed_exact = np.array_equal(
        numpy_result.fixed_max_delta_e00,
        preferred_result.fixed_max_delta_e00,
    )
    numeric_equal = indices_equal and np.allclose(
        numpy_result.cumulative_best_delta_e00,
        preferred_result.cumulative_best_delta_e00,
        rtol=0.0,
        atol=1e-12,
    ) and np.allclose(
        numpy_result.fixed_max_delta_e00,
        preferred_result.fixed_max_delta_e00,
        rtol=0.0,
        atol=1e-12,
    )
    exact_identity = indices_equal and delta_exact and fixed_exact
    return {
        "status": "compared",
        "numpy": numpy_payload,
        "numba": numba_payload,
        # The candidate indices define the visible recipe/result identity.
        # CIEDE2000 is evaluated by different numeric kernels, so keep the
        # bitwise distance check separate from the meaningful solver contract.
        "selected_candidate_identity": bool(indices_equal),
        "exact_identity": exact_identity,
        "distance_bitwise_identity": bool(delta_exact and fixed_exact),
        "numeric_identity_at_1e-12": bool(numeric_equal),
    }


def _run_once(
    *,
    targets: np.ndarray,
    materials: list[Any],
    config: dynamic_solver.DynamicMaterialSolveConfig,
    args: argparse.Namespace,
    cache_root: Path,
) -> dict[str, Any]:
    key = catalog_cache.build_dynamic_catalog_cache_key(
        materials,
        backing_material_index=args.backing_material_index,
        layer_height_mm=args.layer_height_mm,
        substrate=args.substrate,
        min_layer_count=args.min_layers,
        max_layer_count=args.max_layers,
        candidate_budget=args.candidate_budget,
    )
    cache_path = catalog_cache.dynamic_catalog_cache_file_path(
        key, cache_root=cache_root
    )
    existed_before = cache_path.is_file()
    with _RssSampler() as memory:
        started = time.perf_counter()
        result = dynamic_solver.solve_dynamic_material_colors(
            target_srgb=targets,
            materials=materials,
            backing_material_index=args.backing_material_index,
            layer_height_mm=args.layer_height_mm,
            substrate=args.substrate,
            config=config,
            material_candidate_budget=args.candidate_budget,
            catalog_cache_root=cache_root,
        )
        elapsed = time.perf_counter() - started
    exists_after = cache_path.is_file()
    if existed_before:
        cache_status = "hit_expected"
    elif exists_after:
        cache_status = "miss_built"
    else:
        cache_status = "miss_not_persisted"
    return {
        "measurement_kind": "measured",
        "elapsed_seconds": elapsed,
        "memory": memory.as_json(),
        "cache": {
            "status": cache_status,
            "catalog_file_existed_before": existed_before,
            "catalog_file_exists_after": exists_after,
        },
        "result": _result_summary(result),
    }


def _measure_puzzle_preview_analysis_reuse(
    *,
    targets: np.ndarray,
    max_layer_count: int,
    backing_material_index: int,
    temp_root: Path,
) -> dict[str, Any]:
    """Measure P03's dynamic authority-asset reuse for one puzzle-sized input.

    The old puzzle path invoked the exact solver after cropping a piece. This
    narrow measurement instead loads the four authoritative arrays through the
    production P03 validator, records its temporary asset footprint, and is
    reported next to an actual exact-solver reference measurement. It avoids a
    second fake pipeline or browser benchmark harness.
    """

    from core.pipeline.p03_core_processing import _load_dynamic_preview_analysis

    target_count = int(targets.shape[0])
    width = max(1, int(np.ceil(np.sqrt(target_count))))
    height = max(1, int(np.ceil(target_count / width)))
    matched_rgb = np.zeros((height, width, 3), dtype=np.uint8)
    matched_rgb.reshape(-1, 3)[:target_count] = targets
    mask_solid = np.zeros((height, width), dtype=bool)
    mask_solid.reshape(-1)[:target_count] = True
    quantized_image = matched_rgb.copy()
    material_matrix = np.full(
        (height, width, max_layer_count),
        -1,
        dtype=np.int32,
    )
    material_matrix[mask_solid] = int(backing_material_index)

    asset_root = temp_root / f"puzzle-reuse-{target_count}"
    asset_root.mkdir(parents=True, exist_ok=True)
    arrays = {
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "quantized_image": quantized_image,
        "material_matrix": material_matrix,
    }
    ctx: dict[str, Any] = {
        "reuse_preview_analysis": True,
        "material_dynamic_layer_count_enabled": True,
    }
    for name, array in arrays.items():
        path = asset_root / f"{name}.npy"
        np.save(path, array)
        ctx[f"{name}_path"] = str(path)

    temporary_asset_bytes = sum(
        path.stat().st_size for path in asset_root.glob("*.npy")
    )
    with _RssSampler() as memory:
        started = time.perf_counter()
        loaded = _load_dynamic_preview_analysis(
            ctx,
            max_layer_count=max_layer_count,
        )
        elapsed = time.perf_counter() - started
    assert loaded is not None
    identity = all(
        np.array_equal(actual, expected)
        for actual, expected in zip(loaded, arrays.values())
    )
    return {
        "measurement_kind": "measured",
        "elapsed_seconds": elapsed,
        "memory": memory.as_json(),
        "temporary_assets": {
            "file_count": len(arrays),
            "bytes": temporary_asset_bytes,
            "array_shapes": {
                name: list(array.shape) for name, array in arrays.items()
            },
        },
        "authority_arrays_round_trip_identical": identity,
    }


def _summarize_runs(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    elapsed = [float(run["elapsed_seconds"]) for run in runs]
    peak_delta = [
        float(run["memory"]["observed_peak_delta_mb"])
        for run in runs
        if run["memory"]["observed_peak_delta_mb"] is not None
    ]
    digests = [str(run["result"]["sha256"]) for run in runs]
    return {
        "run_count": len(runs),
        "elapsed_seconds": {
            "median": statistics.median(elapsed),
            "min": min(elapsed),
            "max": max(elapsed),
        },
        "observed_peak_delta_mb": (
            {
                "median": statistics.median(peak_delta),
                "min": min(peak_delta),
                "max": max(peak_delta),
            }
            if peak_delta
            else None
        ),
        "result_sha256_all_identical": len(set(digests)) == 1,
        "result_sha256": digests[0],
        "cache_statuses": [str(run["cache"]["status"]) for run in runs],
    }


def _git_revision() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _machine_info() -> dict[str, Any]:
    try:
        import numba

        numba_version: str | None = str(numba.__version__)
    except ImportError:
        numba_version = None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "numpy_version": np.__version__,
        "numba_available": bool(dynamic_solver._NUMBA_AVAILABLE),
        "numba_version": numba_version,
        "git_revision": _git_revision(),
    }


def _build_report(args: argparse.Namespace) -> dict[str, Any]:
    materials_root = args.materials_root.resolve(strict=True)
    material_names = list(args.material_dir)
    if args.backing_material_index >= len(material_names):
        raise ValueError("backing material index is outside the selected palette")

    material_files, material_digest = _material_file_summaries(
        materials_root, material_names
    )
    materials = load_materials(
        material_names,
        materials_dir=str(materials_root),
        use_cache=False,
    )
    config = dynamic_solver.DynamicMaterialSolveConfig(
        min_layer_count=args.min_layers,
        max_layer_count=args.max_layers,
        delta_e00_tolerance=args.delta_e00_tolerance,
    )
    max_target_count = max(args.target_counts)
    rng = np.random.default_rng(args.seed)
    all_targets = rng.integers(
        0,
        256,
        size=(max_target_count, 3),
        dtype=np.uint8,
    )
    target_digest = _array_digest(all_targets)
    candidate_seed = MaterialCandidateCacheConfig.persisted_for_budget(
        args.candidate_budget
    ).seed

    measurements: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="lumina-dynamic-profile-") as temp_name:
        temp_root = Path(temp_name)
        warm_cache_root = temp_root / "warm-cache"

        smallest_count = min(args.target_counts)
        warmup = _run_once(
            targets=all_targets[:smallest_count],
            materials=materials,
            config=config,
            args=args,
            cache_root=warm_cache_root,
        )

        for target_count in args.target_counts:
            targets = all_targets[:target_count]
            cold_runs: list[dict[str, Any]] = []
            for run_index in range(args.cold_runs):
                cold_cache_root = temp_root / (
                    f"cold-cache-{target_count}-{run_index}"
                )
                cold_runs.append(
                    _run_once(
                        targets=targets,
                        materials=materials,
                        config=config,
                        args=args,
                        cache_root=cold_cache_root,
                    )
                )
            warm_runs = [
                _run_once(
                    targets=targets,
                    materials=materials,
                    config=config,
                    args=args,
                    cache_root=warm_cache_root,
                )
                for _run_index in range(args.warm_runs)
            ]

            key = catalog_cache.build_dynamic_catalog_cache_key(
                materials,
                backing_material_index=args.backing_material_index,
                layer_height_mm=args.layer_height_mm,
                substrate=args.substrate,
                min_layer_count=args.min_layers,
                max_layer_count=args.max_layers,
                candidate_budget=args.candidate_budget,
            )
            cached = catalog_cache.load_dynamic_candidate_catalog(
                materials=materials,
                key=key,
                cache_root=warm_cache_root,
            )
            if cached is None:
                backend_identity: dict[str, Any] = {
                    "status": "catalog_unavailable",
                    "exact_identity": None,
                    "numeric_identity_at_1e-12": None,
                }
            else:
                backend_identity = _compare_search_backends(
                    targets,
                    cached.catalog,
                    args.min_layers,
                    args.max_layers,
                )
            puzzle_reuse = _measure_puzzle_preview_analysis_reuse(
                targets=targets,
                max_layer_count=args.max_layers,
                backing_material_index=args.backing_material_index,
                temp_root=temp_root,
            )
            measurements[str(target_count)] = {
                "target_count": target_count,
                "target_prefix_sha256": _array_digest(targets),
                "cold": {
                    "definition": "empty isolated candidate/catalog cache",
                    "runs": cold_runs,
                    "summary": _summarize_runs(cold_runs),
                },
                "warm": {
                    "definition": "validated persisted dynamic catalog cache hit",
                    "runs": warm_runs,
                    "summary": _summarize_runs(warm_runs),
                },
                "numpy_numba_identity": backend_identity,
                "puzzle_preview_analysis_reuse": {
                    "reuse": puzzle_reuse,
                    "legacy_re_solve_reference": {
                        "measurement_kind": "measured_exact_solver_reference",
                        "source": "cold.runs[0]",
                        "elapsed_seconds": cold_runs[0]["elapsed_seconds"],
                        "memory": cold_runs[0]["memory"],
                        "cache": cold_runs[0]["cache"],
                        "result": cold_runs[0]["result"],
                    },
                    "comparison_scope": (
                        "Reuse timing loads the production P03 authority assets; "
                        "the reference is the same target prefix solved exactly "
                        "instead of a second synthetic full-pipeline harness."
                    ),
                },
            }

        warmup_record = {
            "classification": "setup_excluded_from_warm_statistics",
            **warmup,
        }
        cancellation = (
            {
                "status": "skipped",
                "measured": False,
                "reason": "--skip-cancellation-probe was supplied",
            }
            if args.skip_cancellation_probe
            else asyncio.run(
                _measure_worker_pool_cancellation(
                    temp_root=temp_root,
                    timeout_seconds=args.cancellation_timeout_seconds,
                    worker_delay_seconds=args.cancellation_worker_delay_seconds,
                )
            )
        )

    return {
        "schema_version": 1,
        "benchmark": "dynamic_material_layers_exact",
        "measurement_policy": {
            "all_timing_values": "measured_wall_clock",
            "all_memory_values": "sampled_current_process_rss",
            "cold_definition": "cache-cold, not a fresh Python process",
            "warm_definition": "same-process persisted catalog cache hit",
            "extrapolated_values": [],
            "wall_clock_ci_thresholds": "none",
        },
        "machine": _machine_info(),
        "inputs": {
            "materials_root": str(materials_root),
            "material_directories": material_names,
            "material_files": material_files,
            "material_files_sha256": material_digest,
            "backing_material_index": args.backing_material_index,
            "target_counts": list(args.target_counts),
            "target_seed": args.seed,
            "target_array_max_prefix_sha256": target_digest,
            "candidate_budget_per_layer": args.candidate_budget,
            "candidate_sampling_seed": candidate_seed,
            "cold_runs": args.cold_runs,
            "warm_runs": args.warm_runs,
            "min_layers": args.min_layers,
            "max_layers": args.max_layers,
            "delta_e00_tolerance": args.delta_e00_tolerance,
            "layer_height_mm": args.layer_height_mm,
            "substrate": args.substrate,
        },
        "cache": {
            "scope": "temporary_per_invocation",
            "cleanup": "automatic_before_exit",
            "persistent_repo_cache_modified": False,
        },
        "warmup": warmup_record,
        "measurements": measurements,
        "cancellation": cancellation,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and emit one UTF-8 JSON report. 运行 CLI 并输出 JSON。"""

    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    args = _parse_args(argv)
    try:
        report = _build_report(args)
    except Exception as exc:
        print(
            json.dumps(
                {"error_type": type(exc).__name__, "error_message": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output is None:
        print(payload)
    else:
        output_path = args.output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
        print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
