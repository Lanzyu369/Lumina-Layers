"""Regression: recipe overrides must survive editor-selection lifecycle.

复现路径：选区（__editor_selection__:<rev> 合成 region id）→
apply-recipe-override → 前端自动清空选区（合成 id 从
selected_region_masks 清理）→ /generate 重新套用覆盖时必须仍能解析掩码。
修复方式：apply 端点把当时使用的掩码位压缩快照进会话键
``recipe_override_applied_masks``，generate/puzzle 以快照为最高优先级解析
（实时选区与 select-all 重算仅服务旧会话），撤销/重做与重置同步维护。
"""
import pickle
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.selection_state import (
    RECIPE_OVERRIDE_APPLIED_MASKS_KEY,
    pack_applied_region_mask,
    unpack_applied_region_mask,
)
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager

client = TestClient(app)


def _make_mock_pool() -> MagicMock:
    pool = MagicMock(spec=WorkerPoolManager)

    async def _timed_submit(*args, **kwargs):
        return await pool.submit(*args, **kwargs), {}

    pool.submit = AsyncMock()
    pool.submit_timed = AsyncMock(side_effect=_timed_submit)
    return pool


@pytest.fixture(autouse=True)
def _iso(monkeypatch):
    store = SessionStore()
    registry = FileRegistry()
    pool = _make_mock_pool()
    # Apply/reset endpoints schedule async GLB rebuilds whose cache commits
    # can race the undo/redo requests below (flaky 409s). The lifecycle under
    # test here is the override/mask state, not GLB, so stub it out.
    # apply/reset 端点会调度异步 GLB 重建，其缓存提交可能与下方撤销/重做
    # 请求竞态（偶发 409）。本文件验证的是覆盖/掩码生命周期而非 GLB，
    # 直接置空。
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *args, **kwargs: None,
    )
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: pool
    try:
        yield {"store": store, "registry": registry, "pool": pool}
    finally:
        app.dependency_overrides.pop(get_session_store, None)
        app.dependency_overrides.pop(get_file_registry, None)
        app.dependency_overrides.pop(get_worker_pool, None)


def _seed_material_archive_session(store: SessionStore) -> str:
    """Material-archive preview like the recipe override tests use."""
    session_id = store.create()
    matched_rgb = np.full((6, 6, 3), [250, 250, 250], dtype=np.uint8)
    matched_rgb[:3, :3] = [255, 0, 0]
    mask_solid = np.ones((6, 6), dtype=bool)
    material_matrix = np.zeros((6, 6, 3), dtype=np.int32)
    material_matrix[:, :, :] = [0, 1, 0]
    store.put(session_id, "preview_cache", {
        "matched_rgb": matched_rgb.copy(),
        "quantized_image": matched_rgb.copy(),
        "mask_solid": mask_solid,
        "material_matrix": material_matrix,
        "color_layers": 3,
        "layer_height_mm": 0.08,
        "preview_colors": {
            0: [250, 250, 250, 255],
            1: [220, 40, 80, 255],
        },
        "slot_names": ["fake/A", "fake/B"],
        "target_w": 6,
        "target_h": 6,
        "target_width_mm": 60.0,
    })
    store.put(session_id, "material_source", "material_archive")
    store.put(session_id, "selected_materials", ["fake/A", "fake/B"])
    # A completed preview has already resolved its backing channel. Keep this
    # fixture independent of a machine's material library during generation.
    store.put(session_id, "material_backing_material_index", 0)
    store.put(session_id, "material_layer_count", 3)
    store.put(session_id, "material_layer_height_mm", 0.08)
    store.put(session_id, "lut_name", "__material_archive__")
    store.put(session_id, "lut_path", "__material_archive__")
    return session_id


def _select_red_region(client: TestClient, sid: str) -> list[str]:
    resp = client.post("/api/convert/selection/mutate", json={
        "session_id": sid,
        "operation": "same-color-toggle",
        "base_selection_revision": 0,
        "content_revision": 0,
        "color_hex": "ff0000",
    })
    assert resp.status_code == 200, resp.text
    region_ids = resp.json()["region_ids"]
    assert len(region_ids) >= 1, resp.json()
    return region_ids


