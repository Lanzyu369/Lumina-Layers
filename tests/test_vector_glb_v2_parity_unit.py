"""Parity tests for SVG/vector GLB V1/V2 preview descriptors."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import trimesh
from shapely.geometry import box

from core.pipeline import vector_glb_preview


def _analysis_for_modes() -> SimpleNamespace:
    return SimpleNamespace(
        matched_shapes=[
            {"geometry": box(0, 0, 10, 10), "recipe": [1, 1, 0, 0]},
            {"geometry": box(10, 0, 20, 10), "recipe": [2, 2, 2, 0]},
        ],
        silhouette=box(0, 0, 20, 10),
        scale_factor=1.0,
        bbox=(0, 0, 20, 10),
        slot_names=["White", "Red", "Blue"],
        num_channels=3,
        num_layers=4,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
            2: [0, 0, 255, 255],
            "White": [255, 255, 255, 255],
            "Red": [255, 0, 0, 255],
            "Blue": [0, 0, 255, 255],
            "Board": [240, 240, 240, 255],
            "Outline": [20, 20, 20, 255],
        },
    )


@pytest.mark.parametrize(
    ("structure_mode", "color_mode"),
    [
        ("Single-sided", "4-Color (RYBW)"),
        ("Double-sided", "4-Color (RYBW)"),
        ("Single-sided", "5-Color Extended"),
    ],
)
def test_v2_descriptor_bounds_are_finite_for_core_modes(
    structure_mode: str,
    color_mode: str,
) -> None:
    analysis = _analysis_for_modes()

    parts = vector_glb_preview.build_vector_preview_parts_from_analysis(
        analysis=analysis,
        preview_colors=dict(analysis.preview_colors),
        slot_list=list(analysis.slot_names),
        structure_mode=structure_mode,
        color_mode=color_mode,
        thickness_mm=1.6,
        separate_backing=True,
        include_backing=True,
        include_outline=True,
        outline_width_mm=2.0,
    )

    assert parts
    names = {part.export_name for part in parts}
    assert "backing_plate" in names
    assert "Outline" in names
    for part in parts:
        assert part.export_name
        if part.role != "color":
            assert not part.export_name.startswith("color_")
        for extrusion in part.extrusions:
            assert extrusion.z_max > extrusion.z_min
            assert not extrusion.footprint.is_empty
            assert all(value == value for value in extrusion.footprint.bounds)


def test_v2_backing_uses_visible_silhouette_not_preview_canvas_bounds() -> None:
    """V2 backing must stay physical while canvas metadata remains separate."""

    visible_shape = box(4, 4, 16, 16)
    full_backing = box(0, 0, 20, 20)
    analysis = SimpleNamespace(
        matched_shapes=[
            {"geometry": visible_shape, "recipe": [1, 1, 1, 1]},
        ],
        silhouette=visible_shape,
        image_vectorizer_bounds=full_backing,
        scale_factor=1.0,
        bbox=(0, 0, 20, 20),
        slot_names=["White", "Red"],
        num_channels=2,
        num_layers=4,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
            "White": [255, 255, 255, 255],
            "Red": [255, 0, 0, 255],
            "Board": [240, 240, 240, 255],
        },
    )

    parts = vector_glb_preview.build_vector_preview_parts_from_analysis(
        analysis=analysis,
        preview_colors=dict(analysis.preview_colors),
        slot_list=list(analysis.slot_names),
        structure_mode="Single-sided",
        color_mode="4-Color (RYBW)",
        thickness_mm=1.6,
        separate_backing=True,
        include_backing=True,
        include_outline=False,
        outline_width_mm=2.0,
    )

    backing = next(part for part in parts if part.role == "backing")

    assert backing.extrusions[0].footprint.bounds == pytest.approx(
        (3.85, 3.85, 16.15, 16.15)
    )


def test_v2_backing_expansion_matches_v1_scale_factor_order() -> None:
    """V2 backing preparation should match V1's pre-scale buffer ordering."""

    analysis = SimpleNamespace(
        matched_shapes=[
            {"geometry": box(2, 2, 8, 8), "recipe": [1, 1, 1, 1]},
        ],
        silhouette=box(2, 2, 8, 8),
        image_vectorizer_bounds=box(0, 0, 10, 10),
        scale_factor=2.0,
        bbox=(0, 0, 10, 10),
        slot_names=["White", "Red"],
        num_channels=2,
        num_layers=4,
        preview_colors={
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
            "White": [255, 255, 255, 255],
            "Red": [255, 0, 0, 255],
            "Board": [240, 240, 240, 255],
        },
    )

    parts = vector_glb_preview.build_vector_preview_parts_from_analysis(
        analysis=analysis,
        preview_colors=dict(analysis.preview_colors),
        slot_list=list(analysis.slot_names),
        structure_mode="Single-sided",
        color_mode="4-Color (RYBW)",
        thickness_mm=1.6,
        separate_backing=True,
        include_backing=True,
        include_outline=False,
        outline_width_mm=2.0,
    )

    backing = next(part for part in parts if part.role == "backing")

    assert backing.extrusions[0].footprint.bounds == pytest.approx(
        (3.7, 3.7, 16.3, 16.3)
    )


def test_duplicate_color_slots_keep_distinct_export_names() -> None:
    seen: set[str] = set()

    first = vector_glb_preview.make_vector_glb_export_name(
        source_name="Red A",
        role="color",
        rgba=(255, 0, 0, 255),
        seen_names=seen,
    )
    second = vector_glb_preview.make_vector_glb_export_name(
        source_name="Red B",
        role="color",
        rgba=(255, 0, 0, 255),
        seen_names=seen,
    )

    assert [first, second] == ["color_ff0000", "color_ff0000_1"]


def test_v2_exporter_rejects_part_without_footprint(tmp_path) -> None:
    part = vector_glb_preview.VectorPreviewPart(
        source_name="FridgeCavityBoard",
        export_name="backing_plate",
        role="backing",
        rgba=(255, 255, 255, 255),
        is_recolorable=False,
        extrusions=(),
        fallback_mesh=trimesh.creation.box(extents=(1, 1, 1)),
    )

    with pytest.raises(RuntimeError, match="requires footprints"):
        vector_glb_preview.export_vector_glb_preview_v2(
            [part],
            output_path=str(tmp_path / "bad.glb"),
        )
