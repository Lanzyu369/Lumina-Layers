"""Route-level regression tests for ``POST /api/convert/region-requantize``.

聚焦验证 region-requantize 端点在二次量化完成后会把实际唯一色数写入
``preview_cache['glb_max_meshes']``，覆盖 :func:`generate_segmented_glb`
默认 64 mesh 上限——否则后台 GLB 重建会把新色合并掉，导致 3D 预览看
起来跟量化前没区别。

This pins the user-reported bug: "重新量化后 3D 预览的 GLB 没更新"，
根因是 segmented-GLB 的 64 mesh 上限把局部新色合并回主调色板。修复方案
是 region-requantize 在 sync 后按真实 unique-colour 数把 cap 抬高。
"""

from __future__ import annotations

import logging
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from core.gradient_group_analyzer import REGION_ID_ENCODING_MULTIPLIER
from core.pipeline._input_validation_common import MaterialArchiveProfileError

REGION_REQUANTIZE_MATERIALS_UNAVAILABLE_DETAIL = (
    "Region re-quantisation cannot load the selected material archives. "
    "Re-select the materials and run preview again."
)
REGION_REQUANTIZE_SOURCE_IMAGE_UNAVAILABLE_DETAIL = (
    "Region re-quantisation cannot read the original source image. "
    "Re-upload the image and run preview again."
)
REGION_REQUANTIZE_REQUEST_INVALID_DETAIL = (
    "Region re-quantisation could not process the selected region. "
    "Refresh preview and try again."
)


