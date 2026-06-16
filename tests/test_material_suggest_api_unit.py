"""Smoke tests for the material color suggestion API endpoint.

Covers:
- ``POST /api/extractor/material-solver-cache/suggest-colors`` happy path via
  the MITM fallback and the cache fast path (through a monkeypatched cache).
- Input validation for ``target_hex``, ``top_k``, ``min_spacing``, layer
  count / height / substrate.
- Overflow guard translation into HTTP 422 with an actionable hint.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from core.material_color_solver import ColorSuggestion, MaterialParams


def _client_with_state() -> tuple[TestClient, SessionStore, FileRegistry]:
    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app), store, registry


def _mat(name: str, E: tuple, k: tuple) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(E, dtype=np.float64),
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.asarray((1.0, 1.0, 1.0), dtype=np.float64),
        estimated_rgb=np.asarray(
            [int(round(255 * c)) for c in E], dtype=np.uint8
        ),
    )


_SYNTHETIC_PALETTE = [
    _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0)),
    _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0)),
    _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5)),
]


@pytest.fixture
def stub_palette_loader(monkeypatch: pytest.MonkeyPatch):
    """Bypass disk-backed material loading by returning the synthetic palette.
    绕过磁盘加载，直接返回合成耗材以便测试 API 逻辑。
    """

    def _loader(directory_names):
        # Mirror ``core.material_lut_synthesis.load_multiple_materials``'s
        # ordering contract: one MaterialParams per requested directory_name.
        mats = []
        for idx, _name in enumerate(directory_names):
            mats.append(_SYNTHETIC_PALETTE[idx % len(_SYNTHETIC_PALETTE)])
        return mats

    monkeypatch.setattr(
        "api.routers.single_stage.load_multiple_materials", _loader
    )


@pytest.fixture
def stub_cache_miss(monkeypatch: pytest.MonkeyPatch):
    """Force the MITM fallback path by pretending no cache exists on disk."""
    monkeypatch.setattr(
        "api.routers.single_stage.load_material_solver_cache",
        lambda *args, **kwargs: None,
    )


@pytest.fixture
def stub_runtime_miss(monkeypatch: pytest.MonkeyPatch):
    """Force the exact MITM fallback by pretending no hybrid runtime exists."""
    monkeypatch.setattr(
        "api.routers.single_stage.load_material_candidate_runtime",
        lambda *args, **kwargs: None,
        raising=False,
    )


class TestSuggestColorsMitmPath:
    def test_happy_path_returns_suggestions(
        self, stub_palette_loader, stub_cache_miss, stub_runtime_miss
    ):
        client, *_ = _client_with_state()
        response = client.post(
            "/api/extractor/material-solver-cache/suggest-colors",
            data={
                "material_directory_names": json.dumps(
                    ["red", "blue", "white"]
                ),
                "layer_count": 5,
                "layer_height_mm": 0.08,
                "substrate": "white",
                "target_hex": "#B45030",
                "top_k": 8,
                "min_spacing": 1.0,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["source"] == "mitm"
        assert body["target_hex"] == "#B45030"
        assert body["target_rgb"] == [180, 80, 48]
        assert body["layer_count"] == 5
        assert body["layer_height_mm"] == 0.08
        assert body["substrate"] == "white"
        assert 1 <= len(body["suggestions"]) <= 8
        # Each suggestion shape
        for item in body["suggestions"]:
            assert item["hex"].startswith("#") and len(item["hex"]) == 7
            assert len(item["rgb"]) == 3
            assert all(0 <= v <= 255 for v in item["rgb"])
            assert item["delta_e"] >= 0.0
            assert len(item["recipe"]) == 5
            assert all(0 <= v < 3 for v in item["recipe"])
            assert item["recipe_display"].startswith("[") and item[
                "recipe_display"
            ].endswith("]")
        # ΔE ordering
        delta_e_values = [item["delta_e"] for item in body["suggestions"]]
        assert delta_e_values == sorted(delta_e_values)

    def test_accepts_short_hex(
        self, stub_palette_loader, stub_cache_miss, stub_runtime_miss
    ):
        client, *_ = _client_with_state()
        response = client.post(
            "/api/extractor/material-solver-cache/suggest-colors",
            data={
                "material_directory_names": json.dumps(["red"]),
                "layer_count": 5,
                "layer_height_mm": 0.08,
                "substrate": "white",
                "target_hex": "#abc",
                "top_k": 3,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["target_hex"] == "#AABBCC"
        assert body["target_rgb"] == [170, 187, 204]

    def test_overflow_guard_returns_422_with_hint(
        self, stub_palette_loader, stub_cache_miss, stub_runtime_miss
    ):
        client, *_ = _client_with_state()
        response = client.post(
            "/api/extractor/material-solver-cache/suggest-colors",
            data={
                "material_directory_names": json.dumps(["red", "blue", "white"]),
                "layer_count": 10,
                "layer_height_mm": 0.08,
                "substrate": "white",
                "target_hex": "#808080",
                "top_k": 5,
                "max_combinations": 10_000,
            },
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "combinations" in detail.lower()
        assert "cache" in detail.lower()


class TestSuggestColorsCachePath:
    def test_cache_hit_reports_source_cache(
        self, stub_palette_loader, monkeypatch: pytest.MonkeyPatch
    ):
        stub_suggestion = ColorSuggestion(
            matched_rgb=np.asarray([200, 100, 60], dtype=np.uint8),
            recipe=np.asarray([0, 1, 2, 1, 0], dtype=np.int32),
            delta_e=2.5,
        )

        class _StubCache:
            palette_hash = "stubhash"
            valid_cell_count = 1234

            def lookup_top_k(self, *args, **kwargs):
                return [stub_suggestion]

        monkeypatch.setattr(
            "api.routers.single_stage.load_material_solver_cache",
            lambda *args, **kwargs: _StubCache(),
        )
        monkeypatch.setattr(
            "api.routers.single_stage.load_material_candidate_runtime",
            lambda *args, **kwargs: pytest.fail(
                "runtime must not be loaded when exact cache hits"
            ),
            raising=False,
        )

        client, *_ = _client_with_state()
        response = client.post(
            "/api/extractor/material-solver-cache/suggest-colors",
            data={
                "material_directory_names": json.dumps(["red", "blue", "white"]),
                "layer_count": 5,
                "layer_height_mm": 0.08,
                "substrate": "white",
                "target_hex": "#C86432",
                "top_k": 3,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source"] == "cache"
        assert "solver cache" in body["message"]
        assert body["suggestions"] == [
            {
                "hex": "#C8643C",
                "rgb": [200, 100, 60],
                "delta_e": 2.5,
                "recipe": [0, 1, 2, 1, 0],
                "recipe_display": "[0,1,2,1,0]",
            }
        ]


class TestSuggestColorsRuntimePath:
    def test_runtime_hit_reports_source_runtime(
        self,
        stub_palette_loader,
        stub_cache_miss,
        monkeypatch: pytest.MonkeyPatch,
    ):
        stub_suggestion = ColorSuggestion(
            matched_rgb=np.asarray([128, 96, 72], dtype=np.uint8),
            recipe=np.asarray([0, 1, 2, 0, 1, 2, 0, 1, 2, 0], dtype=np.int32),
            delta_e=3.25,
        )

        class _StubRuntime:
            valid_cell_count = 4096

            def lookup_top_k(self, target_rgb, materials, *, top_k, min_spacing):
                assert target_rgb.tolist() == [130, 98, 70]
                assert len(materials) == 12
                assert top_k == 3
                assert min_spacing == 1.5
                return [stub_suggestion]

        monkeypatch.setattr(
            "api.routers.single_stage.load_material_candidate_runtime",
            lambda *args, **kwargs: _StubRuntime(),
            raising=False,
        )
        monkeypatch.setattr(
            "api.routers.single_stage.suggest_colors_for_target",
            lambda *args, **kwargs: pytest.fail("MITM fallback should not run"),
        )

        client, *_ = _client_with_state()
        response = client.post(
            "/api/extractor/material-solver-cache/suggest-colors",
            data={
                "material_directory_names": json.dumps(
                    [f"mat-{idx}" for idx in range(12)]
                ),
                "layer_count": 10,
                "layer_height_mm": 0.08,
                "substrate": "white",
                "target_hex": "#826246",
                "top_k": 3,
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source"] == "runtime"
        assert "hybrid runtime" in body["message"]
        assert body["suggestions"] == [
            {
                "hex": "#806048",
                "rgb": [128, 96, 72],
                "delta_e": 3.25,
                "recipe": [0, 1, 2, 0, 1, 2, 0, 1, 2, 0],
                "recipe_display": "[0,1,2,0,1,2,0,1,2,0]",
            }
        ]


class TestSuggestColorsValidation:
    def test_rejects_invalid_hex(self, stub_palette_loader, stub_cache_miss):
        client, *_ = _client_with_state()
        response = client.post(
            "/api/extractor/material-solver-cache/suggest-colors",
            data={
                "material_directory_names": json.dumps(["red"]),
                "layer_count": 5,
                "layer_height_mm": 0.08,
                "substrate": "white",
                "target_hex": "nope",
            },
        )
        assert response.status_code == 422
        assert "target_hex" in response.json()["detail"]

    def test_rejects_bad_top_k(self, stub_palette_loader, stub_cache_miss):
        client, *_ = _client_with_state()
        response = client.post(
            "/api/extractor/material-solver-cache/suggest-colors",
            data={
                "material_directory_names": json.dumps(["red"]),
                "layer_count": 5,
                "layer_height_mm": 0.08,
                "substrate": "white",
                "target_hex": "#808080",
                "top_k": 0,
            },
        )
        assert response.status_code == 422
        assert "top_k" in response.json()["detail"]

    def test_rejects_bad_spacing(self, stub_palette_loader, stub_cache_miss):
        client, *_ = _client_with_state()
        response = client.post(
            "/api/extractor/material-solver-cache/suggest-colors",
            data={
                "material_directory_names": json.dumps(["red"]),
                "layer_count": 5,
                "layer_height_mm": 0.08,
                "substrate": "white",
                "target_hex": "#808080",
                "min_spacing": -1.0,
            },
        )
        assert response.status_code == 422
        assert "min_spacing" in response.json()["detail"]

    def test_rejects_bad_substrate(self, stub_palette_loader, stub_cache_miss):
        client, *_ = _client_with_state()
        response = client.post(
            "/api/extractor/material-solver-cache/suggest-colors",
            data={
                "material_directory_names": json.dumps(["red"]),
                "layer_count": 5,
                "layer_height_mm": 0.08,
                "substrate": "orange",
                "target_hex": "#808080",
            },
        )
        assert response.status_code == 422
        assert "substrate" in response.json()["detail"]

    def test_rejects_empty_directory_names(self, stub_cache_miss):
        client, *_ = _client_with_state()
        response = client.post(
            "/api/extractor/material-solver-cache/suggest-colors",
            data={
                "material_directory_names": json.dumps([]),
                "layer_count": 5,
                "layer_height_mm": 0.08,
                "substrate": "white",
                "target_hex": "#808080",
            },
        )
        assert response.status_code == 422
        assert "material_directory_names" in response.json()["detail"]
