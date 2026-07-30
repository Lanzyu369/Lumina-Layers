"""Synchronize one reviewed Registry public key into Lumina trust roots."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.workshop.registry_client import load_registry_keys


PRODUCTION_KEY_ID = "registry-2026-01"
MAX_PUBLIC_RECORD_BYTES = 16 * 1024


class _PublicKeyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm: Literal["Ed25519"]
    key_id: str = Field(alias="keyId")
    public_key: str = Field(alias="publicKey")


def _object_without_duplicates(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate public-key field: {key!r}")
        value[key] = item
    return value


def _load_record(path: Path) -> _PublicKeyRecord:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Registry public-key source must be a regular file")
    payload = path.read_bytes()
    if not payload or len(payload) > MAX_PUBLIC_RECORD_BYTES:
        raise ValueError("Registry public-key source has an invalid size")
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_without_duplicates,
        )
        record = _PublicKeyRecord.model_validate(value)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValidationError,
    ) as exc:
        raise ValueError("Registry public-key record is invalid") from exc
    if record.key_id != PRODUCTION_KEY_ID:
        raise ValueError("Registry public-key ID is not the production key")
    try:
        decoded = base64.b64decode(
            record.public_key.encode("ascii"),
            validate=True,
        )
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise ValueError(
            "Registry public key is not canonical base64"
        ) from exc
    if (
        len(decoded) != 32
        or base64.b64encode(decoded).decode("ascii") != record.public_key
    ):
        raise ValueError("Registry Ed25519 public key must be 32 bytes")
    return record


def sync_registry_key(*, source: Path, output: Path) -> None:
    """Write one reviewed key as Lumina's closed trusted-key set.

    将一条已审核公钥写入 Lumina 的封闭可信密钥集合。

    Args:
        source: Strict public-key record from the Registry repository.
            Registry 仓库中的严格公钥记录。
        output: Application-owned key-set destination.
            由应用持有的密钥集合目标文件。

    Raises:
        ValueError: If the record is malformed or changes production identity.
            当记录格式错误或试图替换生产密钥身份时抛出。
    """

    record = _load_record(source)
    payload = (
        json.dumps(
            {
                "schemaVersion": 1,
                "keys": [
                    record.model_dump(
                        by_alias=True,
                        mode="json",
                    )
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        loaded = load_registry_keys(temporary)
        if set(loaded) != {PRODUCTION_KEY_ID}:
            raise ValueError("generated Registry key set changed identity")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Run the public-key synchronization CLI."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    sync_registry_key(
        source=arguments.public_key,
        output=arguments.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
