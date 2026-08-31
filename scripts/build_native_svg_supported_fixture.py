#!/usr/bin/env python3
"""Build the deterministic native-SVG supported-scale benchmark fixture."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import lumina_svg_core  # noqa: E402


SOURCE_SHA256 = (
    "d078cf4293623d934759c2688e13a00491e525055e7595069a0ecc4f078842fb"
)
EXPECTED_FIXTURE_SHA256 = (
    "aedd2705dff8a61779418ddb4574aff7d2b22e19577fa798ebc669e4b60f9070"
)
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
GRID_SIDE = 32
CELL_USER_UNITS = 500.0
CELL_MARGIN_USER_UNITS = 25.0

# These are the 64 longest source paths that independently passed the v0.1
# recorder, precision, topology, curve-tolerance, and legacy-close identity
# gates when normalized into one cell of the fixed 32 x 32 canvas. The list is
# data, not a runtime capability scan: changing it changes the fixture SHA.
SELECTED_SOURCE_PATH_INDICES = (
    35,
    99,
    74,
    187,
    52,
    39,
    139,
    83,
    72,
    71,
    221,
    228,
    43,
    93,
    63,
    75,
    91,
    58,
    87,
    54,
    109,
    339,
    59,
    252,
    204,
    159,
    154,
    260,
    244,
    41,
    439,
    297,
    66,
    158,
    429,
    136,
    150,
    301,
    183,
    395,
    90,
    142,
    398,
    143,
    416,
    294,
    134,
    212,
    336,
    123,
    119,
    438,
    401,
    102,
    127,
    133,
    108,
    115,
    65,
    360,
    238,
    160,
    235,
    193,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _paint_bounds(root: ET.Element, child: ET.Element) -> tuple[float, ...]:
    probe = ET.Element(root.tag, root.attrib)
    probe.append(copy.deepcopy(child))
    recording = lumina_svg_core.record_paint_commands_svg(
        ET.tostring(probe, encoding="unicode")
    )
    if recording.status != "supported" or len(recording.commands) != 1:
        raise RuntimeError(
            "selected_source_path_no_longer_records:"
            + str(recording.reason_code)
        )
    bounds = tuple(float(value) for value in recording.bounds)
    if len(bounds) != 4 or bounds[2] <= 0.0 or bounds[3] <= 0.0:
        raise RuntimeError("selected_source_path_has_empty_bounds")
    return bounds


def build_fixture_payload(source_path: Path) -> bytes:
    """Return canonical fixture bytes after verifying the real source SHA."""

    source_payload = source_path.read_bytes()
    actual_source_sha256 = _sha256(source_payload)
    if actual_source_sha256 != SOURCE_SHA256:
        raise ValueError(
            f"unexpected_source_sha256:{actual_source_sha256}"
        )

    ET.register_namespace("", SVG_NAMESPACE)
    source_root = ET.fromstring(source_payload)
    source_paths = [
        child
        for child in source_root
        if child.tag.rsplit("}", 1)[-1] == "path"
    ]
    if len(source_paths) != 3097:
        raise ValueError(f"unexpected_source_path_count:{len(source_paths)}")

    canvas = GRID_SIDE * CELL_USER_UNITS
    fixture_root = ET.Element(
        source_root.tag,
        {
            "version": "1.1",
            "viewBox": f"0 0 {canvas:g} {canvas:g}",
            "width": f"{canvas:g}",
            "height": f"{canvas:g}",
            "data-lumina-benchmark-source-sha256": SOURCE_SHA256,
            "data-selection": "longest-64-safe-paths",
        },
    )
    selected = [source_paths[index] for index in SELECTED_SOURCE_PATH_INDICES]
    selected_bounds = [
        _paint_bounds(source_root, child) for child in selected
    ]
    cell_inner = CELL_USER_UNITS - 2.0 * CELL_MARGIN_USER_UNITS
    for slot in range(GRID_SIDE * GRID_SIDE):
        source_offset = slot % len(selected)
        source_index = SELECTED_SOURCE_PATH_INDICES[source_offset]
        child = selected[source_offset]
        x, y, width, height = selected_bounds[source_offset]
        scale = min(cell_inner / width, cell_inner / height)
        column = slot % GRID_SIDE
        row = slot // GRID_SIDE
        translate_x = (
            column * CELL_USER_UNITS
            + CELL_MARGIN_USER_UNITS
            + (cell_inner - scale * width) / 2.0
            - scale * x
        )
        translate_y = (
            row * CELL_USER_UNITS
            + CELL_MARGIN_USER_UNITS
            + (cell_inner - scale * height) / 2.0
            - scale * y
        )
        group = ET.SubElement(
            fixture_root,
            f"{{{SVG_NAMESPACE}}}g",
            {
                "transform": (
                    f"matrix({scale:.17g} 0 0 {scale:.17g} "
                    f"{translate_x:.17g} {translate_y:.17g})"
                ),
                "data-source-path-index": str(source_index),
                "data-repeat": str(slot // len(selected)),
            },
        )
        group.append(copy.deepcopy(child))

    payload = ET.tostring(
        fixture_root,
        encoding="utf-8",
        xml_declaration=True,
    )
    actual_fixture_sha256 = _sha256(payload)
    if actual_fixture_sha256 != EXPECTED_FIXTURE_SHA256:
        raise RuntimeError(
            f"unexpected_fixture_sha256:{actual_fixture_sha256}"
        )
    return payload


def provenance(payload: bytes) -> dict[str, object]:
    """Return the auditable source/selection record for fixture bytes."""

    return {
        "schema_version": 1,
        "classification": "derived_supported_scale",
        "source": {
            "path": "test_images/benchmark.svg",
            "sha256": SOURCE_SHA256,
            "path_count": 3097,
        },
        "selection": {
            "policy": "longest_64_fail_closed_safe_paths_tiled_16_times",
            "source_path_indices": list(SELECTED_SOURCE_PATH_INDICES),
            "unique_source_path_count": len(SELECTED_SOURCE_PATH_INDICES),
            "repeat_count": 16,
            "grid": [GRID_SIDE, GRID_SIDE],
            "overlap_policy": "disjoint_cell_bounds",
        },
        "fixture": {
            "path": (
                "native/lumina-svg-core/benchmarks/"
                "supported_scale_fixture.svg"
            ),
            "sha256": _sha256(payload),
            "byte_size": len(payload),
            "path_count": GRID_SIDE * GRID_SIDE,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=REPO_ROOT / "test_images" / "benchmark.svg",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            REPO_ROOT
            / "native"
            / "lumina-svg-core"
            / "benchmarks"
            / "supported_scale_fixture.svg"
        ),
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    payload = build_fixture_payload(args.source.resolve())
    output_path = args.output.resolve()
    if args.verify:
        if not output_path.is_file() or output_path.read_bytes() != payload:
            raise SystemExit("supported_scale_fixture_is_stale")
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(payload)

    record = provenance(payload)
    if args.manifest is not None:
        manifest_path = args.manifest.resolve()
        if not args.verify:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif not manifest_path.is_file() or json.loads(
            manifest_path.read_text(encoding="utf-8")
        ) != record:
            raise SystemExit("supported_scale_fixture_manifest_is_stale")
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
