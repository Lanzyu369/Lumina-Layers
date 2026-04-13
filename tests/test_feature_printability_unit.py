"""Unit tests for the reusable printable feature optimizer foundation."""

import sys
import os

import pytest
from shapely.geometry import box
from shapely.ops import unary_union

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from config import VectorConfig
from core.feature_printability import PrintableFeatureOptimizer


def _shape(geometry, recipe, draw_order=0, color=(255, 0, 0)):
    return {
        "geometry": geometry,
        "recipe": recipe,
        "color": color,
        "draw_order": draw_order,
    }


class TestVectorConfig:
    def test_printable_core_nozzle_multiplier_is_configurable(self):
        assert VectorConfig.PRINTABLE_CORE_NOZZLE_MULTIPLIER == pytest.approx(2.0)


class TestPrintableFeatureOptimizer:
    def test_classifies_normal_isolated_and_thin_shapes(self):
        optimizer = PrintableFeatureOptimizer(
            [
                _shape(box(0, 0, 10, 10), [0, 0, 0], draw_order=0),
                _shape(box(20, 0, 20.3, 0.3), [1, 1, 1], draw_order=1),
                _shape(box(30, 0, 40, 0.2), [2, 2, 2], draw_order=2),
            ],
            scale_factor=1.0,
        )

        result = optimizer.optimize()

        classifications = [item.classification for item in result.items]
        assert classifications == ["normal", "isolated", "thin"]
        assert result.classification_counts["normal"] == 1
        assert result.classification_counts["isolated"] == 1
        assert result.classification_counts["thin"] == 1

    def test_multiplier_override_changes_classification_threshold(self):
        shape = box(0, 0, 5.0, 0.2)

        default_optimizer = PrintableFeatureOptimizer([_shape(shape, [0, 0, 0])], scale_factor=1.0)
        overridden_optimizer = PrintableFeatureOptimizer(
            [_shape(shape, [0, 0, 0])],
            scale_factor=1.0,
            printable_core_nozzle_multiplier=0.2,
        )

        assert default_optimizer.classify(shape) == "thin"
        assert overridden_optimizer.classify(shape) == "normal"

    def test_cross_recipe_merge_exposes_provenance_and_final_metadata(self):
        optimizer = PrintableFeatureOptimizer(
            [
                _shape(box(0, 0, 1.0, 1.0), [0, 0, 0], draw_order=0, color=(255, 0, 0)),
                _shape(box(1.0, 0.2, 1.3, 0.5), [1, 1, 1], draw_order=1, color=(0, 255, 0)),
                _shape(box(2.0, 0, 3.0, 1.0), [2, 2, 2], draw_order=2, color=(0, 0, 255)),
            ],
            scale_factor=1.0,
        )

        result = optimizer.optimize()
        merged = [item for item in result.items if item.action == "merge"]
        survivor = result.records[0]

        assert len(merged) == 1
        assert merged[0].merged_into_index == 0
        assert merged[0].merge_source_recipe == [1, 1, 1]
        assert merged[0].merge_target_recipe == [0, 0, 0]
        assert merged[0].merge_recipe_changed is True
        assert survivor["recipe"] == [0, 0, 0]
        assert survivor["color"] == (255, 0, 0)

    def test_isolated_shape_can_merge_into_later_best_neighbor(self):
        optimizer = PrintableFeatureOptimizer(
            [
                _shape(box(0.0, 0, 0.3, 0.3), [0, 0, 0], draw_order=0),
                _shape(box(5.0, 0, 6.0, 1.0), [1, 1, 1], draw_order=1),
            ],
            scale_factor=1.0,
        )

        result = optimizer.optimize()

        merged = [item for item in result.items if item.action == "merge"]
        assert len(merged) == 1
        assert merged[0].merge_target_index == 1
        assert result.records[0]["recipe"] == [1, 1, 1]
        assert result.records[0]["geometry"].area > 0.0

    def test_source_and_output_areas_are_reported_in_mm2(self):
        optimizer = PrintableFeatureOptimizer(
            [_shape(box(0, 0, 2, 3), [0, 0, 0], draw_order=0)],
            scale_factor=2.0,
        )

        result = optimizer.optimize()
        item = result.items[0]

        assert item.source_area_mm2 == pytest.approx(24.0)
        assert item.output_area_mm2 == pytest.approx(24.0)

    def test_skipped_invalid_inputs_remain_observable(self):
        optimizer = PrintableFeatureOptimizer(
            [
                _shape(box(0, 0, 0, 0), [0, 0, 0], draw_order=0),
                _shape(box(0, 0, 5, 5), [1, 1, 1], draw_order=1),
            ],
            scale_factor=1.0,
        )

        result = optimizer.optimize()

        assert len(result.items) == 2
        assert result.action_counts["skip"] == 1
        skipped = result.items[0]
        assert skipped.action == "skip"
        assert skipped.skip_reason == "empty-geometry"
        assert skipped.output_area_mm2 == 0.0
        assert len(result.records) == 1

    def test_thin_shape_widens_to_normal_when_stable(self):
        optimizer = PrintableFeatureOptimizer(
            [
                _shape(box(0, 0, 10, 0.2), [0, 0, 0], draw_order=0),
                _shape(box(0, 2, 10, 12), [1, 1, 1], draw_order=1),
            ],
            scale_factor=1.0,
        )

        result = optimizer.optimize()

        thin_items = [item for item in result.items if item.classification == "thin"]
        assert thin_items
        assert thin_items[0].action == "widen"
        assert thin_items[0].widened_to_normal is True
        assert result.action_counts["widen"] == 1

    def test_thin_shape_falls_back_to_merge_when_widening_is_unstable(self, monkeypatch):
        optimizer = PrintableFeatureOptimizer(
            [
                _shape(box(0, 0, 1.0, 1.0), [1, 1, 1], draw_order=0),
                _shape(box(1.0, 0, 6.0, 0.2), [0, 0, 0], draw_order=1),
            ],
            scale_factor=1.0,
        )

        monkeypatch.setattr(optimizer, "_widen_to_printable_core", lambda geometry: None)
        result = optimizer.optimize()
        thin_items = [item for item in result.items if item.classification == "thin"]

        assert thin_items[0].action == "merge"
        assert thin_items[0].merge_target_index == 0
        assert result.action_counts["merge"] == 1

    def test_thin_shape_merges_when_widening_would_overlap_later_shape(self):
        optimizer = PrintableFeatureOptimizer(
            [
                _shape(box(0, 0, 10.0, 0.2), [0, 0, 0], draw_order=0),
                _shape(box(0, 0.3, 10.0, 10.3), [1, 1, 1], draw_order=1),
                _shape(box(0, -10.2, 10.0, -0.2), [2, 2, 2], draw_order=2),
            ],
            scale_factor=1.0,
        )

        result = optimizer.optimize()
        thin_items = [item for item in result.items if item.classification == "thin"]

        assert thin_items[0].action == "merge"
        assert thin_items[0].merge_target_index == 1
        assert result.action_counts["merge"] == 1
        assert len(result.records) == 2
        assert result.records[0]["recipe"] == [1, 1, 1]
        assert result.records[1]["recipe"] == [2, 2, 2]

    def test_thin_shape_can_widen_when_it_only_touches_later_geometry_boundary(self):
        thin_geometry = box(0, 0, 10.0, 0.2)
        probe = PrintableFeatureOptimizer([_shape(thin_geometry, [0, 0, 0], draw_order=0)], scale_factor=1.0)
        touching_y = probe._widen_to_printable_core(thin_geometry).bounds[3]

        optimizer = PrintableFeatureOptimizer(
            [
                _shape(thin_geometry, [0, 0, 0], draw_order=0),
                _shape(box(0, touching_y, 10.0, touching_y + 10.0), [1, 1, 1], draw_order=1),
            ],
            scale_factor=1.0,
        )

        result = optimizer.optimize()
        thin_items = [item for item in result.items if item.classification == "thin"]

        assert thin_items[0].action == "widen"
        assert thin_items[0].widened_to_normal is True
        assert result.action_counts["widen"] == 1
        assert len(result.records) == 2

    def test_draw_order_ties_are_deterministic(self):
        optimizer = PrintableFeatureOptimizer(
            [
                _shape(box(0, 0, 1.0, 1.0), [0, 0, 0], draw_order=5),
                _shape(box(1.0, 0.2, 1.3, 0.5), [1, 1, 1], draw_order=5),
                _shape(box(2.0, 0, 3.0, 1.0), [2, 2, 2], draw_order=9),
            ],
            scale_factor=1.0,
        )

        result = optimizer.optimize()
        assert [item.draw_order for item in result.items] == [5, 5, 9]
        assert [item.index for item in result.items] == [0, 1, 2]

    def test_returned_records_keep_input_index_tie_break_for_equal_draw_order(self):
        optimizer = PrintableFeatureOptimizer(
            [
                _shape(box(0, 0, 1.0, 1.0), [0, 0, 0], draw_order=7),
                _shape(box(2.0, 0, 3.0, 1.0), [1, 1, 1], draw_order=7),
            ],
            scale_factor=1.0,
        )

        result = optimizer.optimize()

        assert [record["recipe"] for record in result.records] == [[0, 0, 0], [1, 1, 1]]

    def test_same_recipe_wins_tie_break_after_geometry_ties(self):
        optimizer = PrintableFeatureOptimizer(
            [
                _shape(box(0.0, 0, 1.0, 1.0), [1, 1, 1], draw_order=0),
                _shape(box(1.3, 0, 2.3, 1.0), [9, 9, 9], draw_order=1),
                _shape(box(1.0, 0.35, 1.3, 0.65), [9, 9, 9], draw_order=2),
            ],
            scale_factor=1.0,
        )

        result = optimizer.optimize()
        merged = [item for item in result.items if item.action == "merge"]
        assert len(merged) == 1
        assert merged[0].merge_target_index == 1

    def test_shared_boundary_candidate_outranks_non_touching_zero_distance_candidate(self):
        optimizer = PrintableFeatureOptimizer(
            [
                _shape(box(0.0, 0.0, 0.3, 0.3), [0], draw_order=0),
                _shape(box(-0.1, -0.1, 0.4, 0.4), [9], draw_order=1),
                _shape(box(0.3, 0.0, 1.3, 1.0), [1], draw_order=2),
            ],
            scale_factor=1.0,
        )

        result = optimizer.optimize()
        source_item = next(item for item in result.items if item.index == 0)

        assert source_item.action == "merge"
        assert source_item.merge_target_index == 2

    def test_chain_merge_preserves_geometry_in_the_live_survivor(self):
        shapes = [
            _shape(box(0.0, 0.0, 0.3, 0.3), [0], draw_order=0),
            _shape(box(0.3, 0.0, 1.0, 1.0), [1], draw_order=1),
            _shape(box(0.0, 0.3, 0.3, 0.6), [2], draw_order=2),
        ]
        optimizer = PrintableFeatureOptimizer(shapes, scale_factor=1.0)

        result = optimizer.optimize()

        assert len(result.records) == 1
        assert result.records[0]["geometry"].area == pytest.approx(unary_union([shape["geometry"] for shape in shapes]).area)
        assert result.action_counts["merge"] == 2
        assert [item.action for item in result.items].count("keep") == 1

    def test_merge_refreshes_candidate_index_after_target_geometry_grows(self):
        optimizer = PrintableFeatureOptimizer(
            [
                _shape(box(0.7, 0.0, 1.0, 0.3), [1], draw_order=0),
                _shape(box(1.0, 0.0, 2.0, 1.0), [1], draw_order=1),
                _shape(box(0.4, 0.0, 0.7, 0.3), [2], draw_order=2),
                _shape(box(0.1, 0.0, 0.4, 1.0), [9], draw_order=3),
            ],
            scale_factor=1.0,
        )

        result = optimizer.optimize()

        merged = [item for item in result.items if item.action == "merge"]
        assert len(merged) == 3
        assert merged[0].merge_target_index == 1
        assert merged[1].merge_target_index == 1
        assert merged[2].merge_target_index == 1
        assert len(result.records) == 1
        assert result.records[0]["recipe"] == [1]

    def test_transitive_merge_provenance_survives_later_merge(self, monkeypatch):
        optimizer = PrintableFeatureOptimizer(
            [
                _shape(box(0.0, 0.0, 0.3, 0.3), [0], draw_order=0),
                _shape(box(0.3, 0.0, 1.0, 1.0), [1], draw_order=1),
                _shape(box(1.0, 0.0, 1.3, 1.0), [2], draw_order=2),
            ],
            scale_factor=1.0,
        )

        monkeypatch.setattr(optimizer, "_widen_to_printable_core", lambda geometry: None)
        result = optimizer.optimize()

        survivor = result.records[0]
        assert survivor["recipe"] == [2]
        assert survivor["_received_merge_source_indices"] == [0, 1]
        assert survivor["_received_merge_source_recipes"] == [(0,), (1,)]
        assert result.items[0].merge_source_index == 0
        assert result.items[1].merge_source_index == 1
        assert result.items[2].received_merge_source_indices == (0, 1)
