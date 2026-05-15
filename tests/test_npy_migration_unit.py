#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""NPY 到 JSON 迁移单元测试。
Unit tests for NPY-to-JSON migration.

验证配置路径、preserve_files、MIME 映射、向后兼容加载、文件扫描和上传转换。
Validates config path, preserve_files, MIME mapping, backward-compatible loading,
file scanning, and upload auto-conversion.

需求: 1.1, 1.2, 8.1, 10.1, 7.1, 7.3, 12.1, 12.3
"""

import os
import json
import inspect
import tempfile
import shutil

import pytest
import numpy as np

from config import LUT_FILE_PATH, LUTMetadata, PaletteEntry, PrinterConfig
from utils.lut_manager import LUTManager
from api.file_bridge import _guess_media_type
from utils.stats import Stats

# ============================================================
# 8.1.1 config.LUT_FILE_PATH 后缀测试
# Validates: Requirements 1.1
# ============================================================


class TestConfigLUTFilePath:
    """验证 config.LUT_FILE_PATH 后缀为 .json。"""

    def test_lut_file_path_ends_with_json(self):
        """LUT_FILE_PATH 应以 .json 结尾，而非 .npy。"""
        assert LUT_FILE_PATH.endswith(".json"), f"LUT_FILE_PATH 应以 .json 结尾，实际值: {LUT_FILE_PATH}"

    def test_lut_file_path_contains_lumina_lut(self):
        """LUT_FILE_PATH 文件名应为 lumina_lut.json。"""
        basename = os.path.basename(LUT_FILE_PATH)
        assert basename == "lumina_lut.json", f"文件名应为 lumina_lut.json，实际值: {basename}"


# ============================================================
# 8.1.2 utils/stats.py preserve_files 测试
# Validates: Requirements 1.2
# ============================================================


class TestStatsPreserveFiles:
    """验证 Stats 模块两处 preserve_files 包含 lumina_lut.json。"""

    def test_clear_output_preserve_files_contains_json(self):
        """clear_output() 中的 preserve_files 应包含 'lumina_lut.json'。"""
        source = inspect.getsource(Stats.clear_output)
        assert (
            '"lumina_lut.json"' in source or "'lumina_lut.json'" in source
        ), "clear_output() 的 preserve_files 应包含 'lumina_lut.json'"

    def test_clear_output_preserve_files_not_npy(self):
        """clear_output() 中的 preserve_files 不应包含 'lumina_lut.npy'。"""
        source = inspect.getsource(Stats.clear_output)
        assert (
            '"lumina_lut.npy"' not in source and "'lumina_lut.npy'" not in source
        ), "clear_output() 的 preserve_files 不应包含 'lumina_lut.npy'"

    def test_get_output_size_preserve_files_contains_json(self):
        """get_output_size() 中的 preserve_files 应包含 'lumina_lut.json'。"""
        source = inspect.getsource(Stats.get_output_size)
        assert (
            '"lumina_lut.json"' in source or "'lumina_lut.json'" in source
        ), "get_output_size() 的 preserve_files 应包含 'lumina_lut.json'"

    def test_get_output_size_preserve_files_not_npy(self):
        """get_output_size() 中的 preserve_files 不应包含 'lumina_lut.npy'。"""
        source = inspect.getsource(Stats.get_output_size)
        assert (
            '"lumina_lut.npy"' not in source and "'lumina_lut.npy'" not in source
        ), "get_output_size() 的 preserve_files 不应包含 'lumina_lut.npy'"


# ============================================================
# 8.1.3 api/file_bridge.py MIME 映射测试
# Validates: Requirements 10.1
# ============================================================


class TestFileBridgeMIME:
    """验证 _guess_media_type() 对 .json 返回 application/json。"""

    def test_json_mime_type(self):
        """.json 文件应返回 application/json。"""
        result = _guess_media_type("output/lumina_lut.json")
        assert result == "application/json"

    def test_json_mime_type_uppercase(self):
        """.JSON 大写扩展名也应返回 application/json。"""
        result = _guess_media_type("output/lumina_lut.JSON")
        assert result == "application/json"

    def test_npy_mime_type_still_works(self):
        """.npy 文件仍应返回 application/octet-stream。"""
        result = _guess_media_type("data/old_lut.npy")
        assert result == "application/octet-stream"


# ============================================================
# 8.1.4 向后兼容加载测试 (.npy → load_lut_with_metadata)
# Validates: Requirements 8.1, 12.3
# ============================================================


class TestBackwardCompatibleLoading:
    """验证 .npy 文件可被 LUTManager.load_lut_with_metadata() 正确加载。"""

    def test_load_npy_returns_correct_rgb(self):
        """.npy 文件加载后 RGB 数据应与原始数据一致。"""
        rgb_original = np.array(
            [
                [255, 0, 0],
                [0, 255, 0],
                [0, 0, 255],
                [128, 128, 128],
            ],
            dtype=np.uint8,
        )

        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = f.name
            np.save(tmp_path, rgb_original)

        try:
            loaded_rgb, stacks, metadata = LUTManager.load_lut_with_metadata(tmp_path)
            np.testing.assert_array_equal(loaded_rgb, rgb_original)
            assert stacks is None, ".npy 文件不应有 stacks 数据"
            assert isinstance(metadata, LUTMetadata)
            assert len(metadata.palette) > 0, "应推断出默认 palette"
        finally:
            os.unlink(tmp_path)

    def test_load_npy_grid_shape(self):
        """加载 3D shape 的 .npy 文件（如 32x32x3 网格），验证正确返回。"""
        rgb_grid = np.random.randint(0, 256, size=(32, 32, 3), dtype=np.uint8)

        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = f.name
            np.save(tmp_path, rgb_grid)

        try:
            loaded_rgb, stacks, metadata = LUTManager.load_lut_with_metadata(tmp_path)
            # .npy 加载返回原始 shape
            assert loaded_rgb.shape == (32, 32, 3)
            assert stacks is None
        finally:
            os.unlink(tmp_path)


# ============================================================
# 8.1.5 get_all_lut_files() 扫描 .json 文件测试
# Validates: Requirements 7.1
# ============================================================


class TestGetAllLutFiles:
    """验证 get_all_lut_files() 能扫描到 .json 文件。"""

    @pytest.fixture(autouse=True)
    def _invalidate_preset_cache(self):
        """Drop ``get_all_lut_files`` cache around every test in this class.

        Without this, the 30 s module-level cache populated by the first test
        would be reused by the second one even after we point
        ``LUT_PRESET_DIR`` at a fresh tmp directory, causing the second test
        to read stale scan results from the first directory.
        """

        LUTManager.invalidate_preset_cache()
        try:
            yield
        finally:
            LUTManager.invalidate_preset_cache()

    def test_scan_finds_json_files(self):
        """.json 文件应被 get_all_lut_files() 扫描到。"""
        # 创建临时预设目录
        tmp_dir = tempfile.mkdtemp()
        original_dir = LUTManager.LUT_PRESET_DIR

        try:
            LUTManager.LUT_PRESET_DIR = tmp_dir

            # 创建测试 .json 文件
            json_data = {
                "name": "test_lut",
                "palette": [],
                "entries": [{"rgb": [255, 0, 0], "lab": [50, 60, 40], "recipe": [0]}],
            }
            json_path = os.path.join(tmp_dir, "test_lut.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_data, f)

            result = LUTManager.get_all_lut_files()
            assert len(result) >= 1, "应至少扫描到 1 个 .json 文件"

            # 验证返回的路径指向 .json 文件
            found_json = any(v.endswith(".json") for v in result.values())
            assert found_json, "扫描结果应包含 .json 文件"
        finally:
            LUTManager.LUT_PRESET_DIR = original_dir
            shutil.rmtree(tmp_dir)

    def test_scan_finds_all_formats(self):
        """同时存在 .npy、.json、.npz 文件时，三种格式都应被扫描到。"""
        tmp_dir = tempfile.mkdtemp()
        original_dir = LUTManager.LUT_PRESET_DIR

        try:
            LUTManager.LUT_PRESET_DIR = tmp_dir

            # 创建三种格式的文件
            np.save(os.path.join(tmp_dir, "lut_a.npy"), np.zeros((4, 3), dtype=np.uint8))

            with open(os.path.join(tmp_dir, "lut_b.json"), "w") as f:
                json.dump({"name": "b", "palette": [], "entries": []}, f)

            np.savez(os.path.join(tmp_dir, "lut_c.npz"), rgb=np.zeros((4, 3), dtype=np.uint8))

            result = LUTManager.get_all_lut_files()
            extensions = {os.path.splitext(v)[1] for v in result.values()}
            assert ".npy" in extensions, "应扫描到 .npy 文件"
            assert ".json" in extensions, "应扫描到 .json 文件"
            assert ".npz" in extensions, "应扫描到 .npz 文件"
        finally:
            LUTManager.LUT_PRESET_DIR = original_dir
            shutil.rmtree(tmp_dir)


# ============================================================
# 8.1.6 上传 .npy 自动转换为 .json 测试
# Validates: Requirements 7.3, 12.1
# ============================================================


class TestUploadNpyAutoConvert:
    """验证上传 .npy 文件时自动转换为 .json 保存。"""

    def test_upload_npy_saves_as_json(self):
        """上传 .npy 文件后，预设目录中应保存为 .json 格式。"""
        tmp_dir = tempfile.mkdtemp()
        original_dir = LUTManager.LUT_PRESET_DIR

        try:
            LUTManager.LUT_PRESET_DIR = tmp_dir

            # 创建临时 .npy 文件
            rgb = np.random.randint(0, 256, size=(16, 3), dtype=np.uint8)
            npy_path = os.path.join(tmp_dir, "uploaded_lut.npy")
            np.save(npy_path, rgb)

            # 模拟 file-like 上传对象（有 .name 属性）
            class FakeUploadedFile:
                def __init__(self, path):
                    self.name = path

            fake_file = FakeUploadedFile(npy_path)
            success, message, _ = LUTManager.save_uploaded_lut(fake_file, "test_upload")

            assert success, f"上传应成功，实际消息: {message}"

            # 验证保存的文件是 .json 格式
            custom_dir = os.path.join(tmp_dir, "Custom")
            saved_files = os.listdir(custom_dir) if os.path.exists(custom_dir) else []
            json_files = [f for f in saved_files if f.endswith(".json")]
            assert len(json_files) >= 1, f"Custom 目录应包含 .json 文件，实际文件: {saved_files}"

            # 验证保存的 JSON 内容可被正确加载
            json_path = os.path.join(custom_dir, json_files[0])
            loaded_rgb, stacks, metadata = LUTManager.load_lut_with_metadata(json_path)
            np.testing.assert_array_equal(loaded_rgb, rgb)
        finally:
            LUTManager.LUT_PRESET_DIR = original_dir
            shutil.rmtree(tmp_dir)

    def test_upload_json_copies_directly(self):
        """上传 .json 文件时应直接复制，不做转换。"""
        tmp_dir = tempfile.mkdtemp()
        original_dir = LUTManager.LUT_PRESET_DIR

        try:
            LUTManager.LUT_PRESET_DIR = tmp_dir

            # 创建临时 .json 文件
            json_data = {
                "name": "direct_copy",
                "palette": {"White": {"material": "PLA Basic"}},
                "entries": [{"rgb": [255, 255, 255], "lab": [100, 0, 0], "recipe": ["White"]}],
            }
            json_path = os.path.join(tmp_dir, "direct_copy.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_data, f, ensure_ascii=False)

            class FakeUploadedFile:
                def __init__(self, path):
                    self.name = path

            fake_file = FakeUploadedFile(json_path)
            success, message, _ = LUTManager.save_uploaded_lut(fake_file, "direct_test")

            assert success, f"上传应成功，实际消息: {message}"

            # 验证 Custom 目录中有 .json 文件
            custom_dir = os.path.join(tmp_dir, "Custom")
            saved_files = os.listdir(custom_dir) if os.path.exists(custom_dir) else []
            json_files = [f for f in saved_files if f.endswith(".json")]
            assert len(json_files) >= 1
        finally:
            LUTManager.LUT_PRESET_DIR = original_dir
            shutil.rmtree(tmp_dir)
