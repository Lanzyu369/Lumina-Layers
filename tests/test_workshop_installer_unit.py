from __future__ import annotations

import base64
import errno
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from config import get_workshop_data_dir
from core.workshop import WorkshopInstallError, WorkshopInstaller


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def package(
    tmp_path: Path,
    version: str,
    *,
    module_id: str = "fixture.hello",
) -> Path:
    archive = tmp_path / f"{module_id}-{version}.lumina-workshop"
    manifest = {
        "manifestVersion": 1,
        "id": module_id,
        "version": version,
        "name": {
            "zh-CN": "测试模块",
            "en-US": "Fixture module",
        },
        "description": {
            "zh-CN": "安装事务测试",
            "en-US": "Installer transaction tests",
        },
        "publisher": "Fixture Publisher",
        "workshopApi": {
            "min": "1.0.0",
            "maxExclusive": "2.0.0",
        },
        "luminaVersion": {
            "min": "1.0.0",
        },
        "entrypoints": {
            "ui": "ui/index.html",
        },
        "permissions": [
            {
                "name": "project.storage",
                "reason": "Save fixture projects.",
            }
        ],
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
            b"<!doctype html><html><head></head><body>fixture</body></html>",
        )
        output.writestr("assets/icon.png", PNG_1X1)
        output.writestr("README.md", b"# Fixture\n")
        output.writestr("LICENSE", b"MIT\n")
    return archive


def installer_for(
    tmp_path: Path,
    *,
    after_extract=None,
    directory_replace=os.replace,
) -> WorkshopInstaller:
    return WorkshopInstaller(
        data_dir=tmp_path / "workshop-data",
        after_extract=after_extract,
        directory_replace=directory_replace,
    )


def install_candidate(
    installer: WorkshopInstaller,
    archive: Path,
    *,
    source: str = "registry",
    official: bool = False,
) -> None:
    installer.install_candidate(
        archive,
        source=source,
        source_repository=(
            "https://github.com/lumina-layer-studio/Fixture-Workshop"
        ),
        official=official,
    )


def install_and_activate(
    installer: WorkshopInstaller,
    archive: Path,
    *,
    source: str = "registry",
    official: bool = False,
) -> None:
    install_candidate(
        installer,
        archive,
        source=source,
        official=official,
    )
    installer.activate("fixture.hello", archive.stem.rsplit("-", 1)[-1])


def required_state(installer: WorkshopInstaller):
    state = installer.get("fixture.hello")
    assert state is not None
    return state


def test_candidate_install_does_not_replace_active_version(
    tmp_path: Path,
) -> None:
    installer = installer_for(tmp_path)
    first = package(tmp_path, "1.0.0")
    second = package(tmp_path, "1.1.0")
    install_and_activate(installer, first)

    install_candidate(installer, second)

    state = required_state(installer)
    assert state.active_version == "1.0.0"
    assert state.candidate_version == "1.1.0"
    assert installer.version_path("fixture.hello", "1.0.0").is_dir()
    assert installer.version_path("fixture.hello", "1.1.0").is_dir()


def test_activation_keeps_one_rollback_version(tmp_path: Path) -> None:
    installer = installer_for(tmp_path)
    install_and_activate(installer, package(tmp_path, "1.0.0"))
    install_and_activate(installer, package(tmp_path, "1.1.0"))

    state = required_state(installer)
    assert state.active_version == "1.1.0"
    assert state.previous_version == "1.0.0"

    rolled_back = installer.rollback("fixture.hello")

    assert rolled_back.active_version == "1.0.0"
    assert rolled_back.previous_version == "1.1.0"


