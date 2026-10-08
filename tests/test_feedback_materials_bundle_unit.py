"""Unit tests for ``api.feedback_materials_bundle``.

验证耗材档案打包器：空选择、单目录、多目录、_solver_cache 保留、
缺失目录、超时降级。
"""

from __future__ import annotations

import hashlib
import json
import logging
import zipfile
from pathlib import Path
from typing import Iterator

import pytest

from api.feedback_materials_bundle import (
    MaterialsBundleResult,
    pack_materials,
)
from core.lumina_box_archive import (
    LUMINA_BOX_MEASUREMENTS_FILENAME,
    save_lumina_box_material_archive,
)
from core.km_xyz import (
    KM_XYZ_FIT_OBJECTIVE_ID,
    KM_XYZ_MEASUREMENT_PROTOCOL_ID,
    KM_XYZ_MEASUREMENT_REFLECTION_BOUNDARY_ID,
)


def _make_material(root: Path, dir_name: str, files: dict[str, bytes]) -> Path:
    """Create ``root/<dir_name>/<subpath>`` for each ``subpath → content``."""
    dir_path = root / dir_name
    dir_path.mkdir(parents=True, exist_ok=True)
    for subpath, content in files.items():
        target = dir_path / subpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return dir_path


def _paired_archive_payloads() -> tuple[dict[str, object], dict[str, object]]:
    samples = [
        {
            "thickness_mm": thickness_mm,
            "transmittance_percent_xyz": transmittance,
            "reflectance_percent_xyz": reflectance,
        }
        for thickness_mm, transmittance, reflectance in (
            (0.08, [83.0, 79.0, 75.0], [22.0, 28.0, 34.0]),
            (0.16, [67.0, 61.0, 56.0], [25.0, 31.0, 37.0]),
            (0.32, [42.0, 35.0, 30.0], [30.0, 36.0, 42.0]),
        )
    ]
    predictions = [
        {
            "thickness_mm": sample["thickness_mm"],
            "transmittance": {
                "measured_percent_xyz": sample["transmittance_percent_xyz"],
                "predicted_percent_xyz": sample["transmittance_percent_xyz"],
                "residual_percentage_points_xyz": [0.0, 0.0, 0.0],
            },
            "reflectance": {
                "measured_percent_xyz": sample["reflectance_percent_xyz"],
                "predicted_percent_xyz": sample["reflectance_percent_xyz"],
                "residual_percentage_points_xyz": [0.0, 0.0, 0.0],
            },
        }
        for sample in samples
    ]
    return (
        {
            "protocol_id": KM_XYZ_MEASUREMENT_PROTOCOL_ID,
            "value_scale": "percent_0_100",
            "measurement_backing_percent_xyz": [19.8, 19.7, 24.7],
            "samples": samples,
        },
        {
            "parameters": {"K": [0.5, 0.6, 0.7], "S": [1.0, 1.1, 1.2], "unit": "mm^-1"},
            "sample_predictions": predictions,
            "residual_summary": {
                "transmittance_channel_rmse_percentage_points_xyz": [0.0, 0.0, 0.0],
                "reflectance_channel_rmse_percentage_points_xyz": [0.0, 0.0, 0.0],
                "channel_rmse_percentage_points_xyz": [0.0, 0.0, 0.0],
                "transmittance_rmse_percentage_points": 0.0,
                "reflectance_rmse_percentage_points": 0.0,
                "overall_rmse_percentage_points": 0.0,
                "max_abs_residual_percentage_points": 0.0,
                "max_abs_location": {
                    "thickness_mm": 0.08,
                    "modality": "transmittance",
                    "channel": "X",
                    "signed_residual_percentage_points": 0.0,
                },
            },
            "diagnostics": {
                "success": True,
                "message": "fixture converged",
                "nfev": 1,
                "start_count": 24,
                "robust_objective": 0.0,
                "jacobian_condition": 1.0,
                "measurement_thickness_offset_mm": 0.0,
                "objective_id": KM_XYZ_FIT_OBJECTIVE_ID,
                "objective_config": {"pair_weighting": "equal"},
                "channels": [
                    {
                        "channel": channel,
                        "transmittance_rmse": 0.0,
                        "reflectance_rmse": 0.0,
                        "warnings": [],
                    }
                    for channel in ("X", "Y", "Z")
                ],
                "warnings": [],
            },
            "measurement_backing_base_percent_xyz": [19.8, 19.7, 24.7],
            "measurement_backing_scale": 1.0,
            "measurement_thickness_offset_mm": 0.0,
            "measurement_backing_effective_percent_xyz": [19.8, 19.7, 24.7],
            "measurement_reflection_boundary_id": (
                KM_XYZ_MEASUREMENT_REFLECTION_BOUNDARY_ID
            ),
            "fit_quality": {
                "savable": True,
                "reasons": [],
                "thresholds": {
                    "modality_rmse_percentage_points": 10.0,
                    "overall_rmse_percentage_points": 10.0,
                    "max_abs_residual_percentage_points": 20.0,
                },
            },
            "estimated_effective_d65_10_xyz_relative": [0.3, 0.36, 0.42],
            "estimated_reflectance_thickness_mm": 0.32,
            "estimated_rgb": [64, 108, 145],
            "warnings": [],
        },
    )


