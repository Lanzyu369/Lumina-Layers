"""Immutable Creative Workshop package models."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .constants import ALLOWED_PERMISSION_NAMES, WORKSHOP_MANIFEST_VERSION


SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-"
    r"(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*))*"
    r")?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
MODULE_ID_PATTERN = re.compile(
    r"^[a-z0-9]+(?:[.-][a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?)*$"
)


def validate_semver(value: str) -> str:
    """Return one exact SemVer string or raise a validation error.

    返回一个精确的 SemVer 字符串，否则抛出校验错误。
    """

    if SEMVER_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be valid SemVer")
    return value


class StrictFrozenModel(BaseModel):
    """Base for immutable manifest models with closed schemas."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=False,
    )


class LocalizedText(StrictFrozenModel):
    zh_cn: str = Field(alias="zh-CN", min_length=1, max_length=200)
    en_us: str = Field(alias="en-US", min_length=1, max_length=200)

    @field_validator("zh_cn", "en_us")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("localized text must not be blank")
        return normalized


class WorkshopApiRange(StrictFrozenModel):
    minimum: str = Field(alias="min")
    max_exclusive: str = Field(alias="maxExclusive")

    @field_validator("minimum", "max_exclusive")
    @classmethod
    def versions_are_semver(cls, value: str) -> str:
        return validate_semver(value)


class LuminaVersionRange(StrictFrozenModel):
    minimum: str = Field(alias="min")

    @field_validator("minimum")
    @classmethod
    def version_is_semver(cls, value: str) -> str:
        return validate_semver(value)


class WorkshopEntrypoints(StrictFrozenModel):
    ui: str

    @field_validator("ui")
    @classmethod
    def entry_is_fixed(cls, value: str) -> str:
        if value != "ui/index.html":
            raise ValueError("UI entrypoint must be ui/index.html")
        return value


class WorkshopPermission(StrictFrozenModel):
    name: str
    reason: str = Field(max_length=500)

    @field_validator("name")
    @classmethod
    def permission_is_known(cls, value: str) -> str:
        if value not in ALLOWED_PERMISSION_NAMES:
            raise ValueError(f"unknown permission: {value}")
        return value

    @field_validator("reason")
    @classmethod
    def reason_is_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("permission reason must not be blank")
        return normalized


class WorkshopManifestV1(StrictFrozenModel):
    manifest_version: int = Field(alias="manifestVersion")
    id: str = Field(min_length=3, max_length=128)
    version: str
    name: LocalizedText
    description: LocalizedText
    publisher: str = Field(min_length=1, max_length=200)
    workshop_api: WorkshopApiRange = Field(alias="workshopApi")
    lumina_version: LuminaVersionRange = Field(alias="luminaVersion")
    entrypoints: WorkshopEntrypoints
    permissions: tuple[WorkshopPermission, ...] = Field(max_length=32)

    @field_validator("manifest_version")
    @classmethod
    def manifest_version_is_supported(cls, value: int) -> int:
        if value != WORKSHOP_MANIFEST_VERSION:
            raise ValueError("unsupported manifest version")
        return value

    @field_validator("id")
    @classmethod
    def module_id_is_safe(cls, value: str) -> str:
        if MODULE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("module id must be lowercase reverse-domain style")
        return value

    @field_validator("version")
    @classmethod
    def version_is_semver(cls, value: str) -> str:
        return validate_semver(value)

    @field_validator("publisher")
    @classmethod
    def publisher_is_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("publisher must not be blank")
        return normalized

    @model_validator(mode="after")
    def permissions_are_unique(self) -> "WorkshopManifestV1":
        names = [permission.name for permission in self.permissions]
        if len(names) != len(set(names)):
            raise ValueError("manifest contains duplicate permission entries")
        return self


class InspectedWorkshopPackage(StrictFrozenModel):
    archive_path: Path
    manifest: WorkshopManifestV1
    entry_html: str
    compressed_bytes: int = Field(ge=0)
    unpacked_bytes: int = Field(ge=0)
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    member_names: tuple[str, ...]


class PackageInspectionSummary(StrictFrozenModel):
    module_id: str = Field(alias="moduleId")
    version: str
    manifest_sha256: str = Field(alias="manifestSha256")
    archive_sha256: str = Field(alias="archiveSha256")
    compressed_bytes: int = Field(alias="compressedBytes")
    unpacked_bytes: int = Field(alias="unpackedBytes")

    @classmethod
    def from_inspected(
        cls,
        inspected: InspectedWorkshopPackage,
    ) -> "PackageInspectionSummary":
        return cls.model_validate(
            {
                "moduleId": inspected.manifest.id,
                "version": inspected.manifest.version,
                "manifestSha256": inspected.manifest_sha256,
                "archiveSha256": inspected.archive_sha256,
                "compressedBytes": inspected.compressed_bytes,
                "unpackedBytes": inspected.unpacked_bytes,
            }
        )

    def as_json_object(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)
