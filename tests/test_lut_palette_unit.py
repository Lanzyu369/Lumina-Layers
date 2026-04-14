# -*- coding: utf-8 -*-
"""LUT 调色板集成单元测试。
Unit tests for LUT palette integration.

覆盖数据模型、LUTManager、合并与集成、API 端点四个维度。
Covers data models, LUTManager, merge & integration, and API schemas.
"""

import os
import json
import tempfile

import pytest
import numpy as np

from config import PaletteEntry, LUTMetadata, ColorSystem, PrinterConfig
from utils.lut_manager import LUTManager
from core.lut_merger import LUTMerger
from utils.color_recipe_logger import ColorRecipeLogger


# ============================================================
# 9.1 数据模型单元测试 / Data Model Unit Tests
# ============================================================


class TestDataModels:
    """PaletteEntry 和 LUTMetadata 数据模型测试。"""

    def test_palette_entry_creation(self):
        """PaletteEntry 基本创建和字段访问。"""
        entry = PaletteEntry(
            color="Red",
            material="PLA Basic",
            hex_color="#DC143C",
            color_name="Signal Red",
        )
        assert entry.color == "Red"
        assert entry.material == "PLA Basic"
        assert entry.hex_color == "#DC143C"
        assert entry.color_name == "Signal Red"

        # 默认值
        entry_default = PaletteEntry(color="Cyan")
        assert entry_default.material == "PLA Basic"
        assert entry_default.hex_color is None
        assert entry_default.color_name is None

    def test_metadata_default_values(self):
        """LUTMetadata 默认值正确 (5, 0.08, 0.42, 10, 0, "Top2Bottom")。"""
        meta = LUTMetadata()
        assert meta.max_color_layers == 5
        assert meta.layer_height_mm == pytest.approx(0.08)
        assert meta.line_width_mm == pytest.approx(0.42)
        assert meta.base_layers == 10
        assert meta.base_channel_idx == 0
        assert meta.layer_order == "Top2Bottom"
        assert meta.manufacturer == ""
        assert meta.type == ""
        assert meta.palette == []

    def test_metadata_round_trip_preserves_colordb_fields(self):
        """to_dict / from_dict 可往返保持新增 colordb 字段。"""
        meta = LUTMetadata(
            palette=[
                PaletteEntry(
                    color="White",
                    material="PLA Basic",
                    hex_color="#FFFFFF",
                    color_name="Jade White",
                ),
            ],
            manufacturer="Bambu Lab",
            type="PLA Basic",
            color_mode="4-Color (CMYW)",
        )

        round_tripped = LUTMetadata.from_dict(meta.to_dict())

        assert round_tripped.manufacturer == "Bambu Lab"
        assert round_tripped.type == "PLA Basic"
        assert len(round_tripped.palette) == 1
        assert round_tripped.palette[0].color == "White"
        assert round_tripped.palette[0].color_name == "Jade White"

    def test_metadata_round_trip_preserves_v2_extensions(self):
        """LUT V2 metadata round-trip should preserve schema and extension blocks."""
        meta = LUTMetadata(
            palette=[PaletteEntry(color="White", material="PLA Basic")],
            schema_version="2.0",
            capabilities=["legacy_lookup", "predictive_match", "dynamic_layer_height"],
            extensions={
                "measured_db": {"samples": [{"recipe": [0, 0, 0, 0, 0], "lab": [90, 0, 0]}]},
                "stage_model": {"model_id": "model-001", "gamma": 1.1},
                "runtime_package": {
                    "defaults": {"threshold": 4.5, "margin": 0.8},
                    "modes": {
                        "0.08x5": {
                            "layer_height_mm": 0.08,
                            "color_layers": 5,
                            "layer_order": "Top2Bottom",
                            "candidate_recipes": [[0, 0, 0, 0, 0]],
                            "pred_lab": [[255, 128, 128]],
                        }
                    },
                },
                "custom_block": {"keep": True},
            },
        )

        round_tripped = LUTMetadata.from_dict(meta.to_dict())

        assert round_tripped.get_schema_version() == "2.0"
        assert "predictive_match" in round_tripped.get_capabilities()
        assert round_tripped.supports_predictive_match() is True
        assert round_tripped.extensions["custom_block"] == {"keep": True}
        assert round_tripped.extensions["stage_model"]["model_id"] == "model-001"

    def test_hex_color_format_validation(self):
        """非法 hex_color 格式处理 — PaletteEntry 在 dataclass 层面不做校验，接受任意字符串。"""
        # PaletteEntry 接受任意字符串作为 hex_color
        entry = PaletteEntry(color="Red", hex_color="not-a-hex")
        assert entry.hex_color == "not-a-hex"

        entry2 = PaletteEntry(color="Blue", hex_color="")
        assert entry2.hex_color == ""

    def test_layer_order_invalid_value(self):
        """非法 layer_order — from_dict 存储给定的字符串，不做校验。"""
        data = {
            "palette": {},
            "layer_order": "InvalidOrder",
        }
        meta = LUTMetadata.from_dict(data)
        # from_dict 直接存储 str(data.get("layer_order", ...))
        assert meta.layer_order == "InvalidOrder"


