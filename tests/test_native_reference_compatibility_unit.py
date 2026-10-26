"""Focused unit tests for native reference compatibility checks."""

from __future__ import annotations

import json
import os
import tempfile

import msgpack
import numpy as np
import pytest

from config import LUTMetadata, PaletteEntry
from core.native_reference import (
    NativeReferenceContext,
    SOURCE_KIND_COLORD_DB,
    SOURCE_KIND_STAGE_MODEL,
    discover_native_reference_context,
    opencv_lab_to_rgb_uint8,
    supported_mode_dict,
)
from utils.lut_manager import LUTManager


def test_colordb_discovery_skips_incompatible_global_predictive_assets() -> None:
    """ColorDB discovery should ignore vendor-global predictive assets with mismatched channel sets."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "dbs",
        "PLA",
        "BambuLab",
        "RYBW_008_5L.json",
    )
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    native_ctx = discover_native_reference_context(path, data)

    assert native_ctx is not None
    assert native_ctx.source_kind == SOURCE_KIND_COLORD_DB
    assert native_ctx.package_path is None
    assert native_ctx.stage_model_path is None
    assert len(native_ctx.supported_modes) == 1
    assert native_ctx.supported_modes[0]["color_layers"] == 5
    assert abs(native_ctx.supported_modes[0]["layer_height_mm"] - 0.08) < 1e-3
    assert native_ctx.supported_modes[0]["layer_order"] == "Top2Bottom"


def test_direct_reference_colordb_stays_single_db_even_when_global_predictive_assets_exist() -> None:
    """Direct ColorDB selections should remain single-db exact lookups, even if a compatible global pack/model exists."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "dbs",
        "PLA",
        "BambuLab",
        "RYBWCMKG_008_5L_001.json",
    )

    _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)

    assert metadata.get_source_kind() == SOURCE_KIND_COLORD_DB
    assert metadata.extensions.get("native_model_package_path") is None
    assert metadata.extensions.get("native_stage_model_path") is None
    assert len(metadata.get_supported_modes()) == 1
    mode = metadata.get_supported_modes()[0]
    assert mode["color_layers"] == 5
    assert abs(mode["layer_height_mm"] - 0.08) < 1e-3
    assert mode["layer_order"] == "Top2Bottom"


def test_native_colordb_infers_cmyw_variant_from_palette_contents() -> None:
    """Native ColorDB loaders should infer the 4-color CMYW variant from palette names, not just palette size."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "dbs",
        "PLA",
        "BambuLab",
        "CMYW_008_5L.json",
    )

    _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)

    assert metadata.color_mode == "4-Color (CMYW)"


def test_native_colordb_infers_rybwgk_variant_from_palette_contents() -> None:
    """Native ColorDB loaders should infer the 6-color RYBWGK variant from palette names, not just palette size."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "dbs",
        "PLA",
        "Aliz",
        "BRGYKW_008_5L.json",
    )

    _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)

    assert metadata.color_mode == "6-Color (RYBWGK 1296)"


def test_native_model_package_infer_color_mode_uses_channel_contents() -> None:
    """infer_color_mode should use msgpack channel contents, not only channel count, for ambiguous 4-color packages."""
    payload = {
        "schema_version": 2,
        "name": "TestPackage",
        "scope": {"vendor": "BambuLab", "material_type": "PLA"},
        "channel_keys": [
            "White|PLA Basic",
            "Yellow|PLA Basic",
            "Magenta|PLA Basic",
            "Cyan|PLA Basic",
        ],
        "defaults": {"threshold": 5.0, "margin": 0.7},
        "modes": [],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "native_cmyw.msgpack")
        with open(path, "wb") as fh:
            fh.write(msgpack.packb(payload, use_bin_type=True))

        inferred = LUTManager.infer_color_mode("ReferencePack - native_cmyw", path)

    assert inferred == "4-Color (CMYW)"


