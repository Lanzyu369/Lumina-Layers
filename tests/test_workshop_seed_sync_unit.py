"""Signed Registry snapshot and official Workshop seed synchronization tests."""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from core.workshop import WorkshopRegistryError, inspect_workshop_package
from scripts.sync_workshop_registry import sync_registry_snapshot
from scripts.sync_workshop_seed import sync_workshop_seed


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
MODULE_ID = "lumina.bead-pattern"
MODULE_VERSION = "1.0.1"
ASSET_NAME = f"{MODULE_ID}-{MODULE_VERSION}.lumina-workshop"
REPOSITORY = (
    "https://github.com/lumina-layer-studio/Lumina-Fuse-Bead-Studio"
)


def _canonical(value: dict[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _manifest() -> dict[str, object]:
    return {
        "manifestVersion": 1,
        "id": MODULE_ID,
        "version": MODULE_VERSION,
        "name": {
            "zh-CN": "拼豆工作台",
            "en-US": "Fuse Bead Studio",
        },
        "description": {
            "zh-CN": "识别并编辑拼豆图纸",
            "en-US": "Recognize and edit bead patterns",
        },
        "publisher": "Lumina Studio",
        "workshopApi": {
            "min": "1.0.0",
            "maxExclusive": "2.0.0",
        },
        "luminaVersion": {"min": "2.0.0"},
        "entrypoints": {"ui": "ui/index.html"},
        "permissions": [
            {"name": "image.pick", "reason": "选择图纸"},
            {"name": "project.storage", "reason": "保存工程"},
            {"name": "color-library.read", "reason": "读取色库"},
            {"name": "handoff.image", "reason": "交接图像"},
        ],
    }


def _write_package(tmp_path: Path) -> Path:
    package_path = tmp_path / ASSET_NAME
    with ZipFile(
        package_path,
        "w",
        compression=ZIP_DEFLATED,
    ) as package:
        package.writestr(
            "manifest.json",
            json.dumps(
                _manifest(),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        package.writestr(
            "ui/index.html",
            b"<!doctype html><html><head></head><body>bead</body></html>",
        )
        package.writestr("assets/icon.png", PNG_1X1)
        package.writestr("README.md", b"# Bead\n")
        package.writestr("LICENSE", b"GPL-3.0\n")
    return package_path


def _signed_registry(
    tmp_path: Path,
    *,
    state: str = "active",
    version: str = MODULE_VERSION,
) -> tuple[Path, Path, Path, Path]:
    package_path = _write_package(tmp_path)
    inspected = inspect_workshop_package(package_path)
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    keys_path = tmp_path / "keys.json"
    keys_path.write_bytes(
        _canonical(
            {
                "schemaVersion": 1,
                "keys": [
                    {
                        "algorithm": "Ed25519",
                        "keyId": "registry-2026-01",
                        "publicKey": base64.b64encode(
                            public_bytes
                        ).decode("ascii"),
                    }
                ],
            }
        )
    )
    release_tag = f"v{version}"
    asset_name = f"{MODULE_ID}-{version}.lumina-workshop"
    registry = {
        "schemaVersion": 1,
        "generatedAt": "2026-07-30T00:00:00Z",
        "modules": [
            {
                "moduleId": MODULE_ID,
                "repository": REPOSITORY,
                "official": True,
                "publisher": "Lumina Studio",
                "name": _manifest()["name"],
                "description": _manifest()["description"],
                "versions": [
                    {
                        "version": version,
                        "releaseTag": release_tag,
                        "assetName": asset_name,
                        "downloadUrl": (
                            f"{REPOSITORY}/releases/download/"
                            f"{release_tag}/{asset_name}"
                        ),
                        "assetBytes": inspected.compressed_bytes,
                        "sha256": inspected.archive_sha256,
                        "manifestSha256": inspected.manifest_sha256,
                        "workshopApi": _manifest()["workshopApi"],
                        "luminaVersion": _manifest()["luminaVersion"],
                        "permissions": _manifest()["permissions"],
                        "state": state,
                        "revocation": (
                            None
                            if state != "blocked"
                            else {
                                "reasonCode": "blocked",
                                "severity": "high",
                                "message": {
                                    "zh-CN": "已阻止",
                                    "en-US": "Blocked",
                                },
                            }
                        ),
                    }
                ],
            }
        ],
    }
    index_bytes = _canonical(registry)
    index_path = tmp_path / "registry-v1.json"
    signature_path = tmp_path / "registry-v1.sig"
    index_path.write_bytes(index_bytes)
    signature_path.write_bytes(
        _canonical(
            {
                "algorithm": "Ed25519",
                "keyId": "registry-2026-01",
                "signature": base64.b64encode(
                    private_key.sign(index_bytes)
                ).decode("ascii"),
            }
        )
    )
    return index_path, signature_path, keys_path, package_path


def _copying_downloader(
    tmp_path: Path,
    source: Path,
):
    def download(_candidate) -> Path:
        destination = tmp_path / "downloaded.lumina-workshop"
        shutil.copyfile(source, destination)
        return destination

    return download


def test_snapshot_sync_writes_exact_bytes_only_after_signature_verifies(
    tmp_path: Path,
) -> None:
    index, signature, keys, _package = _signed_registry(tmp_path)
    index_output = tmp_path / "bundled" / "registry-v1.json"
    signature_output = tmp_path / "bundled" / "registry-v1.sig"

    sync_registry_snapshot(
        index_source=index,
        signature_source=signature,
        keys_path=keys,
        index_output=index_output,
        signature_output=signature_output,
    )

    assert index_output.read_bytes() == index.read_bytes()
    assert signature_output.read_bytes() == signature.read_bytes()


def test_bad_snapshot_signature_preserves_existing_outputs(
    tmp_path: Path,
) -> None:
    index, signature, keys, _package = _signed_registry(tmp_path)
    index_output = tmp_path / "bundled-index.json"
    signature_output = tmp_path / "bundled.sig"
    index_output.write_bytes(b"keep-index")
    signature_output.write_bytes(b"keep-signature")
    index.write_bytes(index.read_bytes() + b" ")

    with pytest.raises(WorkshopRegistryError):
        sync_registry_snapshot(
            index_source=index,
            signature_source=signature,
            keys_path=keys,
            index_output=index_output,
            signature_output=signature_output,
        )

    assert index_output.read_bytes() == b"keep-index"
    assert signature_output.read_bytes() == b"keep-signature"


def test_seed_lock_and_package_come_from_verified_registry(
    tmp_path: Path,
) -> None:
    index, signature, keys, package = _signed_registry(tmp_path)
    output = tmp_path / "cache" / ASSET_NAME
    lock_output = tmp_path / "seed-lock.json"

    result = sync_workshop_seed(
        module_id=MODULE_ID,
        version=MODULE_VERSION,
        registry_path=index,
        signature_path=signature,
        keys_path=keys,
        lock_output=lock_output,
        package_output=output,
        package_downloader=_copying_downloader(tmp_path, package),
    )

    assert result.package_path == output
    assert result.lock.module_id == MODULE_ID
    assert result.lock.version == MODULE_VERSION
    assert result.lock.release_asset == ASSET_NAME
    assert output.read_bytes() == package.read_bytes()
    assert output.with_suffix(
        ".lumina-workshop.sha256"
    ).read_text(encoding="utf-8") == (
        f"{result.lock.sha256}  {ASSET_NAME}\n"
    )
    assert json.loads(lock_output.read_text(encoding="utf-8"))[
        "sha256"
    ] == result.lock.sha256


@pytest.mark.parametrize("state", ["deprecated", "blocked"])
def test_non_active_seed_version_is_rejected(
    tmp_path: Path,
    state: str,
) -> None:
    index, signature, keys, package = _signed_registry(
        tmp_path,
        state=state,
    )

    with pytest.raises(ValueError, match="active"):
        sync_workshop_seed(
            module_id=MODULE_ID,
            version=MODULE_VERSION,
            registry_path=index,
            signature_path=signature,
            keys_path=keys,
            lock_output=tmp_path / "seed-lock.json",
            package_output=tmp_path / "cache" / ASSET_NAME,
            package_downloader=_copying_downloader(tmp_path, package),
        )


def test_missing_seed_version_and_changed_package_write_nothing(
    tmp_path: Path,
) -> None:
    index, signature, keys, package = _signed_registry(tmp_path)
    output = tmp_path / "cache" / ASSET_NAME
    lock_output = tmp_path / "seed-lock.json"
    changed = tmp_path / "changed.lumina-workshop"
    changed.write_bytes(package.read_bytes() + b"changed")

    with pytest.raises(ValueError, match="not found"):
        sync_workshop_seed(
            module_id=MODULE_ID,
            version="2.0.0",
            registry_path=index,
            signature_path=signature,
            keys_path=keys,
            lock_output=lock_output,
            package_output=output,
            package_downloader=_copying_downloader(tmp_path, package),
        )
    with pytest.raises(ValueError, match="byte count|digest"):
        sync_workshop_seed(
            module_id=MODULE_ID,
            version=MODULE_VERSION,
            registry_path=index,
            signature_path=signature,
            keys_path=keys,
            lock_output=lock_output,
            package_output=output,
            package_downloader=_copying_downloader(tmp_path, changed),
        )

    assert not lock_output.exists()
    assert not output.exists()


def test_committed_seed_lock_has_real_immutable_identity() -> None:
    value = json.loads(
        Path("assets/workshop-seed/seed-lock.json").read_text(
            encoding="utf-8"
        )
    )

    assert value["moduleId"] == MODULE_ID
    assert value["version"] == MODULE_VERSION
    assert value["releaseAsset"] == ASSET_NAME
    assert value["downloadUrl"].startswith(
        f"{REPOSITORY}/releases/download/v{MODULE_VERSION}/"
    )
    for field in ("sha256", "manifestSha256"):
        assert len(value[field]) == 64
        assert len(set(value[field])) > 1