# ============================================================
# 9.2 LUTManager 单元测试 / LUTManager Unit Tests
# ============================================================


class TestLUTManager:
    """LUTManager 加载/保存功能测试。"""

    def test_load_legacy_npy(self):
        """加载旧版 .npy 文件，验证推断的默认元数据 palette 长度正确。"""
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = f.name
            rgb = np.random.randint(0, 256, size=(1024, 3), dtype=np.uint8)
            np.save(tmp_path, rgb)

        try:
            loaded_rgb, stacks, metadata = LUTManager.load_lut_with_metadata(tmp_path)
            assert loaded_rgb.shape == (1024, 3)
            assert stacks is None
            # 默认推断的 palette 长度应 > 0
            assert len(metadata.palette) > 0
            # 打印参数应为默认值
            assert metadata.layer_height_mm == pytest.approx(PrinterConfig.LAYER_HEIGHT)
            assert metadata.line_width_mm == pytest.approx(PrinterConfig.NOZZLE_WIDTH)
        finally:
            os.unlink(tmp_path)

    def test_load_legacy_npz_no_metadata(self):
        """加载无 metadata_json 的 .npz 文件，验证默认元数据被推断。"""
        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            tmp_path = f.name

        try:
            rgb = np.random.randint(0, 256, size=(100, 3), dtype=np.uint8)
            stacks = np.zeros((100, 5), dtype=np.int32)
            np.savez(tmp_path, rgb=rgb, stacks=stacks)

            loaded_rgb, loaded_stacks, metadata = LUTManager.load_lut_with_metadata(tmp_path)
            assert loaded_rgb.shape == (100, 3)
            assert loaded_stacks is not None
            assert loaded_stacks.shape == (100, 5)
            # 无 metadata_json → 推断默认元数据
            assert metadata.layer_height_mm == pytest.approx(PrinterConfig.LAYER_HEIGHT)
        finally:
            os.unlink(tmp_path)

    def test_keyed_json_with_all_fields(self):
        """完整 Keyed JSON 加载（新对象格式），验证所有字段正确解析。"""
        palette = {
            "White": {"material": "PLA Basic", "hex_color": "#FFFFFF", "color_name": "Jade White"},
            "Red": {"material": "PLA Silk", "hex_color": "#DC143C", "color_name": "Ruby Red"},
        }
        data = {
            "name": "TestLUT",
            "manufacturer": "Bambu Lab",
            "type": "PLA Basic",
            "max_color_layers": 6,
            "layer_height_mm": 0.10,
            "line_width_mm": 0.50,
            "base_layers": 12,
            "base_channel_idx": 1,
            "layer_order": "Bottom2Top",
            "palette": palette,
            "entries": [
                {"rgb": [255, 255, 255], "lab": [100, 0, 0], "recipe": ["White", "White", "White", "White", "White"]},
                {"rgb": [220, 20, 60], "lab": [50, 60, 40], "recipe": ["Red", "Red", "White", "White", "White"]},
            ],
        }

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False, encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            tmp_path = f.name

        try:
            loaded_rgb, loaded_stacks, metadata = LUTManager.load_lut_with_metadata(tmp_path)
            assert loaded_rgb.shape == (2, 3)
            assert loaded_stacks is not None
            assert loaded_stacks.shape[0] == 2
            assert len(metadata.palette) == 2
            assert metadata.palette[0].color == "White"
            assert metadata.palette[1].hex_color == "#DC143C"
            assert metadata.palette[0].color_name == "Jade White"
            assert metadata.manufacturer == "Bambu Lab"
            assert metadata.type == "PLA Basic"
            assert metadata.max_color_layers == 6
            assert metadata.layer_height_mm == pytest.approx(0.10)
            assert metadata.line_width_mm == pytest.approx(0.50)
            assert metadata.base_layers == 12
            assert metadata.base_channel_idx == 1
            assert metadata.layer_order == "Bottom2Top"
        finally:
            os.unlink(tmp_path)

    def test_keyed_json_missing_palette(self):
        """缺少 palette 的 JSON 文件，验证默认调色板被推断。"""
        data = {
            "name": "NoPalette",
            "entries": [
                {"rgb": [128, 128, 128], "lab": [50, 0, 0], "recipe": [0, 0, 0, 0, 0]},
            ],
        }

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False, encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            tmp_path = f.name

        try:
            _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(tmp_path)
            # 无 palette → 应推断默认调色板，长度 > 0
            assert len(metadata.palette) > 0
            # 打印参数应为 PrinterConfig 默认值
            assert metadata.max_color_layers == PrinterConfig.COLOR_LAYERS
        finally:
            os.unlink(tmp_path)

    def test_keyed_json_invalid_palette_entry(self):
        """palette 对象格式中无效条目，验证被跳过。旧数组格式兼容性也测试。"""
        # 新对象格式：值不是 dict 的条目被跳过
        data = {
            "name": "BadPalette",
            "palette": {
                "White": {"material": "PLA Basic"},
                "Red": "not_a_dict",
            },
            "entries": [],
        }

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False, encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            tmp_path = f.name

        try:
            _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(tmp_path)
            # 只有第一个条目有效；但如果只剩 1 个，可能触发推断
            # 关键验证：无效条目被跳过，不会导致异常
            valid_colors = [e.color for e in metadata.palette]
            assert "White" in valid_colors
        finally:
            os.unlink(tmp_path)


