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
    "7f1fd4b2405989394c1a4fd6b59b117c4015ee2b9918b4dba5922c3e8ede472e"
)
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
GRID_SIDE = 32
CELL_USER_UNITS = 500.0
CELL_MARGIN_USER_UNITS = 25.0
SELECTION_TARGET_WIDTH_MM = 111.0
SELECTION_TOLERANCE_MM = 0.02
SELECTION_LEGACY_CLOSE_DELTA_SOURCE_UNITS = 0.03
SELECTION_LEGACY_MINIMUM_PAINT_AREA_FACTOR = 0.25
SELECTION_LEGACY_COMPONENT_AREA_SOURCE_UNITS_SQUARED = 0.01
REQUIRED_RESULT_FLAGS = (
    "legacy_area_filter_identity",
    "legacy_contour_normalization_compatible",
    "legacy_contour_normalization_identity",
    "legacy_curve_tolerance_compatible",
)

# These paths were considered in descending serialized-size order and accepted
# only while the growing compound panel passed every v0.1 recorder, precision,
# topology, curve-tolerance, and legacy-parity gate. The tuple fixes the
# fixture bytes; ``--verify`` recomputes the selection from source and then
# validates the complete tiled document.
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


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_verified_source(source_path: Path) -> ET.Element:
    """Load the fixed source document after checking identity and shape count.

    校验固定源文档的身份和路径数量后加载 XML 根节点。
    """

    source_payload = source_path.read_bytes()
    actual_source_sha256 = _sha256(source_payload)
    if actual_source_sha256 != SOURCE_SHA256:
        raise ValueError(
            f"unexpected_source_sha256:{actual_source_sha256}"
        )

    ET.register_namespace("", SVG_NAMESPACE)
    source_root = ET.fromstring(source_payload)
    if len(_source_paths(source_root)) != 3097:
        raise ValueError(
            f"unexpected_source_path_count:{len(_source_paths(source_root))}"
        )
    return source_root


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
    return bool(getattr(result, "status", "") == "supported") and all(
        bool(getattr(result, flag, False))
        for flag in REQUIRED_RESULT_FLAGS
    )


def _analyze_selection_payload(payload: bytes) -> object:
    return lumina_svg_core.analyze_svg_svg(
        payload.decode("utf-8"),
        SELECTION_TARGET_WIDTH_MM,
        SELECTION_TOLERANCE_MM,
        False,
        SELECTION_LEGACY_CLOSE_DELTA_SOURCE_UNITS,
        SELECTION_LEGACY_MINIMUM_PAINT_AREA_FACTOR,
        SELECTION_LEGACY_COMPONENT_AREA_SOURCE_UNITS_SQUARED,
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
            "data-lumina-benchmark-source-sha256": SOURCE_SHA256,
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


def select_longest_safe_path_indices(
    source_root: ET.Element,
) -> tuple[int, ...]:
    """Recompute the longest 64 paths passing every native parity gate.

    按序列化 XML 字节长度重新排序，并逐条执行完整原生分析与旧链路
    兼容性门禁，返回前 64 个安全路径索引。
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
            SELECTION_LEGACY_CLOSE_DELTA_SOURCE_UNITS,
            SELECTION_LEGACY_MINIMUM_PAINT_AREA_FACTOR,
            SELECTION_LEGACY_COMPONENT_AREA_SOURCE_UNITS_SQUARED,
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
    raise RuntimeError("insufficient_fail_closed_safe_source_paths")


def build_fixture_payload(source_path: Path) -> bytes:
    """Return canonical fixture bytes after verifying the real source SHA."""

    source_root = load_verified_source(source_path)
    payload = _build_tiled_payload(
        source_root, SELECTED_SOURCE_PATH_INDICES
    )
    actual_fixture_sha256 = _sha256(payload)
    if actual_fixture_sha256 != EXPECTED_FIXTURE_SHA256:
        raise RuntimeError(
            f"unexpected_fixture_sha256:{actual_fixture_sha256}"
        )
    result = _analyze_selection_payload(payload)
    if result.status != "supported":
        raise RuntimeError(
            "supported_scale_fixture_no_longer_supported:"
            + str(result.reason_code)
        )
    missing_flags = [
        flag for flag in REQUIRED_RESULT_FLAGS
        if not bool(getattr(result, flag, False))
    ]
    if missing_flags:
        raise RuntimeError(
            "supported_scale_fixture_failed_parity_flags:"
            + ",".join(missing_flags)
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
            "ranking": "serialized_xml_byte_length_descending_then_index",
            "verification_entrypoint": "lumina_svg_core.analyze_svg_svg",
            "target_width_mm": SELECTION_TARGET_WIDTH_MM,
            "tolerance_mm": SELECTION_TOLERANCE_MM,
            "legacy_component_area_source_units_squared": (
                SELECTION_LEGACY_COMPONENT_AREA_SOURCE_UNITS_SQUARED
            ),
            "individual_verification_slot": GRID_SIDE * GRID_SIDE - 1,
            "complete_fixture_verified": True,
            "required_result_flags": list(REQUIRED_RESULT_FLAGS),
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
        source_root = load_verified_source(args.source.resolve())
        recomputed_indices = select_longest_safe_path_indices(source_root)
        if recomputed_indices != SELECTED_SOURCE_PATH_INDICES:
            raise SystemExit("supported_scale_selection_is_stale")
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
