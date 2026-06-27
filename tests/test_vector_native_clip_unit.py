"""Unit tests for optional native SVG occlusion clipping helpers."""

from __future__ import annotations

from shapely.geometry import Polygon

from core.vector_native_clip import difference_with_native


def test_difference_with_native_packs_subject_and_clip_paths() -> None:
    subject = Polygon([(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)])
    clip = Polygon([(2.0, 0.0), (4.0, 0.0), (4.0, 4.0), (2.0, 4.0)])
    seen = {}

    class FakeNativeModule:
        @staticmethod
        def difference_paths(subject_paths, clip_paths, *, scale):
            seen["subject_paths"] = subject_paths
            seen["clip_paths"] = clip_paths
            seen["scale"] = scale
            return [[[(0.0, 0.0), (2.0, 0.0), (2.0, 4.0), (0.0, 4.0)]]]

    result = difference_with_native(subject, [clip], native_module=FakeNativeModule())

    assert seen["scale"] == 1_000_000
    assert seen["subject_paths"] == [[(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]]
    assert seen["clip_paths"] == [[(2.0, 0.0), (4.0, 0.0), (4.0, 4.0), (2.0, 4.0)]]
    assert result is not None
    assert result.area == 8.0
    assert result.bounds == (0.0, 0.0, 2.0, 4.0)


def test_difference_with_native_restores_holes_from_native_output() -> None:
    subject = Polygon([(0.0, 0.0), (6.0, 0.0), (6.0, 6.0), (0.0, 6.0)])
    clip = Polygon([(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)])

    class FakeNativeModule:
        @staticmethod
        def difference_paths(_subject_paths, _clip_paths, *, scale):
            assert scale == 1_000_000
            return [
                [
                    [(0.0, 0.0), (6.0, 0.0), (6.0, 6.0), (0.0, 6.0)],
                    [(2.0, 2.0), (2.0, 4.0), (4.0, 4.0), (4.0, 2.0)],
                ]
            ]

    result = difference_with_native(subject, [clip], native_module=FakeNativeModule())

    assert result is not None
    assert result.area == 32.0
    assert len(result.interiors) == 1


def test_difference_with_native_returns_none_for_empty_native_result() -> None:
    subject = Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])
    clip = subject

    class FakeNativeModule:
        @staticmethod
        def difference_paths(_subject_paths, _clip_paths, *, scale):
            assert scale == 1_000_000
            return []

    assert difference_with_native(subject, [clip], native_module=FakeNativeModule()) is None
