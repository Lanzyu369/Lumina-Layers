"""Regression tests for pixel-accurate sub-region *replacement*.

Covers ``POST /api/convert/region-replace`` when the request carries
``gradient_group_index + gradient_region_index``: the endpoint must rebuild
the mask from the cached ``gradient_region_id_map`` and modify only the
pixels inside that sub-region, leaving other regions that share the same
matched hex untouched. This pins the second half of the fix for the
"picking a region then replacing colour recolours the whole body" bug.
渐变分组"选中子区域"替换的回归测试：验证端点用缓存的 region_id_map 现场
生成 mask，精确地只改 region 内像素，不污染共享同一量化 hex 的其他区域。
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

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
) -> tuple[TestClient, str, SessionStore]:
    """Build a TestClient with a seeded session and expose the store.

    The caller often wants to poke at ``session_data`` post-replace to
    verify the cached ``gradient_region_id_map`` survived — so we return
    the store too.
    构造 TestClient + 预先填充 session（preview_cache + region_id_map）。
    同时返回 store 让测试后续检查 session_data 内部状态。
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
            "matched_rgb": matched_rgb.copy(),
            "mask_solid": mask_solid.copy(),
        },
    )
    if region_id_map is not None:
        store.put(session_id, "gradient_region_id_map", region_id_map.copy())

    return TestClient(app), session_id, store


@pytest.fixture()
def two_red_stripes() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Two same-coloured stripes assigned to distinct gradient regions.

    A 100x100 canvas painted entirely ``#ff0000``. The mask is solid.
    region_id_map tags ``x ∈ [10, 40)`` as ``(group=1, region=1)`` and
    ``x ∈ [60, 90)`` as ``(group=1, region=2)``. This is the exact
    "bleed-into-other-region" scenario a bbox or hex-based replacement
    would fail.
    100x100 全红画布，两段同色红条带分别标记为不同 region。
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


