"""Endpoint tests for the colour workspace: similar recipes + colour-range selection.

颜色工作台接口测试：相似配方推荐与按颜色范围选择。
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import externalize_preview_cache
from api.routers.converter import replace as replace_module
from api.routers.converter import similar_recipes as similar_recipes_module
from api.session_store import SessionStore

client = TestClient(app)


@pytest.fixture(autouse=True)
def _iso():
    store = SessionStore()
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    try:
        yield store
    finally:
        app.dependency_overrides.pop(get_session_store, None)
        app.dependency_overrides.pop(get_file_registry, None)


def _preview_cache(rgb: np.ndarray) -> dict[str, object]:
    height, width = rgb.shape[:2]
    return {
        "matched_rgb": rgb.copy(),
        "quantized_image": rgb.copy(),
        "mask_solid": np.ones((height, width), dtype=bool),
        "material_matrix": np.zeros((height, width, 3), dtype=np.int32),
        "color_layers": 3,
        "layer_height_mm": 0.08,
        "target_w": width,
        "target_h": height,
        "target_width_mm": float(width * 10),
    }


def _seed_lut_session(store: SessionStore) -> str:
    session_id = store.create()
    rgb = np.full((4, 4, 3), [250, 250, 250], dtype=np.uint8)
    rgb[:2, :2] = [200, 0, 0]
    rgb[2:, 2:] = [204, 4, 2]
    store.put(session_id, "preview_cache", _preview_cache(rgb))
    store.put(session_id, "material_source", "lut")
    store.put(session_id, "lut_path", "fake.npz")
    store.put(session_id, "color_mode", "4-Color")
    store.put(session_id, "color_layers", 3)
    return session_id


def _fake_lut_runtime(predictive: object | None = None) -> dict[str, object]:
    return {
        "lut_rgb": np.array(
            [[250, 250, 250], [220, 30, 30], [30, 30, 220], [205, 40, 40]],
            dtype=np.uint8,
        ),
        "ref_stacks": np.array(
            [[0, 0, 0], [1, 1, 0], [2, 2, 0], [1, 1, 1]],
            dtype=np.int64,
        ),
        "predictive_runtime": predictive,
    }


def _patch_runtime(monkeypatch: pytest.MonkeyPatch, runtime: dict | None) -> list[dict]:
    calls: list[dict] = []

    def fake_loader(session_data: dict, *, color_layers: int, layer_height_mm: float):
        calls.append({"color_layers": color_layers, "layer_height_mm": layer_height_mm})
        return runtime

    monkeypatch.setattr(similar_recipes_module, "load_session_lut_runtime", fake_loader)
    return calls


def test_similar_recipes_ranks_lut_entries_by_delta_e(_iso, monkeypatch) -> None:
    sid = _seed_lut_session(_iso)
    calls = _patch_runtime(monkeypatch, _fake_lut_runtime())
    resp = client.post(
        "/api/convert/similar-recipes",
        json={"session_id": sid, "target_color": "#DA2020", "limit": 3},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["target_color"] == "#da2020"
    assert body["layer_order"] == "Top2Bottom"
    assert body["predictive_available"] is False
    assert [item["hex"] for item in body["items"][:2]] == ["#dc1e1e", "#cd2828"]
    assert body["items"][0]["recipe"] == [1, 1, 0]
    assert all(item["source"] == "lut" for item in body["items"])
    assert len(body["items"]) == 3
    assert calls == [{"color_layers": 3, "layer_height_mm": 0.08}]


def test_similar_recipes_includes_predictive_candidates(_iso, monkeypatch) -> None:
    sid = _seed_lut_session(_iso)
    lab = np.array([[46.0, 70.0, 55.0], [90.0, 0.0, 0.0]], dtype=np.float32)
    runtime = SimpleNamespace(
        candidate_recipes=np.array([[0, 1, 1], [0, 0, 0]], dtype=np.int64),
        pred_lab=lab,
        layer_order="Bottom2Top",
    )
    _patch_runtime(monkeypatch, _fake_lut_runtime(runtime))
    resp = client.post(
        "/api/convert/similar-recipes",
        json={"session_id": sid, "target_color": "#dc1e1e", "limit": 6},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["predictive_available"] is True
    predictive = [item for item in body["items"] if item["source"] == "predictive"]
    assert predictive, body
    # Bottom2Top candidates are normalised to the Top2Bottom response order.
    assert [1, 1, 0] in [item["recipe"] for item in predictive]


def test_similar_recipes_converts_bottom_to_top_lut_stacks(_iso, monkeypatch) -> None:
    sid = _seed_lut_session(_iso)
    runtime = _fake_lut_runtime()
    runtime["ref_stacks"] = np.array(
        [[0, 0, 0], [0, 1, 1], [0, 2, 2], [1, 1, 1]],
        dtype=np.int64,
    )
    runtime["layer_order"] = "Bottom2Top"
    _patch_runtime(monkeypatch, runtime)
    resp = client.post(
        "/api/convert/similar-recipes",
        json={"session_id": sid, "target_color": "#dc1e1e", "limit": 1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["layer_order"] == "Top2Bottom"
    # The stored Bottom2Top stack [0, 1, 1] is reported viewing face first.
    assert body["items"][0]["recipe"] == [1, 1, 0]


class _LastRowWinsTree:
    """Exact-match Lab lookup that breaks ties toward the last LUT row."""

    def __init__(self, lab: np.ndarray) -> None:
        self._lab = np.asarray(lab, dtype=np.float64)

    def query(self, points: np.ndarray):
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        dist = np.linalg.norm(self._lab[None, :, :] - points[:, None, :], axis=2)
        flipped = dist[:, ::-1]
        idx = self._lab.shape[0] - 1 - np.argmin(flipped, axis=1)
        return dist[np.arange(points.shape[0]), idx], idx


def test_similar_recipes_shows_the_stack_that_applying_writes(_iso, monkeypatch) -> None:
    import cv2

    sid = _seed_lut_session(_iso)
    lut_rgb = np.array([[255, 80, 55], [255, 80, 55], [250, 250, 250]], dtype=np.uint8)
    lab = cv2.cvtColor(lut_rgb.reshape(1, -1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3)
    runtime = {
        "lut_rgb": lut_rgb,
        "ref_stacks": np.array([[1, 1, 1, 1, 0], [1, 1, 0, 1, 0], [0, 0, 0, 0, 0]], dtype=np.int64),
        "layer_order": "Top2Bottom",
        "kdtree": _LastRowWinsTree(lab),
        "predictive_runtime": None,
    }
    _patch_runtime(monkeypatch, runtime)
    monkeypatch.setattr(replace_module, "load_session_lut_runtime", lambda *a, **k: runtime)

    resp = client.post(
        "/api/convert/similar-recipes",
        json={"session_id": sid, "target_color": "#ff5037", "limit": 1},
    )
    assert resp.status_code == 200, resp.text
    shown = resp.json()["items"][0]["recipe"]

    # Apply the same colour through the region-replacement stack sync.
    updated_rgb = np.full((2, 2, 3), [255, 80, 55], dtype=np.uint8)
    cache = {"material_matrix": np.zeros((2, 2, 5), dtype=np.int32), "color_layers": 5}
    replace_module._sync_lut_material_matrix_for_diff(
        {"color_layers": 5, "layer_height_mm": 0.08},
        cache,
        np.ones((2, 2), dtype=bool),
        updated_rgb,
    )
    written = [int(v) for v in cache["material_matrix"][0, 0]]
    assert shown == written == [1, 1, 0, 1, 0]


def test_similar_recipes_can_skip_predictive(_iso, monkeypatch) -> None:
    sid = _seed_lut_session(_iso)
    runtime = SimpleNamespace(
        candidate_recipes=np.array([[0, 1, 1]], dtype=np.int64),
        pred_lab=np.array([[46.0, 70.0, 55.0]], dtype=np.float32),
        layer_order="Top2Bottom",
    )
    _patch_runtime(monkeypatch, _fake_lut_runtime(runtime))
    resp = client.post(
        "/api/convert/similar-recipes",
        json={"session_id": sid, "target_color": "#dc1e1e", "include_predictive": False},
    )
    assert resp.status_code == 200, resp.text
    assert all(item["source"] == "lut" for item in resp.json()["items"])


def test_similar_recipes_suggests_image_colors_for_material_archive(_iso, monkeypatch) -> None:
    sid = _seed_lut_session(_iso)
    _iso.put(sid, "material_source", "material_archive")
    cache = _iso.get(sid)["preview_cache"]
    matrix = np.zeros((4, 4, 3), dtype=np.int32)
    matrix[:2, :2] = [1, 1, 0]
    matrix[2:, 2:] = [2, 1, -1]  # dynamic-layer padding is not a real layer
    cache["material_matrix"] = matrix

    def must_not_load_lut(*_args, **_kwargs):
        raise AssertionError("material-archive suggestions must not load a LUT")

    monkeypatch.setattr(similar_recipes_module, "load_session_lut_runtime", must_not_load_lut)
    resp = client.post(
        "/api/convert/similar-recipes",
        json={"session_id": sid, "target_color": "#c80000", "limit": 5},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [item["hex"] for item in items] == ["#c80000", "#cc0402", "#fafafa"]
    assert [item["recipe"] for item in items] == [[1, 1, 0], [2, 1], [0, 0, 0]]
    assert all(item["source"] == "image" and item["in_image"] for item in items)


def test_similar_recipes_requires_preview(_iso) -> None:
    sid = _iso.create()
    resp = client.post(
        "/api/convert/similar-recipes",
        json={"session_id": sid, "target_color": "#dc1e1e"},
    )
    assert resp.status_code == 409


def test_similar_recipes_reports_unavailable_lut(_iso, monkeypatch) -> None:
    sid = _seed_lut_session(_iso)
    _patch_runtime(monkeypatch, None)
    resp = client.post(
        "/api/convert/similar-recipes",
        json={"session_id": sid, "target_color": "#dc1e1e"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == similar_recipes_module.SIMILAR_RECIPES_LUT_UNAVAILABLE_DETAIL


def test_similar_recipes_maps_lut_load_errors_to_409(_iso, monkeypatch) -> None:
    sid = _seed_lut_session(_iso)

    def broken_loader(session_data: dict, *, color_layers: int, layer_height_mm: float):
        raise OSError("disk gone")

    monkeypatch.setattr(similar_recipes_module, "load_session_lut_runtime", broken_loader)
    resp = client.post(
        "/api/convert/similar-recipes",
        json={"session_id": sid, "target_color": "#dc1e1e"},
    )
    assert resp.status_code == 409


def test_similar_recipes_validates_input(_iso) -> None:
    sid = _seed_lut_session(_iso)
    bad_color = client.post(
        "/api/convert/similar-recipes",
        json={"session_id": sid, "target_color": "red"},
    )
    assert bad_color.status_code == 422
    unknown = client.post(
        "/api/convert/similar-recipes",
        json={"session_id": "missing", "target_color": "#dc1e1e"},
    )
    assert unknown.status_code == 404


def test_selection_mutate_color_range_toggle_selects_near_shades(_iso) -> None:
    sid = _seed_lut_session(_iso)
    resp = client.post(
        "/api/convert/selection/mutate",
        json={
            "session_id": sid,
            "operation": "color-range-toggle",
            "base_selection_revision": 0,
            "content_revision": 0,
            "x": 0,
            "y": 0,
            "color_tolerance": 5,
        },
    )
    assert resp.status_code == 200, resp.text
    doc = resp.json()
    assert doc["selected_pixel_count"] == 8
    assert sorted(doc["selected_color_hexes"]) == ["#c80000", "#cc0402"]
    assert doc["region_ids"]


def test_selection_mutate_color_range_requires_tolerance(_iso) -> None:
    sid = _seed_lut_session(_iso)
    resp = client.post(
        "/api/convert/selection/mutate",
        json={
            "session_id": sid,
            "operation": "color-range-toggle",
            "base_selection_revision": 0,
            "content_revision": 0,
            "x": 0,
            "y": 0,
        },
    )
    assert resp.status_code == 400


def _in_image_flags(sid: str) -> dict[str, bool]:
    resp = client.post(
        "/api/convert/similar-recipes",
        json={"session_id": sid, "target_color": "#fafafa", "limit": 4},
    )
    assert resp.status_code == 200, resp.text
    return {item["hex"]: item["in_image"] for item in resp.json()["items"]}


def test_similar_recipes_flag_colors_already_in_image(_iso, monkeypatch) -> None:
    sid = _seed_lut_session(_iso)
    _patch_runtime(monkeypatch, _fake_lut_runtime())
    # No visible-block cache yet: falls back to the preview cache pixels.
    flags = _in_image_flags(sid)
    assert flags["#fafafa"] is True
    assert flags["#dc1e1e"] is False


def test_similar_recipes_in_image_uses_visible_block_cache(_iso, monkeypatch) -> None:
    sid = _seed_lut_session(_iso)
    _patch_runtime(monkeypatch, _fake_lut_runtime())
    # A selection gesture builds the visible-block cache used by the fast path.
    mutate = client.post(
        "/api/convert/selection/mutate",
        json={
            "session_id": sid,
            "operation": "point-toggle",
            "base_selection_revision": 0,
            "content_revision": 0,
            "x": 0,
            "y": 0,
        },
    )
    assert mutate.status_code == 200, mutate.text
    assert _in_image_flags(sid) == {"#fafafa": True, "#dc1e1e": False, "#cd2828": False, "#1e1edc": False}


def _seed_artifact_session(
    store: SessionStore,
    tmp_path,
    material_source: str,
    *,
    drop_fields: tuple[str, ...] = (),
) -> tuple[str, dict]:
    """Seed an artifact-backed session shaped like a real preview cache.
    写入与真实预览相同形态的 artifact 缓存会话。
    """
    sid = _seed_lut_session(store)
    store.put(sid, "material_source", material_source)
    cache = dict(store.get(sid)["preview_cache"])
    height, width = cache["matched_rgb"].shape[:2]
    matrix = np.zeros((height, width, 3), dtype=np.int32)
    matrix[:2, :2] = [1, 1, 0]
    matrix[2:, 2:] = [2, 1, -1]
    cache["material_matrix"] = matrix
    cache["preview_rgba"] = np.full((height, width, 4), 255, dtype=np.uint8)
    cache["backing_mask"] = np.zeros((height, width), dtype=bool)
    for field in drop_fields:
        cache.pop(field)
    manifest = externalize_preview_cache(sid, store, cache, root_dir=tmp_path)
    store.put(sid, "preview_cache", manifest)
    return sid, manifest


def _similar(sid: str, color: str = "#c80000"):
    return client.post(
        "/api/convert/similar-recipes",
        json={"session_id": sid, "target_color": color, "limit": 5},
    )


def _break_artifact(manifest: dict, field: str, mode: str = "missing") -> None:
    path = manifest["fields"][field]["path"]
    if mode == "missing":
        os.remove(path)
    else:
        with open(path, "wb") as handle:
            handle.write(b"not a npy file")


@pytest.mark.parametrize("material_source", ["material_archive", "lut"])
@pytest.mark.parametrize(
    "unrelated",
    [("preview_rgba",), ("preview_rgba", "backing_mask", "quantized_image")],
)
def test_similar_recipes_ignores_missing_unrelated_artifacts(
    _iso, monkeypatch, tmp_path, material_source, unrelated
) -> None:
    _patch_runtime(monkeypatch, _fake_lut_runtime())
    sid, manifest = _seed_artifact_session(_iso, tmp_path, material_source)
    before = _similar(sid)
    assert before.status_code == 200, before.text

    for field in unrelated:
        _break_artifact(manifest, field)
    after = _similar(sid)

    assert after.status_code == 200, after.text
    assert after.json() == before.json()


@pytest.mark.parametrize("mode", ["missing", "corrupt"])
@pytest.mark.parametrize(
    ("material_source", "field"),
    [
        ("material_archive", "matched_rgb"),
        ("material_archive", "mask_solid"),
        ("material_archive", "material_matrix"),
        ("lut", "matched_rgb"),
        ("lut", "mask_solid"),
    ],
)
def test_similar_recipes_reports_unreadable_required_artifact_as_409(
    _iso, monkeypatch, tmp_path, material_source, field, mode
) -> None:
    _patch_runtime(monkeypatch, _fake_lut_runtime())
    sid, manifest = _seed_artifact_session(_iso, tmp_path, material_source)
    _break_artifact(manifest, field, mode)

    resp = _similar(sid)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == similar_recipes_module.PREVIEW_CACHE_UNAVAILABLE_DETAIL


def test_similar_recipes_lut_does_not_read_material_matrix(_iso, monkeypatch, tmp_path) -> None:
    _patch_runtime(monkeypatch, _fake_lut_runtime())
    sid, manifest = _seed_artifact_session(_iso, tmp_path, "lut")
    before = _similar(sid, "#dc1e1e")
    _break_artifact(manifest, "material_matrix")

    after = _similar(sid, "#dc1e1e")

    assert after.status_code == 200, after.text
    assert after.json() == before.json()


def test_similar_recipes_keeps_optional_fields_absent_from_manifest(_iso, monkeypatch, tmp_path) -> None:
    sid, _manifest = _seed_artifact_session(
        _iso, tmp_path, "material_archive", drop_fields=("mask_solid", "material_matrix")
    )

    resp = _similar(sid)

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [item["hex"] for item in items] == ["#c80000", "#cc0402", "#fafafa"]
    assert all(item["recipe"] == [] for item in items)
