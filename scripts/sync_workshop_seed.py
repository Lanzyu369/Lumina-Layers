"""Create an official Workshop seed lock from a verified Registry record."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.workshop import (
    WorkshopPackageError,
    WorkshopReleaseError,
    WorkshopSeedLock,
    download_registry_package,
    inspect_workshop_package,
    load_registry_keys,
)
from core.workshop.constants import WORKSHOP_API_VERSION
from core.workshop.models import RegistryVersion
from core.workshop.registry_client import (
    MAX_REGISTRY_BYTES,
    MAX_SIGNATURE_METADATA_BYTES,
    parse_registry_index,
    select_install_candidate,
    verify_registry_signature,
)


LUMINA_VERSION = "2.0.1"
SeedPackageDownloader = Callable[[RegistryVersion], Path]


@dataclass(frozen=True, slots=True)
class WorkshopSeedSyncResult:
    """Verified output paths and immutable seed identity."""

    lock: WorkshopSeedLock
    package_path: Path
    checksum_path: Path


def _read_bounded(path: Path, maximum: int, *, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    size = path.stat().st_size
    if size < 1 or size > maximum:
        raise ValueError(f"{label} has an invalid size")
    return path.read_bytes()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_copy(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as input_stream, os.fdopen(
            descriptor,
            "wb",
        ) as output_stream:
            shutil.copyfileobj(
                input_stream,
                output_stream,
                length=1024 * 1024,
            )
            output_stream.flush()
            os.fsync(output_stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _select_official_version(
    *,
    registry_path: Path,
    signature_path: Path,
    keys_path: Path,
    module_id: str,
    version: str,
) -> tuple[object, RegistryVersion]:
    index_bytes = _read_bounded(
        registry_path,
        MAX_REGISTRY_BYTES,
        label="Registry index",
    )
    signature_bytes = _read_bounded(
        signature_path,
        MAX_SIGNATURE_METADATA_BYTES,
        label="Registry signature",
    )
    keys = load_registry_keys(keys_path)
    verify_registry_signature(index_bytes, signature_bytes, keys)
    index = parse_registry_index(index_bytes)
    module = next(
        (
            candidate
            for candidate in index.modules
            if candidate.module_id == module_id
        ),
        None,
    )
    if module is None:
        raise ValueError("official seed module was not found in Registry")
    if not module.official:
        raise ValueError("Workshop seed module must be official")
    candidate = next(
        (
            item
            for item in module.versions
            if item.version == version
        ),
        None,
    )
    if candidate is None:
        raise ValueError("official seed version was not found in Registry")
    if candidate.state != "active":
        raise ValueError("official seed version must be active")
    compatible = select_install_candidate(
        index,
        module_id,
        lumina_version=LUMINA_VERSION,
        workshop_api_version=WORKSHOP_API_VERSION,
        requested_version=version,
    )
    if compatible is None or compatible.version != version:
        raise ValueError("official seed version is not compatible")
    return module, candidate


def sync_workshop_seed(
    *,
    module_id: str,
    version: str,
    registry_path: Path,
    signature_path: Path,
    keys_path: Path,
    lock_output: Path,
    package_output: Path,
    package_downloader: SeedPackageDownloader | None = None,
) -> WorkshopSeedSyncResult:
    """Download and pin one active official seed from signed Registry bytes.

    从已签名 Registry 字节下载并锁定一个启用中的官方预装模块。

    Args:
        module_id: Exact official module ID. 精确的官方模块 ID。
        version: Explicit full SemVer. 明确的完整 SemVer。
        registry_path: Verified-index candidate. 待验证的索引文件。
        signature_path: Detached Registry signature. Registry 分离签名。
        keys_path: App-owned trusted key set. 应用持有的可信密钥集合。
        lock_output: Committed seed-lock destination. 锁文件目标。
        package_output: Explicit build-cache package destination.
            明确的构建缓存安装包目标。
        package_downloader: Optional test downloader.
            可选的测试下载器。

    Returns:
        Verified lock and output paths. 已验证的锁与输出路径。

    Raises:
        ValueError: If any identity, state, byte, or manifest check fails.
            任一身份、状态、字节或清单校验失败时抛出。
    """

    module, candidate = _select_official_version(
        registry_path=registry_path,
        signature_path=signature_path,
        keys_path=keys_path,
        module_id=module_id,
        version=version,
    )
    if package_output.name != candidate.asset_name:
        raise ValueError(
            "package output name must match Registry release asset"
        )
    downloaded: Path | None = None
    try:
        try:
            downloaded = (package_downloader or download_registry_package)(
                candidate
            )
        except (WorkshopReleaseError, WorkshopPackageError) as exc:
            raise ValueError(
                "official seed package download failed verification"
            ) from exc
        if downloaded.is_symlink() or not downloaded.is_file():
            raise ValueError("official seed downloader returned no package")
        try:
            inspected = inspect_workshop_package(downloaded)
        except WorkshopPackageError as exc:
            raise ValueError(
                "official seed package failed static validation"
            ) from exc
        if inspected.compressed_bytes != candidate.asset_bytes:
            raise ValueError("official seed package byte count changed")
        if not hmac.compare_digest(
            inspected.archive_sha256,
            candidate.sha256,
        ):
            raise ValueError("official seed package digest changed")
        if not hmac.compare_digest(
            inspected.manifest_sha256,
            candidate.manifest_sha256,
        ):
            raise ValueError("official seed manifest digest changed")
        manifest = inspected.manifest
        if (
            manifest.id != module_id
            or manifest.version != version
            or manifest.publisher != module.publisher
            or manifest.workshop_api != candidate.workshop_api
            or manifest.lumina_version != candidate.lumina_version
            or manifest.permissions != candidate.permissions
        ):
            raise ValueError(
                "official seed manifest does not match Registry review"
            )
        lock = WorkshopSeedLock.model_validate(
            {
                "schemaVersion": 1,
                "moduleId": module_id,
                "version": version,
                "repository": module.repository,
                "releaseTag": candidate.release_tag,
                "releaseAsset": candidate.asset_name,
                "downloadUrl": candidate.download_url,
                "assetBytes": candidate.asset_bytes,
                "sha256": candidate.sha256,
                "manifestSha256": candidate.manifest_sha256,
            }
        )
        _atomic_copy(downloaded, package_output)
        checksum_output = package_output.with_suffix(
            f"{package_output.suffix}.sha256"
        )
        _atomic_write(
            checksum_output,
            (
                f"{lock.sha256}  {lock.release_asset}\n"
            ).encode("ascii"),
        )
        _atomic_write(
            lock_output,
            (
                json.dumps(
                    lock.model_dump(by_alias=True, mode="json"),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8"),
        )
        return WorkshopSeedSyncResult(
            lock=lock,
            package_path=package_output,
            checksum_path=checksum_output,
        )
    finally:
        if downloaded is not None:
            downloaded.unlink(missing_ok=True)


def main() -> int:
    """Run the official Workshop seed synchronization CLI."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--module-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument(
        "--keys",
        type=Path,
        default=Path("assets/workshop-registry/keys.json"),
    )
    parser.add_argument("--lock-output", type=Path, required=True)
    parser.add_argument("--package-output", type=Path, required=True)
    arguments = parser.parse_args()
    sync_workshop_seed(
        module_id=arguments.module_id,
        version=arguments.version,
        registry_path=arguments.registry,
        signature_path=arguments.signature,
        keys_path=arguments.keys,
        lock_output=arguments.lock_output,
        package_output=arguments.package_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
