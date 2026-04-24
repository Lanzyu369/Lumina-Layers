"""Regression tests for pixel-accurate sub-region highlighting.

Covers ``POST /api/convert/color-highlight`` when called with
``gradient_group_index + gradient_region_index``: the endpoint must clip the
cyan overlay to the *exact* pixel mask of the selected sub-region, even when
other pixels share the same matched hex (the common case for gradient
groups where multiple disjoint regions use the same material colour).
渐变分组"选中子区域"高亮的像素级精确裁剪回归测试：验证端点使用缓存的
``gradient_region_id_map`` 按精确像素 mask 裁剪，而不会把同色的其他区域也点亮。
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
from core.gradient_group_analyzer import REGION_ID_ENCODING_MULTIPLIER


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_client_with_session(
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
    region_id_map: np.ndarray | None,
) -> tuple[TestClient, str]:
    """Build a TestClient with a seeded session.

    ``matched_rgb`` + ``mask_solid`` go into ``preview_cache``; the optional
    ``region_id_map`` is stored at the session top level under the same key
    the preview pipeline uses. This mirrors the real wiring without having
    to run the full /preview pipeline.
    把 matched_rgb、mask_solid 写入 preview_cache，并将 region_id_map 放在
    session 顶层，模拟真实 /preview 流程写好的缓存布局。
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
        {"matched_rgb": matched_rgb, "mask_solid": mask_solid},
    )
    if region_id_map is not None:
        store.put(session_id, "gradient_region_id_map", region_id_map)

    return TestClient(app), session_id


def _read_png(client: TestClient, preview_url: str) -> np.ndarray:
    response = client.get(preview_url)
    assert response.status_code == 200, response.text
    img = Image.open(io.BytesIO(response.content)).convert("RGB")
    return np.asarray(img, dtype=np.uint8)


@pytest.fixture()
def two_red_stripes() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A 100x100 canvas with two separate red stripes marked as distinct regions.

    Both stripes share the same matched hex (``#ff0000``) but are *separate*
    spatial regions — the exact scenario where a bbox-only approach bleeds
    into the other stripe. The fixture returns a ``region_id_map`` where:
      * stripe A at ``x ∈ [10, 40)`` is encoded as ``(group=1, region=1)``.
      * stripe B at ``x ∈ [60, 90)`` is encoded as ``(group=1, region=2)``.
    两条同色但空间独立的红色条带，region_id_map 分别标注为 (1,1) 与 (1,2)。
    """
    matched_rgb = np.full((100, 100, 3), (255, 0, 0), dtype=np.uint8)
    mask_solid = np.ones((100, 100), dtype=bool)
    region_id_map = np.zeros((100, 100), dtype=np.uint32)
    region_id_map[:, 10:40] = 1 * REGION_ID_ENCODING_MULTIPLIER + 1
    region_id_map[:, 60:90] = 1 * REGION_ID_ENCODING_MULTIPLIER + 2
    return matched_rgb, mask_solid, region_id_map


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_region_mask_path_lights_only_selected_region(
    two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Selecting region 1 leaves region 2 unaffected despite the shared hex.
    选中 region 1 时只有 region 1 的像素被点亮，region 2 保持原色。
    """
    matched_rgb, mask_solid, region_id_map = two_red_stripes
    client, session_id = _make_client_with_session(
        matched_rgb, mask_solid, region_id_map
    )

    response = client.post(
        "/api/convert/color-highlight",
        json={
            "session_id": session_id,
            "color_hexes": ["#ff0000"],
            "gradient_group_index": 1,
            "gradient_region_index": 1,
        },
    )
    assert response.status_code == 200, response.text
    img = _read_png(client, response.json()["preview_url"])

    # Stripe A (x ∈ [10, 40)) — cyan-blended, not pure red anymore.
    assert int(np.all(img[:, 10:40] == (255, 0, 0), axis=-1).sum()) == 0
    # Stripe B (x ∈ [60, 90)) — must stay pure red because it belongs to
    # a different region despite sharing the same matched hex.
    assert int(np.all(img[:, 60:90] == (255, 0, 0), axis=-1).sum()) == 100 * 30
    # Outside both stripes — also pure red because mask is zero there.
    outside_cols = np.r_[0:10, 40:60, 90:100]
    assert int(
        np.all(img[:, outside_cols] == (255, 0, 0), axis=-1).sum()
    ) == 100 * outside_cols.size


def test_region_mask_path_rejects_half_supplied_pair(
    two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Providing only group OR only region must surface a 400.
    只提供 group 或 region 中的一个返回 400，避免误把半成品当合法请求。
    """
    matched_rgb, mask_solid, region_id_map = two_red_stripes
    client, session_id = _make_client_with_session(
        matched_rgb, mask_solid, region_id_map
    )

    response = client.post(
        "/api/convert/color-highlight",
        json={
            "session_id": session_id,
            "color_hexes": ["#ff0000"],
            "gradient_group_index": 1,  # region_index missing
        },
    )
    assert response.status_code == 400, response.text
    assert "gradient_region_index" in response.json()["detail"]


def test_region_mask_path_without_cached_map_returns_409(
    two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Missing region_id_map must be flagged with 409, not a silent fallback.
    缺少 region_id_map 时返回 409 让调用方明确触发重跑预览，而不是静默退回。
    """
    matched_rgb, mask_solid, _ = two_red_stripes
    client, session_id = _make_client_with_session(
        matched_rgb, mask_solid, region_id_map=None
    )

    response = client.post(
        "/api/convert/color-highlight",
        json={
            "session_id": session_id,
            "color_hexes": ["#ff0000"],
            "gradient_group_index": 1,
            "gradient_region_index": 1,
        },
    )
    assert response.status_code == 409, response.text
    assert "gradient_region_id_map" in response.json()["detail"]


def test_region_mask_path_unknown_region_returns_404(
    two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """An identifier pair with no matching pixels yields 404.
    指定的 (group, region) 编号在 region_id_map 中无对应像素时返回 404。
    """
    matched_rgb, mask_solid, region_id_map = two_red_stripes
    client, session_id = _make_client_with_session(
        matched_rgb, mask_solid, region_id_map
    )

    response = client.post(
        "/api/convert/color-highlight",
        json={
            "session_id": session_id,
            "color_hexes": ["#ff0000"],
            "gradient_group_index": 9,  # does not exist in region_id_map
            "gradient_region_index": 9,
        },
    )
    assert response.status_code == 404, response.text


def test_region_mask_path_takes_precedence_over_bbox(
    two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """When both identifiers and bbox are passed, identifiers win.
    同时传 group/region 与 region_bbox 时优先使用精确 mask 路径。
    """
    matched_rgb, mask_solid, region_id_map = two_red_stripes
    client, session_id = _make_client_with_session(
        matched_rgb, mask_solid, region_id_map
    )

    # A deliberately misleading bbox that would otherwise cover the OTHER
    # stripe (region 2). If the endpoint accidentally honoured the bbox
    # path it would highlight region 2; with correct precedence only
    # region 1 gets highlighted.
    response = client.post(
        "/api/convert/color-highlight",
        json={
            "session_id": session_id,
            "color_hexes": ["#ff0000"],
            "gradient_group_index": 1,
            "gradient_region_index": 1,
            "region_bbox": [60, 0, 90, 100],
        },
    )
    assert response.status_code == 200, response.text
    img = _read_png(client, response.json()["preview_url"])
    assert int(np.all(img[:, 10:40] == (255, 0, 0), axis=-1).sum()) == 0
    assert int(np.all(img[:, 60:90] == (255, 0, 0), axis=-1).sum()) == 100 * 30
