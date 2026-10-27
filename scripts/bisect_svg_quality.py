"""Semantic comparator for SVG vector-engine bisect runs."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

LOGGER = logging.getLogger("bisect_svg_quality")
MAIN_ROOT = Path(__file__).resolve().parents[1]
TRACE_PATH = MAIN_ROOT / "output" / "bisect" / "_trace.jsonl"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare SVG repro output against a baseline.")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument(
        "--candidate-out-root",
        type=Path,
        default=Path("output") / "bisect" / "candidate_current",
    )
    parser.add_argument("--pythonpath", required=True)
    parser.add_argument("--mode-keys", default="4color_rybw,6color_rybw,5color_ext")
    parser.add_argument("--ssim-threshold", type=float, default=0.995)
    parser.add_argument("--area-tolerance-mm2", type=float, default=0.01)
    return parser.parse_args()


def _resolve_main_path(path: Path) -> Path:
    return path if path.is_absolute() else MAIN_ROOT / path


def _git_output(worktree: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", os.fspath(worktree), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _current_commit(worktree: Path) -> str:
    return _git_output(worktree, "rev-parse", "HEAD")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _shape_area_signature(stats: dict[str, Any]) -> list[tuple[str, float]]:
    return sorted(
        (str(shape["fill_hex"]), round(float(shape["area_mm2"]), 2))
        for shape in stats["clipped_shapes"]
    )


def _shape_recipe_signature(stats: dict[str, Any]) -> list[tuple[str, tuple[int, ...], tuple[int, ...]]]:
    return sorted(
        (
            str(shape["fill_hex"]),
            tuple(int(value) for value in shape["matched_rgb"]),
            tuple(int(value) for value in shape["recipe"]),
        )
        for shape in stats["clipped_shapes"]
    )


def _total_area(stats: dict[str, Any]) -> float:
    return sum(float(shape["area_mm2"]) for shape in stats["clipped_shapes"])


def _load_gray(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float64)


def _image_similarity(
    baseline_path: Path,
    candidate_path: Path,
    ssim_available: bool,
) -> tuple[float, str]:
    baseline = _load_gray(baseline_path)
    candidate = _load_gray(candidate_path)
    if baseline.shape != candidate.shape:
        return float("inf"), "mse"

    if ssim_available:
        from skimage.metrics import structural_similarity

        return float(structural_similarity(baseline, candidate, data_range=255)), "ssim"

    diff = baseline - candidate
    return float(np.mean(diff * diff)), "mse"


def _image_pass(value: float, metric: str, ssim_threshold: float) -> bool:
    if metric == "ssim":
        return value >= ssim_threshold
    return value < 2.0


def _compare_mode(
    baseline_root: Path,
    candidate_root: Path,
    mode_key: str,
    ssim_threshold: float,
    area_tolerance_mm2: float,
    ssim_available: bool,
) -> tuple[bool, dict[str, Any]]:
    baseline_stats = _load_json(baseline_root / mode_key / "shape_stats.json")
    candidate_stats = _load_json(candidate_root / mode_key / "shape_stats.json")

    baseline_shapes = len(baseline_stats["clipped_shapes"])
    candidate_shapes = len(candidate_stats["clipped_shapes"])
    baseline_area = _total_area(baseline_stats)
    candidate_area = _total_area(candidate_stats)
    area_diff = candidate_area - baseline_area

    overlay_value, overlay_metric = _image_similarity(
        baseline_root / mode_key / "shapes_overlay.png",
        candidate_root / mode_key / "shapes_overlay.png",
        ssim_available,
    )
    preview_value, preview_metric = _image_similarity(
        baseline_root / mode_key / "preview.png",
        candidate_root / mode_key / "preview.png",
        ssim_available,
    )

    diffs: dict[str, Any] = {
        "num_channels_match": baseline_stats["num_channels"] == candidate_stats["num_channels"],
        "num_layers_match": baseline_stats["num_layers"] == candidate_stats["num_layers"],
        "slot_names_match": baseline_stats["slot_names"] == candidate_stats["slot_names"],
        "shape_count_diff": candidate_shapes - baseline_shapes,
        "total_area_diff_mm2": round(area_diff, 6),
        "area_signature_match": _shape_area_signature(baseline_stats)
        == _shape_area_signature(candidate_stats),
        "recipe_signature_match": _shape_recipe_signature(baseline_stats)
        == _shape_recipe_signature(candidate_stats),
        "overlay_metric": overlay_metric,
        "overlay_value": round(overlay_value, 6),
        "preview_metric": preview_metric,
        "preview_value": round(preview_value, 6),
    }

    matches = [
        diffs["num_channels_match"],
        diffs["num_layers_match"],
        diffs["slot_names_match"],
        diffs["shape_count_diff"] == 0,
        diffs["area_signature_match"],
        diffs["recipe_signature_match"],
        abs(area_diff) < area_tolerance_mm2,
        _image_pass(overlay_value, overlay_metric, ssim_threshold),
    ]
    return all(bool(item) for item in matches), diffs


def _append_trace(commit: str, result: str, per_mode_diffs: dict[str, Any]) -> None:
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "commit": commit,
        "result": result,
        "per_mode_diffs": per_mode_diffs,
        "utc_ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    with TRACE_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_json_safe(row), ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        if math.isnan(value):
            return "nan"
        return value
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _harness_command(pythonpath: Path, candidate_out_root: Path, mode_keys: str) -> list[str]:
    script = MAIN_ROOT / "scripts" / "svg_converter_repro.py"
    wrapper = (
        "import runpy, sys; "
        f"worktree={str(pythonpath)!r}; "
        f"script={str(script)!r}; "
        "sys.path.insert(0, worktree); "
        "import core.vector_engine, core.image_processing, config; "
        f"sys.argv=[script, '--out-root', {str(candidate_out_root)!r}, '--modes', {mode_keys!r}]; "
        "runpy.run_path(script, run_name='__main__')"
    )
    return [sys.executable, "-c", wrapper]


def _run_harness(pythonpath: Path, candidate_out_root: Path, mode_keys: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.fspath(pythonpath) + (os.pathsep + existing if existing else "")
    return subprocess.run(
        _harness_command(pythonpath, candidate_out_root, mode_keys),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=os.fspath(MAIN_ROOT),
    )


def _ssim_available() -> bool:
    try:
        from skimage.metrics import structural_similarity  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def main() -> int:
    """Run one semantic SVG quality comparison for git bisect.
    运行一次供 git bisect 使用的 SVG 语义质量比较。
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = _parse_args()
    baseline_root = _resolve_main_path(args.baseline)
    candidate_root = _resolve_main_path(args.candidate_out_root)
    pythonpath = Path(args.pythonpath).resolve()
    mode_keys = [item.strip() for item in args.mode_keys.split(",") if item.strip()]
    commit = "unknown"

    try:
        commit = _current_commit(pythonpath)
        ssim_available = _ssim_available()
        if not ssim_available:
            LOGGER.warning("scikit-image unavailable; falling back to grayscale MSE < 2.0.")

        harness = _run_harness(pythonpath, candidate_root, ",".join(mode_keys))
        if harness.stdout:
            LOGGER.info("harness stdout:\n%s", harness.stdout)
        if harness.stderr:
            LOGGER.info("harness stderr:\n%s", harness.stderr)
        if harness.returncode != 0:
            reason = {
                "harness_returncode": harness.returncode,
                "stderr_tail": harness.stderr[-4000:],
            }
            _append_trace(commit, "skip", {"_error": reason})
            LOGGER.error("Harness failed on %s; skipping commit.", commit)
            return 125

        per_mode_diffs: dict[str, Any] = {}
        all_good = True
        for mode_key in mode_keys:
            mode_good, diffs = _compare_mode(
                baseline_root=baseline_root,
                candidate_root=candidate_root,
                mode_key=mode_key,
                ssim_threshold=float(args.ssim_threshold),
                area_tolerance_mm2=float(args.area_tolerance_mm2),
                ssim_available=ssim_available,
            )
            per_mode_diffs[mode_key] = diffs
            all_good = all_good and mode_good

        result = "good" if all_good else "bad"
        _append_trace(commit, result, per_mode_diffs)
        LOGGER.info("commit %s classified as %s", commit, result)
        return 0 if all_good else 1
    except Exception as exc:
        _append_trace(commit, "skip", {"_error": str(exc)})
        LOGGER.exception("Unexpected comparator failure; skipping commit.")
        return 125


if __name__ == "__main__":
    raise SystemExit(main())
