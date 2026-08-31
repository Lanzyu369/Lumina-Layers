"""Distribution boundary tests for the standalone native SVG package."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tomllib

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_distribution_pins_native_dependencies_and_licenses() -> None:
    dependencies = (
        PACKAGE_ROOT / "cmake" / "Dependencies.cmake"
    ).read_text(encoding="utf-8")
    notices = (PACKAGE_ROOT / "THIRD_PARTY_NOTICES.md").read_text(
        encoding="utf-8"
    )

    assert "59690a23981489acc3f73b8db229ef57bb69c544" in dependencies
    assert "21ebba05db8894f0c7217ad35ea518080f324946" in dependencies
    for revision in (
        "59690a23981489acc3f73b8db229ef57bb69c544",
        "21ebba05db8894f0c7217ad35ea518080f324946",
    ):
        assert "CACHE" not in dependencies.split(revision, 1)[1][:80]
    assert "EXPECTED_REVISION" not in dependencies
    assert "USE_SYSTEM_PLUTOVG OFF" in dependencies
    assert "FETCHCONTENT_SOURCE_DIR_" in dependencies
    assert "lumina_verify_dependency_sources" in dependencies
    assert "git diff --no-ext-diff --binary" in dependencies
    assert "clipper2-svg-miter-fallback.patch" in dependencies
    assert "LunaSVG" in notices
    assert "PlutoVG" in notices
    assert "Clipper2" in notices
    assert "patches/clipper2-svg-miter-fallback.patch" in notices
    assert "over-limit miter fallback" in notices
    assert "FreeType" in notices
    assert "pybind11" in notices
    assert "Version: 3.1.0" in notices

    patch_script = (
        PACKAGE_ROOT / "cmake" / "ApplyLunaSvgPatch.cmake"
    ).read_text(encoding="utf-8")
    assert "59690a23981489acc3f73b8db229ef57bb69c544" in patch_script
    assert "APPROVED_LUNASVG_REVISION" in patch_script
    assert "EXPECTED_REVISION" not in patch_script

    clipper_patch_script = (
        PACKAGE_ROOT / "cmake" / "ApplyClipper2Patch.cmake"
    ).read_text(encoding="utf-8")
    assert "21ebba05db8894f0c7217ad35ea518080f324946" in clipper_patch_script
    assert "APPROVED_CLIPPER2_REVISION" in clipper_patch_script
    assert "EXPECTED_REVISION" not in clipper_patch_script

    metadata = tomllib.loads(
        (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert "patches/**" in metadata["tool"]["scikit-build"]["sdist"][
        "include"
    ]
    assert (
        PACKAGE_ROOT / "patches" / "clipper2-svg-miter-fallback.patch"
    ).is_file()
    sdist_includes = metadata["tool"]["scikit-build"]["sdist"]["include"]
    assert "benchmarks/**" in sdist_includes
    assert "tools/**" in sdist_includes
    assert (
        PACKAGE_ROOT / "benchmarks" / "supported_scale_fixture.svg"
    ).is_file()


def test_distribution_carries_complete_third_party_license_texts() -> None:
    licenses = PACKAGE_ROOT / "THIRD_PARTY_LICENSES"
    expected_markers = {
        "LunaSVG.txt": "Permission is hereby granted, free of charge",
        "PlutoVG.txt": "Permission is hereby granted, free of charge",
        "Clipper2.txt": "Boost Software License - Version 1.0",
        "FreeType-Project.txt": "The FreeType Project LICENSE",
        "stb.txt": "This software is available under 2 licenses",
        "pybind11.txt": "Copyright (c) 2016 Wenzel Jakob",
    }

    for filename, marker in expected_markers.items():
        license_text = (licenses / filename).read_text(encoding="utf-8")
        assert marker in license_text

    metadata = tomllib.loads(
        (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert "THIRD_PARTY_LICENSES/*" in metadata["project"]["license-files"]
    assert "THIRD_PARTY_LICENSES/**" in metadata["tool"]["scikit-build"][
        "sdist"
    ]["include"]


def test_python_distribution_is_exactly_versioned_for_cpython_312() -> None:
    metadata = tomllib.loads(
        (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert metadata["project"]["name"] == "lumina-svg-core"
    assert metadata["project"]["version"] == "0.1.1"
    assert metadata["project"]["requires-python"] == "==3.12.*"
    assert metadata["project"]["license"] == "Apache-2.0"
    assert metadata["build-system"]["requires"] == [
        "scikit-build-core==1.0.3",
        "pybind11==3.1.0",
        "numpy==2.5.2",
        "cmake==4.3.4",
        "ninja==1.13.2",
    ]
    assert metadata["project"]["license-files"] == [
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "THIRD_PARTY_LICENSES/*",
    ]


def test_release_workflow_pins_actions_to_immutable_commits() -> None:
    workflow = (
        PACKAGE_ROOT / ".github" / "workflows" / "wheels.yml"
    ).read_text(encoding="utf-8")

    for pinned_action in (
        "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803",
        "pypa/cibuildwheel@1828c10ab37f080699c7b81cea34097c684a7074",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    ):
        assert pinned_action in workflow


def test_readme_declares_workspace_extraction_boundary() -> None:
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")

    assert "independent repository" in readme
    assert "Lumina Studio" in readme
    assert "VectorAnalysis" not in readme


def test_macos_source_builds_default_to_the_supported_deployment_target() -> None:
    cmake = (PACKAGE_ROOT / "CMakeLists.txt").read_text(encoding="utf-8")

    assert 'CMAKE_OSX_DEPLOYMENT_TARGET "12.0"' in cmake


def test_runtime_package_installs_notices_for_frozen_distributions() -> None:
    cmake = (PACKAGE_ROOT / "CMakeLists.txt").read_text(encoding="utf-8")

    assert "FILES LICENSE THIRD_PARTY_NOTICES.md" in cmake
    assert "DIRECTORY THIRD_PARTY_LICENSES" in cmake
    assert cmake.count("COMPONENT lumina_svg_core") >= 3


def test_cmake_revision_cache_arguments_cannot_override_pins(
    tmp_path: Path,
) -> None:
    cmake_executable = shutil.which("cmake")
    if cmake_executable is None:
        pytest.skip("CMake is unavailable")
    dependency_file = (
        PACKAGE_ROOT / "cmake" / "Dependencies.cmake"
    ).as_posix()
    probe = tmp_path / "probe-pins.cmake"
    probe.write_text(
        f'include("{dependency_file}")\n'
        'if(NOT LUMINA_LUNASVG_REVISION STREQUAL '
        '"59690a23981489acc3f73b8db229ef57bb69c544")\n'
        '  message(FATAL_ERROR "LunaSVG pin was overridden")\n'
        'endif()\n'
        'if(NOT LUMINA_CLIPPER2_REVISION STREQUAL '
        '"21ebba05db8894f0c7217ad35ea518080f324946")\n'
        '  message(FATAL_ERROR "Clipper2 pin was overridden")\n'
        'endif()\n',
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            cmake_executable,
            "-DLUMINA_LUNASVG_REVISION=deadbeef",
            "-DLUMINA_CLIPPER2_REVISION=deadbeef",
            "-P",
            str(probe),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "override_name",
    [
        "FETCHCONTENT_SOURCE_DIR_LUNASVG",
        "FETCHCONTENT_SOURCE_DIR_CLIPPER2",
    ],
)
def test_cmake_rejects_fetchcontent_source_overrides(
    tmp_path: Path,
    override_name: str,
) -> None:
    cmake_executable = shutil.which("cmake")
    if cmake_executable is None:
        pytest.skip("CMake is unavailable")
    dependency_file = (
        PACKAGE_ROOT / "cmake" / "Dependencies.cmake"
    ).as_posix()
    probe = tmp_path / f"probe-{override_name.lower()}.cmake"
    probe.write_text(
        f'include("{dependency_file}")\n'
        f'lumina_reject_dependency_source_override('
        f'{override_name.removeprefix("FETCHCONTENT_SOURCE_DIR_").lower()})\n',
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            cmake_executable,
            f"-D{override_name}={tmp_path}",
            "-P",
            str(probe),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "dependencies are immutable" in completed.stderr
