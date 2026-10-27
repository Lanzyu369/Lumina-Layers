"""回归：统一选区 mutation 产生的 region_ids 能否被 apply-recipe-override 消费。

选区系统（selection_state）把 mask 发布为 __editor_selection__:<rev> 合成
region id；自定义配方对话框把 selectionDocument.region_ids 直接传给
apply-recipe-override。若 _get_region_mask_items_for_ids 无法从合成 id
解析回 mask，就会 409 "No selected regions available for recipe override."。
"""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.session_store import SessionStore
from api.dependencies import get_session_store, get_file_registry
from api.file_registry import FileRegistry

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


def test_selection_region_ids_consumable_by_recipe_override(_iso):
    store = _iso["store"]
    sid = _seed_material_archive_session(store)

    # 1) 统一选区：同色全选红色块
    resp = client.post("/api/convert/selection/mutate", json={
        "session_id": sid,
        "operation": "same-color-toggle",
        "base_selection_revision": 0,
        "content_revision": 0,
        "color_hex": "ff0000",
    })
    assert resp.status_code == 200, resp.text
    doc = resp.json()
    assert doc["selection_revision"] >= 1, doc
    region_ids = doc["region_ids"]
    print("mutation region_ids:", region_ids)
    assert len(region_ids) >= 1, doc

    # 2) apply-recipe-override 直接消费这些 region_ids
    resp2 = client.post("/api/convert/apply-recipe-override", json={
        "session_id": sid,
        "region_ids": region_ids,
        "recipe": [0, 1, 0],
        "layer_height_mm": 0.08,
        "color_layers": 3,
        "layer_order": "Top2Bottom",
    })
    print("apply-recipe-override status:", resp2.status_code, resp2.text[:300])
    assert resp2.status_code == 200, resp2.text

    # 3) region-recipe（对话框打开时的采样）也应可用
    resp3 = client.post("/api/convert/region-recipe", json={
        "session_id": sid,
        "region_ids": region_ids,
        "layer_order": "Top2Bottom",
    })
    print("region-recipe status:", resp3.status_code, resp3.text[:200])
    assert resp3.status_code == 200, resp3.text


def test_recipe_after_selection_undo(_iso):
    """选中 → 撤销选区 → 再应用配方（用户反馈路径：No selected regions）"""
    store = _iso["store"]
    sid = _seed_material_archive_session(store)

    # 1) 选区 mutation rev1
    r1 = client.post("/api/convert/selection/mutate", json={
        "session_id": sid, "operation": "same-color-toggle",
        "base_selection_revision": 0, "content_revision": 0,
        "color_hex": "ff0000",
    })
    assert r1.status_code == 200, r1.text
    ids1 = r1.json()["region_ids"]
    print("rev1 ids:", ids1)

    # 2) 再点一次（toggle off）→ rev2，留一个可撤销的选区手势
    r2 = client.post("/api/convert/selection/mutate", json={
        "session_id": sid, "operation": "same-color-toggle",
        "base_selection_revision": 1, "content_revision": 0,
        "color_hex": "ff0000",
    })
    assert r2.status_code == 200, r2.text
    print("rev2 ids:", r2.json()["region_ids"])

    # 3) 撤销选区手势 → 恢复 rev1 的 mask
    ru = client.post("/api/convert/replacement-history", json={
        "session_id": sid, "action": "undo",
    })
    print("undo status:", ru.status_code, ru.text[:200])
    assert ru.status_code == 200, ru.text
    restored = ru.json()
    print("undo 后 selection:", restored.get("selection"))
    if restored.get("selection"):
        restored_ids = restored["selection"]["region_ids"]
        print("撤销后 region_ids:", restored_ids)
        # 4) 立即应用配方
        ra = client.post("/api/convert/apply-recipe-override", json={
            "session_id": sid, "region_ids": restored_ids,
            "recipe": [0, 1, 0], "layer_height_mm": 0.08,
            "color_layers": 3, "layer_order": "Top2Bottom",
        })
        print("撤销后应用配方 status:", ra.status_code, ra.text[:300])
        assert ra.status_code == 200, ra.text
