"""Unit tests for the material recipe preview API endpoint.

Covers:
- Happy path: forward Beer-Lambert simulation matches a numeric reference.
- Layer count is unconstrained beyond the schema bound (1, 2, 7, ... layers).
- Substrate selection ('white' / 'black') propagates into the response.
- Schema validation rejects empty / malformed inputs.
- 404 propagates when a directory cannot be resolved.

覆盖：
- 正常路径：正向 Beer-Lambert 模拟与数值参照一致；
- 层数除 schema 上限外不受限制；
- ``white`` / ``black`` 基底参数正确生效；
- schema 校验拒绝空 / 非法输入；
- 加载失败时透传 404。
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tests._migrated_app import create_app
from core.material_color_solver import (
    MaterialParams,
    forward_model,
    linear_to_srgb_uint8,
)


def _client() -> TestClient:
    return TestClient(create_app())


def _mat(name: str, E: tuple, k: tuple, est_rgb: tuple = (180, 60, 60)) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(E, dtype=np.float64),
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.asarray((1.0, 1.0, 1.0), dtype=np.float64),
        estimated_rgb=np.asarray(est_rgb, dtype=np.uint8),
    )


_SYNTHETIC_PALETTE = [
    _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0), est_rgb=(220, 30, 30)),
    _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0), est_rgb=(40, 60, 220)),
    _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5), est_rgb=(245, 245, 245)),
]


@pytest.fixture
def stub_palette(monkeypatch: pytest.MonkeyPatch):
    """Bypass disk-backed material loading with the synthetic palette.
    绕过磁盘加载，直接返回合成耗材。
    """

    def _loader(directory_names):
        mats = []
        for idx, _name in enumerate(directory_names):
            mats.append(_SYNTHETIC_PALETTE[idx % len(_SYNTHETIC_PALETTE)])
        return mats

    monkeypatch.setattr(
        "api.routers.single_stage.load_multiple_materials", _loader
    )


def _expected_hex(materials: list[MaterialParams], layer_height_mm: float) -> str:
    recipe = np.arange(len(materials), dtype=np.int32)
    substrate_linear = np.asarray(materials[0].C0_white, dtype=np.float64)
    predicted = forward_model(recipe, materials, layer_height_mm, substrate_linear)
    rgb = linear_to_srgb_uint8(predicted.reshape(1, 3))[0].tolist()
    return "#{:02X}{:02X}{:02X}".format(*rgb)


class TestMaterialRecipePreviewHappyPath:
    def test_three_layer_recipe_matches_forward_model(self, stub_palette):
        response = _client().post(
            "/api/extractor/material-recipe-preview",
            json={
                "directory_names": ["red", "blue", "white"],
                "layer_height_mm": 0.08,
                "substrate": "white",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["layer_count"] == 3
        assert body["layer_height_mm"] == 0.08
        assert body["substrate"] == "white"
        assert body["predicted_hex"] == _expected_hex(_SYNTHETIC_PALETTE[:3], 0.08)
        assert body["predicted_rgb"] == [
            int(c) for c in bytes.fromhex(body["predicted_hex"][1:])
        ]
        assert [layer["layer_index"] for layer in body["layers"]] == [0, 1, 2]
        assert [layer["material_name"] for layer in body["layers"]] == [
            "Red",
            "Blue",
            "White",
        ]
        for layer in body["layers"]:
            assert layer["estimated_hex"].startswith("#")
            assert len(layer["estimated_hex"]) == 7
            assert len(layer["estimated_rgb"]) == 3

    @pytest.mark.parametrize("count", [1, 2, 7, 12])
    def test_layer_count_is_unconstrained(self, stub_palette, count: int):
        names = [f"slot-{i}" for i in range(count)]
        response = _client().post(
            "/api/extractor/material-recipe-preview",
            json={
                "directory_names": names,
                "layer_height_mm": 0.08,
                "substrate": "white",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["layer_count"] == count
        assert len(body["layers"]) == count

    def test_black_substrate_is_supported(self, stub_palette):
        response = _client().post(
            "/api/extractor/material-recipe-preview",
            json={
                "directory_names": ["red", "blue"],
                "layer_height_mm": 0.08,
                "substrate": "black",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["substrate"] == "black"


class TestMaterialRecipePreviewValidation:
    def test_empty_list_is_rejected(self):
        response = _client().post(
            "/api/extractor/material-recipe-preview",
            json={"directory_names": [], "layer_height_mm": 0.08, "substrate": "white"},
        )
        assert response.status_code == 422

    def test_blank_directory_name_is_rejected(self):
        response = _client().post(
            "/api/extractor/material-recipe-preview",
            json={
                "directory_names": ["red", "  "],
                "layer_height_mm": 0.08,
                "substrate": "white",
            },
        )
        assert response.status_code == 422

    def test_invalid_substrate_is_rejected(self):
        response = _client().post(
            "/api/extractor/material-recipe-preview",
            json={
                "directory_names": ["red"],
                "layer_height_mm": 0.08,
                "substrate": "transparent",
            },
        )
        assert response.status_code == 422

    def test_invalid_layer_height_is_rejected(self):
        response = _client().post(
            "/api/extractor/material-recipe-preview",
            json={
                "directory_names": ["red"],
                "layer_height_mm": 0.0,
                "substrate": "white",
            },
        )
        assert response.status_code == 422

    def test_too_many_layers_is_rejected(self):
        response = _client().post(
            "/api/extractor/material-recipe-preview",
            json={
                "directory_names": [f"slot-{i}" for i in range(65)],
                "layer_height_mm": 0.08,
                "substrate": "white",
            },
        )
        assert response.status_code == 422

    def test_missing_directory_returns_404(self, monkeypatch: pytest.MonkeyPatch):
        def _loader(_directory_names):
            raise FileNotFoundError("no such material")

        monkeypatch.setattr(
            "api.routers.single_stage.load_multiple_materials", _loader
        )
        response = _client().post(
            "/api/extractor/material-recipe-preview",
            json={
                "directory_names": ["ghost"],
                "layer_height_mm": 0.08,
                "substrate": "white",
            },
        )
        assert response.status_code == 404
