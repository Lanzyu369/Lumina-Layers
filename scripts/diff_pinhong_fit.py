"""Compare 无境新材/品红 material.json across the last two commits and dump fit_summary
for every material currently used (8-color recipe).

Read-only diagnostic helper for a one-shot user request.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def git_show_json(commitish: str, path: str) -> dict[str, Any] | None:
    proc = subprocess.run(
        ["git", "show", f"{commitish}:{path}"],
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout.decode("utf-8"))


def read_local_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def short(v: Any, n: int = 5) -> Any:
    if isinstance(v, float):
        return round(v, n)
    if isinstance(v, list):
        return [short(x, n) for x in v]
    if isinstance(v, dict):
        return {k: short(val, n) for k, val in v.items()}
    return v


def summarize_material(label: str, doc: dict[str, Any]) -> None:
    print(f"\n=== {label} ===")
    print(f"  material_name = {doc.get('material_name')!r}")
    print(f"  created_at    = {doc.get('created_at')}")
    print(f"  updated_at    = {doc.get('updated_at')}")
    print(f"  verification_count = {doc.get('verification_count')}")
    fit = doc.get("fit_summary") or {}
    print(f"  fit_summary keys: {sorted(fit.keys())}")
    for k in (
        "rmse",
        "rmse_lab",
        "rmse_rgb",
        "rmse_xyz",
        "delta_e_mean",
        "delta_e_max",
        "delta_e_p95",
        "n_samples",
        "loss",
        "residual",
        "g0_mode",
        "thickness_um",
    ):
        if k in fit:
            print(f"    {k} = {short(fit[k])}")
    msum = doc.get("material_summary") or {}
    print(f"  material_summary keys: {sorted(msum.keys())}")
    for k in (
        "ks_K",
        "ks_S",
        "K",
        "S",
        "K_over_S",
        "g0",
        "g0_mode",
        "thickness_um",
        "lab_full",
        "rgb_full",
        "xyz_full",
        "rgb_substrate",
        "lab_substrate",
        "scale",
        "alpha",
        "beta",
    ):
        if k in msum:
            print(f"    {k} = {short(msum[k])}")
    agg = doc.get("aggregation") or {}
    if agg:
        print(f"  aggregation keys: {sorted(agg.keys())}")
        for k in ("rmse", "delta_e_mean", "delta_e_p95", "n_samples", "weight"):
            if k in agg:
                print(f"    agg.{k} = {short(agg[k])}")


def main() -> None:
    pinhong = "materials/无境新材/品红/material.json"
    print("# 无境新材/品红 — old (cbfd1e6) vs new (HEAD)")
    old = git_show_json("cbfd1e6", pinhong)
    if old is None:
        print("  cbfd1e6 not found")
    else:
        summarize_material("OLD cbfd1e6", old)
    new = read_local_json(pinhong)
    summarize_material("NEW HEAD", new)

    # All 8 materials in the user's recipe
    recipe_paths = [
        "materials/瑞贝思/瑞贝思 PLA 白/material.json",
        "materials/瑞贝思/瑞贝思 PLA 红/material.json",
        "materials/瑞贝思/瑞贝思 PLA 绿/material.json",
        "materials/瑞贝思/瑞贝思 PLA 蓝/material.json",
        "materials/瑞贝思/瑞贝思 PLA 黑/material.json",
        "materials/无境新材/品红/material.json",
        "materials/彩多屋/彩多屋 PLA 肤色/material.json",
    ]
    # 6th 瑞贝思 — search dir
    rb_dir = Path("materials/瑞贝思")
    if rb_dir.exists():
        for sub in sorted(rb_dir.iterdir()):
            if sub.is_dir() and (sub / "material.json").exists():
                p = (sub / "material.json").as_posix()
                if p not in recipe_paths:
                    recipe_paths.append(p)

    print("\n# Current 8-color recipe — fit_summary snapshot")
    for path in recipe_paths:
        if not Path(path).exists():
            print(f"\n=== MISSING: {path} ===")
            continue
        doc = read_local_json(path)
        summarize_material(path, doc)


if __name__ == "__main__":
    main()
