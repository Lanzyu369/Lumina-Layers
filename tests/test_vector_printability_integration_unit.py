"""Focused integration tests for SVG printability optimizer wiring."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from core.pipeline.coordinator import _log_vector_timings
from core.vector_engine import VectorProcessor


def _write_merged_lut(tmp_path):
    entries = [
        {
            "rgb": [220, 20, 60],
            "hex": "#DC143C",
            "recipe": ["Red"],
        },
        {
            "rgb": [0, 0, 0],
            "hex": "#000000",
            "recipe": ["Black"],
        },
    ]
    path = tmp_path / "test_merged.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return str(path)


def _write_simple_svg(tmp_path):
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '  <rect x="5" y="5" width="30" height="30" fill="#dc143c"/>'
        '  <rect x="60" y="60" width="20" height="20" fill="#000000"/>'
        "</svg>"
    )
    path = tmp_path / "test.svg"
    path.write_text(svg, encoding="utf-8")
    return str(path)


def _write_thin_svg(tmp_path):
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 10">'
        '  <rect x="0" y="0" width="10" height="0.2" fill="#dc143c"/>'
        "</svg>"
    )
    path = tmp_path / "thin.svg"
    path.write_text(svg, encoding="utf-8")
    return str(path)


class _FakePrintableFeatureOptimizer:
    captured_records = None

    def __init__(self, shape_records, scale_factor, printable_core_nozzle_multiplier=None, nozzle_width_mm=None):
        self.shape_records = [dict(record) for record in shape_records]
        self.scale_factor = scale_factor
        self.printable_core_nozzle_multiplier = printable_core_nozzle_multiplier
        self.nozzle_width_mm = nozzle_width_mm
        _FakePrintableFeatureOptimizer.captured_records = self.shape_records

    def optimize(self):
        assert all("draw_order" in record for record in self.shape_records)
        assert [record["draw_order"] for record in self.shape_records] == sorted(
            record["draw_order"] for record in self.shape_records
        )
        return SimpleNamespace(
            records=[{**record, "optimizer_mark": idx} for idx, record in enumerate(self.shape_records)],
            items=[],
            classification_counts={"normal": 2, "isolated": 0, "thin": 0, "skip": 0},
            action_counts={"keep": 2, "widen": 0, "merge": 0, "skip": 0},
            timings_ms={"classify": 1.5, "action": 2.5, "total": 4.0},
        )


class TestVectorPrintabilityIntegration:
    def test_analyze_svg_uses_optimizer_output_and_records_printability_timing(self, tmp_path, monkeypatch, caplog):
        lut_path = _write_merged_lut(tmp_path)
        svg_path = _write_simple_svg(tmp_path)
        processor = VectorProcessor(lut_path, "Merged")

        monkeypatch.setattr("core.vector_engine.PrintableFeatureOptimizer", _FakePrintableFeatureOptimizer, raising=False)
        caplog.set_level(logging.INFO, logger="core.vector_engine")

        analysis = processor.analyze_svg(svg_path, target_width_mm=50.0)

        assert _FakePrintableFeatureOptimizer.captured_records is not None
        expected_records = [
            {**record, "optimizer_mark": idx}
            for idx, record in enumerate(_FakePrintableFeatureOptimizer.captured_records)
        ]
        assert analysis.matched_shapes == expected_records
        assert analysis.stage_timings["printability_filter_s"] > 0.0
        assert [record["draw_order"] for record in _FakePrintableFeatureOptimizer.captured_records] == [0, 1]
        assert any("Printability filter" in record.message for record in caplog.records)
        assert any("classification_counts" in record.message for record in caplog.records)
        assert any("action_counts" in record.message for record in caplog.records)

    def test_coordinator_vector_timing_log_includes_printability_filter(self, caplog):
        caplog.set_level(logging.INFO, logger="core.pipeline.coordinator")

        _log_vector_timings(
            {
                "parse_s": 0.1,
                "occlusion_s": 0.2,
                "color_match_s": 0.3,
                "printability_filter_s": 0.4,
                "extrude_bottom_s": 0.5,
                "backing_s": 0.6,
                "extrude_top_s": 0.7,
                "assemble_s": 0.8,
                "mesh_total_s": 0.9,
                "export_3mf_s": 1.0,
                "export_glb_s": 1.1,
                "preview_2d_s": 1.2,
                "vector_branch_total_s": 1.3,
            }
        )

        assert any("printability_filter=0.400" in record.message for record in caplog.records)

    def test_analyze_svg_recomputes_silhouette_and_bbox_after_printability_widening(self, tmp_path):
        lut_path = _write_merged_lut(tmp_path)
        svg_path = _write_thin_svg(tmp_path)
        processor = VectorProcessor(lut_path, "Merged")

        analysis = processor.analyze_svg(svg_path, target_width_mm=50.0)

        assert analysis.matched_shapes
        widened = analysis.matched_shapes[0]["geometry"]
        widened_height = widened.bounds[3] - widened.bounds[1]

        assert widened_height > 0.2
        assert analysis.silhouette is not None
        assert analysis.silhouette.bounds[3] - analysis.silhouette.bounds[1] == pytest.approx(widened_height)
        assert analysis.bbox[3] == pytest.approx(analysis.silhouette.bounds[3] - analysis.silhouette.bounds[1])