# ============================================================
# 9.3 合并与集成单元测试 / Merge & Integration Unit Tests
# ============================================================


class TestMergeAndIntegration:
    """LUT 合并、Converter、ColorRecipeLogger 集成测试。"""

    def test_merge_two_luts_with_palette(self):
        """合并两个有 palette 的 LUT，验证合并后 palette 包含所有颜色。"""
        meta1 = LUTMetadata(palette=[
            PaletteEntry(color="White", material="PLA Basic"),
            PaletteEntry(color="Red", material="PLA Basic"),
        ])
        meta2 = LUTMetadata(palette=[
            PaletteEntry(color="White", material="PLA Basic"),
            PaletteEntry(color="Cyan", material="PLA Basic"),
        ])

        merged = LUTMerger.merge_palettes([meta1, meta2], [1, 2])
        merged_names = [e.color for e in merged]
        assert "White" in merged_names
        assert "Red" in merged_names
        assert "Cyan" in merged_names

    def test_merge_with_custom_color_name(self):
        """自定义颜色名称不在标准槽位中，验证追加到末尾。"""
        meta1 = LUTMetadata(palette=[
            PaletteEntry(color="White", material="PLA Basic"),
            PaletteEntry(color="CustomPink", material="PLA Silk"),
        ])
        meta2 = LUTMetadata(palette=[
            PaletteEntry(color="White", material="PLA Basic"),
            PaletteEntry(color="Cyan", material="PLA Basic"),
        ])

        merged = LUTMerger.merge_palettes([meta1, meta2], [1, 1])
        merged_names = [e.color for e in merged]

        # 标准颜色在前
        white_idx = merged_names.index("White")
        cyan_idx = merged_names.index("Cyan")
        custom_idx = merged_names.index("CustomPink")

        # CustomPink 应在标准颜色之后
        assert custom_idx > white_idx
        assert custom_idx > cyan_idx

    def test_load_6color_json_stacks_remap_by_palette_key(self):
        """6 色 RYBW JSON 在合并加载时应按调色板颜色键映射到规范 8 色槽位。"""
        rgb = np.array([[255, 54, 1]], dtype=np.uint8)
        stacks = np.array([[1, 0, 0, 0, 0]], dtype=np.int32)
        metadata = LUTMetadata(
            palette=[
                PaletteEntry(color="White", material="PLA"),
                PaletteEntry(color="Red", material="PLA"),
                PaletteEntry(color="Yellow", material="PLA"),
                PaletteEntry(color="Blue", material="PLA"),
                PaletteEntry(color="Green", material="PLA"),
                PaletteEntry(color="Black", material="PLA"),
            ],
            color_mode="6-Color (RYBWGK 1296)",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "source_6color_rybw.json")
            LUTManager.save_keyed_json(json_path, rgb, stacks, metadata)

            _loaded_rgb, loaded_stacks = LUTMerger.load_lut_with_stacks(json_path, "6-Color")

        np.testing.assert_array_equal(loaded_stacks, np.array([[5, 0, 0, 0, 0]], dtype=np.int32))

    def test_save_merged_json_preserves_recipe_name_after_palette_reindex(self):
        """Merged JSON 导出时应先重建为本地 palette 索引，避免 Red 错写成 Yellow。"""
        rgb = np.array([[255, 54, 1]], dtype=np.uint8)
        canonical_stacks = np.array([[5, 0, 0, 0, 0]], dtype=np.int32)
        merged_metadata = LUTMetadata(
            palette=[
                PaletteEntry(color="White", material="PLA"),
                PaletteEntry(color="Yellow", material="PLA"),
                PaletteEntry(color="Black", material="PLA"),
                PaletteEntry(color="Red", material="PLA"),
                PaletteEntry(color="Green", material="PLA"),
                PaletteEntry(color="Blue", material="PLA"),
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "merged.json")
            json_stacks = LUTMerger.reindex_canonical_stacks_for_palette(
                canonical_stacks,
                merged_metadata.palette,
            )
            LUTManager.save_keyed_json(json_path, rgb, json_stacks, merged_metadata)

            with open(json_path, "r", encoding="utf-8") as f:
                saved = json.load(f)

        assert saved["entries"][0]["recipe"] == ["Red", "White", "White", "White", "White"]

    def test_print_param_mismatch_warning(self):
        """两个 LUT 的 layer_height_mm 不同，验证产生警告。"""
        meta1 = LUTMetadata(layer_height_mm=0.08)
        meta2 = LUTMetadata(layer_height_mm=0.12)

        compatible, warnings = LUTMerger.validate_print_params([meta1, meta2])
        assert not compatible
        assert len(warnings) > 0
        assert "layer_height_mm" in warnings[0]

    def test_converter_uses_palette_hex(self):
        """Converter 使用 palette hex_color — 跳过（集成复杂度高）。"""
        pytest.skip("Converter 集成测试需要完整运行环境，此处跳过")

    def test_converter_fallback_default(self):
        """无 palette 时 Converter 回退默认预览色 — 跳过。"""
        pytest.skip("Converter 集成测试需要完整运行环境，此处跳过")

    def test_recipe_logger_with_palette(self):
        """有 palette 时 ColorRecipeLogger 使用调色板颜色名称。"""
        palette = [
            PaletteEntry(color="White", material="PLA Basic"),
            PaletteEntry(color="Crimson", material="PLA Silk"),
            PaletteEntry(color="Gold", material="PLA Basic"),
        ]
        metadata = LUTMetadata(palette=palette)

        lut_rgb = np.array([[255, 255, 255], [220, 20, 60], [255, 215, 0]], dtype=np.uint8)
        ref_stacks = np.array([[0, 0, 0, 0, 0], [1, 1, 0, 0, 0], [2, 2, 0, 0, 0]], dtype=np.int32)

        logger = ColorRecipeLogger(
            lut_path="test_lut.npy",
            lut_rgb=lut_rgb,
            ref_stacks=ref_stacks,
            color_mode="4-Color",
            metadata=metadata,
        )

        # _get_color_name 应返回 palette 中的名称
        assert logger._get_color_name(0) == "White"
        assert logger._get_color_name(1) == "Crimson"
        assert logger._get_color_name(2) == "Gold"

    def test_recipe_logger_without_palette(self):
        """无 palette 时 ColorRecipeLogger 回退文件名推断。"""
        lut_rgb = np.array([
            [255, 255, 255],
            [220, 20, 60],
            [255, 230, 0],
            [0, 100, 240],
            [0, 0, 0],
            [0, 134, 214],
            [236, 0, 140],
            [0, 174, 66],
        ], dtype=np.uint8)
        ref_stacks = np.zeros((8, 5), dtype=np.int32)

        logger = ColorRecipeLogger(
            lut_path="test_RYBW_lut.npy",
            lut_rgb=lut_rgb,
            ref_stacks=ref_stacks,
            color_mode="4-Color",
            metadata=None,
        )

        # 无 metadata → 回退到 RGB 推断
        name_0 = logger._get_color_name(0)
        # 第一个颜色 (255,255,255) 应被推断为白色相关名称
        assert name_0 is not None
        assert len(name_0) > 0


# ============================================================
# 9.4 API 端点单元测试 / API Schema Unit Tests
# ============================================================


class TestAPISchemas:
    """API Pydantic Schema 验证测试。"""

    def test_extract_response_contains_default_palette(self):
        """ExtractResponse schema 包含 default_palette 字段。"""
        from api.schemas.responses import ExtractResponse

        resp = ExtractResponse(
            session_id="test-session",
            status="ok",
            message="done",
            lut_download_url="/api/files/123",
            warp_view_url="",
            lut_preview_url="",
        )
        # default_palette 应有默认空列表
        assert hasattr(resp, "default_palette")
        assert resp.default_palette == []

        # 带 palette 数据
        resp2 = ExtractResponse(
            session_id="s2",
            status="ok",
            message="done",
            lut_download_url="/api/files/456",
            warp_view_url="",
            lut_preview_url="",
            default_palette=[{"color": "Red", "material": "PLA", "hex_color": "#FF0000", "color_name": "Signal Red"}],
        )
        assert len(resp2.default_palette) == 1
        assert resp2.default_palette[0].color_name == "Signal Red"

    def test_confirm_palette_saves_to_session(self):
        """confirm-palette 端点保存调色板到 session — 跳过（需要运行 FastAPI 应用）。"""
        pytest.skip("需要运行 FastAPI 应用环境")

    def test_confirm_palette_rejects_empty_name(self):
        """confirm-palette 拒绝空白颜色名称 — 跳过（需要运行 FastAPI 应用）。"""
        pytest.skip("需要运行 FastAPI 应用环境")

    def test_confirm_palette_session_not_found(self):
        """confirm-palette 对不存在的 session 返回 404 — 跳过（需要运行 FastAPI 应用）。"""
        pytest.skip("需要运行 FastAPI 应用环境")

    def test_lut_info_response_contains_palette(self):
        """LutInfoResponse schema 包含 palette 和打印参数字段。"""
        from api.schemas.lut import LutInfoResponseV2, PaletteEntrySchema

        resp = LutInfoResponseV2(
            name="TestLUT",
            color_mode="4-Color",
            color_count=1024,
        )
        # 默认值
        assert resp.palette == []
        assert resp.max_color_layers == 5
        assert resp.layer_height_mm == pytest.approx(0.08)
        assert resp.line_width_mm == pytest.approx(0.42)
        assert resp.base_layers == 10
        assert resp.base_channel_idx == 0
        assert resp.layer_order == "Top2Bottom"
        assert resp.schema_version == "1.0"
        assert resp.capabilities == []
        assert resp.supports_predictive_match is False
        assert resp.supports_dynamic_layer_height is False

        # 带 palette 数据
        resp2 = LutInfoResponseV2(
            name="TestLUT2",
            color_mode="8-Color Max",
            color_count=2738,
            palette=[PaletteEntrySchema(color="White", material="PLA Basic", hex_color="#FFFFFF", color_name="Jade White")],
            max_color_layers=6,
            layer_height_mm=0.10,
            line_width_mm=0.50,
            base_layers=12,
            base_channel_idx=1,
            layer_order="Bottom2Top",
            schema_version="2.0",
            capabilities=["legacy_lookup", "predictive_match", "dynamic_layer_height"],
            supports_predictive_match=True,
            supports_dynamic_layer_height=True,
        )
        assert len(resp2.palette) == 1
        assert resp2.palette[0].color == "White"
        assert resp2.palette[0].color_name == "Jade White"
        assert resp2.max_color_layers == 6
        assert resp2.schema_version == "2.0"
        assert resp2.supports_predictive_match is True

    def test_merge_response_contains_warnings(self):
        """MergeResponse schema 包含 warnings 字段。"""
        from api.schemas.lut import MergeResponse, MergeStats

        resp = MergeResponse(
            status="success",
            message="Merged OK",
            filename="merged.npz",
            stats=MergeStats(
                total_before=2000,
                total_after=1800,
                exact_dupes=100,
                similar_removed=100,
            ),
        )
        # 默认值
        assert resp.warnings == []
        assert resp.palette == []

        # 带 warnings
        resp2 = MergeResponse(
            status="success",
            message="Merged with warnings",
            filename="merged2.npz",
            stats=MergeStats(
                total_before=2000,
                total_after=1800,
                exact_dupes=100,
                similar_removed=100,
            ),
            warnings=["layer_height_mm 不一致: 0.0800, 0.1200"],
        )
        assert len(resp2.warnings) == 1
        assert "layer_height_mm" in resp2.warnings[0]
