"""Measure the complete public native SVG analysis entry point."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import statistics
import subprocess
import sys
from pathlib import Path
from time import perf_counter
from typing import Any
import xml.etree.ElementTree as ET

import lumina_svg_core

from fingerprint import result_fingerprint


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
    transform_count = 0
    clip_count = 0
    for event, element in ET.iterparse(path, events=("start",)):
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
        if stroke.strip().lower() != "none":
            stroke_count += 1

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
    }


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 9)


def benchmark(
    path: Path,
    target_width_mm: float,
    tolerance_mm: float,
    warm_runs: int,
    classification: str = "explicit_supported_fixture",
) -> dict[str, Any]:
    if warm_runs < 3:
        raise ValueError("warm_runs_must_be_at_least_three")
    structure = _fixture_structure(path)
    swap_before, swap_source = _system_swap_used_bytes()

    warmup = lumina_svg_core.analyze_svg(
        path, target_width_mm, tolerance_mm
    )
    if warmup.status != "supported":
        raise RuntimeError(f"unsupported_fixture:{warmup.reason_code}")

    elapsed_values: list[float] = []
    recorder_values: list[float] = []
    kernel_values: list[float] = []
    conversion_values: list[float] = []
    fingerprints: set[str] = set()
    result = warmup
    for _ in range(warm_runs):
        started = perf_counter()
        result = lumina_svg_core.analyze_svg(
            path, target_width_mm, tolerance_mm
        )
        elapsed_values.append(perf_counter() - started)
        if result.status != "supported":
            raise RuntimeError(f"unsupported_fixture:{result.reason_code}")
        recorder_values.append(result.recorder_seconds)
        kernel_values.append(result.kernel_seconds)
        conversion_values.append(result.result_conversion_seconds)
        fingerprints.add(result_fingerprint(result))
    if len(fingerprints) != 1:
        raise RuntimeError("non_deterministic_output")

    swap_after, swap_after_source = _system_swap_used_bytes()
    if swap_after_source != swap_source:
        swap_source = f"{swap_source}->{swap_after_source}"
    public_median = _median(elapsed_values)
    return {
        "schema_version": 2,
        "fixture": {
            "path": path.as_posix(),
            "classification": classification,
            "byte_size": path.stat().st_size,
            **structure,
        },
        "host": _host_manifest(),
        "parameters": {
            "target_width_mm": target_width_mm,
            "tolerance_mm": tolerance_mm,
        },
        "measurement": {
            "warmup_runs": 1,
            "warm_runs_seconds": [round(value, 9) for value in elapsed_values],
            "median_seconds": public_median,
            "range_seconds": round(
                max(elapsed_values) - min(elapsed_values), 9
            ),
            "public_entrypoint_seconds": public_median,
            "recorder_seconds": _median(recorder_values),
            "kernel_seconds": _median(kernel_values),
            "result_conversion_seconds": _median(conversion_values),
            "peak_rss_bytes": _peak_rss_bytes(),
            "swap_delta_bytes": max(0, swap_after - swap_before),
            "swap_measurement": swap_source,
            "threshold_seconds": 1.0,
            "threshold_passed": public_median <= 1.0,
        },
        "output": {
            "status": result.status,
            "region_count": result.visible.component_count,
            "hole_count": result.visible.hole_count,
            "coordinate_count": len(result.visible.coordinates),
            "material_count": result.visible.geometry_count,
            "fingerprint": fingerprints.pop(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--svg", required=True, type=Path)
    parser.add_argument("--target-width-mm", type=float, default=111.0)
    parser.add_argument("--tolerance-mm", type=float, default=0.02)
    parser.add_argument("--warm-runs", type=int, default=3)
    parser.add_argument(
        "--classification",
        default="explicit_supported_fixture",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = benchmark(
        args.svg,
        args.target_width_mm,
        args.tolerance_mm,
        args.warm_runs,
        args.classification,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
