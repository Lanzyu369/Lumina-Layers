"""Verify and synchronize exact signed Workshop Registry snapshot bytes."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.workshop.registry_client import (
    MAX_REGISTRY_BYTES,
    MAX_SIGNATURE_METADATA_BYTES,
    load_registry_keys,
    parse_registry_index,
    verify_registry_signature,
)


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


def _download(url: str, output: Path, maximum: int) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Registry source URL must be credential-free HTTPS")
    timeout = httpx.Timeout(
        connect=15.0,
        read=60.0,
        write=60.0,
        pool=15.0,
    )
    received = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        httpx.Client(timeout=timeout, follow_redirects=False) as client,
        client.stream(
            "GET",
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Lumina-Workshop-Snapshot-Sync/1",
            },
        ) as response,
    ):
        if response.status_code != 200:
            raise ValueError(
                f"Registry source returned status {response.status_code}"
            )
        with output.open("xb") as stream:
            for chunk in response.iter_bytes():
                received += len(chunk)
                if received > maximum:
                    raise ValueError("Registry source exceeds size limit")
                stream.write(chunk)
    if received < 1:
        output.unlink(missing_ok=True)
        raise ValueError("Registry source is empty")


def sync_registry_snapshot(
    *,
    index_source: Path,
    signature_source: Path,
    keys_path: Path,
    index_output: Path,
    signature_output: Path,
) -> None:
    """Verify and atomically copy exact Registry index and signature bytes.

    验证并原子复制 Registry 索引与签名的精确字节。

    Args:
        index_source: Signed Registry index file. 已签名索引文件。
        signature_source: Detached signature metadata. 分离签名元数据。
        keys_path: App-owned trusted key set. 应用持有的可信密钥集合。
        index_output: Bundled index destination. 内置索引目标。
        signature_output: Bundled signature destination. 内置签名目标。

    Raises:
        ValueError: If an input file is malformed.
            输入文件格式错误时抛出。
        WorkshopRegistryError: If signature or index verification fails.
            签名或索引验证失败时抛出。
    """

    index_bytes = _read_bounded(
        index_source,
        MAX_REGISTRY_BYTES,
        label="Registry index source",
    )
    signature_bytes = _read_bounded(
        signature_source,
        MAX_SIGNATURE_METADATA_BYTES,
        label="Registry signature source",
    )
    keys = load_registry_keys(keys_path)
    verify_registry_signature(index_bytes, signature_bytes, keys)
    parse_registry_index(index_bytes)
    _atomic_write(index_output, index_bytes)
    _atomic_write(signature_output, signature_bytes)


def main() -> int:
    """Run the signed Registry snapshot synchronization CLI."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--index-url")
    parser.add_argument("--signature-url")
    parser.add_argument("--index-file", type=Path)
    parser.add_argument("--signature-file", type=Path)
    parser.add_argument(
        "--keys",
        type=Path,
        default=Path("assets/workshop-registry/keys.json"),
    )
    parser.add_argument(
        "--index-output",
        type=Path,
        default=Path("assets/workshop-registry/registry-v1.json"),
    )
    parser.add_argument(
        "--signature-output",
        type=Path,
        default=Path("assets/workshop-registry/registry-v1.sig"),
    )
    arguments = parser.parse_args()
    local_pair = (
        arguments.index_file is not None
        and arguments.signature_file is not None
        and arguments.index_url is None
        and arguments.signature_url is None
    )
    remote_pair = (
        arguments.index_url is not None
        and arguments.signature_url is not None
        and arguments.index_file is None
        and arguments.signature_file is None
    )
    if not local_pair and not remote_pair:
        parser.error(
            "provide exactly one complete local or remote Registry pair"
        )

    if local_pair:
        index_source = arguments.index_file
        signature_source = arguments.signature_file
        assert index_source is not None
        assert signature_source is not None
        sync_registry_snapshot(
            index_source=index_source,
            signature_source=signature_source,
            keys_path=arguments.keys,
            index_output=arguments.index_output,
            signature_output=arguments.signature_output,
        )
        return 0

    with tempfile.TemporaryDirectory(
        prefix="lumina-workshop-registry-sync-"
    ) as temporary_directory:
        directory = Path(temporary_directory)
        index_source = directory / "registry-v1.json"
        signature_source = directory / "registry-v1.sig"
        assert arguments.index_url is not None
        assert arguments.signature_url is not None
        try:
            _download(
                arguments.index_url,
                index_source,
                MAX_REGISTRY_BYTES,
            )
            _download(
                arguments.signature_url,
                signature_source,
                MAX_SIGNATURE_METADATA_BYTES,
            )
            sync_registry_snapshot(
                index_source=index_source,
                signature_source=signature_source,
                keys_path=arguments.keys,
                index_output=arguments.index_output,
                signature_output=arguments.signature_output,
            )
        except Exception:
            index_source.unlink(missing_ok=True)
            signature_source.unlink(missing_ok=True)
            raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
