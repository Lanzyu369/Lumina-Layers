#!/usr/bin/env python3
"""Profile optional native SVG vector meshing across an SVG corpus."""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.vector_engine import VectorProcessor  # noqa: E402
from scripts.profile_vector_native_mesh import (  # noqa: E402
    _build_repeated,
    _compare_metrics,
    _evaluate_quality_gate,
    _scene_metrics,
)


NATIVE_STAT_FIELDS = (
    "native_group_count",
    "native_input_paths",
    "native_path_cache_hits",
    "native_path_cache_misses",
    "native_meshes",
    "native_coalesced_meshes",
    "native_coalesced_slots",
    "native_output_meshes",
    "fallback_groups",
    "native_seconds",
    "fallback_seconds",
    "mesh_convert_seconds",
    "pack_seconds",
    "native_split_retries",
    "native_split_group_count",
    "native_split_meshes",
    "native_split_fallback_groups",
    "native_merged_fallback_groups",
    "native_merged_fallback_polygons",
    "native_merged_fallback_input_paths",
    "native_merged_fallback_input_holes",
    "native_merged_fallback_skipped_groups",
    "surface_validation_seconds",
    "native_surface_checked",
    "native_surface_rejects",
)
NATIVE_INT_FIELDS = {
    "native_group_count",
    "native_input_paths",
    "native_path_cache_hits",
    "native_path_cache_misses",
    "native_meshes",
    "native_coalesced_meshes",
    "native_coalesced_slots",
    "native_output_meshes",
    "fallback_groups",
    "native_split_retries",
    "native_split_group_count",
    "native_split_meshes",
    "native_split_fallback_groups",
    "native_merged_fallback_groups",
    "native_merged_fallback_polygons",
    "native_merged_fallback_input_paths",
    "native_merged_fallback_input_holes",
    "native_merged_fallback_skipped_groups",
    "native_surface_checked",
    "native_surface_rejects",
}
FALLBACK_REASON_PREFIX = "fallback_reason_"
NATIVE_IMPORT_WARMUP_DEFAULT = {
    "enabled": False,
    "available": False,
    "seconds": 0.0,
    "module_file": "",
    "triangulation_area_guard": False,
    "capability_error_type": "",
    "error_type": "",
    "error_message": "",
}