def test_native_model_package_bundle_includes_subset_mode_colordbs() -> None:
    """Vendor bundle discovery for an 8-channel package should retain compatible 4-channel DB members as subset modes."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "model_packs",
        "bambulab_pla.msgpack",
    )

    _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)
    native_db_paths = metadata.extensions.get("native_db_paths") or []
    native_db_names = {os.path.basename(item) for item in native_db_paths}

    assert "CMYW_008_5L.json" in native_db_names
    assert "RYBW_008_5L.json" in native_db_names
    assert "RYBWCMKG_008_5L_001.json" in native_db_names


def test_native_model_package_metadata_load_does_not_expose_arbitrary_first_mode_exact_stacks() -> None:
    """Direct msgpack metadata loads should expose runtime metadata without fake first-mode exact stacks."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "model_packs",
        "bambulab_pla.msgpack",
    )

    rgb, stacks, metadata = LUTManager.load_lut_with_metadata(path)

    assert metadata.get_source_kind() == "predictive_package"
    assert metadata.supports_predictive_match() is True
    assert rgb.shape == (0, 3)
    assert stacks is None
    assert any(mode["mode_key"] == "0.08x10" for mode in metadata.get_supported_modes())


def test_native_stage_model_metadata_uses_white_base_channel_from_compatible_package() -> None:
    """Native stage-model metadata should inherit the correct white base channel instead of hardcoded index 0."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "models",
        "forward",
        "bambulab_pla_stage_B.json",
    )

    _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)

    assert metadata.get_source_kind() == "predictive_stage_model"
    assert metadata.palette[metadata.base_channel_idx].color.lower() == "white"
    assert any(mode["mode_key"] == "0.08x10" for mode in metadata.get_supported_modes())


def test_native_bundle_selection_10l_lookup_converts_db_recipes_to_requested_layer_count() -> None:
    """Native DB-first lookups should convert selected DB recipes to the requested target layer count."""
    bundle_path, _display_name = LUTManager.resolve_source_selection(
        source_kind="native_bundle",
        material_type="PLA",
        vendor="BambuLab",
        db_names=["CMYW_008_5L.json", "RYBW_008_5L.json"],
    )

    from core.pipeline.processing_ops.lut_loader import load_lut

    loaded = load_lut(bundle_path, "8-Color Max", color_layers=10, layer_height_mm=0.08, model_enable=False)

    assert loaded["lut_rgb"].shape[0] == 2048
    assert loaded["ref_stacks"].shape == (2048, 10)


def test_native_stage_model_non_exact_mode_lookup_keeps_converted_padding_and_white_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stage-model lookup should keep converted 10-layer DB stacks and use the resolved white base channel."""
    stage_json = {
        "parameters": {
            "channels": [
                {"color_name": "bambugreen", "E": [0.0, 0.68, 0.26]},
                {"color_name": "black", "E": [0.0, 0.0, 0.0]},
                {"color_name": "blue", "E": [0.04, 0.16, 0.54]},
                {"color_name": "cyan", "E": [0.0, 0.7, 0.7]},
                {"color_name": "magenta", "E": [0.7, 0.0, 0.7]},
                {"color_name": "red", "E": [0.7, 0.0, 0.0]},
                {"color_name": "white", "E": [1.0, 1.0, 1.0]},
                {"color_name": "yellow", "E": [0.9, 0.85, 0.1]},
            ]
        },
        "selected_db_paths": ["fake_db.json"],
    }
    native_ctx = NativeReferenceContext(
        source_kind=SOURCE_KIND_STAGE_MODEL,
        primary_path="fake_stage.json",
        package_path=os.path.join(
            "reference",
            "ChromaPrint3D",
            "data",
            "model_packs",
            "bambulab_pla.msgpack",
        ),
        stage_model_path="fake_stage.json",
        db_paths=("fake_db.json",),
        supported_modes=(supported_mode_dict(10, 0.08, layer_order="Top2Bottom"),),
        channel_keys=(
            "bambugreen|PLA Basic",
            "black|PLA Basic",
            "blue|PLA Basic",
            "cyan|PLA Basic",
            "magenta|PLA Basic",
            "red|PLA Basic",
            "white|PLA Basic",
            "yellow|PLA Basic",
        ),
        vendor="BambuLab",
        material_type="PLA",
    )

    def _fake_select_native_db_paths_for_mode(*_args, **_kwargs):
        return ()

    def _fake_load_keyed_json(_path: str, _display: str):
        rgb = np.array([[255, 255, 255], [255, 230, 0]], dtype=np.uint8)
        stacks = np.array([[0, 1, 2, 3, 4], [4, 3, 2, 1, 0]], dtype=np.int32)
        metadata = LUTMetadata(
            palette=[
                PaletteEntry(color="bambugreen", material="PLA Basic"),
                PaletteEntry(color="black", material="PLA Basic"),
                PaletteEntry(color="blue", material="PLA Basic"),
                PaletteEntry(color="cyan", material="PLA Basic"),
                PaletteEntry(color="yellow", material="PLA Basic"),
            ],
            layer_height_mm=0.08,
            layer_order="Top2Bottom",
            base_channel_idx=4,
        )
        return rgb, stacks, metadata

    def _fake_load_native_bundle_exact_lookup(temp_meta: LUTMetadata, *, color_layers: int, layer_height_mm: float, layer_order: str | None):
        assert temp_meta.base_channel_idx == 6
        assert color_layers == 10
        assert abs(layer_height_mm - 0.08) <= 1e-6
        assert layer_order == "Top2Bottom"
        converted = np.array(
            [
                [0, 1, 2, 3, 4, 6, 6, 6, 6, 6],
                [4, 3, 2, 1, 0, 6, 6, 6, 6, 6],
            ],
            dtype=np.int32,
        )
        rgb = np.array([[255, 255, 255], [255, 230, 0]], dtype=np.uint8)
        return rgb, converted

    monkeypatch.setattr("utils.lut_manager.select_native_db_paths_for_mode", _fake_select_native_db_paths_for_mode)
    monkeypatch.setattr(LUTManager, "_load_keyed_json", staticmethod(_fake_load_keyed_json))
    monkeypatch.setattr(LUTManager, "load_native_bundle_exact_lookup", staticmethod(_fake_load_native_bundle_exact_lookup))

    rgb, stacks, metadata = LUTManager._load_native_stage_model_json(
        "fake_stage.json",
        "fake_stage",
        stage_json,
        native_ctx,
    )

    assert metadata.base_channel_idx == 6
    assert metadata.palette[metadata.base_channel_idx].color.lower() == "white"
    assert rgb.shape == (2, 3)
    assert stacks.shape == (2, 10)
    assert np.all(stacks[:, 5:] == 6)