def _save_lumina_box_archive(materials_root: Path, material_name: str) -> Path:
    """Create a valid committed Lumina Box archive for bundle tests."""
    measurement_payload, fit_payload = _paired_archive_payloads()
    result = save_lumina_box_material_archive(
        material_name=material_name,
        brand="Lumina",
        material_type="PLA",
        notes=None,
        measurement_payload=measurement_payload,
        fit_payload=fit_payload,
        materials_dir=str(materials_root),
    )
    return Path(result.archive_path).parent


def _damage_lumina_box_measurements_sidecar(
    archive_dir: Path,
    *,
    field: str,
    value: str,
) -> None:
    """Change one identity field and refresh only its declared file hash.

    保持 sidecar 的 JSON/哈希表面有效，以覆盖 bridge/model/protocol 的
    一致性校验路径，而不是只覆盖文件哈希不匹配。
    """
    sidecar_path = archive_dir / LUMINA_BOX_MEASUREMENTS_FILENAME
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar[field] = value
    sidecar_path.write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    material_path = archive_dir / "material.json"
    material = json.loads(material_path.read_text(encoding="utf-8"))
    material["sidecar_integrity"]["measurements"]["sha256"] = (
        hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
    )
    material_path.write_text(
        json.dumps(material, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_empty_selection_returns_not_applicable(tmp_path: Path) -> None:
    result = pack_materials(tmp_path, [], tmp_path / "out.zip")
    assert result.status == "not_applicable"
    assert result.path is None
    assert result.entry_count == 0


def test_single_dir_packs_all_files(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    _make_material(
        materials,
        "BrandA",
        {"profile.json": b"{}", "notes.txt": b"hello"},
    )
    out = tmp_path / "out.zip"

    result = pack_materials(materials, ["BrandA"], out)

    assert result.status == "attached"
    assert result.path == out
    assert out.exists()
    assert result.entry_count == 2
    assert result.included_dirs == ["BrandA"]
    assert result.excluded_cache_keys == []
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert names == {"BrandA/profile.json", "BrandA/notes.txt"}


def test_preserves_solver_cache_subtree(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    _make_material(
        materials,
        "BrandA",
        {
            "profile.json": b"{}",
            "_solver_cache/cache1.pkl": b"x",
            "_solver_cache/cache2.pkl": b"y",
        },
    )
    out = tmp_path / "out.zip"

    result = pack_materials(materials, ["BrandA"], out)

    assert result.status == "attached"
    assert result.entry_count == 3
    assert result.excluded_cache_keys == []
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert names == {"BrandA/profile.json", "BrandA/_solver_cache/cache1.pkl", "BrandA/_solver_cache/cache2.pkl"}


def test_zero_timeout_preserves_every_file_even_after_the_old_time_budget(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    source = materials / "BrandA"
    source.mkdir(parents=True)
    (source / "profile.json").write_bytes(b"profile")
    (source / "cache.bin").write_bytes(b"cache")
    clock = iter([0.0, 60.0, 120.0, 180.0])
    output = tmp_path / "materials.zip"
    result = pack_materials(materials, ["BrandA"], output, timeout_s=0, now_fn=lambda: next(clock))
    assert result.status == "attached"
    assert result.entry_count == 2


def test_missing_dir_logged_but_still_produces_zip_for_others(
    tmp_path: Path,
) -> None:
    materials = tmp_path / "materials"
    _make_material(materials, "BrandA", {"profile.json": b"{}"})
    out = tmp_path / "out.zip"

    result = pack_materials(materials, ["BrandA", "NoSuchBrand"], out)

    assert result.status == "attached"
    assert result.entry_count == 1
    assert result.included_dirs == ["BrandA"]


def test_all_dirs_missing_returns_not_applicable(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    out = tmp_path / "out.zip"

    result = pack_materials(materials, ["Ghost1", "Ghost2"], out)

    assert result.status == "not_applicable"
    assert not out.exists()


def test_multiple_dirs_preserve_layout(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    _make_material(materials, "BrandA", {"profile.json": b"a"})
    _make_material(materials, "BrandB", {"profile.json": b"b"})
    out = tmp_path / "out.zip"

    result = pack_materials(materials, ["BrandA", "BrandB"], out)

    assert result.status == "attached"
    assert result.entry_count == 2
    assert set(result.included_dirs) == {"BrandA", "BrandB"}
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert names == {"BrandA/profile.json", "BrandB/profile.json"}


def test_lumina_box_bundle_keeps_only_committed_archive_identity_files(
    tmp_path: Path,
) -> None:
    """Lumina Box repro bundles omit every non-archive file.

    Lumina Box 档案复现包只保留可重建身份所需的三份已提交文件。
    """
    materials = tmp_path / "materials"
    archive_dir = _save_lumina_box_archive(materials, "white")
    _make_material(
        archive_dir,
        ".",
        {
            "_solver_cache/cache.bin": b"solver-cache",
            "_candidate_cache/candidate.json": b"candidate-cache",
            "runtime_cache/runtime.json": b"runtime-cache",
            ".lumina-box-staging-tmp/staged.json": b"temporary",
            "secret.txt": b"do-not-export",
            "nested/unrelated.json": b"unrelated",
        },
    )
    out = tmp_path / "lumina-box.zip"

    result = pack_materials(
        materials,
        ["Lumina/white"],
        out,
        archive_profile_kind="lumina_box",
    )

    assert result.status == "attached"
    assert result.entry_count == 3
    assert result.included_dirs == ["Lumina/white"]
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert names == {
        "Lumina/white/material.json",
        "Lumina/white/lumina_box_measurements.json",
        "Lumina/white/km_xyz_parameters.json",
    }


def test_lumina_box_bundle_rejects_incomplete_or_out_of_root_archives(
    tmp_path: Path,
) -> None:
    """A Lumina Box bundle never falls back to arbitrary directory contents."""
    materials = tmp_path / "materials"
    _make_material(
        materials,
        "Lumina/incomplete",
        {"material.json": b"{}", "secret.txt": b"do-not-export"},
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "material.json").write_bytes(b"outside-identity")
    valid = _save_lumina_box_archive(materials, "escaped")
    selected_dirs = ["Lumina/incomplete"]
    (valid / "material.json").unlink()
    try:
        (valid / "material.json").symlink_to(outside / "material.json")
    except (OSError, NotImplementedError):
        pass
    else:
        selected_dirs.append("Lumina/escaped")
    out = tmp_path / "lumina-box.zip"

    result = pack_materials(
        materials,
        selected_dirs,
        out,
        archive_profile_kind="lumina_box",
    )

    assert result.status == "not_applicable"
    assert result.entry_count == 0
    assert not out.exists()


@pytest.mark.parametrize(
    ("damage_kind", "field", "value"),
    [
        ("hash", None, None),
        ("bridge", "color_bridge_id", "wrong-bridge"),
        ("model", "optical_model", "wrong-model"),
        ("protocol", "measurement_protocol_id", "wrong-protocol"),
    ],
)
def test_lumina_box_bundle_rejects_integrity_damage_without_zip(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    damage_kind: str,
    field: str | None,
    value: str | None,
) -> None:
    """All archive-integrity failures skip ZIP creation and emit a warning.

    hash、色彩 bridge、光学 model、采集 protocol 任一损坏时，不能打包，
    同时保留面向反馈打包器的结构化 WARNING 路径。
    """
    materials = tmp_path / "materials"
    archive_dir = _save_lumina_box_archive(materials, "white")
    sidecar_path = archive_dir / LUMINA_BOX_MEASUREMENTS_FILENAME
    if field is None:
        # Preserve valid JSON but invalidate the sidecar digest declared in
        # material.json, so this exercises the hash-specific guard.
        sidecar_path.write_bytes(sidecar_path.read_bytes() + b"\n")
    else:
        assert value is not None
        _damage_lumina_box_measurements_sidecar(
            archive_dir,
            field=field,
            value=value,
        )

    out = tmp_path / f"lumina-box-{damage_kind}.zip"
    target_logger = logging.getLogger("lumina.api.feedback_materials_bundle")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=target_logger.name)
    try:
        result = pack_materials(
            materials,
            ["Lumina/white"],
            out,
            archive_profile_kind="lumina_box",
        )
    finally:
        target_logger.removeHandler(caplog.handler)

    assert result.status == "not_applicable"
    assert result.path is None
    assert result.entry_count == 0
    assert not out.exists()
    warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING
        and getattr(record, "event", None)
        == "feedback_lumina_box_archive_invalid"
    ]
    assert warnings
    assert getattr(warnings[-1], "error_type") == "LuminaBoxArchiveInvalid"


def test_timeout_deletes_partial_zip(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    # Build enough files so the timeout check has multiple iterations to fire.
    _make_material(
        materials,
        "BrandA",
        {f"file_{i}.bin": b"payload" for i in range(5)},
    )
    out = tmp_path / "out.zip"

    # Fake monotonic clock: first call returns 0 (start), every subsequent
    # call jumps 100 seconds so the packer sees it's past the budget.
    # 伪造单调时钟：起点 0，后续每次 +100 秒，立即超时。
    clock_values: Iterator[float] = iter([0.0] + [100.0] * 100)

    def fake_clock() -> float:
        return next(clock_values)

    result = pack_materials(
        materials, ["BrandA"], out, timeout_s=30, now_fn=fake_clock,
    )

    assert result.status == "packaging_timeout"
    assert result.path is None
    assert not out.exists(), (
        "partial zip must be deleted on timeout so we don't leave corrupt "
        "artifacts behind"
    )
    assert result.entry_count == 0


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    """Files that are symlinks pointing outside materials_root are NOT packed.

    符号链接指向 materials_root 外部的文件不会被打包。
    """
    materials = tmp_path / "materials"
    _make_material(materials, "BrandA", {"keep.json": b"{}"})
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"hunter2")
    try:
        (materials / "BrandA" / "leak.txt").symlink_to(outside / "secret.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not supported on this platform")
    out = tmp_path / "out.zip"

    result = pack_materials(materials, ["BrandA"], out)

    assert result.status == "attached"
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    # The symlink target is outside materials_root — must NOT be packed.
    assert "BrandA/leak.txt" not in names
    # Only the legitimate file should be in the zip.
    assert names == {"BrandA/keep.json"}
    # Verify no zip entry starts with / or contains ..
    for name in names:
        assert not name.startswith("/")
        assert ".." not in name.split("/")


def test_rejects_symlink_directory_escape(tmp_path: Path) -> None:
    """Symlink directories pointing outside materials_root are not traversed.

    符号链接目录指向外部时，不递归、不打包外部内容。
    """
    materials = tmp_path / "materials"
    _make_material(materials, "BrandA", {"keep.json": b"{}"})
    outside = tmp_path / "outside_dir"
    outside.mkdir()
    (outside / "external.txt").write_bytes(b"external-secret")
    try:
        (materials / "BrandA" / "linked_dir").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not supported on this platform")
    out = tmp_path / "out.zip"

    result = pack_materials(materials, ["BrandA"], out)

    assert result.status == "attached"
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "BrandA/linked_dir/external.txt" not in names
    assert names == {"BrandA/keep.json"}


def test_rejects_traversal_dir_name(tmp_path: Path) -> None:
    """selected_dirs=['../outside'] does not pack external files.

    路径遍历目录名不会打包外部文件。
    """
    materials = tmp_path / "materials"
    materials.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"hunter2")
    out = tmp_path / "out.zip"

    result = pack_materials(materials, ["../outside"], out)

    assert result.status == "not_applicable"
    assert not out.exists()


def test_rejects_absolute_path_dir_name(tmp_path: Path) -> None:
    """selected_dirs=[absolute_path] does not pack external files.

    绝对路径目录名不会打包外部文件。
    """
    materials = tmp_path / "materials"
    materials.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"hunter2")
    out = tmp_path / "out.zip"

    result = pack_materials(materials, [str(outside)], out)

    assert result.status == "not_applicable"
    assert not out.exists()


def test_zip_names_are_relative_and_safe(tmp_path: Path) -> None:
    """All zip entry names are relative and do not contain '..' parts.

    zip 内所有条目名称都是相对路径，不包含 '..' 路径段。
    """
    materials = tmp_path / "materials"
    _make_material(materials, "BrandA", {"sub/deep/file.txt": b"ok"})
    out = tmp_path / "out.zip"

    result = pack_materials(materials, ["BrandA"], out)

    assert result.status == "attached"
    with zipfile.ZipFile(out) as zf:
        for name in zf.namelist():
            assert not name.startswith("/"), f"zip entry starts with /: {name}"
            assert ".." not in name.split("/"), f"zip entry contains ..: {name}"
