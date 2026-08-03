"""Verify the exact public SDK, signed Registry, and official seed chain."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.workshop import (
    load_registry_keys,
    load_workshop_seed_lock,
    verify_workshop_seed,
)
from core.workshop.registry_client import (
    MAX_REGISTRY_BYTES,
    MAX_SIGNATURE_METADATA_BYTES,
    parse_registry_index,
    verify_registry_signature,
)


SDK_DEPENDENCY = "@lumina/workshop-sdk"
SDK_REPOSITORY = (
    "https://github.com/lumina-layer-studio/Lumina-Workshop-SDK"
)
SDK_URL_PATTERN = re.compile(
    re.escape(SDK_REPOSITORY)
    + r"/releases/download/v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)/"
    + r"lumina-workshop-sdk-(?P=version)\.tgz"
)
MAX_SDK_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_SDK_MEMBER_COUNT = 128
MAX_SDK_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_FRONTEND_METADATA_BYTES = 4 * 1024 * 1024
REQUIRED_SDK_MEMBERS = frozenset(
    {
        "package/package.json",
        "package/dist/index.js",
        "package/dist/index.d.ts",
    }
)


@dataclass(frozen=True, slots=True)
class WorkshopReleaseChainIdentity:
    """Verified public identities across every Workshop release boundary.

    已跨越全部创意工坊发布边界验证的公开身份。
    """

    sdk_version: str
    sdk_sha256: str
    module_id: str
    module_version: str
    module_asset: str
    module_sha256: str
    registry_key_id: str


def _read_regular(path: Path, maximum: int, *, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    size = path.stat().st_size
    if size < 1 or size > maximum:
        raise ValueError(f"{label} has an invalid size")
    return path.read_bytes()


def _json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _sdk_dependency_identity(
    frontend_package_json: Path,
) -> tuple[str, str]:
    value = _json_object(
        _read_regular(
            frontend_package_json,
            MAX_FRONTEND_METADATA_BYTES,
            label="frontend package.json",
        ),
        label="frontend package.json",
    )
    dependencies = value.get("dependencies")
    if not isinstance(dependencies, dict):
        raise ValueError("frontend dependencies are missing")
    url = dependencies.get(SDK_DEPENDENCY)
    if not isinstance(url, str):
        raise ValueError("frontend Workshop SDK dependency is missing")
    match = SDK_URL_PATTERN.fullmatch(url)
    if match is None:
        raise ValueError(
            "frontend Workshop SDK must use one exact public Release URL"
        )
    return match.group("version"), url


def _validate_sdk_checksum(
    *,
    archive: bytes,
    archive_name: str,
    checksum_path: Path,
) -> str:
    digest = hashlib.sha256(archive).hexdigest()
    checksum = _read_regular(
        checksum_path,
        4096,
        label="Workshop SDK checksum",
    )
    expected = f"{digest}  {archive_name}\n".encode("ascii")
    if checksum != expected:
        raise ValueError("Workshop SDK checksum does not match the archive")
    return digest


def _validate_sdk_lockfile(
    *,
    archive: bytes,
    sdk_url: str,
    lockfile_path: Path,
) -> None:
    lockfile = _read_regular(
        lockfile_path,
        MAX_FRONTEND_METADATA_BYTES,
        label="frontend pnpm lockfile",
    )
    try:
        text = lockfile.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "frontend pnpm lockfile is not valid UTF-8"
        ) from exc
    integrity = (
        "sha512-"
        + base64.b64encode(hashlib.sha512(archive).digest()).decode("ascii")
    )
    if sdk_url not in text or f"integrity: {integrity}" not in text:
        raise ValueError(
            "SDK archive integrity is not pinned by the frontend lockfile"
        )


def _safe_sdk_member_name(name: str) -> str:
    candidate = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.parts[0] != "package"
    ):
        raise ValueError("Workshop SDK archive contains an unsafe path")
    return candidate.as_posix()


def _validate_sdk_archive(archive: bytes, *, version: str) -> None:
    try:
        package = tarfile.open(
            fileobj=io.BytesIO(archive),
            mode="r:gz",
        )
    except (tarfile.TarError, OSError) as exc:
        raise ValueError("Workshop SDK archive is not a valid tarball") from exc
    with package:
        members = package.getmembers()
        if not members or len(members) > MAX_SDK_MEMBER_COUNT:
            raise ValueError(
                "Workshop SDK archive has an invalid member count"
            )
        member_names: set[str] = set()
        total_bytes = 0
        for member in members:
            name = _safe_sdk_member_name(member.name)
            if name in member_names:
                raise ValueError(
                    "Workshop SDK archive contains a duplicate member"
                )
            member_names.add(name)
            if not member.isfile():
                raise ValueError(
                    "Workshop SDK archive contains a non-file member"
                )
            total_bytes += member.size
            if total_bytes > MAX_SDK_UNCOMPRESSED_BYTES:
                raise ValueError(
                    "Workshop SDK archive exceeds its extracted-size limit"
                )
        if not REQUIRED_SDK_MEMBERS.issubset(member_names):
            raise ValueError(
                "Workshop SDK archive is missing its public entrypoint"
            )
        package_member = package.getmember("package/package.json")
        package_stream = package.extractfile(package_member)
        if package_stream is None:
            raise ValueError(
                "Workshop SDK package metadata could not be read"
            )
        package_json = _json_object(
            package_stream.read(),
            label="Workshop SDK package.json",
        )
    if (
        package_json.get("name") != SDK_DEPENDENCY
        or package_json.get("version") != version
    ):
        raise ValueError(
            "Workshop SDK package identity does not match its Release URL"
        )
    scripts = package_json.get("scripts", {})
    if not isinstance(scripts, dict):
        raise ValueError("Workshop SDK scripts field is invalid")
    if any(
        name in scripts
        for name in ("preinstall", "install", "postinstall", "prepare")
    ):
        raise ValueError("Workshop SDK archive contains lifecycle scripts")


def _verify_registry_and_seed(
    *,
    registry_index: Path,
    registry_signature: Path,
    registry_keys: Path,
    seed_lock: Path,
    seed_archive: Path,
) -> tuple[str, str, str, str, str]:
    index_bytes = _read_regular(
        registry_index,
        MAX_REGISTRY_BYTES,
        label="Workshop Registry index",
    )
    signature_bytes = _read_regular(
        registry_signature,
        MAX_SIGNATURE_METADATA_BYTES,
        label="Workshop Registry signature",
    )
    keys = load_registry_keys(registry_keys)
    key_id = verify_registry_signature(
        index_bytes,
        signature_bytes,
        keys,
    )
    index = parse_registry_index(index_bytes)
    lock = load_workshop_seed_lock(seed_lock)
    module = next(
        (
            candidate
            for candidate in index.modules
            if candidate.module_id == lock.module_id
        ),
        None,
    )
    version = (
        next(
            (
                candidate
                for candidate in module.versions
                if candidate.version == lock.version
            ),
            None,
        )
        if module is not None
        else None
    )
    if module is None or version is None:
        raise ValueError(
            "official seed lock does not match the signed Registry"
        )
    registry_identity = (
        module.official,
        module.repository,
        version.state,
        version.release_tag,
        version.asset_name,
        version.download_url,
        version.asset_bytes,
        version.sha256,
        version.manifest_sha256,
    )
    lock_identity = (
        True,
        lock.repository,
        "active",
        lock.release_tag,
        lock.release_asset,
        lock.download_url,
        lock.asset_bytes,
        lock.sha256,
        lock.manifest_sha256,
    )
    if registry_identity != lock_identity:
        raise ValueError(
            "official seed lock does not match the signed Registry"
        )
    verified = verify_workshop_seed(seed_archive, seed_lock)
    manifest = verified.inspected.manifest
    if (
        manifest.publisher != module.publisher
        or manifest.name != module.name
        or manifest.description != module.description
        or manifest.workshop_api != version.workshop_api
        or manifest.lumina_version != version.lumina_version
        or manifest.permissions != version.permissions
    ):
        raise ValueError(
            "official seed package does not match the Registry review"
        )
    return (
        lock.module_id,
        lock.version,
        lock.release_asset,
        lock.sha256,
        key_id,
    )


def verify_workshop_release_chain(
    *,
    sdk_archive: Path,
    sdk_checksum: Path,
    frontend_package_json: Path,
    frontend_lockfile: Path,
    registry_index: Path,
    registry_signature: Path,
    registry_keys: Path,
    seed_lock: Path,
    seed_archive: Path,
) -> WorkshopReleaseChainIdentity:
    """Verify every immutable identity used by the installable Workshop.

    校验可安装式创意工坊使用的每一项不可变发布身份。

    The verifier performs no network access. Callers must supply the exact
    downloaded SDK and module assets so CI and release builds can review the
    bytes before using them.

    校验器不会访问网络；调用方必须提供下载后的 SDK 与模块精确资产，
    便于 CI 和发布构建在使用前审查其字节。
    """

    sdk_version, sdk_url = _sdk_dependency_identity(
        frontend_package_json
    )
    expected_sdk_name = f"lumina-workshop-sdk-{sdk_version}.tgz"
    if sdk_archive.name != expected_sdk_name:
        raise ValueError(
            "Workshop SDK archive name does not match its dependency URL"
        )
    sdk_bytes = _read_regular(
        sdk_archive,
        MAX_SDK_ARCHIVE_BYTES,
        label="Workshop SDK archive",
    )
    sdk_sha256 = _validate_sdk_checksum(
        archive=sdk_bytes,
        archive_name=expected_sdk_name,
        checksum_path=sdk_checksum,
    )
    _validate_sdk_lockfile(
        archive=sdk_bytes,
        sdk_url=sdk_url,
        lockfile_path=frontend_lockfile,
    )
    _validate_sdk_archive(sdk_bytes, version=sdk_version)
    (
        module_id,
        module_version,
        module_asset,
        module_sha256,
        registry_key_id,
    ) = _verify_registry_and_seed(
        registry_index=registry_index,
        registry_signature=registry_signature,
        registry_keys=registry_keys,
        seed_lock=seed_lock,
        seed_archive=seed_archive,
    )
    return WorkshopReleaseChainIdentity(
        sdk_version=sdk_version,
        sdk_sha256=sdk_sha256,
        module_id=module_id,
        module_version=module_version,
        module_asset=module_asset,
        module_sha256=module_sha256,
        registry_key_id=registry_key_id,
    )


def main() -> int:
    """Run the offline Workshop release-chain verifier."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk-archive", type=Path, required=True)
    parser.add_argument("--sdk-checksum", type=Path, required=True)
    parser.add_argument("--seed-archive", type=Path, required=True)
    parser.add_argument(
        "--frontend-package-json",
        type=Path,
        default=Path("frontend/package.json"),
    )
    parser.add_argument(
        "--frontend-lockfile",
        type=Path,
        default=Path("frontend/pnpm-lock.yaml"),
    )
    parser.add_argument(
        "--registry-index",
        type=Path,
        default=Path("assets/workshop-registry/registry-v1.json"),
    )
    parser.add_argument(
        "--registry-signature",
        type=Path,
        default=Path("assets/workshop-registry/registry-v1.sig"),
    )
    parser.add_argument(
        "--registry-keys",
        type=Path,
        default=Path("assets/workshop-registry/keys.json"),
    )
    parser.add_argument(
        "--seed-lock",
        type=Path,
        default=Path("assets/workshop-seed/seed-lock.json"),
    )
    arguments = parser.parse_args()
    identity = verify_workshop_release_chain(
        sdk_archive=arguments.sdk_archive,
        sdk_checksum=arguments.sdk_checksum,
        frontend_package_json=arguments.frontend_package_json,
        frontend_lockfile=arguments.frontend_lockfile,
        registry_index=arguments.registry_index,
        registry_signature=arguments.registry_signature,
        registry_keys=arguments.registry_keys,
        seed_lock=arguments.seed_lock,
        seed_archive=arguments.seed_archive,
    )
    sys.stdout.write(
        json.dumps(
            asdict(identity),
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
