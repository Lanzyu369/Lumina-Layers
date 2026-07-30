"""Official Creative Workshop seed-lock contract."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, field_validator, model_validator

from .constants import MAX_PACKAGE_BYTES
from .models import MODULE_ID_PATTERN, StrictFrozenModel, validate_semver


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
