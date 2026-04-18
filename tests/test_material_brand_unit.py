"""Regression tests for brand-based material subdirectories.
品牌子目录（一级分组）支持的回归测试。

Covers:
- Saving with/without ``brand`` (flat + nested layouts coexist).
- Recursive listing returns nested archives with POSIX ``directory_name``
  and a ``brand`` field derived from the first path segment.
- Resolving / loading / deleting accept multi-segment ``directory_name``.
- Path traversal attempts are rejected with ``ValueError``.
- Deleting the last material under a brand prunes the empty brand dir.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.single_stage import (
    delete_saved_stage_a_material_archive,
    list_saved_stage_a_material_archives,
    resolve_saved_material_dir,
    save_stage_a_material_archive,
)


def _minimal_payloads() -> tuple[dict, dict, dict, dict]:
    params_payload = {
        "meta": {},
        "parameters": {
            "channels": [{"color_name": "PLA", "E": [0.2, 0.3, 0.4], "k": [1.0, 1.1, 1.2]}],
            "substrates": [
                {"substrate_id": "white", "C0": [0.9, 0.9, 0.9]},
                {"substrate_id": "black", "C0": [0.1, 0.1, 0.1]},
            ],
        },
        "fitted_substrates": {},
        "validation": {"overall": {"mean_delta_e": 1.5}},
    }
    fit_summary = {
        "overall_validation": {
            "mean_delta_e": 1.5,
            "rmse_linear": 0.15,
            "channel_rmse": [0.15, 0.15, 0.15],
        },
        "warnings": [],
    }
    material_summary = {
        "estimated_rgb": [100, 110, 120],
        "estimated_k": [1.0, 1.1, 1.2],
        "white_zero_rgb": [240, 240, 240],
        "black_zero_rgb": [30, 30, 30],
        "layer_height_mm": 0.04,
        "sample_boxes": [],
    }
    source_summary = {"capture": 1}
    return params_payload, fit_summary, material_summary, source_summary


def test_save_with_brand_creates_nested_directory(tmp_path: Path) -> None:
    materials_root = tmp_path / "materials"
    params, fit, mat, src = _minimal_payloads()

    result = save_stage_a_material_archive(
        material_name="PLA White",
        params_payload=params,
        fit_summary=fit,
        source_summary=src,
        material_summary=mat,
        materials_dir=str(materials_root),
        brand="瑞贝思",
    )

    nested_dir = materials_root / "瑞贝思" / "PLA White"
    assert nested_dir.is_dir()
    assert (nested_dir / "material.json").is_file()
    assert result.material_summary["directory_name"] == "瑞贝思/PLA White"
    assert result.material_summary["brand"] == "瑞贝思"


def test_save_without_brand_remains_flat(tmp_path: Path) -> None:
    materials_root = tmp_path / "materials"
    params, fit, mat, src = _minimal_payloads()

    result = save_stage_a_material_archive(
        material_name="Legacy PLA",
        params_payload=params,
        fit_summary=fit,
        source_summary=src,
        material_summary=mat,
        materials_dir=str(materials_root),
    )

    flat_dir = materials_root / "Legacy PLA"
    assert flat_dir.is_dir()
    assert result.material_summary["directory_name"] == "Legacy PLA"
    assert result.material_summary["brand"] is None


def test_list_returns_both_flat_and_nested_with_brand(tmp_path: Path) -> None:
    materials_root = tmp_path / "materials"
    params, fit, mat, src = _minimal_payloads()

    save_stage_a_material_archive(
        material_name="Legacy",
        params_payload=params,
        fit_summary=fit,
        source_summary=src,
        material_summary=mat,
        materials_dir=str(materials_root),
    )
    save_stage_a_material_archive(
        material_name="PLA Red",
        params_payload=params,
        fit_summary=fit,
        source_summary=src,
        material_summary=mat,
        materials_dir=str(materials_root),
        brand="瑞贝思",
    )
    save_stage_a_material_archive(
        material_name="PLA Blue",
        params_payload=params,
        fit_summary=fit,
        source_summary=src,
        material_summary=mat,
        materials_dir=str(materials_root),
        brand="瑞贝思",
    )

    items = list_saved_stage_a_material_archives(materials_dir=str(materials_root))
    dir_names = {item["directory_name"] for item in items}
    assert {"Legacy", "瑞贝思/PLA Red", "瑞贝思/PLA Blue"} <= dir_names

    by_dir = {item["directory_name"]: item for item in items}
    assert by_dir["Legacy"]["brand"] is None
    assert by_dir["瑞贝思/PLA Red"]["brand"] == "瑞贝思"
    assert by_dir["瑞贝思/PLA Blue"]["brand"] == "瑞贝思"


def test_resolve_and_delete_nested_directory_name(tmp_path: Path) -> None:
    materials_root = tmp_path / "materials"
    params, fit, mat, src = _minimal_payloads()
    save_stage_a_material_archive(
        material_name="PLA Green",
        params_payload=params,
        fit_summary=fit,
        source_summary=src,
        material_summary=mat,
        materials_dir=str(materials_root),
        brand="瑞贝思",
    )
    nested_dir = materials_root / "瑞贝思" / "PLA Green"

    # Resolver accepts forward-slash path and returns the correct directory.
    resolved = resolve_saved_material_dir(materials_root, "瑞贝思/PLA Green")
    assert resolved.resolve() == nested_dir.resolve()

    # Backslash separator also accepted (cross-platform tolerance).
    resolved_backslash = resolve_saved_material_dir(materials_root, "瑞贝思\\PLA Green")
    assert resolved_backslash.resolve() == nested_dir.resolve()

    # Deleting the last material under the brand prunes the empty brand dir.
    delete_result = delete_saved_stage_a_material_archive(
        directory_name="瑞贝思/PLA Green",
        materials_dir=str(materials_root),
    )
    assert delete_result.directory_name == "瑞贝思/PLA Green"
    assert not nested_dir.exists()
    assert not (materials_root / "瑞贝思").exists()


def test_brand_dir_kept_when_sibling_materials_remain(tmp_path: Path) -> None:
    materials_root = tmp_path / "materials"
    params, fit, mat, src = _minimal_payloads()
    save_stage_a_material_archive(
        material_name="A",
        params_payload=params,
        fit_summary=fit,
        source_summary=src,
        material_summary=mat,
        materials_dir=str(materials_root),
        brand="瑞贝思",
    )
    save_stage_a_material_archive(
        material_name="B",
        params_payload=params,
        fit_summary=fit,
        source_summary=src,
        material_summary=mat,
        materials_dir=str(materials_root),
        brand="瑞贝思",
    )

    delete_saved_stage_a_material_archive(
        directory_name="瑞贝思/A",
        materials_dir=str(materials_root),
    )

    assert (materials_root / "瑞贝思").is_dir()
    assert (materials_root / "瑞贝思" / "B").is_dir()


def test_path_traversal_rejected(tmp_path: Path) -> None:
    materials_root = tmp_path / "materials"
    materials_root.mkdir()

    for bad in ("..", "../etc", "a/../b", "/absolute", "./leading-dot"):
        with pytest.raises(ValueError):
            resolve_saved_material_dir(materials_root, bad)

    # Empty / blank names are also rejected.
    for blank in ("", "   ", "."):
        with pytest.raises(ValueError):
            resolve_saved_material_dir(materials_root, blank)


def test_load_material_params_accepts_nested_directory_name(tmp_path: Path) -> None:
    from core.material_lut_synthesis import load_material_params

    materials_root = tmp_path / "materials"
    params, fit, mat, src = _minimal_payloads()
    save_stage_a_material_archive(
        material_name="PLA Cyan",
        params_payload=params,
        fit_summary=fit,
        source_summary=src,
        material_summary=mat,
        materials_dir=str(materials_root),
        brand="瑞贝思",
    )

    loaded = load_material_params("瑞贝思/PLA Cyan", materials_dir=str(materials_root))
    assert loaded.directory_name == "瑞贝思/PLA Cyan"
    assert loaded.E.shape == (3,)
    assert loaded.k.shape == (3,)
    assert loaded.C0_white.shape == (3,)


def test_list_ignores_nested_material_json_inside_another_material(tmp_path: Path) -> None:
    """Defensive: if a material.json is accidentally nested inside another, skip it."""
    materials_root = tmp_path / "materials"
    outer = materials_root / "outer"
    inner = outer / "unexpected_child"
    inner.mkdir(parents=True)

    minimal_archive = {
        "schema_version": "1.1",
        "kind": "lumina_stage_a_material",
        "material_name": "Outer",
        "fit_summary": {"overall_validation": {"mean_delta_e": 1.0}},
        "material_summary": {"estimated_rgb": [1, 2, 3]},
    }
    (outer / "material.json").write_text(json.dumps(minimal_archive), encoding="utf-8")
    (outer / "stage_A_parameters.json").write_text("{}", encoding="utf-8")
    (inner / "material.json").write_text(
        json.dumps({**minimal_archive, "material_name": "Inner"}),
        encoding="utf-8",
    )
    (inner / "stage_A_parameters.json").write_text("{}", encoding="utf-8")

    items = list_saved_stage_a_material_archives(materials_dir=str(materials_root))
    dir_names = {item["directory_name"] for item in items}
    assert "outer" in dir_names
    assert "outer/unexpected_child" not in dir_names
