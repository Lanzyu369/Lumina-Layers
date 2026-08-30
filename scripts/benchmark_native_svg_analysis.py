#!/usr/bin/env python3
"""Benchmark the complete Lumina native-SVG ``VectorAnalysis`` entry point."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import platform
import re
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Set native math runtimes before NumPy/Shapely enter the process. This is one
# caller thread, matching the reference benchmark contract.
for _thread_variable in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[_thread_variable] = "1"

import shapely  # noqa: E402

from core import native_svg_adapter  # noqa: E402
from core.native_svg_adapter import NativeSvgFallback  # noqa: E402
from core.vector_engine import (  # noqa: E402
    VectorProcessor,
    _VECTOR_PARSE_CLIP_CACHE,
)


REAL_R4C1_SHA256 = (
    "da52ef12bdd37a0bd47970649a70582862331a606c151bff05bfb2f6e265f160"
)
LARGE_REGRESSION_MINIMUM_BYTES = 50 * 1024 * 1024


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _style_map(style: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        name, value = declaration.split(":", 1)
        declarations[name.strip().lower()] = value.strip().lower()
    return declarations


def _fixture_structure(path: Path) -> dict[str, Any]:
    root: ET.Element | None = None
    path_count = 0
    stroke_count = 0
    stroke_only_count = 0
    transform_count = 0
    clip_count = 0
    for _event, element in ET.iterparse(path, events=("start",)):
        if root is None:
            root = element
        tag = _local_name(element.tag)
        if tag == "path":
            path_count += 1
        if tag == "clipPath":
            clip_count += 1
        if "transform" in element.attrib:
            transform_count += 1
        style = _style_map(element.attrib.get("style", ""))
        stroke = element.attrib.get("stroke", style.get("stroke", "none"))
        fill = element.attrib.get("fill", style.get("fill", "black"))
        if stroke.strip().lower() != "none":
            stroke_count += 1
            if fill.strip().lower() == "none":
                stroke_only_count += 1

    if root is None:
        raise ValueError("empty_svg")
    view_box = root.attrib.get("viewBox", "").replace(",", " ").split()
    if len(view_box) == 4:
        canvas = [float(view_box[2]), float(view_box[3])]
    else:
        number = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)")

        def dimension(name: str) -> float:
            match = number.match(root.attrib.get(name, ""))
            return float(match.group()) if match else 0.0

        canvas = [dimension("width"), dimension("height")]
    return {
        "canvas_user_units": canvas,
        "path_count": path_count,
        "stroke_count": stroke_count,
        "stroke_only_count": stroke_only_count,
        "transform_count": transform_count,
        "clip_count": clip_count,
    }


def _command_output(args: list[str]) -> str:
    try:
        return subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""


def _processor_name() -> str:
    if sys.platform == "darwin":
        return _command_output(["sysctl", "-n", "machdep.cpu.brand_string"])
    return platform.processor() or platform.machine()


def _memory_bytes() -> int:
    if sys.platform == "darwin":
        value = _command_output(["sysctl", "-n", "hw.memsize"])
        if value.isdigit():
            return int(value)
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except (ImportError, OSError):
        return 0


def _peak_rss_bytes() -> int:
    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024
    except (ImportError, ValueError):
        try:
            import psutil

            return int(psutil.Process().memory_info().rss)
        except (ImportError, OSError):
            return 0


def _system_swap_used_bytes() -> tuple[int, str]:
    if sys.platform == "darwin":
        output = _command_output(["sysctl", "-n", "vm.swapusage"])
        match = re.search(r"used\s*=\s*([0-9.]+)([KMG])", output)
        if match:
            multiplier = {"K": 1024, "M": 1024**2, "G": 1024**3}
            return int(float(match.group(1)) * multiplier[match.group(2)]), (
                "system_vm.swapusage"
            )
    if sys.platform.startswith("linux"):
        values: dict[str, int] = {}
        try:
            for line in Path("/proc/meminfo").read_text("utf-8").splitlines():
                if line.startswith(("SwapTotal:", "SwapFree:")):
                    key, value, _unit = line.split()
                    values[key.rstrip(":")] = int(value) * 1024
            if {"SwapTotal", "SwapFree"} <= values.keys():
                return values["SwapTotal"] - values["SwapFree"], (
                    "system_proc_meminfo"
                )
        except (OSError, ValueError):
            pass
    try:
        import psutil

        return int(psutil.swap_memory().used), "system_psutil"
    except (ImportError, OSError):
        return 0, "unavailable"


def _host_manifest() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "platform_release": platform.release(),
        "machine": platform.machine(),
        "processor": _processor_name(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 1,
        "memory_bytes": _memory_bytes(),
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _rounded(value: float) -> float:
    return round(float(value), 9)


def _geometry_wkb(geometry: Any) -> bytes:
    return bytes(
        shapely.to_wkb(
            geometry,
            byte_order=1,
            include_srid=False,
            output_dimension=2,
        )
    )


def _update_geometry(hasher: Any, geometry: Any) -> None:
    payload = _geometry_wkb(geometry)
    hasher.update(struct.pack("<Q", len(payload)))
    hasher.update(payload)


def _update_json(hasher: Any, value: Any) -> None:
    hasher.update(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def _analysis_fingerprint(analysis: Any) -> str:
    hasher = hashlib.sha256()
    _update_json(
        hasher,
        {
            "bbox": [float(value) for value in analysis.bbox],
            "scale_factor": float(analysis.scale_factor),
            "num_channels": int(analysis.num_channels),
            "num_layers": int(analysis.num_layers),
            "slot_names": list(analysis.slot_names),
        },
    )
    for item in analysis.shape_data:
        _update_json(
            hasher,
            {
                "color": list(item["color"]),
                "source_kind": item.get("source_kind", ""),
            },
        )
        _update_geometry(hasher, item["poly"])
    for item in analysis.clipped_shapes:
        _update_json(
            hasher,
            {
                "color": list(item["color"]),
                "draw_order": int(item.get("draw_order", -1)),
                "native_draw_order": int(item.get("native_draw_order", -1)),
                "native_source_index": int(
                    item.get("native_source_index", -1)
                ),
            },
        )
        _update_geometry(hasher, item["geometry"])
    for item in analysis.matched_shapes:
        _update_json(
            hasher,
            {
                "color": list(item.get("color") or ()),
                "match_color": list(item.get("match_color") or ()),
                "matched_rgb": list(item.get("matched_rgb") or ()),
                "recipe": [int(value) for value in item.get("recipe") or ()],
            },
        )
    _update_geometry(hasher, analysis.silhouette)
    return hasher.hexdigest()


def _polygon_components(geometry: Any) -> list[Any]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [
        component
        for component in geometry.geoms
        if component.geom_type == "Polygon" and not component.is_empty
    ]


def _output_summary(analysis: Any, fingerprint: str) -> dict[str, Any]:
    visible_geometries = [
        item["geometry"] for item in analysis.clipped_shapes
    ]
    silhouette_components = _polygon_components(analysis.silhouette)
    return {
        "geometry_backend": analysis.stage_timings.get("geometry_backend"),
        "native_version": analysis.stage_timings.get("native_version"),
        "native_schema_version": analysis.stage_timings.get(
            "native_schema_version"
        ),
        "native_cache_hit": bool(
            analysis.stage_timings.get("native_cache_hit")
        ),
        "raw_shape_count": len(analysis.shape_data),
        "visible_shape_count": len(analysis.clipped_shapes),
        "matched_shape_count": len(analysis.matched_shapes),
        "silhouette_component_count": len(silhouette_components),
        "silhouette_hole_count": sum(
            len(component.interiors) for component in silhouette_components
        ),
        "coordinate_count": sum(
            int(shapely.get_num_coordinates(geometry))
            for geometry in visible_geometries
        ),
        "source_color_count": len(
            {tuple(item["color"]) for item in analysis.clipped_shapes}
        ),
        "matched_recipe_count": len(
            {
                tuple(int(value) for value in item.get("recipe") or ())
                for item in analysis.matched_shapes
            }
        ),
        "fingerprint": fingerprint,
    }


def _clear_entry_caches(processor: VectorProcessor) -> None:
    if getattr(processor, "_parse_clip_cache_path", None) is not None:
        raise RuntimeError("artifact_cache_must_be_disabled")
    _VECTOR_PARSE_CLIP_CACHE.clear()
    gc.collect()


def _median_stage(stage_runs: list[dict[str, Any]], key: str) -> float:
    return statistics.median(
        max(0.0, float(stage.get(key, 0.0))) for stage in stage_runs
    )


def _measure_complete_entry(
    processor: VectorProcessor,
    svg_path: Path,
    *,
    target_width_mm: float,
    tolerance_mm: float,
    warm_runs: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if warm_runs < 3:
        raise ValueError("warm_runs_must_be_at_least_three")
    processor.sampling_precision = tolerance_mm
    if hasattr(processor, "_parse_clip_cache_path"):
        delattr(processor, "_parse_clip_cache_path")

    _clear_entry_caches(processor)
    warmup = processor.analyze_svg(str(svg_path), target_width_mm)
    if warmup.stage_timings.get("geometry_backend") != "native":
        reason = warmup.stage_timings.get("native_fallback_reason", "unknown")
        raise RuntimeError(f"fixture_did_not_use_native_backend:{reason}")
    fingerprints = {_analysis_fingerprint(warmup)}
    del warmup

    wall_runs: list[float] = []
    stage_runs: list[dict[str, Any]] = []
    output: dict[str, Any] | None = None
    for _run_index in range(warm_runs):
        _clear_entry_caches(processor)
        started = time.perf_counter()
        analysis = processor.analyze_svg(str(svg_path), target_width_mm)
        wall_seconds = time.perf_counter() - started
        if analysis.stage_timings.get("geometry_backend") != "native":
            reason = analysis.stage_timings.get(
                "native_fallback_reason", "unknown"
            )
            raise RuntimeError(f"fixture_did_not_use_native_backend:{reason}")
        if analysis.stage_timings.get("native_cache_hit"):
            raise RuntimeError("benchmark_measured_a_cache_hit")
        fingerprint = _analysis_fingerprint(analysis)
        fingerprints.add(fingerprint)
        wall_runs.append(wall_seconds)
        stage_runs.append(dict(analysis.stage_timings))
        output = _output_summary(analysis, fingerprint)
        del analysis

    if len(fingerprints) != 1 or output is None:
        raise RuntimeError("non_deterministic_vector_analysis")

    native_call_runs = [
        max(0.0, float(stage.get("native_svg_s", 0.0)))
        for stage in stage_runs
    ]
    native_adapter_runs = [
        max(0.0, float(stage.get("native_adapter_s", 0.0)))
        for stage in stage_runs
    ]
    color_match_runs = [
        max(0.0, float(stage.get("color_match_s", 0.0)))
        for stage in stage_runs
    ]
    # VectorProcessor measures ``native_svg_s`` around the complete adapter
    # call, so it already includes the separately reported Shapely conversion.
    # Do not add ``native_adapter_s`` a second time.
    native_geometry_runs = native_call_runs
    orchestration_runs = [
        max(0.0, wall - geometry - color_match)
        for wall, geometry, color_match in zip(
            wall_runs,
            native_geometry_runs,
            color_match_runs,
            strict=True,
        )
    ]
    median_seconds = statistics.median(wall_runs)
    p95_seconds = _percentile(wall_runs, 0.95)
    output["stable_across_runs"] = True
    return (
        {
            "warmup_runs": 1,
            "warm_runs_seconds": [_rounded(value) for value in wall_runs],
            "median_seconds": _rounded(median_seconds),
            "p95_seconds": _rounded(p95_seconds),
            "p95_method": "linear_interpolation_r7",
            "range_seconds": _rounded(max(wall_runs) - min(wall_runs)),
            "native_recorder_seconds": _rounded(
                _median_stage(stage_runs, "native_recorder_s")
            ),
            "native_kernel_seconds": _rounded(
                _median_stage(stage_runs, "native_kernel_s")
            ),
            "native_binding_conversion_seconds": _rounded(
                _median_stage(stage_runs, "native_binding_conversion_s")
            ),
            "native_adapter_conversion_seconds": _rounded(
                _median_stage(stage_runs, "native_adapter_s")
            ),
            "native_geometry_total_seconds": _rounded(
                statistics.median(native_geometry_runs)
            ),
            "color_match_seconds": _rounded(
                statistics.median(color_match_runs)
            ),
            "orchestration_seconds": _rounded(
                statistics.median(orchestration_runs)
            ),
            "cache_policy": {
                "memory_cache_cleared_before_each_run": True,
                "artifact_cache_disabled": True,
            },
            "median_threshold_seconds": 1.0,
            "p95_threshold_seconds": 1.25,
            "median_threshold_passed": median_seconds <= 1.0,
            "p95_threshold_passed": p95_seconds <= 1.25,
        },
        output,
    )


def _verify_real_r4c1(path: Path | None) -> dict[str, Any]:
    evidence_path = (
        REPO_ROOT
        / "native"
        / "lumina-svg-core"
        / "benchmarks"
        / "real_r4c1_capability.json"
    )
    existing = json.loads(evidence_path.read_text(encoding="utf-8"))
    fixture = existing["fixture"]
    output = existing["output"]
    record: dict[str, Any] = {
        "classification": "real_r4c1",
        "path": "private/R4C1.svg",
        "sha256": fixture["sha256"],
        "byte_size": fixture["byte_size"],
        "status": output["status"],
        "reason_code": output["reason_code"],
        "native_by_default_ready": False,
        "source": "checked_in_standalone_capability_evidence",
    }
    if path is None:
        return record

    payload = path.read_bytes()
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != REAL_R4C1_SHA256:
        raise ValueError(f"unexpected_real_r4c1_sha256:{actual_sha256}")
    started = time.perf_counter()
    outcome = native_svg_adapter.analyze_native_svg(
        str(path), 111.0, 0.02
    )
    elapsed = time.perf_counter() - started
    if not isinstance(outcome, NativeSvgFallback):
        raise RuntimeError("real_r4c1_unexpectedly_supported")
    if outcome.reason_code != "unsupported_vector_effect":
        raise RuntimeError(
            f"real_r4c1_unexpected_reason:{outcome.reason_code}"
        )
    record.update(
        {
            "byte_size": len(payload),
            "reason_code": outcome.reason_code,
            "source": "verified_local_private_fixture",
            "capability_check_seconds": _rounded(elapsed),
            "structure": _fixture_structure(path),
        }
    )
    return record


def _parse_search_root(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected LABEL=PATH")
    label, raw_path = value.split("=", 1)
    if not label or not raw_path:
        raise argparse.ArgumentTypeError("expected LABEL=PATH")
    return label, Path(raw_path).expanduser().resolve()


def _find_large_svg_files(
    search_roots: list[tuple[str, Path]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for label, root in search_roots:
        if not root.exists():
            continue
        try:
            candidates = root.rglob("*.svg")
            for candidate in candidates:
                try:
                    byte_size = candidate.stat().st_size
                except OSError:
                    continue
                if byte_size < LARGE_REGRESSION_MINIMUM_BYTES:
                    continue
                matches.append(
                    {
                        "root": label,
                        "relative_path": candidate.relative_to(root).as_posix(),
                        "byte_size": byte_size,
                        "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                    }
                )
        except OSError:
            continue
    return sorted(
        matches,
        key=lambda item: (item["root"], item["relative_path"]),
    )


def _large_regression_record(
    search_roots: list[tuple[str, Path]],
    explicit_path: Path | None,
    processor: VectorProcessor,
    *,
    target_width_mm: float,
    tolerance_mm: float,
    warm_runs: int,
) -> dict[str, Any]:
    matches = _find_large_svg_files(search_roots)
    if explicit_path is None and matches:
        raise RuntimeError(
            "large_regression_found; rerun with --large-svg PATH:"
            + json.dumps(matches, sort_keys=True)
        )
    base_record = {
        "classification": "large_regression",
        "minimum_byte_size": LARGE_REGRESSION_MINIMUM_BYTES,
        "searched_roots": [label for label, _path in search_roots],
        "matching_files": matches,
        "rss_threshold_bytes": 2 * 1024**3,
        "swap_delta_threshold_bytes": 256 * 1024**2,
    }
    if explicit_path is None:
        return {
            **base_record,
            "status": "unavailable",
            "matching_files": [],
            "note": (
                "No SVG at or above 50 MiB was found; the 3.77 MB proxy and "
                "14.47 MB real R4C1 fixture were not substituted."
            ),
        }

    large_path = explicit_path.resolve()
    byte_size = large_path.stat().st_size
    if byte_size < LARGE_REGRESSION_MINIMUM_BYTES:
        raise ValueError(f"large_regression_is_too_small:{byte_size}")
    swap_before, swap_source = _system_swap_used_bytes()
    measurement, output = _measure_complete_entry(
        processor,
        large_path,
        target_width_mm=target_width_mm,
        tolerance_mm=tolerance_mm,
        warm_runs=warm_runs,
    )
    swap_after, swap_after_source = _system_swap_used_bytes()
    if swap_source != swap_after_source:
        swap_source = f"{swap_source}->{swap_after_source}"
    peak_rss_bytes = _peak_rss_bytes()
    swap_delta_bytes = max(0, swap_after - swap_before)
    return {
        **base_record,
        "status": "measured",
        "path": _relative_repo_path(large_path),
        "byte_size": byte_size,
        "sha256": hashlib.sha256(large_path.read_bytes()).hexdigest(),
        "structure": _fixture_structure(large_path),
        "measurement": measurement,
        "output": output,
        "peak_rss_bytes": peak_rss_bytes,
        "swap_delta_bytes": swap_delta_bytes,
        "swap_measurement": swap_source,
        "rss_threshold_passed": peak_rss_bytes <= 2 * 1024**3,
        "swap_delta_threshold_passed": swap_delta_bytes <= 256 * 1024**2,
        "note": (
            "Measured separately from the public proxy and real R4C1 fixture."
        ),
    }


def _relative_repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _benchmark_manifest(args: argparse.Namespace) -> dict[str, Any]:
    svg_path = args.svg.resolve()
    lut_path = args.lut.resolve()
    fixture_bytes = svg_path.read_bytes()
    lut_bytes = lut_path.read_bytes()
    processor = VectorProcessor(str(lut_path), "4-Color (RYBW)")
    swap_before, swap_source = _system_swap_used_bytes()
    measurement, output = _measure_complete_entry(
        processor,
        svg_path,
        target_width_mm=args.target_width_mm,
        tolerance_mm=args.tolerance_mm,
        warm_runs=args.warm_runs,
    )
    swap_after, swap_after_source = _system_swap_used_bytes()
    if swap_source != swap_after_source:
        swap_source = f"{swap_source}->{swap_after_source}"
    measurement.update(
        {
            "peak_rss_bytes": _peak_rss_bytes(),
            "swap_delta_bytes": max(0, swap_after - swap_before),
            "swap_measurement": swap_source,
        }
    )
    return {
        "schema_version": 1,
        "entrypoint": "core.vector_engine.VectorProcessor.analyze_svg",
        "fixture": {
            "path": _relative_repo_path(svg_path),
            "classification": "proxy",
            "sha256": hashlib.sha256(fixture_bytes).hexdigest(),
            "byte_size": len(fixture_bytes),
            **_fixture_structure(svg_path),
        },
        "lut": {
            "path": _relative_repo_path(lut_path),
            "sha256": hashlib.sha256(lut_bytes).hexdigest(),
            "byte_size": len(lut_bytes),
            "color_mode": "4-Color (RYBW)",
        },
        "host": _host_manifest(),
        "parameters": {
            "target_width_mm": args.target_width_mm,
            "tolerance_mm": args.tolerance_mm,
            "build_type": "Release",
            "openmp_enabled": False,
            "caller_threads": 1,
        },
        "measurement": measurement,
        "output": output,
        "real_r4c1": _verify_real_r4c1(args.real_r4c1),
        "large_regression": _large_regression_record(
            args.large_search_root,
            args.large_svg,
            processor,
            target_width_mm=args.target_width_mm,
            tolerance_mm=args.tolerance_mm,
            warm_runs=args.warm_runs,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--svg",
        type=Path,
        default=REPO_ROOT / "test_images" / "benchmark.svg",
    )
    parser.add_argument(
        "--lut",
        type=Path,
        default=(
            REPO_ROOT
            / "lut-preset"
            / "bambulab"
            / "bambulab_pla_basic_rybw.npy"
        ),
    )
    parser.add_argument("--target-width-mm", type=float, default=111.0)
    parser.add_argument("--tolerance-mm", type=float, default=0.02)
    parser.add_argument("--warm-runs", type=int, default=3)
    parser.add_argument("--real-r4c1", type=Path)
    parser.add_argument(
        "--large-svg",
        type=Path,
        help="Explicit >=50 MiB regression SVG to measure when available.",
    )
    parser.add_argument(
        "--large-search-root",
        action="append",
        type=_parse_search_root,
        required=True,
        metavar="LABEL=PATH",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            REPO_ROOT / "progress" / "native-svg-fast-path-benchmark.json"
        ),
    )
    args = parser.parse_args()
    manifest = _benchmark_manifest(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
