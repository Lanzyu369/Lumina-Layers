"""Atomic persistence for Creative Workshop installation state."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from .errors import WorkshopInstallError
from .models import (
    MODULE_ID_PATTERN,
    StrictFrozenModel,
    compare_semver,
    validate_semver,
)


MAX_INSTALL_STATE_BYTES = 2 * 1024 * 1024
_STATE_LOCKS_GUARD = threading.Lock()
_STATE_LOCKS: dict[str, threading.RLock] = {}


def _shared_state_lock(path: Path) -> threading.RLock:
    key = os.fspath(path.expanduser().resolve())
    with _STATE_LOCKS_GUARD:
        return _STATE_LOCKS.setdefault(key, threading.RLock())


class InstalledModuleState(StrictFrozenModel):
    module_id: str
    source: Literal["registry", "github", "local", "seed"]
    source_repository: str = Field(max_length=2048)
    official: bool
    enabled: bool
    active_version: str | None
    previous_version: str | None
    candidate_version: str | None
    versions: tuple[str, ...] = Field(max_length=100)
    official_uninstalled: bool
    consecutive_start_failures: int = Field(ge=0, le=3)

    @field_validator("module_id")
    @classmethod
    def module_id_is_safe(cls, value: str) -> str:
        if MODULE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("module_id is invalid")
        return value

    @field_validator(
        "active_version",
        "previous_version",
        "candidate_version",
    )
    @classmethod
    def optional_versions_are_semver(
        cls,
        value: str | None,
    ) -> str | None:
        if value is not None:
            validate_semver(value)
        return value

    @field_validator("versions")
    @classmethod
    def installed_versions_are_unique_and_sorted(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        for version in value:
            validate_semver(version)
        if len(value) != len(set(value)):
            raise ValueError("installed versions must be unique")
        if any(
            compare_semver(current, previous) <= 0
            for previous, current in zip(value, value[1:])
        ):
            raise ValueError("installed versions must be increasing")
        return value

    @model_validator(mode="after")
    def references_and_tombstone_are_consistent(
        self,
    ) -> "InstalledModuleState":
        installed = set(self.versions)
        for label, value in (
            ("active_version", self.active_version),
            ("previous_version", self.previous_version),
            ("candidate_version", self.candidate_version),
        ):
            if value is not None and value not in installed:
                raise ValueError(f"{label} must reference an installed version")
        if (
            self.active_version is not None
            and self.active_version == self.previous_version
        ):
            raise ValueError("active and previous versions must differ")
        if (
            self.active_version is not None
            and self.active_version == self.candidate_version
        ):
            raise ValueError("active and candidate versions must differ")
        if self.official_uninstalled:
            if (
                not self.official
                or self.enabled
                or self.versions
                or self.active_version is not None
                or self.previous_version is not None
                or self.candidate_version is not None
            ):
                raise ValueError(
                    "official uninstall tombstone must not retain module code"
                )
        return self


class _InstallStateDocument(StrictFrozenModel):
    schema_version: int = Field(alias="schemaVersion")
    modules: tuple[InstalledModuleState, ...]

    @field_validator("schema_version")
    @classmethod
    def schema_is_supported(cls, value: int) -> int:
        if value != 1:
            raise ValueError("unsupported install-state schema")
        return value

    @model_validator(mode="after")
    def module_ids_are_unique(self) -> "_InstallStateDocument":
        module_ids = [module.module_id for module in self.modules]
        if len(module_ids) != len(set(module_ids)):
            raise ValueError("duplicate module in install state")
        return self


def _object_without_duplicates(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise WorkshopInstallError(
                f"duplicate install-state JSON field: {key!r}"
            )
        value[key] = item
    return value


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_descriptor = None
        if directory_descriptor is not None:
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


class InstallStateStore:
    """Serialize read-modify-write operations on install-state.json.

    串行化 install-state.json 的读取、修改和写入。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = _shared_state_lock(self.path)

    def _read_unlocked(self) -> tuple[InstalledModuleState, ...]:
        if not self.path.exists():
            return ()
        try:
            if self.path.stat().st_size > MAX_INSTALL_STATE_BYTES:
                raise WorkshopInstallError(
                    "install state exceeds size limit"
                )
            text = self.path.read_text(encoding="utf-8", errors="strict")
            raw = json.loads(
                text,
                object_pairs_hook=_object_without_duplicates,
            )
            document = _InstallStateDocument.model_validate(raw)
        except WorkshopInstallError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkshopInstallError(
                "install state is unreadable"
            ) from exc
        except ValidationError as exc:
            raise WorkshopInstallError(
                f"install state failed validation: {exc}"
            ) from exc
        return document.modules

    def _write_unlocked(
        self,
        modules: tuple[InstalledModuleState, ...],
    ) -> None:
        ordered = tuple(sorted(modules, key=lambda state: state.module_id))
        document = _InstallStateDocument(
            schemaVersion=1,
            modules=ordered,
        )
        payload = (
            json.dumps(
                document.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if len(payload) > MAX_INSTALL_STATE_BYTES:
            raise WorkshopInstallError("install state exceeds size limit")
        try:
            _atomic_write(self.path, payload)
        except OSError as exc:
            raise WorkshopInstallError(
                "install state could not be committed"
            ) from exc

    def list(self) -> tuple[InstalledModuleState, ...]:
        with self._lock:
            return self._read_unlocked()

    def get(self, module_id: str) -> InstalledModuleState | None:
        with self._lock:
            return next(
                (
                    state
                    for state in self._read_unlocked()
                    if state.module_id == module_id
                ),
                None,
            )

    def upsert(
        self,
        state: InstalledModuleState,
    ) -> InstalledModuleState:
        with self._lock:
            current = {
                item.module_id: item for item in self._read_unlocked()
            }
            current[state.module_id] = state
            self._write_unlocked(tuple(current.values()))
        return state

    def remove(self, module_id: str) -> None:
        with self._lock:
            current = tuple(
                state
                for state in self._read_unlocked()
                if state.module_id != module_id
            )
            self._write_unlocked(current)

    def mutate(
        self,
        module_id: str,
        callback: Callable[
            [InstalledModuleState | None],
            InstalledModuleState | None,
        ],
    ) -> InstalledModuleState | None:
        with self._lock:
            current = {
                item.module_id: item for item in self._read_unlocked()
            }
            replacement = callback(current.get(module_id))
            if replacement is None:
                current.pop(module_id, None)
            else:
                if replacement.module_id != module_id:
                    raise WorkshopInstallError(
                        "install-state mutation changed module identity"
                    )
                current[module_id] = replacement
            self._write_unlocked(tuple(current.values()))
            return replacement