def _apply_recipe_override(client: TestClient, sid: str, region_ids: list[str]):
    return client.post("/api/convert/apply-recipe-override", json={
        "session_id": sid,
        "region_ids": region_ids,
        "recipe": [0, 1, 0],
        "layer_height_mm": 0.08,
        "color_layers": 3,
        "layer_order": "Top2Bottom",
    })


def test_apply_persists_bitpacked_applied_mask_snapshot(_iso):
    """apply-recipe-override 快照本次使用的区域掩码（位压缩存储）。"""
    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_ids = _select_red_region(client, sid)

    resp = _apply_recipe_override(client, sid, region_ids)
    assert resp.status_code == 200, resp.text

    session_data = store.get(sid)
    snapshot = session_data.get(RECIPE_OVERRIDE_APPLIED_MASKS_KEY)
    assert isinstance(snapshot, dict), session_data.keys()
    for region_id in region_ids:
        entry = snapshot.get(region_id)
        # Packed format: shape metadata + ceil(H*W/8) uint8 bytes keeps the
        # per-checkpoint history clone small on large images.
        # 打包格式：shape 元数据 + ceil(H*W/8) 字节，控制大图下历史克隆的
        # 内存占用。
        assert isinstance(entry, dict), (region_id, entry)
        assert entry["shape"] == [6, 6]
        packed = entry["packed"]
        assert isinstance(packed, np.ndarray)
        assert packed.dtype == np.dtype(np.uint8)
        assert packed.size == (6 * 6 + 7) // 8
        restored = unpack_applied_region_mask(entry)
        assert restored is not None and np.any(restored)
        # The restored snapshot matches the live synthetic selection mask at
        # apply time.
        live = (session_data.get("selected_region_masks") or {}).get(region_id)
        assert live is not None
        np.testing.assert_array_equal(restored, np.asarray(live, dtype=bool))


def test_generate_resolves_override_after_selection_cleared(_iso):
    """核心回归：清空选区后 generate 仍能从快照解析覆盖掩码。

    用户操作序列：选区 → 应用颜色替换（apply 成功后前端自动 clear）→
    生成模型。修复前第三步报 422 "Region mask not found for recipe
    override: __editor_selection__:<rev>"。
    """
    from api.routers.converter.generate import (
        _prepare_recipe_override_worker_inputs,
    )
    from api.schemas.converter import ConvertGenerateRequest

    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_ids = _select_red_region(client, sid)

    resp = _apply_recipe_override(client, sid, region_ids)
    assert resp.status_code == 200, resp.text

    cleared = client.post("/api/convert/selection/mutate", json={
        "session_id": sid,
        "operation": "clear",
        "base_selection_revision": 1,
        "content_revision": 0,
    })
    assert cleared.status_code == 200, cleared.text

    # Simulate exactly what broke: the synthetic region id is gone from the
    # live selection state while the override still references it.
    # 复现故障状态：实时选区已不含该合成 id，但覆盖记录仍引用它。
    session_data = store.get(sid)
    live_masks = session_data.get("selected_region_masks") or {}
    for region_id in region_ids:
        assert region_id not in live_masks

    request = ConvertGenerateRequest(
        lut_name="__material_archive__",
        color_layers=3,
        recipe_overrides=[
            {
                "region_id": region_ids[0],
                "recipe": [0, 1, 0],
                "layer_order": "Top2Bottom",
            }
        ],
    )
    mm_path, masks_path = _prepare_recipe_override_worker_inputs(
        cache=session_data.get("preview_cache"),
        session_data=session_data,
        recipe_overrides=[
            {
                "region_id": region_ids[0],
                "recipe": [0, 1, 0],
                "layer_order": "Top2Bottom",
            }
        ],
        request=request,
        sid=sid,
        store=store,
    )
    assert mm_path is not None
    assert masks_path is not None

    with open(masks_path, "rb") as mask_file:
        saved_masks = pickle.load(mask_file)
    assert region_ids[0] in saved_masks
    assert np.any(saved_masks[region_ids[0]])
    # The override must land on exactly the snapshotted footprint.
    # 覆盖必须精确落在快照掩码的像素足迹上。
    written_matrix = np.load(mm_path)
    expected_snapshot = unpack_applied_region_mask(
        store.get(sid)[RECIPE_OVERRIDE_APPLIED_MASKS_KEY][region_ids[0]]
    )
    np.testing.assert_array_equal(saved_masks[region_ids[0]], expected_snapshot)
    np.testing.assert_array_equal(
        written_matrix[expected_snapshot],
        np.tile(np.array([0, 1, 0], dtype=written_matrix.dtype), (int(expected_snapshot.sum()), 1)),
    )
    store.close(sid)


