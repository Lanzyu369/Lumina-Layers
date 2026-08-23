"""Regression: recipe overrides must survive editor-selection lifecycle.

复现路径：选区（__editor_selection__:<rev> 合成 region id）→
apply-recipe-override → 前端自动清空选区（合成 id 从
selected_region_masks 清理）→ /generate 重新套用覆盖时必须仍能解析掩码。
修复方式：apply 端点把当时使用的掩码快照进会话键
``recipe_override_applied_masks``，generate/puzzle 在实时选区缺失时回退。
"""
import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore

client = TestClient(app)


@pytest.fixture(autouse=True)
def _iso():
    store = SessionStore()
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    try:
        yield {"store": store, "registry": registry}
    finally:
        app.dependency_overrides.pop(get_session_store, None)
        app.dependency_overrides.pop(get_file_registry, None)


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
    store.put(session_id, "material_layer_count", 3)
    store.put(session_id, "material_layer_height_mm", 0.08)
    store.put(session_id, "lut_name", "__material_archive__")
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


def test_apply_persists_applied_mask_snapshot(_iso):
    """apply-recipe-override 快照本次使用的区域掩码。"""
    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_ids = _select_red_region(client, sid)

    resp = _apply_recipe_override(client, sid, region_ids)
    assert resp.status_code == 200, resp.text

    session_data = store.get(sid)
    snapshot = session_data.get("recipe_override_applied_masks")
    assert isinstance(snapshot, dict), session_data.keys()
    for region_id in region_ids:
        mask = snapshot.get(region_id)
        assert isinstance(mask, np.ndarray), (region_id, snapshot.keys())
        assert mask.dtype == np.dtype(bool)
        assert mask.shape == (6, 6)
        assert np.any(mask)
        # The snapshot matches the live synthetic selection mask at apply time.
        live = (session_data.get("selected_region_masks") or {}).get(region_id)
        assert live is not None
        np.testing.assert_array_equal(mask, np.asarray(live, dtype=bool))


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
    import pickle

    with open(masks_path, "rb") as mask_file:
        saved_masks = pickle.load(mask_file)
    assert region_ids[0] in saved_masks
    assert np.any(saved_masks[region_ids[0]])
    # The override must land on exactly the snapshotted footprint.
    # 覆盖必须精确落在快照掩码的像素足迹上。
    written_matrix = np.load(mm_path)
    expected_snapshot = np.asarray(
        store.get(sid)["recipe_override_applied_masks"][region_ids[0]],
        dtype=bool,
    )
    np.testing.assert_array_equal(saved_masks[region_ids[0]], expected_snapshot)
    np.testing.assert_array_equal(
        written_matrix[expected_snapshot],
        np.tile(np.array([0, 1, 0], dtype=written_matrix.dtype), (int(expected_snapshot.sum()), 1)),
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
    session_data["recipe_override_applied_masks"] = {
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
    assert store.get(sid).get("recipe_override_applied_masks")

    reset = client.post("/api/convert/reset-replacements", json={"session_id": sid})
    assert reset.status_code == 200, reset.text
    assert store.get(sid).get("recipe_override_applied_masks") == {}


def test_undo_redo_keeps_snapshot_in_sync_with_overrides(_iso):
    """撤销/重做时快照随 recipe_overrides 一起恢复。"""
    store = _iso["store"]
    sid = _seed_material_archive_session(store)
    region_ids = _select_red_region(client, sid)

    resp = _apply_recipe_override(client, sid, region_ids)
    assert resp.status_code == 200, resp.text
    snapshot_after_apply = store.get(sid).get("recipe_override_applied_masks")
    assert region_ids[0] in snapshot_after_apply

    undo = client.post("/api/convert/replacement-history", json={
        "session_id": sid, "action": "undo",
    })
    assert undo.status_code == 200, undo.text
    undone = store.get(sid)
    assert undone.get("recipe_overrides") == []
    assert undone.get("recipe_override_applied_masks") == {}

    redo = client.post("/api/convert/replacement-history", json={
        "session_id": sid, "action": "redo",
    })
    assert redo.status_code == 200, redo.text
    redone = store.get(sid)
    restored_snapshot = redone.get("recipe_override_applied_masks")
    assert region_ids[0] in restored_snapshot
    np.testing.assert_array_equal(
        np.asarray(restored_snapshot[region_ids[0]], dtype=bool),
        np.asarray(snapshot_after_apply[region_ids[0]], dtype=bool),
    )
