"""Contracts for the sole Lumina-to-lumina-svg-core boundary."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest
import shapely

from core.errors import CoreProcessingError, CoreValidationError
from core.native_svg_adapter import (
    NativeSvgFallback,
    NativeSvgGeometry,
    analyze_native_svg,
)


@dataclass
class _FakeCollection:
    coordinates: np.ndarray
    ring_offsets: np.ndarray
    polygon_offsets: np.ndarray
    geometry_offsets: np.ndarray
    rgba: np.ndarray
    draw_indices: np.ndarray
    source_indices: np.ndarray
    source_kinds: np.ndarray

    @property
    def geometry_count(self) -> int:
        return len(self.geometry_offsets) - 1


def _collection(*, source_kind: int = 0) -> _FakeCollection:
    return _FakeCollection(
        coordinates=np.asarray(
            [[0, 0], [100, 0], [100, 50], [0, 50], [0, 0]],
            dtype=np.int64,
        ),
        ring_offsets=np.asarray([0, 5], dtype=np.uint64),
        polygon_offsets=np.asarray([0, 1], dtype=np.uint64),
        geometry_offsets=np.asarray([0, 1], dtype=np.uint64),
        rgba=np.asarray([[255, 0, 0, 255]], dtype=np.uint8),
        draw_indices=np.asarray([7], dtype=np.int32),
        source_indices=np.asarray([3], dtype=np.int32),
        source_kinds=np.asarray([source_kind], dtype=np.int32),
    )


def _native_result(
    *,
    status: str = "supported",
    reason_code: str = "",
    source_kind: int = 0,
    image_vectorizer_origin: bool = False,
) -> SimpleNamespace:
    collection = _collection(source_kind=source_kind)
    return SimpleNamespace(
        status=status,
        reason_code=reason_code,
        schema_version=1,
        bbox=(10.0, 20.0, 100.0, 50.0),
        viewport_bounds=(5.0, 6.0, 80.0, 40.0),
        image_vectorizer_origin=image_vectorizer_origin,
        scale_factor=0.2,
        grid_to_source_unit=1.0,
        recorder_seconds=0.01,
        kernel_seconds=0.02,
        result_conversion_seconds=0.003,
        raw=collection,
        visible=collection,
        silhouette=collection,
    )


def _native_module(
    result: SimpleNamespace,
    calls: list[tuple[object, ...]] | None = None,
) -> SimpleNamespace:
    def analyze_svg(*args: object) -> SimpleNamespace:
        if calls is not None:
            calls.append(args)
        return result

    return SimpleNamespace(
        __version__="0.1.0",
        analyze_svg=analyze_svg,
    )


def test_supported_result_preserves_lumina_coordinate_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(_native_result()),
    )

    outcome = analyze_native_svg(
        "fixture.svg",
        target_width_mm=20.0,
        tolerance_mm=0.02,
        expand_stroke_to_fill=False,
    )

    assert isinstance(outcome, NativeSvgGeometry)
    assert outcome.bbox == (10.0, 20.0, 100.0, 50.0)
    assert outcome.scale_factor == pytest.approx(0.2)
    assert outcome.shape_data[0]["poly"].bounds == pytest.approx(
        (0.0, 0.0, 100.0, 50.0)
    )
    assert outcome.clipped_shapes[0]["geometry"].bounds == pytest.approx(
        (0.0, 0.0, 100.0, 50.0)
    )
    assert outcome.clipped_shapes[0]["color"] == (255, 0, 0)
    assert outcome.geometry_backend == "native"


def test_image_vectorizer_origin_preserves_normalized_viewport_anchor(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svg_path = tmp_path / "vectorized.svg"
    svg_path.write_text(
        "<svg data-lumina-origin='image-vectorizer' viewBox='0 0 100 50'>"
        "<rect x='10' y='10' width='20' height='20'/></svg>",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(
            _native_result(image_vectorizer_origin=True)
        ),
    )

    outcome = analyze_native_svg(str(svg_path), 20.0, 0.02)

    assert isinstance(outcome, NativeSvgGeometry)
    assert outcome.image_vectorizer_bounds is not None
    assert outcome.image_vectorizer_bounds.bounds == pytest.approx(
        (5.0, 6.0, 85.0, 46.0)
    )


def test_adapter_calls_one_vectorized_constructor_per_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    constructor = shapely.from_ragged_array

    def recording_constructor(*args, **kwargs):
        calls.append(args)
        return constructor(*args, **kwargs)

    monkeypatch.setattr(shapely, "from_ragged_array", recording_constructor)
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(_native_result()),
    )

    outcome = analyze_native_svg(
        "fixture.svg", 20.0, 0.02, expand_stroke_to_fill=False
    )

    assert isinstance(outcome, NativeSvgGeometry)
    assert len(calls) == 3


@pytest.mark.parametrize(
    "reason_code",
    [
        "unsupported_marker",
        "unsupported_vector_effect",
        "unsupported_external_resource",
    ],
)
def test_unsupported_native_result_requests_whole_document_fallback(
    monkeypatch: pytest.MonkeyPatch,
    reason_code: str,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(
            _native_result(status="unsupported", reason_code=reason_code)
        ),
    )

    outcome = analyze_native_svg("fixture.svg", 20.0, 0.02)

    assert outcome == NativeSvgFallback(
        reason_code=reason_code,
        native_version="0.1.0",
    )


def test_disabled_stroke_expansion_falls_back_before_semantics_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(_native_result(source_kind=1)),
    )

    outcome = analyze_native_svg(
        "fixture.svg", 20.0, 0.02, expand_stroke_to_fill=False
    )

    assert outcome == NativeSvgFallback(
        reason_code="legacy_stroke_policy",
        native_version="0.1.0",
    )


def test_adapter_disables_native_stroke_kernel_before_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(
            _native_result(
                status="unsupported",
                reason_code="unsupported_stroke_policy",
            ),
            calls,
        ),
    )

    outcome = analyze_native_svg(
        "fixture.svg", 20.0, 0.02, expand_stroke_to_fill=False
    )

    assert calls == [("fixture.svg", 20.0, 0.02, False)]
    assert outcome == NativeSvgFallback(
        reason_code="legacy_stroke_policy",
        native_version="0.1.0",
    )


def test_enabled_strokes_remain_legacy_until_differential_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(_native_result(source_kind=1)),
    )

    outcome = analyze_native_svg(
        "fixture.svg", 20.0, 0.02, expand_stroke_to_fill=True
    )

    assert outcome == NativeSvgFallback(
        reason_code="legacy_stroke_parity",
        native_version="0.1.0",
    )


@pytest.mark.parametrize("element", ["style", "use", "svg:use"])
def test_style_and_use_documents_preserve_legacy_reference_semantics(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    element: str,
) -> None:
    svg_path = tmp_path / "reference-policy.svg"
    svg_path.write_text(f"<svg><{element}/></svg>", encoding="utf-8")
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(_native_result()),
    )

    outcome = analyze_native_svg(str(svg_path), 20.0, 0.02)

    assert outcome == NativeSvgFallback(
        reason_code="legacy_css_use_parity",
        native_version="0.1.0",
    )


@pytest.mark.parametrize("reason_code", ["invalid_svg", "empty_geometry"])
def test_invalid_svg_maps_to_existing_value_error_behavior(
    monkeypatch: pytest.MonkeyPatch,
    reason_code: str,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(
            _native_result(status="invalid", reason_code=reason_code)
        ),
    )

    with pytest.raises(ValueError, match="valid filled shapes|Invalid SVG"):
        analyze_native_svg("fixture.svg", 20.0, 0.02)


def test_numeric_range_error_is_a_core_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(
            _native_result(status="invalid", reason_code="numeric_range_error")
        ),
    )

    with pytest.raises(CoreValidationError, match="numeric range"):
        analyze_native_svg("fixture.svg", 20.0, 0.02)


def test_native_internal_error_is_not_silently_reparsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.native_svg_adapter._load_native_module",
        lambda: _native_module(
            _native_result(status="invalid", reason_code="native_geometry_error")
        ),
    )

    with pytest.raises(CoreProcessingError, match="native SVG"):
        analyze_native_svg("fixture.svg", 20.0, 0.02)