def _surface_validation_requested(args: argparse.Namespace) -> bool:
    if bool(getattr(args, "validate_native_surface", False)):
        return True
    return str(os.environ.get("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _warm_native_module_import(args: argparse.Namespace) -> dict[str, Any]:
    """Optionally import the native module before corpus timing starts."""

    if not bool(getattr(args, "warm_native_import", False)):
        return dict(NATIVE_IMPORT_WARMUP_DEFAULT)

    t0 = time.perf_counter()
    try:
        module = importlib.import_module("clipper2_batch")
    except Exception as exc:
        return {
            **NATIVE_IMPORT_WARMUP_DEFAULT,
            "enabled": True,
            "seconds": time.perf_counter() - t0,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }

    capability_error_type = ""
    capabilities: Any = {}
    capabilities_fn = getattr(module, "native_mesh_capabilities", None)
    if callable(capabilities_fn):
        try:
            capabilities = capabilities_fn()
        except Exception as exc:
            capability_error_type = type(exc).__name__
            capabilities = {}

    return {
        **NATIVE_IMPORT_WARMUP_DEFAULT,
        "enabled": True,
        "available": True,
        "seconds": time.perf_counter() - t0,
        "module_file": str(getattr(module, "__file__", "") or ""),
        "triangulation_area_guard": bool(
            isinstance(capabilities, dict) and capabilities.get("triangulation_area_guard")
        ),
        "capability_error_type": capability_error_type,
    }


def discover_svg_files(path: Path) -> list[Path]:
    """Return SVG files under ``path`` in deterministic path order."""

    path = Path(path)
    if path.is_file():
        return [path] if path.suffix.lower() == ".svg" else []
    if not path.exists():
        return []
    files = [item for item in path.rglob("*") if item.is_file() and item.suffix.lower() == ".svg"]
    return sorted(files, key=lambda item: str(item))


def sample_summary_row(sample: dict[str, Any]) -> dict[str, Any]:
    svg_name = str(sample.get("svg_name", ""))
    if sample.get("status") != "ok":
        error_type = str(sample.get("error_type", "Error"))
        error_message = str(sample.get("error_message", "unknown error"))
        row = {
            "svg_name": svg_name,
            "status": "ERROR",
            "error": f"{error_type}: {error_message}",
            "shape_count": 0,
            "analyze_seconds": 0.0,
            "parse_seconds": 0.0,
            "occlusion_seconds": 0.0,
            "color_match_seconds": 0.0,
            "analyze_unaccounted_seconds": 0.0,
            "baseline_build_seconds": 0.0,
            "native_build_seconds": 0.0,
            "build_speedup": 0.0,
            "baseline_extrude_seconds": 0.0,
            "native_extrude_seconds": 0.0,
            "extrude_speedup": 0.0,
            "native_meshes": 0,
            "fallback_groups": 0,
            "volume_rel_delta": 0.0,
            "area_rel_delta": 0.0,
            "quality_failures": f"{error_type}: {error_message}",
        }
        row.update({field: 0 if field in NATIVE_INT_FIELDS else 0.0 for field in NATIVE_STAT_FIELDS})
        row["fallback_reasons"] = ""
        return row

    baseline = sample["variants"]["baseline"]
    native = sample["variants"]["native_enabled"]
    baseline_build = float(baseline["median_seconds"])
    native_build = float(native["median_seconds"])
    baseline_extrude = float(baseline["stage_timings"].get("extrude_bottom_s", 0.0))
    native_extrude = float(native["stage_timings"].get("extrude_bottom_s", 0.0))
    analysis = sample.get("analysis", {})
    analyze_seconds = float(analysis.get("seconds", 0.0))
    analyze_timings = analysis.get("stage_timings", {}) or {}
    parse_seconds = float(analyze_timings.get("parse_s", 0.0))
    occlusion_seconds = float(analyze_timings.get("occlusion_s", 0.0))
    color_match_seconds = float(analyze_timings.get("color_match_s", 0.0))
    analyze_unaccounted = max(
        0.0,
        analyze_seconds - parse_seconds - occlusion_seconds - color_match_seconds,
    )
    quality_gate = sample.get("quality_gate", {})
    comparison = sample.get("comparison", {}).get("totals", {})
    native_stats = native.get("native_stats", {})
    fallback_reason_counts = {
        str(key.removeprefix(FALLBACK_REASON_PREFIX)): int(value)
        for key, value in native_stats.items()
        if str(key).startswith(FALLBACK_REASON_PREFIX) and int(value or 0) > 0
    }
    row = {
        "svg_name": svg_name,
        "status": "PASS" if quality_gate.get("passed") else "FAIL",
        "error": "",
        "shape_count": int(analysis.get("shape_count", 0)),
        "analyze_seconds": analyze_seconds,
        "parse_seconds": parse_seconds,
        "occlusion_seconds": occlusion_seconds,
        "color_match_seconds": color_match_seconds,
        "analyze_unaccounted_seconds": analyze_unaccounted,
        "baseline_build_seconds": baseline_build,
        "native_build_seconds": native_build,
        "build_speedup": baseline_build / max(native_build, 1e-9),
        "baseline_extrude_seconds": baseline_extrude,
        "native_extrude_seconds": native_extrude,
        "extrude_speedup": baseline_extrude / max(native_extrude, 1e-9),
        "native_meshes": int(native_stats.get("native_meshes", 0)),
        "fallback_groups": int(native_stats.get("fallback_groups", 0)),
        "volume_rel_delta": float(comparison.get("volume", {}).get("rel_delta", 0.0)),
        "area_rel_delta": float(comparison.get("area", {}).get("rel_delta", 0.0)),
        "quality_failures": "; ".join(str(item) for item in quality_gate.get("failures", [])),
    }
    for field in NATIVE_STAT_FIELDS:
        value = native_stats.get(field, 0.0)
        row[field] = int(value) if field in NATIVE_INT_FIELDS else float(value)
    for key, value in native_stats.items():
        key_str = str(key)
        if key_str.startswith(FALLBACK_REASON_PREFIX):
            row[key_str] = int(value or 0)
    row["fallback_reasons"] = ", ".join(
        f"{reason}={count}" for reason, count in sorted(fallback_reason_counts.items())
    )
    return row


def _safe_output_name(index: int, svg_path: Path) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in svg_path.stem)
    safe = safe.strip("_") or "svg"
    return f"{index:03d}_{safe}.json"


def _profile_svg(svg_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    processor = VectorProcessor(str(args.lut), args.color_mode)
    t0 = time.perf_counter()
    analysis = processor.analyze_svg(str(svg_path), target_width_mm=args.target_width_mm)
    analyze_seconds = time.perf_counter() - t0

    baseline_scene, baseline_seconds, baseline_timings, _ = _build_repeated(
        processor,
        analysis,
        repeats=args.repeats,
        thickness_mm=args.thickness_mm,
        structure_mode=args.structure_mode,
        native_enabled=False,
    )
    native_scene, native_seconds, native_timings, native_stats = _build_repeated(
        processor,
        analysis,
        repeats=args.repeats,
        thickness_mm=args.thickness_mm,
        structure_mode=args.structure_mode,
        native_enabled=True,
    )

    baseline_metrics = _scene_metrics(baseline_scene)
    native_metrics = _scene_metrics(native_scene)
    comparison = _compare_metrics(baseline_metrics, native_metrics)
    report: dict[str, Any] = {
        "status": "ok",
        "svg_name": svg_path.name,
        "svg_path": str(svg_path.resolve()),
        "input": {
            "target_width_mm": float(args.target_width_mm),
            "thickness_mm": float(args.thickness_mm),
            "structure_mode": str(args.structure_mode),
            "color_mode": str(args.color_mode),
            "repeats": int(args.repeats),
            "native_surface_validation": _surface_validation_requested(args),
        },
        "analysis": {
            "seconds": analyze_seconds,
            "stage_timings": dict(getattr(analysis, "stage_timings", {}) or {}),
            "shape_count": len(getattr(analysis, "matched_shapes", []) or []),
            "num_layers": int(getattr(analysis, "num_layers", 0) or 0),
            "slot_names": list(getattr(analysis, "slot_names", []) or []),
        },
        "variants": {
            "baseline": {
                "seconds": baseline_seconds,
                "median_seconds": statistics.median(baseline_seconds),
                "stage_timings": baseline_timings,
                "metrics": baseline_metrics,
            },
            "native_enabled": {
                "seconds": native_seconds,
                "median_seconds": statistics.median(native_seconds),
                "stage_timings": native_timings,
                "native_stats": native_stats,
                "metrics": native_metrics,
            },
        },
        "comparison": comparison,
    }
    report["quality_gate"] = _evaluate_quality_gate(report, args)
    return report


def _build_corpus_report(
    *,
    input_path: Path,
    samples: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    args: argparse.Namespace,
    native_warmup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ok_rows = [row for row in rows if row["status"] in {"PASS", "FAIL"}]
    pass_rows = [row for row in rows if row["status"] == "PASS"]
    fail_rows = [row for row in rows if row["status"] == "FAIL"]
    error_rows = [row for row in rows if row["status"] == "ERROR"]
    baseline_total = sum(float(row["baseline_build_seconds"]) for row in ok_rows)
    native_total = sum(float(row["native_build_seconds"]) for row in ok_rows)
    analyze_total = sum(float(row["analyze_seconds"]) for row in ok_rows)
    baseline_extrude_total = sum(float(row["baseline_extrude_seconds"]) for row in ok_rows)
    native_extrude_total = sum(float(row["native_extrude_seconds"]) for row in ok_rows)
    analyze_stage_totals = {
        "parse": sum(float(row.get("parse_seconds", 0.0)) for row in ok_rows),
        "occlusion": sum(float(row.get("occlusion_seconds", 0.0)) for row in ok_rows),
        "color_match": sum(float(row.get("color_match_seconds", 0.0)) for row in ok_rows),
        "unaccounted": sum(float(row.get("analyze_unaccounted_seconds", 0.0)) for row in ok_rows),
    }
    native_stat_keys = set(NATIVE_STAT_FIELDS)
    for row in ok_rows:
        native_stat_keys.update(
            str(key) for key in row.keys() if str(key).startswith(FALLBACK_REASON_PREFIX)
        )
    native_stat_totals = {
        key: sum(float(row.get(key, 0.0)) for row in ok_rows)
        for key in sorted(native_stat_keys)
    }
    native_warmup_info = dict(native_warmup or NATIVE_IMPORT_WARMUP_DEFAULT)
    return {
        "input": {
            "path": str(input_path.resolve()),
            "lut": str(Path(args.lut).resolve()),
            "target_width_mm": float(args.target_width_mm),
            "thickness_mm": float(args.thickness_mm),
            "structure_mode": str(args.structure_mode),
            "color_mode": str(args.color_mode),
            "repeats": int(args.repeats),
            "native_surface_validation": _surface_validation_requested(args),
            "warm_native_import": bool(getattr(args, "warm_native_import", False)),
        },
        "summary": {
            "sample_count": len(samples),
            "pass_count": len(pass_rows),
            "fail_count": len(fail_rows),
            "error_count": len(error_rows),
            "native_surface_validation": _surface_validation_requested(args),
            "native_import_warmup": native_warmup_info,
            "analyze_total_seconds": analyze_total,
            "analyze_stage_totals_seconds": analyze_stage_totals,
            "baseline_build_total_seconds": baseline_total,
            "native_build_total_seconds": native_total,
            "build_speedup": baseline_total / max(native_total, 1e-9),
            "baseline_extrude_total_seconds": baseline_extrude_total,
            "native_extrude_total_seconds": native_extrude_total,
            "extrude_speedup": baseline_extrude_total / max(native_extrude_total, 1e-9),
            "native_stat_totals": native_stat_totals,
        },
        "rows": rows,
        "samples": samples,
    }


def _write_corpus_png(report: dict[str, Any], out_dir: Path) -> Path | None:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    rows = report["rows"]
    height = max(520, 170 + len(rows) * 28)
    width = 1200
    path = out_dir / "vector_native_mesh_corpus.png"
    image = Image.new("RGB", (width, height), (248, 250, 252))
    draw = ImageDraw.Draw(image)
    ink = (15, 23, 42)
    muted = (71, 85, 105)
    grid = (203, 213, 225)
    pass_color = (22, 163, 74)
    fail_color = (220, 38, 38)
    native_color = (37, 99, 235)

    summary = report["summary"]
    draw.text((34, 26), "Vector Native Mesh Corpus", fill=ink)
    draw.text(
        (34, 54),
        (
            f"samples={summary['sample_count']} | pass={summary['pass_count']} | "
            f"fail={summary['fail_count']} | error={summary['error_count']}"
        ),
        fill=muted,
    )
    draw.text(
        (34, 82),
        (
            f"build speedup={summary['build_speedup']:.2f}x | "
            f"extrude speedup={summary['extrude_speedup']:.2f}x | "
            f"analyze total={summary['analyze_total_seconds']:.1f}s"
        ),
        fill=ink,
    )

    left = 420
    bar_w = 560
    top = 140
    max_speedup = max([float(row["build_speedup"]) for row in rows] + [1.0])
    for idx, row in enumerate(rows):
        y = top + idx * 28
        label = str(row["svg_name"])
        if len(label) > 48:
            label = label[:45] + "..."
        status_color = pass_color if row["status"] == "PASS" else fail_color
        draw.text((34, y), row["status"], fill=status_color)
        draw.text((96, y), label, fill=ink)
        draw.rectangle((left, y + 2, left + bar_w, y + 16), fill=(226, 232, 240))
        speedup = float(row["build_speedup"])
        width_px = int(bar_w * min(speedup / max(max_speedup, 1e-9), 1.0))
        draw.rectangle((left, y + 2, left + width_px, y + 16), fill=native_color)
        draw.text((left + bar_w + 16, y), f"{speedup:.2f}x", fill=ink)
        draw.text((left + bar_w + 86, y), f"fb={row['fallback_groups']}", fill=muted)
    draw.line((34, top - 12, width - 34, top - 12), fill=grid, width=1)
    image.save(path)
    return path


def write_corpus_outputs(report: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "vector_native_mesh_corpus.json"
    csv_path = out_dir / "vector_native_mesh_corpus.csv"
    md_path = out_dir / "vector_native_mesh_corpus.md"
    png_path = _write_corpus_png(report, out_dir)

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = report["rows"]
    if rows:
        fieldnames = list(rows[0].keys())
        known = set(fieldnames)
        for row in rows[1:]:
            for key in row.keys():
                if key not in known:
                    fieldnames.append(key)
                    known.add(key)
    else:
        fieldnames = ["svg_name", "status"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary = report["summary"]
    native_totals = summary.get("native_stat_totals", {}) or {}
    native_warmup = summary.get("native_import_warmup", {}) or {}
    native_warmup_status = "off"
    if native_warmup.get("enabled"):
        if native_warmup.get("available"):
            guard = "present" if native_warmup.get("triangulation_area_guard") else "missing"
            native_warmup_status = (
                f"on; available=yes; seconds={float(native_warmup.get('seconds', 0.0)):.6f}; "
                f"guard={guard}"
            )
        else:
            native_warmup_status = (
                f"on; available=no; seconds={float(native_warmup.get('seconds', 0.0)):.6f}; "
                f"error={native_warmup.get('error_type', '') or 'unknown'}"
            )
    fallback_reason_totals = {
        key.removeprefix(FALLBACK_REASON_PREFIX): value
        for key, value in native_totals.items()
        if str(key).startswith(FALLBACK_REASON_PREFIX) and float(value or 0.0) > 0.0
    }
    fallback_reason_text = ", ".join(
        f"{reason}={int(value)}" for reason, value in sorted(fallback_reason_totals.items())
    ) or "none"
    lines = [
        "# Vector Native Mesh Corpus",
        "",
        f"- Samples: {summary['sample_count']}",
        f"- PASS / FAIL / ERROR: {summary['pass_count']} / {summary['fail_count']} / {summary['error_count']}",
        f"- Native surface validation: {'on' if summary.get('native_surface_validation') else 'off'}",
        f"- Native import warmup: {native_warmup_status}",
        f"- Analyze total: {summary['analyze_total_seconds']:.3f}s",
        f"- Analyze parse total: {summary['analyze_stage_totals_seconds']['parse']:.3f}s",
        f"- Analyze occlusion total: {summary['analyze_stage_totals_seconds']['occlusion']:.3f}s",
        f"- Analyze color match total: {summary['analyze_stage_totals_seconds']['color_match']:.3f}s",
        f"- Analyze unaccounted total: {summary['analyze_stage_totals_seconds']['unaccounted']:.3f}s",
        f"- Baseline build total: {summary['baseline_build_total_seconds']:.3f}s",
        f"- Native-enabled build total: {summary['native_build_total_seconds']:.3f}s",
        f"- Build speedup: {summary['build_speedup']:.3f}x",
        f"- Baseline extrude total: {summary['baseline_extrude_total_seconds']:.3f}s",
        f"- Native extrude total: {summary['native_extrude_total_seconds']:.3f}s",
        f"- Extrude speedup: {summary['extrude_speedup']:.3f}x",
        f"- Native internal total: native={native_totals.get('native_seconds', 0.0):.3f}s, "
        f"fallback={native_totals.get('fallback_seconds', 0.0):.3f}s, "
        f"convert={native_totals.get('mesh_convert_seconds', 0.0):.3f}s, "
        f"pack={native_totals.get('pack_seconds', 0.0):.3f}s, "
        f"surface_check={native_totals.get('surface_validation_seconds', 0.0):.3f}s",
        f"- Native groups: total={int(native_totals.get('native_group_count', 0))}, "
        f"path_cache={int(native_totals.get('native_path_cache_hits', 0))}/"
        f"{int(native_totals.get('native_path_cache_misses', 0))} hit/miss, "
        f"native_meshes={int(native_totals.get('native_meshes', 0))}, "
        f"coalesced_meshes={int(native_totals.get('native_coalesced_meshes', 0))}, "
        f"output_meshes={int(native_totals.get('native_output_meshes', 0))}, "
        f"fallback_groups={int(native_totals.get('fallback_groups', 0))}, "
        f"split_retries={int(native_totals.get('native_split_retries', 0))}, "
        f"split_meshes={int(native_totals.get('native_split_meshes', 0))}, "
        f"split_fallbacks={int(native_totals.get('native_split_fallback_groups', 0))}, "
        f"fallback_reasons={fallback_reason_text}",
        "",
        "## Per-Sample Results",
        "",
        "| status | svg | shapes | analyze_s | parse_s | occlusion_s | match_s | build_base_s | build_native_s | speedup | extrude_speedup | native/fallback | volume_delta | area_delta |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| "
            f"{row['status']} | `{row['svg_name']}` | {row['shape_count']} | "
            f"{row['analyze_seconds']:.3f} | {row['parse_seconds']:.3f} | "
            f"{row['occlusion_seconds']:.3f} | {row['color_match_seconds']:.3f} | "
            f"{row['baseline_build_seconds']:.3f} | "
            f"{row['native_build_seconds']:.3f} | {row['build_speedup']:.3f}x | "
            f"{row['extrude_speedup']:.3f}x | {row['native_meshes']}/{row['fallback_groups']} | "
            f"{row['volume_rel_delta']:.6%} | {row['area_rel_delta']:.6%} |"
        )
    slow_rows = sorted(rows, key=lambda item: float(item["baseline_build_seconds"]), reverse=True)[:5]
    low_speedup_rows = sorted(rows, key=lambda item: float(item["build_speedup"]))[:5]
    slow_analyze_rows = sorted(rows, key=lambda item: float(item["analyze_seconds"]), reverse=True)[:5]
    slow_parse_rows = sorted(rows, key=lambda item: float(item["parse_seconds"]), reverse=True)[:5]
    slow_occlusion_rows = sorted(rows, key=lambda item: float(item["occlusion_seconds"]), reverse=True)[:5]
    fallback_rows = sorted(rows, key=lambda item: int(item.get("fallback_groups", 0)), reverse=True)[:5]
    lines.extend(["", "## Slowest Analyze", ""])
    lines.extend(
        f"- `{row['svg_name']}`: analyze={row['analyze_seconds']:.3f}s, "
        f"parse={row['parse_seconds']:.3f}s, occlusion={row['occlusion_seconds']:.3f}s"
        for row in slow_analyze_rows
    )
    lines.extend(["", "## Slowest Parse", ""])
    lines.extend(
        f"- `{row['svg_name']}`: parse={row['parse_seconds']:.3f}s, shapes={row['shape_count']}"
        for row in slow_parse_rows
    )
    lines.extend(["", "## Slowest Occlusion", ""])
    lines.extend(
        f"- `{row['svg_name']}`: occlusion={row['occlusion_seconds']:.3f}s, shapes={row['shape_count']}"
        for row in slow_occlusion_rows
    )
    lines.extend(["", "## Slowest Baseline Build", ""])
    lines.extend(
        f"- `{row['svg_name']}`: {row['baseline_build_seconds']:.3f}s baseline, "
        f"{row['native_build_seconds']:.3f}s native, {row['build_speedup']:.3f}x"
        for row in slow_rows
    )
    lines.extend(["", "## Lowest Build Speedup", ""])
    lines.extend(
        f"- `{row['svg_name']}`: {row['build_speedup']:.3f}x, fallback={row['fallback_groups']}"
        for row in low_speedup_rows
    )
    lines.extend(["", "## Most Fallback Groups", ""])
    lines.extend(
        f"- `{row['svg_name']}`: fallback={row.get('fallback_groups', 0)}, "
        f"reasons={row.get('fallback_reasons', '') or 'none'}"
        for row in fallback_rows
    )
    failed_rows = [row for row in rows if row["status"] != "PASS"]
    if failed_rows:
        lines.extend(["", "## Failures", ""])
        for row in failed_rows:
            detail = row["quality_failures"] or row["error"]
            lines.append(f"- `{row['svg_name']}`: {row['status']} {detail}")
    lines.extend(
        [
            "",
            f"JSON: `{json_path}`",
            f"CSV: `{csv_path}`",
        ]
    )
    if png_path is not None:
        lines.append(f"Visual: `{png_path}`")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")

    outputs = {"json": str(json_path), "csv": str(csv_path), "markdown": str(md_path)}
    if png_path is not None:
        outputs["png"] = str(png_path)
    return outputs


def run(args: argparse.Namespace) -> int:
    if bool(getattr(args, "validate_native_surface", False)):
        os.environ["LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE"] = "1"
    input_path = Path(args.input)
    svg_files = discover_svg_files(input_path)
    out_dir = Path(args.out_dir).resolve()
    sample_dir = out_dir / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    native_warmup = _warm_native_module_import(args)
    if not svg_files:
        print(f"No SVG files found under {input_path}", file=sys.stderr)
        return 2

    samples: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for index, svg_path in enumerate(svg_files, start=1):
        print(f"[{index}/{len(svg_files)}] {svg_path}")
        try:
            sample = _profile_svg(svg_path, args)
        except Exception as exc:
            sample = {
                "status": "error",
                "svg_name": svg_path.name,
                "svg_path": str(svg_path.resolve()),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        sample_path = sample_dir / _safe_output_name(index, svg_path)
        sample["sample_report"] = str(sample_path)
        sample_path.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
        samples.append(sample)
        rows.append(sample_summary_row(sample))

    report = _build_corpus_report(
        input_path=input_path,
        samples=samples,
        rows=rows,
        args=args,
        native_warmup=native_warmup,
    )
    outputs = write_corpus_outputs(report, out_dir)
    print(outputs["markdown"])

    has_failures = any(row["status"] != "PASS" for row in rows)
    return 0 if args.allow_failures or not has_failures else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--lut", type=Path, default=REPO_ROOT / "lut-preset" / "Custom" / "lumina_lut.json")
    parser.add_argument("--color-mode", default="4-Color (RYBW)")
    parser.add_argument("--target-width-mm", type=float, default=80.0)
    parser.add_argument("--thickness-mm", type=float, default=1.6)
    parser.add_argument("--structure-mode", default="Single-sided")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / ".scratch" / "vector_native_mesh_corpus")
    parser.add_argument("--max-volume-rel-delta", type=float, default=0.001)
    parser.add_argument("--max-area-rel-delta", type=float, default=0.001)
    parser.add_argument("--max-bounds-delta-mm", type=float, default=0.001)
    parser.add_argument("--validate-native-surface", action="store_true")
    parser.add_argument(
        "--warm-native-import",
        action="store_true",
        help="Import clipper2_batch before sample timing so corpus results reflect warm steady-state timing.",
    )
    parser.add_argument("--allow-failures", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args(sys.argv[1:])))
