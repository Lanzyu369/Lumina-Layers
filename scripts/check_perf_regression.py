"""Compare current Stage-3 performance against baseline and emit PASS/WARN/FAIL.

Exit codes:
  0 = PASS
  1 = WARN
  2 = FAIL
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_JSON = ROOT / "artifacts" / "perf_baseline.json"
CURRENT_JSON = ROOT / "artifacts" / "perf_latest.json"
PROFILE_SCRIPT = ROOT / "scripts" / "profile_stage3.py"

KEY_METRICS = ["total_s", "s06_s", "s07_s", "s11_s", "peak_memory_mb"]
HOTSPOT_COMPONENTS = [
    "mesh_compute_s",
    "mesh_apply_transform_s",
    "s11_unique_s",
    "s11_merge_s",
    "s11_mask_build_s",
    "s11_mesh_loop_s",
    "s11_backing_s",
    "s11_export_s",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check performance regression against baseline.")
    parser.add_argument("--baseline", type=Path, default=BASELINE_JSON, help="Baseline JSON path.")
    parser.add_argument("--current", type=Path, default=CURRENT_JSON, help="Current JSON path.")
    parser.add_argument(
        "--regenerate-current",
        action="store_true",
        help="Run profile_stage3.py to generate current JSON before comparison.",
    )
    parser.add_argument(
        "--use-cold-start",
        action="store_true",
        help="Compare cold-start (run1) instead of warm median.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _regress_pct(current: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.0
    return ((current - baseline) / baseline) * 100.0


def _metric_value(ds: dict, metric: str, use_cold_start: bool) -> float:
    if use_cold_start:
        cold = ds.get("cold_start", {})
        if metric in cold:
            return float(cold[metric])
    summary = ds.get("summary", {})
    metric_obj = summary.get(metric, {})
    if "warm_median" in metric_obj and not use_cold_start:
        return float(metric_obj["warm_median"])
    if "median" in metric_obj:
        return float(metric_obj["median"])
    warm_summary = ds.get("warm_summary", {}).get(metric, {})
    if "median" in warm_summary and not use_cold_start:
        return float(warm_summary["median"])
    return 0.0


def _compare(baseline: dict, current: dict, use_cold_start: bool) -> tuple[int, list[str]]:
    warn_pct = float(baseline.get("thresholds", {}).get("warn_regression_pct", 15))
    fail_pct = float(baseline.get("thresholds", {}).get("fail_regression_pct", 30))

    base_ds = {d["name"]: d for d in baseline.get("datasets", [])}
    curr_ds = {d["name"]: d for d in current.get("datasets", [])}
    status = 0
    lines: list[str] = []

    for ds_name in sorted(base_ds.keys()):
        if ds_name not in curr_ds:
            status = 2
            lines.append(f"[FAIL] dataset missing in current: {ds_name}")
            continue
        b_ds = base_ds[ds_name]
        c_ds = curr_ds[ds_name]
        for metric in KEY_METRICS:
            b_val = _metric_value(b_ds, metric, use_cold_start)
            c_val = _metric_value(c_ds, metric, use_cold_start)
            pct = _regress_pct(c_val, b_val)
            if pct > fail_pct:
                status = 2
                lines.append(
                    f"[FAIL] {ds_name}.{metric}: baseline={b_val:.3f}, current={c_val:.3f}, "
                    f"regression={pct:.2f}% ({'cold' if use_cold_start else 'warm'})"
                )
            elif pct > warn_pct and status < 2:
                status = max(status, 1)
                lines.append(
                    f"[WARN] {ds_name}.{metric}: baseline={b_val:.3f}, current={c_val:.3f}, "
                    f"regression={pct:.2f}% ({'cold' if use_cold_start else 'warm'})"
                )

    if not lines:
        lines.append("[PASS] No regression beyond warn threshold.")
    return status, lines


def _top_hotspots(ds: dict, use_cold_start: bool) -> list[tuple[str, float]]:
    pairs: list[tuple[str, float]] = []
    for key in HOTSPOT_COMPONENTS:
        value = _metric_value(ds, key, use_cold_start)
        if value > 0:
            pairs.append((key, value))
    pairs.sort(key=lambda item: item[1], reverse=True)
    return pairs[:3]


def _print_total_regression_diagnostics(baseline: dict, current: dict, use_cold_start: bool) -> None:
    warn_pct = float(baseline.get("thresholds", {}).get("warn_regression_pct", 15))
    fail_pct = float(baseline.get("thresholds", {}).get("fail_regression_pct", 30))
    base_ds = {d["name"]: d for d in baseline.get("datasets", [])}
    curr_ds = {d["name"]: d for d in current.get("datasets", [])}
    mode = "cold" if use_cold_start else "warm"

    for ds_name in sorted(base_ds.keys()):
        if ds_name not in curr_ds:
            continue
        b_total = _metric_value(base_ds[ds_name], "total_s", use_cold_start)
        c_total = _metric_value(curr_ds[ds_name], "total_s", use_cold_start)
        pct = _regress_pct(c_total, b_total)
        if pct <= warn_pct:
            continue
        level = "FAIL" if pct > fail_pct else "WARN"
        print(f"[{level}] diagnostic for {ds_name}.total_s ({mode}):")
        current_top = _top_hotspots(curr_ds[ds_name], use_cold_start)
        baseline_top = _top_hotspots(base_ds[ds_name], use_cold_start)
        if current_top:
            print("  current top segments: " + ", ".join(f"{k}={v:.3f}s" for k, v in current_top))
        if baseline_top:
            print("  baseline top segments: " + ", ".join(f"{k}={v:.3f}s" for k, v in baseline_top))
        c_s07 = _metric_value(curr_ds[ds_name], "mesh_compute_s", use_cold_start)
        c_s11 = _metric_value(curr_ds[ds_name], "s11_mesh_loop_s", use_cold_start)
        likely = "S07-side compute" if c_s07 >= c_s11 else "S11-side mesh loop"
        print(f"  likely dominant side: {likely}")


def main() -> int:
    args = _parse_args()
    if args.regenerate_current:
        cmd = [
            sys.executable,
            str(PROFILE_SCRIPT),
            "--output-json",
            str(args.current),
            "--skip-markdown",
        ]
        print(f">>> {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=ROOT, text=True)
        if proc.returncode != 0:
            print("[FAIL] Unable to generate current profile payload.")
            return 2

    try:
        baseline = _load_json(args.baseline)
        current = _load_json(args.current)
    except FileNotFoundError as exc:
        print(f"[FAIL] {exc}")
        print("Action: run `python scripts/profile_stage3.py --also-write-latest` first.")
        return 2

    status, lines = _compare(baseline, current, args.use_cold_start)
    warm_status, _ = _compare(baseline, current, False)
    cold_status, _ = _compare(baseline, current, True)
    for line in lines:
        print(line)
    _print_total_regression_diagnostics(baseline, current, args.use_cold_start)
    print(
        f"Mode summary: warm={'PASS' if warm_status == 0 else 'WARN' if warm_status == 1 else 'FAIL'}, "
        f"cold={'PASS' if cold_status == 0 else 'WARN' if cold_status == 1 else 'FAIL'}"
    )
    if args.use_cold_start:
        print("Comparison mode: cold-start (run1).")
    else:
        print("Comparison mode: warm median (run2/run3).")

    if status == 0:
        print("Action: safe to proceed.")
    elif status == 1:
        print("Action: re-run profiling to confirm; update baseline only if change is expected.")
    else:
        print("Action: block merge, investigate bottleneck or fix regression before updating baseline.")

    return status


if __name__ == "__main__":
    raise SystemExit(main())
