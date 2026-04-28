"""One-shot diagnostic: print 品红4 archive after the user's second
verification run, including per-run breakdown so we can see whether
the merged refit improves over the single-run baseline.

This script is intended to be deleted once the comparison is captured
in chat; it has no production callers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

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


def show_top_level(archive: dict) -> None:
    fit = archive.get("fit_summary") or {}
    val = fit.get("overall_validation") or {}
    ms = archive.get("material_summary") or {}
    agg = archive.get("aggregation") or {}
    print("# 品红4 (HEAD) — aggregated archive")
    print(f"  updated_at         = {archive.get('updated_at')}")
    print(f"  verification_count = {archive.get('verification_count')}")
    print(f"  aggregation.method = {agg.get('method')}")
    print(f"  aggregation.image_source = {agg.get('image_source')}")
    print(f"  mean_delta_e       = {round(float(val.get('mean_delta_e') or 0), 4)}")
    print(f"  max_delta_e        = {round(float(val.get('max_delta_e') or 0), 4)}")
    print(f"  rmse_linear        = {round(float(val.get('rmse_linear') or 0), 5)}")
    ce = val.get("channel_rmse") or []
    print(f"  channel_rmse(RGB)  = {[round(float(v), 5) for v in ce]}")
    print(f"  estimated_rgb      = {ms.get('estimated_rgb')}")
    print(f"  estimated_k(RGB)   = {[round(float(v), 4) for v in (ms.get('estimated_k') or [])]}")
    print(f"  white_zero_rgb     = {ms.get('white_zero_rgb')}")
    print(f"  black_zero_rgb     = {ms.get('black_zero_rgb')}")
    print(f"  layer_height_mm    = {ms.get('layer_height_mm')}")
    print(f"  warnings           = {fit.get('warnings')}")


def show_runs(archive: dict) -> None:
    runs = archive.get("verification_runs") or []
    print(f"\n# 各 verification_run 拆分 (n={len(runs)})")
    for i, r in enumerate(runs):
        rfit = (r.get("fit_summary") or {}).get("overall_validation") or {}
        rms = r.get("material_summary") or {}
        rs = r.get("source") or {}
        captured_at = r.get("captured_at") or rs.get("captured_at") or "-"
        img_src = rs.get("image_source", "-")
        print(f"  run[{i}] captured_at={captured_at} image_source={img_src}")
        print(
            f"          mean={round(float(rfit.get('mean_delta_e') or 0), 4)} "
            f"max={round(float(rfit.get('max_delta_e') or 0), 4)} "
            f"rmse={round(float(rfit.get('rmse_linear') or 0), 5)}"
        )
        k_list = rms.get("estimated_k") or []
        print(
            f"          k={[round(float(v), 4) for v in k_list]} "
            f"white_zero_rgb={rms.get('white_zero_rgb')} "
            f"black_zero_rgb={rms.get('black_zero_rgb')}"
        )


def show_forward(archive: dict, stage_a: dict) -> None:
    """Use the merged (E, k, C0_white) for the same recipes the previous
    comparison printed, so the user can see the visual delta side-by-side."""
    channels = (stage_a.get("parameters") or {}).get("channels") or []
    substrates = (stage_a.get("parameters") or {}).get("substrates") or []
    E = np.asarray(channels[0]["E"], dtype=np.float64)
    k = np.asarray(channels[0]["k"], dtype=np.float64)
    C0w = None
    for sub in substrates:
        if sub.get("substrate_id") == "white":
            C0w = np.asarray(sub["C0"], dtype=np.float64)
            break
    ms = archive.get("material_summary") or {}
    pinhong = MaterialParams(
        name="品红4 (merged)",
        directory_name="无境新材/品红4",
        E=E, k=k, C0_white=C0w,
        estimated_rgb=np.asarray(ms.get("estimated_rgb", [0, 0, 0]), dtype=np.uint8),
    )

    def load_local(path: Path, name: str) -> MaterialParams:
        arc = json.loads((path / "material.json").read_text(encoding="utf-8"))
        sa = json.loads((path / "stage_A_parameters.json").read_text(encoding="utf-8"))
        chs = (sa.get("parameters") or {}).get("channels") or []
        subs = (sa.get("parameters") or {}).get("substrates") or []
        E2 = np.asarray(chs[0]["E"], dtype=np.float64)
        k2 = np.asarray(chs[0]["k"], dtype=np.float64)
        C0w2 = None
        for sub in subs:
            if sub.get("substrate_id") == "white":
                C0w2 = np.asarray(sub["C0"], dtype=np.float64)
                break
        ms2 = arc.get("material_summary") or {}
        return MaterialParams(
            name=name,
            directory_name=path.name,
            E=E2, k=k2, C0_white=C0w2,
            estimated_rgb=np.asarray(ms2.get("estimated_rgb", [0, 0, 0]), dtype=np.uint8),
        )

    materials = REPO / "materials"
    furo = load_local(materials / "彩多屋" / "彩多屋 PLA 肤色", "彩多屋 PLA 肤色")
    lyu = load_local(materials / "瑞贝思" / "瑞贝思 PLA 绿", "瑞贝思 PLA 绿")

    palette = [pinhong, furo, lyu]
    recipes = [
        ("底→顶 [品红, 肤色, 品红, 肤色, 绿色] (绿色顶)", [0, 1, 0, 1, 2]),
        ("底→顶 [绿色, 肤色, 品红, 肤色, 品红] (品红顶)", [2, 1, 0, 1, 0]),
    ]
    print("\n# Forward 模拟 @ 0.08 mm 白底 (合并后参数)")
    for label, recipe in recipes:
        out_lin = forward_batch_model(
            recipes=np.array([recipe], dtype=np.int64),
            materials=palette,
            layer_height_mm=0.08,
            substrate_linear=np.ones(3, dtype=np.float64),
        )
        srgb = linear_to_uint8(out_lin)[0]
        print(
            f"  {label}\n"
            f"    linear={[round(float(v), 3) for v in out_lin[0]]} "
            f"sRGB={tuple(int(v) for v in srgb)}"
        )

    a = np.exp(-pinhong.k * 0.08)
    print(f"\n  单层 attenuation a=exp(-k*0.08) = {[round(float(v), 3) for v in a]} (R, G, B)")

    out_lin = forward_batch_model(
        recipes=np.array([[0]], dtype=np.int64),
        materials=palette,
        layer_height_mm=0.08,
        substrate_linear=np.ones(3, dtype=np.float64),
    )
    srgb = linear_to_uint8(out_lin)[0]
    print(
        f"  1 层品红覆盖白底 sRGB = {tuple(int(v) for v in srgb)} "
        f"linear={[round(float(v), 3) for v in out_lin[0]]}"
    )


def main() -> None:
    archive_path = REPO / "materials" / "无境新材" / "品红4" / "material.json"
    stage_a_path = REPO / "materials" / "无境新材" / "品红4" / "stage_A_parameters.json"
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    stage_a = json.loads(stage_a_path.read_text(encoding="utf-8"))
    show_top_level(archive)
    show_runs(archive)
    show_forward(archive, stage_a)


if __name__ == "__main__":
    main()