@pytest.fixture(autouse=True)
def _profile_loader_uses_route_material_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Route regressions patch the material loader, not on-disk archives."""

    from api.routers.converter import replace

    monkeypatch.setattr(
        replace,
        "load_and_validate_material_archive_profile",
        lambda directory_names, *, profile_kind: (
            str(profile_kind or "stage_a"),
            replace.load_multiple_materials(directory_names),
        ),
    )


# ---------------------------------------------------------------------------
# Fixtures / shared scaffolding
# ---------------------------------------------------------------------------


@pytest.fixture()
def patched_dependencies(tmp_path):
    """Build a TestClient + SessionStore + on-disk fake source image.

    Centralises the heavy fan-out: real ``MaterialSolverCache`` and async
    GLB build are mocked because both rely on filesystem caches and
    background threads that aren't worth exercising for cap-propagation
    tests. We DO call the real ``requantize_gradient_regions`` so the
    side-effect on ``cache['matched_rgb']`` (and therefore on the new
    ``glb_max_meshes`` value the route writes) is exactly what production
    sees.
    集中处理脚手架：构造 TestClient、SessionStore，以及一张落盘的伪造
    原图。``MaterialSolverCache`` 与异步 GLB 构建被打桩——它们依赖
    磁盘缓存和线程池，对 cap 写入回归没价值。``requantize_gradient_regions``
    保留真实实现，确保对 ``cache['matched_rgb']`` 的副作用与生产一致。
    """
    h, w = 32, 48
    # Source image with smooth gradients in the centre region. The
    # gradient is what the requantizer K-Means'es into many local colours.
    # 中央区域是平滑渐变，正是 K-Means 会切成很多局部色的输入。
    rng = np.random.default_rng(0)
    src = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    src_path = tmp_path / "source.png"
    Image.fromarray(src).save(src_path)

    # Initial matched_rgb: just two flat colours, well below the cap.
    # 初始 matched_rgb 只有两种色，远低于 64 上限。
    matched_rgb = np.full((h, w, 3), (10, 20, 30), dtype=np.uint8)
    matched_rgb[:, w // 2 :] = (200, 50, 80)
    mask_solid = np.ones((h, w), dtype=bool)

    # Region id map: central rectangle is (group=1, region=1).
    region_id_map = np.zeros((h, w), dtype=np.uint32)
    y0, y1 = h // 4, 3 * h // 4
    x0, x1 = w // 4, 3 * w // 4
    region_id_map[y0:y1, x0:x1] = 1 * REGION_ID_ENCODING_MULTIPLIER + 1

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
            "color_layers": 10,
            "layer_height_mm": 0.08,
            "material_substrate": "white",
            "target_w": w,
            "target_h": h,
            "target_width_mm": 100.0,
        },
    )
    store.put(session_id, "gradient_region_id_map", region_id_map)
    store.put(session_id, "image_path", str(src_path))
    store.put(session_id, "material_source", "material_archive")
    # Two fake material archive paths — they are never actually loaded
    # because the route's ``load_multiple_materials`` call is patched.
    # 两个假路径；``load_multiple_materials`` 已打桩，不会真去读它们。
    store.put(session_id, "selected_materials", ["fake/A", "fake/B"])
    store.put(session_id, "material_layer_count", 10)
    store.put(session_id, "material_layer_height_mm", 0.08)

    client = TestClient(app)
    return client, session_id, store


class _FakeSolverCache:
    """Minimal ``MaterialSolverCache`` stub for the route.

    Maps every input colour to a unique deterministic output by hashing
    so the post-quantise ``matched_rgb`` ends up with as many distinct
    colours as the local K-Means produced.
    把每个输入色按哈希映射到唯一输出色，确保量化后 ``matched_rgb`` 的
    唯一色数 = K-Means 簇数，方便测试 cap 是否同步抬高。
    """

    def lookup(self, target_srgb, _user_materials):  # noqa: D401
        arr = np.asarray(target_srgb, dtype=np.uint8)
        # Encode each input RGB into a deterministic distinct output by
        # rotating the channels — guarantees output uniqueness while
        # remaining valid uint8 RGB triples.
        # 通过通道旋转生成唯一输出，简单又可复现。
        rotated = arr[:, [1, 2, 0]].copy()
        # Add a tiny per-row offset so even (a, a, a) inputs become distinct.
        # 给每行加一个小偏移，确保即便 (a,a,a) 这种灰也唯一。
        offsets = (np.arange(arr.shape[0], dtype=np.int32) % 64).astype(np.uint8)
        rotated[:, 0] = ((rotated[:, 0].astype(np.int32) + offsets) % 256).astype(np.uint8)
        recipes = np.zeros((arr.shape[0], 1), dtype=np.int32)
        delta_e = np.zeros(arr.shape[0], dtype=np.float64)
        return rotated, recipes, delta_e


def _region_requantize_payload(session_id: str) -> dict[str, object]:
    return {
        "session_id": session_id,
        "targets": [
            {"gradient_group_index": 1, "gradient_region_index": 1},
        ],
        "local_quantize_colors": 12,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_requantize_material_load_error_uses_safe_detail_and_logs(
    patched_dependencies,
    caplog,
):
    client, session_id, _store = patched_dependencies
    target_logger = logging.getLogger("lumina.api.routers.converter.replace")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=target_logger.name)
    try:
        with patch(
            "api.routers.converter.replace.load_multiple_materials",
            side_effect=FileNotFoundError(
                "/Users/min/private/materials/BrandA/material.json"
            ),
        ):
            resp = client.post(
                "/api/convert/region-requantize",
                json=_region_requantize_payload(session_id),
            )
    finally:
        target_logger.removeHandler(caplog.handler)

    assert resp.status_code == 409
    assert resp.json()["detail"] == REGION_REQUANTIZE_MATERIALS_UNAVAILABLE_DETAIL
    assert "/Users/min/private" not in resp.text
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "converter_region_requantize_failed"
    ]
    assert records
    assert records[-1].error_type == "FileNotFoundError"
    assert "/Users/min/private" in records[-1].error_message


def test_requantize_source_image_error_uses_safe_detail(
    patched_dependencies,
    tmp_path,
):
    client, session_id, store = patched_dependencies
    corrupt_source = tmp_path / "private-source.png"
    corrupt_source.write_text("not an image", encoding="utf-8")
    store.put(session_id, "image_path", str(corrupt_source))

    with patch(
        "api.routers.converter.replace.load_multiple_materials",
        return_value=[],
    ), patch(
        "api.routers.converter.replace.load_material_solver_cache_with_fallback",
        return_value=(_FakeSolverCache(), 64),
    ):
        resp = client.post(
            "/api/convert/region-requantize",
            json=_region_requantize_payload(session_id),
        )

    assert resp.status_code == 500
    assert resp.json()["detail"] == REGION_REQUANTIZE_SOURCE_IMAGE_UNAVAILABLE_DETAIL
    assert str(corrupt_source) not in resp.text


def test_requantize_core_error_uses_safe_detail(
    patched_dependencies,
):
    client, session_id, _store = patched_dependencies

    with patch(
        "api.routers.converter.replace.load_multiple_materials",
        return_value=[],
    ), patch(
        "api.routers.converter.replace.load_material_solver_cache_with_fallback",
        return_value=(_FakeSolverCache(), 64),
    ), patch(
        "api.routers.converter.replace.requantize_gradient_regions",
        side_effect=ValueError(
            "local quantize failed for /Users/min/private/source.png"
        ),
    ):
        resp = client.post(
            "/api/convert/region-requantize",
            json=_region_requantize_payload(session_id),
        )

    assert resp.status_code == 409
    assert resp.json()["detail"] == REGION_REQUANTIZE_REQUEST_INVALID_DETAIL
    assert "/Users/min/private" not in resp.text


def test_requantize_writes_glb_max_meshes_above_default(patched_dependencies):
    """After requantize, ``cache['glb_max_meshes']`` must rise to ≥ unique-count.
    量化后 cap 必须 ≥ matched_rgb 真实唯一色数，否则 GLB 合并会丢色。
    """
    client, session_id, store = patched_dependencies
    schedule_calls: list[tuple[str, dict]] = []

    def _capture_schedule(sid, _store, _registry, cache):
        # Snapshot what the route handed to the GLB scheduler — this is
        # exactly what the background worker will read.
        # 抓取 route 传给调度器的 cache 快照，这就是 worker 实际读的内容。
        schedule_calls.append((sid, dict(cache)))
        return "fake-job-token"

    with patch(
        "api.routers.converter.replace.load_multiple_materials",
        return_value=[],
    ), patch(
        "api.routers.converter.replace.load_material_solver_cache_with_fallback",
        return_value=(_FakeSolverCache(), 64),
    ), patch(
        "api.routers.converter.replace._sync_material_matrix_after_rgb_change",
        # Real sync requires solving against materials — bypass it
        # because the cap-bumping logic runs AFTER sync and only depends
        # on matched_rgb's content.
        # 真 sync 需要真材料；cap 计算在 sync 之后只依赖 matched_rgb，
        # 所以这里直接跳过。
    ), patch(
        "api.routers.converter.replace.schedule_glb_build",
        side_effect=_capture_schedule,
    ):
        resp = client.post(
            "/api/convert/region-requantize",
            json={
                "session_id": session_id,
                "targets": [
                    {"gradient_group_index": 1, "gradient_region_index": 1}
                ],
                "local_quantize_colors": 64,
            },
        )

    assert resp.status_code == 200, resp.text

    cache = store.get(session_id)["preview_cache"]
    # The fake solver returns a unique colour per input, so the in-region
    # pixels now span up to 64 colours; combined with the two original
    # palette colours outside the region, the unique-count exceeds the
    # default 64 cap, which is exactly the production scenario this fix
    # addresses.
    # FakeSolver 每个输入返回唯一输出 → 区域内最多 64 新色 + 区域外 2 旧色，
    # 唯一色数大于默认 64，这正是修复场景。
    matched_rgb = np.asarray(cache["matched_rgb"])
    unique_count = int(np.unique(matched_rgb.reshape(-1, 3), axis=0).shape[0])
    assert unique_count > 64, (
        "test scaffolding precondition: matched_rgb after requantize must "
        "have more than 64 unique colours so the cap-bumping is observable"
    )

    cap = cache.get("glb_max_meshes")
    assert isinstance(cap, int), (
        "region-requantize must persist 'glb_max_meshes' so the GLB worker "
        "can override the default 64-mesh merge cap"
    )
    assert cap >= unique_count, (
        f"glb_max_meshes={cap} must be >= unique colour count "
        f"({unique_count}); otherwise low-frequency new colours from "
        f"local k-means get merged out of the segmented GLB"
    )

    # And the very same cache instance was handed to schedule_glb_build,
    # so the background worker reads the bumped cap.
    # schedule_glb_build 收到的同一份 cache，让后台 worker 看到新 cap。
    assert len(schedule_calls) == 1
    scheduled_cache = schedule_calls[0][1]
    assert scheduled_cache.get("glb_max_meshes") == cap


def test_requantize_refreshes_cache_color_palette(patched_dependencies):
    """``cache['color_palette']`` must be re-extracted after requantize.
    二次量化后 cache 内的 color_palette 必须按新 matched_rgb 重新提取，
    否则 /layer-images 等下游端点会按旧调色板循环，生成的分层图缺色。
    """
    client, session_id, store = patched_dependencies
    # Seed a stale palette that clearly could not be produced from the
    # post-requantize matched_rgb. If the route forgets to refresh, this
    # sentinel survives and the assertion fires.
    # 塞一条明显的陈旧调色板；若端点忘记刷新，断言就会命中。
    pre_cache = store.get(session_id)["preview_cache"]
    pre_cache["color_palette"] = [
        {"color": (1, 1, 1), "hex": "#010101", "count": 99999, "percentage": 100.0}
    ]
    store.put(session_id, "preview_cache", pre_cache)

    with patch(
        "api.routers.converter.replace.load_multiple_materials",
        return_value=[],
    ), patch(
        "api.routers.converter.replace.load_material_solver_cache_with_fallback",
        return_value=(_FakeSolverCache(), 64),
    ), patch(
        "api.routers.converter.replace._sync_material_matrix_after_rgb_change",
    ), patch(
        "api.routers.converter.replace.recompute_gradient_groups_into_session",
        return_value=[],
    ), patch(
        "api.routers.converter.replace.schedule_glb_build",
        return_value="fake-job-token",
    ):
        resp = client.post(
            "/api/convert/region-requantize",
            json={
                "session_id": session_id,
                "targets": [
                    {"gradient_group_index": 1, "gradient_region_index": 1}
                ],
                "local_quantize_colors": 32,
            },
        )

    assert resp.status_code == 200, resp.text
    cache = store.get(session_id)["preview_cache"]
    palette = cache.get("color_palette")
    assert isinstance(palette, list) and len(palette) > 0, (
        "color_palette must be refreshed from the post-requantize matched_rgb"
    )
    # The stale sentinel entry must not survive: its hex is #010101 and the
    # fake solver output cannot yield that value for this test image.
    # 检查哨兵条目被覆盖；FakeSolver 的输出决定了 #010101 不可能出现在新调色板。
    assert all(entry["hex"] != "#010101" for entry in palette), (
        "stale palette must be replaced, not merged"
    )
    # Every palette entry must expose the shape extract_color_palette produces
    # so downstream consumers (``/layer-images``) keep working.
    # 调色板结构必须与 extract_color_palette 输出一致，保证下游可直接消费。
    required_keys = {"color", "hex", "count", "percentage"}
    for entry in palette:
        assert required_keys.issubset(entry.keys()), (
            f"palette entry missing keys: {entry}"
        )


def test_requantize_response_carries_refreshed_gradient_groups(patched_dependencies):
    """Response must include refreshed ``gradient_groups`` after requantize.
    二次量化后响应应带回刷新的渐变分组，供前端立即更新面板。
    """
    client, session_id, store = patched_dependencies
    sentinel_groups = [
        {
            "group_index": 1,
            "total_pixel_count": 123,
            "material_colour_count": 2,
            "material_colours": [],
            "representative_hex": "#112233",
            "representative_rgb": [17, 34, 51],
            "boundary_pair_count": 1,
            "regions": [],
        }
    ]

    def _fake_recompute(cache, sid, store_):
        # Simulate the analyser running: write sentinel groups into
        # session and return them so the route can ship them back.
        # 模拟分析器：向 session 写入哨兵分组并作为返回值。
        store_.put(sid, "gradient_groups", sentinel_groups)
        return sentinel_groups

    with patch(
        "api.routers.converter.replace.load_multiple_materials",
        return_value=[],
    ), patch(
        "api.routers.converter.replace.load_material_solver_cache_with_fallback",
        return_value=(_FakeSolverCache(), 64),
    ), patch(
        "api.routers.converter.replace._sync_material_matrix_after_rgb_change",
    ), patch(
        "api.routers.converter.replace.recompute_gradient_groups_into_session",
        side_effect=_fake_recompute,
    ), patch(
        "api.routers.converter.replace.schedule_glb_build",
        return_value="fake-job-token",
    ):
        resp = client.post(
            "/api/convert/region-requantize",
            json={
                "session_id": session_id,
                "targets": [
                    {"gradient_group_index": 1, "gradient_region_index": 1}
                ],
                "local_quantize_colors": 32,
            },
        )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert "gradient_groups" in payload, (
        "response must expose the 'gradient_groups' field so the frontend "
        "can refresh the Gradient Groups panel in the same round-trip"
    )
    assert payload["gradient_groups"] == sentinel_groups


def test_requantize_response_passes_through_none_when_recompute_degrades(
    patched_dependencies,
):
    """If the analyser degrades the response ``gradient_groups`` must be null.
    分析器降级（返回 None）时响应字段应为 null，前端按此保留旧分组。
    """
    client, session_id, _store = patched_dependencies

    with patch(
        "api.routers.converter.replace.load_multiple_materials",
        return_value=[],
    ), patch(
        "api.routers.converter.replace.load_material_solver_cache_with_fallback",
        return_value=(_FakeSolverCache(), 64),
    ), patch(
        "api.routers.converter.replace._sync_material_matrix_after_rgb_change",
    ), patch(
        "api.routers.converter.replace.recompute_gradient_groups_into_session",
        return_value=None,
    ), patch(
        "api.routers.converter.replace.schedule_glb_build",
        return_value="fake-job-token",
    ):
        resp = client.post(
            "/api/convert/region-requantize",
            json={
                "session_id": session_id,
                "targets": [
                    {"gradient_group_index": 1, "gradient_region_index": 1}
                ],
                "local_quantize_colors": 32,
            },
        )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload.get("gradient_groups") is None


def test_requantize_unmapped_region_falls_back_to_group_pixels(patched_dependencies):
    """Targeting a region with no stamped pixels must still rewrite the group.
    点击分析器静默跳过的 region（``region_id_map`` 中无该编码像素）时，
    端点必须回退到整组像素并完成二次量化；否则 ``rewritten_pixels`` 始终
    为 0，``matched_rgb`` 不变，前端表现为"点了开始量化什么都不变"。
    """
    client, session_id, store = patched_dependencies
    pre_cache = store.get(session_id)["preview_cache"]
    matched_before = np.asarray(pre_cache["matched_rgb"]).copy()
    region_id_map = np.asarray(
        store.get(session_id)["gradient_region_id_map"]
    )
    # Sanity: the fixture stamps (group=1, region=1). Region 7 inside the
    # same group is intentionally absent — exactly the situation the
    # gradient analyser produces when it cannot resolve a region's CC label.
    # 前置条件：fixture 仅盖了 (1, 1)；(1, 7) 模拟分析器静默跳过的 region。
    encoded_seven = (
        1 * REGION_ID_ENCODING_MULTIPLIER + 7
    )
    assert not np.any(region_id_map == encoded_seven)

    with patch(
        "api.routers.converter.replace.load_multiple_materials",
        return_value=[],
    ), patch(
        "api.routers.converter.replace.load_material_solver_cache_with_fallback",
        return_value=(_FakeSolverCache(), 64),
    ), patch(
        "api.routers.converter.replace._sync_material_matrix_after_rgb_change",
    ), patch(
        "api.routers.converter.replace.recompute_gradient_groups_into_session",
        return_value=[],
    ), patch(
        "api.routers.converter.replace.schedule_glb_build",
        return_value="fake-job-token",
    ):
        resp = client.post(
            "/api/convert/region-requantize",
            json={
                "session_id": session_id,
                "targets": [
                    {"gradient_group_index": 1, "gradient_region_index": 7},
                ],
                "local_quantize_colors": 32,
            },
        )

    assert resp.status_code == 200, resp.text
    cache = store.get(session_id)["preview_cache"]
    matched_after = np.asarray(cache["matched_rgb"])
    # The whole (group=1) region — i.e. the central rectangle from the
    # fixture — must have been rewritten despite the request targeting an
    # unmapped (1, 7) pair.
    # 整组（中央矩形）的像素都应该被重写，证明端点正确走了 group 回退。
    group_mask = region_id_map == (1 * REGION_ID_ENCODING_MULTIPLIER + 1)
    assert int(np.any(matched_before[group_mask] != matched_after[group_mask])), (
        "group fallback must rewrite the parent group's pixels even when "
        "the targeted region itself has no stamped pixels"
    )
    # The on-disk session region_id_map must not be mutated — the route
    # is supposed to operate on a working copy only.
    # session 内的 region_id_map 不应被破坏，端点只在工作副本上盖章。
    region_id_map_after = np.asarray(
        store.get(session_id)["gradient_region_id_map"]
    )
    assert np.array_equal(region_id_map, region_id_map_after)


def test_requantize_does_not_lower_existing_cap(patched_dependencies):
    """A pre-existing higher cap must survive the second requantize call.
    已有更高 cap 时不应被覆盖回较小值，防止连续量化退化。
    """
    client, session_id, store = patched_dependencies
    # Pre-seed a high cap as if a previous edit already bumped it.
    # 模拟之前已有一次更高 cap 的设置。
    pre_cache = store.get(session_id)["preview_cache"]
    pre_cache["glb_max_meshes"] = 9999
    store.put(session_id, "preview_cache", pre_cache)

    with patch(
        "api.routers.converter.replace.load_multiple_materials",
        return_value=[],
    ), patch(
        "api.routers.converter.replace.load_material_solver_cache_with_fallback",
        return_value=(_FakeSolverCache(), 64),
    ), patch(
        "api.routers.converter.replace._sync_material_matrix_after_rgb_change",
    ), patch(
        "api.routers.converter.replace.schedule_glb_build",
        return_value="fake-job-token",
    ):
        resp = client.post(
            "/api/convert/region-requantize",
            json={
                "session_id": session_id,
                "targets": [
                    {"gradient_group_index": 1, "gradient_region_index": 1}
                ],
                "local_quantize_colors": 32,
            },
        )

    assert resp.status_code == 200, resp.text
    cache = store.get(session_id)["preview_cache"]
    assert cache["glb_max_meshes"] == 9999, (
        "existing higher glb_max_meshes must be preserved across "
        "subsequent requantize calls"
    )


class _FakeKmRuntime:
    """Idempotent candidate runtime used to verify the explicit KM adapter."""

    def __init__(self) -> None:
        self.lookup_calls = 0

    def lookup(self, target_srgb, _user_materials):
        self.lookup_calls += 1
        colors = np.asarray(target_srgb, dtype=np.uint8).copy()
        recipes = np.ones((colors.shape[0], 1), dtype=np.int32)
        delta_e = np.zeros(colors.shape[0], dtype=np.float64)
        return colors, recipes, delta_e


def _seed_lumina_region_session(store: SessionStore, session_id: str) -> None:
    store.put(session_id, "material_profile_kind", "lumina_box")
    cache = store.get(session_id)["preview_cache"]
    h, w = np.asarray(cache["matched_rgb"]).shape[:2]
    cache["material_matrix"] = np.full((h, w, 1), 7, dtype=np.uint8)
    store.put(session_id, "preview_cache", cache)


def test_lumina_region_uses_candidate_runtime_and_persists_matching_matrix(
    patched_dependencies,
):
    client, session_id, store = patched_dependencies
    _seed_lumina_region_session(store, session_id)
    runtime = _FakeKmRuntime()
    materials = [SimpleNamespace(), SimpleNamespace()]
    before = np.asarray(store.get(session_id)["preview_cache"]["matched_rgb"]).copy()

    with patch(
        "api.routers.converter.replace.load_and_validate_material_archive_profile",
        return_value=("lumina_box", materials),
    ), patch(
        "api.routers.converter.replace.load_persisted_candidate_runtime_with_fallback",
        return_value=runtime,
    ) as runtime_loader, patch(
        "api.routers.converter.replace.load_material_solver_cache_with_fallback",
        side_effect=AssertionError("Lumina Box must not load the affine cache"),
    ), patch(
        "api.routers.converter.replace.recompute_gradient_groups_into_session",
        return_value=[],
    ), patch(
        "api.routers.converter.replace.schedule_glb_build",
        return_value="fake-job-token",
    ):
        response = client.post(
            "/api/convert/region-requantize",
            json=_region_requantize_payload(session_id),
        )

    assert response.status_code == 200, response.text
    runtime_loader.assert_called_once()
    assert runtime.lookup_calls == 2  # region color lookup + matrix recipe sync
    stored_cache = store.get(session_id)["preview_cache"]
    after = np.asarray(stored_cache["matched_rgb"])
    changed = np.any(after != before, axis=-1)
    assert np.any(changed)
    material_matrix = np.asarray(stored_cache["material_matrix"])
    assert material_matrix.shape[2] == 1
    assert np.all(material_matrix[changed, 0] == 1)


def test_lumina_region_missing_runtime_returns_409_without_mutation(
    patched_dependencies,
):
    client, session_id, store = patched_dependencies
    _seed_lumina_region_session(store, session_id)
    before_cache = store.get(session_id)["preview_cache"]
    before_rgb = np.asarray(before_cache["matched_rgb"]).copy()
    before_matrix = np.asarray(before_cache["material_matrix"]).copy()

    with patch(
        "api.routers.converter.replace.load_and_validate_material_archive_profile",
        return_value=("lumina_box", [SimpleNamespace(), SimpleNamespace()]),
    ), patch(
        "api.routers.converter.replace.load_persisted_candidate_runtime_with_fallback",
        return_value=None,
    ), patch(
        "api.routers.converter.replace.schedule_glb_build",
    ) as schedule:
        response = client.post(
            "/api/convert/region-requantize",
            json=_region_requantize_payload(session_id),
        )

    assert response.status_code == 409
    assert "Build the Lumina Box candidate runtime" in response.json()["detail"]
    schedule.assert_not_called()
    after_cache = store.get(session_id)["preview_cache"]
    np.testing.assert_array_equal(after_cache["matched_rgb"], before_rgb)
    np.testing.assert_array_equal(after_cache["material_matrix"], before_matrix)


def test_lumina_region_session_profile_mismatch_returns_422(
    patched_dependencies,
):
    client, session_id, store = patched_dependencies
    _seed_lumina_region_session(store, session_id)
    seen_profile: list[str] = []

    def _reject(_names, *, profile_kind):
        seen_profile.append(str(profile_kind))
        raise MaterialArchiveProfileError("Selected archive is Stage A")

    with patch(
        "api.routers.converter.replace.load_and_validate_material_archive_profile",
        side_effect=_reject,
    ), patch(
        "api.routers.converter.replace.load_persisted_candidate_runtime_with_fallback",
    ) as runtime_loader:
        response = client.post(
            "/api/convert/region-requantize",
            json=_region_requantize_payload(session_id),
        )

    assert seen_profile == ["lumina_box"]
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "material_profile_kind_mismatch"
    runtime_loader.assert_not_called()


def test_lumina_region_catalog_failure_rolls_back_transaction(
    patched_dependencies,
):
    client, session_id, store = patched_dependencies
    _seed_lumina_region_session(store, session_id)
    before_cache = store.get(session_id)["preview_cache"]
    before_rgb = np.asarray(before_cache["matched_rgb"]).copy()
    before_matrix = np.asarray(before_cache["material_matrix"]).copy()

    def _fail_sync(_session_data, cache, *_args, **_kwargs):
        cache["material_matrix"][...] = 9
        raise ValueError("candidate catalog sync failed")

    with patch(
        "api.routers.converter.replace.load_and_validate_material_archive_profile",
        return_value=("lumina_box", [SimpleNamespace(), SimpleNamespace()]),
    ), patch(
        "api.routers.converter.replace.load_persisted_candidate_runtime_with_fallback",
        return_value=_FakeKmRuntime(),
    ), patch(
        "api.routers.converter.replace._sync_material_matrix_after_rgb_change",
        side_effect=_fail_sync,
    ), patch(
        "api.routers.converter.replace.schedule_glb_build",
    ) as schedule:
        response = client.post(
            "/api/convert/region-requantize",
            json=_region_requantize_payload(session_id),
        )

    assert response.status_code >= 400
    schedule.assert_not_called()
    after_cache = store.get(session_id)["preview_cache"]
    np.testing.assert_array_equal(after_cache["matched_rgb"], before_rgb)
    np.testing.assert_array_equal(after_cache["material_matrix"], before_matrix)