def test_generate_route_uses_snapshot_footprint_end_to_end(_iso, tmp_path, monkeypatch):
    """API 级回归：替换→清空选区→/generate 全链路按快照足迹套用配方。

    直接调用内部 helper 的单测无法证明真实路由装配；本用例走
    POST /api/convert/generate（mock worker 池），校验提交给 worker 的
    掩码与材料矩阵都精确等于 apply 时快照的足迹。
    """
    store = _iso["store"]
    pool = _iso["pool"]
    sid = _seed_material_archive_session(store)
    # The synthetic material archive has no on-disk catalog; keep material
    # preflight isolated while exercising the real snapshot-to-worker handoff.
    monkeypatch.setattr(
        "api.routers.converter.generate.require_material_selection",
        lambda *args, **kwargs: {"ready": True},
    )

    image_path = tmp_path / "input.png"
    out_path = tmp_path / "out.3mf"
    Image.fromarray(np.zeros((6, 6, 3), dtype=np.uint8)).save(image_path)
    out_path.write_bytes(b"3mf")
    store.put(sid, "image_path", str(image_path))
    store.put(sid, "replacement_regions", [])
    store.put(sid, "free_color_set", set())

    region_ids = _select_red_region(client, sid)
    resp = _apply_recipe_override(client, sid, region_ids)
    assert resp.status_code == 200, resp.text
    cleared = client.post("/api/convert/selection/mutate", json={
        "session_id": sid,
        "operation": "clear",
        "base_selection_revision": 1,
        "content_revision": 0,
    })
    assert cleared.status_code == 200, cleared.text

    pool.submit = AsyncMock(return_value={
        "threemf_path": str(out_path),
        "glb_path": None,
        "status_msg": "OK",
    })

    response = client.post("/api/convert/generate", json={
        "session_id": sid,
        "params": {
            "lut_name": "__material_archive__",
            "modeling_mode": "vector",
            "target_width_mm": 113,
            "spacer_thick": 0.24,
            "structure_mode": "Single-sided",
            "color_layers": 3,
            "layer_height_mm": 0.08,
            "separate_backing": True,
            "recipe_overrides": [{
                "region_id": region_ids[0],
                "recipe": [0, 1, 0],
                "layer_order": "Top2Bottom",
            }],
        },
    })

    assert response.status_code == 200, response.text
    submitted_params = pool.submit.call_args.args[3]
    assert submitted_params["recipe_override_masks_path"] is not None
    with open(submitted_params["recipe_override_masks_path"], "rb") as f:
        masks = pickle.load(f)
    assert masks.keys() == {region_ids[0]}
    expected_snapshot = unpack_applied_region_mask(
        store.get(sid)[RECIPE_OVERRIDE_APPLIED_MASKS_KEY][region_ids[0]]
    )
    np.testing.assert_array_equal(masks[region_ids[0]], expected_snapshot)
    material_matrix = np.load(submitted_params["material_matrix_path"])
    np.testing.assert_array_equal(
        material_matrix[expected_snapshot],
        np.tile(np.array([0, 1, 0], dtype=material_matrix.dtype), (int(expected_snapshot.sum()), 1)),
    )


