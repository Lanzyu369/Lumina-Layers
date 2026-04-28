"""Audit every saved material archive for legacy schema fields and replay
the new bias-filter selection on each one to confirm backward compat.

For every material.json under ``materials/``:
- Check which new fields are missing on each verification_run
  (``samples``, ``source.image_source``, ``fit_summary.orientation_ranking``).
- Replay :func:`_aggregate_stage_a_runs` to ensure the upgraded
  selection logic does not crash on minimal legacy payloads, and to
  surface the resulting selection diagnostic.

Read-only: never writes to disk.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.single_stage.materials import (  # noqa: E402
    _aggregate_stage_a_runs,
    _select_runs_for_refit,
)


def audit_archive(archive_path: Path) -> None:
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    runs = archive.get("verification_runs") or []
    rel = archive_path.relative_to(REPO)
    print(f"\n# {rel}")
    print(f"  schema_version       = {archive.get('schema_version')}")
    print(f"  verification_count   = {archive.get('verification_count')}")
    print(f"  has aggregation      = {bool(archive.get('aggregation'))}")
    print(f"  runs.len             = {len(runs)}")

    for i, run in enumerate(runs):
        has_samples = bool(run.get("samples"))
        has_image_source = bool((run.get("source") or {}).get("image_source"))
        has_orientation = bool(
            (run.get("fit_summary") or {}).get("orientation_ranking")
        )
        has_params = bool(run.get("params"))
        print(
            f"  run[{i}] params={'Y' if has_params else 'N'} "
            f"samples={'Y' if has_samples else 'N'} "
            f"image_source={'Y' if has_image_source else 'N'} "
            f"orientation_ranking={'Y' if has_orientation else 'N'}"
        )

    if not runs:
        return

    selection = _select_runs_for_refit(runs)
    print(
        f"  selection.selected   = {selection['selected_indices']} "
        f"strategy={selection['selection_strategy']}"
    )

    try:
        params = json.loads(
            (archive_path.parent / "stage_A_parameters.json").read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        print("  stage_A_parameters.json missing → skipping aggregator replay")
        return

    try:
        agg_params, fit, msum = _aggregate_stage_a_runs(
            material_name=str(archive.get("material_name") or "unknown"),
            params_payload={"meta": {}, "parameters": params.get("parameters") or {}},
            fit_summary=archive.get("fit_summary") or {},
            material_summary=archive.get("material_summary") or {},
            verification_runs=runs,
        )
    except Exception as exc:
        print(f"  ERROR: aggregator raised {type(exc).__name__}: {exc}")
        return

    print(
        f"  replayed method      = {fit['overall_validation'].get('aggregation_method')}"
    )


def main() -> None:
    materials_dir = REPO / "materials"
    archive_paths = sorted(materials_dir.rglob("material.json"))
    print(f"# Found {len(archive_paths)} archive(s) under {materials_dir}")
    for path in archive_paths:
        try:
            audit_archive(path)
        except Exception as exc:
            print(f"\n# {path.relative_to(REPO)}\n  AUDIT FAILED: {exc}")


if __name__ == "__main__":
    main()
