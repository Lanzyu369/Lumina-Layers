"""Manifest-driven topology, material, area, and determinism corpus."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import lumina_svg_core


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
MANIFEST = json.loads(
    (Path(__file__).resolve().parent / "golden_manifest.json").read_text(
        encoding="utf-8"
    )
)
SPEC = importlib.util.spec_from_file_location(
    "native_svg_fingerprint", PACKAGE_ROOT / "tools" / "fingerprint.py"
)
assert SPEC is not None and SPEC.loader is not None
FINGERPRINT_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FINGERPRINT_MODULE)


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=lambda case: case["file"])
def test_golden_case(case: dict[str, object]) -> None:
    path = FIXTURES / str(case["file"])
    result = lumina_svg_core.analyze_svg(
        path,
        MANIFEST["target_width_mm"],
        MANIFEST["tolerance_mm"],
    )
    actual = FINGERPRINT_MODULE.result_summary(result)
    for key in (
        "status",
        "reason_code",
        "bbox",
        "ordered_rgba",
        "raw_components",
        "visible_components",
        "visible_holes",
        "area_by_rgba",
        "fingerprint",
    ):
        assert actual[key] == case[key]


def test_golden_fingerprint_is_stable_across_repeated_runs() -> None:
    path = FIXTURES / "strokes_clips_occlusion.svg"
    fingerprints = {
        FINGERPRINT_MODULE.result_fingerprint(
            lumina_svg_core.analyze_svg(
                path,
                MANIFEST["target_width_mm"],
                MANIFEST["tolerance_mm"],
            )
        )
        for _ in range(3)
    }
    assert len(fingerprints) == 1
