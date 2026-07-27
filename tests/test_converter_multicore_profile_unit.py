from pathlib import Path

import pytest

from config import ModelingMode
from scripts.profile_converter_multicore import (
    MATERIAL_PALETTES,
    ProfileCase,
    build_pipeline_context,
)


@pytest.mark.parametrize("size", [8, 12, 15])
def test_material_palette_has_requested_unique_archives(size: int) -> None:
    palette = MATERIAL_PALETTES[size]
    assert len(palette) == size
    assert len(set(palette)) == size
    for directory_name in palette:
        archive = Path("materials") / directory_name / "material.json"
        stage_a = Path("materials") / directory_name / "stage_A_parameters.json"
        assert archive.is_file()
        assert stage_a.is_file()


@pytest.mark.parametrize(
    ("kind", "mode"),
    [("raster", ModelingMode.HIGH_FIDELITY), ("vector", ModelingMode.VECTOR)],
)
def test_build_pipeline_context_uses_quality_locked_profile_settings(
    tmp_path: Path,
    kind: str,
    mode: ModelingMode,
) -> None:
    source = tmp_path / ("input.svg" if kind == "vector" else "input.png")
    source.write_bytes(b"<svg/>" if kind == "vector" else b"not-decoded-in-this-test")
    case = ProfileCase(
        name=f"{kind}-12",
        kind=kind,
        input_path=source,
        target_width_mm=299.0,
        material_count=12,
    )

    ctx = build_pipeline_context(case)

    assert ctx["modeling_mode"] is mode
    assert ctx["material_source"] == "material_archive"
    assert ctx["selected_materials"] == MATERIAL_PALETTES[12]
    assert ctx["material_layer_count"] == 10
    assert ctx["material_layer_height_mm"] == 0.08
    assert ctx["quantize_colors"] == 64
    assert ctx["target_width_mm"] == 299.0
    assert ctx["structure_mode"] == "single-sided"
