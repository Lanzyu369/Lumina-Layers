"""Diagnostic comparison: 无境新材/品红 (cbfd1e6 vs HEAD) and 8-color recipe snapshot."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def git_show_json(commitish: str, path: str) -> dict[str, Any] | None:
    proc = subprocess.run(["git", "show", f"{commitish}:{path}"], capture_output=True)
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout.decode("utf-8"))


def read_local_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def r(v: Any, n: int = 4) -> Any:
    if isinstance(v, float):
        return round(v, n)
    if isinstance(v, list):
        return [r(x, n) for x in v]
    return v


def show(label: str, doc: dict[str, Any]) -> None:
    fit = doc.get("fit_summary", {}) or {}
    val = fit.get("overall_validation", {}) or {}
    msum = doc.get("material_summary", {}) or {}
    print(f"  {label}")
    print(f"    updated_at        = {doc.get('updated_at')}")
    print(f"    mean_delta_e      = {r(val.get('mean_delta_e'))}")
    print(f"    max_delta_e       = {r(val.get('max_delta_e'))}")
    print(f"    rmse_linear       = {r(val.get('rmse_linear'), 5)}")
    print(f"    channel_rmse(RGB) = {r(val.get('channel_rmse'), 5)}")
    print(f"    estimated_rgb     = {msum.get('estimated_rgb')}")
    print(f"    estimated_k(RGB)  = {r(msum.get('estimated_k'), 4)}")
    print(f"    white_zero_rgb    = {msum.get('white_zero_rgb')}")
    print(f"    black_zero_rgb    = {msum.get('black_zero_rgb')}")
    print(f"    sample_count      = {msum.get('sample_count')} "
          f"(per-substrate {msum.get('per_substrate_sample_count')})")
    print(f"    layer_height_mm   = {msum.get('layer_height_mm')}")
    print(f"    thickness_layers  = {msum.get('thickness_layers')}")
    warns = fit.get("warnings") or []
    if warns:
        print(f"    warnings          = {warns}")


def main() -> None:
    pinhong = "materials/无境新材/品红/material.json"
    print("# 无境新材/品红 — old (cbfd1e6 = 2026-04-26 09:00) vs new (HEAD)")
    old = git_show_json("cbfd1e6", pinhong)
    if old is not None:
        show("OLD cbfd1e6", old)
    show("NEW  HEAD ", read_local_json(pinhong))

    print("\n# 当前所有耗材 fit 指标（mean_delta_e / max_delta_e / rmse_linear / estimated_k）")
    paths: list[str] = []
    rb = Path("materials/瑞贝思")
    for sub in sorted(rb.iterdir()):
        if sub.is_dir() and (sub / "material.json").exists():
            paths.append((sub / "material.json").as_posix())
    paths.append("materials/无境新材/品红/material.json")
    paths.append("materials/彩多屋/彩多屋 PLA 肤色/material.json")
    for p in paths:
        if not Path(p).exists():
            print(f"  MISSING: {p}")
            continue
        print(f"\n  {p}")
        show("  ", read_local_json(p))


if __name__ == "__main__":
    main()
