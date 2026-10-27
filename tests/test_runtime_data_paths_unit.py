"""Configurable settings, material, cache and LUT directory tests.

设置、耗材、缓存和 LUT 目录配置测试。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.routers.system import resolve_settings_file
from api.services import lut_registry_sync
from core import material_cache
from core.lut_details.service import get_lut_details_service
from utils.lut_manager import LUTManager


def _write_lut(path: Path, *, manufacturer: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "manufacturer": manufacturer,
                "type": "PLA",
                "palette": {
                    "White": {
                        "material": "PLA",
                        "hex_color": "#FFFFFF",
                        "color_name": "White",
                    }
                },
                "entries": [
                    {
                        "rgb": [255, 255, 255],
                        "lab": [100.0, 0.0, 0.0],
                        "recipe": ["White"],
                    }
                ],
                "max_color_layers": 1,
                "layer_height_mm": 0.08,
                "line_width_mm": 0.42,
                "base_layers": 10,
                "base_channel_idx": 0,
                "layer_order": "Top2Bottom",
                "color_mode": "BW (Black & White)",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_settings_file_uses_override_and_keeps_source_default(
    tmp_path: Path,
) -> None:
    shared_settings = tmp_path / "shared" / "settings" / "common.json"

    assert resolve_settings_file({}) == Path("user_settings.json")
    assert resolve_settings_file(
        {"LUMINA_SETTINGS_PATH": str(shared_settings)}
    ) == shared_settings


def test_settings_file_rejects_relative_override() -> None:
    with pytest.raises(ValueError, match="LUMINA_SETTINGS_PATH"):
        resolve_settings_file({"LUMINA_SETTINGS_PATH": "settings/common.json"})


def test_runtime_cache_keeps_solver_cache_outside_materials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_materials = tmp_path / "shared" / "materials"
    version_cache = tmp_path / "cache" / "runtime-version"
    monkeypatch.setattr(material_cache, "MATERIALS_DIR", str(shared_materials))
    monkeypatch.setenv("LUMINA_RUNTIME_CACHE_DIR", str(version_cache))

    assert material_cache.default_cache_directory() == (
        version_cache / material_cache.CACHE_SUBDIR
    )


def test_runtime_cache_rejects_relative_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_RUNTIME_CACHE_DIR", "cache/runtime-version")

    with pytest.raises(ValueError, match="LUMINA_RUNTIME_CACHE_DIR"):
        material_cache.default_cache_directory()


def test_custom_and_cloud_luts_are_scanned_beside_builtin_presets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset_root = tmp_path / "runtime" / "lut-preset"
    custom_root = tmp_path / "shared" / "luts" / "custom"
    cloud_root = tmp_path / "shared" / "luts" / "cloud"
    preset_root.mkdir(parents=True)
    custom_root.mkdir(parents=True)
    (cloud_root / "Official").mkdir(parents=True)
    (preset_root / "builtin.json").write_text("{}", encoding="utf-8")
    (custom_root / "mine.json").write_text("{}", encoding="utf-8")
    (cloud_root / "Official" / "remote.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(preset_root))
    monkeypatch.setenv("LUMINA_CUSTOM_LUT_DIR", str(custom_root))
    monkeypatch.setenv("LUMINA_CLOUD_LUT_DIR", str(cloud_root))
    LUTManager.invalidate_preset_cache()
    try:
        files = LUTManager.get_all_lut_files()
    finally:
        LUTManager.invalidate_preset_cache()

    assert files["builtin"] == str(preset_root / "builtin.json")
    assert files["Custom - mine"] == str(custom_root / "mine.json")
    assert files["Cloud - Official - remote"] == str(
        cloud_root / "Official" / "remote.json"
    )


def test_custom_luts_are_available_in_details_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset_root = tmp_path / "runtime" / "lut-preset"
    custom_root = tmp_path / "shared" / "luts" / "custom"
    cloud_root = tmp_path / "shared" / "luts" / "cloud"
    preset_root.mkdir(parents=True)
    _write_lut(custom_root / "mine.json", manufacturer="Local Maker")
    _write_lut(
        cloud_root / "Official" / "remote.json",
        manufacturer="Cloud Maker",
    )
    outside_lut = tmp_path / "outside.json"
    _write_lut(outside_lut, manufacturer="Outside")
    escaped_link = custom_root / "escaped.json"
    try:
        escaped_link.symlink_to(outside_lut)
    except OSError:
        escaped_link = None

    monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(preset_root))
    monkeypatch.setenv("LUMINA_CUSTOM_LUT_DIR", str(custom_root))
    monkeypatch.setenv("LUMINA_CLOUD_LUT_DIR", str(cloud_root))
    get_lut_details_service.cache_clear()
    try:
        service = get_lut_details_service()
        names = {
            item.name
            for group in service.get_catalog().groups
            for item in group.items
        }

        assert "Custom - mine" in names
        assert "Cloud - Official - remote" in names
        assert service.get_lut_details("Custom - mine").manufacturer == (
            "Local Maker"
        )
        if escaped_link is not None:
            assert "outside" not in names
    finally:
        get_lut_details_service.cache_clear()


def test_cloud_registry_uses_shared_cloud_and_sync_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset_root = tmp_path / "runtime" / "lut-preset"
    cloud_root = tmp_path / "shared" / "luts" / "cloud"
    monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(preset_root))
    monkeypatch.setenv("LUMINA_CLOUD_LUT_DIR", str(cloud_root))

    target = lut_registry_sync._safe_cloud_target("Cloud/Official/demo.json")

    assert target == cloud_root / "Official" / "demo.json"
    assert lut_registry_sync._relative_lut_preset_path(target) == (
        "Cloud/Official/demo.json"
    )
    assert lut_registry_sync._index_path() == (
        cloud_root.parent / "_sync" / "luts" / "index.json"
    )


def test_shared_cloud_index_round_trips_logical_installed_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset_root = tmp_path / "runtime" / "lut-preset"
    cloud_root = tmp_path / "shared" / "luts" / "cloud"
    installed = cloud_root / "Official" / "demo.json"
    installed.parent.mkdir(parents=True)
    installed.write_text(json.dumps({"rgb": []}), encoding="utf-8")
    monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(preset_root))
    monkeypatch.setenv("LUMINA_CLOUD_LUT_DIR", str(cloud_root))

    resolved = lut_registry_sync._safe_index_installed_path(
        {"installed_path": "Cloud/Official/demo.json"}
    )

    assert resolved == installed
