"""Tests for the native vector clip profiling helper script."""

from __future__ import annotations

from shapely.geometry import Polygon

from scripts.profile_vector_native_clip import (
    _clip_occlusion_native_poc,
    _compare_clip_outputs,
    _geometry_signature,
    _parse_args,
    _profile_sample,
    _render_markdown,
)


def test_geometry_signature_rounds_area_and_bounds() -> None:
    items = [
        {
            "geometry": Polygon(
                [
                    (0.00000001, 0.0),
                    (1.23456789, 0.0),
                    (1.23456789, 2.0),
                    (0.00000001, 2.0),
                ]
            ),
            "color": (255, 0, 0),
        }
    ]

    assert _geometry_signature(items, geometry_key="geometry") == [
        {
            "color": (255, 0, 0),
            "geom_type": "Polygon",
            "area": 2.469136,
            "bounds": (0.0, 0.0, 1.234568, 2.0),
        }
    ]


def test_compare_clip_outputs_reports_first_mismatch_and_area_delta() -> None:
    reference = [
        {
            "geometry": Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]),
            "color": (255, 0, 0),
        }
    ]
    candidate = [
        {
            "geometry": Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 2.0), (0.0, 2.0)]),
            "color": (255, 0, 0),
        }
    ]

    result = _compare_clip_outputs(reference, candidate)

    assert result["summary_match"] is False
    assert result["reference_count"] == 1
    assert result["candidate_count"] == 1
    assert result["total_area_delta"] == 2.0
    assert result["first_mismatch_index"] == 0


def test_render_markdown_includes_decision_fields() -> None:
    report = {
        "summary": {
            "sample_count": 1,
            "ok_count": 1,
            "quality_pass_count": 0,
            "native_faster_count": 1,
            "reference_total_seconds": 2.0,
            "native_total_seconds": 1.0,
            "speedup": 2.0,
        },
        "samples": [
            {
                "svg_name": "sample.svg",
                "status": "ok",
                "reference_seconds": 2.0,
                "native_seconds": 1.0,
                "speedup": 2.0,
                "quality": {
                    "summary_match": False,
                    "reference_count": 10,
                    "candidate_count": 9,
                    "total_area_delta": 0.01,
                },
            }
        ],
    }

    markdown = _render_markdown(report)

    assert "Native Vector Clip POC" in markdown
    assert "Quality pass: 0 / 1" in markdown
    assert "`sample.svg`" in markdown
    assert "summary_match=False" in markdown


def test_parse_args_accepts_native_coordinate_scale() -> None:
    args = _parse_args(["sample.svg", "--scale", "10000000"])

    assert args.scale == 10_000_000


def test_native_clip_profile_passes_scale_to_native_difference(monkeypatch) -> None:
    seen = {}

    def fake_difference_with_native(subject, clips, *, native_module, scale):
        seen["subject_area"] = subject.area
        seen["clip_count"] = len(clips)
        seen["native_module"] = native_module
        seen["scale"] = scale
        return Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 2.0), (0.0, 2.0)])

    monkeypatch.setattr(
        "scripts.profile_vector_native_clip.difference_with_native",
        fake_difference_with_native,
    )
    native_module = object()
    shape_data = [
        {
            "poly": Polygon([(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]),
            "color": (255, 0, 0),
        },
        {
            "poly": Polygon([(2.0, 0.0), (4.0, 0.0), (4.0, 4.0), (2.0, 4.0)]),
            "color": (0, 0, 255),
        },
    ]

    _clip_occlusion_native_poc(shape_data, native_module=native_module, scale=10_000_000)

    assert seen == {
        "subject_area": 16.0,
        "clip_count": 1,
        "native_module": native_module,
        "scale": 10_000_000,
    }


def test_profile_sample_uses_default_analyze_stroke_policy(monkeypatch, tmp_path) -> None:
    seen = {}

    def fake_parse_svg(self, _svg_path, target_width_mm):
        assert target_width_mm == 80.0
        seen["parse_expand_stroke_to_fill"] = getattr(self, "_parse_expand_stroke_to_fill", None)
        return (
            [
                {
                    "poly": Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]),
                    "color": (255, 0, 0),
                }
            ],
            1.0,
            (0.0, 0.0, 2.0, 2.0),
        )

    monkeypatch.setattr(
        "scripts.profile_vector_native_clip.VectorProcessor._parse_svg",
        fake_parse_svg,
    )
    monkeypatch.setattr(
        "scripts.profile_vector_native_clip.VectorProcessor._clip_occlusion",
        lambda _self, _shape_data, return_silhouette=False: [],
    )
    monkeypatch.setattr(
        "scripts.profile_vector_native_clip._clip_occlusion_native_poc",
        lambda _shape_data, *, native_module, scale: ([], {"native_calls": 0, "native_errors": 0}),
    )

    svg_path = tmp_path / "sample.svg"
    svg_path.write_text("<svg />", encoding="utf-8")

    _profile_sample(
        svg_path,
        native_module=object(),
        target_width_mm=80.0,
        scale=1_000_000,
    )

    assert seen["parse_expand_stroke_to_fill"] is False