def test_interrupted_extract_leaves_active_version_untouched(
    tmp_path: Path,
) -> None:
    normal = installer_for(tmp_path)
    install_and_activate(normal, package(tmp_path, "1.0.0"))

    def fail_after_extract(inspected, _staging_path: Path) -> None:
        if inspected.manifest.version == "1.1.0":
            raise RuntimeError("simulated interruption")

    interrupted = installer_for(
        tmp_path,
        after_extract=fail_after_extract,
    )
    with pytest.raises(WorkshopInstallError, match="candidate installation"):
        install_candidate(interrupted, package(tmp_path, "1.1.0"))

    state = required_state(interrupted)
    assert state.active_version == "1.0.0"
    assert state.candidate_version is None
    assert not interrupted.version_path(
        "fixture.hello",
        "1.1.0",
    ).exists()
    assert list(interrupted.staging_dir.iterdir()) == []


def test_new_candidate_cleans_up_an_unactivated_candidate(
    tmp_path: Path,
) -> None:
    installer = installer_for(tmp_path)
    install_and_activate(installer, package(tmp_path, "1.0.0"))
    install_candidate(installer, package(tmp_path, "1.1.0"))
    install_candidate(installer, package(tmp_path, "1.2.0"))

    state = required_state(installer)
    assert state.candidate_version == "1.2.0"
    assert state.versions == ("1.0.0", "1.2.0")
    assert not installer.version_path("fixture.hello", "1.1.0").exists()


def test_disable_and_enable_preserve_installed_code(tmp_path: Path) -> None:
    installer = installer_for(tmp_path)
    install_and_activate(installer, package(tmp_path, "1.0.0"))

    disabled = installer.set_enabled("fixture.hello", False)
    enabled = installer.set_enabled("fixture.hello", True)

    assert disabled.enabled is False
    assert enabled.enabled is True
    assert installer.version_path("fixture.hello", "1.0.0").is_dir()


def test_uninstall_preserves_projects_by_default(tmp_path: Path) -> None:
    installer = installer_for(tmp_path)
    install_and_activate(installer, package(tmp_path, "1.0.0"))
    project = installer.project_data_path("fixture.hello") / "project.json"
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")

    installer.uninstall("fixture.hello")

    assert installer.get("fixture.hello") is None
    assert project.is_file()
    assert not installer.module_path("fixture.hello").exists()


def test_uninstall_can_explicitly_delete_projects(tmp_path: Path) -> None:
    installer = installer_for(tmp_path)
    install_and_activate(installer, package(tmp_path, "1.0.0"))
    project_root = installer.project_data_path("fixture.hello")
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text("{}", encoding="utf-8")

    installer.uninstall("fixture.hello", delete_projects=True)

    assert not project_root.exists()


def test_official_uninstall_tombstone_blocks_seed_resurrection(
    tmp_path: Path,
) -> None:
    installer = installer_for(tmp_path)
    seed = package(tmp_path, "1.0.0")
    install_and_activate(
        installer,
        seed,
        source="seed",
        official=True,
    )

    installer.uninstall("fixture.hello")

    tombstone = required_state(installer)
    assert tombstone.official_uninstalled is True
    assert tombstone.versions == ()
    with pytest.raises(WorkshopInstallError, match="uninstalled"):
        install_candidate(
            installer,
            seed,
            source="seed",
            official=True,
        )

    install_candidate(
        installer,
        seed,
        source="registry",
        official=True,
    )
    assert required_state(installer).official_uninstalled is False


def test_cross_device_candidate_rename_is_rejected(tmp_path: Path) -> None:
    normal = installer_for(tmp_path)
    install_and_activate(normal, package(tmp_path, "1.0.0"))

    def cross_device(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EXDEV, "cross-device link")

    installer = installer_for(
        tmp_path,
        directory_replace=cross_device,
    )

    with pytest.raises(WorkshopInstallError, match="same filesystem"):
        install_candidate(installer, package(tmp_path, "1.1.0"))

    assert required_state(installer).active_version == "1.0.0"
    assert not installer.version_path("fixture.hello", "1.1.0").exists()


