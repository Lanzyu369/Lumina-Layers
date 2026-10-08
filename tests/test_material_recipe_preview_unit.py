"""Unit tests for the material recipe preview API endpoint.

Covers:
- Happy path: forward Beer-Lambert simulation matches a numeric reference.
- Layer count is unconstrained beyond the schema bound (1, 2, 7, ... layers).
- Substrate selection ('white' / 'black') propagates into the response.
- Schema validation rejects empty / malformed inputs.
- Archive/profile contract errors are returned as safe 422 responses.

覆盖：
- 正常路径：正向 Beer-Lambert 模拟与数值参照一致；
- 层数除 schema 上限外不受限制；
- ``white`` / ``black`` 基底参数正确生效；
- schema 校验拒绝空 / 非法输入；
- 档案/光学契约错误安全地返回 422。
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from core.material_color_solver import (
    MaterialParams,
    forward_model,
    linear_to_srgb_uint8,
    predict_material_recipe_srgb,
)
from core.km_xyz import (
    KM_XYZ_COLOR_BRIDGE_ID,
)
from core.backed_gradient_material import (
    BACKED_GRADIENT_PROTOCOL_ID,
    BackedGradientComponent,
    BackedGradientReference,
)
from core.backed_gradient_smooth import SPECTRAL_SMOOTH_MODEL_ID
from core.material_optical_runtime import bind_material_print_backing


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


def _lumina_box_material() -> MaterialParams:
    reference = BackedGradientReference(
        "recipe-preview-reference",
        BackedGradientComponent("white", (-6.0, 0.0, 0.0, 0.0, 0.7)),
        BackedGradientComponent("black", (2.0, -4.0, 0.0, 0.5)),
        {"W": (96.0, 96.0, 96.0), "K": (0.1, 0.1, 0.1)},
    )
    return MaterialParams(
        name="Lumina Blue",
        directory_name="lumina-blue",
        E=np.zeros(3, dtype=np.float64),
        k=np.zeros(3, dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=np.asarray((50, 90, 190), dtype=np.uint8),
        optical_model_id=SPECTRAL_SMOOTH_MODEL_ID,
        measurement_protocol_id=BACKED_GRADIENT_PROTOCOL_ID,
        color_bridge_id=KM_XYZ_COLOR_BRIDGE_ID,
        backed_gradient_component=BackedGradientComponent(
            "color", (-3.0, -2.0, 0.0, 0.0, 0.0, 1.0, 0.7),
        ),
        backed_gradient_reference=reference,
    )


@pytest.fixture
def stub_palette(monkeypatch: pytest.MonkeyPatch):
    """Bypass disk-backed material loading with the synthetic palette.
    绕过磁盘加载，直接返回合成耗材。
    """

    def _loader(directory_names, *, profile_kind):
        mats = []
        for idx, _name in enumerate(directory_names):
            mats.append(_SYNTHETIC_PALETTE[idx % len(_SYNTHETIC_PALETTE)])
        return profile_kind, mats

    monkeypatch.setattr(
        "api.routers.single_stage.load_and_validate_material_archive_profile",
        _loader,
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
        assert body["material_profile_kind"] == "stage_a"
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

    def test_lumina_box_profile_uses_the_production_backed_gradient_forward_dispatcher(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        materials = [_lumina_box_material()]
        captured: dict[str, object] = {}

        def _loader(directory_names, *, profile_kind):
            captured["directory_names"] = directory_names
            captured["material_profile_kind"] = profile_kind
            return profile_kind, materials

        monkeypatch.setattr(
            "api.routers.single_stage.load_and_validate_material_archive_profile",
            _loader,
        )
        expected_rgb = predict_material_recipe_srgb(
            np.asarray([0], dtype=np.int32),
            bind_material_print_backing(materials, layer_height_mm=0.08, substrate="white"),
            layer_height_mm=0.08,
            substrate="white",
        ).tolist()

        response = _client().post(
            "/api/extractor/material-recipe-preview",
            json={
                "directory_names": ["lumina-blue"],
                "material_profile_kind": "lumina_box",
                "layer_height_mm": 0.08,
                "substrate": "white",
            },
        )

        assert response.status_code == 200, response.text
        assert captured == {
            "directory_names": ["lumina-blue"],
            "material_profile_kind": "lumina_box",
        }
        assert response.json()["material_profile_kind"] == "lumina_box"
        assert response.json()["predicted_rgb"] == expected_rgb

    def test_white_substrate_ignores_first_archive_c0(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        first = MaterialParams(
            name="Non-white C0",
            directory_name="non-white-c0",
            E=np.asarray((0.7, 0.3, 0.2), dtype=np.float64),
            k=np.asarray((1.4, 1.2, 1.0), dtype=np.float64),
            C0_white=np.asarray((0.35, 0.45, 0.55), dtype=np.float64),
            estimated_rgb=np.asarray((190, 100, 80), dtype=np.uint8),
        )
        materials = [first, _SYNTHETIC_PALETTE[1]]
        monkeypatch.setattr(
            "api.routers.single_stage.load_and_validate_material_archive_profile",
            lambda _directory_names, *, profile_kind: (
                profile_kind,
                materials,
            ),
        )
        recipe = np.arange(len(materials), dtype=np.int32)
        expected_rgb = predict_material_recipe_srgb(
            recipe,
            materials,
            layer_height_mm=0.08,
            substrate="white",
        ).tolist()
        legacy_rgb = linear_to_srgb_uint8(
            forward_model(
                recipe,
                materials,
                0.08,
                np.asarray(first.C0_white, dtype=np.float64),
            )
        ).tolist()

        response = _client().post(
            "/api/extractor/material-recipe-preview",
            json={
                "directory_names": ["non-white-c0", "blue"],
                "layer_height_mm": 0.08,
                "substrate": "white",
            },
        )

        assert expected_rgb != legacy_rgb
        assert response.status_code == 200, response.text
        assert response.json()["predicted_rgb"] == expected_rgb


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

    def test_profile_contract_failure_returns_422(self, monkeypatch: pytest.MonkeyPatch):
        from core.pipeline._input_validation_common import MaterialArchiveProfileError

        def _loader(_directory_names, *, profile_kind):
            raise MaterialArchiveProfileError(
                f"unknown optical contract for {profile_kind}"
            )

        monkeypatch.setattr(
            "api.routers.single_stage.load_and_validate_material_archive_profile",
            _loader,
        )
        response = _client().post(
            "/api/extractor/material-recipe-preview",
            json={
                "directory_names": ["ghost"],
                "material_profile_kind": "lumina_box",
                "layer_height_mm": 0.08,
                "substrate": "white",
            },
        )
        assert response.status_code == 422
        body = response.json()
        assert body["detail"]["code"] == "material_profile_kind_mismatch"
        assert "unknown optical contract" in body["detail"]["message"]

    def test_missing_stage_a_directory_preserves_legacy_404(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from core.pipeline._input_validation_common import MaterialArchiveProfileError

        def _profile_loader(_directory_names, *, profile_kind):
            raise MaterialArchiveProfileError(
                f"Selected {profile_kind} material archive cannot be read."
            )

        def _legacy_loader(_directory_names):
            raise FileNotFoundError("no such material")

        monkeypatch.setattr(
            "api.routers.single_stage.load_and_validate_material_archive_profile",
            _profile_loader,
        )
        monkeypatch.setattr(
            "api.routers.single_stage.load_multiple_materials",
            _legacy_loader,
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


class TestMaterialRecipeSwatchProfileContract:
    def test_lumina_box_swatch_carries_the_profile_and_preserves_result_hex(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        output_path = tmp_path / "lumina-box-swatch.3mf"
        output_path.write_bytes(b"3mf")
        captured: dict[str, object] = {}

        def _loader(directory_names, *, profile_kind):
            captured["directory_names"] = directory_names
            captured["material_profile_kind"] = profile_kind
            return profile_kind, [_lumina_box_material()]

        def _generate(*, recipes, **_kwargs):
            captured["recipes"] = recipes
            return str(output_path), None, "ok"

        monkeypatch.setattr(
            "api.routers.single_stage.load_and_validate_material_archive_profile",
            _loader,
        )
        monkeypatch.setattr(
            "core.material_recipe_swatch.generate_material_recipe_swatch",
            _generate,
        )

        response = _client().post(
            "/api/extractor/generate-material-swatch",
            json={
                "material_profile_kind": "lumina_box",
                "recipes": [
                    {
                        "directory_names": ["lumina-red"],
                        "result_hex": "#325ABE",
                        "layer_height_mm": 0.08,
                        "substrate": "white",
                    }
                ],
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["material_profile_kind"] == "lumina_box"
        assert captured["directory_names"] == ["lumina-red"]
        assert captured["material_profile_kind"] == "lumina_box"
        assert captured["recipes"][0].result_hex == "#325ABE"

    def test_swatch_rejects_a_mixed_archive_profile_before_generation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from core.pipeline._input_validation_common import MaterialArchiveProfileError

        def _loader(directory_names, *, profile_kind):
            if "stage-a-red" in directory_names:
                raise MaterialArchiveProfileError(
                    "unknown optical contract for stage-a-red"
                )
            return profile_kind, [_SYNTHETIC_PALETTE[0]]

        monkeypatch.setattr(
            "api.routers.single_stage.load_and_validate_material_archive_profile",
            _loader,
        )
        monkeypatch.setattr(
            "core.material_recipe_swatch.generate_material_recipe_swatch",
            lambda **_kwargs: pytest.fail("mixed profile must not generate a swatch"),
        )
        response = _client().post(
            "/api/extractor/generate-material-swatch",
            json={
                "material_profile_kind": "lumina_box",
                "recipes": [
                    {
                        "directory_names": ["lumina-blue"],
                        "result_hex": "#325ABE",
                        "layer_height_mm": 0.08,
                        "substrate": "white",
                    },
                    {
                        "directory_names": ["stage-a-red"],
                        "result_hex": "#B43C5A",
                        "layer_height_mm": 0.08,
                        "substrate": "white",
                    },
                ],
            },
        )

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "material_profile_kind_mismatch"
