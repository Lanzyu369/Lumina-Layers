#!/usr/bin/env python3
"""Profile optional native SVG vector mesh extrusion against the baseline."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.vector_engine import VectorProcessor  # noqa: E402


def _write_summary_png(report: dict, out_dir: Path) -> Path | None:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    path = out_dir / "vector_native_mesh_profile.png"
    image = Image.new("RGB", (1000, 620), (248, 250, 252))
    draw = ImageDraw.Draw(image)

    ink = (15, 23, 42)
    muted = (71, 85, 105)
    grid = (203, 213, 225)
    baseline_color = (37, 99, 235)
    native_color = (22, 163, 74)
    warn_color = (217, 119, 6)

    draw.text((42, 30), "Vector Native Mesh Profile", fill=ink)
    draw.text(
        (42, 58),
        f"shapes={report['analysis']['shape_count']} | repeats={report['input']['repeats']}",
        fill=muted,
    )

    build_base = float(report["variants"]["baseline"]["median_seconds"])
    build_native = float(report["variants"]["native_enabled"]["median_seconds"])
    extrude_base = float(report["variants"]["baseline"]["stage_timings"].get("extrude_bottom_s", 0.0))
    extrude_native = float(report["variants"]["native_enabled"]["stage_timings"].get("extrude_bottom_s", 0.0))
    max_value = max(build_base, build_native, extrude_base, extrude_native, 0.001)

    left = 260
    top = 130
    bar_w = 560
    bar_h = 28
    rows = [
        ("Build baseline", build_base, baseline_color),
        ("Build native flag", build_native, native_color),
        ("Extrude baseline", extrude_base, baseline_color),
        ("Extrude native flag", extrude_native, native_color),
    ]
    for idx, (label, value, color) in enumerate(rows):
        y = top + idx * 62
        draw.text((42, y + 6), label, fill=ink)
        draw.rectangle((left, y, left + bar_w, y + bar_h), fill=(226, 232, 240))
        width = int(bar_w * (value / max_value))
        draw.rectangle((left, y, left + width, y + bar_h), fill=color)
        draw.text((left + bar_w + 18, y + 6), f"{value:.3f}s", fill=ink)

    draw.line((42, 404, 958, 404), fill=grid, width=1)
    speedup_build = build_base / max(build_native, 1e-9)
    speedup_extrude = extrude_base / max(extrude_native, 1e-9)
    comparison = report["comparison"]["totals"]
    volume_delta = float(comparison["volume"]["delta"])
    volume_rel = float(comparison["volume"].get("rel_delta", 0.0))
    area_delta = float(comparison["area"]["delta"])
    area_rel = float(comparison["area"].get("rel_delta", 0.0))
    native_stats = report["variants"]["native_enabled"].get("native_stats", {})

    metric_rows = [
        ("Build speedup", f"{speedup_build:.2f}x", native_color),
        ("Extrude speedup", f"{speedup_extrude:.2f}x", native_color),
        ("Volume delta", f"{volume_delta:.6f} mm^3 ({volume_rel:.6%})", warn_color),
        ("Area delta", f"{area_delta:.6f} mm^2 ({area_rel:.6%})", warn_color),
        (
            "Native/fallback groups",
            f"{native_stats.get('native_meshes', 0)} native, {native_stats.get('fallback_groups', 0)} fallback",
            ink,
        ),
    ]
    for idx, (label, value, color) in enumerate(metric_rows):
        x = 42 + (idx % 2) * 460
        y = 438 + (idx // 2) * 56
        draw.text((x, y), label, fill=muted)
        draw.text((x, y + 22), value, fill=color)

    image.save(path)
    return path


def _scene_metrics(scene) -> dict:
    geometries = {}
    totals = {
        "vertices": 0,
        "faces": 0,
        "volume": 0.0,
        "area": 0.0,
        "watertight_geometries": 0,
    }
    for name in sorted(scene.geometry.keys()):
        mesh = scene.geometry[name]
        vertices = int(len(mesh.vertices))
        faces = int(len(mesh.faces))
        volume = float(mesh.volume)
        area = float(mesh.area)
        watertight = bool(mesh.is_watertight)
        bounds = np.asarray(mesh.bounds, dtype=np.float64)
        geometries[name] = {
            "vertices": vertices,
            "faces": faces,
            "volume": volume,
            "area": area,
            "watertight": watertight,
            "bounds": bounds.tolist(),
        }
        totals["vertices"] += vertices
        totals["faces"] += faces
        totals["volume"] += volume
        totals["area"] += area
        totals["watertight_geometries"] += 1 if watertight else 0
    return {"geometries": geometries, "totals": totals}


def _compare_metrics(base: dict, candidate: dict) -> dict:
    comparison = {"geometries": {}, "totals": {}}
    base_geoms = base["geometries"]
    cand_geoms = candidate["geometries"]
    for name in sorted(set(base_geoms) | set(cand_geoms)):
        if name not in base_geoms or name not in cand_geoms:
            comparison["geometries"][name] = {"status": "missing_in_one_variant"}
            continue
        base_item = base_geoms[name]
        candidate_item = cand_geoms[name]
        base_bounds = np.asarray(base_item["bounds"], dtype=np.float64)
        candidate_bounds = np.asarray(candidate_item["bounds"], dtype=np.float64)
        volume_delta = float(candidate_item["volume"] - base_item["volume"])
        area_delta = float(candidate_item["area"] - base_item["area"])
        comparison["geometries"][name] = {
            "vertex_delta": int(candidate_item["vertices"] - base_item["vertices"]),
            "face_delta": int(candidate_item["faces"] - base_item["faces"]),
            "volume_delta": volume_delta,
            "volume_rel_delta": volume_delta / max(abs(float(base_item["volume"])), 1e-9),
            "area_delta": area_delta,
            "area_rel_delta": area_delta / max(abs(float(base_item["area"])), 1e-9),
            "bounds_max_abs_delta_mm": float(np.max(np.abs(candidate_bounds - base_bounds))),
            "watertight_changed": bool(candidate_item["watertight"] != base_item["watertight"]),
        }
    for key in ("vertices", "faces", "volume", "area", "watertight_geometries"):
        base_value = base["totals"][key]
        candidate_value = candidate["totals"][key]
        delta = candidate_value - base_value
        entry = {"delta": delta}
        if isinstance(base_value, float):
            entry["rel_delta"] = float(delta) / max(abs(float(base_value)), 1e-9)
        comparison["totals"][key] = entry
    return comparison


def _evaluate_quality_gate(report: dict, args: argparse.Namespace) -> dict:
    comparison = report["comparison"]
    volume_rel = abs(float(comparison["totals"]["volume"].get("rel_delta", 0.0)))
    area_rel = abs(float(comparison["totals"]["area"].get("rel_delta", 0.0)))
    max_bounds_delta = 0.0
    failures = []
    for name, item in comparison["geometries"].items():
        if item.get("status") == "missing_in_one_variant":
            failures.append(f"{name}: missing in one variant")
            continue
        max_bounds_delta = max(max_bounds_delta, float(item.get("bounds_max_abs_delta_mm", 0.0)))
        if item.get("watertight_changed"):
            failures.append(f"{name}: watertight changed")

    if volume_rel > args.max_volume_rel_delta:
        failures.append(
            f"volume relative delta {volume_rel:.6%} exceeds {args.max_volume_rel_delta:.6%}"
        )
    if area_rel > args.max_area_rel_delta:
        failures.append(f"area relative delta {area_rel:.6%} exceeds {args.max_area_rel_delta:.6%}")
    if max_bounds_delta > args.max_bounds_delta_mm:
        failures.append(
            f"bounds delta {max_bounds_delta:.6f}mm exceeds {args.max_bounds_delta_mm:.6f}mm"
        )

    return {
        "passed": not failures,
        "failures": failures,
        "thresholds": {
            "max_volume_rel_delta": float(args.max_volume_rel_delta),
            "max_area_rel_delta": float(args.max_area_rel_delta),
            "max_bounds_delta_mm": float(args.max_bounds_delta_mm),
        },
        "observed": {
            "volume_rel_delta_abs": volume_rel,
            "area_rel_delta_abs": area_rel,
            "max_bounds_delta_mm": max_bounds_delta,
        },
    }


def _build_repeated(
    processor: VectorProcessor,
    analysis,
    *,
    repeats: int,
    thickness_mm: float,
    structure_mode: str,
    native_enabled: bool,
) -> tuple[object, list[float], dict, dict]:
    processor.enable_native_vector_mesh = native_enabled
    scene = None
    seconds = []
    timings = {}
    native_stats = {}
    for _ in range(repeats):
        t0 = time.perf_counter()
        scene = processor.build_mesh(
            analysis=analysis,
            thickness_mm=thickness_mm,
            structure_mode=structure_mode,
        )
        seconds.append(time.perf_counter() - t0)
        timings = dict(getattr(processor, "last_stage_timings", {}) or {})
        native_stats = dict(getattr(processor, "last_native_vector_mesh_stats", {}) or {})
    return scene, seconds, timings, native_stats


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    processor = VectorProcessor(str(args.lut), args.color_mode)
    t0 = time.perf_counter()
    analysis = processor.analyze_svg(str(args.svg), target_width_mm=args.target_width_mm)
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
    report = {
        "input": {
            "svg": str(Path(args.svg).resolve()),
            "lut": str(Path(args.lut).resolve()),
            "target_width_mm": float(args.target_width_mm),
            "thickness_mm": float(args.thickness_mm),
            "structure_mode": str(args.structure_mode),
            "color_mode": str(args.color_mode),
            "repeats": int(args.repeats),
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

    report_path = out_dir / "vector_native_mesh_profile.json"
    summary_path = out_dir / "vector_native_mesh_profile.md"
    visual_path = _write_summary_png(report, out_dir)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Vector Native Mesh Profile",
        "",
        f"- SVG: `{report['input']['svg']}`",
        f"- Analyze: {analyze_seconds:.3f}s; shapes={report['analysis']['shape_count']}",
        f"- Baseline median build: {report['variants']['baseline']['median_seconds']:.3f}s",
        f"- Native-enabled median build: {report['variants']['native_enabled']['median_seconds']:.3f}s",
        f"- Baseline extrude_bottom: {baseline_timings.get('extrude_bottom_s', 0.0):.3f}s",
        f"- Native extrude_bottom: {native_timings.get('extrude_bottom_s', 0.0):.3f}s",
        f"- Native stats: `{json.dumps(native_stats, ensure_ascii=False, sort_keys=True)}`",
        f"- Quality gate: {'PASS' if report['quality_gate']['passed'] else 'FAIL'}",
        "",
        "## Mesh Deltas",
        "",
        f"- vertices delta: {comparison['totals']['vertices']['delta']}",
        f"- faces delta: {comparison['totals']['faces']['delta']}",
        f"- volume delta: {comparison['totals']['volume']['delta']:.6f}mm^3 "
        f"({comparison['totals']['volume'].get('rel_delta', 0.0):.6%})",
        f"- area delta: {comparison['totals']['area']['delta']:.6f}mm^2 "
        f"({comparison['totals']['area'].get('rel_delta', 0.0):.6%})",
        "",
        f"Report: `{report_path}`",
    ]
    if visual_path is not None:
        lines.extend(["", f"Visual: `{visual_path}`"])
    if report["quality_gate"]["failures"]:
        lines.extend(["", "## Quality Gate Failures", ""])
        lines.extend(f"- {failure}" for failure in report["quality_gate"]["failures"])
    lines.append("")
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print(summary_path)
    return 0 if report["quality_gate"]["passed"] else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--svg", type=Path, default=REPO_ROOT / "test_images" / "benchmark.svg")
    parser.add_argument("--lut", type=Path, default=REPO_ROOT / "lut-preset" / "Custom" / "lumina_lut.json")
    parser.add_argument("--color-mode", default="4-Color (RYBW)")
    parser.add_argument("--target-width-mm", type=float, default=80.0)
    parser.add_argument("--thickness-mm", type=float, default=1.6)
    parser.add_argument("--structure-mode", default="Single-sided")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / ".scratch" / "vector_native_mesh")
    parser.add_argument("--max-volume-rel-delta", type=float, default=0.001)
    parser.add_argument("--max-area-rel-delta", type=float, default=0.001)
    parser.add_argument("--max-bounds-delta-mm", type=float, default=0.001)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args(sys.argv[1:])))
