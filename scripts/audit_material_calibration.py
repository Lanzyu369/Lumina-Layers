"""Audit Stage-A calibration health for every saved material.

Reports per-material:
  - metadata layer_height_mm
  - C0_white (linear RGB) + mean
  - C0_black (linear RGB) + mean
  - estimated_k (RGB)
  - mean delta_e / max delta_e / rmse_linear
  - thickness_layers list

Flags ``C0_white_mean > 0.95`` as a white-balance / restored-input
suspicion: when zero-thickness samples sit near pure white, the input
image was almost certainly white-balanced (auto-WB, restored card
render, etc.) before Stage A fitting, and the resulting ``(E, k)`` will
be biased away from the true physical attenuation.

Read-only: never mutates any file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


C0_WHITE_OVERBRIGHT_THRESHOLD = 0.95
"""Linear-RGB C0_white mean threshold; above this the zero-thickness
samples are suspiciously close to ideal white (= 1.0), which strongly
suggests the input image was white-balanced / restored before fitting."""


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _stage_a_arrays(
    stage_a_payload: dict[str, Any],
) -> tuple[list[float], list[float], list[float], list[float]] | None:
    parameters = stage_a_payload.get("parameters") or {}
    channels = parameters.get("channels") or []
    if not channels or not isinstance(channels[0], dict):
        return None
    ch0 = channels[0]
    e_values = list(ch0.get("E") or [])
    k_values = list(ch0.get("k") or [])
    if len(e_values) != 3 or len(k_values) != 3:
        return None
    substrates = parameters.get("substrates") or []
    c0_white: list[float] | None = None
    c0_black: list[float] | None = None
    for sub in substrates:
        if not isinstance(sub, dict):
            continue
        sid = sub.get("substrate_id")
        c0 = sub.get("C0")
        if isinstance(c0, list) and len(c0) == 3:
            if sid == "white":
                c0_white = [float(v) for v in c0]
            elif sid == "black":
                c0_black = [float(v) for v in c0]
    if c0_white is None or c0_black is None:
        return None
    return e_values, k_values, c0_white, c0_black


def _format_triplet(values: list[float]) -> str:
    return "[" + ", ".join(f"{v:.4f}" for v in values) + "]"


def audit(materials_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for archive_path in sorted(materials_dir.rglob("material.json")):
        material_dir = archive_path.parent
        if material_dir.name.startswith("_"):
            continue
        archive = _load_json(archive_path)
        if archive is None or archive.get("kind") != "lumina_stage_a_material":
            continue
        stage_a_filename = str(
            archive.get("stage_a_params_file") or "stage_A_parameters.json"
        )
        stage_a_path = material_dir / stage_a_filename
        stage_a = _load_json(stage_a_path)
        if stage_a is None:
            continue
        params = _stage_a_arrays(stage_a)
        if params is None:
            continue
        e_values, k_values, c0_white, c0_black = params

        msum = archive.get("material_summary") or {}
        fit = archive.get("fit_summary") or {}
        validation = fit.get("overall_validation") or {}
        rel_dir = material_dir.relative_to(materials_dir)

        rows.append(
            {
                "directory": str(rel_dir),
                "name": archive.get("material_name") or material_dir.name,
                "metadata_layer_h": msum.get("layer_height_mm"),
                "c0_white": c0_white,
                "c0_white_mean": float(np.mean(c0_white)),
                "c0_black": c0_black,
                "c0_black_mean": float(np.mean(c0_black)),
                "e_values": e_values,
                "k_values": k_values,
                "white_zero_rgb": msum.get("white_zero_rgb"),
                "black_zero_rgb": msum.get("black_zero_rgb"),
                "estimated_rgb": msum.get("estimated_rgb"),
                "mean_delta_e": validation.get("mean_delta_e"),
                "max_delta_e": validation.get("max_delta_e"),
                "rmse_linear": validation.get("rmse_linear"),
                "verification_count": archive.get("verification_count"),
                "thickness_layers": msum.get("thickness_layers"),
                "updated_at": archive.get("updated_at"),
            }
        )
    return rows


def render_console_report(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(no materials found)"

    suspicious_white = [
        r for r in rows if r["c0_white_mean"] > C0_WHITE_OVERBRIGHT_THRESHOLD
    ]
    layer_h_mismatch_candidates = [
        r for r in rows if r.get("metadata_layer_h") not in (0.04, 0.08, 0.16, 0.20)
    ]

    lines: list[str] = []
    lines.append("# Material Calibration Audit")
    lines.append("")
    lines.append(
        f"Scanned {len(rows)} material(s). "
        f"Suspect 'restored / white-balanced' inputs: "
        f"{len(suspicious_white)} (C0_white mean > "
        f"{C0_WHITE_OVERBRIGHT_THRESHOLD:.2f})."
    )
    if layer_h_mismatch_candidates:
        lines.append(
            f"Materials with non-standard metadata layer_height_mm: "
            f"{len(layer_h_mismatch_candidates)}"
        )
    lines.append("")
    lines.append(
        "Per-material details (sorted by C0_white mean, descending):"
    )
    lines.append("")

    rows_sorted = sorted(rows, key=lambda r: -r["c0_white_mean"])
    for row in rows_sorted:
        flag = (
            "[OVERBRIGHT]"
            if row["c0_white_mean"] > C0_WHITE_OVERBRIGHT_THRESHOLD
            else "[ok]"
        )
        lines.append(f"  {flag} {row['directory']}")
        lines.append(f"      name              = {row['name']}")
        lines.append(f"      metadata_layer_h  = {row['metadata_layer_h']}")
        lines.append(
            f"      C0_white (linear) = {_format_triplet(row['c0_white'])} "
            f"mean={row['c0_white_mean']:.4f}"
        )
        lines.append(
            f"      C0_black (linear) = {_format_triplet(row['c0_black'])} "
            f"mean={row['c0_black_mean']:.4f}"
        )
        lines.append(f"      white_zero_rgb    = {row.get('white_zero_rgb')}")
        lines.append(f"      black_zero_rgb    = {row.get('black_zero_rgb')}")
        lines.append(f"      E (linear)        = {_format_triplet(row['e_values'])}")
        lines.append(f"      k                 = {_format_triplet(row['k_values'])}")
        lines.append(f"      estimated_rgb     = {row.get('estimated_rgb')}")
        mean_de = row.get("mean_delta_e")
        max_de = row.get("max_delta_e")
        rmse = row.get("rmse_linear")
        mean_de_s = f"{mean_de:.3f}" if isinstance(mean_de, (int, float)) else str(mean_de)
        max_de_s = f"{max_de:.3f}" if isinstance(max_de, (int, float)) else str(max_de)
        rmse_s = f"{rmse:.5f}" if isinstance(rmse, (int, float)) else str(rmse)
        lines.append(
            f"      mean_dE / max_dE  = {mean_de_s} / {max_de_s}    rmse_linear={rmse_s}"
        )
        lines.append(f"      verification_cnt  = {row.get('verification_count')}")
        lines.append(f"      thickness_layers  = {row.get('thickness_layers')}")
        lines.append(f"      updated_at        = {row.get('updated_at')}")
        lines.append("")

    lines.append("# Summary")
    if suspicious_white:
        lines.append("")
        lines.append(
            "These materials likely need to be re-calibrated using the *raw* "
            "(non-white-balanced, non-restored) capture to recover physical "
            "(E, k):"
        )
        for row in sorted(suspicious_white, key=lambda r: -r["c0_white_mean"]):
            lines.append(
                f"  - {row['directory']:<40s} C0_white mean={row['c0_white_mean']:.4f}"
            )
    else:
        lines.append("")
        lines.append("No materials flagged as 'restored input' suspect.")
    return "\n".join(lines)


def main() -> int:
    materials_dir = REPO / "materials"
    if not materials_dir.is_dir():
        print(f"materials directory not found: {materials_dir}")
        return 1
    rows = audit(materials_dir)
    print(render_console_report(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
