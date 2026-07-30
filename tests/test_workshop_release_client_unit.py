"""Creative Workshop GitHub release boundary tests."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest

from core.workshop.errors import WorkshopReleaseError
from core.workshop.models import RegistryVersion
from core.workshop.package_validator import inspect_workshop_package
from core.workshop import release_client


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
REPOSITORY = "https://github.com/lumina-layer-studio/Fixture-Workshop"


def write_package(
    tmp_path: Path,
    *,
    module_id: str = "fixture.hello",
    version: str = "1.0.0",
) -> Path:
    archive = tmp_path / f"{module_id}-{version}.lumina-workshop"
    manifest = {
        "manifestVersion": 1,
        "id": module_id,
        "version": version,
        "name": {"zh-CN": "测试模块", "en-US": "Fixture module"},
        "description": {
            "zh-CN": "Release 边界测试",
            "en-US": "Release boundary tests",
        },
        "publisher": "Fixture Publisher",
        "workshopApi": {"min": "1.0.0", "maxExclusive": "2.0.0"},
        "luminaVersion": {"min": "1.0.0"},
        "entrypoints": {"ui": "ui/index.html"},
        "permissions": [],
    }
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
        output.writestr(
            "manifest.json",
            json.dumps(
                manifest,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        output.writestr(
            "ui/index.html",
            b"<!doctype html><html><head></head><body></body></html>",
        )
        output.writestr("assets/icon.png", PNG_1X1)
        output.writestr("README.md", b"# Fixture\n")
        output.writestr("LICENSE", b"MIT\n")
    return archive


def registry_version(archive: Path) -> RegistryVersion:
    inspected = inspect_workshop_package(archive)
    return RegistryVersion.model_validate(
        {
            "version": inspected.manifest.version,
            "releaseTag": f"v{inspected.manifest.version}",
            "assetName": archive.name,
            "downloadUrl": (
                f"{REPOSITORY}/releases/download/"
                f"v{inspected.manifest.version}/{archive.name}"
            ),
            "assetBytes": archive.stat().st_size,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "manifestSha256": inspected.manifest_sha256,
            "workshopApi": {
                "min": "1.0.0",
                "maxExclusive": "2.0.0",
            },
            "luminaVersion": {"min": "1.0.0"},
            "permissions": [],
            "state": "active",
            "revocation": None,
        }
    )


def release_metadata(
    archive: Path,
    *,
    draft: bool = False,
    prerelease: bool = False,
) -> dict[str, object]:
    version = archive.name.removesuffix(
        ".lumina-workshop"
    ).rsplit("-", 1)[1]
    return {
        "tag_name": f"v{version}",
        "draft": draft,
        "prerelease": prerelease,
        "assets": [
            {
                "name": archive.name,
                "size": archive.stat().st_size,
                "browser_download_url": (
                    f"{REPOSITORY}/releases/download/"
                    f"v{version}/{archive.name}"
                ),
                "digest": (
                    "sha256:"
                    + hashlib.sha256(archive.read_bytes()).hexdigest()
                ),
            }
        ],
    }


def test_registry_download_revalidates_exact_package_identity(
    tmp_path: Path,
) -> None:
    archive = write_package(tmp_path)
    candidate = registry_version(archive)

    resolved = release_client.download_registry_package(
        candidate,
        package_downloader=lambda _url, _bytes, _sha: archive,
    )

    assert resolved == archive


def test_registry_download_removes_manifest_digest_mismatch(
    tmp_path: Path,
) -> None:
    archive = write_package(tmp_path)
    candidate = registry_version(archive).model_copy(
        update={"manifest_sha256": "f" * 64}
    )

    with pytest.raises(
        WorkshopReleaseError,
        match="manifest digest",
    ):
        release_client.download_registry_package(
            candidate,
            package_downloader=lambda _url, _bytes, _sha: archive,
        )

    assert not archive.exists()


def test_github_release_requires_one_exact_full_release_asset(
    tmp_path: Path,
) -> None:
    archive = write_package(tmp_path)
    metadata = release_metadata(archive)

    resolved = release_client.resolve_github_release_package(
        REPOSITORY,
        "1.0.0",
        fetch_json=lambda _url: metadata,
        package_downloader=lambda _url, _bytes, _sha: archive,
    )

    assert resolved == archive


@pytest.mark.parametrize(
    ("draft", "prerelease"),
    [(True, False), (False, True)],
)
def test_github_release_rejects_draft_and_prerelease(
    tmp_path: Path,
    draft: bool,
    prerelease: bool,
) -> None:
    archive = write_package(tmp_path)

    with pytest.raises(WorkshopReleaseError, match="full, public"):
        release_client.resolve_github_release_package(
            REPOSITORY,
            "1.0.0",
            fetch_json=lambda _url: release_metadata(
                archive,
                draft=draft,
                prerelease=prerelease,
            ),
            package_downloader=lambda _url, _bytes, _sha: archive,
        )


def test_github_release_rejects_cross_repository_asset(
    tmp_path: Path,
) -> None:
    archive = write_package(tmp_path)
    metadata = release_metadata(archive)
    assets = metadata["assets"]
    assert isinstance(assets, list)
    assert isinstance(assets[0], dict)
    assets[0]["browser_download_url"] = (
        "https://github.com/attacker/repository/releases/download/"
        f"v1.0.0/{archive.name}"
    )

    with pytest.raises(WorkshopReleaseError, match="requested repository"):
        release_client.resolve_github_release_package(
            REPOSITORY,
            "1.0.0",
            fetch_json=lambda _url: metadata,
            package_downloader=lambda _url, _bytes, _sha: archive,
        )


def test_github_release_rejects_encoded_repository_segment() -> None:
    with pytest.raises(WorkshopReleaseError, match="exact GitHub"):
        release_client.resolve_github_release_package(
            "https://github.com/owner/%2Frepository",
            "1.0.0",
            fetch_json=lambda _url: {},
            package_downloader=lambda _url, _bytes, _sha: Path("unused"),
        )


def test_stream_download_blocks_redirect_outside_github(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "https://example.com/payload"},
            request=request,
        )

    monkeypatch.setattr(release_client, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(
        release_client,
        "_new_http_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        ),
    )

    with pytest.raises(WorkshopReleaseError, match="trusted GitHub"):
        release_client.stream_package_download(
            f"{REPOSITORY}/releases/download/v1.0.0/"
            "fixture.hello-1.0.0.lumina-workshop"
        )

    assert list(tmp_path.iterdir()) == []


def test_stream_download_enforces_limit_without_content_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"12345", request=request)

    monkeypatch.setattr(release_client, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(release_client, "MAX_PACKAGE_BYTES", 4)
    monkeypatch.setattr(
        release_client,
        "_new_http_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        ),
    )

    with pytest.raises(WorkshopReleaseError, match="size limit"):
        release_client.stream_package_download(
            f"{REPOSITORY}/releases/download/v1.0.0/"
            "fixture.hello-1.0.0.lumina-workshop"
        )

    assert list(tmp_path.iterdir()) == []

