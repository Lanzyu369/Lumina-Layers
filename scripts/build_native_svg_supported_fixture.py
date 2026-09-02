#!/usr/bin/env python3
"""Build the deterministic native-SVG supported-scale benchmark fixture."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import lumina_svg_core  # noqa: E402


SVG_NAMESPACE = "http://www.w3.org/2000/svg"
GRID_SIDE = 32
CELL_USER_UNITS = 500.0
CELL_MARGIN_USER_UNITS = 25.0
SELECTION_TARGET_WIDTH_MM = 111.0
SELECTION_TOLERANCE_MM = 0.02

# These paths were considered in descending serialized-size order and accepted
# only while the growing compound panel remained supported by the native
# parser. The tuple makes fixture generation deterministic.
SELECTED_SOURCE_PATH_INDICES = (
    35,
    74,
    52,
    39,
    72,
    71,
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
    159,
    154,
    244,
    41,
    66,
    158,
    136,
    150,
    183,
    395,
    90,
    142,
    143,
    134,
    212,
    123,
    119,
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
    107,
    224,
    293,
    241,
    463,
    200,
    300,
    410,
    430,
    210,
    356,
    237,
    277,
    545,
    234,
    56,
    510,
    278,
    290,
)


def load_source(source_path: Path) -> ET.Element:
    """Load an SVG source document without an identity preflight.

    不执行身份预检，直接加载 SVG 源文档。
    """
    source_payload = source_path.read_bytes()
    ET.register_namespace("", SVG_NAMESPACE)
    return ET.fromstring(source_payload)


def _source_paths(source_root: ET.Element) -> list[ET.Element]:
    return [
        child
        for child in source_root
        if child.tag.rsplit("}", 1)[-1] == "path"
    ]


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


def _placement_transform(
    bounds: tuple[float, ...], slot: int
) -> str:
    x, y, width, height = bounds
    cell_inner = CELL_USER_UNITS - 2.0 * CELL_MARGIN_USER_UNITS
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
    return (
        f"matrix({scale:.17g} 0 0 {scale:.17g} "
        f"{translate_x:.17g} {translate_y:.17g})"
    )


def _single_candidate_svg(
    source_root: ET.Element,
    child: ET.Element,
    bounds: tuple[float, ...],
) -> str:
    canvas = GRID_SIDE * CELL_USER_UNITS
    fixture_root = ET.Element(
        source_root.tag,
        {
            "version": "1.1",
            "viewBox": f"0 0 {canvas:g} {canvas:g}",
            "width": f"{canvas:g}",
            "height": f"{canvas:g}",
        },
    )
    group = ET.SubElement(
        fixture_root,
        f"{{{SVG_NAMESPACE}}}g",
        {
            "transform": _placement_transform(
                bounds, GRID_SIDE * GRID_SIDE - 1
            )
        },
    )
    group.append(copy.deepcopy(child))
    return ET.tostring(fixture_root, encoding="unicode")


def _passes_required_gates(result: object) -> bool:
    return bool(getattr(result, "status", "") == "supported")


def _analyze_selection_payload(payload: bytes) -> object:
    return lumina_svg_core.analyze_svg_svg(
        payload.decode("utf-8"),
        SELECTION_TARGET_WIDTH_MM,
        SELECTION_TOLERANCE_MM,
        False,
    )


def _build_tiled_payload(
    source_root: ET.Element,
    selected_indices: tuple[int, ...],
) -> bytes:
    if not selected_indices or len(selected_indices) > 64:
        raise ValueError("selected_path_count_out_of_range")
    source_paths = _source_paths(source_root)
    canvas = GRID_SIDE * CELL_USER_UNITS
    fixture_root = ET.Element(
        source_root.tag,
        {
            "version": "1.1",
            "viewBox": f"0 0 {canvas:g} {canvas:g}",
            "width": f"{canvas:g}",
            "height": f"{canvas:g}",
            "data-selection": "longest-64-safe-paths",
        },
    )
    selected = [source_paths[index] for index in selected_indices]
    selected_bounds = [
        _paint_bounds(source_root, child) for child in selected
    ]
    repeats = GRID_SIDE * GRID_SIDE // 64
    for repeat in range(repeats):
        for source_offset, (source_index, child, bounds) in enumerate(
            zip(selected_indices, selected, selected_bounds, strict=True)
        ):
            slot = repeat * 64 + source_offset
            group = ET.SubElement(
                fixture_root,
                f"{{{SVG_NAMESPACE}}}g",
                {
                    "transform": _placement_transform(bounds, slot),
                    "data-source-path-index": str(source_index),
                    "data-repeat": str(repeat),
                },
            )
            group.append(copy.deepcopy(child))
    return ET.tostring(
        fixture_root,
        encoding="utf-8",
        xml_declaration=True,
    )


def select_longest_supported_path_indices(
    source_root: ET.Element,
) -> tuple[int, ...]:
    """Return the longest 64 paths currently supported by the native core.

    按序列化 XML 字节长度重新排序，并逐条执行原生分析，返回前 64 个
    可直接解析的路径索引。
    """

    source_paths = _source_paths(source_root)
    ranked_indices = sorted(
        range(len(source_paths)),
        key=lambda index: (
            -len(ET.tostring(source_paths[index], encoding="utf-8")),
            index,
        ),
    )
    selected: list[int] = []
    for source_index in ranked_indices:
        child = source_paths[source_index]
        try:
            bounds = _paint_bounds(source_root, child)
        except RuntimeError:
            continue
        result = lumina_svg_core.analyze_svg_svg(
            _single_candidate_svg(source_root, child, bounds),
            SELECTION_TARGET_WIDTH_MM,
            SELECTION_TOLERANCE_MM,
            False,
        )
        if not _passes_required_gates(result):
            continue
        tentative = (*selected, source_index)
        if not _passes_required_gates(
            _analyze_selection_payload(
                _build_tiled_payload(source_root, tentative)
            )
        ):
            continue
        selected.append(source_index)
        if len(selected) == len(SELECTED_SOURCE_PATH_INDICES):
            return tuple(selected)
    raise RuntimeError("insufficient_supported_source_paths")


def build_fixture_payload(source_path: Path) -> bytes:
    """Return fixture bytes from the provided source document."""

    source_root = load_source(source_path)
    payload = _build_tiled_payload(
        source_root, SELECTED_SOURCE_PATH_INDICES
    )
    result = _analyze_selection_payload(payload)
    if result.status != "supported":
        raise RuntimeError(
            "supported_scale_fixture_no_longer_supported:"
            + str(result.reason_code)
        )
    return payload


def provenance(payload: bytes) -> dict[str, object]:
    """Return the auditable source/selection record for fixture bytes."""

    return {
        "schema_version": 1,
        "classification": "derived_supported_scale",
        "source": {
            "path": "test_images/benchmark.svg",
            "path_count": 3097,
        },
        "selection": {
            "policy": "longest_64_supported_paths_tiled_16_times",
            "ranking": "serialized_xml_byte_length_descending_then_index",
            "verification_entrypoint": "lumina_svg_core.analyze_svg_svg",
            "target_width_mm": SELECTION_TARGET_WIDTH_MM,
            "tolerance_mm": SELECTION_TOLERANCE_MM,
            "individual_verification_slot": GRID_SIDE * GRID_SIDE - 1,
            "complete_fixture_verified": True,
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
    args = parser.parse_args()

    payload = build_fixture_payload(args.source.resolve())
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)

    record = provenance(payload)
    if args.manifest is not None:
        manifest_path = args.manifest.resolve()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
