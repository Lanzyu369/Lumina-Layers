"""Runtime lifecycle tests for the bundled official Workshop seed."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from core.workshop import (
    WorkshopInstallError,
    WorkshopInstaller,
    converge_workshop_seed,
    inspect_workshop_package,
)


MODULE_ID = "lumina.bead-pattern"
REPOSITORY = (
    "https://github.com/lumina-layer-studio/Lumina-Fuse-Bead-Studio"
)
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _seed_directory(tmp_path: Path, version: str) -> Path:
    seed_dir = tmp_path / f"seed-{version}"
    seed_dir.mkdir()
    asset_name = f"{MODULE_ID}-{version}.lumina-workshop"
    archive = seed_dir / asset_name
    manifest = {
        "manifestVersion": 1,
        "id": MODULE_ID,
        "version": version,
        "name": {
            "zh-CN": "官方拼豆工作台",
            "en-US": "Official fuse-bead studio",
        },
        "description": {
            "zh-CN": "官方预装模块测试。",
            "en-US": "Official seed lifecycle fixture.",
        },
        "publisher": "Lumina Studio",
        "workshopApi": {
            "min": "1.0.0",
            "maxExclusive": "2.0.0",
        },
        "luminaVersion": {
            "min": "1.0.0",
        },
        "entrypoints": {
            "ui": "ui/index.html",
        },
        "permissions": [
            {
                "name": "project.storage",
                "reason": "Save fuse-bead projects.",
            }
        ],
    }
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
        output.writestr(
            "manifest.json",
            json.dumps(
                manifest,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        output.writestr(
            "ui/index.html",
            b"<!doctype html><html><head></head><body>seed</body></html>",
        )
        output.writestr("assets/icon.png", PNG_1X1)
        output.writestr("README.md", b"# Official seed\n")
        output.writestr("LICENSE", b"MIT\n")

    inspected = inspect_workshop_package(archive)
    lock = {
        "schemaVersion": 1,
        "moduleId": MODULE_ID,
        "version": version,
        "repository": REPOSITORY,
        "releaseTag": f"v{version}",
        "releaseAsset": asset_name,
        "downloadUrl": (
            f"{REPOSITORY}/releases/download/v{version}/{asset_name}"
        ),
        "assetBytes": archive.stat().st_size,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "manifestSha256": inspected.manifest_sha256,
    }
    (seed_dir / "seed-lock.json").write_text(
        json.dumps(lock, ensure_ascii=False),
        encoding="utf-8",
    )
    return seed_dir


def _installer(tmp_path: Path) -> WorkshopInstaller:
    return WorkshopInstaller(data_dir=tmp_path / "workshop-data")


def test_first_startup_stages_verified_official_seed(
    tmp_path: Path,
) -> None:
    installer = _installer(tmp_path)

    result = converge_workshop_seed(
        _seed_directory(tmp_path, "1.0.1"),
        installer,
    )

    assert result.action == "installed"
    assert result.module_id == MODULE_ID
    assert result.version == "1.0.1"
    state = installer.get(MODULE_ID)
    assert state is not None
    assert state.source == "seed"
    assert state.official is True
    assert state.active_version is None
    assert state.candidate_version == "1.0.1"


def test_seed_is_idempotent_and_never_downgrades_installed_code(
    tmp_path: Path,
) -> None:
    installer = _installer(tmp_path)
    current_seed = _seed_directory(tmp_path, "1.0.1")
    converge_workshop_seed(current_seed, installer)
    installer.activate(MODULE_ID, "1.0.1")

    same = converge_workshop_seed(current_seed, installer)
    older = converge_workshop_seed(
        _seed_directory(tmp_path, "1.0.0"),
        installer,
    )

    assert same.action == "unchanged"
    assert older.action == "newer-installed"
    state = installer.get(MODULE_ID)
    assert state is not None
    assert state.active_version == "1.0.1"
    assert state.candidate_version is None
    assert state.versions == ("1.0.1",)


def test_newer_seed_is_staged_without_replacing_active_version(
    tmp_path: Path,
) -> None:
    installer = _installer(tmp_path)
    converge_workshop_seed(
        _seed_directory(tmp_path, "1.0.0"),
        installer,
    )
    installer.activate(MODULE_ID, "1.0.0")

    result = converge_workshop_seed(
        _seed_directory(tmp_path, "1.0.1"),
        installer,
    )

    assert result.action == "installed"
    state = installer.get(MODULE_ID)
    assert state is not None
    assert state.active_version == "1.0.0"
    assert state.candidate_version == "1.0.1"
    assert state.versions == ("1.0.0", "1.0.1")


def test_uninstall_tombstone_blocks_startup_but_explicit_restore_succeeds(
    tmp_path: Path,
) -> None:
    installer = _installer(tmp_path)
    seed_dir = _seed_directory(tmp_path, "1.0.1")
    converge_workshop_seed(seed_dir, installer)
    installer.activate(MODULE_ID, "1.0.1")
    project = installer.project_data_path(MODULE_ID) / "project.json"
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")
    installer.uninstall(MODULE_ID)

    skipped = converge_workshop_seed(seed_dir, installer)

    assert skipped.action == "user-uninstalled"
    tombstone = installer.get(MODULE_ID)
    assert tombstone is not None
    assert tombstone.official_uninstalled is True
    assert not installer.module_path(MODULE_ID).exists()

    restored = converge_workshop_seed(
        seed_dir,
        installer,
        restore_uninstalled=True,
        expected_module_id=MODULE_ID,
    )

    assert restored.action == "restored"
    state = installer.get(MODULE_ID)
    assert state is not None
    assert state.official_uninstalled is False
    assert state.candidate_version == "1.0.1"
    assert state.active_version is None
    assert project.is_file()


def test_explicit_restore_requires_the_matching_official_tombstone(
    tmp_path: Path,
) -> None:
    installer = _installer(tmp_path)
    seed_dir = _seed_directory(tmp_path, "1.0.1")

    with pytest.raises(
        ValueError,
        match="does not match the requested module",
    ):
        converge_workshop_seed(
            seed_dir,
            installer,
            restore_uninstalled=True,
            expected_module_id="lumina.other-module",
        )

    with pytest.raises(
        WorkshopInstallError,
        match="not awaiting seed restore",
    ):
        converge_workshop_seed(
            seed_dir,
            installer,
            restore_uninstalled=True,
            expected_module_id=MODULE_ID,
        )


def test_corrupt_seed_fails_closed_without_install_state(
    tmp_path: Path,
) -> None:
    installer = _installer(tmp_path)
    seed_dir = _seed_directory(tmp_path, "1.0.1")
    archive = seed_dir / f"{MODULE_ID}-1.0.1.lumina-workshop"
    archive.write_bytes(archive.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="byte count"):
        converge_workshop_seed(seed_dir, installer)

    assert installer.list() == ()


def test_missing_seed_directory_fails_without_creating_module_state(
    tmp_path: Path,
) -> None:
    installer = _installer(tmp_path)

    with pytest.raises(ValueError, match="regular directory"):
        converge_workshop_seed(tmp_path / "missing-seed", installer)

    assert installer.list() == ()
