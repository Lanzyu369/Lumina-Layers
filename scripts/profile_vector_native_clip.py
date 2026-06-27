#!/usr/bin/env python3
"""Profile optional Clipper2 native SVG occlusion clipping against Shapely."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from shapely.strtree import STRtree
from shapely.validation import make_valid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.vector_engine import VECTOR_HANDLED_ERRORS, VectorProcessor
from core.vector_native_clip import difference_with_native
from scripts.profile_vector_native_mesh_corpus import discover_svg_files


def _geometry_signature(items, *, geometry_key: str) -> list[dict[str, Any]]:
    signature = []
    for item in items:
        geom = item.get(geometry_key)
        if geom is None or geom.is_empty:
            continue
        signature.append(
            {
                "color": tuple(item.get("color") or ()),
                "geom_type": geom.geom_type,
                "area": round(float(geom.area), 6),
                "bounds": tuple(round(float(value), 6) for value in geom.bounds),
            }
        )
    return signature


def _compare_clip_outputs(reference, candidate) -> dict[str, Any]:
    reference_signature = _geometry_signature(reference, geometry_key="geometry")
    candidate_signature = _geometry_signature(candidate, geometry_key="geometry")
    total_area_delta = abs(
        sum(float(item["geometry"].area) for item in reference if item.get("geometry") is not None)
        - sum(float(item["geometry"].area) for item in candidate if item.get("geometry") is not None)
    )
    first_mismatch_index = None
    first_reference = None
    first_candidate = None
    for idx, (ref_row, cand_row) in enumerate(zip(reference_signature, candidate_signature)):
        if ref_row != cand_row:
            first_mismatch_index = idx
            first_reference = ref_row
            first_candidate = cand_row
            break
    if first_mismatch_index is None and len(reference_signature) != len(candidate_signature):
        first_mismatch_index = min(len(reference_signature), len(candidate_signature))

    return {
        "summary_match": reference_signature == candidate_signature,
        "reference_count": len(reference_signature),
        "candidate_count": len(candidate_signature),
        "total_area_delta": round(float(total_area_delta), 9),
        "first_mismatch_index": first_mismatch_index,
        "first_reference": first_reference,
        "first_candidate": first_candidate,
    }


def _clip_occlusion_native_poc(shape_data, *, native_module, scale: int = 1_000_000):
    n = len(shape_data)
    valid = []
    for i, item in enumerate(shape_data):
        geom = item["poly"]
        if geom is not None and not geom.is_empty:
            valid.append((i, geom))
    if not valid:
        return [], {"native_calls": 0, "native_errors": 0}

    orders = [item[0] for item in valid]
    geoms = [item[1] for item in valid]
    tree = STRtree(geoms)
    geom_id_to_idx = {id(geom): idx for idx, geom in enumerate(geoms)}
    result = []
    native_calls = 0
    native_errors = 0

    for i in range(n - 1, -1, -1):
        item = shape_data[i]
        geom = item["poly"]
        if geom is None or geom.is_empty:
            continue

        occluders = []
        predicate_filtered = False
        try:
            candidate_refs = tree.query(geom, predicate="intersects")
            predicate_filtered = True
        except TypeError:
            try:
                candidate_refs = tree.query(geom)
            except VECTOR_HANDLED_ERRORS:
                candidate_refs = []
        except VECTOR_HANDLED_ERRORS:
            try:
                candidate_refs = tree.query(geom)
            except VECTOR_HANDLED_ERRORS:
                candidate_refs = []

        for ref in candidate_refs:
            if isinstance(ref, (int, np.integer)):
                idx = int(ref)
            else:
                idx = geom_id_to_idx.get(id(ref), -1)
            if idx < 0 or orders[idx] <= i:
                continue
            candidate = geoms[idx]
            if predicate_filtered:
                occluders.append(candidate)
                continue
            try:
                if candidate.intersects(geom):
                    occluders.append(candidate)
            except VECTOR_HANDLED_ERRORS:
                continue

        geometry_normalized = False
        if not occluders:
            clipped = geom
            geometry_normalized = bool(item.get("geometry_normalized"))
        else:
            native_calls += 1
            try:
                clipped = difference_with_native(
                    geom,
                    occluders,
                    native_module=native_module,
                    scale=int(scale),
                )
            except Exception:
                native_errors += 1
                clipped = None

        if clipped is not None and not clipped.is_empty:
            if not clipped.is_valid:
                clipped = make_valid(clipped)
            if not clipped.is_empty:
                result.append(
                    {
                        "geometry": clipped,
                        "color": item["color"],
                        "draw_order": i,
                        "geometry_normalized": geometry_normalized,
                    }
                )

    result.reverse()
    return result, {"native_calls": native_calls, "native_errors": native_errors}


def _profile_sample(
    svg_path: Path,
    *,
    native_module,
    target_width_mm: float,
    scale: int = 1_000_000,
    ) -> dict[str, Any]:
    processor = VectorProcessor.__new__(VectorProcessor)
    processor.sampling_precision = 0.02
    processor._parse_expand_stroke_to_fill = False
    t0 = time.perf_counter()
    shape_data, _scale, _bbox = processor._parse_svg(str(svg_path), target_width_mm=target_width_mm)
    parse_seconds = time.perf_counter() - t0

    t0 = time.perf_counter()
    reference = processor._clip_occlusion(shape_data, return_silhouette=False)
    reference_seconds = time.perf_counter() - t0

    t0 = time.perf_counter()
    native, native_stats = _clip_occlusion_native_poc(
        shape_data,
        native_module=native_module,
        scale=int(scale),
    )
    native_seconds = time.perf_counter() - t0

    return {
        "svg_name": svg_path.name,
        "status": "ok",
        "scale": int(scale),
        "parse_seconds": round(parse_seconds, 6),
        "reference_seconds": round(reference_seconds, 6),
        "native_seconds": round(native_seconds, 6),
        "speedup": round(reference_seconds / native_seconds, 6) if native_seconds > 0 else None,
        "raw_shape_count": len(shape_data),
        "quality": _compare_clip_outputs(reference, native),
        "native_stats": native_stats,
    }


def _build_report(*, input_path: Path, samples: list[dict[str, Any]], scale: int = 1_000_000) -> dict[str, Any]:
    ok_samples = [sample for sample in samples if sample.get("status") == "ok"]
    reference_total = sum(float(sample.get("reference_seconds", 0.0)) for sample in ok_samples)
    native_total = sum(float(sample.get("native_seconds", 0.0)) for sample in ok_samples)
    quality_pass_count = sum(
        1 for sample in ok_samples if (sample.get("quality") or {}).get("summary_match") is True
    )
    native_faster_count = sum(
        1 for sample in ok_samples if float(sample.get("speedup") or 0.0) > 1.0
    )
    return {
        "input": {"path": str(input_path.resolve()), "scale": int(scale)},
        "summary": {
            "sample_count": len(samples),
            "ok_count": len(ok_samples),
            "quality_pass_count": quality_pass_count,
            "native_faster_count": native_faster_count,
            "reference_total_seconds": round(reference_total, 6),
            "native_total_seconds": round(native_total, 6),
            "speedup": round(reference_total / native_total, 6) if native_total > 0 else None,
        },
        "samples": samples,
    }


def _render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    speedup = summary.get("speedup")
    lines = [
        "# Native Vector Clip POC",
        "",
        f"- Samples: {summary['sample_count']}",
        f"- OK: {summary['ok_count']}",
        f"- Quality pass: {summary['quality_pass_count']} / {summary['ok_count']}",
        f"- Native faster: {summary['native_faster_count']} / {summary['ok_count']}",
        f"- Clip total: reference={summary['reference_total_seconds']:.3f}s, "
        f"native={summary['native_total_seconds']:.3f}s, speedup={speedup:.3f}x"
        if speedup is not None
        else "- Clip total: unavailable",
        "",
        "## Samples",
        "",
    ]
    for sample in report["samples"]:
        if sample.get("status") != "ok":
            lines.append(f"- `{sample.get('svg_name', '?')}`: ERROR {sample.get('error_type')}")
            continue
        quality = sample["quality"]
        lines.append(
            f"- `{sample['svg_name']}`: reference={sample['reference_seconds']:.3f}s, "
            f"native={sample['native_seconds']:.3f}s, speedup={sample['speedup']:.3f}x, "
            f"summary_match={quality['summary_match']}, "
            f"count={quality['reference_count']}->{quality['candidate_count']}, "
            f"area_delta={quality['total_area_delta']:.9f}"
        )
    return "\n".join(lines) + "\n"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="SVG file or directory")
    parser.add_argument("--target-width-mm", type=float, default=100.0)
    parser.add_argument("--scale", type=int, default=1_000_000)
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--out-dir", type=Path, default=Path(".scratch/vector_native_clip_poc"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        native_module = __import__("clipper2_batch")
    except Exception as exc:
        print(f"clipper2_batch is unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    svg_files = discover_svg_files(args.input)
    if args.max_samples is not None:
        svg_files = svg_files[: max(0, int(args.max_samples))]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    samples = []
    for index, svg_path in enumerate(svg_files, start=1):
        print(f"[{index}/{len(svg_files)}] {svg_path}", flush=True)
        try:
            samples.append(
                _profile_sample(
                    svg_path,
                    native_module=native_module,
                    target_width_mm=float(args.target_width_mm),
                    scale=int(args.scale),
                )
            )
        except Exception as exc:
            samples.append(
                {
                    "svg_name": svg_path.name,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )

    report = _build_report(input_path=args.input, samples=samples, scale=int(args.scale))
    json_path = args.out_dir / "vector_native_clip_poc.json"
    md_path = args.out_dir / "vector_native_clip_poc.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