def test_snapshot_wins_over_select_all_recompute(_iso):
    """/generate 的已提交覆盖必须使用 apply 时快照，而非按新像素重算。

    select-all 区域 id 在旧顺序下会用当前 matched_rgb 重算足迹；若 apply
    之后可见内容变化（同色像素位置改变），重算结果会偏离用户确认时的
    足迹。快照优先保证生成与预览所见一致。
    """
    from api.routers.converter.generate import (
        _prepare_recipe_override_worker_inputs,
    )
    from api.schemas.converter import ConvertGenerateRequest

    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_id = "__select_all_color__:ff0000"

    # Snapshot says bottom-right block; a fresh select-all recomputation on
    # the seeded matched_rgb would answer top-left [:3,:3] instead.
    # 快照记录右下块；若按种子图重算 select-all 会得到左上 [:3,:3]。
    committed_mask = np.zeros((6, 6), dtype=bool)
    committed_mask[4:, 4:] = True
    session_data = store.get(sid)
    session_data[RECIPE_OVERRIDE_APPLIED_MASKS_KEY] = {
        region_id: pack_applied_region_mask(committed_mask),
    }

    request = ConvertGenerateRequest(
        lut_name="__material_archive__",
        color_layers=3,
        recipe_overrides=[{
            "region_id": region_id,
            "recipe": [1, 0, 1],
            "layer_order": "Top2Bottom",
        }],
    )
    mm_path, _masks_path = _prepare_recipe_override_worker_inputs(
        cache=session_data.get("preview_cache"),
        session_data=session_data,
        recipe_overrides=[{
            "region_id": region_id,
            "recipe": [1, 0, 1],
            "layer_order": "Top2Bottom",
        }],
        request=request,
        sid=sid,
        store=store,
    )
    assert mm_path is not None
    written_matrix = np.load(mm_path)
    # Committed footprint got the user recipe…
    # 已提交足迹被套上用户配方……
    np.testing.assert_array_equal(
        written_matrix[committed_mask],
        np.tile(np.array([1, 0, 1], dtype=written_matrix.dtype), (int(committed_mask.sum()), 1)),
    )
    # …while the drifted recompute zone kept its original stack.
    # ……而已漂移的重算区保持原堆叠不被误改。
    drifted_zone = np.zeros((6, 6), dtype=bool)
    drifted_zone[:3, :3] = True
    np.testing.assert_array_equal(
        written_matrix[drifted_zone],
        np.tile(np.array([0, 1, 0], dtype=written_matrix.dtype), (int(drifted_zone.sum()), 1)),
    )
    store.close(sid)


def test_legacy_raw_array_snapshot_still_resolvable(_iso):
    """位压缩上线前的旧会话（裸布尔数组）无需迁移即可继续生成。"""
    from api.routers.converter.generate import (
        _prepare_recipe_override_worker_inputs,
    )
    from api.schemas.converter import ConvertGenerateRequest

    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_id = "__editor_selection__:3"
    legacy_mask = np.zeros((6, 6), dtype=bool)
    legacy_mask[1:4, 1:4] = True
    session_data = store.get(sid)
    session_data[RECIPE_OVERRIDE_APPLIED_MASKS_KEY] = {region_id: legacy_mask}

    request = ConvertGenerateRequest(
        lut_name="__material_archive__",
        color_layers=3,
        recipe_overrides=[{
            "region_id": region_id,
            "recipe": [1, 0, 1],
            "layer_order": "Top2Bottom",
        }],
    )
    mm_path, masks_path = _prepare_recipe_override_worker_inputs(
        cache=session_data.get("preview_cache"),
        session_data=session_data,
        recipe_overrides=[{
            "region_id": region_id,
            "recipe": [1, 0, 1],
            "layer_order": "Top2Bottom",
        }],
        request=request,
        sid=sid,
        store=store,
    )
    assert mm_path is not None and masks_path is not None
    written_matrix = np.load(mm_path)
    np.testing.assert_array_equal(
        written_matrix[legacy_mask],
        np.tile(np.array([1, 0, 1], dtype=written_matrix.dtype), (int(legacy_mask.sum()), 1)),
    )
    store.close(sid)