def test_existing_module_identity_cannot_be_replaced_by_local_source(
    tmp_path: Path,
) -> None:
    installer = installer_for(tmp_path)
    install_and_activate(installer, package(tmp_path, "1.0.0"))

    with pytest.raises(WorkshopInstallError, match="source repository"):
        installer.install_candidate(
            package(tmp_path, "1.1.0"),
            source="local",
            source_repository="",
            official=False,
        )

    state = required_state(installer)
    assert state.active_version == "1.0.0"
    assert state.candidate_version is None
    assert not installer.version_path("fixture.hello", "1.1.0").exists()


def test_same_module_candidate_installs_are_serialized(
    tmp_path: Path,
) -> None:
    guard = threading.Lock()
    active_extractions = 0
    maximum_concurrency = 0

    def observe_extract(_inspected, _staging_path: Path) -> None:
        nonlocal active_extractions, maximum_concurrency
        with guard:
            active_extractions += 1
            maximum_concurrency = max(
                maximum_concurrency,
                active_extractions,
            )
        time.sleep(0.03)
        with guard:
            active_extractions -= 1

    installer = installer_for(tmp_path, after_extract=observe_extract)
    archives = [
        package(tmp_path, "1.0.0"),
        package(tmp_path, "1.1.0"),
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(install_candidate, installer, archive)
            for archive in archives
        ]
        for future in futures:
            future.result()

    assert maximum_concurrency == 1
    state = required_state(installer)
    assert len(state.versions) == 1
    assert state.candidate_version in {"1.0.0", "1.1.0"}


def test_same_module_lock_is_shared_across_installer_instances(
    tmp_path: Path,
) -> None:
    guard = threading.Lock()
    active_extractions = 0
    maximum_concurrency = 0

    def observe_extract(_inspected, _staging_path: Path) -> None:
        nonlocal active_extractions, maximum_concurrency
        with guard:
            active_extractions += 1
            maximum_concurrency = max(
                maximum_concurrency,
                active_extractions,
            )
        time.sleep(0.03)
        with guard:
            active_extractions -= 1

    first_installer = installer_for(
        tmp_path,
        after_extract=observe_extract,
    )
    second_installer = installer_for(
        tmp_path,
        after_extract=observe_extract,
    )
    archives = [
        package(tmp_path, "1.0.0"),
        package(tmp_path, "1.1.0"),
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                install_candidate,
                first_installer,
                archives[0],
            ),
            executor.submit(
                install_candidate,
                second_installer,
                archives[1],
            ),
        ]
        for future in futures:
            future.result()

    assert maximum_concurrency == 1


def test_three_consecutive_start_failures_roll_back(tmp_path: Path) -> None:
    installer = installer_for(tmp_path)
    install_and_activate(installer, package(tmp_path, "1.0.0"))
    install_and_activate(installer, package(tmp_path, "1.1.0"))

    installer.record_start_failure("fixture.hello")
    installer.record_start_failure("fixture.hello")
    rolled_back = installer.record_start_failure("fixture.hello")

    assert rolled_back.active_version == "1.0.0"
    assert rolled_back.previous_version == "1.1.0"
    assert rolled_back.consecutive_start_failures == 0


def test_workshop_data_dir_honors_explicit_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override = tmp_path / "custom-workshop"
    monkeypatch.setenv("LUMINA_WORKSHOP_DATA_DIR", os.fspath(override))

    assert get_workshop_data_dir() == os.fspath(override.resolve())


def test_install_state_is_canonical_and_survives_reopen(
    tmp_path: Path,
) -> None:
    installer = installer_for(tmp_path)
    install_and_activate(installer, package(tmp_path, "1.0.0"))
    state_bytes = installer.state_path.read_bytes()

    reopened = installer_for(tmp_path)

    assert b"\n" == state_bytes[-1:]
    assert b": " not in state_bytes
    assert required_state(reopened).active_version == "1.0.0"
    assert not tuple(installer.data_dir.glob("*.tmp"))
