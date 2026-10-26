"""Regression tests for contour-aware keychain loop anchoring."""

import numpy as np
import pytest

from core.pipeline.s05_preview_generation import _calculate_loop_position


def _irregular_mask() -> np.ndarray:
    """Create a body whose tallest point is far from the top-center anchor."""
    mask = np.zeros((60, 60), dtype=bool)
    mask[20:55, 18:42] = True
    mask[5:55, 4:8] = True
    return mask


def _ticket_like_mask() -> np.ndarray:
    """Approximate the ticket's small global-to-local top-edge gap."""
    mask = np.zeros((60, 60), dtype=bool)
    mask[8:55, 18:42] = True
    mask[6:55, 4:8] = True
    return mask


def test_top_center_clamps_inward_offset_to_local_contact_edge() -> None:
    """An inward offset must stop at the body under the loop contact width."""
    attach_x, attach_y = _calculate_loop_position(
        position_preset="top-center",
        offset_x=0.0,
        offset_y=-20.0,
        mask_solid=_irregular_mask(),
        target_w=60,
        target_h=60,
        pixel_scale=1.0,
        contact_width_mm=8.0,
    )

    assert attach_x == 22.5
    assert attach_y == 40.0


def test_top_center_non_overlapping_offsets_remain_additive() -> None:
    """Offsets remain additive while the requested position stays outside."""
    mask = _irregular_mask()
    base_x, base_y = _calculate_loop_position(
        "top-center", 0.0, 0.0, mask, 60, 60, 1.0, contact_width_mm=8.0
    )
    moved_x, moved_y = _calculate_loop_position(
        "top-center", 6.0, 3.5, mask, 60, 60, 1.0, contact_width_mm=8.0
    )

    assert moved_x == base_x + 6.0
    assert moved_y == base_y + 3.5


@pytest.mark.parametrize("captured_offset_y", [-6.5, -10.5])
def test_ticket_offsets_stop_at_local_contact_edge(captured_offset_y: float) -> None:
    """Both offsets captured in LUM-20260730-002 must remain outside."""
    attach_x, attach_y = _calculate_loop_position(
        "top-center",
        0.0,
        captured_offset_y,
        _ticket_like_mask(),
        60,
        60,
        1.0,
        contact_width_mm=7.0,
    )

    assert attach_x == 22.5
    assert attach_y == 52.0