def test_generate_without_snapshot_still_raises_422(_iso):
    """未知 region id 且无快照时保持确定性 422。"""
    from api.routers.converter.generate import (
        _prepare_recipe_override_worker_inputs,
    )
    from api.schemas.converter import ConvertGenerateRequest

    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    session_data = store.get(sid)

    request = ConvertGenerateRequest(
        lut_name="__material_archive__",
        color_layers=3,
        recipe_overrides=[{
            "region_id": "__editor_selection__:99",
            "recipe": [0, 1, 0],
            "layer_order": "Top2Bottom",
        }],
    )
    with pytest.raises(HTTPException) as excinfo:
        _prepare_recipe_override_worker_inputs(
            cache=session_data.get("preview_cache"),
            session_data=session_data,
            recipe_overrides=[{
                "region_id": "__editor_selection__:99",
                "recipe": [0, 1, 0],
                "layer_order": "Top2Bottom",
            }],
            request=request,
            sid=sid,
            store=store,
        )
    assert excinfo.value.status_code == 422
    assert "__editor_selection__:99" in str(excinfo.value.detail)
    store.close(sid)


def test_snapshot_shape_mismatch_is_rejected(_iso):
    """快照形状与当前 material_matrix 不符时必须拒绝，不能静默套错位置。"""
    from api.routers.converter.generate import (
        _prepare_recipe_override_worker_inputs,
    )
    from api.schemas.converter import ConvertGenerateRequest

    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_id = "__editor_selection__:3"
    session_data = store.get(sid)
    session_data[RECIPE_OVERRIDE_APPLIED_MASKS_KEY] = {
        region_id: np.ones((8, 10), dtype=bool),
    }

    request = ConvertGenerateRequest(
        lut_name="__material_archive__",
        color_layers=3,
        recipe_overrides=[{
            "region_id": region_id,
            "recipe": [0, 1, 0],
            "layer_order": "Top2Bottom",
        }],
    )
    with pytest.raises(HTTPException) as excinfo:
        _prepare_recipe_override_worker_inputs(
            cache=session_data.get("preview_cache"),
            session_data=session_data,
            recipe_overrides=[{
                "region_id": region_id,
                "recipe": [0, 1, 0],
                "layer_order": "Top2Bottom",
            }],
            request=request,
            sid=sid,
            store=store,
        )
    assert excinfo.value.status_code == 422
    assert region_id in str(excinfo.value.detail)
    store.close(sid)


def test_reset_replacements_clears_applied_mask_snapshot(_iso):
    """重置替换必须连同快照一起清空，避免旧掩码无限期驻留会话。"""
    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_ids = _select_red_region(client, sid)

    resp = _apply_recipe_override(client, sid, region_ids)
    assert resp.status_code == 200, resp.text
    assert store.get(sid).get(RECIPE_OVERRIDE_APPLIED_MASKS_KEY)

    reset = client.post("/api/convert/reset-replacements", json={"session_id": sid})
    assert reset.status_code == 200, reset.text
    assert store.get(sid).get(RECIPE_OVERRIDE_APPLIED_MASKS_KEY) == {}


def test_new_preview_clears_overrides_and_applied_mask_snapshot(_iso):
    """新预览必须连同配方覆盖与掩码快照一起重置。

    同一会话换图重新预览时（标准 LUT 尺寸下新旧图片尺寸常常相同），若
    快照残留，generate 会把旧覆盖静默套到新图上；必须随
    clear_replacement_history 一并清空，让后续生成确定性失败并提示重新替换。
    """
    from api.replacement_history import clear_replacement_history

    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_ids = _select_red_region(client, sid)

    resp = _apply_recipe_override(client, sid, region_ids)
    assert resp.status_code == 200, resp.text
    seeded = store.get(sid)
    assert seeded.get("recipe_overrides")
    assert seeded.get(RECIPE_OVERRIDE_APPLIED_MASKS_KEY)

    # New previews funnel through clear_replacement_history (preview.py).
    clear_replacement_history(sid, store)

    fresh = store.get(sid)
    assert fresh.get("recipe_overrides") == []
    assert fresh.get("recipe_override_count") == 0
    assert fresh.get(RECIPE_OVERRIDE_APPLIED_MASKS_KEY) == {}
    assert not fresh.get("editor_selection_mask")


