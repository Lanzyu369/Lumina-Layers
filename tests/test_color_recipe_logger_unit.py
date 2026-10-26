"""Unit tests for color recipe report helpers."""

import numpy as np

from utils.color_recipe_logger import _count_unique_color_stack_combinations


def test_count_unique_color_stack_combinations_preserves_counts_and_order() -> None:
    matched_rgb = np.array(
        [
            [[1, 2, 3], [9, 9, 9]],
            [[1, 2, 3], [4, 5, 6]],
        ],
        dtype=np.uint8,
    )
    material_matrix = np.array(
        [
            [[0, 1, 2, 3, 4], [1, 1, 1, 1, 1]],
            [[0, 1, 2, 3, 4], [2, 2, 2, 2, 2]],
        ],
        dtype=np.int32,
    )
    mask_solid = np.array([[True, True], [True, False]])

    assert _count_unique_color_stack_combinations(
        matched_rgb,
        material_matrix,
        mask_solid,
    ) == [
        ((1, 2, 3), (0, 1, 2, 3, 4), 2),
        ((9, 9, 9), (1, 1, 1, 1, 1), 1),
    ]


def test_count_unique_color_stack_combinations_falls_back_for_large_material_ids() -> None:
    matched_rgb = np.array([[[1, 2, 3], [1, 2, 3]]], dtype=np.uint8)
    material_matrix = np.array(
        [
            [
                [300, 0, 0, 0, 0],
                [44, 1, 0, 0, 0],
            ]
        ],
        dtype=np.int32,
    )
    mask_solid = np.array([[True, True]])

    assert _count_unique_color_stack_combinations(
        matched_rgb,
        material_matrix,
        mask_solid,
    ) == [
        ((1, 2, 3), (300, 0, 0, 0, 0), 1),
        ((1, 2, 3), (44, 1, 0, 0, 0), 1),
    ]
