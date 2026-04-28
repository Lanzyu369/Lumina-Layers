"""Unit tests for LUT info and merge API endpoints.

Validates:
- GET /api/lut/{name}/info returns correct info or 404 (Requirement 6.7)
- POST /api/lut/merge returns 400 for invalid requests (Requirement 6.8)
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_session_store
from api.schemas.converter import ColorMode, ConvertGenerateRequest, ConvertPreviewRequest
from api.session_store import SessionStore
from config import LUTMetadata, PaletteEntry
from core.native_reference import (
    NativeReferenceContext,
    SOURCE_KIND_COLORD_DB,
    SOURCE_KIND_PACKAGE,
)

client: TestClient = TestClient(app)


def _raw_lut_colors(count: int) -> list[dict]:
    return [{"hex": "#000000", "color": (0, 0, 0)} for _ in range(count)]


# =========================================================================
# 1. GET /api/lut/{name}/info — success scenario (Requirement 6.7)
# =========================================================================


class TestLutInfoSuccess:
    """Verify the info endpoint returns correct mode and count."""

    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(
            None,
            None,
            LUTMetadata(
                schema_version="2.0",
                capabilities=["legacy_lookup", "predictive_match", "dynamic_layer_height", "dynamic_layer_count"],
                palette=[
                    PaletteEntry(
                        color="White",
                        material="PLA Basic",
                        hex_color="#FFFFFF",
                        color_name="Jade White",
                    )
                ],
                extensions={
                    "source_kind": "predictive_package",
                    "runtime_package": {
                        "defaults": {"threshold": 5.0},
                        "modes": {},
                    }
                },
            ),
        ),
    )
    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("8-Color", 2738))
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/path.npy")
    def test_info_returns_200_with_correct_fields(
        self, mock_path, mock_detect, mock_load_meta
    ) -> None:
        response = client.get("/api/lut/TestLUT/info")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "TestLUT"
        assert data["color_mode"] == "8-Color Max"
        assert data["color_count"] == 2738
        assert data["schema_version"] == "2.0"
        assert data["supports_predictive_match"] is True
        assert data["supports_dynamic_layer_height"] is True
        assert data["supports_dynamic_layer_count"] is True
        assert data["supports_custom_recipe"] is False
        assert data["source_kind"] == "predictive_package"
        assert data["supported_modes"] == []
        assert data["palette"] == [
            {
                "color": "White",
                "material": "PLA Basic",
                "hex_color": "#FFFFFF",
                "color_name": "Jade White",
            }
        ]
        assert "predictive_match" in data["capabilities"]

    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(None, None, LUTMetadata()),
    )
    @patch("api.routers.lut.LUTManager.infer_color_mode", return_value="4-Color (RYBW)")
    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("4-Color", 1024))
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/path.npy")
    def test_info_prefers_canonicalized_color_mode_for_response(
        self,
        mock_path,
        mock_detect,
        mock_infer,
        mock_load_meta,
    ) -> None:
        response = client.get("/api/lut/TestLegacy/info")
        assert response.status_code == 200
        data = response.json()
        assert data["color_mode"] == "4-Color (RYBW)"
        assert data["color_count"] == 1024


# =========================================================================
# 2. GET /api/lut/{name}/info — 404 scenario (Requirement 6.7)
# =========================================================================


class TestLutInfoNotFound:
    """Verify the info endpoint returns 404 for non-existent LUT."""

    @patch("api.routers.lut.LUTManager.get_lut_path", return_value=None)
    def test_info_returns_404_when_lut_not_found(self, mock_path) -> None:
        response = client.get("/api/lut/NonExistent/info")
        assert response.status_code == 404
        assert "LUT not found" in response.json()["detail"]


# =========================================================================
# 3. GET /api/lut/session/{session_id}/info — works for sessions without
#    a globally-known LUT name (material archive / native bundle).
# =========================================================================


class TestSessionLutInfo:
    """Verify the session-scoped LUT info endpoint."""

    def _override_store(self, store: SessionStore) -> None:
        app.dependency_overrides[get_session_store] = lambda: store

    def _clear_override(self) -> None:
        app.dependency_overrides.pop(get_session_store, None)

    def test_returns_404_when_session_missing(self) -> None:
        store = SessionStore(ttl=60)
        self._override_store(store)
        try:
            response = client.get("/api/lut/session/does-not-exist/info")
            assert response.status_code == 404
            assert "Session not found" in response.json()["detail"]
        finally:
            self._clear_override()

    def test_returns_409_when_session_has_no_lut(self) -> None:
        store = SessionStore(ttl=60)
        session_id = store.create()
        self._override_store(store)
        try:
            response = client.get(f"/api/lut/session/{session_id}/info")
            assert response.status_code == 409
            assert "LUT" in response.json()["detail"]
        finally:
            self._clear_override()

    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(
            None,
            None,
            LUTMetadata(
                palette=[
                    PaletteEntry(
                        color="White",
                        material="PLA Basic",
                        hex_color="#FFFFFF",
                        color_name="Jade White",
                    ),
                    PaletteEntry(
                        color="Red",
                        material="PLA Basic",
                        hex_color="#FF0000",
                        color_name="Ruby",
                    ),
                ],
            ),
        ),
    )
    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("8-Color", 2))
    def test_returns_channel_palette_for_session_lut(
        self,
        mock_detect,
        mock_load_meta,
        tmp_path: Path,
    ) -> None:
        # Need a real file path for os.path.exists guard in the endpoint.
        lut_file = tmp_path / "session_lut.json"
        lut_file.write_text("{}", encoding="utf-8")

        store = SessionStore(ttl=60)
        session_id = store.create()
        store.put(session_id, "lut_path", str(lut_file))
        store.put(session_id, "lut_name", "Material Archive Session")

        self._override_store(store)
        try:
            response = client.get(f"/api/lut/session/{session_id}/info")
            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "Material Archive Session"
            assert data["color_mode"] == "8-Color Max"
            # Channel palette should be returned in LUT order, not quantized order.
            assert [entry["color"] for entry in data["palette"]] == ["White", "Red"]
            assert data["palette"][0]["hex_color"] == "#FFFFFF"
            assert data["palette"][1]["hex_color"] == "#FF0000"
        finally:
            self._clear_override()

    def test_generate_schema_accepts_legacy_8_color_alias(self) -> None:
        request = ConvertGenerateRequest(lut_name="Legacy8", color_mode="8-Color")

        assert request.color_mode is ColorMode.EIGHT_COLOR

    def test_preview_schema_accepts_legacy_8_color_alias(self) -> None:
        request = ConvertPreviewRequest(lut_name="Legacy8", color_mode="8-Color")

        assert request.color_mode is ColorMode.EIGHT_COLOR

    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(None, None, LUTMetadata()),
    )
    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("BW", 2))
    def test_falls_back_to_file_stem_when_lut_name_missing(
        self,
        mock_detect,
        mock_load_meta,
        tmp_path: Path,
    ) -> None:
        lut_file = tmp_path / "fallback_name.json"
        lut_file.write_text("{}", encoding="utf-8")

        store = SessionStore(ttl=60)
        session_id = store.create()
        store.put(session_id, "lut_path", str(lut_file))
        # Intentionally no "lut_name" stored.

        self._override_store(store)
        try:
            response = client.get(f"/api/lut/session/{session_id}/info")
            assert response.status_code == 200
            assert response.json()["name"] == "fallback_name"
        finally:
            self._clear_override()

    def test_returns_material_archive_palette_for_session_without_lut_file(self) -> None:
        store = SessionStore(ttl=60)
        session_id = store.create()
        store.put(session_id, "lut_path", "__material_archive__")
        store.put(session_id, "lut_name", "__material_archive__")
        store.put(session_id, "material_source", "material_archive")
        store.put(session_id, "selected_materials", [
            "brand/red-pla",
            "brand/green-pla",
            "brand/blue-pla",
            "brand/yellow-pla",
            "brand/cyan-pla",
        ])
        store.put(session_id, "material_layer_count", 7)
        store.put(session_id, "material_layer_height_mm", 0.08)
        store.put(
            session_id,
            "preview_cache",
            {
                "color_layers": 7,
                "layer_height_mm": 0.08,
                "slot_names": [
                    "PLA Red",
                    "PLA Green",
                    "PLA Blue",
                    "PLA Yellow",
                    "PLA Cyan",
                ],
                "preview_colors": {
                    0: [255, 0, 0, 255],
                    1: [0, 255, 0, 255],
                    2: [0, 0, 255, 255],
                    3: [255, 255, 0, 255],
                    4: [0, 255, 255, 255],
                },
            },
        )

        self._override_store(store)
        try:
            response = client.get(f"/api/lut/session/{session_id}/info")
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["name"] == "__material_archive__"
            assert data["color_mode"] == "Material Archive"
            assert data["color_count"] == 5
            assert data["max_color_layers"] == 7
            assert data["layer_height_mm"] == 0.08
            assert [entry["color"] for entry in data["palette"]] == [
                "PLA Red",
                "PLA Green",
                "PLA Blue",
                "PLA Yellow",
                "PLA Cyan",
            ]
            assert [entry["material"] for entry in data["palette"]] == [
                "brand/red-pla",
                "brand/green-pla",
                "brand/blue-pla",
                "brand/yellow-pla",
                "brand/cyan-pla",
            ]
            assert [entry["hex_color"] for entry in data["palette"]] == [
                "#FF0000",
                "#00FF00",
                "#0000FF",
                "#FFFF00",
                "#00FFFF",
            ]
        finally:
            self._clear_override()


class TestLutColorsLayout:
    """Verify LUT colors card payloads use flattened LUT rows."""

    def test_colors_flattens_grid_rgb_before_resolving_layout(self) -> None:
        rgb = np.zeros((32, 32, 3), dtype=np.uint8)

        with (
            patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/four.npy"),
            patch(
                "api.routers.lut.LUTManager.load_lut_with_metadata",
                return_value=(rgb, None, LUTMetadata(color_mode="4-Color (RYBW)")),
            ),
            patch(
                "core.converter.extract_lut_available_colors",
                return_value=_raw_lut_colors(1024),
            ),
        ):
            response = client.get("/api/lut/FourGrid/colors")

        assert response.status_code == 200
        data = response.json()
        assert data["layout"]["total_count"] == 1024
        assert data["layout"]["pages"][0]["data_cols"] == 32
        assert len(data["cards"]) == 1
        assert len(data["cards"][0]["colors"]) == 1024

    def test_colors_splits_flattened_8color_grid_into_two_cards(self) -> None:
        rgb = np.zeros((74, 37, 3), dtype=np.uint8)

        with (
            patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/eight.npy"),
            patch(
                "api.routers.lut.LUTManager.load_lut_with_metadata",
                return_value=(rgb, None, LUTMetadata(color_mode="8-Color Max")),
            ),
            patch(
                "core.converter.extract_lut_available_colors",
                return_value=_raw_lut_colors(2738),
            ),
        ):
            response = client.get("/api/lut/EightGrid/colors")

        assert response.status_code == 200
        data = response.json()
        assert data["layout"]["total_count"] == 2738
        assert [card["page"]["card_label"] for card in data["cards"]] == ["A", "B"]
        assert [len(card["colors"]) for card in data["cards"]] == [1369, 1369]


class TestPredictRecipeColor:
    """Verify predictive recipe endpoint returns predicted color data."""

    @patch(
        "api.routers.lut.predict_recipe_color",
        return_value={
            "rgb": [255, 255, 255],
            "lab": [100.0, 0.0, 0.0],
            "runtime_mode_key": "0.08x5",
            "source": "stage_model",
        },
    )
    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(None, None, LUTMetadata()),
    )
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/source.json")
    def test_predict_recipe_color_returns_200(
        self,
        mock_path,
        mock_load_meta,
        mock_predict,
    ) -> None:
        response = client.post(
            "/api/lut/TestSource/predict-recipe-color",
            json={
                "recipe": [0, 0, 0, 0, 0],
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "layer_order": "Top2Bottom",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["rgb"] == [255, 255, 255]
        assert data["runtime_mode_key"] == "0.08x5"

    @patch(
        "api.routers.lut.predict_recipe_color",
        side_effect=ValueError("Recipe is not present in the runtime package; exact prediction unavailable for package-only source"),
    )
    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(None, None, LUTMetadata()),
    )
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/source.json")
    def test_predict_recipe_color_returns_422_for_non_exact_package_only_recipe(
        self,
        mock_path,
        mock_load_meta,
        mock_predict,
    ) -> None:
        response = client.post(
            "/api/lut/TestSource/predict-recipe-color",
            json={
                "recipe": [0, 1, 0, 1, 0],
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "layer_order": "Top2Bottom",
            },
        )
        assert response.status_code == 422
        assert "exact prediction unavailable" in response.json()["detail"]


class TestSourceKindFallback:
    """Verify plain V2 predictive LUTs still surface predictive source_kind without explicit extension."""

    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(
            None,
            None,
            LUTMetadata(
                schema_version="2.0",
                capabilities=["predictive_match"],
                extensions={
                    "runtime_package": {
                        "defaults": {"threshold": 5.0},
                        "modes": {},
                    }
                },
            ),
        ),
    )
    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("8-Color", 2738))
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/path.json")
    def test_info_source_kind_falls_back_to_predictive_package(
        self, mock_path, mock_detect, mock_load_meta
    ) -> None:
        response = client.get("/api/lut/TestRuntimePackage/info")
        assert response.status_code == 200
        data = response.json()
        assert data["source_kind"] == "predictive_package"


class TestSourceCatalog:
    """Verify the new LUT/source catalog exposes both legacy and native groupings."""

    def test_list_remains_legacy_only(self) -> None:
        response = client.get("/api/lut/list")
        assert response.status_code == 200

        data = response.json()["luts"]
        names = {entry["name"] for entry in data}
        assert not any(name.startswith("ReferenceDB -") for name in names)
        assert not any(name.startswith("ReferencePack -") for name in names)
        assert not any(name.startswith("ReferenceModel -") for name in names)

    def test_catalog_includes_legacy_and_native_groups(self) -> None:
        response = client.get("/api/lut/catalog")
        assert response.status_code == 200

        data = response.json()
        assert "legacy_groups" in data
        assert "native_brand_groups" in data

        legacy_group_names = {group["group_name"] for group in data["legacy_groups"]}
        assert {"Preset", "ReferenceDB", "ReferencePack", "ReferenceModel"} & legacy_group_names

        native_groups = data["native_brand_groups"]
        assert native_groups

        bambu_pla = next(
            group
            for group in native_groups
            if group["vendor"] == "BambuLab" and group["material_type"] == "PLA"
        )
        assert bambu_pla["brand_key"]
        assert bambu_pla["display_name"]
        assert bambu_pla["db_options"]
        assert bambu_pla["default_db_names"]
        assert bambu_pla["package_name"] == "bambulab_pla.msgpack"
        assert bambu_pla["model_name"] == "bambulab_pla_stage_B.json"
        assert bambu_pla["supported_modes"]
        option_names = {option["name"] for option in bambu_pla["db_options"]}
        assert bambu_pla["default_db_names"][0] in option_names

    @patch(
        "api.routers.lut.LUTManager.get_source_catalog",
        return_value={
            "legacy_groups": [
                {
                    "group_name": "Preset",
                    "items": [
                        {
                            "name": "Legacy8",
                            "color_mode": "8-Color",
                            "path": "/legacy8.npy",
                            "fingerprint": "fp-legacy8",
                        }
                    ],
                }
            ],
            "native_brand_groups": [
                {
                    "brand_key": "bambulab_pla",
                    "material_type": "PLA",
                    "vendor": "BambuLab",
                    "display_name": "BambuLab PLA",
                    "db_options": [
                        {
                            "name": "Eight.json",
                            "path": "/Eight.json",
                            "color_mode": "8-Color",
                            "fingerprint": "fp-eight",
                        }
                    ],
                    "default_db_names": ["Eight.json"],
                    "package_name": None,
                    "model_name": None,
                    "supported_modes": [],
                }
            ],
        },
    )
    def test_catalog_canonicalizes_legacy_8_color_aliases(self, mock_catalog) -> None:
        response = client.get("/api/lut/catalog")
        assert response.status_code == 200

        data = response.json()
        assert data["legacy_groups"][0]["items"][0]["color_mode"] == "8-Color Max"
        assert data["native_brand_groups"][0]["db_options"][0]["color_mode"] == "8-Color Max"

    def test_catalog_falls_back_to_bundled_native_assets_when_reference_repo_is_missing(self) -> None:
        from utils.lut_manager import LUTManager

        bundled_root = Path("assets/native_sources/ChromaPrint3D").resolve()
        assert bundled_root.joinpath("data", "model_packs", "bambulab_pla.msgpack").exists()
        assert bundled_root.joinpath("data", "models", "forward", "bambulab_pla_stage_B.json").exists()
        assert bundled_root.joinpath("data", "dbs", "PLA", "BambuLab", "CMYW_008_5L.json").exists()

        LUTManager.invalidate_native_source_index_cache()
        resolved_path = None
        missing_reference_root = Path(os.getcwd(), "missing-reference-root-does-not-exist")

        try:
            with (
                patch(
                    "core.native_reference.iter_reference_repo_candidates",
                    return_value=(missing_reference_root, bundled_root),
                ),
                patch("utils.lut_manager.LUTManager._build_legacy_catalog_groups", return_value=[]),
            ):
                catalog = LUTManager.get_source_catalog()
                native_groups = catalog["native_brand_groups"]
                assert native_groups

                bambu_pla = next(
                    group for group in native_groups if group["brand_key"] == "bambulab_pla"
                )
                assert bambu_pla["package_name"] == "bambulab_pla.msgpack"
                assert bambu_pla["model_name"] == "bambulab_pla_stage_B.json"
                assert "CMYW_008_5L.json" in bambu_pla["default_db_names"]

                resolved_path, resolved_name = LUTManager.resolve_source_selection(
                    source_kind="native_bundle",
                    material_type="PLA",
                    vendor="BambuLab",
                    db_names=["CMYW_008_5L.json"],
                )

                assert Path(resolved_path).exists()
                assert resolved_name == "BambuLab PLA"
        finally:
            LUTManager.invalidate_native_source_index_cache()
            if resolved_path and Path(resolved_path).exists():
                resolved_resolved = Path(resolved_path).resolve()
                if not str(resolved_resolved).startswith(str(bundled_root)):
                    resolved_resolved.unlink(missing_ok=True)

    def test_manager_catalog_payload_omits_internal_resolution_fields(self) -> None:
        fake_path = os.path.join("C:\\tmp", "fake.msgpack")
        native_ctx = NativeReferenceContext(
            source_kind=SOURCE_KIND_PACKAGE,
            primary_path=fake_path,
            package_path=fake_path,
            stage_model_path=os.path.join("C:\\tmp", "fake_stage.json"),
            db_paths=(os.path.join("C:\\tmp", "A.json"),),
            vendor="BambuLab",
            material_type="PLA",
        )

        from utils.lut_manager import LUTManager

        LUTManager.invalidate_native_source_index_cache()
        try:
            with (
                patch("utils.lut_manager.LUTManager._build_legacy_catalog_groups", return_value=[]),
                patch("utils.lut_manager.LUTManager._iter_scanned_lut_files", return_value=[("ReferencePack", "C:\\tmp", fake_path)]),
                patch("utils.lut_manager.discover_native_reference_context", return_value=native_ctx),
            ):
                catalog = LUTManager.get_source_catalog()

            native_group = catalog["native_brand_groups"][0]
            assert "package_path" not in native_group
            assert "model_path" not in native_group
        finally:
            LUTManager.invalidate_native_source_index_cache()

    def test_native_source_catalog_reuses_cached_index(self) -> None:
        from utils.lut_manager import LUTManager

        LUTManager.invalidate_native_source_index_cache()
        try:
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                fake_path = os.path.join(tmpdir, "A.json")
                with open(fake_path, "w", encoding="utf-8") as fh:
                    fh.write("{}")

                native_ctx = NativeReferenceContext(
                    source_kind=SOURCE_KIND_COLORD_DB,
                    primary_path=fake_path,
                    db_paths=(fake_path,),
                    vendor="BambuLab",
                    material_type="PLA",
                )

                with (
                    patch("utils.lut_manager.LUTManager._build_legacy_catalog_groups", return_value=[]),
                    patch("utils.lut_manager.LUTManager._iter_scanned_lut_files", return_value=[("ReferenceDB", tmpdir, fake_path)]),
                    patch("utils.lut_manager.discover_native_reference_context", return_value=native_ctx) as mock_discover,
                    patch("utils.lut_manager.LUTManager.compute_fingerprint", return_value="fp"),
                    patch("utils.lut_manager.LUTManager.infer_color_mode", return_value="4-Color (RYBW)"),
                ):
                    first = LUTManager.get_source_catalog()
                    second = LUTManager.get_source_catalog()
                    resolved_path, resolved_name = LUTManager.resolve_source_selection(
                        source_kind="native_bundle",
                        material_type="PLA",
                        vendor="BambuLab",
                        db_names=["A.json"],
                    )

                assert first == second
                assert resolved_path == fake_path
                assert resolved_name == "A.json"
                assert mock_discover.call_count == 1
        finally:
            LUTManager.invalidate_native_source_index_cache()

    def test_native_source_catalog_auto_refreshes_after_ttl(self) -> None:
        from utils.lut_manager import LUTManager, _NativeBrandIndexItem, _NativeDbIndexItem

        LUTManager.invalidate_native_source_index_cache()
        original_ttl = getattr(LUTManager, "NATIVE_SOURCE_INDEX_TTL_SECONDS", None)
        LUTManager.NATIVE_SOURCE_INDEX_TTL_SECONDS = 10.0
        first_index = (
            _NativeBrandIndexItem(
                brand_key="bambulab_pla",
                material_type="PLA",
                vendor="BambuLab",
                display_name="BambuLab PLA",
                db_options=(
                    _NativeDbIndexItem(
                        name="A.json",
                        path="A.json",
                        color_mode="4-Color (RYBW)",
                        fingerprint="fp-a",
                    ),
                ),
                default_db_names=("A.json",),
                package_name=None,
                model_name=None,
                supported_modes=(),
                package_path=None,
                model_path=None,
            ),
        )
        second_index = (
            _NativeBrandIndexItem(
                brand_key="bambulab_pla",
                material_type="PLA",
                vendor="BambuLab",
                display_name="BambuLab PLA",
                db_options=(
                    _NativeDbIndexItem(
                        name="B.json",
                        path="B.json",
                        color_mode="4-Color (CMYW)",
                        fingerprint="fp-b",
                    ),
                ),
                default_db_names=("B.json",),
                package_name=None,
                model_name=None,
                supported_modes=(),
                package_path=None,
                model_path=None,
            ),
        )

        try:
            with (
                patch("utils.lut_manager.time.monotonic", side_effect=[0.0, 0.0, 11.0, 11.0]),
                patch(
                    "utils.lut_manager.LUTManager._build_native_source_index",
                    side_effect=[first_index, second_index],
                ) as mock_build,
            ):
                first = LUTManager.get_source_catalog()
                second = LUTManager.get_source_catalog()

            assert first["native_brand_groups"][0]["db_options"][0]["name"] == "A.json"
            assert second["native_brand_groups"][0]["db_options"][0]["name"] == "B.json"
            assert mock_build.call_count == 2
        finally:
            if original_ttl is None:
                delattr(LUTManager, "NATIVE_SOURCE_INDEX_TTL_SECONDS")
            else:
                LUTManager.NATIVE_SOURCE_INDEX_TTL_SECONDS = original_ttl
            LUTManager.invalidate_native_source_index_cache()


# =========================================================================
# 3. POST /api/lut/merge — empty secondary list (Requirement 6.8)
# =========================================================================


class TestMergeEmptySecondary:
    """Verify merge returns 400 when secondary_names is empty."""

    def test_merge_empty_secondary_returns_400(self) -> None:
        payload = {
            "primary_name": "SomeLUT",
            "secondary_names": [],
            "dedup_threshold": 3.0,
        }
        response = client.post("/api/lut/merge", json=payload)
        assert response.status_code == 400
        assert "At least one secondary LUT" in response.json()["detail"]


# =========================================================================
# 4. POST /api/lut/merge — Primary mode not 6/8-Color (Requirement 6.8)
# =========================================================================


class TestMergePrimaryModeInvalid:
    """Verify merge returns 400 when primary LUT is not 6-Color or 8-Color."""

    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("4-Color", 1024))
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/primary.npy")
    def test_merge_4color_primary_returns_400(self, mock_path, mock_detect) -> None:
        payload = {
            "primary_name": "FourColorLUT",
            "secondary_names": ["SecondaryLUT"],
            "dedup_threshold": 3.0,
        }
        response = client.post("/api/lut/merge", json=payload)
        assert response.status_code == 400
        assert "Primary LUT must be 6-Color or 8-Color" in response.json()["detail"]


# =========================================================================
# 5. POST /api/lut/merge — compatibility failure (Requirement 6.8)
# =========================================================================


class TestMergeCompatibilityFailure:
    """Verify merge returns 400 when LUT modes are incompatible."""

    @patch(
        "api.routers.lut.LUTMerger.validate_compatibility",
        return_value=(False, "Incompatible color modes"),
    )
    @patch("api.routers.lut.LUTMerger.load_lut_with_stacks")
    @patch("api.routers.lut.LUTMerger.detect_color_mode")
    @patch("api.routers.lut.LUTManager.get_lut_path")
    def test_merge_incompatible_modes_returns_400(
        self, mock_path, mock_detect, mock_load, mock_validate
    ) -> None:
        import numpy as np

        # get_lut_path returns a path for both primary and secondary
        mock_path.side_effect = ["/fake/primary.npy", "/fake/secondary.npy"]
        # detect_color_mode: primary is 8-Color, secondary is 8-Color (incompatible)
        mock_detect.side_effect = [("8-Color", 2738), ("8-Color", 2738)]
        # load_lut_with_stacks returns dummy data
        dummy_rgb = np.zeros((10, 3), dtype=np.uint8)
        dummy_stacks = np.zeros((10, 5), dtype=np.int32)
        mock_load.return_value = (dummy_rgb, dummy_stacks)

        payload = {
            "primary_name": "PrimaryLUT",
            "secondary_names": ["SecondaryLUT"],
            "dedup_threshold": 3.0,
        }
        response = client.post("/api/lut/merge", json=payload)
        assert response.status_code == 400
        assert "Incompatible" in response.json()["detail"]


# =========================================================================
# 6. POST /api/lut/compare — success scenario
# =========================================================================


class TestCompareSuccess:
    """Verify compare returns 200 with same-recipe stats."""

    @patch("api.routers.lut.LUTMerger.validate_print_params", return_value=(True, []))
    @patch(
        "api.routers.lut.LUTMerger.compare_luts_by_recipe",
        return_value={
            "stats": {
                "matched_recipe_count": 2,
                "recipe_coverage_a": 1.0,
                "recipe_coverage_b": 1.0,
                "mean_delta_e00": 1.25,
                "median_delta_e00": 1.25,
                "p95_delta_e00": 1.8,
                "max_delta_e00": 2.0,
                "identical_rgb_count": 1,
                "recipes_only_in_a": 0,
                "recipes_only_in_b": 0,
            },
            "warnings": [],
            "worst_diffs": [
                {
                    "recipe": ["White", "Red", "Yellow", "Blue", "White"],
                    "rgb_a": [255, 0, 0],
                    "rgb_b": [254, 5, 0],
                    "hex_a": "#FF0000",
                    "hex_b": "#FE0500",
                    "delta_e00": 2.0,
                }
            ],
        },
    )
    @patch("api.routers.lut.LUTMerger.normalize_stacks_for_compare")
    @patch("api.routers.lut.LUTManager.load_lut_with_metadata")
    @patch("api.routers.lut.LUTMerger.load_lut_with_stacks")
    @patch("api.routers.lut.LUTMerger.detect_color_mode")
    @patch("api.routers.lut.LUTManager.get_lut_path")
    def test_compare_returns_200_with_stats(
        self,
        mock_path,
        mock_detect,
        mock_load,
        mock_load_meta,
        mock_normalize,
        mock_compare,
        mock_validate,
    ) -> None:
        import numpy as np

        dummy_rgb = np.array([[255, 0, 0], [0, 255, 0]], dtype=np.uint8)
        dummy_stacks = np.array([[0, 5, 3, 6, 0], [0, 1, 2, 3, 4]], dtype=np.int32)

        mock_path.side_effect = ["/fake/a.json", "/fake/b.json"]
        mock_detect.side_effect = [("4-Color", 1024), ("4-Color", 1024)]
        mock_load.side_effect = [(dummy_rgb, dummy_stacks), (dummy_rgb, dummy_stacks)]
        mock_load_meta.side_effect = [
            (dummy_rgb, dummy_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
            (dummy_rgb, dummy_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
        ]
        mock_normalize.side_effect = [dummy_stacks, dummy_stacks]

        payload = {
            "lut_a_name": "LUT_A",
            "lut_b_name": "LUT_B",
            "top_n": 5,
        }
        response = client.post("/api/lut/compare", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["lut_a_name"] == "LUT_A"
        assert data["lut_b_name"] == "LUT_B"
        assert data["stats"]["matched_recipe_count"] == 2
        assert data["stats"]["mean_delta_e00"] == 1.25
        assert data["worst_diffs"][0]["delta_e00"] == 2.0

    @patch("api.routers.lut.LUTMerger.normalize_stacks_for_compare")
    @patch("api.routers.lut.LUTMerger.validate_print_params", return_value=(True, []))
    @patch("api.routers.lut.LUTManager.load_lut_with_metadata")
    @patch("api.routers.lut.LUTMerger.load_lut_with_stacks")
    @patch("api.routers.lut.LUTMerger.detect_color_mode")
    @patch("api.routers.lut.LUTManager.get_lut_path")
    def test_compare_uses_canonical_stacks_from_loader(
        self,
        mock_path,
        mock_detect,
        mock_load,
        mock_load_meta,
        mock_validate,
        mock_normalize,
    ) -> None:
        import numpy as np

        dummy_rgb = np.array([[255, 0, 0]], dtype=np.uint8)
        canonical_stacks = np.array([[0, 5, 3, 6, 0]], dtype=np.int32)

        def compare_side_effect(rgb_a, stacks_a, rgb_b, stacks_b, top_n):
            np.testing.assert_array_equal(stacks_a, canonical_stacks)
            np.testing.assert_array_equal(stacks_b, canonical_stacks)
            return {
                "stats": {
                    "matched_recipe_count": 1,
                    "recipe_coverage_a": 1.0,
                    "recipe_coverage_b": 1.0,
                    "mean_delta_e00": 0.0,
                    "median_delta_e00": 0.0,
                    "p95_delta_e00": 0.0,
                    "max_delta_e00": 0.0,
                    "identical_rgb_count": 1,
                    "recipes_only_in_a": 0,
                    "recipes_only_in_b": 0,
                },
                "warnings": [],
                "worst_diffs": [],
            }

        mock_normalize.side_effect = AssertionError(
            "compare route should not re-normalize canonical stacks"
        )
        mock_path.side_effect = ["/fake/a.json", "/fake/b.json"]
        mock_detect.side_effect = [("4-Color", 1024), ("4-Color", 1024)]
        mock_load.side_effect = [
            (dummy_rgb, canonical_stacks),
            (dummy_rgb, canonical_stacks),
        ]
        mock_load_meta.side_effect = [
            (dummy_rgb, canonical_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
            (dummy_rgb, canonical_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
        ]

        with patch(
            "api.routers.lut.LUTMerger.compare_luts_by_recipe",
            side_effect=compare_side_effect,
        ):
            payload = {
                "lut_a_name": "LUT_A",
                "lut_b_name": "LUT_B",
                "top_n": 5,
            }
            response = client.post("/api/lut/compare", json=payload)

        assert response.status_code == 200
        mock_normalize.assert_not_called()


# =========================================================================
# 7. POST /api/lut/compare — 404 scenario
# =========================================================================


class TestCompareNotFound:
    """Verify compare returns 404 when a LUT is missing."""

    @patch("api.routers.lut.LUTManager.get_lut_path", return_value=None)
    def test_compare_returns_404_when_lut_not_found(self, mock_path) -> None:
        payload = {
            "lut_a_name": "MissingLUT",
            "lut_b_name": "OtherLUT",
            "top_n": 5,
        }
        response = client.post("/api/lut/compare", json=payload)
        assert response.status_code == 404
        assert "LUT not found" in response.json()["detail"]


# =========================================================================
# 8. POST /api/lut/compare — no shared recipes warning
# =========================================================================


class TestCompareNoSharedRecipes:
    """Verify compare surfaces the empty shared-recipe warning."""

    @patch("api.routers.lut.LUTMerger.validate_print_params", return_value=(True, []))
    @patch(
        "api.routers.lut.LUTMerger.compare_luts_by_recipe",
        return_value={
            "stats": {
                "matched_recipe_count": 0,
                "recipe_coverage_a": 0.0,
                "recipe_coverage_b": 0.0,
                "mean_delta_e00": 0.0,
                "median_delta_e00": 0.0,
                "p95_delta_e00": 0.0,
                "max_delta_e00": 0.0,
                "identical_rgb_count": 0,
                "recipes_only_in_a": 10,
                "recipes_only_in_b": 12,
            },
            "warnings": [],
            "worst_diffs": [],
        },
    )
    @patch("api.routers.lut.LUTMerger.normalize_stacks_for_compare")
    @patch("api.routers.lut.LUTManager.load_lut_with_metadata")
    @patch("api.routers.lut.LUTMerger.load_lut_with_stacks")
    @patch("api.routers.lut.LUTMerger.detect_color_mode")
    @patch("api.routers.lut.LUTManager.get_lut_path")
    def test_compare_includes_no_shared_recipe_warning(
        self,
        mock_path,
        mock_detect,
        mock_load,
        mock_load_meta,
        mock_normalize,
        mock_compare,
        mock_validate,
    ) -> None:
        import numpy as np

        dummy_rgb = np.array([[255, 0, 0]], dtype=np.uint8)
        dummy_stacks = np.array([[0, 5, 3, 6, 0]], dtype=np.int32)

        mock_path.side_effect = ["/fake/a.json", "/fake/b.json"]
        mock_detect.side_effect = [("4-Color", 1024), ("4-Color", 1024)]
        mock_load.side_effect = [(dummy_rgb, dummy_stacks), (dummy_rgb, dummy_stacks)]
        mock_load_meta.side_effect = [
            (dummy_rgb, dummy_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
            (dummy_rgb, dummy_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
        ]
        mock_normalize.side_effect = [dummy_stacks, dummy_stacks]

        payload = {
            "lut_a_name": "LUT_A",
            "lut_b_name": "LUT_B",
            "top_n": 5,
        }
        response = client.post("/api/lut/compare", json=payload)

        assert response.status_code == 200
        warnings = response.json()["warnings"]
        assert any("No shared recipes found" in warning for warning in warnings)
