"""Compare every available 无境新材 品红 calibration:

- OLD cbfd1e6 (metadata layer_height=0.04, k≈2× true) — the historical
  archive that motivated the metadata fix.
- NEW HEAD  品红 / 品红1 / 品红2 / 品红3 / 品红4 — successive recalibrations
  recorded by the user as we iterated on capture conditions and on the
  Stage A pipeline.

For each variant:

- print fit metrics + estimated_rgb + estimated_k + the loaded (E, k, C0_white)
- forward-simulate two disputed 5-layer recipes
  ([品红, 肤色, 品红, 肤色, 绿色] and its reverse) on white substrate @ 0.08 mm
- list the per-channel single-layer attenuation a = exp(-k * 0.08)
- list the predicted colour of a single 品红 layer over white @ 0.08 mm

The variant set is defined exactly once in :data:`VARIANTS` so adding a
new 品红N only requires one line.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.material_color_solver import (  # noqa: E402
    MaterialParams,
    forward_batch_model,
    linear_to_srgb_float,
)


def linear_to_uint8(linear_rgb: np.ndarray) -> np.ndarray:
    return np.round(linear_to_srgb_float(linear_rgb) * 255.0).astype(np.uint8)


def load_material_from_paths(
    material_json_path: Path, stage_a_path: Path, name: str | None = None
) -> tuple[MaterialParams, dict[str, Any]]:
    archive = json.loads(material_json_path.read_text(encoding="utf-8"))
    stage_a = json.loads(stage_a_path.read_text(encoding="utf-8"))
    channels = (stage_a.get("parameters") or {}).get("channels") or []
    ch0 = channels[0]
    E = np.asarray(ch0["E"], dtype=np.float64)
    k = np.asarray(ch0["k"], dtype=np.float64)
    substrates = (stage_a.get("parameters") or {}).get("substrates") or []
    C0_white = None
    for sub in substrates:
        if sub.get("substrate_id") == "white":
            C0_white = np.asarray(sub["C0"], dtype=np.float64)
            break
    msum = archive.get("material_summary") or {}
    est_rgb = np.asarray(msum.get("estimated_rgb", [0, 0, 0]), dtype=np.uint8)
    return (
        MaterialParams(
            name=name or str(archive.get("material_name") or "unknown"),
            directory_name=material_json_path.parent.name,
            E=E,
            k=k,
            C0_white=C0_white,
            estimated_rgb=est_rgb,
        ),
        archive,
    )


def load_local(path_dir: Path, label: str) -> tuple[MaterialParams, dict[str, Any]]:
    return load_material_from_paths(
        path_dir / "material.json",
        path_dir / "stage_A_parameters.json",
        name=label,
    )


def load_from_git(commitish: str, path: str) -> dict[str, Any]:
    proc = subprocess.run(["git", "show", f"{commitish}:{path}"], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git show failed for {commitish}:{path}: {proc.stderr.decode('utf-8', 'ignore')}")
    return json.loads(proc.stdout.decode("utf-8"))


def show_summary(label: str, archive: dict[str, Any], mp: MaterialParams) -> None:
    fit = archive.get("fit_summary", {}) or {}
    val = fit.get("overall_validation", {}) or {}
    msum = archive.get("material_summary", {}) or {}
    print(f"\n  --- {label} ---")
    print(f"    updated_at        = {archive.get('updated_at')}")
    print(f"    metadata_layer_h  = {msum.get('layer_height_mm')}")
    print(f"    mean_delta_e      = {round(float(val.get('mean_delta_e', 0)), 4)}")
    print(f"    max_delta_e       = {round(float(val.get('max_delta_e', 0)), 4)}")
    print(f"    rmse_linear       = {round(float(val.get('rmse_linear', 0)), 5)}")
    print(f"    estimated_rgb     = {msum.get('estimated_rgb')}")
    print(f"    estimated_k(RGB)  = {[round(float(v),4) for v in msum.get('estimated_k', [])]}")
    print(f"    white_zero_rgb    = {msum.get('white_zero_rgb')}")
    print(f"    black_zero_rgb    = {msum.get('black_zero_rgb')}")
    print(f"    thickness_layers  = {msum.get('thickness_layers')}")
    print(f"    Loaded params:")
    print(f"      E      = {[round(float(v),4) for v in mp.E]}")
    print(f"      k      = {[round(float(v),4) for v in mp.k]}")
    print(f"      C0_white = {[round(float(v),4) for v in mp.C0_white]}")


def forward_recipe(palette: list[MaterialParams], recipe: list[int],
                   layer_height_mm: float = 0.08) -> tuple[np.ndarray, np.ndarray]:
    out_lin = forward_batch_model(
        recipes=np.array([recipe], dtype=np.int64),
        materials=palette,
        layer_height_mm=layer_height_mm,
        substrate_linear=np.ones(3, dtype=np.float64),
    )
    out_srgb = linear_to_uint8(out_lin)[0]
    return out_lin[0], out_srgb


def material_params_from_archive(
    archive: dict[str, Any],
    stage_a: dict[str, Any],
    *,
    name: str,
    directory_name: str,
) -> MaterialParams:
    """Reconstruct a :class:`MaterialParams` from raw archive + Stage A dicts.
    用 archive + Stage A 字典手工重建 MaterialParams，便于复用 git-show 来源。
    """
    channels = (stage_a.get("parameters") or {}).get("channels") or []
    substrates = (stage_a.get("parameters") or {}).get("substrates") or []
    E = np.asarray(channels[0]["E"], dtype=np.float64)
    k = np.asarray(channels[0]["k"], dtype=np.float64)
    C0_white = None
    for sub in substrates:
        if sub.get("substrate_id") == "white":
            C0_white = np.asarray(sub["C0"], dtype=np.float64)
            break
    msum = archive.get("material_summary") or {}
    est_rgb = np.asarray(msum.get("estimated_rgb", [0, 0, 0]), dtype=np.uint8)
    return MaterialParams(
        name=name,
        directory_name=directory_name,
        E=E,
        k=k,
        C0_white=C0_white,
        estimated_rgb=est_rgb,
    )


def main() -> None:
    materials_dir = REPO / "materials"

    # Helper materials shared across all 品红 variants
    furo, _ = load_local(materials_dir / "彩多屋" / "彩多屋 PLA 肤色", "彩多屋 PLA 肤色")
    lyu, _ = load_local(materials_dir / "瑞贝思" / "瑞贝思 PLA 绿", "瑞贝思 PLA 绿")

    # ---- Single source of truth for every 品红 variant ----
    # Tuple shape: (display_label, padded_label_for_grid, MaterialParams, archive_dict)
    # The padded label is fixed-width so the forward-simulation grids
    # below align cleanly when more variants get added.
    # ``OLD cbfd1e6`` is loaded directly from git so we can compare the
    # historical archive against today's recalibrations without polluting
    # the working tree.
    variants: list[tuple[str, str, MaterialParams, dict[str, Any]]] = []

    old_archive = load_from_git("cbfd1e6", "materials/无境新材/品红/material.json")
    old_stage_a = load_from_git(
        "cbfd1e6", "materials/无境新材/品红/stage_A_parameters.json"
    )
    pinhong_old = material_params_from_archive(
        old_archive, old_stage_a,
        name="品红 (OLD cbfd1e6)",
        directory_name="无境新材/品红",
    )
    variants.append((
        "OLD cbfd1e6 (metadata 0.04, k 高估 2x)",
        "OLD cbfd1e6  ",
        pinhong_old,
        old_archive,
    ))

    head_dirs: list[tuple[str, str, str]] = [
        ("品红", "NEW HEAD 品红 (metadata 0.08)", "NEW HEAD 品红 "),
        ("品红1", "NEW HEAD 品红1 (新校准)", "NEW HEAD 品红1"),
        ("品红2", "NEW HEAD 品红2 (新校准2)", "NEW HEAD 品红2"),
        ("品红3", "NEW HEAD 品红3 (新校准3)", "NEW HEAD 品红3"),
        ("品红4", "NEW HEAD 品红4 (新校准4)", "NEW HEAD 品红4"),
    ]
    for dir_name, summary_label, grid_label in head_dirs:
        params, archive = load_local(materials_dir / "无境新材" / dir_name, summary_label)
        variants.append((summary_label, grid_label, params, archive))

    # ---- Stage 1: per-variant fit metrics + loaded params ----
    print("# 五个 品红 校准版本 — 拟合指标与已加载参数")
    for summary_label, _grid_label, params, archive in variants:
        show_summary(summary_label, archive, params)

    # ---- Stage 2: forward simulation for the disputed recipes ----
    recipes = [
        ("底→顶 [品红, 肤色, 品红, 肤色, 绿色] (绿色顶)", [0, 1, 0, 1, 2]),
        ("底→顶 [绿色, 肤色, 品红, 肤色, 品红] (品红顶)", [2, 1, 0, 1, 0]),
    ]
    print("\n# Forward 模拟 @ 0.08 mm 白底")
    for label, recipe in recipes:
        print(f"\n  ## 配方: {label}")
        for _summary_label, grid_label, params, _archive in variants:
            palette = [params, furo, lyu]
            lin, rgb = forward_recipe(palette, recipe, layer_height_mm=0.08)
            print(
                f"    {grid_label}: linear={[round(float(v),3) for v in lin]} "
                f"sRGB={tuple(int(v) for v in rgb)}"
            )

    # ---- Stage 3: per-variant single-layer attenuation @ 0.08 mm ----
    print("\n# 单层 @ 0.08 mm 时品红的 attenuation a = exp(-k*0.08)（越小=越遮盖）")
    for _summary_label, grid_label, params, _archive in variants:
        a = np.exp(-params.k * 0.08)
        print(f"    {grid_label}: a={[round(float(v),3) for v in a]} (R, G, B)")

    # ---- Stage 4: single 品红 layer covering white @ 0.08 mm ----
    print("\n# 1 层品红覆盖白底 @ 0.08 mm 的预测颜色")
    for _summary_label, grid_label, params, _archive in variants:
        lin, rgb = forward_recipe([params], [0], 0.08)
        print(
            f"    {grid_label}: linear={[round(float(v),3) for v in lin]} "
            f"sRGB={tuple(int(v) for v in rgb)}"
        )


if __name__ == "__main__":
    main()
