"""Official Creative Workshop seed-lock contract."""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, field_validator, model_validator

from .constants import MAX_PACKAGE_BYTES
from .errors import WorkshopInstallError
from .install_store import InstalledModuleState
from .installer import WorkshopInstaller
from .models import (
    MODULE_ID_PATTERN,
    InspectedWorkshopPackage,
    StrictFrozenModel,
    compare_semver,
    validate_semver,
)
from .package_validator import inspect_workshop_package


MAX_SEED_LOCK_BYTES = 64 * 1024


class WorkshopSeedLock(StrictFrozenModel):
    """Immutable identity of one bundled official Workshop package.

    一个随应用打包的官方创意工坊模块的不可变身份。
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=False,
    )

    schema_version: int = Field(alias="schemaVersion")
    module_id: str = Field(alias="moduleId", min_length=3, max_length=128)
    version: str
    repository: str = Field(min_length=1, max_length=500)
    release_tag: str = Field(alias="releaseTag", min_length=2, max_length=160)
    release_asset: str = Field(
        alias="releaseAsset",
        min_length=1,
        max_length=240,
    )
    download_url: str = Field(
        alias="downloadUrl",
        min_length=1,
        max_length=2048,
    )
    asset_bytes: int = Field(
        alias="assetBytes",
        gt=0,
        le=MAX_PACKAGE_BYTES,
    )
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(
        alias="manifestSha256",
        pattern=r"^[0-9a-f]{64}$",
    )

    @field_validator("schema_version")
    @classmethod
    def schema_is_supported(cls, value: int) -> int:
        if value != 1:
            raise ValueError("unsupported Workshop seed-lock schema")
        return value

    @field_validator("module_id")
    @classmethod
    def module_id_is_safe(cls, value: str) -> str:
        if MODULE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("seed moduleId is invalid")
        return value

    @field_validator("version")
    @classmethod
    def version_is_semver(cls, value: str) -> str:
        return validate_semver(value)

    @field_validator("repository")
    @classmethod
    def repository_is_exact_github_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        parts = tuple(part for part in parsed.path.split("/") if part)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
            or value.endswith("/")
            or len(parts) != 2
            or parts[1].endswith(".git")
        ):
            raise ValueError(
                "seed repository must be an exact GitHub HTTPS URL"
            )
        return value

    @model_validator(mode="after")
    def release_identity_is_exact(self) -> "WorkshopSeedLock":
        expected_tag = f"v{self.version}"
        expected_asset = (
            f"{self.module_id}-{self.version}.lumina-workshop"
        )
        expected_url = (
            f"{self.repository}/releases/download/"
            f"{expected_tag}/{expected_asset}"
        )
        if self.release_tag != expected_tag:
            raise ValueError("seed releaseTag must equal v<version>")
        if self.release_asset != expected_asset:
            raise ValueError(
                "seed releaseAsset must match moduleId and version"
            )
        if self.download_url != expected_url:
            raise ValueError(
                "seed downloadUrl must be the immutable Release asset"
            )
        return self


def load_workshop_seed_lock(path: str | Path) -> WorkshopSeedLock:
    """Load one bounded regular seed-lock file.

    读取一份大小受限的普通预装模块锁文件。

    Args:
        path: Seed-lock JSON path. 预装模块锁文件路径。

    Returns:
        Validated immutable seed identity. 已验证的不可变预装身份。

    Raises:
        ValueError: If the file or payload is invalid.
            文件或内容不合法时抛出。
    """

    lock_path = Path(path)
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ValueError("Workshop seed lock must be a regular file")
    if lock_path.stat().st_size > MAX_SEED_LOCK_BYTES:
        raise ValueError("Workshop seed lock exceeds its size limit")
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        return WorkshopSeedLock.model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, ValueError) and not isinstance(
            exc,
            json.JSONDecodeError,
        ):
            raise
        raise ValueError("Workshop seed lock is invalid") from exc


@dataclass(frozen=True, slots=True)
class VerifiedWorkshopSeed:
    """A package whose bytes and manifest match its immutable seed lock.

    字节与清单均匹配不可变锁文件的预装模块包。
    """

    lock: WorkshopSeedLock
    archive_path: Path
    inspected: InspectedWorkshopPackage


@dataclass(frozen=True, slots=True)
class WorkshopSeedConvergenceResult:
    """Outcome of reconciling one verified seed with the install store.

    将一个已验证预装模块与安装状态收敛后的结果。
    """

    action: Literal[
        "installed",
        "restored",
        "unchanged",
        "newer-installed",
        "user-uninstalled",
    ]
    module_id: str
    version: str
    state: InstalledModuleState | None


def verify_workshop_seed(
    seed_path: str | Path,
    lock_path: str | Path,
) -> VerifiedWorkshopSeed:
    """Verify an exact seed archive against an immutable lock.

    对照不可变锁文件校验一个精确的预装模块安装包。

    Args:
        seed_path: Exact package path. 精确安装包路径。
        lock_path: Immutable lock path. 不可变锁文件路径。

    Returns:
        Fully inspected seed identity. 已完成静态检查的预装身份。

    Raises:
        ValueError: If the resource identity differs from its lock.
            资源身份与锁文件不一致时抛出。
        WorkshopPackageError: If static package inspection fails.
            安装包未通过静态安全检查时抛出。
    """

    lock = load_workshop_seed_lock(lock_path)
    archive_path = Path(seed_path)
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError("Workshop seed must be a regular file")
    if archive_path.name != lock.release_asset:
        raise ValueError("Workshop seed asset name does not match lock")
    if archive_path.stat().st_size != lock.asset_bytes:
        raise ValueError("Workshop seed byte count does not match lock")

    inspected = inspect_workshop_package(archive_path)
    if not hmac.compare_digest(inspected.archive_sha256, lock.sha256):
        raise ValueError("Workshop seed SHA-256 does not match lock")
    if (
        inspected.manifest.id != lock.module_id
        or inspected.manifest.version != lock.version
    ):
        raise ValueError("Workshop seed package identity does not match lock")
    if not hmac.compare_digest(
        inspected.manifest_sha256,
        lock.manifest_sha256,
    ):
        raise ValueError("Workshop seed manifest SHA-256 does not match lock")
    return VerifiedWorkshopSeed(
        lock=lock,
        archive_path=archive_path,
        inspected=inspected,
    )


def verify_workshop_seed_directory(
    seed_directory: str | Path,
) -> VerifiedWorkshopSeed:
    """Load and verify the single locked package in a seed directory.

    读取并校验预装目录中由锁文件精确指定的安装包。
    """

    directory = Path(seed_directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Workshop seed must be a regular directory")
    lock_path = directory / "seed-lock.json"
    lock = load_workshop_seed_lock(lock_path)
    return verify_workshop_seed(
        directory / lock.release_asset,
        lock_path,
    )


def _require_existing_code(
    installer: WorkshopInstaller,
    state: InstalledModuleState,
    version: str,
) -> None:
    if not installer.version_path(state.module_id, version).is_dir():
        raise WorkshopInstallError(
            "installed Workshop seed state is missing module code"
        )


def converge_workshop_seed(
    seed_directory: str | Path,
    installer: WorkshopInstaller,
    *,
    restore_uninstalled: bool = False,
    expected_module_id: str | None = None,
) -> WorkshopSeedConvergenceResult:
    """Safely reconcile one bundled official package with installed state.

    将一个随应用打包的官方模块安全地收敛到本地安装状态。

    Automatic startup never clears an uninstall tombstone and never
    downgrades a newer installed version. Explicit restore is accepted only
    for the matching official tombstone, and the installer clears that
    tombstone only after the candidate transaction commits.

    自动启动不会清除用户卸载墓碑，也不会降级较新的已安装版本。显式恢复仅
    接受匹配的官方墓碑，且只有候选安装事务提交后才会清除墓碑。
    """

    verified = verify_workshop_seed_directory(seed_directory)
    lock = verified.lock
    if (
        expected_module_id is not None
        and lock.module_id != expected_module_id
    ):
        raise ValueError(
            "Workshop seed does not match the requested module"
        )

    existing = installer.get(lock.module_id)
    if restore_uninstalled:
        if (
            existing is None
            or not existing.official
            or not existing.official_uninstalled
        ):
            raise WorkshopInstallError(
                "official module is not awaiting seed restore"
            )
    elif existing is not None and existing.official_uninstalled:
        return WorkshopSeedConvergenceResult(
            action="user-uninstalled",
            module_id=lock.module_id,
            version=lock.version,
            state=existing,
        )

    if existing is not None and not existing.official_uninstalled:
        if not existing.official:
            raise WorkshopInstallError(
                "bundled official module conflicts with community identity"
            )
        if existing.source_repository != lock.repository:
            raise WorkshopInstallError(
                "bundled official module source repository cannot change"
            )
        if existing.versions:
            newest_version = existing.versions[-1]
            _require_existing_code(installer, existing, newest_version)
            comparison = compare_semver(newest_version, lock.version)
            if comparison > 0:
                return WorkshopSeedConvergenceResult(
                    action="newer-installed",
                    module_id=lock.module_id,
                    version=lock.version,
                    state=existing,
                )
            if comparison == 0:
                return WorkshopSeedConvergenceResult(
                    action="unchanged",
                    module_id=lock.module_id,
                    version=lock.version,
                    state=existing,
                )

    state = installer.install_candidate(
        verified.archive_path,
        source="seed",
        source_repository=lock.repository,
        official=True,
        restore_official=restore_uninstalled,
    )
    return WorkshopSeedConvergenceResult(
        action="restored" if restore_uninstalled else "installed",
        module_id=lock.module_id,
        version=lock.version,
        state=state,
    )
