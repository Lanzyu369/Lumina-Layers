"""Diagnostic: do the saved verification_runs of 品红4 actually carry
``fit_samples``? If not, the auto-aggregator falls back to parameter
``mean`` instead of joint refit-combined LM optimisation, which is why
the second verification did not improve the fit numbers as expected.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def describe_run(idx: int, run: dict) -> None:
    """Inspect a stored verification_run.

    The persistent location for the per-run sample matrix is ``run["samples"]``
    (a dict with ``thickness_mm`` / ``white_linear`` / ``black_linear``), not
    ``run["fit_summary"]["fit_samples"]``. The earlier version of this probe
    looked in the wrong place and reported false negatives on archives that
    were actually fully samples-bearing.
    每个 run 的样本矩阵实际持久化在 run[\"samples\"]，不是 run[\"fit_summary\"]
    [\"fit_samples\"]；旧版本探测脚本看错了字段，会把已存样本误报为缺失。
    """
    fit = run.get("fit_summary") or {}
    samples = run.get("samples")
    src = run.get("source") or {}
    captured = run.get("captured_at") or src.get("captured_at") or "-"
    img_src = src.get("image_source", "-")
    print(f"run[{idx}] captured_at={captured} image_source={img_src}")
    if samples is None:
        print("    samples: MISSING (run is legacy / saved before step-3 code)")
    else:
        thickness = samples.get("thickness_mm") or []
        white = samples.get("white_linear") or []
        black = samples.get("black_linear") or []
        print(
            f"    samples: present  "
            f"thickness_mm={len(thickness)}  "
            f"white_linear={len(white)}x{len(white[0]) if white else 0}  "
            f"black_linear={len(black)}x{len(black[0]) if black else 0}"
        )
    print(f"    run keys: {sorted(run.keys())}")
    print(f"    fit_summary keys: {sorted(fit.keys())}")


def describe_stage_a(path: Path, label: str) -> None:
    if not path.exists():
        print(f"\n{label}: MISSING ({path})")
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    params = payload.get("parameters") or {}
    channels = params.get("channels") or []
    print(f"\n{label}: {path.name}")
    print(f"  meta.aggregation_method = {(payload.get('meta') or {}).get('aggregation_method', '-')}")
    print(f"  meta.image_source       = {(payload.get('meta') or {}).get('image_source', '-')}")
    if not channels:
        print("  channels: MISSING")
        return
    ch0 = channels[0]
    samples = ch0.get("fit_samples") or ch0.get("samples")
    if samples is None:
        print("  channels[0].fit_samples: MISSING (nor samples)")
    else:
        try:
            n = len(samples)
            inner = len(samples[0]) if n else 0
        except Exception:
            n = "?"
            inner = "?"
        print(f"  channels[0].fit_samples: present, shape=({n}, {inner})")
        if n:
            print(f"    first row: {samples[0]}")
    print(f"  channels[0] keys: {sorted(ch0.keys())}")


def main() -> None:
    archive_path = REPO / "materials" / "无境新材" / "品红4" / "material.json"
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    runs = archive.get("verification_runs") or []
    print(f"# 品红4 verification_runs = {len(runs)}\n")
    for i, run in enumerate(runs):
        describe_run(i, run)
        print()

    # The aggregated stage_A_parameters.json holds the merged (E, k, C0) we
    # actually load; it is rewritten by save_stage_a_material_archive each
    # time we merge a run. ``meta.aggregation_method`` should say
    # ``refit_combined`` once samples exist on every run.
    describe_stage_a(
        REPO / "materials" / "无境新材" / "品红4" / "stage_A_parameters.json",
        label="aggregated stage_A_parameters.json",
    )


if __name__ == "__main__":
    main()
