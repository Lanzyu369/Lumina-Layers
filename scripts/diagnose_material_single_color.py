from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.material_cache import load_material_solver_cache
from core.material_lut_synthesis import load_multiple_materials
from core.material_color_solver import solve_image_colors_optimal


def _parse_hex_color(raw: str) -> tuple[str, list[int]]:
    cleaned = raw.strip()
    if cleaned.startswith("#"):
        cleaned = cleaned[1:]
    if len(cleaned) == 3:
        cleaned = "".join(ch * 2 for ch in cleaned)
    if len(cleaned) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in cleaned):
        raise ValueError(f"Invalid target hex color: {raw!r}")
    cleaned = cleaned.upper()
    return cleaned, [int(cleaned[i:i + 2], 16) for i in range(0, 6, 2)]


def _recipe_names(materials, recipe: np.ndarray) -> list[str]:
    return [materials[int(index)].name for index in recipe.tolist()]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--material", action="append", required=True)
    parser.add_argument("--target-hex", required=True)
    parser.add_argument("--layer-count", type=int, default=10)
    parser.add_argument("--layer-height-mm", type=float, default=0.08)
    parser.add_argument("--substrate", choices=("white", "black"), default="white")
    return parser.parse_args()


def main() -> int:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    args = _parse_args()
    target_hex, target_rgb = _parse_hex_color(args.target_hex)
    materials = load_multiple_materials(args.material)
    target = np.asarray([target_rgb], dtype=np.uint8)

    cache = load_material_solver_cache(
        materials,
        layer_count=args.layer_count,
        layer_height_mm=args.layer_height_mm,
        substrate=args.substrate,
    )

    report: dict[str, object] = {
        "target_hex": f"#{target_hex}",
        "target_rgb": target_rgb,
        "layer_count": int(args.layer_count),
        "layer_height_mm": float(args.layer_height_mm),
        "substrate": args.substrate,
        "materials": [mat.directory_name for mat in materials],
    }

    if cache is not None:
        cache_start = time.perf_counter()
        cache_rgb, cache_recipe, cache_delta_e = cache.lookup(target, materials)
        report["cache"] = {
            "status": "hit",
            "palette_hash": cache.palette_hash,
            "grid_resolution": cache.grid_resolution,
            "valid_cell_count": cache.valid_cell_count,
            "elapsed_seconds": time.perf_counter() - cache_start,
            "matched_rgb": cache_rgb[0].tolist(),
            "delta_e": float(cache_delta_e[0]),
            "recipe": cache_recipe[0].tolist(),
            "recipe_names": _recipe_names(materials, cache_recipe[0]),
        }
    else:
        report["cache"] = {
            "status": "miss",
        }

    strict_start = time.perf_counter()
    strict_rgb, strict_recipe, strict_delta_e = solve_image_colors_optimal(
        target,
        materials,
        layer_count=args.layer_count,
        layer_height_mm=args.layer_height_mm,
        substrate=args.substrate,
    )
    report["strict"] = {
        "elapsed_seconds": time.perf_counter() - strict_start,
        "matched_rgb": strict_rgb[0].tolist(),
        "delta_e": float(strict_delta_e[0]),
        "recipe": strict_recipe[0].tolist(),
        "recipe_names": _recipe_names(materials, strict_recipe[0]),
    }

    cache_info = report["cache"]
    if isinstance(cache_info, dict) and cache_info.get("status") == "hit":
        report["comparison"] = {
            "cache_minus_strict_delta_e": (
                float(cache_info["delta_e"]) - float(report["strict"]["delta_e"])
            ),
            "cache_matches_strict_rgb": cache_info["matched_rgb"] == report["strict"]["matched_rgb"],
            "cache_matches_strict_recipe": cache_info["recipe"] == report["strict"]["recipe"],
        }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