def test_gradient_region_replace_only_touches_that_region(
    two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Replacing region 1 leaves region 2's same-hex pixels untouched.
    仅替换 region 1，region 2 的同色像素保持红色（bug 修复回归锁定）。
    """
    matched_rgb, mask_solid, region_id_map = two_red_stripes
    client, session_id, store = _make_client_with_session(
        matched_rgb, mask_solid, region_id_map
    )

    response = client.post(
        "/api/convert/region-replace",
        json={
            "session_id": session_id,
            "replacement_color": "#00ff00",
            "gradient_group_index": 1,
            "gradient_region_index": 1,
        },
    )
    assert response.status_code == 200, response.text

    # Re-read matched_rgb from the store to verify the actual pixel
    # mutation (not just the rendered PNG).
    # 直接从 store 取更新后的 matched_rgb 验证像素级正确性。
    updated = store.get(session_id)["preview_cache"]["matched_rgb"]
    assert np.all(updated[:, 10:40] == (0, 255, 0)), "region 1 should be green"
    assert np.all(updated[:, 60:90] == (255, 0, 0)), (
        "region 2 must stay red — the bug would recolour it"
    )
    outside_cols = np.r_[0:10, 40:60, 90:100]
    assert np.all(updated[:, outside_cols] == (255, 0, 0)), (
        "pixels outside any gradient region must stay red"
    )


def test_gradient_region_replace_preserves_region_id_map_for_subsequent_edits(
    two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """After a gradient-region replace, region_id_map must still be cached.

    The click-detected flow ``/region-detect → /region-replace`` is a
    one-shot interaction and clears ``selected_region_mask`` after use.
    The gradient flow is different: the user typically edits region after
    region; forcing a ``/preview`` re-run between each one would be
    prohibitively slow. So the cached ``gradient_region_id_map`` must
    survive the replacement.
    渐变路径需支持连续编辑多个区域，要求 region_id_map 在替换后继续可用。
    """
    matched_rgb, mask_solid, region_id_map = two_red_stripes
    client, session_id, store = _make_client_with_session(
        matched_rgb, mask_solid, region_id_map
    )

    response = client.post(
        "/api/convert/region-replace",
        json={
            "session_id": session_id,
            "replacement_color": "#00ff00",
            "gradient_group_index": 1,
            "gradient_region_index": 1,
        },
    )
    assert response.status_code == 200, response.text

    cached = store.get(session_id).get("gradient_region_id_map")
    assert cached is not None, (
        "gradient_region_id_map must survive the replace so the user can "
        "edit another region without re-running /preview"
    )
    assert np.asarray(cached).shape == (100, 100)


def test_gradient_group_replace_touches_all_regions_in_group(
    two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Providing only group_index (no region_index) replaces all pixels in
    the group — the "去海带纹 whole group" flow.
    只传 gradient_group_index（不传 region_index）时覆盖该组所有像素。
    """
    matched_rgb, mask_solid, region_id_map = two_red_stripes
    client, session_id, store = _make_client_with_session(
        matched_rgb, mask_solid, region_id_map
    )

    response = client.post(
        "/api/convert/region-replace",
        json={
            "session_id": session_id,
            "replacement_color": "#00ff00",
            "gradient_group_index": 1,
            # gradient_region_index intentionally omitted
        },
    )
    assert response.status_code == 200, response.text

    updated = store.get(session_id)["preview_cache"]["matched_rgb"]
    # Both region 1 (cols 10-40) and region 2 (cols 60-90) should be green
    assert np.all(updated[:, 10:40] == (0, 255, 0)), "region 1 should be green"
    assert np.all(updated[:, 60:90] == (0, 255, 0)), "region 2 should be green"
    # Pixels outside any gradient region stay red
    outside_cols = np.r_[0:10, 40:60, 90:100]
    assert np.all(updated[:, outside_cols] == (255, 0, 0)), (
        "pixels outside gradient regions must stay red"
    )


def test_gradient_region_replace_without_cached_map_returns_409(
    two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Missing region_id_map must be flagged with 409, not a silent fallback.
    缺少 region_id_map 返回 409，提示调用方重跑 /preview。
    """
    matched_rgb, mask_solid, _ = two_red_stripes
    client, session_id, _ = _make_client_with_session(
        matched_rgb, mask_solid, region_id_map=None
    )

    response = client.post(
        "/api/convert/region-replace",
        json={
            "session_id": session_id,
            "replacement_color": "#00ff00",
            "gradient_group_index": 1,
            "gradient_region_index": 1,
        },
    )
    assert response.status_code == 409, response.text
    assert "gradient_region_id_map" in response.json()["detail"]


def test_gradient_region_replace_unknown_region_returns_404(
    two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """An identifier pair with no matching pixels yields 404.
    指定 (group, region) 编号在 region_id_map 中无对应像素返回 404。
    """
    matched_rgb, mask_solid, region_id_map = two_red_stripes
    client, session_id, _ = _make_client_with_session(
        matched_rgb, mask_solid, region_id_map
    )

    response = client.post(
        "/api/convert/region-replace",
        json={
            "session_id": session_id,
            "replacement_color": "#00ff00",
            "gradient_group_index": 9,  # does not exist
            "gradient_region_index": 9,
        },
    )
    assert response.status_code == 404, response.text


def test_legacy_click_region_replace_still_works_without_gradient_fields(
    two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """The legacy click-detected mask path is not regressed by the new field.
    不传 gradient 字段时仍走 legacy 的 selected_region_mask 路径，不影响既有流程。
    """
    matched_rgb, mask_solid, _ = two_red_stripes
    client, session_id, store = _make_client_with_session(
        matched_rgb, mask_solid, region_id_map=None
    )

    # Pretend /region-detect has already stashed a mask covering only
    # the top half of the canvas.
    # 模拟 region-detect 的写入，mask 仅覆盖画布上半部分。
    legacy_mask = np.zeros((100, 100), dtype=bool)
    legacy_mask[:50, :] = True
    store.put(session_id, "selected_region_mask", legacy_mask)
    store.put(session_id, "selected_region_id", "legacy-region-uuid")

    response = client.post(
        "/api/convert/region-replace",
        json={
            "session_id": session_id,
            "replacement_color": "#0000ff",
        },
    )
    assert response.status_code == 200, response.text

    updated = store.get(session_id)["preview_cache"]["matched_rgb"]
    assert np.all(updated[:50, :] == (0, 0, 255)), "top half should be blue"
    assert np.all(updated[50:, :] == (255, 0, 0)), "bottom half stays red"

    # Legacy flow clears the one-shot mask to prevent accidental reuse.
    # Legacy 路径消费完 mask 后清理，防止后续误用同一 mask。
    session_after = store.get(session_id)
    assert session_after.get("selected_region_mask") is None
    assert session_after.get("selected_region_id") is None
