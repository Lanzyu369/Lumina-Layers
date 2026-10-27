"""Production Workshop Registry public-key synchronization tests."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from core.workshop.registry_client import load_registry_keys
from scripts.sync_workshop_registry_key import sync_registry_key


def _public_record(*, key_id: str = "registry-2026-01") -> dict[str, str]:
    return {
        "algorithm": "Ed25519",
        "keyId": key_id,
        "publicKey": base64.b64encode(bytes(range(32))).decode("ascii"),
    }


def test_sync_wraps_one_strict_public_record_in_app_owned_key_set(
    tmp_path: Path,
) -> None:
    source = tmp_path / "public.json"
    output = tmp_path / "keys.json"
    source.write_text(
        json.dumps(_public_record()),
        encoding="utf-8",
    )

    sync_registry_key(source=source, output=output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "schemaVersion": 1,
        "keys": [_public_record()],
    }
    assert set(load_registry_keys(output)) == {"registry-2026-01"}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"privateKey": "forbidden"}),
        lambda value: value.update({"algorithm": "RSA"}),
        lambda value: value.update({"keyId": "registry-2026-02"}),
        lambda value: value.update({"publicKey": "YQ=="}),
    ],
)
def test_invalid_or_replacement_key_writes_nothing(
    tmp_path: Path,
    mutation,
) -> None:
    source = tmp_path / "public.json"
    output = tmp_path / "keys.json"
    output.write_text('{"keep":true}\n', encoding="utf-8")
    record = _public_record()
    mutation(record)
    source.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError):
        sync_registry_key(source=source, output=output)

    assert output.read_text(encoding="utf-8") == '{"keep":true}\n'


def test_committed_key_set_contains_only_production_key() -> None:
    keys = load_registry_keys("assets/workshop-registry/keys.json")

    assert set(keys) == {"registry-2026-01"}
