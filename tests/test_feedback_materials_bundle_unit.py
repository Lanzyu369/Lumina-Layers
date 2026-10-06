"""Unit tests for ``api.feedback_materials_bundle``.

验证耗材档案打包器：空选择、单目录、多目录、_solver_cache 排除、
缺失目录、超时降级。
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Iterator

import pytest

from api.feedback_materials_bundle import (
    MaterialsBundleResult,
    pack_materials,
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


def test_excludes_solver_cache_subtree(tmp_path: Path) -> None:
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
    assert result.entry_count == 1
    assert result.excluded_cache_keys == ["_solver_cache"]
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert names == {"BrandA/profile.json"}


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