def test_corrupt_snapshot_with_live_mask_must_not_drift(_iso):
    """复审复现 1：快照存在但损坏时不得静默退回可变实时选区。

    会话已具备快照能力（dict 非空）且该覆盖条目损坏（形状不符）时，即使
    实时选区仍能解析出同 id 掩码，也必须确定性 422，而不是把配方套到
    "后来变化过的几何"上造成足迹漂移。
    """
    from api.routers.converter.generate import (
        _prepare_recipe_override_worker_inputs,
    )
    from api.schemas.converter import ConvertGenerateRequest

    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_id = "__editor_selection__:7"
    session_data = store.get(sid)
    session_data[RECIPE_OVERRIDE_APPLIED_MASKS_KEY] = {
        region_id: pack_applied_region_mask(np.ones((5, 5), dtype=bool)),
    }
    drifted_live = np.zeros((6, 6), dtype=bool)
    drifted_live[0, :4] = True
    session_data["selected_region_masks"] = {region_id: drifted_live}

    request = ConvertGenerateRequest(
        lut_name="__material_archive__",
        color_layers=3,
        recipe_overrides=[{
            "region_id": region_id,
            "recipe": [1, 0, 1],
            "layer_order": "Top2Bottom",
        }],
    )
    overrides = [{
        "region_id": region_id,
        "recipe": [1, 0, 1],
        "layer_order": "Top2Bottom",
    }]
    with patch("api.routers.converter.generate.log.warning") as warning_mock:
        with pytest.raises(HTTPException) as excinfo:
            _prepare_recipe_override_worker_inputs(
                cache=session_data.get("preview_cache"),
                session_data=session_data,
                recipe_overrides=overrides,
                request=request,
                sid=sid,
                store=store,
            )
    assert excinfo.value.status_code == 422
    assert region_id in str(excinfo.value.detail)
    warning_mock.assert_called_once()
    log_message = warning_mock.call_args.args[0]
    log_fields = warning_mock.call_args.kwargs["extra"]
    assert "falling back" not in log_message.lower()
    assert log_fields.get("fallback_action") != "use_live_region_state"
    assert log_fields["recovery_action"] == "reapply_color_replacement"
    store.close(sid)


def test_missing_entry_in_capable_snapshot_dict_is_rejected(_iso):
    """复审复现 1b：具备快照能力的会话中条目缺失同样确定性拒绝。

    非原子多写窗口可能产生"有快照键但缺该覆盖条目"的会话；此时静默回退
    到实时选区会漂移足迹，必须报错要求重新替换。
    """
    from api.routers.converter.generate import (
        _prepare_recipe_override_worker_inputs,
    )
    from api.schemas.converter import ConvertGenerateRequest

    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_id = "__editor_selection__:7"
    other_region = "__editor_selection__:8"
    session_data = store.get(sid)
    other_mask = np.zeros((6, 6), dtype=bool)
    other_mask[5, 5] = True
    session_data[RECIPE_OVERRIDE_APPLIED_MASKS_KEY] = {
        other_region: pack_applied_region_mask(other_mask),
    }
    live_mask = np.zeros((6, 6), dtype=bool)
    live_mask[0, :4] = True
    session_data["selected_region_masks"] = {region_id: live_mask}

    request = ConvertGenerateRequest(
        lut_name="__material_archive__",
        color_layers=3,
        recipe_overrides=[{
            "region_id": region_id,
            "recipe": [1, 0, 1],
            "layer_order": "Top2Bottom",
        }],
    )
    with pytest.raises(HTTPException) as excinfo:
        _prepare_recipe_override_worker_inputs(
            cache=session_data.get("preview_cache"),
            session_data=session_data,
            recipe_overrides=[{
                "region_id": region_id,
                "recipe": [1, 0, 1],
                "layer_order": "Top2Bottom",
            }],
            request=request,
            sid=sid,
            store=store,
        )
    assert excinfo.value.status_code == 422
    store.close(sid)


