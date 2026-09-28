"""Cross-repository Workshop release-chain verification tests."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts.sync_workshop_seed import sync_workshop_seed
from scripts.verify_workshop_release_chain import (
    verify_workshop_release_chain,
)
from tests.test_workshop_seed_sync_unit import (
    ASSET_NAME,
    MODULE_ID,
    MODULE_VERSION,
    _copying_downloader,
    _signed_registry,
)


SDK_VERSION = "1.0.1"
SDK_ASSET = f"lumina-workshop-sdk-{SDK_VERSION}.tgz"
SDK_URL = (
    "https://github.com/lumina-layer-studio/Lumina-Workshop-SDK/"
    f"releases/download/v{SDK_VERSION}/{SDK_ASSET}"
)


def _write_sdk_release(tmp_path: Path) -> tuple[Path, Path]:
    archive = tmp_path / SDK_ASSET
    package_json = json.dumps(
        {
            "name": "@lumina/workshop-sdk",
            "version": SDK_VERSION,
            "type": "module",
            "exports": {
                ".": {
                    "types": "./dist/index.d.ts",
                    "import": "./dist/index.js",
                }
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    with tarfile.open(archive, "w:gz") as output:
        for name, payload in (
            ("package/package.json", package_json),
            ("package/dist/index.js", b"export {};\n"),
            ("package/dist/index.d.ts", b"export {};\n"),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            member.mode = 0o644
            output.addfile(member, io.BytesIO(payload))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum_path = tmp_path / f"{SDK_ASSET}.sha256"
    # sha256sum format is byte-exact; write_text would emit CRLF on Windows.
    checksum_path.write_bytes(f"{checksum}  {SDK_ASSET}\n".encode("ascii"))
    return archive, checksum_path


def _write_frontend_dependency(
    tmp_path: Path,
    sdk_archive: Path,
) -> tuple[Path, Path]:
    package_json = tmp_path / "package.json"
    package_json.write_text(
        json.dumps(
            {
                "dependencies": {
                    "@lumina/workshop-sdk": SDK_URL,
                }
            }
        ),
        encoding="utf-8",
    )
    integrity = (
        "sha512-"
        + base64.b64encode(
            hashlib.sha512(sdk_archive.read_bytes()).digest()
        ).decode("ascii")
    )
    lockfile = tmp_path / "pnpm-lock.yaml"
    lockfile.write_text(
        (
            "lockfileVersion: '9.0'\n"
            "importers:\n"
            "  .:\n"
            "    dependencies:\n"
            "      '@lumina/workshop-sdk':\n"
            f"        specifier: {SDK_URL}\n"
            f"        version: {SDK_URL}\n"
            "packages:\n"
            f"  '@lumina/workshop-sdk@{SDK_URL}':\n"
            f"    resolution: {{integrity: {integrity}, "
            f"tarball: {SDK_URL}}}\n"
            f"    version: {SDK_VERSION}\n"
        ),
        encoding="utf-8",
    )
    return package_json, lockfile


def _release_chain_fixture(tmp_path: Path) -> dict[str, Path]:
    registry, signature, keys, package = _signed_registry(tmp_path)
    seed_archive = tmp_path / "seed" / ASSET_NAME
    seed_archive.parent.mkdir()
    seed_lock = tmp_path / "seed-lock.json"
    sync_workshop_seed(
        module_id=MODULE_ID,
        version=MODULE_VERSION,
        registry_path=registry,
        signature_path=signature,
        keys_path=keys,
        lock_output=seed_lock,
        package_output=seed_archive,
        package_downloader=_copying_downloader(tmp_path, package),
    )
    sdk_archive, sdk_checksum = _write_sdk_release(tmp_path)
    frontend_package, frontend_lock = _write_frontend_dependency(
        tmp_path,
        sdk_archive,
    )
    return {
        "sdk_archive": sdk_archive,
        "sdk_checksum": sdk_checksum,
        "frontend_package_json": frontend_package,
        "frontend_lockfile": frontend_lock,
        "registry_index": registry,
        "registry_signature": signature,
        "registry_keys": keys,
        "seed_lock": seed_lock,
        "seed_archive": seed_archive,
    }


def test_release_chain_binds_sdk_registry_seed_and_module_bytes(
    tmp_path: Path,
) -> None:
    result = verify_workshop_release_chain(
        **_release_chain_fixture(tmp_path),
    )

    assert result.sdk_version == SDK_VERSION
    assert result.module_id == MODULE_ID
    assert result.module_version == MODULE_VERSION
    assert result.module_asset == ASSET_NAME
    assert result.registry_key_id == "registry-2026-01"


def test_release_chain_rejects_an_sdk_not_bound_by_the_lockfile(
    tmp_path: Path,
) -> None:
    paths = _release_chain_fixture(tmp_path)
    paths["frontend_lockfile"].write_text(
        paths["frontend_lockfile"]
        .read_text(encoding="utf-8")
        .replace("sha512-", "sha512-tampered"),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="SDK archive integrity is not pinned",
    ):
        verify_workshop_release_chain(**paths)


def test_release_chain_rejects_seed_identity_drift_from_registry(
    tmp_path: Path,
) -> None:
    paths = _release_chain_fixture(tmp_path)
    lock = json.loads(paths["seed_lock"].read_text(encoding="utf-8"))
    lock["assetBytes"] += 1
    paths["seed_lock"].write_text(
        json.dumps(lock),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="seed lock does not match the signed Registry",
    ):
        verify_workshop_release_chain(**paths)


def test_release_chain_workflow_adopts_the_offline_verifier() -> None:
    workflow = (
        Path(".github/workflows/workshop-release-chain.yml")
        .read_text(encoding="utf-8")
    )

    assert "pull_request:" in workflow
    assert "pnpm/action-setup@" in workflow
    assert "version: 10.33.2" in workflow
    assert '"hypothesis>=' in workflow
    assert "verify_workshop_release_chain.py" in workflow
    assert "--sdk-archive" in workflow
    assert "--sdk-checksum" in workflow
    assert "--seed-archive" in workflow
    assert "/latest/" not in workflow
