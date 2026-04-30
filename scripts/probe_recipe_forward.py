"""Forward-simulate the 5-layer recipe [品红, 肤色, 品红, 肤色, 绿色]
on a white substrate at 0.08 mm layer height, using the current
material parameters in materials/.

Read-only diagnostic.
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


def load_material(material_dir: Path) -> MaterialParams:
    archive = json.loads((material_dir / "material.json").read_text(encoding="utf-8"))
    stage_a = json.loads(
        (material_dir / "stage_A_parameters.json").read_text(encoding="utf-8")
    )
    channels = (stage_a.get("parameters") or {}).get("channels") or []
    if not channels:
        raise ValueError(f"No channels for {material_dir}")
    ch0 = channels[0]
    E = np.asarray(ch0["E"], dtype=np.float64)
    k = np.asarray(ch0["k"], dtype=np.float64)
    substrates = (stage_a.get("parameters") or {}).get("substrates") or []
    C0_white = None
    for sub in substrates:
        if sub.get("substrate_id") == "white":
            C0_white = np.asarray(sub["C0"], dtype=np.float64)
            break
    if C0_white is None:
        raise ValueError(f"No white C0 for {material_dir}")
    msum = archive.get("material_summary") or {}
    est_rgb = np.asarray(msum.get("estimated_rgb", [0, 0, 0]), dtype=np.uint8)
    name = str(archive.get("material_name") or material_dir.name)
    meta_lh = msum.get("layer_height_mm")
    print(
        f"  loaded {name:<22} E={[round(float(v),3) for v in E]} "
        f"k={[round(float(v),3) for v in k]} "
        f"C0_white={[round(float(v),3) for v in C0_white]} "
        f"metadata_layer_h={meta_lh}"
    )
    return MaterialParams(
        name=name,
        directory_name=material_dir.name,
        E=E,
        k=k,
        C0_white=C0_white,
        estimated_rgb=est_rgb,
    )


def linear_to_uint8(linear_rgb: np.ndarray) -> np.ndarray:
    return np.round(linear_to_srgb_float(linear_rgb) * 255.0).astype(np.uint8)


def main() -> None:
    materials_dir = REPO / "materials"
    pinhong = load_material(materials_dir / "无境新材" / "品红")
    furo = load_material(materials_dir / "彩多屋" / "彩多屋 PLA 肤色")
    lyu = load_material(materials_dir / "瑞贝思" / "瑞贝思 PLA 绿")

    palette = [pinhong, furo, lyu]  # indices: 0=品红, 1=肤色, 2=绿
    layer_height_mm = 0.08
    substrate_white = np.ones(3, dtype=np.float64)

    cases = [
        (
            "底->顶 = [品红, 肤色, 品红, 肤色, 绿色]  (绿色在顶, 即视线侧)",
            np.array([[0, 1, 0, 1, 2]], dtype=np.int64),
        ),
        (
            "底->顶 = [绿色, 肤色, 品红, 肤色, 品红]  (品红在顶, 即视线侧)",
            np.array([[2, 1, 0, 1, 0]], dtype=np.int64),
        ),
    ]
    print("\n# Forward simulation @ 0.08 mm, white substrate")
    for label, recipes in cases:
        out_lin = forward_batch_model(
            recipes=recipes,
            materials=palette,
            layer_height_mm=layer_height_mm,
            substrate_linear=substrate_white,
        )
        out_srgb = linear_to_uint8(out_lin)[0]
        out_lin0 = out_lin[0]
        print(f"\n  {label}")
        print(f"    predicted linear RGB = {[round(float(v),4) for v in out_lin0]}")
        print(f"    predicted sRGB uint8 = {tuple(int(v) for v in out_srgb)}")

    print("\n# Per-layer running color (linear -> sRGB) for the 1st recipe:")
    recipe = cases[0][1][0]
    C = substrate_white.copy()
    print(f"  layer 0 (substrate)     -> linear {tuple(round(float(v),3) for v in C)} "
          f"sRGB {tuple(int(v) for v in linear_to_uint8(C.reshape(1,3))[0])}")
    for i, mat_idx in enumerate(recipe, start=1):
        m = palette[mat_idx]
        a = float(np.exp(-m.k * layer_height_mm)[0])
        C = m.E + (C - m.E) * np.exp(-m.k * layer_height_mm)
        print(
            f"  after layer {i} = {m.name:<14} -> linear "
            f"{tuple(round(float(v),3) for v in C)} "
            f"sRGB {tuple(int(v) for v in linear_to_uint8(C.reshape(1,3))[0])}"
        )


if __name__ == "__main__":
    main()