def test_native_bundle_selection_path_limits_runtime_db_subset() -> None:
    """Selecting a native bundle subset should persist only the requested DB names into the runtime metadata."""
    selected_db_names = ["CMYW_008_5L.json", "RYBW_008_5L.json"]

    bundle_path, _display_name = LUTManager.resolve_source_selection(
        source_kind="native_bundle",
        material_type="PLA",
        vendor="BambuLab",
        db_names=selected_db_names,
    )

    _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(bundle_path)
    native_db_paths = metadata.extensions.get("native_db_paths") or []
    native_db_names = sorted(os.path.basename(item) for item in native_db_paths)

    assert native_db_names == sorted(selected_db_names)


def test_native_model_package_float_space_lab_preview_conversion_uses_reference_semantics() -> None:
    """Native model packages should decode float-space OpenCV Lab payloads without blue bias."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "model_packs",
        "bambulab_pla.msgpack",
    )

    with open(path, "rb") as fh:
        payload = msgpack.unpackb(fh.read(), raw=False)

    first_mode = next(item for item in payload["modes"] if isinstance(item, dict) and int(item.get("num_candidates", 0)) > 0)
    num_candidates = int(first_mode["num_candidates"])
    pred_lab = np.frombuffer(first_mode["pred_lab"], dtype="<f4").reshape(num_candidates, 3).astype(np.float32)
    rgb = opencv_lab_to_rgb_uint8(pred_lab[:8])

    assert np.all((pred_lab[:8, 0] >= 0.0) & (pred_lab[:8, 0] <= 100.0))
    assert np.all((pred_lab[:8, 1:] >= -127.0) & (pred_lab[:8, 1:] <= 127.0))
    assert rgb.shape == (8, 3)
    assert np.unique(rgb, axis=0).shape[0] >= 4
    assert np.all(rgb[:, 2] <= 245)
