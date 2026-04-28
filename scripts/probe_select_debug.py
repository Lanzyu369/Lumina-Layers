"""Ad-hoc diagnostic: print the bias-score breakdown that the new run
selection sees on the same synthetic captures used by
``test_aggregate_uses_refit_combined_samples_when_all_runs_have_samples``.

Used to figure out why the existing refit-combined regression now
fails after introducing the bias filter — specifically, whether a
spurious ``c0_white`` or ``orientation`` flag pushes one of the two
synthetic runs into the "strictly worse than fresh" bucket.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from test_stage_a_refit_combined_unit import _extract_run, _make_spec  # noqa: E402

from core.single_stage import save_stage_a_material_archive  # noqa: E402
from core.single_stage.materials import _score_run_bias  # noqa: E402


def main() -> None:
    spec = _make_spec()
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td)
        materials_root = tp / "materials"
        first = _extract_run(tp, spec, noise_seed=11, suffix="run1")
        sf = save_stage_a_material_archive(
            material_name="PLA Basic",
            params_payload=first.params_payload,
            fit_summary=first.fit_summary,
            source_summary=first.source_summary,
            material_summary=first.material_summary,
            materials_dir=str(materials_root),
        )
        second = _extract_run(tp, spec, noise_seed=23, suffix="run2")
        ss = save_stage_a_material_archive(
            material_name="PLA Basic",
            params_payload=second.params_payload,
            fit_summary=second.fit_summary,
            source_summary=second.source_summary,
            material_summary=second.material_summary,
            materials_dir=str(materials_root),
            existing_directory_name=sf.material_summary["directory_name"],
        )
        arc = json.loads(Path(ss.archive_path).read_text(encoding="utf-8"))
        print("Selection:")
        print(json.dumps(arc["aggregation"]["selection"], indent=2, ensure_ascii=False)[:2000])
        print()
        for i, r in enumerate(arc["verification_runs"]):
            params = r.get("params", {})
            score = _score_run_bias(r)
            print(f"run[{i}] white_C0={params.get('white_C0')}")
            print(f"        score={score}")


if __name__ == "__main__":
    main()