@pytest.mark.parametrize(
    "snapshot_container",
    [{}, None, "corrupt-container"],
    ids=["empty", "none", "corrupt"],
)
def test_present_snapshot_key_never_falls_back_to_live_mask(
    _iso,
    snapshot_container,
):
    """Modern sessions reject unusable snapshot containers instead of drifting."""
    from api.routers.converter.generate import (
        _prepare_recipe_override_worker_inputs,
    )
    from api.schemas.converter import ConvertGenerateRequest

    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_id = "__editor_selection__:7"
    session_data = store.get(sid)
    session_data[RECIPE_OVERRIDE_APPLIED_MASKS_KEY] = snapshot_container
    live_mask = np.zeros((6, 6), dtype=bool)
    live_mask[0, :4] = True
    session_data["selected_region_masks"] = {region_id: live_mask}
    overrides = [{
        "region_id": region_id,
        "recipe": [1, 0, 1],
        "layer_order": "Top2Bottom",
    }]
    request = ConvertGenerateRequest(
        lut_name="__material_archive__",
        color_layers=3,
        recipe_overrides=overrides,
    )

    with pytest.raises(HTTPException) as excinfo:
        _prepare_recipe_override_worker_inputs(
            cache=session_data.get("preview_cache"),
            session_data=session_data,
            recipe_overrides=overrides,
            request=request,
            sid=sid,
            store=store,
        )

    assert excinfo.value.status_code == 422
    assert region_id in str(excinfo.value.detail)
    store.close(sid)


def test_legacy_session_without_snapshot_key_still_uses_live_mask(_iso):
    """Only sessions that truly predate the snapshot key keep live-mask fallback."""
    from api.routers.converter.generate import (
        _prepare_recipe_override_worker_inputs,
    )
    from api.schemas.converter import ConvertGenerateRequest

    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_id = "__editor_selection__:7"
    session_data = store.get(sid)
    assert RECIPE_OVERRIDE_APPLIED_MASKS_KEY not in session_data
    live_mask = np.zeros((6, 6), dtype=bool)
    live_mask[0, :4] = True
    session_data["selected_region_masks"] = {region_id: live_mask}
    overrides = [{
        "region_id": region_id,
        "recipe": [1, 0, 1],
        "layer_order": "Top2Bottom",
    }]
    request = ConvertGenerateRequest(
        lut_name="__material_archive__",
        color_layers=3,
        recipe_overrides=overrides,
    )

    _matrix_path, masks_path = _prepare_recipe_override_worker_inputs(
        cache=session_data.get("preview_cache"),
        session_data=session_data,
        recipe_overrides=overrides,
        request=request,
        sid=sid,
        store=store,
    )

    assert masks_path is not None
    with open(masks_path, "rb") as mask_file:
        saved_masks = pickle.load(mask_file)
    np.testing.assert_array_equal(saved_masks[region_id], live_mask)
    store.close(sid)


