"""Replay the new bias-filter + cross-val selection against the
on-disk 品红4 archive without touching it.

This script does NOT modify the archive; it only re-runs
``_aggregate_stage_a_runs`` on the persisted ``verification_runs`` to
show what the upgraded aggregator would have decided. Used to confirm
the selection pipeline correctly drops the biased run on real data
(品红4's run[0] should be excluded for ``c0_white_avg > 0.95``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.single_stage.materials import (  # noqa: E402
    _aggregate_stage_a_runs,
    _score_run_bias,
)


def main() -> None:
    archive_path = REPO / "materials" / "无境新材" / "品红4" / "material.json"
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    verification_runs = archive.get("verification_runs") or []
    print(f"# 品红4 — replay aggregator on {len(verification_runs)} runs (read-only)")

    # Per-run bias diagnostic (independent of aggregation)
    for i, run in enumerate(verification_runs):
        score = _score_run_bias(run)
        print(
            f"\nrun[{i}] captured_at={run.get('captured_at')}\n"
            f"        bias_flags={score['bias_flags']}\n"
            f"        structural_flags={score['structural_flags']}\n"
            f"        white_c0_avg={score['white_c0_avg']:.4f} "
            f"image_source={score['image_source']!r}"
        )

    # Re-run the aggregator with the existing payloads. The only side
    # effect is the returned tuple — nothing is written to disk.
    params, fit, msum = _aggregate_stage_a_runs(
        material_name=str(archive.get("material_name") or "PLA"),
        params_payload={
            "meta": {},
            "parameters": (archive.get("material_summary") or {}).get("parameters")
            or json.loads(
                (archive_path.parent / "stage_A_parameters.json").read_text(
                    encoding="utf-8"
                )
            ).get("parameters", {}),
        },
        fit_summary=archive.get("fit_summary") or {},
        material_summary=archive.get("material_summary") or {},
        verification_runs=verification_runs,
    )
    selection = params["meta"]["selection"]
    print("\n# Aggregator selection:")
    print(json.dumps(selection, indent=2, ensure_ascii=False))

    print("\n# Summary:")
    print(f"  selected_indices    = {selection['selected_indices']}")
    print(f"  excluded_indices    = {[e['index'] for e in selection['excluded_runs']]}")
    print(f"  selection_strategy  = {selection['selection_strategy']}")
    print(f"  aggregation_method  = {fit['overall_validation']['aggregation_method']}")


if __name__ == "__main__":
    main()
