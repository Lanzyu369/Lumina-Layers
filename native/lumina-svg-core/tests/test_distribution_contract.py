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


def test_clipper_offset_range_rejects_double_two_to_the_63_boundary() -> None:
    safety = (PACKAGE_ROOT / "src" / "clipper_safety.h").read_text(
        encoding="utf-8"
    )

    assert "extension >= 0x1p63" in safety


def test_python_distribution_is_exactly_versioned_for_cpython_312() -> None:
    metadata = tomllib.loads(
        (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert metadata["project"]["name"] == "lumina-svg-core"
    assert metadata["project"]["version"] == "0.3.0"
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


def test_clipper_work_limits_cover_each_operation_and_complete_document() -> None:
    budget = (PACKAGE_ROOT / "src" / "complexity_budget.h").read_text(
        encoding="utf-8"
    )
    safety = (PACKAGE_ROOT / "src" / "clipper_safety.h").read_text(
        encoding="utf-8"
    )

    assert "requireClipperIntersectionWorkCapacity" in budget
    assert "consumeClipperIntersectionWork" in budget
    assert "consumeClipperIntersectionCandidates" in budget
    assert "consumeIntersectionWork" in safety
    assert "MAX_BOOLEAN_INPUT_POINTS_PER_DOCUMENT" in budget
    assert "MAX_CLIPPER_INTERSECTION_CANDIDATES_PER_DOCUMENT" in budget
    assert "MAX_CLIPPER_INTERSECTION_COMPARISONS_PER_DOCUMENT" in budget
    assert "MAX_CLIPPER_OUTPUT_POINTS_PER_DOCUMENT" in budget
    assert "MAX_CLIPPER_OUTPUT_RINGS_PER_DOCUMENT" in budget
    assert (
        "MAX_CLIPPER_ENGINE_INTERSECTION_NODE_ALLOCATIONS_PER_DOCUMENT"
        in budget
    )
    assert (
        "MAX_CLIPPER_ENGINE_PROCESSED_INTERSECTION_EVENTS_PER_DOCUMENT"
        in budget
    )
    assert "m_booleanInputPoints" in budget
    assert "m_clipperIntersectionComparisons" in budget
    assert "consumeClipperEngineWork" in budget
    assert "requireClipperOutputCapacity" in budget
    assert "preflightClipperOutput" in safety
    assert "requireClipperOutputCapacity(" in safety

    stroke_expander = (
        PACKAGE_ROOT / "src" / "stroke_expander.cpp"
    ).read_text(encoding="utf-8")
    assert "requireClipperOutputCapacity(" in stroke_expander


def test_normalized_pair_boolean_relies_on_bounded_clipper_not_shadow_scan() -> None:
    geometry_kernel = (
        PACKAGE_ROOT / "src" / "geometry_kernel.cpp"
    ).read_text(encoding="utf-8")
    normalized_pair = geometry_kernel.split(
        "void preflightNormalizedBoolean(ComplexityBudget& complexityBudget,\n"
        "                                const Paths64& first,\n"
        "                                const Paths64& second)",
        1,
    )[1].split("\n}\n\nclass PackedBoundsIndex", 1)[0]
    assert "requireBoundedClipperIntersections" not in normalized_pair
    assert "preflightClipperOutput(" in normalized_pair
    assert "CHEAP_CROSS_PRODUCT_LIMIT" not in normalized_pair


def test_pinned_clipper_patch_caps_internal_output_allocations() -> None:
    patch = (
        PACKAGE_ROOT / "patches" / "clipper2-svg-miter-fallback.patch"
    ).read_text(encoding="utf-8")

    assert "ClipperExecutionLimitError" in patch
    assert "MAX_OUTPUT_POINT_ALLOCATIONS" in patch
    assert "MAX_OUTPUT_RECORD_ALLOCATIONS" in patch
    assert "MAX_INTERSECTION_NODE_ALLOCATIONS" in patch
    assert "MAX_PROCESSED_INTERSECTION_EVENTS" in patch
    assert "NewOutPt" in patch
    assert "RequireIntersectionNodeCapacity" in patch
    assert "RequireProcessedIntersectionCapacity" in patch
    assert "OutputPointAllocationCount" in patch
    assert "OutputRecordAllocationCount" in patch
    assert "IntersectionNodeAllocationCount" in patch
    assert "ProcessedIntersectionEventCount" in patch


def test_parallel_replay_reserves_peak_geometry_resources_before_allocation(
) -> None:
    patch = (
        PACKAGE_ROOT / "patches" / "clipper2-svg-miter-fallback.patch"
    ).read_text(encoding="utf-8")
    budget = (PACKAGE_ROOT / "src" / "complexity_budget.h").read_text(
        encoding="utf-8"
    )
    safety = (PACKAGE_ROOT / "src" / "clipper_safety.h").read_text(
        encoding="utf-8"
    )
    kernel = (PACKAGE_ROOT / "src" / "geometry_kernel.cpp").read_text(
        encoding="utf-8"
    )
    stroke = (PACKAGE_ROOT / "src" / "stroke_expander.cpp").read_text(
        encoding="utf-8"
    )

    assert "class ClipperExecutionGate" in patch
    assert patch.index(
        "RequireExecutionGateCapacity(ClipperExecutionCounter::OutputPoints"
    ) < patch.index("++output_point_allocations_")
    assert "ReleaseExecutionGateReservations();" in patch
    assert "c.SetExecutionGate(execution_gate_);" in patch
    assert "reserveBooleanInputPoints" in budget
    assert "reserveTransientPoints" in budget
    assert "reserveClipperIndexSegments" in budget
    assert "reserveClipperIndexSegments(count)" in safety
    assert "clipper.SetExecutionGate(" in kernel
    assert "offset.SetExecutionGate(" in stroke
    assert "reserveTransientPoints(outputPointUpperBound)" in stroke
    assert "InflatePaths(" not in stroke
    discard = kernel.split(
        "void discardPreparedNormalizations(", 1
    )[1].split("\n}\n", 1)[0]
    assert "swap(batch.commands)" in discard
    assert "batch.clipper_gate.reset()" in discard
    assert kernel.count("catch(const std::bad_alloc&)") >= 3


def test_pinned_clipper_patch_counts_every_processed_intersection() -> None:
    patch = (
        PACKAGE_ROOT / "patches" / "clipper2-svg-miter-fallback.patch"
    ).read_text(encoding="utf-8")

    assert "MAX_INTERSECTION_NODE_ALLOCATIONS" in patch
    assert "MAX_PROCESSED_INTERSECTION_EVENTS" in patch
    assert "RequireIntersectionNodeCapacity();" in patch
    assert "RequireProcessedIntersectionCapacity();" in patch
    assert "IntersectionNodeAllocationCount" in patch
    assert "ProcessedIntersectionEventCount" in patch

    intersect_edges = patch.split(
        "void ClipperBase::IntersectEdges(Active& e1, Active& e2, "
        "const Point64& pt)",
        1,
    )[1].split("//MANAGE OPEN PATH INTERSECTIONS SEPARATELY", 1)[0]
    assert "RequireProcessedIntersectionCapacity();" in intersect_edges


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