def test_snapshot_capability_does_not_reinflate_into_session_store(_iso):
    """复审复现 2：解包后的快照不得写回会话共享字典重新膨胀。

    打包条目在首次生成后若以裸布尔数组形式出现在
    selected_region_masks 中，内存版会话将永久持有放大后的数据。
    """
    from api.routers.converter.generate import (
        _prepare_recipe_override_worker_inputs,
    )
    from api.schemas.converter import ConvertGenerateRequest

    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_ids = _select_red_region(client, sid)

    resp = _apply_recipe_override(client, sid, region_ids)
    assert resp.status_code == 200, resp.text
    cleared = client.post("/api/convert/selection/mutate", json={
        "session_id": sid,
        "operation": "clear",
        "base_selection_revision": 1,
        "content_revision": 0,
    })
    assert cleared.status_code == 200, cleared.text
    # Mirror the production failure sequence: the synthetic id is gone from
    # live state before generate runs.
    # 复刻生产故障序列：生成前实时状态里已没有合成 id。
    assert region_ids[0] not in (
        store.get(sid).get("selected_region_masks") or {}
    )

    session_data = store.get(sid)
    request = ConvertGenerateRequest(
        lut_name="__material_archive__",
        color_layers=3,
        recipe_overrides=[{
            "region_id": region_ids[0],
            "recipe": [0, 1, 0],
            "layer_order": "Top2Bottom",
        }],
    )
    mm_path, masks_path = _prepare_recipe_override_worker_inputs(
        cache=session_data.get("preview_cache"),
        session_data=session_data,
        recipe_overrides=[{
            "region_id": region_ids[0],
            "recipe": [0, 1, 0],
            "layer_order": "Top2Bottom",
        }],
        request=request,
        sid=sid,
        store=store,
    )
    assert mm_path is not None and masks_path is not None
    # Worker inputs still carry the exact committed footprint…
    # worker 输入仍携带精确的已提交足迹……
    with open(masks_path, "rb") as mask_file:
        saved_masks = pickle.load(mask_file)
    expected = unpack_applied_region_mask(
        store.get(sid)[RECIPE_OVERRIDE_APPLIED_MASKS_KEY][region_ids[0]]
    )
    np.testing.assert_array_equal(saved_masks[region_ids[0]], expected)
    # …but the shared selection-state dict never gains the raw array back.
    # ……但共享选区状态字典不会重新出现裸布尔数组。
    assert region_ids[0] not in (
        store.get(sid).get("selected_region_masks") or {}
    )
    store.close(sid)


def test_history_budget_counts_session_field_arrays(_iso):
    """历史字节预算必须计入 session_fields 内的数组（含打包掩码）。"""
    from api.replacement_history import (
        _stack_artifact_nbytes,
        snapshot_replacement_state,
    )

    mask = np.zeros((32, 32), dtype=bool)
    mask[:16, :] = True
    checkpoint = snapshot_replacement_state(
        {
            RECIPE_OVERRIDE_APPLIED_MASKS_KEY: {"r1": pack_applied_region_mask(mask)},
        },
        label="budget_probe",
        include_preview_cache=False,
    )
    expected_packed_bytes = ((32 * 32) // 8) * 1
    assert checkpoint["session_fields_nbytes"] >= expected_packed_bytes
    assert _stack_artifact_nbytes([checkpoint]) >= expected_packed_bytes


def test_undo_redo_keeps_snapshot_in_sync_with_overrides(_iso):
    """撤销/重做时快照随 recipe_overrides 一起恢复。"""
    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_ids = _select_red_region(client, sid)

    resp = _apply_recipe_override(client, sid, region_ids)
    assert resp.status_code == 200, resp.text
    snapshot_after_apply = store.get(sid).get(RECIPE_OVERRIDE_APPLIED_MASKS_KEY)
    assert region_ids[0] in snapshot_after_apply

    undo = client.post("/api/convert/replacement-history", json={
        "session_id": sid, "action": "undo",
    })
    assert undo.status_code == 200, undo.text
    undone = store.get(sid)
    assert undone.get("recipe_overrides") == []
    assert undone.get(RECIPE_OVERRIDE_APPLIED_MASKS_KEY) == {}

    redo = client.post("/api/convert/replacement-history", json={
        "session_id": sid, "action": "redo",
    })
    assert redo.status_code == 200, redo.text
    redone = store.get(sid)
    restored_snapshot = redone.get(RECIPE_OVERRIDE_APPLIED_MASKS_KEY)
    assert region_ids[0] in restored_snapshot
    np.testing.assert_array_equal(
        unpack_applied_region_mask(restored_snapshot[region_ids[0]]),
        unpack_applied_region_mask(snapshot_after_apply[region_ids[0]]),
    )
