"""Desktop bundling tests for the verified official Workshop seed."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from core.workshop import inspect_workshop_package
from scripts.build_desktop import (
    prepare_workshop_seed_resource,
    verify_workshop_seed,
)


MODULE_ID = "lumina.bead-pattern"
VERSION = "1.0.1"
ASSET_NAME = f"{MODULE_ID}-{VERSION}.lumina-workshop"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _seed_fixture(tmp_path: Path) -> tuple[Path, Path]:
    package_path = tmp_path / ASSET_NAME
    manifest = {
        "manifestVersion": 1,
        "id": MODULE_ID,
        "version": VERSION,
        "name": {"zh-CN": "拼豆工作台", "en-US": "Fuse Bead Studio"},
        "description": {
            "zh-CN": "测试预装模块",
            "en-US": "Test seed module",
        },
        "publisher": "Lumina Studio",
        "workshopApi": {"min": "1.0.0", "maxExclusive": "2.0.0"},
        "luminaVersion": {"min": "2.0.0"},
        "entrypoints": {"ui": "ui/index.html"},
        "permissions": [
            {"name": "project.storage", "reason": "保存工程"},
        ],
    }
    with ZipFile(
        package_path,
        "w",
        compression=ZIP_DEFLATED,
    ) as package:
        package.writestr(
            "manifest.json",
            json.dumps(
                manifest,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        package.writestr(
            "ui/index.html",
            "<!doctype html><html><head></head><body></body></html>",
        )
        package.writestr("assets/icon.png", PNG_1X1)
        package.writestr("README.md", "# Seed\n")
        package.writestr("LICENSE", "GPL-3.0\n")
    inspected = inspect_workshop_package(package_path)
    lock = {
        "schemaVersion": 1,
        "moduleId": MODULE_ID,
        "version": VERSION,
        "repository": (
            "https://github.com/lumina-layer-studio/"
            "Lumina-Fuse-Bead-Studio"
        ),
        "releaseTag": f"v{VERSION}",
        "releaseAsset": ASSET_NAME,
        "downloadUrl": (
            "https://github.com/lumina-layer-studio/"
            "Lumina-Fuse-Bead-Studio/releases/download/"
            f"v{VERSION}/{ASSET_NAME}"
        ),
        "assetBytes": inspected.compressed_bytes,
        "sha256": inspected.archive_sha256,
        "manifestSha256": inspected.manifest_sha256,
    }
    lock_path = tmp_path / "seed-lock.json"
    lock_path.write_text(
        json.dumps(lock, ensure_ascii=False),
        encoding="utf-8",
    )
    return package_path, lock_path


def test_verified_seed_is_copied_with_only_its_lock(
    tmp_path: Path,
) -> None:
    package_path, lock_path = _seed_fixture(tmp_path)
    resource_dir = tmp_path / "resources"
    resource_dir.mkdir()
    (resource_dir / ".gitignore").write_text("*\n", encoding="utf-8")
    (resource_dir / "old-0.9.0.lumina-workshop").write_bytes(b"old")
    (resource_dir / "seed-lock.json").write_text(
        '{"old":true}',
        encoding="utf-8",
    )

    lock = prepare_workshop_seed_resource(
        seed_path=package_path,
        lock_path=lock_path,
        resource_dir=resource_dir,
        allow_missing=False,
    )

    assert lock.release_asset == ASSET_NAME
    assert (resource_dir / ASSET_NAME).read_bytes() == (
        package_path.read_bytes()
    )
    assert (resource_dir / "seed-lock.json").read_bytes() == (
        lock_path.read_bytes()
    )
    assert sorted(path.name for path in resource_dir.iterdir()) == [
        ".gitignore",
        ASSET_NAME,
        "seed-lock.json",
    ]


def test_wrong_seed_digest_stops_before_resource_mutation(
    tmp_path: Path,
) -> None:
    package_path, lock_path = _seed_fixture(tmp_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["sha256"] = hashlib.sha256(b"different").hexdigest()
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    resource_dir = tmp_path / "resources"
    resource_dir.mkdir()
    sentinel = resource_dir / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        prepare_workshop_seed_resource(
            seed_path=package_path,
            lock_path=lock_path,
            resource_dir=resource_dir,
            allow_missing=False,
        )

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_missing_seed_requires_explicit_development_opt_out(
    tmp_path: Path,
) -> None:
    _package_path, lock_path = _seed_fixture(tmp_path)
    resource_dir = tmp_path / "resources"
    resource_dir.mkdir()
    stale = resource_dir / ASSET_NAME
    stale.write_bytes(b"stale")

    with pytest.raises(ValueError, match="required"):
        prepare_workshop_seed_resource(
            seed_path=None,
            lock_path=lock_path,
            resource_dir=resource_dir,
            allow_missing=False,
        )
    assert stale.exists()

    result = prepare_workshop_seed_resource(
        seed_path=None,
        lock_path=lock_path,
        resource_dir=resource_dir,
        allow_missing=True,
    )

    assert result is None
    assert not stale.exists()


def test_verify_rejects_wrong_name_before_package_copy(
    tmp_path: Path,
) -> None:
    package_path, lock_path = _seed_fixture(tmp_path)
    wrong_name = tmp_path / "renamed.lumina-workshop"
    wrong_name.write_bytes(package_path.read_bytes())

    with pytest.raises(ValueError, match="name"):
        verify_workshop_seed(wrong_name, lock_path)
