#!/usr/bin/env python3
"""Profile single-task converter workloads without changing output quality.

在不改变输出质量的前提下分析转换器单任务工作负载。
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import math
import os
import platform
import pstats
import statistics
import sys
import threading
import time
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Literal

import numpy as np
import psutil
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import ModelingMode
from core.pipeline.coordinator import run_preview_pipeline, run_raster_pipeline


_BASE_EIGHT = [
    "纵维立方/纵维立方PLA白色",
    "纵维立方/纵维立方PLA黑色",
    "纵维立方/纵维立方PLA红色",
    "纵维立方/纵维立方PLA黄色",
    "纵维立方/纵维立方PLA蓝色",
    "纵维立方/纵维立方PLA绿色",
    "纵维立方/纵维立方PLA青色",
    "纵维立方/纵维立方PLA品红色",
]
_EXTRA_SEVEN = [
    "Karvax/Karvax PLA 晴山蓝",
    "Karvax/Karvax PLA 流光蓝",
    "Karvax/Karvax PLA 烟笼紫霞",
    "Karvax/Karvax PLA 暖黄",
    "Karvax/Karvax PLA 朱砂红",
    "Karvax/Karvax PLA 拓竹绿",
    "Karvax/Karvax PLA 耀石黑",
]
MATERIAL_PALETTES = {
    8: list(_BASE_EIGHT),
    12: [*_BASE_EIGHT, *_EXTRA_SEVEN[:4]],
    15: [*_BASE_EIGHT, *_EXTRA_SEVEN],
}
_NUMERIC_RUN_METRICS = (
    "total_s",
    "cpu_s",
    "average_cpu_percent",
    "peak_rss_mb",
    "peak_thread_count",
    "peak_child_process_count",
)


@dataclass(frozen=True)
class ProfileCase:
    """Describe one deterministic converter profiling case.

    描述一个确定性的转换器性能分析案例。

    Attributes:
        name: Stable case identifier. 稳定的案例标识。
        kind: Raster or vector workflow. 位图或矢量工作流。
        input_path: Source asset path. 输入素材路径。
        target_width_mm: Requested model width. 目标模型宽度。
        material_count: Material Archive palette size. 耗材档案颜色数量。
    """

    name: str
    kind: Literal["raster", "vector"]
    input_path: Path
    target_width_mm: float
    material_count: Literal[8, 12, 15] = 12


def build_pipeline_context(case: ProfileCase) -> dict[str, Any]:
    """Build a quality-locked pipeline context for a profile case.

    为性能分析案例构建质量参数锁定的流水线上下文。

    Args:
        case: Deterministic profile case. 确定性的性能分析案例。

    Returns:
        Context accepted by the raster or vector pipeline.
        位图或矢量流水线可接受的上下文字典。
    """

    modeling_mode = (
        ModelingMode.VECTOR
        if case.kind == "vector"
        else ModelingMode.HIGH_FIDELITY
    )
    return {
        "image_path": str(case.input_path),
        "lut_path": "__material_archive__",
        "target_width_mm": float(case.target_width_mm),
        "spacer_thick": 1.2,
        "structure_mode": "single-sided",
        "color_mode": "4-Color (RYBW)",
        "add_loop": False,
        "loop_width": 4.0,
        "loop_length": 8.0,
        "loop_hole": 2.5,
        "loop_pos": None,
        "modeling_mode": modeling_mode,
        "color_layers": 10,
        "layer_height_mm": 0.08,
        "quantize_colors": 64,
        "color_replacements": None,
        "replacement_regions": None,
        "backing_color_id": 0,
        "separate_backing": False,
        "enable_relief": False,
        "color_height_map": None,
        "height_mode": "color",
        "heightmap_path": None,
        "heightmap_max_height": None,
        "enable_cleanup": True,
        "enable_outline": False,
        "outline_width": 2.0,
        "enable_cloisonne": False,
        "wire_width_mm": 0.4,
        "wire_height_mm": 0.4,
        "free_color_set": None,
        "enable_coating": False,
        "coating_height_mm": 0.08,
        "hue_weight": 0.5,
        "chroma_gate": 15.0,
        "matched_rgb_path": None,
        "loop_angle": 0.0,
        "loop_offset_x": 0.0,
        "loop_offset_y": 0.0,
        "loop_position_preset": "top-center",
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.4",
        "relief_global_max_height": None,
        "progress": None,
        "need_2d_preview": False,
        "material_source": "material_archive",
        "selected_materials": list(MATERIAL_PALETTES[case.material_count]),
        "material_layer_count": 10,
        "material_layer_height_mm": 0.08,
        "material_grid_resolution": 8,
        "material_backing_material_index": 0,
        "use_lut_constrained": False,
        "auto_dynamic_range": False,
        "high_precision_3d_preview": False,
    }


def _array_summary(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    array = np.ascontiguousarray(np.asarray(value))
    digest = hashlib.sha256()
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(repr(tuple(int(item) for item in array.shape)).encode("ascii"))
    digest.update(memoryview(array).cast("B"))
    return {
        "shape": [int(item) for item in array.shape],
        "dtype": array.dtype.str,
        "sha256": digest.hexdigest(),
    }


def _canonical_triangle_sha256(mesh: trimesh.Trimesh) -> str:
    vertices = np.round(np.asarray(mesh.vertices, dtype=np.float64), 9)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    triangles = vertices[faces]
    vertex_order = np.lexsort(
        (triangles[:, :, 2], triangles[:, :, 1], triangles[:, :, 0]),
        axis=1,
    )
    ordered_vertices = np.take_along_axis(
        triangles,
        vertex_order[:, :, np.newaxis],
        axis=1,
    )
    flattened = np.ascontiguousarray(ordered_vertices.reshape((-1, 9)))
    face_order = np.lexsort(
        tuple(flattened[:, index] for index in range(8, -1, -1))
    )
    canonical = np.ascontiguousarray(flattened[face_order])
    return hashlib.sha256(memoryview(canonical).cast("B")).hexdigest()


def _mesh_summary(mesh: trimesh.Trimesh) -> dict[str, object]:
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "bounds": np.round(bounds, 9).tolist(),
        "area": round(float(mesh.area), 9),
        "volume": round(float(mesh.volume), 9),
        "watertight": bool(mesh.is_watertight),
        "euler_number": int(mesh.euler_number),
        "degenerate_faces": int(
            np.count_nonzero(np.asarray(mesh.area_faces) <= 1e-12)
        ),
        "canonical_triangle_sha256": _canonical_triangle_sha256(mesh),
    }


def semantic_snapshot(ctx: dict[str, Any]) -> dict[str, object]:
    """Summarize output arrays and geometry using deterministic semantics.

    以确定性语义摘要记录输出数组与几何结果。

    Args:
        ctx: Completed pipeline context. 已完成的流水线上下文。

    Returns:
        Order-independent semantic snapshot. 与顺序无关的语义快照。
    """

    cache = ctx.get("cache")
    payload = cache if isinstance(cache, dict) else ctx
    scene = ctx.get("scene")
    if scene is None:
        scene = payload.get("scene")
    geometry: dict[str, object] = {}
    if isinstance(scene, trimesh.Scene):
        for name in sorted(scene.geometry):
            raw = scene.geometry[name]
            if isinstance(raw, trimesh.Trimesh):
                geometry[str(name)] = _mesh_summary(raw)
    return {
        "matched_rgb": _array_summary(payload.get("matched_rgb")),
        "material_matrix": _array_summary(payload.get("material_matrix")),
        "mask_solid": _array_summary(payload.get("mask_solid")),
        "slot_names": [str(item) for item in payload.get("slot_names") or []],
        "geometry": geometry,
    }


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("values must not be empty")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, object]:
    """Summarize cold, warm, percentile, and peak profile metrics.

    汇总冷启动、热启动、分位数和峰值性能指标。

    Args:
        runs: Chronological profiling runs. 按时间顺序排列的分析结果。

    Returns:
        Numeric summary while retaining the complete cold run.
        保留完整冷启动结果的数值汇总。

    Raises:
        ValueError: If no run is provided. 未提供运行结果时抛出。
    """

    if not runs:
        raise ValueError("runs must not be empty")
    keys = [
        key
        for key in _NUMERIC_RUN_METRICS
        if any(key in run for run in runs)
    ]
    warm = runs[1:] or runs

    def values_for(key: str, candidates: list[dict[str, Any]]) -> list[float]:
        values = [float(run[key]) for run in candidates if key in run]
        return values or [float(run[key]) for run in runs if key in run]

    return {
        "cold": dict(runs[0]),
        "warm_median": {
            key: statistics.median(values_for(key, warm))
            for key in keys
        },
        "p90": {
            key: _percentile(values_for(key, warm), 0.90)
            for key in keys
        },
        "peak": {
            key: max(values_for(key, runs))
            for key in keys
        },
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_report(
    case: ProfileCase,
    runs: list[dict[str, Any]],
) -> dict[str, object]:
    """Build a report that excludes private absolute input/material paths.

    构建不包含私有输入绝对路径和耗材目录名的报告。

    Args:
        case: Profile case metadata. 性能分析案例元数据。
        runs: Raw per-run measurements. 每轮原始测量结果。

    Returns:
        Sanitized, JSON-serializable report. 已脱敏且可序列化的报告。
    """

    return {
        "schema": "lumina_converter_multicore_profile_v1",
        "machine": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "visible_cpu": os.cpu_count(),
        },
        "input": {
            "name": case.input_path.name,
            "sha256": _sha256_file(case.input_path),
            "kind": case.kind,
            "target_width_mm": case.target_width_mm,
        },
        "materials": {
            "count": case.material_count,
            "palette_sha256": hashlib.sha256(
                "\n".join(MATERIAL_PALETTES[case.material_count]).encode("utf-8")
            ).hexdigest(),
        },
        "runs": runs,
        "summary": summarize_runs(runs),
    }


class _ResourceSampler:
    def __init__(self, process: psutil.Process, interval_s: float = 0.05) -> None:
        self._process = process
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.peak_rss_bytes = 0
        self.peak_thread_count = 0
        self.peak_child_process_count = 0

    def _sample(self) -> None:
        try:
            children = self._process.children(recursive=True)
            processes = [self._process, *children]
            rss_bytes = 0
            thread_count = 0
            for process in processes:
                try:
                    rss_bytes += process.memory_info().rss
                    thread_count += process.num_threads()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self.peak_rss_bytes = max(self.peak_rss_bytes, rss_bytes)
            self.peak_thread_count = max(self.peak_thread_count, thread_count)
            self.peak_child_process_count = max(
                self.peak_child_process_count,
                len(children),
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            self._sample()

    def __enter__(self) -> "_ResourceSampler":
        self._sample()
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._sample()


def _cleanup_result_files(result: dict[str, Any]) -> None:
    for key in ("out_path", "glb_path", "color_recipe_path"):
        raw_path = result.get(key)
        if not raw_path:
            continue
        path = Path(str(raw_path))
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            continue


def execute_case(
    case: ProfileCase,
    phase: Literal["preview", "generate"],
) -> dict[str, object]:
    """Execute and profile one quality-locked conversion phase.

    执行并分析一次质量参数锁定的转换阶段。

    Args:
        case: Deterministic profile case. 确定性的性能分析案例。
        phase: Preview or generation phase. 预览或生成阶段。

    Returns:
        Timings, resource peaks, semantic snapshot, and cProfile text.
        计时、资源峰值、语义快照和 cProfile 文本。

    Raises:
        RuntimeError: If the pipeline reports an error. 流水线报错时抛出。
    """

    ctx = build_pipeline_context(case)
    profile = cProfile.Profile()
    process = psutil.Process()
    cpu_before = process.cpu_times()
    started = time.perf_counter()
    with _ResourceSampler(process) as resources:
        profile.enable()
        try:
            result = (
                run_preview_pipeline(ctx)
                if phase == "preview"
                else run_raster_pipeline(ctx)
            )
        finally:
            profile.disable()
    elapsed = time.perf_counter() - started
    cpu_after = process.cpu_times()
    if result.get("error"):
        _cleanup_result_files(result)
        raise RuntimeError(str(result["error"]))
    stream = StringIO()
    (
        pstats.Stats(profile, stream=stream)
        .strip_dirs()
        .sort_stats("cumulative")
        .print_stats(80)
    )
    cpu_s = (
        cpu_after.user
        + cpu_after.system
        - cpu_before.user
        - cpu_before.system
    )
    try:
        snapshot = semantic_snapshot(result)
        return {
            "total_s": elapsed,
            "cpu_s": cpu_s,
            "average_cpu_percent": (cpu_s / elapsed * 100.0) if elapsed else 0.0,
            "peak_rss_mb": resources.peak_rss_bytes / (1024 * 1024),
            "peak_thread_count": resources.peak_thread_count,
            "peak_child_process_count": resources.peak_child_process_count,
            "step_timings": dict(
                result.get("_preview_step_timings")
                or result.get("_step_timings")
                or {}
            ),
            "preview_timings": dict(result.get("_preview_timings") or {}),
            "vector_timings": dict(result.get("_vector_timings") or {}),
            "semantic_snapshot": snapshot,
            "cprofile": stream.getvalue(),
        }
    finally:
        _cleanup_result_files(result)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile one Lumina converter preview or generate task."
    )
    parser.add_argument("--kind", choices=("raster", "vector"), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--phase",
        choices=("preview", "generate"),
        required=True,
    )
    parser.add_argument("--target-width-mm", type=float, default=299.0)
    parser.add_argument(
        "--material-count",
        type=int,
        choices=(8, 12, 15),
        default=12,
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".scratch/converter-multicore"),
    )
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    if args.target_width_mm <= 0:
        parser.error("--target-width-mm must be > 0")
    if not args.input.is_file():
        parser.error(f"--input is not a file: {args.input}")
    expected_suffix = ".svg" if args.kind == "vector" else None
    if expected_suffix and args.input.suffix.lower() != expected_suffix:
        parser.error("--kind vector requires an SVG input")
    return args


def _render_markdown(report: dict[str, object]) -> str:
    summary = report["summary"]
    input_meta = report["input"]
    materials = report["materials"]
    assert isinstance(summary, dict)
    assert isinstance(input_meta, dict)
    assert isinstance(materials, dict)
    cold = summary["cold"]
    assert isinstance(cold, dict)
    return "\n".join(
        [
            "# Converter Multicore Profile",
            "",
            f"- Kind: `{input_meta['kind']}`",
            f"- Input: `{input_meta['name']}`",
            f"- Input SHA-256: `{input_meta['sha256']}`",
            f"- Phase: `{report['phase']}`",
            f"- Materials: `{materials['count']}`",
            f"- Target width: `{input_meta['target_width_mm']} mm`",
            f"- Cold total: `{float(cold['total_s']):.3f} s`",
            f"- Cold peak RSS: `{float(cold['peak_rss_mb']):.2f} MiB`",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    """Run the converter profiling command.

    运行转换器性能分析命令。

    Args:
        argv: Optional command-line arguments. 可选命令行参数。

    Returns:
        Process exit code. 进程退出码。
    """

    args = _parse_args(argv)
    case = ProfileCase(
        name=f"{args.kind}-{args.material_count}",
        kind=args.kind,
        input_path=args.input,
        target_width_mm=args.target_width_mm,
        material_count=args.material_count,
    )
    runs: list[dict[str, Any]] = []
    for index in range(1, args.runs + 1):
        print(
            f"[profile] {case.name} {args.phase} run {index}/{args.runs}",
            flush=True,
        )
        run = execute_case(case, args.phase)
        runs.append(run)
        print(
            f"[profile] total={float(run['total_s']):.3f}s "
            f"peak_rss={float(run['peak_rss_mb']):.2f}MiB",
            flush=True,
        )
    report = build_report(case, runs)
    report["phase"] = args.phase
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "profile.json"
    markdown_path = args.output_dir / "profile.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    print(f"[profile] json={json_path}", flush=True)
    print(f"[profile] markdown={markdown_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
