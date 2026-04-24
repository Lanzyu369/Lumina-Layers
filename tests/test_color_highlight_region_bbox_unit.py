"""Regression tests for ``POST /api/convert/color-highlight`` region_bbox.

Verifies that the endpoint clips its cyan-overlay scan to the optional
``region_bbox`` rectangle so the Gradient Groups panel's "select region"
button can highlight only that one region instead of every matching pixel
on the canvas.
渐变分组面板"选中区域"的高亮范围修复回归测试：验证 region_bbox 能把
高亮扫描限制在矩形内，避免"点小分组却把整组都点亮"的视觉 bug。
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore


# ---------------------------------------------------------------------------
# Fixtures — isolated FastAPI app + in-memory stores per test.
# ---------------------------------------------------------------------------


def _make_client_with_cache(
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
) -> tuple[TestClient, str]:
    """Create a fresh TestClient with a pre-populated preview cache.

    Returns ``(client, session_id)`` where the session already has the
    minimal ``preview_cache`` keys the ``color-highlight`` route reads.
    返回一个预置 preview_cache 的 TestClient 与 session_id，便于直接
    调用高亮路由而无需跑完整预览流程。
    """
    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry

    session_id = store.create()
    store.put(
        session_id,
        "preview_cache",
        {
            "matched_rgb": matched_rgb,
            "mask_solid": mask_solid,
        },
    )

    return TestClient(app), session_id


def _read_png(client: TestClient, preview_url: str) -> np.ndarray:
    """Fetch the PNG at ``preview_url`` and return it as an RGB ndarray."""
    response = client.get(preview_url)
    assert response.status_code == 200, response.text
    img = Image.open(io.BytesIO(response.content)).convert("RGB")
    return np.asarray(img, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def solid_red_frame() -> tuple[np.ndarray, np.ndarray]:
    """A 100x100 all-red solid frame used across the tests.
    用于全部测试的 100×100 纯红色图。
    """
    matched_rgb = np.full((100, 100, 3), (255, 0, 0), dtype=np.uint8)
    mask_solid = np.ones((100, 100), dtype=bool)
    return matched_rgb, mask_solid


def test_color_highlight_without_bbox_covers_whole_canvas(
    solid_red_frame: tuple[np.ndarray, np.ndarray],
) -> None:
    """Baseline: omitting region_bbox scans the full canvas (unchanged).
    基准行为：不传 region_bbox 时仍然全图扫描匹配 hex。
    """
    matched_rgb, mask_solid = solid_red_frame
    client, session_id = _make_client_with_cache(matched_rgb, mask_solid)

    response = client.post(
        "/api/convert/color-highlight",
        json={"session_id": session_id, "color_hexes": ["#ff0000"]},
    )
    assert response.status_code == 200, response.text
    preview_url = response.json()["preview_url"]
    img = _read_png(client, preview_url)

    # Every pixel should be the cyan-mixed overlay, nowhere should the
    # original pure red survive.
    # 预期全图都被 cyan overlay 覆盖，原始纯红应不再存在。
    pure_red_pixels = int(np.all(img == (255, 0, 0), axis=-1).sum())
    assert pure_red_pixels == 0


def test_color_highlight_with_bbox_clips_to_rectangle(
    solid_red_frame: tuple[np.ndarray, np.ndarray],
) -> None:
    """Core fix: region_bbox restricts the cyan overlay to the rectangle.
    核心修复：region_bbox 把高亮限定在矩形内，矩形外保持原色。
    """
    matched_rgb, mask_solid = solid_red_frame
    client, session_id = _make_client_with_cache(matched_rgb, mask_solid)

    response = client.post(
        "/api/convert/color-highlight",
        json={
            "session_id": session_id,
            "color_hexes": ["#ff0000"],
            "region_bbox": [0, 0, 50, 100],  # left half only
        },
    )
    assert response.status_code == 200, response.text
    preview_url = response.json()["preview_url"]
    img = _read_png(client, preview_url)

    # Left half (x < 50): should be cyan-mixed, i.e. NOT pure red anymore.
    # Right half (x >= 50): should stay pure (255, 0, 0) because scan was
    # clipped to the bbox. This is exactly the visual the user wanted.
    # 左半高亮后不再纯红；右半保持 (255, 0, 0) —— 就是用户想要的效果。
    left_pure_red = int(np.all(img[:, :50] == (255, 0, 0), axis=-1).sum())
    right_pure_red = int(np.all(img[:, 50:] == (255, 0, 0), axis=-1).sum())
    assert left_pure_red == 0
    assert right_pure_red == 100 * 50


def test_color_highlight_rejects_out_of_bounds_bbox(
    solid_red_frame: tuple[np.ndarray, np.ndarray],
) -> None:
    """Out-of-bounds bbox must yield HTTP 400 with an actionable message.
    越界 bbox 返回 400，便于前端/调用方快速定位问题。
    """
    matched_rgb, mask_solid = solid_red_frame
    client, session_id = _make_client_with_cache(matched_rgb, mask_solid)

    response = client.post(
        "/api/convert/color-highlight",
        json={
            "session_id": session_id,
            "color_hexes": ["#ff0000"],
            "region_bbox": [0, 0, 999, 999],  # exceeds the 100x100 frame
        },
    )
    assert response.status_code == 400, response.text
    assert "region_bbox" in response.json()["detail"]


def test_color_highlight_rejects_inverted_bbox(
    solid_red_frame: tuple[np.ndarray, np.ndarray],
) -> None:
    """Inverted bbox (x0>=x1 or y0>=y1) is also a 400, not a silent empty.
    反向 bbox 同样返回 400，避免静默产生空高亮让调用方无法排查。
    """
    matched_rgb, mask_solid = solid_red_frame
    client, session_id = _make_client_with_cache(matched_rgb, mask_solid)

    response = client.post(
        "/api/convert/color-highlight",
        json={
            "session_id": session_id,
            "color_hexes": ["#ff0000"],
            "region_bbox": [50, 0, 50, 100],  # zero-width rectangle
        },
    )
    assert response.status_code == 400, response.text
