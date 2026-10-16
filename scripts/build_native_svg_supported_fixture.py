#!/usr/bin/env python3
"""Generate a deterministic native-SVG workload without external artwork."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[1]
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
GRID_SIDE = 32
CELL_USER_UNITS = 500
POINTS_PER_PATH = 64
FIXTURE_PATH = REPO_ROOT / "native/lumina-svg-core/benchmarks/supported_scale_fixture.svg"


def _outline(variant: int) -> str:
    """Return a closed radial contour defined only by analytic functions."""
    points: list[str] = []
    phase = variant * math.tau / 64
    amplitude = 0.10 + 0.015 * (variant % 4)
    for index in range(POINTS_PER_PATH):
        angle = index * math.tau / POINTS_PER_PATH
        radius = 180 * (1 + amplitude * math.sin(3 * angle + phase)
                        + 0.05 * math.cos(5 * angle - phase))
        x = CELL_USER_UNITS / 2 + radius * math.cos(angle)
        y = CELL_USER_UNITS / 2 + radius * math.sin(angle)
        points.append(f"{x:.4f} {y:.4f}")
    return "M " + " L ".join(points) + " Z"


def build_fixture_payload() -> bytes:
    """Return 1,024 disjoint polygons with 65,536 contour vertices."""
    ET.register_namespace("", SVG_NAMESPACE)
    canvas = GRID_SIDE * CELL_USER_UNITS
    root = ET.Element(f"{{{SVG_NAMESPACE}}}svg", {
        "version": "1.1", "viewBox": f"0 0 {canvas} {canvas}",
        "width": str(canvas), "height": str(canvas),
    })
    for slot in range(GRID_SIDE * GRID_SIDE):
        variant = slot % 64
        group = ET.SubElement(root, f"{{{SVG_NAMESPACE}}}g", {
            "transform": f"translate({slot % GRID_SIDE * CELL_USER_UNITS} "
                         f"{slot // GRID_SIDE * CELL_USER_UNITS})",
        })
        color = tuple(16 + (variant * multiplier + offset) % 240
                      for multiplier, offset in [(41, 37), (73, 19), (29, 113)])
        ET.SubElement(group, f"{{{SVG_NAMESPACE}}}path", {
            "d": _outline(variant), "fill": "#%02x%02x%02x" % color,
        })
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def provenance(payload: bytes) -> dict[str, object]:
    """Describe this generated workload without identifying it as real artwork."""
    return {
        "schema_version": 2,
        "classification": "owned_synthetic_scale",
        "source": {"generator": "scripts/build_native_svg_supported_fixture.py",
                   "external_artwork": None, "algorithm": "radial_contours_v1"},
        "selection": {"grid": [GRID_SIDE, GRID_SIDE],
                      "points_per_path": POINTS_PER_PATH,
                      "overlap_policy": "disjoint_cell_bounds"},
        "fixture": {"path": FIXTURE_PATH.relative_to(REPO_ROOT).as_posix(),
                    "byte_size": len(payload), "path_count": GRID_SIDE * GRID_SIDE},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    payload = build_fixture_payload()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    record = provenance(payload)
    if args.manifest is not None:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
