"""Regression coverage for scalar spatial-edit diagnostics.

空间局部改色诊断标量的回归测试。
"""

from __future__ import annotations

import json

import pytest

from api.routers.feedback import BugReportRequest
from tests.test_feedback_router_unit import _payload


def _validate_advanced_params(value):
    payload = _payload()
    payload["context"]["advanced_params"] = value
    return BugReportRequest.model_validate(payload).context.advanced_params


@pytest.mark.parametrize("count", [0, 1, 27])
def test_sanitizer_preserves_spatial_edit_count_without_spatial_payload(
    count: int,
) -> None:
    """Keep the scalar count without adding masks, blobs, or coordinates.

    仅保留空间编辑次数标量，不携带掩码、Blob 或坐标。
    """
    payload = {
        "color_replacement": {
            "spatial_edit_count": count,
        }
    }

    sanitized = _validate_advanced_params(payload)

    assert sanitized == payload
    serialized = json.dumps(sanitized, sort_keys=True).lower()
    for forbidden in ("mask", "blob", "coordinate", "click_x", "click_y"):
        assert forbidden not in serialized
