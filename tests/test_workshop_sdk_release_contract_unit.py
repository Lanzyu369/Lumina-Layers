"""Immutable Workshop SDK release contract tests."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "workshop-sdk"
SDK_TARBALL = (
    SDK_ROOT
    / "dist-package"
    / "lumina-workshop-sdk-1.0.1.tgz"
)
RELEASE_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "workshop-sdk-release.yml"
)


def _build_sdk_tarball() -> Path:
    if (
        os.environ.get(
            "LUMINA_WORKSHOP_SDK_USE_EXISTING_TARBALL",
        )
        == "1"
    ):
        assert SDK_TARBALL.is_file()
        return SDK_TARBALL
    shutil.rmtree(SDK_TARBALL.parent, ignore_errors=True)
    environment = os.environ.copy()
    environment["CI"] = "true"
    detected_pnpm = subprocess.run(
        ["pnpm", "--version"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    pnpm_command = (
        ["pnpm"]
        if detected_pnpm == "10.33.2"
        else ["pnpm", "dlx", "pnpm@10.33.2"]
    )
    subprocess.run(
        [
            *pnpm_command,
            "--dir",
            str(SDK_ROOT),
            "run",
            "pack:release",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert SDK_TARBALL.is_file()
    return SDK_TARBALL


def _read_package_json(
    archive: tarfile.TarFile,
) -> dict[str, object]:
    member = archive.getmember("package/package.json")
    extracted = archive.extractfile(member)
    assert extracted is not None
    return json.loads(extracted.read().decode("utf-8"))


def test_sdk_release_identity_is_exact() -> None:
    package = json.loads(
        (SDK_ROOT / "package.json").read_text(encoding="utf-8"),
    )

    assert package["name"] == "@lumina/workshop-sdk"
    assert package["version"] == "1.0.1"
    assert package["files"] == ["dist", "README.md", "LICENSE"]
    assert package["scripts"]["pack:release"] == (
        "pnpm run test && pnpm pack --pack-destination dist-package"
    )


def test_sdk_tarball_contains_only_public_package_files() -> None:
    tarball = _build_sdk_tarball()

    with tarfile.open(tarball, mode="r:gz") as archive:
        members = {
            member.name
            for member in archive.getmembers()
            if member.isfile()
        }
        assert "package/dist/index.js" in members
        assert "package/dist/index.d.ts" in members
        assert "package/README.md" in members
        assert "package/LICENSE" in members
        assert "package/package.json" in members
        assert all(member.startswith("package/") for member in members)
        assert not any(member.endswith(".map") for member in members)
        assert not any(
            forbidden in member
            for member in members
            for forbidden in (
                "frontend/",
                "core/",
                "api/",
                "electron/",
                "node_modules/",
                "src/",
                "test/",
            )
        )

        packed_package = _read_package_json(archive)
        scripts = packed_package.get("scripts", {})
        assert isinstance(scripts, dict)
        assert not {
            "preinstall",
            "install",
            "postinstall",
            "prepare",
        }.intersection(scripts)
        dependencies = packed_package.get("dependencies", {})
        peer_dependencies = packed_package.get("peerDependencies", {})
        assert dependencies in ({}, None)
        assert peer_dependencies in ({}, None)
        packed_text = io.BytesIO()
        for member_name in sorted(members):
            extracted = archive.extractfile(member_name)
            assert extracted is not None
            packed_text.write(extracted.read())
        release_payload = packed_text.getvalue().decode(
            "utf-8",
            errors="ignore",
        )
        assert str(REPO_ROOT) not in release_payload
        assert "react" not in {
            str(name).lower()
            for name in (
                *(
                    dependencies.keys()
                    if isinstance(dependencies, dict)
                    else ()
                ),
                *(
                    peer_dependencies.keys()
                    if isinstance(peer_dependencies, dict)
                    else ()
                ),
            )
        }


def test_release_workflow_is_immutable_and_tag_scoped() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "workshop-sdk-v*" in workflow
    assert "branches:" not in workflow
    assert "workflow_dispatch:" not in workflow
    assert "node-version: 22" in workflow
    assert "version: 10.33.2" in workflow
    assert (
        "pnpm --dir workshop-sdk install --frozen-lockfile"
        in workflow
    )
    assert "tests/test_workshop_sdk_release_contract_unit.py" in workflow
    assert (
        "LUMINA_WORKSHOP_SDK_USE_EXISTING_TARBALL=1"
        in workflow
    )
    assert '"hypothesis==6.152.4"' in workflow
    assert "sha256sum" in workflow
    assert "gh release create" in workflow
    assert "workshop-sdk-v${SDK_VERSION}" in workflow
    assert "lumina-workshop-sdk-${SDK_VERSION}.tgz.sha256" in workflow
    assert "npm publish" not in workflow
    assert "--latest" not in workflow
    assert "/latest/" not in workflow.lower()
    assert (
        "actions/checkout@"
        "11d5960a326750d5838078e36cf38b85af677262"
    ) in workflow
    assert (
        "pnpm/action-setup@"
        "b906affcce14559ad1aafd4ab0e942779e9f58b1"
    ) in workflow
    assert (
        "actions/setup-node@"
        "49933ea5288caeca8642d1e84afbd3f7d6820020"
    ) in workflow
